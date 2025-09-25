#!/bin/bash

# Fauxnos Pi Setup Script
# Prepares a fresh Raspberry Pi OS install for Fauxnos client onboarding

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAUXNOS_USER="${SUDO_USER:-${USER}}"
FAUXNOS_HOME="/home/${FAUXNOS_USER}"
CLIENT_SRC_DIR="${FAUXNOS_HOME}/src/fauxnos-client"
TEMP_HOSTNAME_PREFIX="fauxnos-temp"

# Flags
DRY_RUN=false
TEST_MODE=false
SKIP_REBOOT=false
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Prepares a Raspberry Pi OS install for Fauxnos client registration.

OPTIONS:
    --dry-run       Show what would be done without making changes
    --test          Use test configuration and skip system modifications
    --skip-reboot   Don't reboot at the end (useful for testing)
    --verbose       Show detailed output
    -h, --help      Show this help message

EXAMPLES:
    # Test what would happen without making changes
    $0 --dry-run

    # Run in test mode (safe for existing systems)
    $0 --test --skip-reboot

    # Full installation on fresh Pi
    sudo $0
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

    if [ "$TEST_MODE" = true ] && [[ "$cmd" =~ (apt|systemctl|reboot|hostnamectl) ]]; then
        log "TEST MODE: Skipping system command: $cmd"
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

    # Check if running on Raspberry Pi (unless in test mode)
    if [ "$TEST_MODE" = false ]; then
        if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
            log_warning "This doesn't appear to be a Raspberry Pi"
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi

    # Check for sudo if not in test mode
    if [ "$TEST_MODE" = false ] && [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi

    # Check internet connectivity
    if ! ping -c 1 8.8.8.8 &> /dev/null; then
        log_error "No internet connectivity detected"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

update_system() {
    log "Updating system packages..."
    execute "apt update" "Updating package lists"
    execute "apt upgrade -y" "Upgrading system packages"
}

install_dependencies() {
    log "Installing Fauxnos dependencies..."

    local packages=(
        "snapclient"
        "pulseaudio"
        "pulseaudio-utils"
        "alsa-utils"
        "avahi-daemon"
        "avahi-utils"
        "curl"
        "jq"
        "git"
        "python3"
        "python3-pip"
        "python3-venv"
    )

    for package in "${packages[@]}"; do
        execute "apt install -y $package" "Installing $package"
    done
}

setup_audio_permissions() {
    log "Setting up audio permissions for user: $FAUXNOS_USER"

    execute "usermod -a -G audio $FAUXNOS_USER" "Adding user to audio group"
    execute "usermod -a -G pulse-access $FAUXNOS_USER" "Adding user to pulse-access group"
}

download_fauxnos_client() {
    log "Setting up Fauxnos client code..."

    local src_url="https://raw.githubusercontent.com/user/fauxnos/main/pi/src/fauxnos-client"

    if [ "$TEST_MODE" = true ]; then
        # In test mode, copy from local development
        local local_src="$SCRIPT_DIR/../pi/src/fauxnos-client"
        if [ -d "$local_src" ]; then
            execute "cp -r '$local_src' '$CLIENT_SRC_DIR'" "Copying local fauxnos-client"
        else
            execute "mkdir -p '$CLIENT_SRC_DIR'" "Creating client directory"
            execute "echo '# Test client placeholder' > '$CLIENT_SRC_DIR/README.md'" "Creating test placeholder"
        fi
    else
        execute "mkdir -p '$CLIENT_SRC_DIR'" "Creating client source directory"
        # TODO: Replace with actual download once repo is public
        execute "echo '# Fauxnos client will be downloaded here' > '$CLIENT_SRC_DIR/README.md'" "Creating client placeholder"
    fi

    execute "chown -R $FAUXNOS_USER:$FAUXNOS_USER '$FAUXNOS_HOME/src'" "Setting ownership of source directory"
}

setup_temporary_hostname() {
    log "Setting up temporary hostname..."

    local mac_suffix
    mac_suffix=$(cat /sys/class/net/*/address | head -1 | sed 's/://g' | tail -c 5)
    local temp_hostname="${TEMP_HOSTNAME_PREFIX}-${mac_suffix}"

    execute "hostnamectl set-hostname '$temp_hostname'" "Setting temporary hostname to $temp_hostname"

    # Update /etc/hosts
    execute "sed -i 's/127.0.1.1.*/127.0.1.1\t$temp_hostname/' /etc/hosts" "Updating /etc/hosts"

    log_success "Temporary hostname set to: $temp_hostname"
}

create_setup_script() {
    log "Creating client setup script..."

    local setup_script="$CLIENT_SRC_DIR/setup-client.py"

    cat > "$setup_script" << 'EOF'
#!/usr/bin/env python3
"""
Fauxnos Client Setup Script
Handles registration with server and configuration deployment
"""

import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description='Fauxnos Client Setup')
    parser.add_argument('--setup', action='store_true', help='Run client registration')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--test', action='store_true', help='Use test configuration')

    args = parser.parse_args()

    if args.setup:
        print("Client registration would run here")
        if args.dry_run:
            print("DRY RUN: Would register with server")
        elif args.test:
            print("TEST MODE: Would use test server")
        else:
            print("Would register with production server")
    else:
        print("Use --setup to register this client")

if __name__ == '__main__':
    main()
EOF

    execute "chmod +x '$setup_script'" "Making setup script executable"
    execute "chown $FAUXNOS_USER:$FAUXNOS_USER '$setup_script'" "Setting ownership of setup script"
}

enable_services() {
    log "Enabling required services..."

    execute "systemctl enable avahi-daemon" "Enabling Avahi daemon"
    execute "systemctl start avahi-daemon" "Starting Avahi daemon"
}

print_next_steps() {
    log_success "Pi setup completed successfully!"
    echo
    echo -e "${GREEN}Next steps:${NC}"
    echo "1. Reboot this Pi (will happen automatically unless --skip-reboot)"
    echo "2. After reboot, run client registration:"
    echo -e "   ${BLUE}cd ~/src/fauxnos-client${NC}"
    echo -e "   ${BLUE}python3 setup-client.py --setup${NC}"
    echo
    echo -e "${YELLOW}For testing:${NC}"
    echo -e "   ${BLUE}python3 setup-client.py --setup --dry-run${NC}"
    echo -e "   ${BLUE}python3 setup-client.py --setup --test${NC}"
    echo

    if [ "$TEST_MODE" = true ]; then
        log_warning "TEST MODE: No system changes were made"
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --test)
            TEST_MODE=true
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

    if [ "$TEST_MODE" = true ]; then
        log_warning "TEST MODE: System modifications will be skipped"
    fi

    check_prerequisites

    if [ "$TEST_MODE" = false ]; then
        update_system
        install_dependencies
        setup_audio_permissions
        setup_temporary_hostname
        enable_services
    fi

    download_fauxnos_client
    create_setup_script

    print_next_steps

    # Reboot unless skipped
    if [ "$SKIP_REBOOT" = false ] && [ "$DRY_RUN" = false ] && [ "$TEST_MODE" = false ]; then
        log "Rebooting in 5 seconds... (Ctrl+C to cancel)"
        sleep 5
        reboot
    fi
}

main "$@"