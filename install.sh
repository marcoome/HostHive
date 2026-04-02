#!/bin/bash
#======================================================================
#   HostHive — One-Line Installer Bootstrap
#   Usage: bash <(curl -sSL https://raw.githubusercontent.com/marcoome/HostHive/main/install.sh)
#======================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'; BOLD='\033[1m'
REPO="https://github.com/marcoome/HostHive.git"
INSTALL_DIR="/opt/hosthive"

echo -e "${BOLD}HostHive Installer Bootstrap${NC}\n"

# Must be root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: Run as root: sudo bash install.sh${NC}"
    exit 1
fi

# Install git if missing
if ! command -v git &>/dev/null; then
    echo -e "Installing git..."
    apt-get update -qq && apt-get install -y -qq git
fi

# Clone or update repo
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo -e "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull
else
    echo -e "Downloading HostHive..."
    rm -rf "$INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
fi

# Run main installer
cd "$INSTALL_DIR"
bash install-hosthive.sh
