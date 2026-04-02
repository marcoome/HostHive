#!/usr/bin/env bash
###############################################################################
# HostHive — Master Installer
# Supported OS: Debian 12 (Bookworm)
# This script is idempotent: running it multiple times will not break things.
###############################################################################
set -euo pipefail

# ─── Constants ───────────────────────────────────────────────────────────────
NOVAPANEL_DIR="/opt/novapanel"
CONFIG_DIR="${NOVAPANEL_DIR}/config"
SECRETS_FILE="${CONFIG_DIR}/secrets.env"
VENV_DIR="${NOVAPANEL_DIR}/venv"
FRONTEND_DIR="${NOVAPANEL_DIR}/frontend"
LOG_FILE="/var/log/novapanel-install.log"
PANEL_PORT=8083
API_PORT=8000
AGENT_PORT=7080
NOVAPANEL_USER="novapanel"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULES_DIR="${SCRIPT_DIR}/modules"

# ─── Colours / helpers ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[HostHive]${NC} $*" | tee -a "${LOG_FILE}"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $*" | tee -a "${LOG_FILE}"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" | tee -a "${LOG_FILE}" >&2; }
die()  { err "$@"; exit 1; }

# ─── Pre-flight checks ──────────────────────────────────────────────────────
[[ "$(id -u)" -eq 0 ]] || die "This installer must be run as root."

# Verify Debian 12
if [[ ! -f /etc/os-release ]]; then
    die "Cannot detect OS — /etc/os-release not found."
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "debian" ]] || [[ "${VERSION_ID:-}" != "12" ]]; then
    die "HostHive requires Debian 12 (Bookworm). Detected: ${PRETTY_NAME:-unknown}"
fi
log "Detected Debian 12 (Bookworm) — proceeding."

# ─── Create log file ────────────────────────────────────────────────────────
mkdir -p "$(dirname "${LOG_FILE}")"
touch "${LOG_FILE}"
chmod 640 "${LOG_FILE}"

# ─── 1. Update repositories & install packages ──────────────────────────────
log "Updating apt repositories..."
apt-get update -qq >> "${LOG_FILE}" 2>&1

PACKAGES=(
    nginx
    postgresql
    redis-server
    python3.11
    python3.11-venv
    python3-pip
    nodejs
    npm
    certbot
    python3-certbot-nginx
    bind9
    bind9utils
    exim4
    dovecot-core
    dovecot-imapd
    dovecot-pop3d
    spamassassin
    clamav
    proftpd-basic
    fail2ban
    ufw
    mariadb-server
    php8.2-fpm
    php8.2-cli
    php8.2-mysql
    php8.2-curl
    php8.2-mbstring
    git
    curl
    wget
    unzip
    htop
    # WAF: Naxsi-style WAF rules are managed natively via Nginx config;
    #      libnginx-mod-http-naxsi is optional for advanced rulesets.
    # libnginx-mod-http-naxsi
    # DKIM: OpenDKIM for email signing and verification
    opendkim
    opendkim-tools
    # Spam filtering: Rspamd (modern replacement for SpamAssassin)
    rspamd
    # Node.js process management: PM2 (installed via npm below)
    # Python app server: gunicorn + uvicorn (installed in venv)
    # DNS lookup tools for email auth verification
    dnsutils
)

log "Installing system packages (this may take a while)..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PACKAGES[@]}" >> "${LOG_FILE}" 2>&1
log "System packages installed."

# ─── 2. Create system user ──────────────────────────────────────────────────
if id "${NOVAPANEL_USER}" &>/dev/null; then
    log "System user '${NOVAPANEL_USER}' already exists — skipping."
else
    useradd --system --no-create-home --shell /usr/sbin/nologin "${NOVAPANEL_USER}"
    log "Created system user '${NOVAPANEL_USER}'."
fi

# ─── 3. Create directory structure ───────────────────────────────────────────
mkdir -p "${CONFIG_DIR}" "${NOVAPANEL_DIR}/logs" "${NOVAPANEL_DIR}/data" "${FRONTEND_DIR}"
chown -R "${NOVAPANEL_USER}:${NOVAPANEL_USER}" "${NOVAPANEL_DIR}"

