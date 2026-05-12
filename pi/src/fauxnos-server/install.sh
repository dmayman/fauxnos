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
REPO_URL="${REPO_URL:-https://raw.githubusercontent.com/dmayman/fauxnos/main}"
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
    # `ir-keytable` is what fauxnos-client's IR listener spawns to read raw IR
    # scancodes; without it, fauxnos_client.py logs "IR listener: feature
    # disabled, not starting" and the remote is dead.
    sudo apt install -y \
        snapclient \
        mosquitto \
        mosquitto-clients \
        avahi-daemon \
        avahi-utils \
        ir-keytable \
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
    # `websocket-client` (NOT `websockets` — different package) is what
    # fauxnos-client/modules/go_librespot.py uses for the WS connection to
    # the go-librespot daemon. Without it, Spotify-mobile-app slider changes
    # don't propagate to fauxnos UI and the warning
    #   "websocket-client not installed — Spotify-side volume changes will
    #    not propagate to fauxnos"
    # appears in fauxnos-client logs at startup.
    pip3 install --user flask flask-cors requests websockets websocket-client paho-mqtt paramiko --break-system-packages

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

    # Snapcast .deb assets are named like:
    #   snapserver_0.31.0-1_arm64_bookworm.deb
    #   snapserver_0.31.0-1_arm64_bullseye.deb
    # Read the OS codename from /etc/os-release so we pick the matching asset.
    local codename
    codename=$(. /etc/os-release && echo "${VERSION_CODENAME:-}")
    if [ -z "$codename" ]; then
        log_error "Could not determine Debian codename from /etc/os-release"
        return 1
    fi

    local deb_file="snapserver_${SNAPCAST_TARGET_VERSION}-1_${deb_arch}_${codename}.deb"
    local url="https://github.com/badaix/snapcast/releases/download/v${SNAPCAST_TARGET_VERSION}/${deb_file}"
    local tmp_deb="/tmp/${deb_file}"

    log "Downloading snapserver ${SNAPCAST_TARGET_VERSION} for ${deb_arch}/${codename}..."
    if ! curl -fsSL "$url" -o "$tmp_deb"; then
        log_error "Download failed: $url"
        log_error "Check that snapcast v${SNAPCAST_TARGET_VERSION} has a build for ${deb_arch}/${codename}."
        return 1
    fi
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

    # Local-development mode: skip the GitHub download and assume the caller
    # has already pushed source files into $INSTALL_DIR (e.g. via rsync from
    # a dev machine). Set FAUXNOS_LOCAL=1 to enable.
    if [ "${FAUXNOS_LOCAL:-0}" = "1" ]; then
        log "FAUXNOS_LOCAL=1 — skipping GitHub download, using files already at $INSTALL_DIR"
        if [ ! -f "$INSTALL_DIR/fauxnos-server.py" ]; then
            log_error "FAUXNOS_LOCAL=1 but $INSTALL_DIR/fauxnos-server.py is missing. Push the source tree first (scripts/push-to-pi.sh)."
            return 1
        fi
        cd "$INSTALL_DIR"
        chmod +x fauxnos-server.py 2>/dev/null || true
        log_success "Using local files at $INSTALL_DIR"
        return 0
    fi

    mkdir -p "$(dirname "$INSTALL_DIR")"

    if [ -d "$INSTALL_DIR" ]; then
        log "Removing existing installation at $INSTALL_DIR..."
        rm -rf "$INSTALL_DIR"
    fi

    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    log "Downloading server files..."

    # server_config.json is NOT in this list anymore — it's runtime state
    # (registered clients, home_groups, deployed SHAs), gitignored, and
    # auto-created from configs/server_config.json.template by
    # config_manager.ConfigManager._ensure_config_exists() on first start.
    local files=(
        "fauxnos-server.py"
        "requirements.txt"
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
        "modules/install_runner.py"
        "modules/dac_overlays.py"
    )

    # The web UI is React + Vite. index.html references hashed asset files
    # (web/assets/index-XXXXXX.{js,css}) that change every build, so we only
    # list index.html here and parse it for asset paths after download.
    local web_files=(
        "web/index.html"
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
        # server_config.json is no longer in the download list — it's runtime
        # state, gitignored, auto-created from the template by config_manager.
        # Old preserve-on-rerun branch removed (was a workaround for the file
        # being tracked in git).
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

    # Pull the hashed React assets that web/index.html references. Vite emits
    # filenames like web/assets/index-DDCOYkvc.js that change every build, so
    # we extract them from the just-downloaded index.html instead of hard-
    # coding. If index.html is missing (download failed), this is a no-op.
    if [ -f "web/index.html" ]; then
        mkdir -p web/assets
        local asset_paths
        asset_paths=$(grep -oE '/assets/[A-Za-z0-9_.-]+\.(js|css)' web/index.html 2>/dev/null | sort -u || true)
        if [ -n "$asset_paths" ]; then
            for asset_path in $asset_paths; do
                local asset_file="web${asset_path}"  # e.g. web/assets/index-DDCOYkvc.js
                local asset_url="${REPO_URL}/pi/src/fauxnos-server/${asset_file}"
                if curl -fsSL "$asset_url" -o "${asset_file}" 2>/dev/null; then
                    log "Downloaded: ${asset_file}"
                else
                    log_warning "Failed to download: ${asset_file}"
                fi
            done
        else
            log_warning "No /assets/* references found in web/index.html — UI may be broken"
        fi
    fi

    # Download the full fauxnos-client tree. The server device IS also a
    # client (server-as-client architecture: fauxnos000 runs a
    # fauxnos-client-fauxnos000 daemon for its own room), so it needs the
    # whole client codebase locally — not just the bootstrap install.sh.
    # The wizard also serves these files to fresh client Pis via the API,
    # so they're useful for that path too.
    #
    # Without this, fauxnos-client-fauxnos000.service hits
    #   ModuleNotFoundError: No module named 'modules.config_manager'
    # and restart-loops forever, dragging IR + per-source volume sync down
    # with it.
    mkdir -p "../fauxnos-client"
    cd "../fauxnos-client"

    local client_root_files=(
        "install.sh"
        "fauxnos_client.py"
        "setup-client.py"
        "requirements.txt"
        "client_config.yaml.template"
    )
    local client_modules=(
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
    local client_configs=(
        "configs/config.yaml.template"
        "configs/pulseaudio/default.pa"
        "configs/systemd/fauxnos-client.service"
        "configs/systemd/snapclient.service"
    )

    mkdir -p modules configs/pulseaudio configs/systemd sounds

    for file in "${client_root_files[@]}" "${client_modules[@]}" "${client_configs[@]}"; do
        local url="${REPO_URL}/pi/src/fauxnos-client/${file}"
        if curl -fsSL "$url" -o "$file"; then
            log "Downloaded: fauxnos-client/$file"
        else
            log_warning "Failed to download fauxnos-client/$file"
        fi
    done

    # IR feedback sounds. Volume-N tone files are named volume-NNN.wav for
    # N in 0..100 step 5, plus mute / unmute / source_switch / volume_up /
    # volume_down. fauxnos-client/modules/ir_listener.py looks them up from
    # the package-relative `sounds/` dir at startup.
    local sound_files=(
        "sounds/mute.wav"
        "sounds/unmute.wav"
        "sounds/source_switch.wav"
        "sounds/volume_up.wav"
        "sounds/volume_down.wav"
    )
    for n in 000 005 010 015 020 025 030 035 040 045 050 \
             055 060 065 070 075 080 085 090 095 100; do
        sound_files+=("sounds/volume-${n}.wav")
    done
    for file in "${sound_files[@]}"; do
        local url="${REPO_URL}/pi/src/fauxnos-client/${file}"
        curl -fsSL "$url" -o "$file" 2>/dev/null \
            && log "Downloaded: fauxnos-client/$file" \
            || log_warning "Failed to download fauxnos-client/$file"
    done

    chmod +x install.sh fauxnos_client.py setup-client.py 2>/dev/null || true

    cd "$INSTALL_DIR"
    chmod +x fauxnos-server.py 2>/dev/null || true

    log_success "Server + client code downloaded to: $INSTALL_DIR + ../fauxnos-client"
}

# ─── Step 5b: Server SSH identity for client install runner ──────────────────
#
# The Add Device wizard (web UI) drives client installs by SSHing into a
# freshly-flashed Pi as `user@fauxnos-client.local` and running install.sh
# end-to-end. That requires a key the server itself owns — the user pastes
# this .pub into Pi Imager's "Allow public-key authentication only" field
# alongside their personal 1Password key. Idempotent: skip if already there.
setup_install_keypair() {
    log_section "Setting Up Server SSH Identity"
    local ssh_dir="$HOME/.ssh"
    local key="$ssh_dir/id_ed25519_fauxnos"

    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"
    touch "$ssh_dir/known_hosts"
    chmod 600 "$ssh_dir/known_hosts"

    if [ -f "$key" ] && [ -f "$key.pub" ]; then
        log "Server install keypair already exists at $key"
    else
        log "Generating Ed25519 install keypair (no passphrase)..."
        ssh-keygen -t ed25519 -N "" -C "fauxnos-server@$(hostname)" -f "$key" >/dev/null
        log_success "Generated $key"
    fi
    chmod 600 "$key"
    chmod 644 "$key.pub"
    log "Server public key (paste into Pi Imager when flashing a client):"
    cat "$key.pub" | tee -a "$LOG_FILE"
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

    # Enable IR kernel decoders at boot (NEC for the fauxnos remote)
    log "Installing IR decoder boot service..."
    _install_ir_decoders_service

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

    # Add a mosquitto WebSocket listener on port 9001. The web UI's mqtt.js
    # client connects via ws://<host>:9001 for real-time volume/mode updates.
    # Without this, status/clients/+/volume MQTT messages reach the broker
    # but the browser cannot subscribe, so the UI's volume slider doesn't
    # follow Spotify-side changes.
    if [ ! -f /etc/mosquitto/conf.d/websockets.conf ]; then
        log "Adding mosquitto WebSocket listener on port 9001..."
        sudo tee /etc/mosquitto/conf.d/websockets.conf > /dev/null <<'MOSQ_WS'
# Web UI connects via mqtt.js over WebSocket. Without this listener the
# browser cannot subscribe to status/clients/+/* and real-time volume
# sync between Spotify and the UI does not work.
listener 9001
protocol websockets
allow_anonymous true

# Keep the standard TCP listener too (for fauxnos_client / mosquitto_sub).
listener 1883
protocol mqtt
allow_anonymous true
MOSQ_WS
        sudo systemctl restart mosquitto
        log_success "Mosquitto WebSocket listener configured on port 9001"
    fi

    # Disable system snapserver and snapclient (we run them as user services
    # with our own configs and --hostID so they integrate with the rest of
    # the fauxnos pipeline). The apt postinsts auto-enable both system units;
    # leaving them on causes duplicate snapcast clients to register against
    # snapserver — one under MAC (system unit, no --hostID) and one under
    # fauxnos000 (our user unit) — which surfaces as two groups in the UI.
    sudo systemctl stop snapserver snapclient 2>/dev/null || true
    sudo systemctl disable snapserver snapclient 2>/dev/null || true

    # snapserver's apt postinst creates /tmp/snapfifo as a named pipe (its
    # default source). Our user-mode setup-fifo.sh wants /tmp/snapfifo to be a
    # *directory* and can't `rm` a non-user-owned file in /tmp (sticky bit).
    # Clean it up here while we still have sudo.
    if [ -e /tmp/snapfifo ] && [ ! -d /tmp/snapfifo ]; then
        sudo rm -f /tmp/snapfifo
        log "Removed leftover /tmp/snapfifo from snapserver default config"
    fi

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

    # GPIO IR receiver overlay. The fauxnos remote-receiver hardware is wired
    # to GPIO17 (3.3V on the receiver's VS line — GPIO is NOT 5V-tolerant).
    # Without this overlay, the kernel only registers /sys/class/rc/rc0 as
    # rc-cec (HDMI CEC); fauxnos-client's IR listener has no gpio_ir_recv
    # device to attach to and the remote silently does nothing. Idempotent —
    # drops any prior line first so changing pin numbers in a future revision
    # just works.
    sudo sed -i '/^dtoverlay=gpio-ir/d' "$config_txt"
    echo "dtoverlay=gpio-ir,gpio_pin=17" | sudo tee -a "$config_txt" > /dev/null
    log "Added: dtoverlay=gpio-ir,gpio_pin=17 → $config_txt"
    log_success "HiFiBerry overlay set to $dtoverlay in $config_txt"
}

# The gpio-ir overlay creates /sys/class/rc/rcN, but the kernel defaults to
# [rc-6] + [lirc] active — neither matches the fauxnos remote (NEC extended).
# Without this, `ir-keytable -t` reads from the device but the kernel emits no
# scancodes and the remote silently does nothing. fauxnos-client's IR listener
# uses `-t` test mode which does NOT touch protocols, so the protocol bit has
# to be set elsewhere. We install a system oneshot that writes `+nec` to the
# protocols file for whichever rc device is a gpio_ir_recv (rc0 on a no-CEC
# Pi, sometimes rc1 if HDMI CEC claimed rc0 first).
_install_ir_decoders_service() {
    local helper="/usr/local/bin/fauxnos-ir-enable-decoders.sh"
    local unit="/etc/systemd/system/fauxnos-ir-decoders.service"

    sudo tee "$helper" > /dev/null <<'IR_ENABLE_SH'
#!/bin/sh
# Enable NEC decoder on whichever rc-core device is a gpio_ir_recv.
# Idempotent: writing "+nec" to /sys/class/rc/rcN/protocols is additive and
# safe to re-run.
set -e
for d in /sys/class/rc/rc*; do
    [ -e "$d/uevent" ] || continue
    if grep -q "DRV_NAME=gpio_ir_recv" "$d/uevent"; then
        echo +nec > "$d/protocols"
        echo "fauxnos-ir: enabled nec on $d"
    fi
done
IR_ENABLE_SH
    sudo chmod +x "$helper"

    sudo tee "$unit" > /dev/null <<UNIT
[Unit]
Description=Fauxnos: enable IR kernel decoders on gpio_ir_recv
After=systemd-modules-load.service
Before=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$helper

[Install]
WantedBy=multi-user.target
UNIT

    sudo systemctl daemon-reload
    sudo systemctl enable fauxnos-ir-decoders.service
    sudo systemctl start fauxnos-ir-decoders.service || true
    log_success "fauxnos-ir-decoders.service installed and started"
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

    # Bookworm ships with PipeWire as the default audio server. Its
    # pulse-compatibility shim (pipewire-pulse) takes ownership of the
    # /run/user/$UID/pulse/native socket, so even though pulseaudio is
    # installed and "enabled", it can never actually run. PipeWire also
    # silently ignores ~/.config/pulse/default.pa, so our virtual sinks
    # (snapsink, analogsink, systemsink) never get loaded — fauxnos_client
    # then errors with "Failed to get sink information: No such entity".
    #
    # We need real PulseAudio. Mask the PipeWire user units, ensure
    # pulseaudio is unmasked + enabled, and start it.
    log "Disabling PipeWire user services (we need real PulseAudio)..."
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

    mkdir -p "$HOME/.config/pulse"

    local pa_source="$INSTALL_DIR/configs/pulseaudio/default.pa"
    if [ -f "$pa_source" ]; then
        cp "$pa_source" "$HOME/.config/pulse/default.pa"
        log_success "PulseAudio config deployed from $pa_source"
    else
        log_warning "PulseAudio config not found at $pa_source, using default"
    fi

    # Start PulseAudio now (so the rest of the install can talk to it)
    systemctl --user start pulseaudio.socket pulseaudio.service 2>/dev/null || true
    sleep 1
    if pactl info 2>/dev/null | grep -q "^Server Name: pulseaudio$"; then
        log_success "PulseAudio is the active audio server"
        log "Loaded sinks: $(pactl list short sinks 2>/dev/null | awk '{print $2}' | tr '\n' ' ')"
    else
        log_warning "PulseAudio did not start cleanly; check 'systemctl --user status pulseaudio'"
    fi
}

# ─── Step 8: Initialize server config and self-register ───────────────────────
initialize_server_config() {
    log_section "Initializing Server Configuration"

    cd "$INSTALL_DIR"

    # Ensure server_config.json exists + is valid JSON. config_manager would
    # also auto-create from template on first ConfigManager() instantiation,
    # but we do it here so the file is in place before `fauxnos-server.py
    # add-client` runs below (and so the install log makes it visible).
    if [ ! -f "server_config.json" ] || ! python3 -c "import json; json.load(open('server_config.json'))" 2>/dev/null; then
        if [ -f "configs/server_config.json.template" ]; then
            log "Creating server_config.json from template..."
            cp configs/server_config.json.template server_config.json
        else
            log_error "Missing configs/server_config.json.template — bad install state"
            return 1
        fi
    else
        log "Preserving existing server_config.json ($(python3 -c "import json; print(len(json.load(open('server_config.json'))['clients']))") clients registered)"
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

    # ── Server-as-client (fauxnos_client.py daemon for fauxnos000) ───
    # The server is also a first-class audio endpoint, so it runs the
    # same fauxnos_client.py daemon as every other client. This is what
    # subscribes to MQTT set/clients/fauxnos000/{volume,mode} and
    # publishes status/clients/fauxnos000/{volume,mode,activity,hello}.
    # Without this, the web UI's volume slider has no subscriber on the
    # server side and Spotify-source MQTT status is one-way only.
    log "Setting up fauxnos_client daemon for server-as-client..."

    mkdir -p "$HOME/.config/fauxnos" "$HOME/logs" "$HOME/src/fauxnos-client"

    # Resolve our actual MAC. Prefer wlan0 since most Pis are on WiFi —
    # snapclient's hostID lookup will work either way (we look up by
    # device.name / hostID, not MAC), but having the right MAC keeps
    # diagnostics accurate.
    local client_mac
    client_mac=$(cat /sys/class/net/wlan0/address 2>/dev/null \
                || cat /sys/class/net/eth0/address 2>/dev/null \
                || echo "00:00:00:00:00:00")

    # Determine analog source availability: only include if a HiFiBerry
    # DAC+ADC (or other ADC-capable HAT) is present. Detection: the
    # hifiberry-dacplusadc overlay we set in _configure_hifiberry implies
    # ADC. Could refine with /proc/device-tree/hat/product later.
    local analog_section=""
    if grep -q "^dtoverlay=hifiberry-dacplusadc" /boot/firmware/config.txt 2>/dev/null \
       || grep -q "^dtoverlay=hifiberry-dacplusadc" /boot/config.txt 2>/dev/null; then
        analog_section="
  - id: analog
    label: Analog In
    type: internal
    sink: analogsink
    starting_volume: 50
    volume_controller: self
    pa_calibration: 100"
    fi

    cat > "$HOME/.config/fauxnos/client_config.yaml" <<CLIENTCFG
# Fauxnos Client Configuration — Server-as-client (fauxnos000)
# Generated by install.sh. Edit to taste, but keep server_host: localhost.

device:
  name: fauxnos000
  mac: "$client_mac"
  display_name: Server

# Server is on this same machine, so snapcast/MQTT are local.
server_host: localhost

sources:
  - id: spotify
    label: Spotify
    type: internal
    sink: snapsink
    starting_volume: 50
    volume_controller: snapcast
    pa_calibration: 50           # snap loopback ceiling — Spotify is loud out of the box$analog_section

logging:
  file: ~/logs/fauxnos-client.log
  level: INFO

state_file: ~/.config/fauxnos/client_state.json

mqtt:
  broker_host: localhost
  broker_port: 1883
  enabled: true
CLIENTCFG

    # The fauxnos_client.py daemon expects to live at ~/src/fauxnos-client/
    # along with its modules/. push-to-pi.sh (or download_client_code in the
    # client install path) populates this. If we got here via the server
    # install with FAUXNOS_LOCAL=1, the dev workflow already placed the
    # files there.
    if [ ! -f "$HOME/src/fauxnos-client/fauxnos_client.py" ]; then
        log_warning "fauxnos_client.py missing at ~/src/fauxnos-client/. Push it (scripts/push-to-pi.sh) before starting fauxnos-client-fauxnos000.service."
    fi

    cat > "$HOME/.config/systemd/user/fauxnos-client-fauxnos000.service" <<SERVICE
[Unit]
Description=Fauxnos Client Daemon for fauxnos000 (server-as-client)
After=snapclient-fauxnos000.service mosquitto.service pulseaudio.service
Wants=snapclient-fauxnos000.service mosquitto.service

[Service]
Type=simple
WorkingDirectory=$HOME/src/fauxnos-client
ExecStart=/usr/bin/python3 $HOME/src/fauxnos-client/fauxnos_client.py --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
SERVICE

    log_success "Systemd service files created (including fauxnos-client-fauxnos000)"
}

# ─── Step 11: Enable and start all services ────────────────────────────────────
enable_services() {
    log_section "Enabling and Starting Services"

    systemctl --user daemon-reload

    local user_services=(
        "fauxnos-fifo-setup"
        "fauxnos-fifo-pinner"
        "snapserver"
        "fauxnos-server"
        "snapclient-fauxnos000"
        "fauxnos-client-fauxnos000"
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
    setup_install_keypair
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
