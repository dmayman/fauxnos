#!/bin/bash

# Fauxnos Server - One-Command Install
# =====================================
# Bootstrap script for the Fauxnos server device (fauxnos000).
# Run as regular user (not root) on a fresh Raspberry Pi OS Bookworm installation.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/dmayman/fauxnos/main/pi/src/fauxnos-server/install.sh | bash
#
# What this does:
# 1. Installs all system dependencies (snapserver, go-librespot, mosquitto, etc.)
# 2. Downloads the fauxnos-server code
# 3. Sets hostname to fauxnos000 and configures HiFiBerry audio
# 4. Sets up PulseAudio and enables user service lingering
# 5. Self-registers as fauxnos000 and runs initial deploy
# 6. Starts all services and validates
# 7. Reboots

set -e

# ─── Configuration ───────────────────────────────────────────────────────────
REPO_URL="https://raw.githubusercontent.com/dmayman/fauxnos/main"
INSTALL_DIR="$HOME/src/fauxnos-server"
LOG_FILE="/tmp/fauxnos-server-install.log"
SERVER_HOSTNAME="fauxnos000"
SNAPCAST_MIN_VERSION="0.30"
SNAPCAST_TARGET_VERSION="0.31.0"
GO_LIBRESPOT_VERSION="latest"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Logging ─────────────────────────────────────────────────────────────────
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

cleanup_on_error() {
    log_error "Installation failed! Check log at: $LOG_FILE"
    log_error "You can retry the installation by running this script again"
    exit 1
}
trap cleanup_on_error ERR

# ─── Step 1: Pre-flight checks ────────────────────────────────────────────────
check_user() {
    log_section "Pre-flight Checks"

    if [ "$EUID" -eq 0 ]; then
        log_error "Do not run as root! Run as regular user with sudo privileges"
        exit 1
    fi

    if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        log_warning "This doesn't appear to be a Raspberry Pi"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    if ! ping -c 1 8.8.8.8 &>/dev/null; then
        log_error "No internet connectivity detected"
        exit 1
    fi

    log_success "Pre-flight checks passed"
}

# ─── Step 2: Enable persistent journal (critical for debugging) ───────────────
enable_journal_persistence() {
    log_section "Enabling Persistent Journal"

    if grep -q "^Storage=persistent" /etc/systemd/journald.conf 2>/dev/null; then
        log "Journal persistence already enabled"
    else
        sudo sed -i 's/#\?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf 2>/dev/null || \
            echo "Storage=persistent" | sudo tee -a /etc/systemd/journald.conf > /dev/null
        sudo systemctl restart systemd-journald
        log_success "Journal persistence enabled"
    fi
}

# ─── Step 3: System dependencies ─────────────────────────────────────────────
install_system_dependencies() {
    log_section "Installing System Dependencies"

    log "Updating package lists..."
    sudo apt update -y

    log "Installing core packages..."
    sudo apt install -y \
        snapclient \
        mosquitto \
        mosquitto-clients \
        avahi-daemon \
        avahi-utils \
        shairport-sync \
        python3 \
        python3-pip \
        python3-yaml \
        git \
        curl \
        jq \
        openssh-server \
        alsa-utils \
        pulseaudio \
        pulseaudio-utils

    # Install snapserver — check if apt version is recent enough
    local apt_snap_ver
    apt_snap_ver=$(apt-cache show snapserver 2>/dev/null | grep "^Version:" | head -1 | awk '{print $2}' | cut -d. -f1,2 || echo "0.0")
    if awk -v v="$apt_snap_ver" -v min="$SNAPCAST_MIN_VERSION" 'BEGIN{exit (v < min) ? 0 : 1}'; then
        log "apt snapserver $apt_snap_ver is too old (need $SNAPCAST_MIN_VERSION+), downloading from GitHub..."
        _install_snapserver_from_github
    else
        log "Installing snapserver from apt (version $apt_snap_ver)..."
        sudo apt install -y snapserver
    fi

    log "Installing Python packages..."
    pip3 install --user flask flask-cors requests websockets paho-mqtt --break-system-packages

    log_success "System dependencies installed"
}

