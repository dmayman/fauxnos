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
module only queues and controls playback.
"""

import logging
import subprocess
from typing import List
from urllib.parse import quote


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

    def play(self, items: List[str], loop: bool = False) -> bool:
        """Replace the queue with `items` and start playing.

        loop=True repeats: a single item repeats on its own (MPD `single`
        mode), several items repeat as a playlist.
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
        if not (self._mpc("repeat", repeat) and self._mpc("single", single)):
            return False
        if not self._mpc("play"):
            return False

        self.logger.info(f"Library playing {len(urls)} item(s), loop={loop}: {urls[0]}")
        return True

    def stop(self) -> bool:
        """Stop playback (keeps the queue)."""
        return self._mpc("stop")
