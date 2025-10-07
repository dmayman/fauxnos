#!/bin/bash

# Fauxnos Pi Setup - System Preparation Script
# ============================================
# Prepares a fresh Raspberry Pi OS for Fauxnos client installation
# This handles all system-level configuration and dependencies

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAUXNOS_USER="${SUDO_USER:-${USER}}"
FAUXNOS_HOME="/home/${FAUXNOS_USER}"
TEMP_HOSTNAME_PREFIX="fauxnos-temp"

# Flags
DRY_RUN=false
SKIP_UPDATES=false
SKIP_REBOOT=false
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;36m'  # Bright cyan for better visibility
NC='\033[0m'

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Prepares a Raspberry Pi OS for Fauxnos client installation.

OPTIONS:
    --dry-run           Show what would be done without making changes
    --skip-updates      Skip system package updates (faster for testing)
    --skip-reboot       Don't reboot at the end
    --verbose           Show detailed output
    -h, --help          Show this help message

EXAMPLES:
    # Full Pi preparation
    sudo $0

    # Test what would happen
    $0 --dry-run

    # Quick setup without updates (for testing)
    sudo $0 --skip-updates --skip-reboot
EOF
}

log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] ✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date +'%H:%M:%S')] ✗${NC} $1"
}

execute() {
    local cmd="$1"
    local description="$2"

    if [ "$VERBOSE" = true ]; then
        log "Executing: $cmd"
    fi

    if [ "$DRY_RUN" = true ]; then
        log "DRY RUN: Would execute: $cmd"
        return 0
    fi

    if [ -n "$description" ]; then
        log "$description"
    fi

    if eval "$cmd"; then
        if [ -n "$description" ]; then
            log_success "$description completed"
        fi
        return 0
    else
        log_error "Failed: $cmd"
        return 1
    fi
}

