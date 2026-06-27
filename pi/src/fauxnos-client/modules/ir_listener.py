#!/usr/bin/env python3
"""
IR Listener — hardware-remote support for the fauxnos client.

Drives an `ir-keytable -t -s rc0` subprocess and dispatches matched
scancodes to caller-supplied command handlers. Supports a learning
mode where the next scancode received is captured + persisted as the
new mapping for a given command.

Architecture rationale
----------------------
We use `ir-keytable -t` (the kernel-tooling binary that ships with the
`ir-keytable` apt package) as our single source of truth for IR
events. Its stdout format is stable across rc-core versions and gives
us both the protocol name AND the scancode on one line — which we
want for the UI's "NEC 0x1FE807F" display. Going through python-evdev
would give the scancode but not the protocol, requiring a second read
path; routing every event through subprocess line-parse is plenty
fast for IR (≤10 Hz from a real remote).

Why a thread and not asyncio: the rest of the fauxnos_client.py
daemon is synchronous (signal-based shutdown, while-True sleep loop),
so a background reader thread fits naturally and keeps the IR work
out of the daemon's hot path.

State and persistence
---------------------
- Enabled flag + per-command mappings live in client_state.json
  via StateManager.get_ir / set_ir_enabled / set_ir_mapping.
- ir.enabled controls whether the subprocess runs at all. When the
  feature is off, no subprocess is spawned and no input group access
  is needed.
- Mappings are loaded into an in-process cache at start() and on
  every mutation, so the hot path (idle dispatch) doesn't hit disk
  per IR event.

Threading and safety
--------------------
- One reader thread runs the subprocess + parses stdout.
- One optional watchdog thread enforces the learn-timeout.
- A single threading.Lock guards mode transitions (idle ↔ learning)
  and the learn callbacks. Dispatching command handlers happens OFF
  the lock so a slow handler can't deadlock a cancel.
"""

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Canonical command IDs. Must match the server's persistence layer and
# the web UI's row labels. Order is the source-cycle order if the
# 'source' command ends up needing to iterate (it doesn't here — that's
# the SourceManager's job — but kept ordered for stability).
COMMAND_IDS = [
    'volume_up',
    'volume_down',
    'mute',
    'source_cycle',
    'source_analog',
    'play_pause',
    'next',
    'previous',
]


# ir-keytable -t output line we care about, e.g.:
#   1746850543.123456: lirc protocol(nec): scancode = 0x1fe807f
# Some kernels emit the protocol name in CAPS (RC-5 etc); accept both.
_SCANCODE_RE = re.compile(
    r'lirc protocol\((?P<protocol>[\w-]+)\):\s*scancode\s*=\s*(?P<scancode>0x[0-9a-fA-F]+)',
    re.IGNORECASE,
)


