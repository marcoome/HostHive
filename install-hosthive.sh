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
#   One-command installer for Debian 12 (Bookworm)
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

# ─── Branding (loaded from config if available) ───
PRODUCT_NAME="HostHive"
PRODUCT_VERSION="1.0.0"
INSTALL_DIR="/opt/hosthive"
CONFIG_DIR="${INSTALL_DIR}/config"
LOG_FILE="${INSTALL_DIR}/logs/install.log"

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
TOTAL_STEPS=12

print_header

echo -e "  ${WHITE}${BOLD}Pre-flight checks${NC}\n"

# Must be root
if [[ $EUID -ne 0 ]]; then
    fail "This installer must be run as root. Use: sudo bash install-hosthive.sh"
fi

# Check Debian 12
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" != "debian" ]] || [[ ! "$VERSION_ID" =~ ^12 ]]; then
        fail "HostHive requires Debian 12 (Bookworm). Detected: ${PRETTY_NAME:-unknown}"
    fi
    success "OS: Debian 12 (Bookworm)"
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

echo ""

# ─── Create directory structure ───
step 1 $TOTAL_STEPS "Creating directory structure"

mkdir -p "${INSTALL_DIR}"/{api/{routers,services,models,schemas,tasks,core},agent/executors,frontend/{src/{views,components,stores,api},dist},scripts/{modules,hooks},config,data/templates,logs,backups,tests}
mkdir -p /home/hosthive-users
success "Directory structure created"

# Initialize log
mkdir -p "${INSTALL_DIR}/logs"
touch "$LOG_FILE"
log "=== HostHive Installation Started ==="
log "Server IP: ${SERVER_IP}"

# ─── Update system & install packages ───
step 2 $TOTAL_STEPS "Installing system packages (this may take a few minutes)"

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq >> "$LOG_FILE" 2>&1 &
spinner $! "Updating package lists"
success "Package lists updated"

# Install packages in groups for better error handling
PACKAGES_CORE="nginx postgresql redis-server python3 python3-venv python3-pip git curl wget unzip htop openssl"
PACKAGES_MAIL="exim4 dovecot-core dovecot-imapd dovecot-pop3d spamassassin clamav"
PACKAGES_WEB="certbot python3-certbot-nginx php8.2-fpm php8.2-cli php8.2-mysql php8.2-curl php8.2-mbstring php8.2-xml php8.2-zip php8.2-gd php8.2-intl"
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

# ─── Create system user ───
step 3 $TOTAL_STEPS "Creating system user"

if ! id -u hosthive &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin hosthive
    success "System user 'hosthive' created"
else
    success "System user 'hosthive' already exists"
fi

# ─── Generate secrets ───
step 4 $TOTAL_STEPS "Generating secrets"

DB_PASSWORD=$(generate_password)
REDIS_PASSWORD=$(generate_password)
SECRET_KEY=$(generate_password)
AGENT_SECRET=$(generate_password)
ADMIN_PASSWORD=$(generate_password | head -c 16)

cat > "${CONFIG_DIR}/secrets.env" << SECRETS
# HostHive Secrets — AUTO-GENERATED, DO NOT COMMIT
# Generated: $(date -Iseconds)

DATABASE_URL=postgresql+asyncpg://hosthive:${DB_PASSWORD}@localhost:5432/hosthive
DATABASE_PASSWORD=${DB_PASSWORD}

REDIS_URL=redis://:${REDIS_PASSWORD}@localhost:6379/0
REDIS_PASSWORD=${REDIS_PASSWORD}

SECRET_KEY=${SECRET_KEY}
AGENT_SECRET=${AGENT_SECRET}

ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASSWORD}

SERVER_IP=${SERVER_IP}
PANEL_PORT=8083
SECRETS

chmod 600 "${CONFIG_DIR}/secrets.env"
chown hosthive:hosthive "${CONFIG_DIR}/secrets.env"
success "Secrets generated and stored"

# ─── Setup PostgreSQL ───
step 5 $TOTAL_STEPS "Configuring PostgreSQL"

systemctl enable --now postgresql >> "$LOG_FILE" 2>&1

