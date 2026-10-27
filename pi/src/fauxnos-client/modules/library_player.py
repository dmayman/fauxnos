#!/usr/bin/env python3
"""
Library Player

Drives this device's own MPD (fauxnos-mpd.service, which plays into
librarysink) via the `mpc` CLI. The MP3s themselves live on the server
and are served at http://<server_host>:8080/library/<path>; MPD streams
them, so nothing is copied to the device.

An item is either a full URL (played as-is — internet radio works too)
or a path relative to the server's library folder, e.g.
"lullabies/twinkle.mp3".

Switching the active source to `library` is the caller's job; this
module only queues and controls playback, and reports what's playing
(watch → status/clients/<id>/library) so the apps can show the track.
"""

import logging
import re
import subprocess
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, unquote

# "[playing] #1/3   0:14/2:00 (11%)"
_STATUS_RE = re.compile(r"^\[(\w+)\]\s+#(\d+)/(\d+)\s+(\d+):(\d+)(?::(\d+))?/(\d+):(\d+)(?::(\d+))?")


def _ms(a, b, c) -> int:
    """mpc's m:ss (or h:mm:ss) as milliseconds."""
    parts = [int(x) for x in (a, b, c) if x is not None]
    seconds = 0
    for x in parts:
        seconds = seconds * 60 + x
    return seconds * 1000


class LibraryPlayer:
    """Queue and control playback on the local MPD."""

    def __init__(self, server_host: str, server_port: int = 8080,
                 mpd_host: str = "localhost", mpd_port: int = 6600):
        self.logger = logging.getLogger(__name__)
        self.server_host = server_host
        self.server_port = server_port
        self.mpd_host = mpd_host
        self.mpd_port = mpd_port

    def resolve(self, item: str) -> str:
        """Turn a library-relative path into the server URL; pass URLs through."""
        item = (item or "").strip()
        if "://" in item:
            return item
        path = quote(item.lstrip("/"))
        return f"http://{self.server_host}:{self.server_port}/library/{path}"

    def _mpc(self, *args: str) -> bool:
        cmd = ["mpc", "-q", "--host", self.mpd_host, "--port", str(self.mpd_port), *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception as e:
            self.logger.error(f"mpc {' '.join(args)} failed to run: {e}")
            return False
        if r.returncode != 0:
            self.logger.error(f"mpc {' '.join(args)} failed: {r.stderr.strip()}")
            return False
        return True

    def play(self, items: List[str], loop: bool = False, shuffle: bool = False) -> bool:
        """Replace the queue with `items` and start playing.

        loop=True repeats: a single item repeats on its own (MPD `single`
        mode), several items repeat as a playlist. shuffle=True plays in
        random order (MPD `random` mode), reshuffled on each pass when
        looping.
        """
        urls = [self.resolve(i) for i in items if i and str(i).strip()]
        if not urls:
            self.logger.error("Library play: no items given")
            return False

        if not self._mpc("clear"):
            return False
        for url in urls:
            if not self._mpc("add", url):
                return False
        repeat = "on" if loop else "off"
        single = "on" if loop and len(urls) == 1 else "off"
        random = "on" if shuffle else "off"
        if not (self._mpc("repeat", repeat) and self._mpc("single", single)
                and self._mpc("random", random)):
            return False
        if not self._mpc("play"):
            return False

        self.logger.info(f"Library playing {len(urls)} item(s), loop={loop}, shuffle={shuffle}: {urls[0]}")
        return True

    def stop(self) -> bool:
        """Stop playback (keeps the queue)."""
        return self._mpc("stop")

    def control(self, action: str) -> bool:
        """Transport: toggle (play/pause), next or prev."""
        if action not in ("toggle", "next", "prev"):
            return False
        return self._mpc(action)

    def seek(self, position_ms: int) -> bool:
        """Jump to a position in the current song."""
        return self._mpc("seek", str(max(0, int(position_ms)) // 1000))

    def library_path(self, url: str) -> Optional[str]:
        """The library-relative path of a server URL, or None for other URLs."""
        prefix = f"http://{self.server_host}:{self.server_port}/library/"
        return unquote(url[len(prefix):]) if url.startswith(prefix) else None

    def now_playing(self) -> Dict:
        """What MPD is doing: {state, file, path, position, queue_length,
        elapsed_ms, duration_ms, updated_at}. state is play, pause or stop."""
        state = {"state": "stop", "file": None, "path": None, "position": None,
                 "queue_length": 0, "elapsed_ms": 0, "duration_ms": None,
                 "updated_at": int(time.time() * 1000)}
        try:
            r = subprocess.run(
                ["mpc", "--host", self.mpd_host, "--port", str(self.mpd_port),
                 "-f", "%file%", "status"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            self.logger.debug(f"mpc status failed: {e}")
            return state
        lines = r.stdout.splitlines()
        if r.returncode != 0 or len(lines) < 2:
            return state  # stopped (or MPD down): only the options line
        m = _STATUS_RE.match(lines[1])
        if not m:
            return state
        state.update(
            state="play" if m.group(1) == "playing" else "pause",
            file=lines[0].strip(),
            path=self.library_path(lines[0].strip()),
            position=int(m.group(2)),
            queue_length=int(m.group(3)),
            elapsed_ms=_ms(m.group(4), m.group(5), m.group(6)),
            duration_ms=_ms(m.group(7), m.group(8), m.group(9)) or None,
        )
        return state

    def watch(self, publish: Callable[[Dict], None], stop_event=None):
        """Publish now_playing() now and on every MPD player/queue change.

        Blocks: run it on its own thread. `mpc idle` returns on each change;
        if MPD isn't up yet (it starts alongside us), retry every few seconds.
        """
        last = None
        while stop_event is None or not stop_event.is_set():
            current = self.now_playing()
            key = {k: v for k, v in current.items() if k != "updated_at"}
            if key != last:
                publish(current)
                last = key
            try:
                r = subprocess.run(
                    ["mpc", "--host", self.mpd_host, "--port", str(self.mpd_port),
                     "idle", "player", "playlist"],
                    capture_output=True, text=True, timeout=600,
                )
                if r.returncode != 0:
                    time.sleep(3)
            except subprocess.TimeoutExpired:
                pass  # no change in 10 minutes; re-check and idle again
            except Exception as e:
                self.logger.debug(f"mpc idle failed: {e}")
                time.sleep(3)
