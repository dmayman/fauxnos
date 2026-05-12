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

# Reboot-needed marker. Touched by mark_reboot_needed() whenever something
# reboot-sensitive changes (dtparam= line, dtoverlay= line, newly-installed
# apt packages). The update orchestrator (server side) reads this file over
# SSH after install.sh completes to decide whether to prompt for a reboot.
# Cleared at start of every run so a stale marker from a previous install
# never causes a false reboot prompt.
NEEDS_REBOOT_MARKER=/tmp/fauxnos-install-needs-reboot
rm -f "$NEEDS_REBOOT_MARKER"

mark_reboot_needed() {
    local reason="$1"
    touch "$NEEDS_REBOOT_MARKER"
    log_warning "Reboot will be needed: $reason"
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

    # Count installed packages before + after so we can mark reboot-needed
    # if anything new actually landed. apt-installed packages occasionally
    # bring in kernel modules or systemd-units that only activate on next
    # boot, so when we're in update mode we want the orchestrator to know.
    local pkg_count_before pkg_count_after
    pkg_count_before=$(dpkg -l 2>/dev/null | awk '/^ii/{n++} END{print n+0}')

    log "Installing core dependencies..."
    sudo apt install -y \
        snapclient \
        shairport-sync \
        mosquitto-clients \
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
        python3-requests \
        ir-keytable \
        python3-evdev

    log "Installing Python packages..."
    pip3 install --user requests pyyaml paho-mqtt websocket-client --break-system-packages

    pkg_count_after=$(dpkg -l 2>/dev/null | awk '/^ii/{n++} END{print n+0}')
    if [ "$pkg_count_after" -gt "$pkg_count_before" ]; then
        mark_reboot_needed "$((pkg_count_after - pkg_count_before)) new apt package(s) installed"
    fi

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

    # Configure DAC dt-overlay
    # FAUXNOS_DAC_OVERLAY is injected by firstrun.sh (which the server
    # generates with a per-install default — see modules/dac_overlays.py
    # DEFAULT_OVERLAY). If unset (legacy direct invocations), default to
    # allo-boss-dac-pcm512x-audio: it drives both genuine Allo Boss and
    # INNO-MAKER PCM5122 hats with the full PCM512x mixer enabled.
    # Users with a HiFiBerry can switch via the Devices tab after install
    # (Apply button rewrites this exact line and reboots).
    local overlay="${FAUXNOS_DAC_OVERLAY:-allo-boss-dac-pcm512x-audio}"
    case "$overlay" in
        hifiberry-dac|hifiberry-dacplus|hifiberry-dacplusadc|allo-boss-dac-pcm512x-audio|iqaudio-dacplus) ;;
        *)
            log_error "Unknown FAUXNOS_DAC_OVERLAY: '$overlay'"
            log_error "Allowed: hifiberry-dac, hifiberry-dacplus, hifiberry-dacplusadc, allo-boss-dac-pcm512x-audio, iqaudio-dacplus"
            exit 1
            ;;
    esac

    log "Configuring DAC overlay: $overlay"
    local config_txt="/boot/firmware/config.txt"
    local legacy_config_txt="/boot/config.txt"

    # Check which config file exists (newer Pi OS uses /boot/firmware/)
    if [ -f "$config_txt" ]; then
        config_txt="/boot/firmware/config.txt"
    elif [ -f "$legacy_config_txt" ]; then
        config_txt="$legacy_config_txt"
    fi

    if [ -f "$config_txt" ]; then
        # Disable onboard audio to avoid conflicts
        if ! grep -q "^dtparam=audio=off" "$config_txt"; then
            echo "dtparam=audio=off" | sudo tee -a "$config_txt" > /dev/null
            log "Disabled onboard audio"
            mark_reboot_needed "added dtparam=audio=off"
        fi

        # Strip every overlay we manage so re-running install with a
        # different overlay choice doesn't leave stragglers behind, then
        # write the chosen one. Idempotent — and on an update run we only
        # mark reboot-needed if the active overlay actually changed.
        local existing_dac_line new_dac_line
        existing_dac_line=$(grep -m1 -E '^dtoverlay=(hifiberry|allo-|iqaudio-)' "$config_txt" || true)
        new_dac_line="dtoverlay=$overlay"

        if [ "$existing_dac_line" != "$new_dac_line" ]; then
            sudo sed -i '/^dtoverlay=hifiberry/d; /^dtoverlay=allo-/d; /^dtoverlay=iqaudio-/d' "$config_txt"
            echo "$new_dac_line" | sudo tee -a "$config_txt" > /dev/null
            mark_reboot_needed "DAC overlay changed: '${existing_dac_line:-<none>}' → '$new_dac_line'"
            log_success "DAC overlay set to '$overlay' in $config_txt"
        else
            log "DAC overlay already set to '$overlay' — no change"
        fi
    else
        log_error "Could not find config.txt file"
    fi

    # On an update run (install.sh re-invoked against a device that's
    # already provisioned), the hostname is already fauxnosNNN. Bouncing
    # it through fauxnos-temp-XXXX and back is pointless and leaves the
    # device in a temp state if the server becomes unreachable mid-install.
    # Only rename if we're starting from a non-fauxnos hostname (fresh
    # install path).
    local current_hostname
    current_hostname=$(hostname)
    if [[ "$current_hostname" =~ ^fauxnos[0-9]{3}$ ]]; then
        log "Hostname already configured as $current_hostname — skipping temp-hostname rename"
    else
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
    fi

    log_success "System configuration completed"
}

