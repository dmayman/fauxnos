#!/bin/bash

# EQ Preset Manager for Fauxnos
# Creates and applies different EQ settings for testing

# Configuration
PRESET_DIR="/opt/fauxnos/eq_presets"
ASOUND_CONF="/etc/asound.conf"

# Create preset directory if it doesn't exist
mkdir -p "$PRESET_DIR"

# Function to create a preset file
create_preset() {
    local name=$1
    shift
    local values=("$@")
    
    echo "Creating preset: $name"
    
    # Create asound.conf template with EQ values
    cat > "$PRESET_DIR/asound_${name}.conf" << EOF
# Fauxnos ALSA Configuration - $name preset
pcm.!default {
    type plug
    slave.pcm "plugequal"
}

ctl.!default {
    type hw
    card 0
}

pcm.plugequal {
    type ladspa
    slave.pcm "plughw:0,0"  # Adjust if your HiFiBerry is on a different card
    path "/usr/lib/ladspa"
    plugins [
        {
            label mbeq
            input {
                controls [${values[*]}]
            }
        }
    ]
}
EOF
    
    echo "Preset $name created at $PRESET_DIR/asound_${name}.conf"
}

# Function to apply a preset
apply_preset() {
    local name=$1
    local preset_file="$PRESET_DIR/asound_${name}.conf"
    
    if [ ! -f "$preset_file" ]; then
        echo "Error: Preset $name not found!"
        return 1
    fi
    
    echo "Applying preset: $name"
    
    # Backup current config
    sudo cp "$ASOUND_CONF" "$ASOUND_CONF.backup"
    
    # Apply new config
    sudo cp "$preset_file" "$ASOUND_CONF"
    
    # Reload ALSA
    sudo alsactl kill quit 2>/dev/null
    sudo alsa force-reload 2>/dev/null || true
    
    echo "Preset $name applied. Play audio to test."
}

# Function to test with a sine wave
test_preset() {
    local freq=${1:-440}
    echo "Playing test tone at ${freq}Hz for 3 seconds..."
    speaker-test -t sine -f "$freq" -c 2 -l 1 -P 3
}

# Create different presets

# 1. Flat (all zeros)
create_preset "flat" 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

# 2. Bass boost (boost low frequencies)
create_preset "bass_boost" 10 10 8 6 4 2 0 0 0 0 0 0 0 0 0

# 3. Treble boost (boost high frequencies)
create_preset "treble_boost" 0 0 0 0 0 0 0 0 2 4 6 8 10 10 10

# 4. Midrange boost (voice clarity)
create_preset "voice_boost" -2 -2 0 2 4 6 8 6 4 2 0 -2 -2 -4 -4

# 5. Extreme V-shape (boost bass and treble, cut mids)
create_preset "v_shape" 12 10 8 4 0 -6 -8 -6 0 4 8 10 12 14 14

# 6. Telephone effect (narrow band)
create_preset "telephone" -15 -15 -10 -5 0 5 5 5 0 -5 -10 -15 -15 -15 -15

# 7. Bass cut (reduce low frequencies)
create_preset "bass_cut" -12 -10 -8 -6 -4 -2 0 0 0 0 0 0 0 0 0

# 8. Loudness (subtle boost at extremes)
create_preset "loudness" 4 3 2 1 0 0 0 0 0 0 1 2 3 4 4

# 9. Concert hall simulation
create_preset "concert_hall" 2 2 4 4 2 0 -2 -4 -2 0 2 4 4 2 2

# 10. Radio/AM simulation
create_preset "radio_am" -15 -12 -8 -4 0 2 2 2 0 -4 -8 -12 -15 -15 -15

# Show usage if no arguments
if [ $# -eq 0 ]; then
    echo "Fauxnos EQ Preset Manager"
    echo "Usage:"
    echo "  $0 apply <preset>     - Apply an EQ preset"
    echo "  $0 test [frequency]   - Play test tone (default 440Hz)"
    echo "  $0 list              - List available presets"
    echo "  $0 restore           - Restore backup config"
    echo ""
    echo "Available presets:"
    echo "  flat         - No EQ (all bands at 0)"
    echo "  bass_boost   - Enhanced bass response"
    echo "  treble_boost - Enhanced high frequencies"
    echo "  voice_boost  - Enhanced vocal clarity"
    echo "  v_shape      - Boosted bass and treble"
    echo "  telephone    - Narrow band (phone effect)"
    echo "  bass_cut     - Reduced bass response"
    echo "  loudness     - Subtle loudness curve"
    echo "  concert_hall - Simulated concert acoustics"
    echo "  radio_am     - AM radio simulation"
    exit 0
fi

# Parse commands
case $1 in
    apply)
        if [ $# -ne 2 ]; then
            echo "Usage: $0 apply <preset>"
            exit 1
        fi
        apply_preset "$2"
        ;;
    test)
        test_preset "${2:-440}"
        ;;
    list)
        echo "Available presets:"
        ls "$PRESET_DIR" | grep "asound_" | sed 's/asound_//;s/\.conf//' | sort
        ;;
    restore)
        if [ -f "$ASOUND_CONF.backup" ]; then
            echo "Restoring backup configuration..."
            sudo cp "$ASOUND_CONF.backup" "$ASOUND_CONF"
            sudo alsactl kill quit 2>/dev/null
            sudo alsa force-reload 2>/dev/null || true
            echo "Backup restored."
        else
            echo "No backup found."
        fi
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run '$0' without arguments for usage information"
        exit 1
        ;;
esac

exit 0