_install_snapserver_from_github() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        aarch64) local deb_arch="arm64" ;;
        armv7l)  local deb_arch="armhf" ;;
        x86_64)  local deb_arch="amd64" ;;
        *)        log_error "Unknown arch: $arch"; return 1 ;;
    esac

    local deb_file="snapserver_${SNAPCAST_TARGET_VERSION}-1_${deb_arch}.deb"
    local url="https://github.com/badaix/snapcast/releases/download/v${SNAPCAST_TARGET_VERSION}/${deb_file}"
    local tmp_deb="/tmp/${deb_file}"

    log "Downloading snapserver ${SNAPCAST_TARGET_VERSION} for ${deb_arch}..."
    curl -fsSL "$url" -o "$tmp_deb"
    sudo dpkg -i "$tmp_deb" || sudo apt-get install -f -y
    rm -f "$tmp_deb"
    log_success "snapserver ${SNAPCAST_TARGET_VERSION} installed"
}

# ─── Step 4: Install go-librespot ─────────────────────────────────────────────
install_go_librespot() {
    log_section "Installing go-librespot"

    if [ -f "/usr/local/bin/go-librespot" ]; then
        log "go-librespot already installed at /usr/local/bin/go-librespot"
        log_success "go-librespot ready"
        return
    fi

    local arch
    arch=$(uname -m)
    case "$arch" in
        aarch64) local go_arch="arm64" ;;
        armv7l)  local go_arch="armv7" ;;
        x86_64)  local go_arch="amd64" ;;
        *)        log_error "Unknown arch: $arch"; return 1 ;;
    esac

    local tarball="go-librespot_linux_${go_arch}.tar.gz"
    local api_url="https://api.github.com/repos/devgianlu/go-librespot/releases/latest"

    log "Fetching latest go-librespot release info..."
    local download_url
    download_url=$(curl -fsSL "$api_url" | jq -r --arg name "$tarball" '.assets[] | select(.name==$name) | .browser_download_url')

    if [ -z "$download_url" ]; then
        log_error "Could not find go-librespot download URL for $tarball"
        return 1
    fi

    log "Downloading $tarball..."
    local tmp_dir
    tmp_dir=$(mktemp -d)
    curl -fsSL "$download_url" -o "$tmp_dir/$tarball"
    tar -xzf "$tmp_dir/$tarball" -C "$tmp_dir"

    local binary
    binary=$(find "$tmp_dir" -name "go-librespot" -type f | head -1)
    if [ -z "$binary" ]; then
        log_error "go-librespot binary not found in tarball"
        rm -rf "$tmp_dir"
        return 1
    fi

    sudo install -m 755 "$binary" /usr/local/bin/go-librespot
    rm -rf "$tmp_dir"

    log_success "go-librespot installed to /usr/local/bin/go-librespot"
}

