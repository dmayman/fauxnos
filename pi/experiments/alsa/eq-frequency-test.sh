#!/bin/bash

# EQ Frequency Test Script
# Plays test tones at the frequencies corresponding to each EQ band

echo "Fauxnos EQ Frequency Test"
echo "========================="
echo "This will play test tones at frequencies for each EQ band"
echo "You should hear different volumes based on your EQ settings"
echo ""

# 15-band EQ center frequencies (approximately)
FREQUENCIES=(
    25    # Band 1
    40    # Band 2
    63    # Band 3
    100   # Band 4
    160   # Band 5
    250   # Band 6
    400   # Band 7
    630   # Band 8
    1000  # Band 9
    1600  # Band 10
    2500  # Band 11
    4000  # Band 12
    6300  # Band 13
    10000 # Band 14
    16000 # Band 15
)

BAND_NAMES=(
    "Sub-bass (25 Hz)"
    "Deep bass (40 Hz)"
    "Bass (63 Hz)"
    "Upper bass (100 Hz)"
    "Lower midrange (160 Hz)"
    "Midrange (250 Hz)"
    "Upper midrange (400 Hz)"
    "Middle (630 Hz)"
    "Upper middle (1 kHz)"
    "Lower treble (1.6 kHz)"
    "Treble (2.5 kHz)"
    "Upper treble (4 kHz)"
    "High treble (6.3 kHz)"
    "Very high (10 kHz)"
    "Ultra high (16 kHz)"
)

# Function to play a specific frequency
play_frequency() {
    local freq=$1
    local duration=${2:-1}
    local device=${3:-default}
    
    echo "Playing ${freq}Hz for ${duration} second(s)..."
    
    # Use speaker-test for accurate frequency generation
    if [ $freq -lt 100 ]; then
        # For very low frequencies, increase duration for better perception
        speaker-test -t sine -f "$freq" -c 2 -l 1 -P 2 -D "$device" >/dev/null 2>&1
    else
        speaker-test -t sine -f "$freq" -c 2 -l 1 -P "$duration" -D "$device" >/dev/null 2>&1
    fi
}

# Function to run frequency sweep
frequency_sweep() {
    local device=${1:-default}
    echo "Running frequency sweep on device: $device"
    echo "Listen for volume changes based on your EQ settings"
    echo "Press Ctrl+C to stop"
    echo ""
    
    for i in ${!FREQUENCIES[@]}; do
        echo "Band $((i+1)): ${BAND_NAMES[$i]}"
        play_frequency "${FREQUENCIES[$i]}" 1 "$device"
        sleep 0.5
    done
}

# Function to test specific band
test_band() {
    local band=$1
    local device=${2:-default}
    
    if [ $band -lt 1 ] || [ $band -gt 15 ]; then
        echo "Error: Band must be between 1 and 15"
        return 1
    fi
    
    local index=$((band-1))
    echo "Testing Band $band: ${BAND_NAMES[$index]}"
    play_frequency "${FREQUENCIES[$index]}" 3 "$device"
}

# Function to run continuous test
continuous_test() {
    local device=${1:-default}
    echo "Starting continuous frequency test"
    echo "This will cycle through all frequencies"
    echo "Press Ctrl+C to stop"
    echo ""
    
    while true; do
        frequency_sweep "$device"
        echo "Cycle complete. Starting again..."
        sleep 1
    done
}

# Show usage if no arguments
if [ $# -eq 0 ]; then
    echo "Usage:"
    echo "  $0 sweep [device]         - Run frequency sweep test"
    echo "  $0 band <1-15> [device]   - Test specific EQ band"
    echo "  $0 continuous [device]    - Run continuous test loop"
    echo "  $0 list                   - List EQ bands and frequencies"
    echo ""
    echo "Devices: Use 'default' or specific device names from your asound.conf"
    echo "Example: $0 sweep librespot"
    exit 0
fi

# Parse commands
case $1 in
    sweep)
        frequency_sweep "${2:-default}"
        ;;
    band)
        if [ $# -lt 2 ]; then
            echo "Usage: $0 band <1-15> [device]"
            exit 1
        fi
        test_band "$2" "${3:-default}"
        ;;
    continuous)
        continuous_test "${2:-default}"
        ;;
    list)
        echo "EQ Bands and Center Frequencies:"
        echo "--------------------------------"
        for i in ${!FREQUENCIES[@]}; do
            printf "Band %2d: %5d Hz - %s\n" "$((i+1))" "${FREQUENCIES[$i]}" "${BAND_NAMES[$i]}"
        done
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run '$0' without arguments for usage information"
        exit 1
        ;;
esac

exit 0