check_prerequisites() {
    log "Checking prerequisites..."

    # Check if running on Raspberry Pi
    if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        log_warning "This doesn't appear to be a Raspberry Pi"
        if [ "$DRY_RUN" = false ]; then
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi

    # Check for sudo
    if [ "$DRY_RUN" = false ] && [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi

    # Check internet connectivity
    if [ "$DRY_RUN" = false ] && ! ping -c 1 8.8.8.8 &> /dev/null; then
        log_error "No internet connectivity detected"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

update_system() {
    if [ "$SKIP_UPDATES" = true ]; then
        log_warning "Skipping system updates (--skip-updates)"
        return 0
    fi

    log "Updating system packages..."
    execute "apt update" "Updating package lists"
    execute "apt upgrade -y" "Upgrading system packages"
}

install_audio_system() {
    log "Installing audio system..."

    local audio_packages=(
        "pulseaudio"
        "pulseaudio-utils"
        "pulseaudio-module-bluetooth"
        "alsa-utils"
        "snapclient"
    )

    for package in "${audio_packages[@]}"; do
        execute "apt install -y $package" "Installing $package"
    done

    # Configure PulseAudio for system mode if needed
    execute "systemctl --global disable pulseaudio.service pulseaudio.socket" "Disabling global PulseAudio"
}

install_network_tools() {
    log "Installing network and discovery tools..."

    local network_packages=(
        "avahi-daemon"
        "avahi-utils"
        "dnsutils"
        "curl"
        "wget"
        "openssh-server"
    )

    for package in "${network_packages[@]}"; do
        execute "apt install -y $package" "Installing $package"
    done

    execute "systemctl enable avahi-daemon" "Enabling Avahi daemon"
    execute "systemctl start avahi-daemon" "Starting Avahi daemon"

    execute "systemctl enable ssh" "Enabling SSH server"
    execute "systemctl start ssh" "Starting SSH server"
}

install_development_tools() {
    log "Installing development tools..."

    local dev_packages=(
        "git"
        "jq"
        "python3"
        "python3-pip"
        "python3-venv"
        "python3-requests"
    )

    for package in "${dev_packages[@]}"; do
        execute "apt install -y $package" "Installing $package"
    done
}

configure_audio_permissions() {
    log "Configuring audio permissions for user: $FAUXNOS_USER"

    execute "usermod -a -G audio $FAUXNOS_USER" "Adding user to audio group"
    execute "usermod -a -G pulse-access $FAUXNOS_USER" "Adding user to pulse-access group"
}

configure_pi_audio() {
    log "Configuring Pi audio settings..."

    # Configure HiFiBerry DAC+ in config.txt
    local config_txt="/boot/firmware/config.txt"
    local legacy_config_txt="/boot/config.txt"

    # Check which config file exists (newer Pi OS uses /boot/firmware/)
    if [ -f "$config_txt" ]; then
        # Use /boot/firmware/config.txt (newer Pi OS)
        config_txt="/boot/firmware/config.txt"
    elif [ -f "$legacy_config_txt" ]; then
        # Fallback to /boot/config.txt (older Pi OS)
        config_txt="$legacy_config_txt"
    fi

    if [ -f "$config_txt" ]; then
        # Disable onboard audio to avoid conflicts
        if ! grep -q "^dtparam=audio=off" "$config_txt"; then
            execute "echo 'dtparam=audio=off' >> $config_txt" "Disabling onboard audio"
        fi

        # Enable HiFiBerry DAC+ overlay
        if ! grep -q "^dtoverlay=hifiberry-dac" "$config_txt"; then
            execute "echo 'dtoverlay=hifiberry-dac' >> $config_txt" "Enabling HiFiBerry DAC overlay"
        fi

        log_success "HiFiBerry DAC+ configured in $config_txt"
        log_warning "A reboot will be required for audio changes to take effect"
    else
        log_error "Could not find config.txt file"
        return 1
    fi

    # Set audio output to auto (will be managed by PulseAudio)
    execute "amixer cset numid=3 0" "Setting audio output to auto" || true
}

setup_temporary_hostname() {
    log "Setting up temporary hostname..."

    local mac_suffix
    mac_suffix=$(cat /sys/class/net/*/address | head -1 | sed 's/://g' | tail -c 5)
    local temp_hostname="${TEMP_HOSTNAME_PREFIX}-${mac_suffix}"

    execute "hostnamectl set-hostname '$temp_hostname'" "Setting temporary hostname to $temp_hostname"
    execute "sed -i 's/127.0.1.1.*/127.0.1.1\t$temp_hostname/' /etc/hosts" "Updating /etc/hosts"

    log_success "Temporary hostname set to: $temp_hostname"
}

enable_ssh() {
    log "Ensuring SSH is enabled..."
    execute "systemctl enable ssh" "Enabling SSH service"
    execute "systemctl start ssh" "Starting SSH service"
}

create_install_directory() {
    log "Creating installation directory..."

    local install_dir="$FAUXNOS_HOME/src"
    execute "mkdir -p '$install_dir'" "Creating $install_dir"
    execute "chown $FAUXNOS_USER:$FAUXNOS_USER '$install_dir'" "Setting ownership of installation directory"
}

print_next_steps() {
    log_success "Pi setup completed successfully!"
    echo
    echo -e "${GREEN}System is now ready for Fauxnos client installation!${NC}"
    echo
    echo -e "${YELLOW}Next steps:${NC}"
    echo "1. Reboot this Pi (will happen automatically unless --skip-reboot)"
    echo "2. After reboot, run the client installation:"
    echo -e "   ${BLUE}curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash${NC}"
    echo
    echo -e "${YELLOW}Or manually:${NC}"
    echo -e "   ${BLUE}cd ~/src && git clone <repo> && cd fauxnos-client${NC}"
    echo -e "   ${BLUE}python3 setup-client.py --setup${NC}"
    echo

    if [ "$DRY_RUN" = true ]; then
        log_warning "DRY RUN: No actual changes were made"
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-updates)
            SKIP_UPDATES=true
            shift
            ;;
        --skip-reboot)
            SKIP_REBOOT=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    log "Starting Fauxnos Pi setup..."

    if [ "$DRY_RUN" = true ]; then
        log_warning "DRY RUN MODE: No changes will be made"
    fi

    check_prerequisites
    update_system
    install_audio_system
    install_network_tools
    install_development_tools
    configure_audio_permissions
    configure_pi_audio
    setup_temporary_hostname
    enable_ssh
    create_install_directory

    print_next_steps

    # Reboot unless skipped
    if [ "$SKIP_REBOOT" = false ] && [ "$DRY_RUN" = false ]; then
        log "Rebooting in 10 seconds... (Ctrl+C to cancel)"
        sleep 10
        reboot
    fi
}

main "$@"