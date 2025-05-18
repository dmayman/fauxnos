#!/bin/bash

# Simple EQ Testing Script for Fauxnos
# Tests EQ settings with real-time audio feedback

# Configuration
ASOUND_CONF="/etc/asound.conf"
TEST_WAV="./test.wav"

# Check prerequisites
check_requirements() {
    if ! command -v aplay &> /dev/null; then
        echo "Error: aplay not found. Please install alsa-utils."
        exit 1
    fi
    
    if [ ! -f "$TEST_WAV" ]; then
        echo "Error: test.wav not found in the current directory."
        exit 1
    fi
}

# Apply EQ settings
apply_eq_settings() {
    local values=("$@")
    cat > "/tmp/asound_dynamic.conf" << EOF
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
    slave.pcm "plughw:0,0"
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
    sudo cp "/tmp/asound_dynamic.conf" "$ASOUND_CONF"
    sudo alsactl kill quit 2>/dev/null
    sleep 0.5
}

# Interactive EQ adjustment
interactive_eq() {
    local eq_values=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)
    local band_names=(
        "25Hz" "40Hz" "63Hz" "100Hz" "160Hz"
        "250Hz" "400Hz" "630Hz" "1kHz" "1.6kHz"
        "2.5kHz" "4kHz" "6.3kHz" "10kHz" "16kHz"
    )
    
    apply_eq_settings "${eq_values[@]}"
    
    aplay -D default "$TEST_WAV" &
    local PLAYBACK_PID=$!
    
    while true; do
        clear
        echo "Fauxnos Real-time EQ Adjuster"
        echo "============================="
        echo "Current EQ Values (dB):"
        
        for i in {0..14}; do
            printf "%2d: %-5s %+3d dB\n" "$((i+1))" "${band_names[i]}" "${eq_values[i]}"
        done
        
        echo ""
        echo "Commands:"
        echo "  1-15: Select frequency band to adjust"
        echo "  +/-:  Increase/decrease selected band by 1dB"
        echo "  q:    Quit"
        echo ""
        
        read -n1 -p "Command: " cmd
        echo ""
        
        case "$cmd" in
            [1-9]|1[0-5])
                local selected_band=$((cmd - 1))
                echo "Selected band $cmd: ${band_names[selected_band]}"
                echo "Current value: ${eq_values[selected_band]} dB"
                echo "Use +/- to adjust, Enter to finish"
                
                while true; do
                    read -n1 -s adjust_cmd
                    case "$adjust_cmd" in
                        +)
                            if [ ${eq_values[selected_band]} -lt 15 ]; then
                                eq_values[selected_band]=$((eq_values[selected_band] + 1))
                                apply_eq_settings "${eq_values[@]}"
                                echo -ne "\rBand $cmd: ${eq_values[selected_band]} dB  "
                            fi
                            ;;
                        -)
                            if [ ${eq_values[selected_band]} -gt -15 ]; then
                                eq_values[selected_band]=$((eq_values[selected_band] - 1))
                                apply_eq_settings "${eq_values[@]}"
                                echo -ne "\rBand $cmd: ${eq_values[selected_band]} dB  "
                            fi
                            ;;
                        "")
                            echo ""
                            break
                            ;;
                    esac
                done
                ;;
            
            q)
                kill $PLAYBACK_PID
                echo "Exiting..."
                exit 0
                ;;
            
            *)
                echo "Invalid command"
                ;;
        esac
    done
}

# Main script logic
check_requirements
interactive_eq