# ─── 4. Generate secrets (idempotent — skip if file exists) ─────────────────
generate_password() {
    openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

if [[ -f "${SECRETS_FILE}" ]]; then
    log "Secrets file already exists — loading existing secrets."
    # shellcheck disable=SC1090
    source "${SECRETS_FILE}"
else
    DB_PASSWORD="$(generate_password)"
    REDIS_PASSWORD="$(generate_password)"
    ADMIN_PASSWORD="$(generate_password)"
    SECRET_KEY="$(generate_password)"

    cat > "${SECRETS_FILE}" <<SECRETS_EOF
# HostHive secrets — generated $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Do NOT share or commit this file.
DB_NAME=novapanel
DB_USER=novapanel
DB_PASSWORD=${DB_PASSWORD}
REDIS_PASSWORD=${REDIS_PASSWORD}
ADMIN_USER=admin
ADMIN_PASSWORD=${ADMIN_PASSWORD}
SECRET_KEY=${SECRET_KEY}
SECRETS_EOF

    chmod 600 "${SECRETS_FILE}"
    chown "${NOVAPANEL_USER}:${NOVAPANEL_USER}" "${SECRETS_FILE}"
    log "Generated secrets and stored in ${SECRETS_FILE}."
fi

# Re-source to ensure variables are available
# shellcheck disable=SC1090
source "${SECRETS_FILE}"

# ─── 5. Run modular setup scripts ───────────────────────────────────────────
run_module() {
    local module="$1"
    local path="${MODULES_DIR}/${module}"
    if [[ ! -x "${path}" ]]; then
        chmod +x "${path}"
    fi
    log "Running module: ${module}..."
    bash "${path}" 2>&1 | tee -a "${LOG_FILE}"
}

run_module "setup_postgresql.sh"
run_module "setup_redis.sh"
run_module "setup_nginx.sh"
run_module "setup_firewall.sh"
run_module "setup_fail2ban.sh"

# ─── 6. Python virtualenv & dependencies ────────────────────────────────────
if [[ -d "${VENV_DIR}" ]]; then
    log "Python virtualenv already exists — skipping creation."
else
    log "Creating Python virtualenv..."
    python3.11 -m venv "${VENV_DIR}"
fi

log "Installing Python packages into virtualenv..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip >> "${LOG_FILE}" 2>&1
"${VENV_DIR}/bin/pip" install --quiet \
    "fastapi" \
    "uvicorn[standard]" \
    "sqlalchemy[asyncio]" \
    "asyncpg" \
    "celery" \
    "redis" \
    "pydantic" \
    "passlib[bcrypt]" \
    "python-jose[cryptography]" \
    "python-multipart" \
    "aiofiles" \
    "paramiko" \
    "dnspython" \
    "slowapi" \
    "jinja2" \
    "httpx" \
    "cryptography" \
    >> "${LOG_FILE}" 2>&1
log "Python packages installed."

# ─── 7. Node.js via nvm + build frontend ────────────────────────────────────
export NVM_DIR="/opt/novapanel/.nvm"
if [[ -d "${NVM_DIR}" ]]; then
    log "nvm already installed — skipping download."
else
    log "Installing nvm..."
    mkdir -p "${NVM_DIR}"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | NVM_DIR="${NVM_DIR}" bash >> "${LOG_FILE}" 2>&1
fi

# Load nvm into current shell
# shellcheck disable=SC1091
[ -s "${NVM_DIR}/nvm.sh" ] && source "${NVM_DIR}/nvm.sh"

if command -v node &>/dev/null && [[ "$(node --version)" == v20.* ]]; then
    log "Node 20 LTS already installed."
else
    log "Installing Node 20 LTS via nvm..."
    nvm install 20 >> "${LOG_FILE}" 2>&1
    nvm alias default 20 >> "${LOG_FILE}" 2>&1
fi

# Build the Vue frontend if package.json exists
if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
    log "Building Vue frontend..."
    cd "${FRONTEND_DIR}"
    npm install --no-audit --no-fund >> "${LOG_FILE}" 2>&1
    npm run build >> "${LOG_FILE}" 2>&1
    cd -
    log "Frontend built."
else
    warn "No frontend package.json found at ${FRONTEND_DIR}/package.json — skipping build."
    # Create a placeholder index so Nginx has something to serve
    mkdir -p "${FRONTEND_DIR}/dist"
    cat > "${FRONTEND_DIR}/dist/index.html" <<'HTML_EOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>HostHive</title></head>
<body><h1>HostHive</h1><p>Frontend not yet built. Run the Vue build to replace this page.</p></body>
</html>
HTML_EOF
    chown -R "${NOVAPANEL_USER}:${NOVAPANEL_USER}" "${FRONTEND_DIR}"
fi

# ─── 8. Install systemd service files ───────────────────────────────────────
REPO_CONFIG_DIR="${SCRIPT_DIR}/../config"

install_service() {
    local name="$1"
    local src="${REPO_CONFIG_DIR}/${name}"
    local dest="/etc/systemd/system/${name}"

    if [[ ! -f "${src}" ]]; then
        warn "Service file ${src} not found — skipping."
        return
    fi

    cp "${src}" "${dest}"
    chmod 644 "${dest}"
    log "Installed systemd unit: ${name}"
}

install_service "novapanel-api.service"
install_service "novapanel-agent.service"
install_service "novapanel-worker.service"

systemctl daemon-reload

# Enable and start services
for svc in novapanel-api novapanel-agent novapanel-worker; do
    systemctl enable "${svc}.service" >> "${LOG_FILE}" 2>&1 || true
    systemctl restart "${svc}.service" >> "${LOG_FILE}" 2>&1 || warn "Could not start ${svc} — check logs."
done
log "Systemd services configured."

# ─── 9. Create initial admin user (idempotent) ──────────────────────────────
ADMIN_FLAG="${CONFIG_DIR}/.admin_created"
if [[ -f "${ADMIN_FLAG}" ]]; then
    log "Admin user already created — skipping."
else
    # Store admin credentials for the API to pick up on first boot
    cat > "${CONFIG_DIR}/initial_admin.json" <<ADMIN_EOF
{
    "username": "${ADMIN_USER:-admin}",
    "password": "${ADMIN_PASSWORD}",
    "email": "admin@localhost"
}
ADMIN_EOF
    chmod 600 "${CONFIG_DIR}/initial_admin.json"
    chown "${NOVAPANEL_USER}:${NOVAPANEL_USER}" "${CONFIG_DIR}/initial_admin.json"
    touch "${ADMIN_FLAG}"
    log "Initial admin credentials written."
fi

# ─── 10. Install PM2 for Node.js app management ───────────────────────────
if command -v npm &>/dev/null; then
    if ! command -v pm2 &>/dev/null; then
        log "Installing PM2 (Node.js process manager)..."
        npm install -g pm2 >> "${LOG_FILE}" 2>&1 || warn "PM2 install failed — Node.js apps will use systemd only."
    else
        log "PM2 already installed — skipping."
    fi
fi

# ─── 11. Install HostHive CLI symlink ──────────────────────────────────────
CLI_SCRIPT="${NOVAPANEL_DIR}/scripts/hosthive-cli.py"
CLI_LINK="/usr/local/bin/hosthive"

if [[ -f "${SCRIPT_DIR}/hosthive-cli.py" ]]; then
    cp "${SCRIPT_DIR}/hosthive-cli.py" "${CLI_SCRIPT}"
    chmod +x "${CLI_SCRIPT}"
    ln -sf "${CLI_SCRIPT}" "${CLI_LINK}"
    log "HostHive CLI installed: ${CLI_LINK} -> ${CLI_SCRIPT}"
else
    warn "hosthive-cli.py not found in ${SCRIPT_DIR} — CLI not installed."
fi

# ─── 12. Configure OpenDKIM (basic setup) ─────────────────────────────────
if command -v opendkim &>/dev/null; then
    mkdir -p /etc/opendkim/keys
    chown -R opendkim:opendkim /etc/opendkim
    systemctl enable opendkim >> "${LOG_FILE}" 2>&1 || true
    log "OpenDKIM base directories configured."
fi

# ─── 13. Configure Rspamd (basic setup) ───────────────────────────────────
if command -v rspamd &>/dev/null; then
    systemctl enable rspamd >> "${LOG_FILE}" 2>&1 || true
    log "Rspamd enabled."
fi

# ─── 14. Final ownership pass ──────────────────────────────────────────────
chown -R "${NOVAPANEL_USER}:${NOVAPANEL_USER}" "${NOVAPANEL_DIR}"

# ─── Done ────────────────────────────────────────────────────────────────────
HOST_IP="$(hostname -I | awk '{print $1}')"

echo ""
echo "==========================================================="
echo "  HostHive installation complete!"
echo "==========================================================="
echo ""
echo "  Panel URL : http://${HOST_IP}:${PANEL_PORT}"
echo "  Username  : ${ADMIN_USER:-admin}"
echo "  Password  : ${ADMIN_PASSWORD}"
echo ""
echo "  Secrets   : ${SECRETS_FILE}"
echo "  Logs      : ${LOG_FILE}"
echo ""
echo "  Services:"
echo "    systemctl status novapanel-api"
echo "    systemctl status novapanel-agent"
echo "    systemctl status novapanel-worker"
echo ""
echo "  IMPORTANT: Change the default admin password immediately!"
echo "==========================================================="
