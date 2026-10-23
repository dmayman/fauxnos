#!/bin/bash
# Endless generated noise into the noisesink PulseAudio sink.
#
# Run by fauxnos-noise.service (Restart=always). The source manager starts
# the service when the `noise` source becomes active and stops it on leave;
# while it runs, nothing here depends on the server, snapcast or Wi-Fi.
#
# Colour comes from FAUXNOS_NOISE_COLOR (white | pink | brown, default
# brown), set in ~/.config/fauxnos/noise.env. The per-colour gains bring
# all three to roughly the same RMS (~0.1) with headroom: raw sox noise
# peaks at full scale and clips, and white/brown come out ~8 dB hotter
# than pink.
#
# pipefail matters: if pacat dies (PulseAudio restarted), sox would keep
# writing into a broken pipe; failing the whole pipeline lets systemd
# restart us against the new PA instance.
set -o pipefail

color="${FAUXNOS_NOISE_COLOR:-brown}"
case "$color" in
    white) gain=-15 ;;
    pink)  gain=-7 ;;
    brown) gain=-15 ;;
    *)
        echo "noise-generator: unknown colour '$color', using brown" >&2
        color=brown
        gain=-15
        ;;
esac

rate=48000
sox -q -D -n -t raw -r "$rate" -e signed-integer -b 16 -c 2 - \
    synth "${color}noise" gain "$gain" \
| pacat --playback --raw --device=noisesink \
    --rate="$rate" --format=s16le --channels=2 \
    --client-name=fauxnos-noise --stream-name="${color} noise"
