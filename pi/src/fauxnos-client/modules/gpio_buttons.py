#!/usr/bin/env python3
"""
GPIO Button Handler — hardware-button support for the fauxnos client.

Drives a small set of momentary push-buttons wired to GPIO pins on the
Pi header and dispatches presses to the same command-handler map that
the IR listener uses (volume_up, volume_down, source_cycle, ...). The
handlers themselves play the per-action feedback sound BEFORE the
action — see fauxnos_client._ir_volume_up / _ir_source_cycle — so a
press feels identical whether it came from the remote or a button.

Hardware
--------
Buttons are momentary SPST, wired between a GPIO pin and GND. We
enable the Pi's internal ~50k pull-up; pressed = LOW, idle = HIGH.
Zero external components needed.

Pin defaults (clear of HiFiBerry I2S/I2C and gpio-ir-recv on GPIO 17):
  GPIO 5  / header pin 29 → volume_up
  GPIO 6  / header pin 31 → volume_down
  GPIO 26 / header pin 37 → source_cycle
  GND    / header pin 39  (common)

Auto-repeat on hold
-------------------
volume_{up,down} set `hold_repeat: true` in config — gpiozero's
hold_repeat re-fires when_held every `hold_time` while the button is
held, so a held button ramps the volume the same way a held IR button
does. source_cycle does NOT auto-repeat (no when_held wired) — cycling
through sources rapidly is bad UX.

Soft failure
------------
Missing gpiozero or a GPIO that's already claimed by something else
(gpio-ir overlay, HiFiBerry I2S/I2C, another buttons entry typoed to
the same pin) is logged at warning/error level and the handler comes
up degraded rather than crashing the daemon. Important on shared
overlays where a future config typo could otherwise take the client
offline.
"""

import logging
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)


class GPIOButtonHandler:
    """
    Wires GPIO buttons to caller-supplied command handlers.

    Mirrors IRListener's public surface (start / stop / is_running)
    so the daemon can treat both inputs uniformly. Each Button is
    created in start() and released in stop(); the handler object
    can be re-started after a stop.

    Args:
        buttons_config: ButtonsConfig dataclass from ConfigManager.
            enabled=False or empty pins=[] → start() is a no-op.
        command_handlers: Same {command_id: callable()} map the IR
            listener uses. Reusing it means buttons play the same
            feedback sounds and publish the same MQTT updates as
            a remote press — no duplicated code paths.
    """

    def __init__(
        self,
        buttons_config,
        command_handlers: Dict[str, Callable[[], None]],
    ):
        self.config = buttons_config
        self.command_handlers = command_handlers
        # list of gpiozero.Button instances — populated in start(),
        # cleared in stop(). Kept as a list (not a dict keyed by pin)
        # because the only operation we do on it after start is close().
        self._buttons: List = []
        self._running = False

    def start(self):
        """
        Claim the configured GPIO pins and wire callbacks.

        No-op cases (each logged at info level so the operator can
        see why nothing fired on a button press):
          - buttons.enabled = false
          - no pin entries configured
          - gpiozero not importable (apt package missing)

        Per-pin failures (gpio already claimed, etc.) are logged at
        error level and the loop continues — other buttons still
        come up.
        """
        if not self.config.enabled:
            logger.info("GPIO buttons: disabled in config, not starting")
            return
        if not self.config.pins:
            logger.info("GPIO buttons: no pins configured, not starting")
            return

        # Import inside start() so the daemon boots cleanly on devices
        # that don't have python3-gpiozero installed yet (older client
        # images pre-dating the install.sh change).
        try:
            from gpiozero import Button
        except ImportError as e:
            logger.warning(
                "GPIO buttons: gpiozero not available (%s); "
                "install python3-gpiozero to enable hardware buttons",
                e,
            )
            return

        bounce_s = self.config.bounce_time_ms / 1000.0
        hold_s = self.config.hold_time_ms / 1000.0

        for pin_cfg in self.config.pins:
            handler = self.command_handlers.get(pin_cfg.command)
            if handler is None:
                logger.warning(
                    "GPIO buttons: GPIO%d → '%s' has no handler, skipping",
                    pin_cfg.gpio, pin_cfg.command,
                )
                continue

            try:
                btn = Button(
                    pin=pin_cfg.gpio,
                    pull_up=True,
                    bounce_time=bounce_s,
                    hold_time=hold_s,
                    hold_repeat=pin_cfg.hold_repeat,
                )
            except Exception as e:
                # Pin already claimed (gpio-ir overlay, HiFiBerry I2S/I2C,
                # duplicate entry in config). Log and skip rather than
                # crashing — keeps the other buttons working.
                logger.error(
                    "GPIO buttons: failed to claim GPIO%d for '%s': %s",
                    pin_cfg.gpio, pin_cfg.command, e,
                )
                continue

            # when_pressed fires once on the falling edge (press).
            # when_held fires after hold_time, then every hold_time
            # while held (hold_repeat=True). For source_cycle we
            # deliberately leave when_held unset so cycling stays
            # one-step-per-press.
            btn.when_pressed = handler
            if pin_cfg.hold_repeat:
                btn.when_held = handler
            self._buttons.append(btn)

            logger.info(
                "GPIO buttons: GPIO%d → %s (hold_repeat=%s)",
                pin_cfg.gpio, pin_cfg.command, pin_cfg.hold_repeat,
            )

        if self._buttons:
            self._running = True
            logger.info("GPIO buttons: %d button(s) live", len(self._buttons))
        else:
            logger.warning("GPIO buttons: no buttons came up — all entries failed")

    def stop(self):
        """Release all claimed GPIOs. Idempotent."""
        for btn in self._buttons:
            try:
                btn.close()
            except Exception as e:
                logger.warning("GPIO buttons: error closing button: %s", e)
        self._buttons = []
        self._running = False

    def is_running(self) -> bool:
        return self._running