# ─── Step 5: Download server code ─────────────────────────────────────────────
download_server_code() {
    log_section "Downloading Fauxnos Server Code"

    mkdir -p "$(dirname "$INSTALL_DIR")"

    if [ -d "$INSTALL_DIR" ]; then
        log "Removing existing installation at $INSTALL_DIR..."
        rm -rf "$INSTALL_DIR"
    fi

    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    log "Downloading server files..."

    local files=(
        "fauxnos-server.py"
        "requirements.txt"
        "server_config.json"
    )

    local module_files=(
        "modules/__init__.py"
        "modules/config_manager.py"
        "modules/api_server.py"
        "modules/deploy.py"
        "modules/cleanup.py"
        "modules/group_manager.py"
        "modules/client_monitor.py"
        "modules/volume_manager.py"
    )

    local web_files=(
        "web/index.html"
        "web/app.js"
        "web/style.css"
    )

    local test_files=(
        "tests/__init__.py"
        "tests/test_utils.py"
        "tests/test_server_health.py"
        "tests/test_api.py"
        "tests/test_snapcast.py"
        "tests/test_registration.py"
        "tests/run_tests.py"
    )

    local config_files=(
        "configs/server_config.json.template"
        "configs/pulseaudio/default.pa"
        "configs/avahi/fauxnos.service"
    )

    mkdir -p modules web tests configs/pulseaudio configs/avahi

    for file in "${files[@]}" "${module_files[@]}" "${web_files[@]}" "${test_files[@]}" "${config_files[@]}"; do
        local url="${REPO_URL}/pi/src/fauxnos-server/$file"
        local dir
        dir=$(dirname "$file")
        mkdir -p "$dir"
        if curl -fsSL "$url" -o "$file" 2>/dev/null; then
            log "Downloaded: $file"
        else
            log_warning "Failed to download: $file (may not exist yet)"
        fi
    done

    # Also download client install.sh so API can serve it
    mkdir -p "../fauxnos-client"
    local client_url="${REPO_URL}/pi/src/fauxnos-client/install.sh"
    if curl -fsSL "$client_url" -o "../fauxnos-client/install.sh"; then
        chmod +x "../fauxnos-client/install.sh"
        log "Downloaded: fauxnos-client/install.sh"
    else
        log_warning "Failed to download client install.sh"
    fi

    chmod +x fauxnos-server.py 2>/dev/null || true

    log_success "Server code downloaded to: $INSTALL_DIR"
}

# ─── Step 6: System configuration ─────────────────────────────────────────────
configure_system() {
    log_section "Configuring System"

    # Set hostname to fauxnos000
    log "Setting hostname to $SERVER_HOSTNAME..."
    sudo hostnamectl set-hostname "$SERVER_HOSTNAME"
    # Update /etc/hosts
    if grep -q "127.0.1.1" /etc/hosts; then
        sudo sed -i "s/127.0.1.1.*/127.0.1.1\t$SERVER_HOSTNAME/" /etc/hosts
    else
        echo -e "127.0.1.1\t$SERVER_HOSTNAME" | sudo tee -a /etc/hosts > /dev/null
    fi
    log_success "Hostname set to $SERVER_HOSTNAME"

    # Enable user service lingering
    log "Enabling user service lingering..."
    sudo loginctl enable-linger "$USER"

    # Add user to audio groups
    log "Configuring audio permissions..."
    sudo usermod -a -G audio "$USER" 2>/dev/null || true
    sudo usermod -a -G pulse-access "$USER" 2>/dev/null || true

    # Configure HiFiBerry
    log "Configuring HiFiBerry audio..."
    _configure_hifiberry

    # Register avahi _fauxnos._tcp service for client auto-discovery
    log "Registering fauxnos mDNS service..."
    _register_avahi_service

    # Enable system services
    log "Enabling system services..."
    sudo systemctl enable avahi-daemon
    sudo systemctl start avahi-daemon || true
    sudo systemctl enable ssh
    sudo systemctl start ssh || true
    sudo systemctl enable mosquitto
    sudo systemctl start mosquitto || true

    # Disable system snapserver (we run it as user service)
    sudo systemctl stop snapserver 2>/dev/null || true
    sudo systemctl disable snapserver 2>/dev/null || true

    log_success "System configuration completed"
}

