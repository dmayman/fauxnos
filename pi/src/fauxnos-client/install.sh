#!/bin/bash

# Fauxnos Client - One-Command Install
# ===================================
# Bootstrap script for fresh Raspberry Pi OS installations
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-client/install.sh | bash
#
# This script:
# 1. Sets up the Pi OS environment with all dependencies
# 2. Downloads the complete fauxnos-client system
# 3. Automatically registers with fauxnos-server
# 4. Deploys and starts all necessary services
# 5. Validates the installation

set -e

# Configuration
REPO_URL="https://raw.githubusercontent.com/dmayman/fauxnos/main"
INSTALL_DIR="$HOME/src/fauxnos-client"
LOG_FILE="/tmp/fauxnos-install.log"
TEMP_HOSTNAME_PREFIX="fauxnos-temp"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;36m'  # Bright cyan for better visibility
BOLD='\033[1m'
NC='\033[0m'

# Logging functions
log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] ✓${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date +'%H:%M:%S')] ✗${NC} $1" | tee -a "$LOG_FILE"
}

log_section() {
    echo -e "\n${BOLD}${BLUE}=== $1 ===${NC}" | tee -a "$LOG_FILE"
}

# Error handling
cleanup_on_error() {
    log_error "Installation failed! Check log at: $LOG_FILE"
    log_error "You can retry the installation by running this script again"
    exit 1
}

trap cleanup_on_error ERR

# Check if running as root (we don't want that)
check_user() {
    if [ "$EUID" -eq 0 ]; then
        log_error "Do not run this script as root! Run as regular user (pi)"
        exit 1
    fi
}