# Configure GPIO IR receiver
#
# Sets up the kernel side of the optional hardware-remote feature so the
# userspace listener (modules/ir_listener.py) has something to read from.
# The userspace mapping is per-device state — flipping ir.enabled in the
# web UI activates/deactivates the listener without touching anything
# here. We always install the overlay + decoder service: cost is one
# kernel module + a few KB of resident driver state, and it means a Pi
# can pick up IR with no extra install steps later.
#
# Wiring (VS1838B → 40-pin header):
#   VS1838B VCC → pin 1  (3.3V)
#   VS1838B GND → pin 6  (GND)
#   VS1838B OUT → pin 11 (GPIO17)
#
# 3.3V (not 5V) keeps the receiver's OUT line in spec for the Pi's GPIO,
# which is NOT 5V-tolerant. GPIO17 is the gpio-ir overlay default and is
# free on every audio HAT we ship (HiFiBerry DAC+ADC + Allo Boss both
# use I2S on GPIO 18–21 + I2C on GPIO 2/3).
configure_ir_receiver() {
    log_section "Configuring IR Receiver"

    local config_txt
    if [ -f "/boot/firmware/config.txt" ]; then
        config_txt="/boot/firmware/config.txt"
    elif [ -f "/boot/config.txt" ]; then
        config_txt="/boot/config.txt"
    else
        log_warning "Could not find config.txt — skipping IR overlay setup"
        return 0
    fi

    # Idempotent: drop any prior gpio-ir line (so re-runs with a future
    # different pin replace cleanly) and re-add. Pin 17 is the rc-core
    # default; the userspace listener doesn't currently expose pin
    # selection in the UI. On an update run we only mark reboot-needed
    # when the active line actually changes.
    local existing_ir_line new_ir_line
    existing_ir_line=$(grep -m1 '^dtoverlay=gpio-ir' "$config_txt" || true)
    new_ir_line="dtoverlay=gpio-ir,gpio_pin=17"

    if [ "$existing_ir_line" != "$new_ir_line" ]; then
        sudo sed -i '/^dtoverlay=gpio-ir/d' "$config_txt"
        echo "$new_ir_line" | sudo tee -a "$config_txt" > /dev/null
        mark_reboot_needed "gpio-ir overlay changed: '${existing_ir_line:-<none>}' → '$new_ir_line'"
        log "Added: $new_ir_line → $config_txt"
    else
        log "gpio-ir overlay already configured — no change"
    fi

    # ir-keytable enables individual protocol decoders on the rc-core
    # receiver at runtime. Without this, /dev/lirc0 exists but
    # /dev/input/eventN never emits scancodes because no protocol module
    # is loaded for the receiver's allowed_protocols mask.
    #
    # The right rc-core device (rcN) varies by hardware: on a Pi with
    # HDMI CEC enabled, the CEC driver also exposes itself via rc-core,
    # so probe order determines whether gpio_ir_recv is rc0 or rc1.
    # We install a small helper script that scans /sys/class/rc/ for
    # DRV_NAME=gpio_ir_recv and uses whichever device matched. Keeps
    # the systemd ExecStart line readable and mirrors the discovery
    # logic in modules/ir_listener.py (Python side).
    log "Installing /usr/local/bin/fauxnos-ir-enable-decoders.sh..."
    sudo tee /usr/local/bin/fauxnos-ir-enable-decoders.sh > /dev/null <<'EOF'
#!/bin/sh
# fauxnos-ir-enable-decoders — find the gpio_ir_recv rc-core device
# and enable the IR protocol decoders we care about. Retries up to
# 5 seconds for the overlay's probe to complete.

set -e
TARGET_DRV=gpio_ir_recv
PROTOCOLS="nec,rc-5,rc-6,jvc,sony,sanyo,sharp,xmp,imon"

find_rc() {
    for r in /sys/class/rc/rc*; do
        [ -d "$r" ] || continue
        drv=$(awk -F= '/^DRV_NAME=/ {print $2}' "$r/uevent" 2>/dev/null)
        if [ "$drv" = "$TARGET_DRV" ]; then
            basename "$r"
            return 0
        fi
    done
    return 1
}

for attempt in 1 2 3 4 5; do
    if rc=$(find_rc); then
        echo "fauxnos-ir: enabling [$PROTOCOLS] on $rc"
        exec /usr/bin/ir-keytable -p "$PROTOCOLS" -s "$rc"
    fi
    sleep 1
done

echo "fauxnos-ir: no rc-core device with DRV_NAME=$TARGET_DRV after 5s" >&2
exit 1
EOF
    sudo chmod +x /usr/local/bin/fauxnos-ir-enable-decoders.sh

    log "Installing fauxnos-ir-decoders.service (boot-time protocol enabler)..."
    sudo tee /etc/systemd/system/fauxnos-ir-decoders.service > /dev/null <<'EOF'
[Unit]
Description=Fauxnos: enable IR protocol decoders on the gpio_ir_recv rc-core device
# The rc-core devices appear after the gpio-ir overlay's probe; the
# helper script polls for up to 5s if no matching device is registered
# yet. ConditionPathExistsGlob short-circuits cleanly on systems
# without any rc-core devices at all (e.g. /sys/class/rc absent).
After=systemd-modules-load.service
ConditionPathExistsGlob=/sys/class/rc/rc*

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/fauxnos-ir-enable-decoders.sh

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable fauxnos-ir-decoders.service > /dev/null 2>&1 || true
    # Best-effort start now; on first install the overlay isn't loaded
    # yet so rc0 won't exist — ConditionPathExists short-circuits and
    # the unit will run cleanly after the post-install reboot.
    sudo systemctl start fauxnos-ir-decoders.service 2>/dev/null || true

    # The userland listener (modules/ir_listener.py) runs as the regular
    # user and shells out to `ir-keytable -t`, which reads the rc-core
    # device's /dev/input/eventN node. RPi OS udev defaults set that
    # node's group to either `input` or `video` depending on the rc
    # subsystem — add the user to BOTH so the listener works regardless.
    # Group membership takes effect on next login; install.sh reboots at
    # the end, so the new groups are live by the time fauxnos-client
    # tries to spawn the listener.
    log "Adding $USER to input + video groups for IR access..."
    sudo usermod -a -G input "$USER" 2>/dev/null || true
    sudo usermod -a -G video "$USER" 2>/dev/null || true

    log_success "IR receiver configured (active after reboot)"
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
        "configs/systemd/shairport-sync-fauxnos.service"
        "configs/shairport-sync/fauxnos.conf"
        "configs/shairport-sync/claim-source.sh"
    )

    # Python modules
    local module_files=(
        "modules/__init__.py"
        "modules/config_manager.py"
        "modules/go_librespot.py"
        "modules/ir_listener.py"
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
    configure_ir_receiver
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

    # Reboot decision:
    #   - FAUXNOS_NO_REBOOT=1 (set by the update orchestrator on the server)
    #     means "hand the decision back to me — I'll inspect the marker
    #     file and reboot over SSH if it's there." We exit cleanly here so
    #     the SSE stream gets a clean termination.
    #   - Unset (the interactive `curl | bash` first-install path) means
    #     "auto-reboot after a 30s countdown" — preserves the original
    #     behavior so nothing changes for users running install.sh directly.
    if [ "${FAUXNOS_NO_REBOOT:-0}" = "1" ]; then
        if [ -f "$NEEDS_REBOOT_MARKER" ]; then
            log_warning "FAUXNOS_NO_REBOOT=1 — skipping reboot, but install touched reboot-sensitive state"
            log_warning "Orchestrator can read $NEEDS_REBOOT_MARKER to decide whether to reboot the device"
        else
            log "FAUXNOS_NO_REBOOT=1 and no reboot-sensitive changes detected — exiting without reboot"
        fi
        exit 0
    fi

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