# Create database and user (idempotent)
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='hosthive'\" | grep -q 1 || psql -c \"CREATE ROLE hosthive WITH LOGIN PASSWORD '${DB_PASSWORD}'\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='hosthive'\" | grep -q 1 || psql -c \"CREATE DATABASE hosthive OWNER hosthive\"" >> "$LOG_FILE" 2>&1
success "PostgreSQL configured"

# ─── Setup Redis ───
step 6 $TOTAL_STEPS "Configuring Redis"

# Set Redis password
if ! grep -q "^requirepass" /etc/redis/redis.conf 2>/dev/null; then
    echo "requirepass ${REDIS_PASSWORD}" >> /etc/redis/redis.conf
else
    sed -i "s/^requirepass.*/requirepass ${REDIS_PASSWORD}/" /etc/redis/redis.conf
fi

systemctl enable --now redis-server >> "$LOG_FILE" 2>&1
systemctl restart redis-server >> "$LOG_FILE" 2>&1
success "Redis configured with password"

# ─── Setup Python environment ───
step 7 $TOTAL_STEPS "Setting up Python environment"

python3 -m venv "${INSTALL_DIR}/venv" >> "$LOG_FILE" 2>&1
source "${INSTALL_DIR}/venv/bin/activate"

pip install --upgrade pip >> "$LOG_FILE" 2>&1 &
spinner $! "Upgrading pip"

pip install \
    fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg \
    celery redis pydantic pydantic-settings "passlib[bcrypt]" "python-jose[cryptography]" \
    python-multipart aiofiles paramiko dnspython slowapi jinja2 httpx \
    cryptography alembic psutil >> "$LOG_FILE" 2>&1 &
spinner $! "Installing Python packages"
success "Python environment ready"

# ─── Setup Node.js & build frontend ───
step 8 $TOTAL_STEPS "Setting up Node.js & building frontend"

# Install Node 20 LTS via NodeSource
if ! command -v node &>/dev/null || [[ ! "$(node -v)" =~ ^v20 ]]; then
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

# ─── Configure Nginx ───
step 9 $TOTAL_STEPS "Configuring Nginx"

cat > /etc/nginx/sites-available/hosthive << 'NGINX_CONF'
# HostHive Panel — Nginx Configuration
server {
    listen 8083 ssl http2;
    listen [::]:8083 ssl http2;
    server_name _;

    # SSL (self-signed initially, certbot later)
    ssl_certificate /etc/ssl/hosthive/panel.crt;
    ssl_certificate_key /etc/ssl/hosthive/panel.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' wss:;" always;

    # Frontend (Vue SPA)
    root /opt/hosthive/frontend/dist;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        client_max_body_size 512M;
    }

    # WebSocket proxy
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }

    # Logs
    access_log /opt/hosthive/logs/nginx-panel.access.log;
    error_log /opt/hosthive/logs/nginx-panel.error.log;
}

# HTTP redirect to HTTPS
server {
    listen 8080;
    listen [::]:8080;
    server_name _;
    return 301 https://$host:8083$request_uri;
}
NGINX_CONF

# Generate self-signed cert for panel (replaced by Let's Encrypt later)
mkdir -p /etc/ssl/hosthive
if [[ ! -f /etc/ssl/hosthive/panel.crt ]]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/ssl/hosthive/panel.key \
        -out /etc/ssl/hosthive/panel.crt \
        -subj "/CN=HostHive Panel/O=HostHive" >> "$LOG_FILE" 2>&1
    success "Self-signed SSL certificate generated"
fi

# Enable site
ln -sf /etc/nginx/sites-available/hosthive /etc/nginx/sites-enabled/hosthive
rm -f /etc/nginx/sites-enabled/default

nginx -t >> "$LOG_FILE" 2>&1 || warn "Nginx config test failed, check log"
systemctl enable --now nginx >> "$LOG_FILE" 2>&1
systemctl reload nginx >> "$LOG_FILE" 2>&1
success "Nginx configured on port 8083"

# ─── Create systemd services ───
step 10 $TOTAL_STEPS "Creating systemd services"

