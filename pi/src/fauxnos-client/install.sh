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

    # Set temporary hostname
    local mac_suffix
    mac_suffix=$(cat /sys/class/net/*/address | head -1 | sed 's/://g' | tail -c 5)
    local temp_hostname="${TEMP_HOSTNAME_PREFIX}-${mac_suffix}"

    log "Setting temporary hostname to: $temp_hostname"
    sudo hostnamectl set-hostname "$temp_hostname"
    sudo sed -i "s/127.0.1.1.*/127.0.1.1\t$temp_hostname/" /etc/hosts

    log_success "System configuration completed"
}

# Download fauxnos-client code
download_client_code() {
    log_section "Downloading Fauxnos Client"

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

    # Download all client files
    local files=(
        "setup-client.py"
        "fauxnos-client.py"
        "README.md"
        "TESTING.md"
        "install.sh"
        "pi-setup.sh"
        "requirements.txt"
    )

    # Download config files
    local config_files=(
        "configs/pulseaudio/default.pa"
        "configs/systemd/snapclient.service"
        "configs/systemd/fauxnos-client.service"
    )

    for file in "${files[@]}"; do
        local url="${REPO_URL}/pi/src/fauxnos-client/$file"
        if curl -fsSL "$url" -o "$file"; then
            log "Downloaded: $file"
        else
            log_warning "Failed to download: $file (may not exist yet)"
        fi
    done

    # Download config files with directory creation
    for file in "${config_files[@]}"; do
        local url="${REPO_URL}/pi/src/fauxnos-client/$file"
        local dir=$(dirname "$file")
        mkdir -p "$dir"
        if curl -fsSL "$url" -o "$file"; then
            log "Downloaded config: $file"
        else
            log_warning "Failed to download config: $file"
        fi
    done

    # Make scripts executable
    chmod +x setup-client.py 2>/dev/null || true
    chmod +x fauxnos-client.py 2>/dev/null || true
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
    if python3 setup-client.py --setup; then
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

    # Check if config exists
    if [ -f "$INSTALL_DIR/config.json" ]; then
        log_success "Client configuration found"
        local client_id
        client_id=$(jq -r '.client_id' "$INSTALL_DIR/config.json" 2>/dev/null || echo "unknown")
        log "Client ID: $client_id"
    else
        log_error "Client configuration missing"
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

    local client_id
    if [ -f "$INSTALL_DIR/config.json" ]; then
        client_id=$(jq -r '.client_id // "unknown"' "$INSTALL_DIR/config.json" 2>/dev/null)
        local display_name
        display_name=$(jq -r '.display_name // "Unknown"' "$INSTALL_DIR/config.json" 2>/dev/null)
        echo -e "${BLUE}Client ID:${NC} $client_id"
        echo -e "${BLUE}Display Name:${NC} $display_name"
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
main() {
    log_section "Fauxnos Client Installation Starting"
    log "Installation log: $LOG_FILE"

    check_user
    check_prerequisites
    install_system_dependencies
    configure_system
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