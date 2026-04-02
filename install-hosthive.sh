#!/bin/bash
#======================================================================
#
#   ██╗  ██╗ ██████╗ ███████╗████████╗██╗  ██╗██╗██╗   ██╗███████╗
#   ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝██║  ██║██║██║   ██║██╔════╝
#   ███████║██║   ██║███████╗   ██║   ███████║██║██║   ██║█████╗
#   ██╔══██║██║   ██║╚════██║   ██║   ██╔══██║██║╚██╗ ██╔╝██╔══╝
#   ██║  ██║╚██████╔╝███████║   ██║   ██║  ██║██║ ╚████╔╝ ███████╗
#   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚══════╝
#
#   HostHive — Modern Hosting Control Panel
#   One-command installer for Debian 12/13 (Bookworm/Trixie)
#
#   Usage:
#     wget https://get.hosthive.io/install.sh && sudo bash install.sh
#     — or —
#     curl -fsSL https://get.hosthive.io/install.sh | sudo bash
#
#======================================================================
set -euo pipefail

# ─── Colors & formatting ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

# ─── Branding ───
PRODUCT_NAME="HostHive"
PRODUCT_VERSION="1.0.0"
INSTALL_DIR="/opt/hosthive"
CONFIG_DIR="${INSTALL_DIR}/config"
LOG_DIR="${INSTALL_DIR}/logs"
LOG_FILE="${LOG_DIR}/install.log"

# Resolve the directory where this script lives (for copying source files)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Create base dirs early so logging works ───
mkdir -p "${LOG_DIR}"
mkdir -p "${CONFIG_DIR}"
touch "$LOG_FILE"

# ─── Helpers ───
print_header() {
    clear
    echo -e "${PURPLE}"
    echo "  ██╗  ██╗ ██████╗ ███████╗████████╗██╗  ██╗██╗██╗   ██╗███████╗"
    echo "  ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝██║  ██║██║██║   ██║██╔════╝"
    echo "  ███████║██║   ██║███████╗   ██║   ███████║██║██║   ██║█████╗  "
    echo "  ██╔══██║██║   ██║╚════██║   ██║   ██╔══██║██║╚██╗ ██╔╝██╔══╝  "
    echo "  ██║  ██║╚██████╔╝███████║   ██║   ██║  ██║██║ ╚████╔╝ ███████╗"
    echo "  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚══════╝"
    echo -e "${NC}"
    echo -e "  ${WHITE}${BOLD}Modern Hosting Control Panel${NC} ${DIM}v${PRODUCT_VERSION}${NC}"
    echo ""
}

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

step() {
    local step_num=$1
    local total=$2
    local msg=$3
    echo -e "  ${CYAN}[${step_num}/${total}]${NC} ${WHITE}${msg}${NC}"
    log "STEP ${step_num}/${total}: ${msg}"
}

success() {
    echo -e "  ${GREEN}  ✓${NC} ${DIM}$1${NC}"
    log "OK: $1"
}

warn() {
    echo -e "  ${YELLOW}  ⚠${NC} $1"
    log "WARN: $1"
}

fail() {
    echo -e "\n  ${RED}  ✗ ERROR: $1${NC}"
    log "FAIL: $1"
    echo -e "  ${DIM}Check log: ${LOG_FILE}${NC}\n"
    exit 1
}

