#!/usr/bin/env python3
"""
Generate placeholder WAV files for the IR-remote volume feedback feature.

Produces 21 mono 16-bit WAVs (one per 5% notch from 0 to 100) in
pi/src/fauxnos-client/sounds/. They're meant to be REPLACED by the
user's actual sounds; they exist so the wiring is testable end-to-end
before the real sounds arrive.

Design:
  - Intermediate notches (5..95): log-spaced sine tones between
    ~220 Hz and ~1760 Hz (3 octaves over 19 steps = ~1.085× per
    notch, a roughly-semitone climb). 80 ms each with 8 ms fade-in/
    out to suppress click artifacts.
  - 0% boundary:  120 ms low thud at 80 Hz (mute / floor sound).
  - 100% boundary: 150 ms bright chime at 2400 Hz (max / ceiling).

Re-running overwrites every file in place. Real user sounds dropped
into the same paths are NOT touched by this script — it always wipes
its output (use git to track replacements).
"""
import math
import struct
import wave
from pathlib import Path

# 22.05 kHz / mono / 16-bit keeps the placeholders ~3-5 KB each.
# Plenty of fidelity for short feedback clicks; real sounds can be
# whatever the user wants.
SAMPLE_RATE = 22050
AMPLITUDE = 0.5  # 50% of max int16, leaves headroom — placeholders shouldn't clip

# Frequency band the intermediate notches walk: 3 octaves so each step
# is clearly audible against the previous one.
F_LOW_HZ = 220.0
F_HIGH_HZ = F_LOW_HZ * (2 ** 3)  # 1760 Hz


def gen_tone(freq_hz: float, duration_s: float, fade_ms: float = 8.0) -> bytes:
    """Render a mono 16-bit sine with a short linear fade-in/out."""
    n_samples = int(SAMPLE_RATE * duration_s)
    fade_n = max(1, int(SAMPLE_RATE * fade_ms / 1000))
    omega = 2 * math.pi * freq_hz / SAMPLE_RATE
    out = bytearray()
    for i in range(n_samples):
        if i < fade_n:
            env = i / fade_n
        elif i >= n_samples - fade_n:
            env = (n_samples - i) / fade_n
        else:
            env = 1.0
        s = AMPLITUDE * env * math.sin(omega * i)
        out += struct.pack('<h', int(s * 32767))
    return bytes(out)


def write_wav(path: Path, frames: bytes) -> None:
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)


def main() -> None:
    out_dir = (
        Path(__file__).resolve().parent.parent
        / 'pi' / 'src' / 'fauxnos-client' / 'sounds'
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    notches = list(range(0, 101, 5))  # [0, 5, 10, ..., 100] — 21 items

    print(f'writing {len(notches)} placeholder WAVs to {out_dir}')
    for i, notch in enumerate(notches):
        if notch == 0:
            freq = 80.0
            duration = 0.12
            tag = 'thud'
        elif notch == 100:
            freq = 2400.0
            duration = 0.15
            tag = 'chime'
        else:
            # Map intermediate notches (i=1..19) onto a log-spaced band.
            # i ranges 1..19; normalize to 0..1 across that interior.
            t = (i - 1) / (len(notches) - 3)  # 0 at notch=5, 1 at notch=95
            freq = F_LOW_HZ * ((F_HIGH_HZ / F_LOW_HZ) ** t)
            duration = 0.08
            tag = 'sine'

        path = out_dir / f'volume-{notch:03d}.wav'
        write_wav(path, gen_tone(freq, duration))
        print(f'  {path.name:20s}  {tag:5s}  {freq:7.1f} Hz  {duration*1000:5.1f} ms')


if __name__ == '__main__':
    main()