# API service
cat > /etc/systemd/system/hosthive-api.service << 'EOF'
[Unit]
Description=HostHive API Server
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=exec
User=hosthive
Group=hosthive
WorkingDirectory=/opt/hosthive
EnvironmentFile=/opt/hosthive/config/secrets.env
ExecStart=/opt/hosthive/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 4 --log-level info
Restart=always
RestartSec=5
StandardOutput=append:/opt/hosthive/logs/api.log
StandardError=append:/opt/hosthive/logs/api.error.log

[Install]
WantedBy=multi-user.target
EOF

# Agent service (runs as root)
cat > /etc/systemd/system/hosthive-agent.service << 'EOF'
[Unit]
Description=HostHive System Agent
After=network.target

[Service]
Type=exec
User=root
WorkingDirectory=/opt/hosthive
EnvironmentFile=/opt/hosthive/config/secrets.env
ExecStart=/opt/hosthive/venv/bin/uvicorn agent.agent:app --host 127.0.0.1 --port 7080 --log-level info
Restart=always
RestartSec=5
StandardOutput=append:/opt/hosthive/logs/agent.log
StandardError=append:/opt/hosthive/logs/agent.error.log

[Install]
WantedBy=multi-user.target
EOF

# Celery worker
cat > /etc/systemd/system/hosthive-worker.service << 'EOF'
[Unit]
Description=HostHive Celery Worker
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=exec
User=hosthive
Group=hosthive
WorkingDirectory=/opt/hosthive
EnvironmentFile=/opt/hosthive/config/secrets.env
ExecStart=/opt/hosthive/venv/bin/celery -A api.tasks worker -l info -B --scheduler celery.beat:PersistentScheduler
Restart=always
RestartSec=10
StandardOutput=append:/opt/hosthive/logs/worker.log
StandardError=append:/opt/hosthive/logs/worker.error.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hosthive-api hosthive-agent hosthive-worker >> "$LOG_FILE" 2>&1
success "Systemd services created and enabled"

# ─── Firewall ───
step 11 $TOTAL_STEPS "Configuring firewall & security"

# UFW
ufw --force reset >> "$LOG_FILE" 2>&1
ufw default deny incoming >> "$LOG_FILE" 2>&1
ufw default allow outgoing >> "$LOG_FILE" 2>&1
for port in 22 80 443 8083 21 25 587 993 110 995 53 3306; do
    ufw allow "$port" >> "$LOG_FILE" 2>&1
done
ufw --force enable >> "$LOG_FILE" 2>&1
success "UFW firewall configured"

# Fail2ban
cat > /etc/fail2ban/jail.d/hosthive.conf << 'F2B'
[hosthive-auth]
enabled = true
port = 8083
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

# ─── Initialize database & start services ───
step 12 $TOTAL_STEPS "Starting HostHive services"

# Set permissions
chown -R hosthive:hosthive "${INSTALL_DIR}"
chmod -R 750 "${INSTALL_DIR}"
# Agent needs root-owned dirs
chown root:root "${INSTALL_DIR}/agent" -R

# Start services
systemctl start hosthive-api >> "$LOG_FILE" 2>&1 || warn "API service failed to start (will work after code deploy)"
systemctl start hosthive-agent >> "$LOG_FILE" 2>&1 || warn "Agent service failed to start (will work after code deploy)"
systemctl start hosthive-worker >> "$LOG_FILE" 2>&1 || warn "Worker service failed to start (will work after code deploy)"

success "Services started"

# ─── Done! ───
echo ""
echo -e "  ${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "  ${GREEN}${BOLD}║                                                              ║${NC}"
echo -e "  ${GREEN}${BOLD}║   ${WHITE}✓ HostHive installed successfully!${GREEN}                         ║${NC}"
echo -e "  ${GREEN}${BOLD}║                                                              ║${NC}"
echo -e "  ${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${WHITE}${BOLD}Panel URL:${NC}     https://${SERVER_IP}:8083"
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
echo -e "  ${PURPLE}Thank you for choosing HostHive! 🐝${NC}"
echo ""

log "=== HostHive Installation Completed ==="