spinner() {
    local pid=$1
    local msg=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${BLUE}  ${spin:i++%${#spin}:1}${NC} ${DIM}${msg}${NC}"
        sleep 0.1
    done
    printf "\r"
}

generate_password() {
    openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

# ─── Pre-flight checks ───
TOTAL_STEPS=13

print_header

echo -e "  ${WHITE}${BOLD}Pre-flight checks${NC}\n"

# Must be root
if [[ $EUID -ne 0 ]]; then
    fail "This installer must be run as root. Use: sudo bash install-hosthive.sh"
fi

# Check Debian 12/13
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" != "debian" ]] || [[ ! "$VERSION_ID" =~ ^1[23]$ ]]; then
        fail "HostHive requires Debian 12 or 13 (Bookworm/Trixie). Detected: ${PRETTY_NAME:-unknown}"
    fi
    success "OS: ${PRETTY_NAME}"
else
    fail "Cannot detect OS. /etc/os-release not found."
fi

# Check memory (minimum 1GB)
TOTAL_MEM=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $TOTAL_MEM -lt 1024 ]]; then
    warn "Low memory: ${TOTAL_MEM}MB. Recommended: 2048MB+"
else
    success "Memory: ${TOTAL_MEM}MB"
fi

# Check disk (minimum 10GB free)
FREE_DISK=$(df -BG / | awk 'NR==2 {print int($4)}')
if [[ $FREE_DISK -lt 10 ]]; then
    warn "Low disk: ${FREE_DISK}GB free. Recommended: 20GB+"
else
    success "Disk: ${FREE_DISK}GB free"
fi

# Detect server IP
SERVER_IP=$(hostname -I | awk '{print $1}')
success "Server IP: ${SERVER_IP}"

# Detect PHP version available for this Debian release
PHP_VERSION="8.2"
if [[ "$VERSION_ID" == "13" ]]; then
    PHP_VERSION="8.3"
fi

echo ""

# ─── Step 1: Create directory structure ───
step 1 $TOTAL_STEPS "Creating directory structure"

mkdir -p "${INSTALL_DIR}"/{api/{routers,services,models,schemas,tasks,core},agent/executors,frontend/{src/{views,components,stores,api},dist},scripts/{modules,hooks},config,data/templates,logs,backups,tests}
mkdir -p /home/hosthive-users
mkdir -p /var/log/hosthive
success "Directory structure created"

log "=== HostHive Installation Started ==="
log "Server IP: ${SERVER_IP}"

# ─── Step 2: Update system & install packages ───
step 2 $TOTAL_STEPS "Installing system packages (this may take a few minutes)"

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq >> "$LOG_FILE" 2>&1 &
spinner $! "Updating package lists"
success "Package lists updated"

# Install packages in groups for better error handling
PACKAGES_CORE="nginx postgresql redis-server python3 python3-venv python3-pip git curl wget unzip htop openssl"
PACKAGES_MAIL="exim4 dovecot-core dovecot-imapd dovecot-pop3d spamassassin clamav"
PACKAGES_WEB="certbot python3-certbot-nginx php${PHP_VERSION}-fpm php${PHP_VERSION}-cli php${PHP_VERSION}-mysql php${PHP_VERSION}-curl php${PHP_VERSION}-mbstring php${PHP_VERSION}-xml php${PHP_VERSION}-zip php${PHP_VERSION}-gd php${PHP_VERSION}-intl"
PACKAGES_DNS="bind9 bind9utils"
PACKAGES_FTP="proftpd-basic"
PACKAGES_SEC="fail2ban ufw"
PACKAGES_DB="mariadb-server"

for group_name in CORE MAIL WEB DNS FTP SEC DB; do
    var="PACKAGES_${group_name}"
    apt-get install -y -qq ${!var} >> "$LOG_FILE" 2>&1 &
    spinner $! "Installing ${group_name,,} packages"
    success "${group_name,,} packages installed"
done

# ─── Step 3: Create system user ───
step 3 $TOTAL_STEPS "Creating system user"

if ! id -u hosthive &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin hosthive
    success "System user 'hosthive' created"
else
    success "System user 'hosthive' already exists"
fi

# ─── Step 4: Verify application source code ───
step 4 $TOTAL_STEPS "Verifying application source code"

# The bootstrap installer (install.sh) clones the repo directly into /opt/hosthive,
# so all source files are already in place. Just verify key dirs exist.
for component in api agent config data frontend; do
    if [[ ! -d "${INSTALL_DIR}/${component}" ]]; then
        fail "Missing ${component}/ directory. Re-run the bootstrap installer."
    fi
done

success "Application source verified in ${INSTALL_DIR}"

# ─── Step 5: Generate secrets ───
step 5 $TOTAL_STEPS "Generating secrets"

# Ask for admin email
echo ""
echo -e "  ${WHITE}${BOLD}Admin Configuration${NC}"
echo -ne "  ${CYAN}Admin email: ${NC}"
read -r ADMIN_EMAIL
if [[ -z "$ADMIN_EMAIL" ]]; then
    ADMIN_EMAIL="admin@localhost"
    warn "No email provided, using admin@localhost"
fi
echo ""

DB_PASSWORD=$(generate_password)
REDIS_PASSWORD=$(generate_password)
SECRET_KEY=$(generate_password)
AGENT_SECRET=$(generate_password)
ADMIN_PASSWORD=$(generate_password | head -c 16)

cat > "${CONFIG_DIR}/secrets.env" << SECRETS
# HostHive Secrets — AUTO-GENERATED, DO NOT COMMIT
# Generated: $(date -Iseconds)

# ── Database ──
DATABASE_URL=postgresql+asyncpg://hosthive:${DB_PASSWORD}@localhost:5432/hosthive
DATABASE_PASSWORD=${DB_PASSWORD}

# ── Redis ──
REDIS_URL=redis://:${REDIS_PASSWORD}@localhost:6379/0
REDIS_PASSWORD=${REDIS_PASSWORD}

# ── Secrets / Keys ──
SECRET_KEY=${SECRET_KEY}
AGENT_SECRET=${AGENT_SECRET}

# ── Initial admin ──
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ADMIN_EMAIL=${ADMIN_EMAIL}

# ── Network ──
SERVER_IP=${SERVER_IP}
PANEL_PORT=8443
SECRETS

chmod 600 "${CONFIG_DIR}/secrets.env"
chown hosthive:hosthive "${CONFIG_DIR}/secrets.env"
success "Secrets generated and stored"

# ─── Step 6: Setup PostgreSQL ───
step 6 $TOTAL_STEPS "Configuring PostgreSQL"

systemctl enable --now postgresql >> "$LOG_FILE" 2>&1

# Create database and user (idempotent)
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='hosthive'\" | grep -q 1 || psql -c \"CREATE ROLE hosthive WITH LOGIN PASSWORD '${DB_PASSWORD}'\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='hosthive'\" | grep -q 1 || psql -c \"CREATE DATABASE hosthive OWNER hosthive\"" >> "$LOG_FILE" 2>&1

# Grant privileges explicitly
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE hosthive TO hosthive\"" >> "$LOG_FILE" 2>&1
success "PostgreSQL configured"

# ─── Step 7: Setup Redis ───
step 7 $TOTAL_STEPS "Configuring Redis"

# Set Redis password
if ! grep -q "^requirepass" /etc/redis/redis.conf 2>/dev/null; then
    echo "requirepass ${REDIS_PASSWORD}" >> /etc/redis/redis.conf
else
    sed -i "s/^requirepass.*/requirepass ${REDIS_PASSWORD}/" /etc/redis/redis.conf
fi

systemctl enable --now redis-server >> "$LOG_FILE" 2>&1
systemctl restart redis-server >> "$LOG_FILE" 2>&1
success "Redis configured with password"

# ─── Step 8: Setup Python environment ───
step 8 $TOTAL_STEPS "Setting up Python environment"

python3 -m venv "${INSTALL_DIR}/venv" >> "$LOG_FILE" 2>&1
source "${INSTALL_DIR}/venv/bin/activate"

pip install --upgrade pip >> "$LOG_FILE" 2>&1 &
spinner $! "Upgrading pip"

# Install Python dependencies
# Prefer requirements.txt if it exists, otherwise install known packages
if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
    pip install -r "${INSTALL_DIR}/requirements.txt" >> "$LOG_FILE" 2>&1 &
    spinner $! "Installing Python packages from requirements.txt"
else
    pip install \
        fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg \
        celery redis pydantic pydantic-settings "passlib[bcrypt]" "python-jose[cryptography]" \
        python-multipart aiofiles paramiko dnspython slowapi jinja2 httpx \
        cryptography alembic psutil >> "$LOG_FILE" 2>&1 &
    spinner $! "Installing Python packages"
fi
success "Python environment ready"

# ─── Step 9: Setup Node.js & build frontend ───
step 9 $TOTAL_STEPS "Setting up Node.js & building frontend"

# Install Node 20 LTS via NodeSource
if ! command -v node &>/dev/null || [[ ! "$(node -v)" =~ ^v2[0-9] ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >> "$LOG_FILE" 2>&1
    apt-get install -y -qq nodejs >> "$LOG_FILE" 2>&1
fi
success "Node.js $(node -v) installed"

cd "${INSTALL_DIR}/frontend"
if [[ -f package.json ]]; then
    npm install --production=false >> "$LOG_FILE" 2>&1 &
    spinner $! "Installing npm packages"

    npm run build >> "$LOG_FILE" 2>&1 &
    spinner $! "Building frontend"
    success "Frontend built"
else
    warn "Frontend package.json not found, skipping build"
fi
cd "${INSTALL_DIR}"

# ─── Step 10: Configure Nginx ───
step 10 $TOTAL_STEPS "Configuring Nginx"

# Create log directory for nginx used by the config file
mkdir -p /var/log/hosthive
chown www-data:adm /var/log/hosthive

# Generate self-signed cert for panel (replaced by Let's Encrypt later)
mkdir -p /etc/ssl/hosthive
if [[ ! -f /etc/ssl/hosthive/panel.crt ]]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/ssl/hosthive/panel.key \
        -out /etc/ssl/hosthive/panel.crt \
        -subj "/CN=HostHive Panel/O=HostHive" >> "$LOG_FILE" 2>&1
    success "Self-signed SSL certificate generated"
fi

# Use the nginx config from the repo if available, otherwise generate inline
if [[ -f "${INSTALL_DIR}/config/nginx-panel.conf" ]]; then
    cp "${INSTALL_DIR}/config/nginx-panel.conf" /etc/nginx/sites-available/hosthive
    success "Nginx config copied from config/nginx-panel.conf"
else
    # Fallback: generate a basic config with SSL
    cat > /etc/nginx/sites-available/hosthive << 'NGINX_CONF'
# HostHive Panel — Nginx Configuration
server {
    listen 8443 ssl http2;
    listen [::]:8443 ssl http2;
    server_name _;

    ssl_certificate /etc/ssl/hosthive/panel.crt;
    ssl_certificate_key /etc/ssl/hosthive/panel.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    root /opt/hosthive/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        client_max_body_size 512M;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }

    access_log /var/log/hosthive/nginx-access.log;
    error_log /var/log/hosthive/nginx-error.log;

    client_max_body_size 256m;
    server_tokens off;
}
NGINX_CONF
    success "Nginx config generated inline (fallback)"
fi

# Enable site
ln -sf /etc/nginx/sites-available/hosthive /etc/nginx/sites-enabled/hosthive
rm -f /etc/nginx/sites-enabled/default

nginx -t >> "$LOG_FILE" 2>&1 || warn "Nginx config test failed, check log"
systemctl enable --now nginx >> "$LOG_FILE" 2>&1
systemctl reload nginx >> "$LOG_FILE" 2>&1
success "Nginx configured on HTTPS port 8443"

# ─── Step 11: Install systemd services ───
step 11 $TOTAL_STEPS "Creating systemd services"

# Copy service files from the repo config/ directory.
# These files contain the correct module paths and security hardening.
for svc in hosthive-api hosthive-agent hosthive-worker; do
    if [[ -f "${INSTALL_DIR}/config/${svc}.service" ]]; then
        cp "${INSTALL_DIR}/config/${svc}.service" "/etc/systemd/system/${svc}.service"
        success "Installed ${svc}.service from config/"
    else
        warn "${svc}.service not found in config/, skipping"
    fi
done

systemctl daemon-reload
systemctl enable hosthive-api hosthive-agent hosthive-worker >> "$LOG_FILE" 2>&1
success "Systemd services created and enabled"

# ─── Step 12: Firewall & security ───
step 12 $TOTAL_STEPS "Configuring firewall & security"

# UFW
ufw --force reset >> "$LOG_FILE" 2>&1
ufw default deny incoming >> "$LOG_FILE" 2>&1
ufw default allow outgoing >> "$LOG_FILE" 2>&1
for port in 22 80 443 8443 21 25 587 993 110 995 53 3306; do
    ufw allow "$port" >> "$LOG_FILE" 2>&1
done
ufw --force enable >> "$LOG_FILE" 2>&1
success "UFW firewall configured"

# Fail2ban
cat > /etc/fail2ban/jail.d/hosthive.conf << 'F2B'
[hosthive-auth]
enabled = true
port = 8443
filter = hosthive-auth
logpath = /opt/hosthive/logs/api.log
maxretry = 5
bantime = 900
findtime = 600

[sshd]
enabled = true
maxretry = 5
bantime = 3600
F2B

cat > /etc/fail2ban/filter.d/hosthive-auth.conf << 'F2B_FILTER'
[Definition]
failregex = ^.*LOGIN_FAILED.*ip=<HOST>.*$
ignoreregex =
F2B_FILTER

systemctl enable --now fail2ban >> "$LOG_FILE" 2>&1
systemctl restart fail2ban >> "$LOG_FILE" 2>&1
success "Fail2ban configured"

# ─── Step 13: Set permissions & start services ───
step 13 $TOTAL_STEPS "Starting HostHive services"

# Set permissions
chown -R hosthive:hosthive "${INSTALL_DIR}"
chmod -R 750 "${INSTALL_DIR}"

# Frontend dist must be readable by nginx (www-data)
chmod -R o+rX "${INSTALL_DIR}/frontend/dist" 2>/dev/null || true
# Also ensure parent dirs are traversable
chmod o+x "${INSTALL_DIR}"
chmod o+x "${INSTALL_DIR}/frontend"
chmod o+x "${INSTALL_DIR}/frontend/dist"

# Agent directory needs root ownership (it runs as root for privileged ops)
chown -R root:root "${INSTALL_DIR}/agent"

# Logs dir needs to be writable by hosthive user and root (for agent)
chown hosthive:hosthive "${INSTALL_DIR}/logs"
chmod 770 "${INSTALL_DIR}/logs"

# Ensure venv is accessible
chmod -R 755 "${INSTALL_DIR}/venv"

# Config dir readable by hosthive user
chmod -R 750 "${INSTALL_DIR}/config"
chown -R hosthive:hosthive "${INSTALL_DIR}/config"

# Ensure /var/log/hosthive exists for nginx
mkdir -p /var/log/hosthive
chown www-data:adm /var/log/hosthive

# Start services
systemctl start hosthive-api >> "$LOG_FILE" 2>&1 || warn "API service failed to start (check: journalctl -u hosthive-api)"
systemctl start hosthive-agent >> "$LOG_FILE" 2>&1 || warn "Agent service failed to start (check: journalctl -u hosthive-agent)"
systemctl start hosthive-worker >> "$LOG_FILE" 2>&1 || warn "Worker service failed to start (check: journalctl -u hosthive-worker)"

success "Services started"

# ─── Done! ───
echo ""
echo -e "  ${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "  ${GREEN}${BOLD}║                                                              ║${NC}"
echo -e "  ${GREEN}${BOLD}║   ${WHITE}✓ HostHive installed successfully!${GREEN}                         ║${NC}"
echo -e "  ${GREEN}${BOLD}║                                                              ║${NC}"
echo -e "  ${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${WHITE}${BOLD}Panel URL:${NC}     https://${SERVER_IP}:8443"
echo -e "  ${WHITE}${BOLD}Username:${NC}      admin"
echo -e "  ${WHITE}${BOLD}Password:${NC}      ${ADMIN_PASSWORD}"
echo ""
echo -e "  ${DIM}Save these credentials! Password will not be shown again.${NC}"
echo -e "  ${DIM}Log file: ${LOG_FILE}${NC}"
echo ""
echo -e "  ${CYAN}Services:${NC}"
echo -e "    hosthive-api      $(systemctl is-active hosthive-api 2>/dev/null || echo 'pending')"
echo -e "    hosthive-agent    $(systemctl is-active hosthive-agent 2>/dev/null || echo 'pending')"
echo -e "    hosthive-worker   $(systemctl is-active hosthive-worker 2>/dev/null || echo 'pending')"
echo ""
echo -e "  ${PURPLE}Thank you for choosing HostHive!${NC}"
echo ""

log "=== HostHive Installation Completed ==="
