#!/bin/bash
# play_loop.sh

# Configuration
WAV_FILE="test.wav"
DEVICE="system"  # Change to: librespot, snapcast, analog, or system

# Check if file exists
if [ ! -f "$WAV_FILE" ]; then
    echo "Error: WAV file not found at $WAV_FILE"
    exit 1
fi

echo "Playing $WAV_FILE on device $DEVICE in a loop..."
echo "Press Ctrl+C to stop"

# Infinite loop
while true; do
    aplay -D "$DEVICE" "$WAV_FILE"
done