_configure_hifiberry() {
    # Server hardware is fixed: HiFiBerry DAC+ADC. No detection — just set it.
    # (Clients are also fixed at hifiberry-dac in the client install.sh.)
    # Auto-detection was removed because the HAT EEPROM isn't always
    # programmed/readable, and `aplay -l` parsing has a chicken-and-egg
    # bootstrap problem on first install.
    local dtoverlay="hifiberry-dacplusadc"

    local config_txt
    if [ -f "/boot/firmware/config.txt" ]; then
        config_txt="/boot/firmware/config.txt"
    elif [ -f "/boot/config.txt" ]; then
        config_txt="/boot/config.txt"
    else
        log_warning "config.txt not found, skipping HiFiBerry configuration"
        return
    fi

    # Disable onboard audio (idempotent: only appends if not already off)
    if ! grep -q "^dtparam=audio=off" "$config_txt"; then
        sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$config_txt"
        if ! grep -q "^dtparam=audio=off" "$config_txt"; then
            echo "dtparam=audio=off" | sudo tee -a "$config_txt" > /dev/null
        fi
        log "Disabled onboard audio"
    fi

    # Replace any existing hifiberry overlay with the server's overlay
    sudo sed -i '/^dtoverlay=hifiberry/d' "$config_txt"
    echo "dtoverlay=$dtoverlay" | sudo tee -a "$config_txt" > /dev/null
    log_success "HiFiBerry overlay set to $dtoverlay in $config_txt"
}

_register_avahi_service() {
    local avahi_service_dir="/etc/avahi/services"
    local avahi_service_file="$avahi_service_dir/fauxnos.service"

    # Use bundled file if downloaded, otherwise generate inline
    local source_file="$INSTALL_DIR/configs/avahi/fauxnos.service"
    if [ -f "$source_file" ]; then
        sudo cp "$source_file" "$avahi_service_file"
    else
        sudo tee "$avahi_service_file" > /dev/null <<'AVAHI_XML'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Fauxnos Server (%h)</name>
  <service>
    <type>_fauxnos._tcp</type>
    <port>8080</port>
    <txt-record>version=1.0</txt-record>
    <txt-record>role=server</txt-record>
  </service>
</service-group>
AVAHI_XML
    fi

    sudo systemctl restart avahi-daemon || true
    log_success "Fauxnos mDNS service registered"
}

# ─── Step 7: PulseAudio configuration ─────────────────────────────────────────
setup_pulseaudio() {
    log_section "Setting Up PulseAudio"

    mkdir -p "$HOME/.config/pulse"

    local pa_source="$INSTALL_DIR/configs/pulseaudio/default.pa"
    if [ -f "$pa_source" ]; then
        cp "$pa_source" "$HOME/.config/pulse/default.pa"
        log_success "PulseAudio config deployed from $pa_source"
    else
        log_warning "PulseAudio config not found at $pa_source, using default"
    fi
}

# ─── Step 8: Initialize server config and self-register ───────────────────────
initialize_server_config() {
    log_section "Initializing Server Configuration"

    cd "$INSTALL_DIR"

    # Ensure server_config.json has the right structure
    if [ ! -f "server_config.json" ] || ! python3 -c "import json; json.load(open('server_config.json'))" 2>/dev/null; then
        log "Creating fresh server_config.json..."
        cat > server_config.json <<'JSON'
{
  "server": {
    "snapcast": {
      "host": "localhost",
      "port": 1705
    },
    "mqtt": {
      "broker_host": "localhost",
      "broker_port": 1883
    },
    "paths": {
      "fifo_base": "/tmp/snapfifo",
      "go_librespot_config_base": "~/.config/go-librespot"
    }
  },
  "clients": []
}
JSON
    fi

    # Check if fauxnos000 is already registered
    if python3 -c "
import json
c = json.load(open('server_config.json'))
ids = [x['id'] for x in c.get('clients', [])]
exit(0 if 'fauxnos000' not in ids else 1)
" 2>/dev/null; then
        # Not yet registered — add fauxnos000 (server device)
        log "Self-registering as fauxnos000..."
        local mac
        mac=$(cat /sys/class/net/eth0/address 2>/dev/null || \
              cat /sys/class/net/wlan0/address 2>/dev/null || \
              ip link show | grep "link/ether" | head -1 | awk '{print $2}' || \
              echo "00:00:00:00:00:00")

        python3 fauxnos-server.py add-client \
            --name "Server" \
            --mac "$mac" \
            --is-server-device \
            --no-deploy \
            --no-assign
        log_success "Self-registered as fauxnos000 (MAC: $mac)"
    else
        log "fauxnos000 already registered in config"
    fi
}