# Check prerequisites
check_prerequisites() {
    log_section "Checking Prerequisites"

    # Check if this is a Raspberry Pi
    if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        log_warning "This doesn't appear to be a Raspberry Pi"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Check internet connectivity
    if ! ping -c 1 8.8.8.8 &> /dev/null; then
        log_error "No internet connectivity detected"
        exit 1
    fi

    # Check if we can reach GitHub
    if ! curl -s --head https://raw.githubusercontent.com &> /dev/null; then
        log_error "Cannot reach GitHub. Check your internet connection"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

# Update system and install dependencies
install_system_dependencies() {
    log_section "Installing System Dependencies"

    log "Updating package lists..."
    sudo apt update -y

    log "Installing core dependencies..."
    sudo apt install -y \
        snapclient \
        pulseaudio \
        pulseaudio-utils \
        alsa-utils \
        avahi-daemon \
        avahi-utils \
        openssh-server \
        curl \
        jq \
        git \
        python3 \
        python3-pip \
        python3-venv \
        python3-requests

    log "Installing Python packages..."
    pip3 install --user requests pyyaml --break-system-packages

    log_success "System dependencies installed"
}

# Configure system settings
configure_system() {
    log_section "Configuring System"

    # Enable services
    log "Enabling system services..."
    sudo systemctl enable avahi-daemon
    sudo systemctl start avahi-daemon
    sudo systemctl enable ssh
    sudo systemctl start ssh

    # Disable the apt-installed system snapclient.service. It runs as the
    # _snapclient user with MAC-based hostID and registers itself with the
    # snapserver as a phantom second client, in addition to our per-client
    # user service (snapclient-fauxnosNNN). Disable + stop it so only our
    # user-level snapclient connects.
    log "Disabling system snapclient.service (we use the user-level service)..."
    sudo systemctl disable --now snapclient.service 2>/dev/null || true

    # Enable user service lingering for automatic startup
    log "Enabling user service lingering for automatic startup..."
    sudo loginctl enable-linger "$USER"

    # Add user to audio groups
    log "Configuring audio permissions..."
    sudo usermod -a -G audio "$USER"
    sudo usermod -a -G pulse-access "$USER"

    # Configure HiFiBerry DAC+ audio
    log "Configuring HiFiBerry DAC+ audio..."
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
            echo "dtparam=audio=off" | sudo tee -a "$config_txt" > /dev/null
            log "Disabled onboard audio"
        fi

        # Enable HiFiBerry DAC+ overlay
        if ! grep -q "^dtoverlay=hifiberry-dac" "$config_txt"; then
            echo "dtoverlay=hifiberry-dac" | sudo tee -a "$config_txt" > /dev/null
            log "Enabled HiFiBerry DAC overlay"
        fi

        log_success "HiFiBerry DAC+ configured in $config_txt"
    else
        log_error "Could not find config.txt file"
    fi

    # Set temporary hostname using the first non-loopback MAC. The previous
    # `cat /sys/class/net/*/address | head -1` matched lo first (all-zero
    # MAC), producing a useless temp hostname like `fauxnos-temp-0000` and a
    # `sudo: unable to resolve host fauxnos-temp-0000` warning. setup-client.py
    # renames to fauxnosNNN later anyway, but we want this name to actually
    # identify the device while it's installing.
    local mac_suffix=""
    for iface_addr in /sys/class/net/*/address; do
        local iface=$(basename "$(dirname "$iface_addr")")
        [ "$iface" = "lo" ] && continue
        local mac=$(cat "$iface_addr" 2>/dev/null)
        [ -z "$mac" ] || [ "$mac" = "00:00:00:00:00:00" ] && continue
        mac_suffix=$(echo "$mac" | sed 's/://g' | tail -c 5)
        break
    done
    [ -z "$mac_suffix" ] && mac_suffix="$$"  # fall back to PID
    local temp_hostname="${TEMP_HOSTNAME_PREFIX}-${mac_suffix}"

    log "Setting temporary hostname to: $temp_hostname"
    sudo hostnamectl set-hostname "$temp_hostname"
    sudo sed -i "s/127.0.1.1.*/127.0.1.1\t$temp_hostname/" /etc/hosts
    # Add the new name to /etc/hosts so sudo doesn't warn about unresolvable
    # host on subsequent commands in this same install run.
    grep -q "127.0.1.1.*$temp_hostname" /etc/hosts || echo "127.0.1.1 $temp_hostname" | sudo tee -a /etc/hosts > /dev/null

    log_success "System configuration completed"
}

# Download fauxnos-client code
download_client_code() {
    log_section "Downloading Fauxnos Client"

    # Determine download base URL
    # Prefer FAUXNOS_SERVER_URL (injected by server) so we get the server's
    # current copy of all files, including those not yet on GitHub.
    local base_url
    if [ -n "$FAUXNOS_SERVER_URL" ]; then
        base_url="${FAUXNOS_SERVER_URL}/api/install/files/client"
        log "Downloading from fauxnos server: $FAUXNOS_SERVER_URL"
    else
        base_url="${REPO_URL}/pi/src/fauxnos-client"
        log "Downloading from GitHub"
    fi

    # Create installation directory
    mkdir -p "$(dirname "$INSTALL_DIR")"

    # Remove existing installation
    if [ -d "$INSTALL_DIR" ]; then
        log "Removing existing installation..."
        rm -rf "$INSTALL_DIR"
    fi

    # Create new directory
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    log "Downloading client files..."

    # Main scripts and metadata
    local files=(
        "setup-client.py"
        "fauxnos-client.py"
        "fauxnos_client.py"
        "README.md"
        "TESTING.md"
        "install.sh"
        "pi-setup.sh"
        "requirements.txt"
        "client_config.yaml.template"
    )

    # Config files (with subdirectory creation)
    local config_files=(
        "configs/pulseaudio/default.pa"
        "configs/systemd/snapclient.service"
        "configs/systemd/fauxnos-client.service"
    )

    # Python modules
    local module_files=(
        "modules/__init__.py"
        "modules/config_manager.py"
        "modules/logger.py"
        "modules/mqtt_client.py"
        "modules/pulse_controller.py"
        "modules/snapcast_controller.py"
        "modules/source_manager.py"
        "modules/state_manager.py"
    )

    for file in "${files[@]}"; do
        local url="${base_url}/$file"
        if curl -fsSL "$url" -o "$file" 2>/dev/null; then
            log "Downloaded: $file"
        else
            log_warning "Failed to download: $file (may not exist)"
        fi
    done

    for file in "${config_files[@]}" "${module_files[@]}"; do
        local url="${base_url}/$file"
        local dir
        dir=$(dirname "$file")
        mkdir -p "$dir"
        if curl -fsSL "$url" -o "$file" 2>/dev/null; then
            log "Downloaded: $file"
        else
            log_warning "Failed to download: $file (may not exist)"
        fi
    done

    # Make scripts executable
    chmod +x setup-client.py 2>/dev/null || true
    chmod +x fauxnos-client.py 2>/dev/null || true
    chmod +x fauxnos_client.py 2>/dev/null || true
    chmod +x install.sh 2>/dev/null || true
    chmod +x pi-setup.sh 2>/dev/null || true

    log_success "Client code downloaded to: $INSTALL_DIR"
}

# Run client registration
register_client() {
    log_section "Registering Client with Server"

    cd "$INSTALL_DIR"

    # Check if setup-client.py exists
    if [ ! -f "setup-client.py" ]; then
        log_error "setup-client.py not found! Download may have failed"
        return 1
    fi

    log "Starting client registration..."
    log "This will discover the fauxnos-server and register this device"

    # Run the client setup
    # Pass display name non-interactively if provided via env var.
    # --no-reboot: install.sh owns the final reboot. Without this flag
    # setup-client.py would reboot first, killing install.sh's own countdown
    # and validation steps.
    local setup_args="--setup --no-reboot"
    if [ -n "$DISPLAY_NAME" ]; then
        setup_args="$setup_args --display-name $DISPLAY_NAME"
    fi

    if python3 setup-client.py $setup_args; then
        log_success "Client registration completed successfully"
        return 0
    else
        log_error "Client registration failed"
        return 1
    fi
}

# Validate installation
validate_installation() {
    log_section "Validating Installation"

    local errors=0

    # The actual client config is YAML, written by setup-client.py to
    # ~/.config/fauxnos/client_config.yaml. The old check looked at
    # $INSTALL_DIR/config.json which has never existed in this codebase
    # (stale path from before the YAML migration); leaving it in here
    # caused validate to false-positive and `set -e` to abort the install
    # before the auto-reboot. See install_idempotency_bugs.md.
    local config_file="$HOME/.config/fauxnos/client_config.yaml"
    if [ -f "$config_file" ]; then
        log_success "Client configuration found"
        local client_id
        client_id=$(sed -n 's/^client_id:[[:space:]]*//p' "$config_file" | head -1)
        log "Client ID: ${client_id:-unknown}"
    else
        log_error "Client configuration missing at $config_file"
        ((errors++))
    fi

    # Check hostname
    local current_hostname
    current_hostname=$(hostname)
    if [[ "$current_hostname" == fauxnos[0-9][0-9][0-9] ]]; then
        log_success "Hostname configured: $current_hostname"
    else
        log_warning "Hostname may not be properly configured: $current_hostname"
    fi

    # Check services (after reboot, they should be running)
    local services=(
        "snapclient-$current_hostname"
        "fauxnos-client-$current_hostname"
    )

    for service in "${services[@]}"; do
        if systemctl --user is-enabled "$service" &>/dev/null; then
            log_success "Service enabled: $service"
        else
            log_warning "Service not found: $service (will be created after reboot)"
        fi
    done

    # Check audio system
    if command -v pactl &> /dev/null; then
        log_success "PulseAudio available"
    else
        log_warning "PulseAudio not found"
        ((errors++))
    fi

    if [ $errors -eq 0 ]; then
        log_success "Validation completed - no critical errors found"
        return 0
    else
        log_warning "Validation found $errors potential issues"
        return 1
    fi
}

# Print final instructions
print_completion_message() {
    log_section "Installation Complete"

    echo -e "\n${GREEN}${BOLD}🎉 Fauxnos Client Installation Successful!${NC}\n"

    local config_file="$HOME/.config/fauxnos/client_config.yaml"
    local client_id display_name
    if [ -f "$config_file" ]; then
        client_id=$(sed -n 's/^client_id:[[:space:]]*//p' "$config_file" | head -1)
        # display_name appears twice in the rendered YAML (top-level + under
        # device:); the top-level one wins because we read the first match.
        display_name=$(sed -n 's/^display_name:[[:space:]]*//p' "$config_file" | head -1)
        echo -e "${BLUE}Client ID:${NC} ${client_id:-unknown}"
        echo -e "${BLUE}Display Name:${NC} ${display_name:-Unknown}"
    fi

    echo -e "\n${YELLOW}Next Steps:${NC}"
    echo "1. The system will reboot automatically in 30 seconds"
    echo "2. After reboot, your Fauxnos client will be fully operational"
    echo "3. You should see it appear in Spotify as a playback device"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo "  # Check service status"
    echo "  systemctl --user status snapclient-* fauxnos-client-*"
    echo ""
    echo "  # View service logs"
    echo "  journalctl --user -u fauxnos-client-* -f"
    echo ""
    echo "  # Manual client restart"
    echo "  cd $INSTALL_DIR && python3 setup-client.py --setup"
    echo ""
    echo -e "${BLUE}Installation Log:${NC} $LOG_FILE"
}

# Main installation flow
setup_pulseaudio_user_services() {
    log_section "Switching from PipeWire to PulseAudio"

    # Bookworm ships with PipeWire as the default audio server. Its
    # pulse-compatibility shim (pipewire-pulse) takes ownership of the
    # /run/user/$UID/pulse/native socket, so even though pulseaudio is
    # installed and "enabled", it can never actually run. PipeWire also
    # silently ignores ~/.config/pulse/default.pa, so our virtual sinks
    # (snapsink, analogsink, systemsink) never get loaded — fauxnos_client
    # then errors with "Failed to get sink information: No such entity".
    #
    # Mask the PipeWire user units so PulseAudio can take the socket on
    # next start. setup-client.py later copies our default.pa, and
    # PulseAudio is started on demand by its socket.
    log "Stopping and masking PipeWire user services..."
    systemctl --user stop \
        pipewire-pulse.service pipewire-pulse.socket \
        pipewire.service pipewire.socket \
        wireplumber.service 2>/dev/null || true
    systemctl --user mask \
        pipewire.service pipewire.socket \
        pipewire-pulse.service pipewire-pulse.socket \
        wireplumber.service 2>/dev/null || true

    log "Enabling PulseAudio user service..."
    systemctl --user unmask pulseaudio.service pulseaudio.socket 2>/dev/null || true
    systemctl --user enable pulseaudio.service pulseaudio.socket 2>/dev/null || true

    log_success "PulseAudio user services configured"
}

main() {
    log_section "Fauxnos Client Installation Starting"
    log "Installation log: $LOG_FILE"

    check_user
    check_prerequisites
    install_system_dependencies
    configure_system
    setup_pulseaudio_user_services
    download_client_code

    # Attempt registration (may fail if server not available)
    if register_client; then
        log_success "Registration successful"
    else
        log_warning "Registration failed - you can retry manually later"
        log "To retry: cd $INSTALL_DIR && python3 setup-client.py --setup"
    fi

    validate_installation
    print_completion_message

    # Ask about reboot
    echo -e "\n${YELLOW}The system needs to reboot to complete the installation.${NC}"
    echo "This will happen automatically in 30 seconds..."
    echo "Press Ctrl+C to cancel the reboot (you can reboot manually later)"

    # Countdown
    for i in {30..1}; do
        echo -ne "\rRebooting in $i seconds... "
        sleep 1
    done

    echo -e "\n${BLUE}Rebooting now...${NC}"
    sudo reboot
}

# Run the installation
main "$@"