class IRListener:
    """
    Drives ir-keytable, routes scancodes to command handlers in idle
    mode, captures-and-persists in learning mode.

    Args:
        state_manager: StateManager for ir state persistence.
        command_handlers: Map of {command_id: callable()} for the seven
            canonical commands. Missing keys = command logged-and-ignored
            (useful for staging the listener before transport-control is
            wired in).
        on_learn_event: Optional notifier called on learn lifecycle
            transitions: on_learn_event(event, payload_dict). Events:
            'started'   {command_id, deadline_ms}
            'captured'  {command_id, protocol, scancode}
            'timeout'   {command_id}
            'cancelled' {command_id}
            Used by MQTT plumbing to mirror the state to the UI.
        device_name: Fallback rc-core device name when auto-detection
            fails. We always prefer to discover the right device at
            start time by scanning /sys/class/rc/rc*/uevent for
            DRV_NAME=gpio_ir_recv — the Pi's HDMI CEC also shows up
            as an rc-core device and we don't want to enable IR
            decoders on it. The fallback is only used if no gpio_ir
            receiver is registered (e.g. overlay not loaded).
    """

    # Debounce windows in seconds.
    # Idle: a real remote sends the same scancode 3–5× per press; we
    # only want to fire the handler once per press.
    REPEAT_WINDOW_S = 0.25
    # Learn: after capture, ignore the same code for a short cooldown
    # so the trailing repeats don't immediately fire as a real action.
    LEARN_COOLDOWN_S = 0.30

    def __init__(
        self,
        state_manager,
        command_handlers: Dict[str, Callable[[], None]],
        on_learn_event: Optional[Callable[[str, dict], None]] = None,
        device_name: str = 'rc0',
    ):
        self.state_manager = state_manager
        self.command_handlers = command_handlers
        self.on_learn_event = on_learn_event
        self.device_name = device_name

        # Subprocess + thread handles
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        # Mode state — guarded by _lock.
        self._lock = threading.Lock()
        self._learn_command: Optional[str] = None
        self._learn_deadline: float = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None

        # In-process cache of the on-disk mapping. Refreshed on set/clear
        # so the hot path doesn't read state_manager per IR event.
        # Shape: {cmd_id: (protocol_lower, scancode_lower)}.
        self._mapping_cache: Dict[str, tuple] = {}
        self._load_mapping_cache()

        # Per-command timestamp of the last dispatch, for idle debounce.
        self._last_dispatch_ts: Dict[str, float] = {}

        # Brief post-capture cooldown so repeats of the captured code
        # don't immediately trigger the (now-learned) action.
        self._cooldown_until: Dict[tuple, float] = {}

    # -------- public API --------

    def start(self):
        """
        Start the listener if ir.enabled is True. No-op if the feature
        is disabled or ir-keytable is missing (logged at warning level).
        """
        ir = self.state_manager.get_ir()
        if not ir.get('enabled'):
            logger.info("IR listener: feature disabled, not starting")
            return
        self._start_subprocess()

    def stop(self):
        """Stop the listener if running. Idempotent."""
        self._stop_subprocess()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def set_enabled(self, enabled: bool):
        """
        Persist the enabled flag and start/stop the subprocess to match.
        Safe to call from any thread.
        """
        self.state_manager.set_ir_enabled(enabled)
        if enabled and not self.is_running():
            self._start_subprocess()
        elif not enabled and self.is_running():
            self._stop_subprocess()

    def get_mapping(self) -> Dict[str, Optional[Dict[str, str]]]:
        """
        Return the persisted {command_id: {"protocol","scancode"} | None}
        map. Read from state_manager (source of truth, not the cache —
        cache is only for the hot scancode→handler lookup direction).
        """
        return self.state_manager.get_ir().get('mappings', {})

    def set_command(self, command_id: str, protocol: str, scancode: str):
        """Persist a manually-set mapping and refresh the lookup cache."""
        self.state_manager.set_ir_mapping(command_id, protocol, scancode)
        self._load_mapping_cache()

    def clear_command(self, command_id: str):
        """Forget a mapping. Listener-side effect: the code no longer fires."""
        self.state_manager.set_ir_mapping(command_id, None, None)
        self._load_mapping_cache()

    def start_learning(self, command_id: str, timeout_s: float = 15.0) -> bool:
        """
        Enter learning mode for `command_id`. The next decoded scancode
        becomes its new mapping. Returns False if another learn is
        already in flight or the listener isn't running.
        """
        if command_id not in COMMAND_IDS:
            logger.warning(f"IR learn: unknown command_id {command_id!r}")
            return False
        if not self.is_running():
            logger.warning("IR learn: listener not running; enable IR first")
            return False
        with self._lock:
            if self._learn_command is not None:
                logger.warning(
                    f"IR learn: rejected {command_id} — already learning {self._learn_command}"
                )
                return False
            self._learn_command = command_id
            self._learn_deadline = time.monotonic() + max(1.0, timeout_s)
        logger.info(f"IR learn: started for {command_id} (timeout {timeout_s:.0f}s)")
        self._notify_learn('started', {
            'command_id': command_id,
            'deadline_ms': int(timeout_s * 1000),
        })
        # Watchdog enforces the timeout — fires 'timeout' if no scancode
        # arrives before _learn_deadline.
        self._watchdog_thread = threading.Thread(
            target=self._learn_watchdog_loop,
            args=(command_id,),
            name=f"ir-learn-watchdog-{command_id}",
            daemon=True,
        )
        self._watchdog_thread.start()
        return True

    def cancel_learning(self) -> bool:
        """Abort an in-flight learn, if any. Returns True if there was one."""
        with self._lock:
            cmd = self._learn_command
            self._learn_command = None
            self._learn_deadline = 0.0
        if cmd is None:
            return False
        logger.info(f"IR learn: cancelled for {cmd}")
        self._notify_learn('cancelled', {'command_id': cmd})
        return True

    # -------- subprocess management --------

    @staticmethod
    def _find_rc_device(target_driver: str = 'gpio_ir_recv') -> Optional[str]:
        """
        Scan /sys/class/rc/rc* for the device whose driver is
        gpio_ir_recv. Returns the device name (e.g. 'rc0' or 'rc1')
        or None if no matching device exists.

        Rationale: on a Pi, /sys/class/rc/ may also contain the HDMI
        CEC receiver (DRV_NAME=cec). Which rcN gets which driver depends
        on probe order, so we can't hardcode rc0 across all hardware.
        """
        rc_root = Path('/sys/class/rc')
        if not rc_root.exists():
            return None
        for rc_path in sorted(rc_root.glob('rc*')):
            uevent = rc_path / 'uevent'
            try:
                for line in uevent.read_text().splitlines():
                    if line.startswith('DRV_NAME=') and \
                       line.split('=', 1)[1].strip() == target_driver:
                        return rc_path.name
            except OSError:
                continue
        return None

    def _start_subprocess(self):
        if self.is_running():
            return
        if shutil.which('ir-keytable') is None:
            logger.warning("IR listener: ir-keytable not installed; cannot start")
            return
        # Resolve which rcN is actually the gpio_ir_recv. Falls back to
        # the constructor default if scanning failed — preserves backward
        # compat for setups where the user explicitly set device_name.
        resolved = self._find_rc_device() or self.device_name
        if resolved != self.device_name:
            logger.info(
                f"IR listener: auto-detected rc device {resolved!r} "
                f"(fallback was {self.device_name!r})"
            )
        # -t: test mode (just print events, don't modify protocols).
        # -s <dev>: select the rc-core device. Protocol enabling is
        # done at boot by fauxnos-ir-decoders.service (see install.sh).
        #
        # `stdbuf -oL`: force ir-keytable's stdout to line-buffered.
        # Otherwise glibc applies full-block buffering when stdout is
        # a pipe (our subprocess.Popen pipe), and scancodes accumulate
        # in an 8KB buffer until either the buffer fills or the process
        # exits. Verified empirically on fauxnos000 (2026-05-10): without
        # stdbuf, 28 button presses queued for ~29 seconds then dumped in
        # a 14ms burst on SIGTERM. With stdbuf each event arrives within
        # one frame of the actual button press. Without this, learn mode
        # would always time out before the first scancode arrived.
        cmd = ['stdbuf', '-oL', 'ir-keytable', '-t', '-s', resolved]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError:
            logger.error("IR listener: ir-keytable not found on PATH")
            self._proc = None
            return
        except PermissionError as e:
            logger.error(
                f"IR listener: permission denied launching ir-keytable ({e}); "
                f"is the user in the 'input' group?"
            )
            self._proc = None
            return
        self._stop_evt.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name='ir-listener-reader',
            daemon=True,
        )
        self._reader_thread.start()
        logger.info(f"IR listener: started ({' '.join(cmd)}, pid={self._proc.pid})")

        # Re-arm kernel protocol decoders after test mode resets them.
        #
        # Why: `ir-keytable -t -s rcN` switches the device into LIRC
        # test mode, which clears the kernel rc-core protocol mask to
        # defaults (e.g. just `rc-6` on Pi). Any protocols set by the
        # boot-time fauxnos-ir-decoders.service get stripped ~tens of
        # ms after our subprocess starts, so a NEC remote that worked
        # at boot stops emitting scancodes for the daemon to read.
        #
        # The fix re-runs the same /usr/local/bin/fauxnos-ir-enable-
        # decoders.sh that the boot service uses, after a brief delay
        # so test-mode init has settled. Threaded so a sudoers misconfig
        # can't block subprocess startup; idempotent so it's safe to
        # repeat across listener restarts. Permission to call this
        # script without a password is provisioned by install.sh via
        # /etc/sudoers.d/fauxnos-ir.
        threading.Thread(
            target=self._rearm_protocols,
            name='ir-listener-rearm',
            daemon=True,
        ).start()

    # Path to the install.sh-provisioned helper. Kept as a class
    # constant so tests can monkeypatch a fake path without touching
    # /usr/local/bin.
    _REARM_SCRIPT = '/usr/local/bin/fauxnos-ir-enable-decoders.sh'
    # Delay before the rearm shell-out. The strip-on-start race is
    # ~tens of ms wide in practice (measured on fauxnos000 2026-05-13);
    # a one-second delay puts us comfortably past it without the user
    # perceiving a startup lag.
    _REARM_DELAY_S = 1.0

    def _rearm_protocols(self):
        """
        Re-enable the kernel rc-core decoders the test-mode spawn just
        stripped. Soft-fails on missing sudo / missing script / missing
        sudoers grant — IR will still work for whichever protocols the
        device defaulted to (typically rc-6), and the failure mode is
        identical to "operator hasn't run the latest install.sh yet".
        """
        # Don't run if the subprocess died during the delay window
        # (e.g. user toggled IR off immediately after enabling it).
        if not self._wait_settle():
            return
        if not Path(self._REARM_SCRIPT).is_file():
            logger.warning(
                "IR listener: rearm script %s not present; "
                "kernel decoders left at boot defaults",
                self._REARM_SCRIPT,
            )
            return
        # sudo -n: never prompt. If the sudoers grant is missing this
        # exits with non-zero and we log a warning rather than hang.
        try:
            result = subprocess.run(
                ['sudo', '-n', self._REARM_SCRIPT],
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except FileNotFoundError:
            logger.warning("IR listener: rearm skipped — sudo not on PATH")
            return
        except subprocess.TimeoutExpired:
            logger.warning("IR listener: rearm timed out after 10s")
            return
        except Exception as e:
            logger.warning(f"IR listener: rearm failed to spawn: {e}")
            return
        if result.returncode == 0:
            # Script echoes its action on stdout — surface it to make
            # the boot/restart trail self-documenting.
            msg = (result.stdout or '').strip().splitlines()
            logger.info(
                "IR listener: rearmed kernel decoders — %s",
                msg[-1] if msg else "(no output)",
            )
        else:
            logger.warning(
                "IR listener: rearm exited %d; stderr=%r",
                result.returncode,
                (result.stderr or '').strip(),
            )

    def _wait_settle(self) -> bool:
        """
        Sleep _REARM_DELAY_S but bail early if shutdown is requested.
        Returns True if the subprocess is still alive after the wait.
        """
        self._stop_evt.wait(self._REARM_DELAY_S)
        if self._stop_evt.is_set():
            return False
        return self.is_running()

    def _stop_subprocess(self):
        self._stop_evt.set()
        # Tear down any in-flight learn so the watchdog exits cleanly.
        with self._lock:
            cmd_in_flight = self._learn_command
            self._learn_command = None
            self._learn_deadline = 0.0
        if cmd_in_flight:
            self._notify_learn('cancelled', {'command_id': cmd_in_flight})

        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("IR listener: ir-keytable didn't terminate; killing")
                self._proc.kill()
                try:
                    self._proc.wait(timeout=1.0)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"IR listener: error stopping subprocess: {e}")
            self._proc = None

        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        self._reader_thread = None
        logger.info("IR listener: stopped")

    # -------- reader thread --------

    def _reader_loop(self):
        """
        Drain ir-keytable stdout, dispatch or capture per line.
        Exits when the subprocess terminates or _stop_evt fires.
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._stop_evt.is_set():
                    break
                m = _SCANCODE_RE.search(line)
                if not m:
                    continue
                protocol = m.group('protocol').lower()
                scancode = m.group('scancode').lower()
                self._on_scancode(protocol, scancode)
        except Exception as e:
            logger.error(f"IR listener: reader thread crashed: {e}", exc_info=True)
        finally:
            logger.debug("IR listener: reader thread exiting")

    def _on_scancode(self, protocol: str, scancode: str):
        """Decide whether this event is a learn-capture or a normal dispatch."""
        now = time.monotonic()

        # Snapshot mode under the lock; do the actual work outside it.
        with self._lock:
            learn_cmd = self._learn_command

        if learn_cmd is not None:
            self._capture_for_learn(learn_cmd, protocol, scancode)
            return

        # Honor post-capture cooldown (avoid the captured code's
        # trailing repeats triggering the now-learned action).
        key = (protocol, scancode)
        cooldown_until = self._cooldown_until.get(key, 0.0)
        if cooldown_until > now:
            return

        cmd_id = self._lookup_command(protocol, scancode)
        if cmd_id is None:
            logger.debug(f"IR: unmatched {protocol} {scancode}")
            return

        # Idle debounce per command — only fire on the first repeat in
        # a burst.
        last = self._last_dispatch_ts.get(cmd_id, 0.0)
        if (now - last) < self.REPEAT_WINDOW_S:
            return
        self._last_dispatch_ts[cmd_id] = now

        self._dispatch(cmd_id)

    def _capture_for_learn(self, command_id: str, protocol: str, scancode: str):
        """Stash the (protocol, scancode) pair as command_id's new mapping."""
        # Atomically clear the learning state so a fast double-press
        # doesn't get captured into the same slot twice.
        with self._lock:
            if self._learn_command != command_id:
                # State changed under us (cancel or another capture won)
                return
            self._learn_command = None
            self._learn_deadline = 0.0

        self.set_command(command_id, protocol, scancode)
        # Post-capture cooldown: ignore this scancode briefly so the
        # remote's repeat frames don't trigger the new mapping immediately.
        self._cooldown_until[(protocol, scancode)] = (
            time.monotonic() + self.LEARN_COOLDOWN_S
        )
        logger.info(f"IR learn: captured {command_id} → {protocol} {scancode}")
        self._notify_learn('captured', {
            'command_id': command_id,
            'protocol': protocol,
            'scancode': scancode,
        })

    def _dispatch(self, command_id: str):
        """Call the registered handler for a matched command."""
        handler = self.command_handlers.get(command_id)
        if handler is None:
            logger.info(f"IR: matched {command_id} but no handler registered")
            return
        try:
            handler()
        except Exception as e:
            logger.error(f"IR: handler for {command_id} raised: {e}", exc_info=True)

    # -------- learning watchdog --------

    def _learn_watchdog_loop(self, command_id: str):
        """Fire 'timeout' if the learn deadline passes without a capture."""
        while not self._stop_evt.is_set():
            with self._lock:
                if self._learn_command != command_id:
                    return  # capture or cancel won the race
                deadline = self._learn_deadline
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Sleep no more than 250ms so cancels are responsive.
            time.sleep(min(0.25, remaining))

        # Timed out — clear state if still ours and notify.
        with self._lock:
            if self._learn_command != command_id:
                return
            self._learn_command = None
            self._learn_deadline = 0.0
        logger.info(f"IR learn: timed out for {command_id}")
        self._notify_learn('timeout', {'command_id': command_id})

    # -------- helpers --------

    def _load_mapping_cache(self):
        """Refresh in-process scancode → command lookup table."""
        ir = self.state_manager.get_ir()
        mappings = ir.get('mappings') or {}
        cache: Dict[str, tuple] = {}
        for cmd_id, m in mappings.items():
            if not m:
                continue
            proto = str(m.get('protocol', '')).lower()
            scan = str(m.get('scancode', '')).lower()
            if proto and scan:
                cache[cmd_id] = (proto, scan)
        self._mapping_cache = cache

    def _lookup_command(self, protocol: str, scancode: str) -> Optional[str]:
        """
        Return the command_id mapped to (protocol, scancode), or None.

        Match policy: scancode equality wins regardless of protocol.
        This is what users expect ("my remote's volume-up button"
        works no matter what the decoder reports it as on a given
        kernel) and avoids false negatives when ir-keytable labels a
        protocol differently between captures (rare but observed on
        edge protocols).
        """
        for cmd_id, (_p, s) in self._mapping_cache.items():
            if s == scancode:
                return cmd_id
        return None

    def _notify_learn(self, event: str, payload: dict):
        if self.on_learn_event is None:
            return
        try:
            self.on_learn_event(event, payload)
        except Exception as e:
            logger.error(f"IR: on_learn_event raised: {e}", exc_info=True)