# ─── Step 9: Initial deploy (configs, scripts, services) ──────────────────────
run_initial_deploy() {
    log_section "Running Initial Deploy"

    cd "$INSTALL_DIR"

    log "Deploying server infrastructure (go-librespot configs, snapserver.conf, FIFOs)..."
    if python3 fauxnos-server.py deploy-server; then
        log_success "Server infrastructure deployed"
    else
        log_error "Deploy failed — check logs above"
        return 1
    fi
}

# ─── Step 10: Create fauxnos-server systemd service ───────────────────────────
create_server_service() {
    log_section "Creating Systemd Services"

    mkdir -p "$HOME/.config/systemd/user"

    # fauxnos-server service (runs the Flask API + monitoring daemon)
    cat > "$HOME/.config/systemd/user/fauxnos-server.service" <<SERVICE
[Unit]
Description=Fauxnos Server Daemon
After=network.target mosquitto.service

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/fauxnos-server.py run
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SERVICE

    # snapclient service for server's own audio (fauxnos000 plays locally)
    cat > "$HOME/.config/systemd/user/snapclient-fauxnos000.service" <<SERVICE
[Unit]
Description=Snapcast Client for fauxnos000 (local server audio)
After=network.target fauxnos-fifo-setup.service snapserver.service
Requires=snapserver.service

[Service]
Type=simple
ExecStart=/usr/bin/snapclient --hostID fauxnos000 --host 127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
SERVICE

    log_success "Systemd service files created"
}

# ─── Step 11: Enable and start all services ────────────────────────────────────
enable_services() {
    log_section "Enabling and Starting Services"

    systemctl --user daemon-reload

    local user_services=(
        "fauxnos-fifo-setup"
        "snapserver"
        "fauxnos-server"
        "snapclient-fauxnos000"
    )

    # Add go-librespot services for all registered clients
    local client_ids
    client_ids=$(python3 -c "
import json, sys
try:
    c = json.load(open('$INSTALL_DIR/server_config.json'))
    print(' '.join(x['id'] for x in c.get('clients', [])))
except:
    pass
" 2>/dev/null || true)

    for cid in $client_ids; do
        user_services+=("go-librespot-${cid}")
    done

    for svc in "${user_services[@]}"; do
        if systemctl --user enable "$svc" 2>/dev/null; then
            log "Enabled: $svc"
        else
            log_warning "Could not enable: $svc (may not exist yet)"
        fi
    done

    # Start in order: FIFO first, then snapserver, then go-librespot, then clients
    log "Starting fauxnos-fifo-setup..."
    systemctl --user start fauxnos-fifo-setup || log_warning "fauxnos-fifo-setup failed to start"

    log "Starting snapserver..."
    systemctl --user start snapserver || log_warning "snapserver failed to start"
    sleep 2

    log "Starting go-librespot instances..."
    for cid in $client_ids; do
        systemctl --user start "go-librespot-${cid}" || log_warning "go-librespot-${cid} failed to start"
    done

    log "Starting snapclient-fauxnos000..."
    systemctl --user start snapclient-fauxnos000 || log_warning "snapclient-fauxnos000 failed to start"

    log "Starting fauxnos-server..."
    systemctl --user start fauxnos-server || log_warning "fauxnos-server failed to start"

    log_success "Services enabled and started"
}

# ─── Step 12: Validate installation ───────────────────────────────────────────
validate_installation() {
    log_section "Validating Installation"

    local errors=0

    # Wait for API to come up (up to 30s)
    log "Waiting for API server to start (up to 30s)..."
    local retries=0
    local api_ok=false
    while [ $retries -lt 30 ]; do
        if curl -sf http://localhost:8080/api/status &>/dev/null; then
            api_ok=true
            break
        fi
        sleep 1
        retries=$((retries + 1))
    done

    if $api_ok; then
        log_success "API server responding on port 8080"
    else
        log_error "API server not responding on port 8080 after 30s"
        errors=$((errors + 1))
    fi

    # Check snapcast
    if python3 -c "
import socket, json
s = socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 1705))
s.send(b'{\"jsonrpc\":\"2.0\",\"method\":\"Server.GetStatus\",\"id\":1}\r\n')
d = s.recv(4096); json.loads(d); print('ok')
" 2>/dev/null | grep -q "ok"; then
        log_success "Snapcast JSON-RPC responding on port 1705"
    else
        log_warning "Snapcast not responding on port 1705 (may still be starting)"
    fi

    # Check MQTT
    if nc -z localhost 1883 2>/dev/null; then
        log_success "MQTT (mosquitto) listening on port 1883"
    else
        log_warning "MQTT not responding on port 1883"
    fi

    # Check mDNS (fauxnos000.local should resolve to self)
    if avahi-resolve -n fauxnos000.local &>/dev/null; then
        log_success "mDNS: fauxnos000.local resolves"
    else
        log_warning "mDNS fauxnos000.local not resolving (avahi may need a moment)"
    fi

    # Check service statuses
    for svc in snapserver fauxnos-server; do
        if systemctl --user is-active "$svc" &>/dev/null; then
            log_success "Service running: $svc"
        else
            log_warning "Service not active: $svc"
            errors=$((errors + 1))
        fi
    done

    if [ $errors -eq 0 ]; then
        log_success "All validation checks passed!"
    else
        log_warning "$errors check(s) failed — review logs above"
    fi

    return $errors
}

