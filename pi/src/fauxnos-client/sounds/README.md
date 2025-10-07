# Fauxnos Audio Feedback Sounds

This directory contains audio files used for user feedback during fauxnos-client operations.

## Sound Files

- `source_switch.wav` - Played when switching between audio sources
- `volume_up.wav` - Played when volume is increased
- `volume_down.wav` - Played when volume is decreased

## Format Requirements

- **Format**: WAV (uncompressed)
- **Sample Rate**: 44.1kHz recommended
- **Channels**: Mono or stereo
- **Duration**: Keep short (< 1 second) for responsive UI

## Customization

To customize sounds:

1. Replace the WAV files in this directory
2. Keep the same filenames
3. Test with: `aplay ~/src/fauxnos-client/sounds/source_switch.wav`

## Creating Your Own Sounds

Simple beep sounds can be generated with:

```bash
# Generate a short beep
sox -n ~/src/fauxnos-client/sounds/custom_beep.wav synth 0.2 sine 800

# Generate a two-tone beep
sox -n ~/src/fauxnos-client/sounds/two_tone.wav synth 0.1 sine 600 : synth 0.1 sine 800
```