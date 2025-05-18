#!/bin/bash

# EQ Control Script for Fauxnos
# This script helps manage the 15-band equalizer

# Check if we have the necessary dependencies
if ! command -v amixer &> /dev/null; then
    echo "Error: amixer not found. Please install alsa-utils."
    exit 1
fi

# Define the 15 bands with their approximate frequencies
BANDS=(
    "Band1 (25Hz)"
    "Band2 (40Hz)"
    "Band3 (63Hz)"
    "Band4 (100Hz)"
    "Band5 (160Hz)"
    "Band6 (250Hz)"
    "Band7 (400Hz)"
    "Band8 (630Hz)"
    "Band9 (1kHz)"
    "Band10 (1.6kHz)"
    "Band11 (2.5kHz)"
    "Band12 (4kHz)"
    "Band13 (6.3kHz)"
    "Band14 (10kHz)"
    "Band15 (16kHz)"
)

# Function to list the current EQ settings
list_eq() {
    echo "Current EQ Settings:"
    for i in {0..14}; do
        value=$(get_ladspa_control $i)
        printf "%-18s %+5.1f dB\n" "${BANDS[$i]}" "$value"
    done
}

# Function to get the value of a LADSPA control
get_ladspa_control() {
    local control=$1
    # This would need to be implemented based on how your system stores LADSPA settings
    # For now, it just returns 0 as a placeholder
    echo 0
}

# Function to set a specific EQ band
set_eq_band() {
    local band=$1
    local value=$2
    
    if [[ $band -lt 0 || $band -gt 14 ]]; then
        echo "Error: Band must be between 0 and 14"
        return 1
    fi
    
    if [[ $value -lt -20 || $value -gt 20 ]]; then
        echo "Error: Value must be between -20 and +20 dB"
        return 1
    fi
    
    # This would set the actual control value
    # Implementation depends on how you've configured LADSPA
    echo "Setting ${BANDS[$band]} to $value dB"
    
    # Example of how you might call a command to update the control
    # Replace this with actual implementation
    # alsactl set "eq_control_$band" "$value"
}

# Function to apply preset EQ curves
apply_preset() {
    local preset=$1
    
    case $preset in
        flat)
            echo "Applying flat response (0 dB for all bands)"
            for i in {0..14}; do
                set_eq_band $i 0
            done
            ;;
        bass_boost)
            echo "Applying bass boost preset"
            set_eq_band 0 8  # 25Hz
            set_eq_band 1 10 # 40Hz
            set_eq_band 2 7  # 63Hz
            set_eq_band 3 5  # 100Hz
            set_eq_band 4 3  # 160Hz
            set_eq_band 5 1  # 250Hz
            # Set rest to 0
            for i in {6..14}; do
                set_eq_band $i 0
            done
            ;;
        vocal)
            echo "Applying vocal clarity preset"
            # Cut some bass
            for i in {0..3}; do
                set_eq_band $i -2
            done
            # Boost mid-range vocals
            set_eq_band 6 2  # 400Hz
            set_eq_band 7 4  # 630Hz
            set_eq_band 8 5  # 1kHz
            set_eq_band 9 4  # 1.6kHz
            set_eq_band 10 2 # 2.5kHz
            # Leave the rest neutral
            for i in {11..14}; do
                set_eq_band $i 0
            done
            ;;
        *)
            echo "Unknown preset: $preset"
            echo "Available presets: flat, bass_boost, vocal"
            return 1
            ;;
    esac
    
    echo "Preset applied successfully"
}

# Show help if no arguments
if [ $# -eq 0 ]; then
    echo "Fauxnos EQ Control"
    echo "Usage:"
    echo "  $0 list                         - List current EQ settings"
    echo "  $0 set <band> <value>           - Set band (0-14) to value (-20 to +20 dB)"
    echo "  $0 preset <preset_name>         - Apply a preset (flat, bass_boost, vocal)"
    echo "  $0 save <filename>              - Save current EQ settings to file"
    echo "  $0 load <filename>              - Load EQ settings from file"
    exit 0
fi

# Parse commands
case $1 in
    list)
        list_eq
        ;;
    set)
        if [ $# -ne 3 ]; then
            echo "Usage: $0 set <band> <value>"
            exit 1
        fi
        set_eq_band $2 $3
        ;;
    preset)
        if [ $# -ne 2 ]; then
            echo "Usage: $0 preset <preset_name>"
            exit 1
        fi
        apply_preset $2
        ;;
    save)
        if [ $# -ne 2 ]; then
            echo "Usage: $0 save <filename>"
            exit 1
        fi
        echo "Saving EQ settings to $2 (not yet implemented)"
        # Implementation would save current settings to a file
        ;;
    load)
        if [ $# -ne 2 ]; then
            echo "Usage: $0 load <filename>"
            exit 1
        fi
        echo "Loading EQ settings from $2 (not yet implemented)"
        # Implementation would load settings from a file
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run '$0' without arguments for usage information"
        exit 1
        ;;
esac

exit 0