# ─── Completion message ────────────────────────────────────────────────────────
print_completion_message() {
    local ip
    ip=$(hostname -I | awk '{print $1}')

    echo -e "\n${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║   Fauxnos Server Installation Complete!          ║${NC}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${NC}\n"

    echo -e "${BOLD}Server Details:${NC}"
    echo -e "  Hostname:   fauxnos000.local"
    echo -e "  IP Address: $ip"
    echo -e ""
    echo -e "${BOLD}Management Web UI:${NC}"
    echo -e "  http://fauxnos000.local:8080"
    echo -e "  http://$ip:8080"
    echo -e ""
    echo -e "${BOLD}Add a new client device:${NC}"
    echo -e "  1. Open the web UI → 'Add Device' tab"
    echo -e "  2. Download firstrun.sh"
    echo -e "  3. Copy to SD card boot partition"
    echo -e "  4. Insert card + power on Pi"
    echo -e ""
    echo -e "${BOLD}Direct install URL for clients:${NC}"
    echo -e "  http://fauxnos000.local:8080/api/install/client.sh"
    echo -e ""
    echo -e "${BOLD}Run tests after reboot:${NC}"
    echo -e "  cd ~/src/fauxnos-server && python3 tests/run_tests.py"
    echo -e ""
    echo -e "${YELLOW}Rebooting in 30 seconds... (Ctrl+C to cancel)${NC}"
}

# ─── Main ─────────────────────────────────────────────────────────────────────
main() {
    echo -e "\n${BOLD}${BLUE}Fauxnos Server Installer${NC}"
    echo -e "Log: $LOG_FILE\n"

    check_user
    enable_journal_persistence
    install_system_dependencies
    install_go_librespot
    download_server_code
    configure_system
    setup_pulseaudio
    initialize_server_config
    run_initial_deploy
    create_server_service
    enable_services
    validate_installation || true  # Don't fail on validation warnings

    print_completion_message

    # 30-second countdown reboot
    for i in $(seq 30 -1 1); do
        printf "\r${YELLOW}Rebooting in %2d seconds... (Ctrl+C to cancel)${NC}" "$i"
        sleep 1
    done
    echo ""
    sudo reboot
}

main "$@"
