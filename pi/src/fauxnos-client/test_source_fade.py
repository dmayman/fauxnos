#!/usr/bin/env python3
"""
Test opt-in crossfades and on_enter/on_leave hooks in SourceManager.

Covers: an instant switch stays instant; a fade ramps both sinks and
defers the outgoing source's leave hooks to the end; a switch or a
volume change mid-fade lands the fade at once; switching back to the
source being faded away from skips its leave hooks; daemon restart
does not mute the restored source's sink.

Run: python3 test_source_fade.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.config_manager import SourceConfig
from modules.source_manager import SourceManager


class FakePulse:
    def __init__(self):
        self.levels = {}
        self.writes = []  # (sink, level) in order
        self.lock = threading.Lock()

    def set_sink_volume(self, sink, volume):
        with self.lock:
            self.levels[sink] = volume
            self.writes.append((sink, volume))
        return True

    def mute_sink(self, sink):
        return self.set_sink_volume(sink, 0)

    def get_sink_volume(self, sink):
        return self.levels.get(sink)

    def set_loopback_calibration(self, role, value):
        return True


class FakeState:
    def __init__(self, current=None):
        self.current = current

    def save_state(self, current, volumes):
        self.current = current

    def get_current_source(self):
        return self.current

    def get_pa_calibration(self, source_id):
        return None


class FakeConfig:
    def __init__(self, sources):
        self.sources = {s.id: s for s in sources}

    def get_source(self, sid):
        return self.sources.get(sid)

    def get_internal_sources(self):
        return {k: v for k, v in self.sources.items() if v.type == 'internal'}


SOURCES = [
    SourceConfig(id='airplay', label='AirPlay', type='internal', sink='airplaysink',
                 volume_controller='external', on_leave_command='leave-airplay'),
    SourceConfig(id='library', label='Library', type='internal', sink='librarysink',
                 volume_controller='self', on_leave_command='leave-library'),
    SourceConfig(id='noise', label='Noise', type='internal', sink='noisesink',
                 volume_controller='self', on_enter_command='enter-noise',
                 on_leave_command='leave-noise'),
]


def make(current=None, volumes=None):
    sm = SourceManager.__new__(SourceManager)  # skip real PA/snapcast/state
    import logging
    sm.logger = logging.getLogger("test")
    sm.config_manager = FakeConfig(SOURCES)
    sm.pulse = FakePulse()
    sm.state_manager = FakeState(current)
    sm.go_librespot = None
    sm.external_volume_enabled = False
    sm.current_source = current
    sm.source_volumes = {'airplay': 50, 'library': 60, 'noise': 40}
    sm.source_volumes.update(volumes or {})
    sm._fade_lock = threading.Lock()
    sm._fade_gen = 0
    sm._fade = None
    sm.hooks = []
    sm._spawn_hook = lambda sid, hook, cmd: sm.hooks.append(cmd)
    return sm


def test_instant_switch_unchanged():
    sm = make(current='library')
    sm.pulse.levels = {'librarysink': 60}
    assert sm.switch_source('noise')
    assert sm.current_source == 'noise'
    assert sm.pulse.levels['librarysink'] == 0
    assert sm.pulse.levels['noisesink'] == 40
    assert sm.hooks == ['leave-library', 'enter-noise'], sm.hooks
    print("ok: instant switch mutes old, sets new, runs leave then enter")


def test_fade_ramps_and_defers_leave():
    sm = make(current='library')
    sm.FADE_STEP_MS = 20
    sm.pulse.levels = {'librarysink': 60, 'noisesink': 0}
    t0 = time.monotonic()
    assert sm.switch_source('noise', fade_ms=200)
    assert time.monotonic() - t0 < 0.05, "switch must return at once"
    assert sm.current_source == 'noise'
    assert sm.hooks == ['enter-noise'], "leave hooks wait for the fade"
    time.sleep(0.1)
    mid_old, mid_new = sm.pulse.levels['librarysink'], sm.pulse.levels['noisesink']
    assert 0 < mid_old < 60 and 0 < mid_new < 40, (mid_old, mid_new)
    time.sleep(0.25)
    assert sm._fade is None
    assert sm.pulse.levels['librarysink'] == 0
    assert sm.pulse.levels['noisesink'] == 40
    assert sm.hooks == ['enter-noise', 'leave-library'], sm.hooks
    # the incoming sink only ever rises, the outgoing only ever falls
    new_writes = [v for s, v in sm.pulse.writes if s == 'noisesink']
    assert new_writes == sorted(new_writes), new_writes
    print(f"ok: fade ramps both sinks (mid {mid_old}/{mid_new}), leave hook at the end")


def test_switch_mid_fade_lands_it():
    sm = make(current='library')
    sm.FADE_STEP_MS = 20
    sm.pulse.levels = {'librarysink': 60}
    sm.switch_source('noise', fade_ms=1000)
    time.sleep(0.1)
    assert sm.switch_source('airplay')
    time.sleep(0.1)
    assert sm.current_source == 'airplay'
    assert sm.pulse.levels['librarysink'] == 0
    assert sm.pulse.levels['noisesink'] == 0
    assert sm.pulse.levels['airplaysink'] == 100
    assert sm.hooks == ['enter-noise', 'leave-library', 'leave-noise'], sm.hooks
    n = len(sm.pulse.writes)
    time.sleep(0.2)
    assert len(sm.pulse.writes) == n, "retired fade thread must not write again"
    print("ok: a switch mid-fade lands the fade, then switches; no stale steps")


def test_switch_back_mid_fade_skips_leave():
    sm = make(current='library')
    sm.FADE_STEP_MS = 20
    sm.pulse.levels = {'librarysink': 60}
    sm.switch_source('noise', fade_ms=1000)
    time.sleep(0.1)
    sm.switch_source('library')
    time.sleep(0.05)
    assert sm.current_source == 'library'
    assert sm.pulse.levels['librarysink'] == 60
    assert sm.pulse.levels['noisesink'] == 0
    assert 'leave-library' not in sm.hooks, sm.hooks
    print("ok: switching back mid-fade doesn't run the returning source's leave hook")


def test_volume_mid_fade_lands_it():
    sm = make(current='library')
    sm.FADE_STEP_MS = 20
    sm.pulse.levels = {'librarysink': 60}
    sm.switch_source('noise', fade_ms=1000)
    time.sleep(0.1)
    assert sm.set_volume(25)
    time.sleep(0.1)
    assert sm._fade is None
    assert sm.pulse.levels['noisesink'] == 25
    assert sm.pulse.levels['librarysink'] == 0
    print("ok: a volume change mid-fade lands the fade at the new level")


def test_fade_falls_back_to_instant_on_same_sink():
    sm = make(current='noise')
    assert not SourceManager._can_fade(SOURCES[2], SOURCES[2])
    assert not SourceManager._can_fade(None, SOURCES[2])
    assert SourceManager._can_fade(SOURCES[1], SOURCES[2])
    print("ok: fades only between two internal sources on different sinks")


def test_restart_keeps_restored_sink_unmuted():
    sm = make(current=None)
    sm.state_manager = FakeState(current='noise')
    sm.resync_go_librespot_volume = lambda: None
    sm.pulse.levels = {'noisesink': 40}
    sm.initialize_audio_system()
    assert ('noisesink', 0) not in sm.pulse.writes, sm.pulse.writes
    assert sm.pulse.levels['noisesink'] == 40
    assert sm.pulse.levels['librarysink'] == 0
    assert sm.current_source == 'noise'
    print("ok: daemon restart never mutes the source it restores (no noise gap)")


def test_boot_brings_restored_sink_to_level():
    sm = make(current=None)
    sm.state_manager = FakeState(current='noise')
    sm.resync_go_librespot_volume = lambda: None
    sm.pulse.levels = {'noisesink': 100, 'librarysink': 100, 'airplaysink': 100}  # fresh PA
    sm.initialize_audio_system()
    assert sm.pulse.writes[:3] == [('airplaysink', 0), ('librarysink', 0), ('noisesink', 40)], sm.pulse.writes
    assert ('noisesink', 0) not in sm.pulse.writes
    print("ok: on a fresh boot the restored sink goes straight from 100 to its level")


def test_is_fading_from():
    sm = make(current='library')
    sm.FADE_STEP_MS = 20
    assert not sm.is_fading_from('library')
    sm.switch_source('noise', fade_ms=200)
    assert sm.is_fading_from('library') and not sm.is_fading_from('noise')
    time.sleep(0.35)
    assert not sm.is_fading_from('library')
    print("ok: is_fading_from is true only while the fade away runs")


if __name__ == "__main__":
    test_instant_switch_unchanged()
    test_fade_ramps_and_defers_leave()
    test_switch_mid_fade_lands_it()
    test_switch_back_mid_fade_skips_leave()
    test_volume_mid_fade_lands_it()
    test_fade_falls_back_to_instant_on_same_sink()
    test_restart_keeps_restored_sink_unmuted()
    test_boot_brings_restored_sink_to_level()
    test_is_fading_from()
