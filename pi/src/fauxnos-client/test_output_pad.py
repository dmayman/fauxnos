#!/usr/bin/env python3
"""
Test the EVC output-pad state machine in SourceManager.

The pad is driven by a *retained* MQTT config topic, so the same payload
replays on every reconnect — and the user can retune the pad without ever
touching the `enabled` flag. Those two facts are what make this more than
an assignment, so they're what's asserted here.

Run: python3 test_output_pad.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.source_manager import SourceManager


def _fresh():
    """A SourceManager with only the pad-relevant state.

    __new__ skips __init__ so we don't need PulseAudio, snapcast, a broker
    or a config file just to exercise a state machine. The enabled-transition
    branch will reach for self.snapcast and raise, but that's inside
    set_external_volume_state's own try/except — the pad path runs first
    and is unaffected.
    """
    import logging
    sm = SourceManager.__new__(SourceManager)
    sm.logger = logging.getLogger("test")
    sm.logger.setLevel(logging.CRITICAL)  # mute that expected warning
    sm.external_volume_enabled = False
    sm.output_pad_db = None
    sm.applied = []
    sm._apply_output_pad = sm.applied.append
    return sm


def test_first_message_always_applies():
    """Fresh boot: the mixer may hold a stale stored value, so even a
    pad of 0 has to be written once. The None sentinel is what buys this."""
    sm = _fresh()
    sm.set_external_volume_state(True, 0)
    assert sm.applied == [0], sm.applied


def test_applies_and_is_idempotent_under_replay():
    sm = _fresh()
    sm.set_external_volume_state(True, -24)
    assert sm.applied == [-24], sm.applied
    # Retained payload re-fires on every subscribe — must not re-shell amixer.
    sm.set_external_volume_state(True, -24)
    sm.set_external_volume_state(True, -24)
    assert sm.applied == [-24], sm.applied


def test_retune_without_toggling_enabled():
    """The regression an `enabled`-only guard would cause: every pad edit
    after the first silently swallowed."""
    sm = _fresh()
    sm.set_external_volume_state(True, -24)
    sm.set_external_volume_state(True, -18)
    sm.set_external_volume_state(True, -30)
    assert sm.applied == [-24, -18, -30], sm.applied


def test_positive_pad_clamped():
    """This control only ever cuts — a boost would push the DAC past
    full scale, which is the exact failure it exists to prevent."""
    sm = _fresh()
    sm.set_external_volume_state(True, 6)
    assert sm.applied == [0], sm.applied


def test_disable_restores_unity():
    """Turning external off hands attenuation back to the local chain;
    leaving the pad in would stack on top of it."""
    sm = _fresh()
    sm.set_external_volume_state(True, -24)
    sm.set_external_volume_state(False, -24)
    assert sm.applied == [-24, 0], sm.applied


def test_pad_ignored_while_external_off():
    sm = _fresh()
    sm.set_external_volume_state(False, -24)
    assert sm.applied == [0], sm.applied


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print(f"✓ {name}")
    print("\nAll output-pad tests passed.")
