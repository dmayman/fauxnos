#!/bin/bash

# Test script for Fauxnos audio configuration
# Tests each audio source individually

echo "Testing Fauxnos Audio Sources"
echo "============================="

# Function to test a specific audio device
test_device() {
    local device=$1
    local name=$2
    
    echo "Testing $name (PCM device: $device)"
    echo "Playing 3 seconds of test tone..."
    
    speaker-test -D $device -c 2 -t sine -f 440 -l 1 -P 2
    
    echo "--------------------------"
    echo "Done testing $name"
    echo ""
}

# Function to set volume for a specific control
set_volume() {
    local control=$1
    local volume=$2
    
    echo "Setting $control to $volume%"
    amixer -c 0 set "$control" ${volume}% > /dev/null
}

# Set all volumes to 70%
echo "Setting all volumes to 70%"
set_volume "Librespot Volume" 70
set_volume "Snapcast Volume" 70
set_volume "Analog Volume" 70
set_volume "System Volume" 70
echo ""

# Test each device
test_device "librespot" "Librespot (Spotify Connect)"
test_device "snapcast" "Snapcast (Multiroom Sync)"
test_device "analog" "Analog Input"
test_device "system" "System Sounds"

# Test simultaneous playback
echo "Testing simultaneous playback - you should hear two tones"
speaker-test -D system -c 2 -t sine -f 440 -l 1 -P 8 &
PID1=$!
sleep 2
speaker-test -D librespot -c 2 -t sine -f 880 -l 1 -P 6 &
PID2=$!

wait $PID1
wait $PID2

echo ""
echo "All tests completed."
echo "If you heard all test tones clearly, your ALSA configuration is working!"
