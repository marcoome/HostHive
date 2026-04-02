#!/bin/bash
#======================================================================
#   HostHive — One-Line Installer Bootstrap
#
#   Usage:
#     bash <(curl -sSL https://raw.githubusercontent.com/marcoome/HostHive/main/install.sh)
#     — or —
#     wget -qO- https://raw.githubusercontent.com/marcoome/HostHive/main/install.sh | bash
#     — or —
#     curl -fsSL https://raw.githubusercontent.com/marcoome/HostHive/main/install.sh | bash
#======================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
REPO="https://github.com/marcoome/HostHive.git"
INSTALL_DIR="/opt/hosthive"

echo ""
echo -e "${BOLD}${CYAN}HostHive Installer Bootstrap${NC}"
echo ""

# Must be root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: Run as root:${NC} curl -fsSL https://raw.githubusercontent.com/marcoome/HostHive/main/install.sh | bash"
    exit 1
fi

# Install git if missing
if ! command -v git &>/dev/null; then
    echo -e "  ${DIM}Installing git...${NC}"
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq git >/dev/null 2>&1
fi

# Install curl if missing (needed by installer for NodeSource)
if ! command -v curl &>/dev/null; then
    echo -e "  ${DIM}Installing curl...${NC}"
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq curl >/dev/null 2>&1
fi

# Clone or update repo
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo -e "  ${GREEN}✓${NC} Updating existing installation..."
    cd "$INSTALL_DIR"
    git fetch origin main >> /dev/null 2>&1
    git reset --hard origin/main >> /dev/null 2>&1
else
    echo -e "  ${DIM}Downloading HostHive...${NC}"
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
fi

echo -e "  ${GREEN}✓${NC} Source code ready"
echo ""

# Run main installer
cd "$INSTALL_DIR"
exec bash install-hosthive.sh "$@"
