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
set -uo pipefail
# Note: NOT using set -e because many optional steps may fail gracefully

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
    openssl rand -base64 48 | tr -d '/+=# \n' | head -c 32
}

# ─── Pre-flight checks ───
TOTAL_STEPS=14

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

# Fix hostname resolution (prevents sudo warnings)
CURRENT_HOSTNAME=$(hostname)
if ! grep -q "$CURRENT_HOSTNAME" /etc/hosts 2>/dev/null; then
    echo "127.0.1.1 $CURRENT_HOSTNAME" >> /etc/hosts
    success "Added hostname to /etc/hosts"
fi

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

# Pre-seed debconf for non-interactive installs
debconf-set-selections <<< "phpmyadmin phpmyadmin/dbconfig-install boolean false" 2>/dev/null || true
debconf-set-selections <<< "phpmyadmin phpmyadmin/reconfigure-webserver multiselect none" 2>/dev/null || true
debconf-set-selections <<< "phppgadmin phppgadmin/dbconfig-install boolean false" 2>/dev/null || true
debconf-set-selections <<< "roundcube roundcube/dbconfig-install boolean false" 2>/dev/null || true

# Install packages in groups for better error handling
PACKAGES_CORE="nginx postgresql redis-server python3 python3-venv python3-pip git curl wget unzip htop openssl"
PACKAGES_MAIL="exim4 dovecot-core dovecot-imapd dovecot-pop3d spamassassin clamav clamav-daemon clamav-freshclam opendkim opendkim-tools rspamd roundcube roundcube-plugins roundcube-pgsql"
PACKAGES_WEB="certbot python3-certbot-nginx php${PHP_VERSION}-fpm php${PHP_VERSION}-cli php${PHP_VERSION}-mysql php${PHP_VERSION}-pgsql php${PHP_VERSION}-curl php${PHP_VERSION}-mbstring php${PHP_VERSION}-xml php${PHP_VERSION}-zip php${PHP_VERSION}-gd php${PHP_VERSION}-intl php${PHP_VERSION}-soap php${PHP_VERSION}-bcmath php${PHP_VERSION}-readline php${PHP_VERSION}-opcache php${PHP_VERSION}-redis phpmyadmin phppgadmin"
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

# ─── Email server & Roundcube configuration functions ───
configure_email_server() {
    log "Configuring email server..."

    # Exim4 — internet site configuration
    debconf-set-selections <<< "exim4-config exim4/dc_eximconfig_configtype select internet site; mail is sent and received directly using SMTP"
    debconf-set-selections <<< "exim4-config exim4/dc_other_hostnames string ${SERVER_HOSTNAME:-$(hostname -f)}"
    debconf-set-selections <<< "exim4-config exim4/dc_local_interfaces string 0.0.0.0 ; ::0"
    debconf-set-selections <<< "exim4-config exim4/use_split_config boolean true"
    dpkg-reconfigure -f noninteractive exim4-config

    # Create virtual mailbox directories
    mkdir -p /var/mail/vhosts
    groupadd -g 5000 vmail 2>/dev/null || true
    useradd -u 5000 -g vmail -s /usr/sbin/nologin -d /var/mail/vhosts -m vmail 2>/dev/null || true
    chown -R vmail:vmail /var/mail/vhosts

    # Dovecot — configure for virtual users
    cat > /etc/dovecot/conf.d/10-mail.conf <<'DOVEOF'
mail_location = maildir:/var/mail/vhosts/%d/%n
namespace inbox {
  inbox = yes
}
mail_privileged_group = vmail
DOVEOF

    cat > /etc/dovecot/conf.d/10-auth.conf <<'DOVEOF'
disable_plaintext_auth = yes
auth_mechanisms = plain login
!include auth-passwdfile.conf.ext
DOVEOF

    cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext <<'DOVEOF'
passdb {
  driver = passwd-file
  args = scheme=SHA512-CRYPT /etc/dovecot/virtual_users
}
userdb {
  driver = static
  args = uid=vmail gid=vmail home=/var/mail/vhosts/%d/%n
}
DOVEOF

    # Create empty virtual users file
    touch /etc/dovecot/virtual_users
    chown dovecot:dovecot /etc/dovecot/virtual_users
    chmod 600 /etc/dovecot/virtual_users

    # Dovecot SSL
    cat > /etc/dovecot/conf.d/10-ssl.conf <<DOVEOF
ssl = required
ssl_cert = </etc/ssl/hosthive/panel.crt
ssl_key = </etc/ssl/hosthive/panel.key
ssl_min_protocol = TLSv1.2
DOVEOF

    # Create Exim4 virtual aliases file
    mkdir -p /etc/exim4
    touch /etc/exim4/virtual_aliases

    # OpenDKIM
    mkdir -p /etc/opendkim/keys
    cat > /etc/opendkim.conf <<'DKIMEOF'
Syslog          yes
UMask           007
Mode            sv
SubDomains      no
AutoRestart     yes
AutoRestartRate 10/1M
Background      yes
DNSTimeout      5
SignatureAlgorithm rsa-sha256
OversignHeaders From
KeyTable        /etc/opendkim/key.table
SigningTable    refile:/etc/opendkim/signing.table
ExternalIgnoreList  /etc/opendkim/trusted.hosts
InternalHosts       /etc/opendkim/trusted.hosts
DKIMEOF

    touch /etc/opendkim/key.table
    touch /etc/opendkim/signing.table
    cat > /etc/opendkim/trusted.hosts <<'EOF'
127.0.0.1
::1
localhost
EOF

    # Enable and start services
    systemctl enable --now dovecot exim4 opendkim 2>/dev/null || true
    systemctl restart dovecot exim4 2>/dev/null || true

    success "Email server configured"
}

configure_roundcube() {
    log "Configuring Roundcube webmail..."

    # Generate Roundcube DB password
    RC_DB_PASS=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)

    # Create Roundcube database
    sudo -u postgres psql -c "CREATE ROLE roundcube WITH LOGIN PASSWORD '${RC_DB_PASS}';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER ROLE roundcube WITH PASSWORD '${RC_DB_PASS}';"
    sudo -u postgres psql -c "CREATE DATABASE roundcube OWNER roundcube;" 2>/dev/null || true

    # Initialize Roundcube DB schema
    if [ -f /usr/share/roundcube/SQL/postgres.initial.sql ]; then
        PGPASSWORD="${RC_DB_PASS}" psql -U roundcube -d roundcube -f /usr/share/roundcube/SQL/postgres.initial.sql 2>/dev/null || true
    fi

    # Roundcube config
    RC_DES_KEY=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
    cat > /etc/roundcube/config.inc.php <<RCEOF
<?php
\$config = [];
\$config['db_dsnw'] = 'pgsql://roundcube:${RC_DB_PASS}@localhost/roundcube';
\$config['imap_host'] = 'ssl://localhost:993';
\$config['smtp_host'] = 'tls://localhost:587';
\$config['smtp_user'] = '%u';
\$config['smtp_pass'] = '%p';
\$config['support_url'] = '';
\$config['product_name'] = 'HostHive Webmail';
\$config['des_key'] = '${RC_DES_KEY}';
\$config['plugins'] = ['archive', 'zipdownload', 'managesieve'];
\$config['skin'] = 'elastic';
\$config['language'] = 'en_US';
\$config['spellcheck_engine'] = 'pspell';
\$config['mime_param_folding'] = 0;
\$config['draft_autosave'] = 60;
\$config['login_autocomplete'] = 2;
RCEOF

    chown www-data:www-data /etc/roundcube/config.inc.php
    chmod 640 /etc/roundcube/config.inc.php

    # Roundcube webmail nginx config (dedicated vhost for webmail.*/mail.*)
    cat > /etc/nginx/conf.d/roundcube.conf <<'NGEOF'
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name webmail.* mail.*;

    ssl_certificate /etc/ssl/hosthive/panel.crt;
    ssl_certificate_key /etc/ssl/hosthive/panel.key;

    root /usr/share/roundcube;
    index index.php;

    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }

    location ~ /\. { deny all; }
    location ~ ^/(config|temp|logs)/ { deny all; }
}
NGEOF

    # Deploy SSO bridge script for Roundcube auto-login from the panel
    if [[ -d /usr/share/roundcube ]]; then
        if [[ -f "${SCRIPT_DIR}/scripts/roundcube-sso.php" ]]; then
            cp "${SCRIPT_DIR}/scripts/roundcube-sso.php" /usr/share/roundcube/sso.php
        else
            cat > /usr/share/roundcube/sso.php << 'RCSSOPHP'
<?php
$token = $_GET['token'] ?? '';
if (empty($token) || !preg_match('/^[A-Za-z0-9_-]+$/', $token)) {
    header('HTTP/1.1 400 Bad Request'); echo 'Invalid or missing SSO token.'; exit;
}
$redis = new Redis();
$redis->connect('127.0.0.1', 6379);
$sf = '/opt/hosthive/config/secrets.env';
if (file_exists($sf)) {
    $c = file_get_contents($sf);
    if (preg_match('/REDIS_PASSWORD=(.+)/', $c, $m)) { $rp = trim($m[1]); if (!empty($rp)) $redis->auth($rp); }
}
$key = "hosthive:rc_sso:{$token}";
$data = $redis->get($key);
if ($data === false) { header('HTTP/1.1 403 Forbidden'); echo 'Token expired or invalid.'; exit; }
$redis->del($key);
$creds = json_decode($data, true);
if (!$creds || empty($creds['user']) || empty($creds['password'])) {
    header('HTTP/1.1 500 Internal Server Error'); echo 'Invalid SSO payload.'; exit;
}
define('INSTALL_PATH', '/usr/share/roundcube/');
require_once INSTALL_PATH . 'program/include/iniset.php';
$rcmail = rcmail::get_instance(0, 'web');
$auth = $rcmail->login($creds['user'], $creds['password'], 'localhost', false);
if ($auth) { header('Location: /roundcube/?_task=mail'); exit; }
else { header('HTTP/1.1 401 Unauthorized'); echo 'Roundcube login failed.'; exit; }
RCSSOPHP
        fi
        chown www-data:www-data /usr/share/roundcube/sso.php
        chmod 644 /usr/share/roundcube/sso.php
        success "Roundcube SSO bridge deployed"
    fi

    success "Roundcube webmail configured"
}

# ─── Step 3: Create system user ───
step 3 $TOTAL_STEPS "Creating system user"

if ! id -u hosthive &>/dev/null; then
    useradd --system --home-dir /home/hosthive --create-home --shell /usr/sbin/nologin hosthive
    success "System user 'hosthive' created"
else
    success "System user 'hosthive' already exists"
fi
mkdir -p /home/hosthive/.postgresql
chown -R hosthive:hosthive /home/hosthive

# ─── Step 4: Clone/update application source code ───
step 4 $TOTAL_STEPS "Verifying application source code"

REPO_URL="https://github.com/marcoome/HostHive.git"

# Clone the repo if source code is missing, otherwise pull latest
if [[ ! -d "${INSTALL_DIR}/api" ]] || [[ ! -d "${INSTALL_DIR}/frontend/src" ]]; then
    log "Source code missing, cloning from GitHub..."
    # Save existing config if any
    if [[ -f "${CONFIG_DIR}/secrets.env" ]]; then
        cp "${CONFIG_DIR}/secrets.env" /tmp/hosthive-secrets.env.bak
    fi

    # Clone into a temp dir and copy over (preserves existing data/logs/venv)
    TMPDIR=$(mktemp -d)
    git clone --depth 1 "${REPO_URL}" "${TMPDIR}" >> "$LOG_FILE" 2>&1 &
    spinner $! "Cloning HostHive from GitHub"

    # Copy source directories from repo
    for src_dir in api agent frontend config scripts tests novapanel; do
        if [[ -d "${TMPDIR}/${src_dir}" ]]; then
            rm -rf "${INSTALL_DIR}/${src_dir}"
            cp -r "${TMPDIR}/${src_dir}" "${INSTALL_DIR}/${src_dir}"
        fi
    done

    # Copy root-level files
    for root_file in requirements.txt package.json install-hosthive.sh; do
        if [[ -f "${TMPDIR}/${root_file}" ]]; then
            cp "${TMPDIR}/${root_file}" "${INSTALL_DIR}/${root_file}"
        fi
    done

    rm -rf "${TMPDIR}"

    # Restore secrets if backed up
    if [[ -f /tmp/hosthive-secrets.env.bak ]]; then
        cp /tmp/hosthive-secrets.env.bak "${CONFIG_DIR}/secrets.env"
        rm -f /tmp/hosthive-secrets.env.bak
    fi

    success "Source code cloned from GitHub"
else
    # Try to pull latest if it's a git repo
    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        cd "${INSTALL_DIR}"
        git pull origin main >> "$LOG_FILE" 2>&1 &
        spinner $! "Pulling latest updates"
        success "Source code updated from GitHub"
    else
        success "Application source verified in ${INSTALL_DIR}"
    fi
fi

# Final verification
for component in api agent config frontend; do
    if [[ ! -d "${INSTALL_DIR}/${component}" ]]; then
        fail "Missing ${component}/ directory after clone. Check ${LOG_FILE}"
    fi
done

success "Application source verified in ${INSTALL_DIR}"

# ─── Step 5: Generate secrets ───
step 5 $TOTAL_STEPS "Generating secrets"

# Admin email (pass as env var ADMIN_EMAIL or first argument, otherwise default)
ADMIN_EMAIL="${ADMIN_EMAIL:-${1:-admin@localhost}}"
if [[ "$ADMIN_EMAIL" == "admin@localhost" ]]; then
    # Try to read from terminal if available (not piped)
    if [[ -t 0 ]]; then
        echo ""
        echo -e "  ${WHITE}${BOLD}Admin Configuration${NC}"
        echo -ne "  ${CYAN}Admin email [admin@localhost]: ${NC}"
        read -r input_email
        if [[ -n "$input_email" ]]; then
            ADMIN_EMAIL="$input_email"
        fi
        echo ""
    fi
fi
success "Admin email: ${ADMIN_EMAIL}"

DB_PASSWORD=$(generate_password)
REDIS_PASSWORD=$(generate_password)
SECRET_KEY=$(generate_password)
AGENT_SECRET=$(generate_password)
FERNET_SALT=$(openssl rand -hex 32)
ADMIN_PASSWORD=$(generate_password | head -c 16)

cat > "${CONFIG_DIR}/secrets.env" << SECRETS
# HostHive Secrets — AUTO-GENERATED, DO NOT COMMIT
# Generated: $(date -Iseconds)

DB_USER=hosthive
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=hosthive
REDIS_PASSWORD=${REDIS_PASSWORD}
SECRET_KEY=${SECRET_KEY}
AGENT_SECRET=${AGENT_SECRET}
FERNET_SALT=${FERNET_SALT}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ADMIN_EMAIL=${ADMIN_EMAIL}
SERVER_IP=${SERVER_IP}
PANEL_PORT=8443
SECRETS

chmod 600 "${CONFIG_DIR}/secrets.env"
chown hosthive:hosthive "${CONFIG_DIR}/secrets.env"
success "Secrets generated and stored"

# ─── Step 6: Setup PostgreSQL ───
step 6 $TOTAL_STEPS "Configuring PostgreSQL"

systemctl enable --now postgresql >> "$LOG_FILE" 2>&1

# Create database and user — always reset password to match secrets.env
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='hosthive'\" | grep -q 1 || psql -c \"CREATE ROLE hosthive WITH LOGIN PASSWORD '${DB_PASSWORD}'\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -c \"ALTER ROLE hosthive WITH PASSWORD '${DB_PASSWORD}'\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='hosthive'\" | grep -q 1 || psql -c \"CREATE DATABASE hosthive OWNER hosthive\"" >> "$LOG_FILE" 2>&1

# Grant privileges explicitly (PostgreSQL 15+ revoked public CREATE by default)
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE hosthive TO hosthive\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -d hosthive -c \"GRANT ALL ON SCHEMA public TO hosthive\"" >> "$LOG_FILE" 2>&1
su - postgres -c "psql -d hosthive -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO hosthive\"" >> "$LOG_FILE" 2>&1
success "PostgreSQL configured"

# ─── Step 7: Setup Redis ───
step 7 $TOTAL_STEPS "Configuring Redis"

# Set Redis password - handle both legacy requirepass and Redis 6+ ACL
REDIS_CONF="/etc/redis/redis.conf"
if [ -f "$REDIS_CONF" ]; then
    # Remove any existing requirepass lines (including commented ones that might interfere)
    sed -i '/^requirepass/d' "$REDIS_CONF"
    # Add clean requirepass
    echo "requirepass ${REDIS_PASSWORD}" >> "$REDIS_CONF"
    # Disable protected-mode since we use password auth
    sed -i 's/^protected-mode yes/protected-mode no/' "$REDIS_CONF"
    # Bind to localhost only
    sed -i 's/^bind .*/bind 127.0.0.1 ::1/' "$REDIS_CONF"
fi

systemctl enable --now redis-server >> "$LOG_FILE" 2>&1
systemctl restart redis-server >> "$LOG_FILE" 2>&1

# Verify Redis auth works and also set password via CLI (handles ACL-based Redis 7+)
sleep 1
redis-cli -a "${REDIS_PASSWORD}" ping >> "$LOG_FILE" 2>&1 || {
    # If password auth fails, try without password and set it via ACL
    redis-cli ping >> "$LOG_FILE" 2>&1 && {
        redis-cli CONFIG SET requirepass "${REDIS_PASSWORD}" >> "$LOG_FILE" 2>&1
        redis-cli -a "${REDIS_PASSWORD}" CONFIG REWRITE >> "$LOG_FILE" 2>&1 || true
    }
    # Also try setting via ACL for Redis 6+
    redis-cli ACL SETUSER default on ">${REDIS_PASSWORD}" ~* &* +@all >> "$LOG_FILE" 2>&1 || true
}
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
        celery redis "pydantic[email]" pydantic-settings bcrypt "python-jose[cryptography]" \
        python-multipart aiofiles paramiko dnspython slowapi jinja2 httpx \
        cryptography alembic psutil email-validator psycopg2-binary >> "$LOG_FILE" 2>&1 &
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

# ─── GeoIP2 module for geo-blocking ───
log "Installing GeoIP2 module for nginx geo-blocking..."
apt-get install -y -qq libnginx-mod-http-geoip2 >> "$LOG_FILE" 2>&1 && \
    success "libnginx-mod-http-geoip2 installed" || \
    warn "Failed to install libnginx-mod-http-geoip2 (geo-blocking will be unavailable)"

# Install geoipupdate for automatic MaxMind database updates
if ! command -v geoipupdate &>/dev/null; then
    apt-get install -y -qq geoipupdate >> "$LOG_FILE" 2>&1 && \
        success "geoipupdate installed" || \
        warn "geoipupdate not available in repos (install manually for auto-updates)"
fi

# Create GeoIP directory and download the free GeoLite2-Country database
mkdir -p /usr/share/GeoIP

# If geoipupdate is installed and configured, use it
if command -v geoipupdate &>/dev/null && [ -f /etc/GeoIP.conf ]; then
    geoipupdate >> "$LOG_FILE" 2>&1 && \
        success "GeoLite2-Country database downloaded via geoipupdate" || \
        warn "geoipupdate failed -- configure /etc/GeoIP.conf with your MaxMind license key"
else
    log "geoipupdate not configured. To enable GeoIP geo-blocking:"
    log "  1. Sign up at https://www.maxmind.com/en/geolite2/signup"
    log "  2. Generate a license key"
    log "  3. Configure /etc/GeoIP.conf with your AccountID and LicenseKey"
    log "  4. Run: geoipupdate"
    warn "GeoIP database not downloaded (MaxMind license key required)"
fi

# Ensure geoip2 module is loaded in nginx
if ! grep -q "ngx_http_geoip2_module" /etc/nginx/nginx.conf 2>/dev/null; then
    if [ ! -f /etc/nginx/modules-enabled/50-mod-http-geoip2.conf ]; then
        GEOIP2_SO=$(find /usr/lib/nginx/modules -name "ngx_http_geoip2_module.so" 2>/dev/null | head -1)
        if [ -n "$GEOIP2_SO" ]; then
            sed -i "1i load_module ${GEOIP2_SO};" /etc/nginx/nginx.conf
            log "Added geoip2 load_module to nginx.conf"
        fi
    fi
fi

# Create WAF directory for geo state
mkdir -p /etc/nginx/waf
success "GeoIP2 geo-blocking setup complete"

# Configure email server and Roundcube webmail
configure_email_server
configure_roundcube

# ─── Configure phpMyAdmin (non-interactive) ───
configure_phpmyadmin() {
    log "Configuring phpMyAdmin..."

    # Pre-seed debconf to avoid interactive prompts
    debconf-set-selections <<< "phpmyadmin phpmyadmin/dbconfig-install boolean false"
    debconf-set-selections <<< "phpmyadmin phpmyadmin/reconfigure-webserver multiselect none"

    # Ensure phpMyAdmin is installed
    if [[ ! -d /usr/share/phpmyadmin ]]; then
        apt-get install -y -qq phpmyadmin >> "$LOG_FILE" 2>&1 || warn "phpMyAdmin installation failed"
    fi

    # Create phpMyAdmin config for MariaDB
    if [[ -d /usr/share/phpmyadmin ]]; then
        cat > /etc/phpmyadmin/config-db.php << 'PMAEOF'
<?php
$dbuser='phpmyadmin';
$dbpass='';
$basepath='';
$dbname='phpmyadmin';
$dbserver='localhost';
$dbport='3306';
$dbtype='mysql';
PMAEOF

        # Create blowfish secret and configure signon auth for SSO
        PMA_SECRET=$(openssl rand -hex 24)
        cat > /etc/phpmyadmin/conf.d/hosthive.php << PMACONF
<?php
\$cfg['blowfish_secret'] = '${PMA_SECRET}';
\$cfg['Servers'][1]['auth_type'] = 'signon';
\$cfg['Servers'][1]['SignonSession'] = 'SignonSession';
\$cfg['Servers'][1]['SignonURL'] = '/phpmyadmin/signon.php';
\$cfg['Servers'][1]['LogoutURL'] = '/phpmyadmin/signon.php';
\$cfg['Servers'][1]['host'] = 'localhost';
\$cfg['Servers'][1]['compress'] = false;
\$cfg['Servers'][1]['AllowNoPassword'] = false;
\$cfg['LoginCookieValidity'] = 36000;
\$cfg['MaxRows'] = 50;
\$cfg['UploadDir'] = '';
\$cfg['SaveDir'] = '';
PMACONF

        # Set permissions - www-data needs to read secrets for SSO
        chown -R www-data:www-data /etc/phpmyadmin
        chmod 640 /etc/phpmyadmin/config-db.php
        chmod 640 /etc/phpmyadmin/conf.d/hosthive.php
        chmod 755 "${INSTALL_DIR}/config"
        chmod 644 "${INSTALL_DIR}/config/secrets.env"

        # Deploy SSO + signon scripts
        cp "${INSTALL_DIR}/scripts/phpmyadmin-sso.php" /usr/share/phpmyadmin/sso.php 2>/dev/null || true
        cp "${INSTALL_DIR}/scripts/phpmyadmin-signon.php" /usr/share/phpmyadmin/signon.php 2>/dev/null || true
        chown www-data:www-data /usr/share/phpmyadmin/sso.php /usr/share/phpmyadmin/signon.php 2>/dev/null || true
        chmod 644 /usr/share/phpmyadmin/sso.php /usr/share/phpmyadmin/signon.php 2>/dev/null || true

        # Create phpMyAdmin configuration storage database
        mysql -u root -e "CREATE DATABASE IF NOT EXISTS phpmyadmin;" >> "$LOG_FILE" 2>&1 || true
        mysql -u root phpmyadmin < /usr/share/phpmyadmin/sql/create_tables.sql >> "$LOG_FILE" 2>&1 || true
        mysql -u root -e "CREATE USER IF NOT EXISTS 'pma'@'localhost' IDENTIFIED BY '';" >> "$LOG_FILE" 2>&1 || true
        mysql -u root -e "GRANT ALL PRIVILEGES ON phpmyadmin.* TO 'pma'@'localhost';" >> "$LOG_FILE" 2>&1 || true
        mysql -u root -e "FLUSH PRIVILEGES;" >> "$LOG_FILE" 2>&1 || true

        # Update config-db.php with pma user
        cat > /etc/phpmyadmin/config-db.php << 'PMADBEOF'
<?php
$dbuser='pma';
$dbpass='';
$basepath='';
$dbname='phpmyadmin';
$dbserver='localhost';
$dbport='3306';
$dbtype='mysql';
PMADBEOF

        success "phpMyAdmin configured with SSO"
    else
        warn "phpMyAdmin not found at /usr/share/phpmyadmin"
    fi
}
configure_phpmyadmin

# ─── Configure phpPgAdmin (non-interactive) ───
configure_phppgadmin() {
    log "Configuring phpPgAdmin..."

    # Ensure phpPgAdmin is installed
    if [[ ! -d /usr/share/phppgadmin ]]; then
        apt-get install -y -qq phppgadmin >> "$LOG_FILE" 2>&1 || warn "phpPgAdmin installation failed"
    fi

    if [[ -d /usr/share/phppgadmin ]]; then
        # Configure phpPgAdmin for localhost PostgreSQL
        if [[ -f /etc/phppgadmin/config.inc.php ]]; then
            cat > /etc/phppgadmin/config.inc.php << 'PGAEOF'
<?php
/**
 * phpPgAdmin configuration — managed by HostHive.
 */
$conf['servers'][0]['desc'] = 'PostgreSQL';
$conf['servers'][0]['host'] = 'localhost';
$conf['servers'][0]['port'] = 5432;
$conf['servers'][0]['sslmode'] = 'allow';
$conf['servers'][0]['defaultdb'] = 'template1';
$conf['servers'][0]['pg_dump_path'] = '/usr/bin/pg_dump';
$conf['servers'][0]['pg_dumpall_path'] = '/usr/bin/pg_dumpall';

// Display options
$conf['default_lang'] = 'auto';
$conf['autocomplete'] = 'default on';
$conf['extra_login_security'] = false;
$conf['owned_only'] = false;
$conf['show_comments'] = true;
$conf['show_advanced'] = false;
$conf['show_system'] = false;
$conf['min_password_length'] = 1;
$conf['left_width'] = 200;
$conf['theme'] = 'default';
$conf['show_oids'] = false;
$conf['max_rows'] = 30;
$conf['max_chars'] = 50;
$conf['use_xhtml_strict'] = false;

// Disable login page (SSO handles auth)
$conf['servers'][0]['pg_dump_path'] = '/usr/bin/pg_dump';
$conf['servers'][0]['pg_dumpall_path'] = '/usr/bin/pg_dumpall';
PGAEOF
        fi

        # Set permissions
        chown -R www-data:www-data /etc/phppgadmin
        chmod 640 /etc/phppgadmin/config.inc.php

        # Deploy SSO script
        cp "${INSTALL_DIR}/scripts/phppgadmin-sso.php" /usr/share/phppgadmin/sso.php 2>/dev/null || true
        chown www-data:www-data /usr/share/phppgadmin/sso.php 2>/dev/null || true
        chmod 644 /usr/share/phppgadmin/sso.php 2>/dev/null || true

        success "phpPgAdmin configured with SSO"
    else
        warn "phpPgAdmin not found at /usr/share/phppgadmin"
    fi
}
configure_phppgadmin

# ─── Configure sudoers for hosthive user ───
log "Configuring sudoers for hosthive..."
cat > /etc/sudoers.d/hosthive << 'SUDOEOF'
# HostHive panel — allow hosthive user to manage system services
hosthive ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/sbin/ufw, /usr/bin/fail2ban-client, /usr/bin/tail, /usr/bin/certbot, /usr/sbin/rndc, /usr/bin/crontab, /usr/bin/mysql, /usr/bin/mysqldump, /usr/bin/ftpasswd, /bin/tar, /bin/chown, /usr/sbin/nginx, /usr/bin/doveadm, /usr/sbin/exim4, /usr/bin/pg_dump, /usr/bin/psql, /usr/bin/clamscan, /usr/bin/freshclam, /usr/bin/apt, /usr/bin/apt-get, /usr/sbin/apache2ctl, /usr/bin/varnishadm, /usr/bin/ss, /usr/sbin/smartctl, /usr/bin/ip, /usr/sbin/logrotate, /usr/bin/setquota, /usr/bin/quota, /usr/sbin/repquota, /usr/bin/phpenmod, /usr/bin/phpdismod, /usr/sbin/a2ensite, /usr/sbin/a2dissite, /usr/sbin/a2enmod, /usr/bin/hostnamectl, /usr/bin/reboot
SUDOEOF
chmod 440 /etc/sudoers.d/hosthive
success "Sudoers configured for hosthive user"

# ─── Create required directories ───
mkdir -p /etc/bind/zones /opt/hosthive/backups /var/mail/vhosts
chown -R hosthive:hosthive /opt/hosthive/backups

# ─── Install psutil for monitoring ───
"${INSTALL_DIR}/venv/bin/pip" install psutil >> "$LOG_FILE" 2>&1 &
spinner $! "Installing psutil for monitoring"
success "psutil installed"

# Reload nginx to pick up Roundcube + phpMyAdmin + phpPgAdmin config
nginx -t >> "$LOG_FILE" 2>&1 || warn "Nginx config test failed"
systemctl reload nginx >> "$LOG_FILE" 2>&1

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

# ─── Step 13: Security hardening ───
step 13 $TOTAL_STEPS "Applying security hardening"

configure_security() {
    log "Configuring security hardening..."

    # SSH Hardening
    if [ -f /etc/ssh/sshd_config ]; then
        # Backup original
        cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.hosthive

        # Apply hardening (don't disable password auth - user might not have keys)
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
        sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 5/' /etc/ssh/sshd_config
        sed -i 's/^#\?ClientAliveInterval.*/ClientAliveInterval 300/' /etc/ssh/sshd_config
        sed -i 's/^#\?ClientAliveCountMax.*/ClientAliveCountMax 2/' /etc/ssh/sshd_config
        sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config
        systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null || true
    fi

    # ClamAV setup
    if command -v freshclam &>/dev/null; then
        # Ensure ClamAV log directory and permissions
        mkdir -p /var/log/clamav
        touch /var/log/clamav/freshclam.log /var/log/clamav/clamav.log
        chown -R clamav:clamav /var/log/clamav
        chmod 640 /var/log/clamav/*.log
        # Stop freshclam if running, update virus definitions
        systemctl stop clamav-freshclam 2>/dev/null || true
        freshclam --quiet 2>/dev/null || true
        systemctl enable --now clamav-freshclam 2>/dev/null || true
        systemctl enable --now clamav-daemon 2>/dev/null || true

        # Create scan script for uploaded files
        mkdir -p /opt/hosthive/scripts
        cat > /opt/hosthive/scripts/clamav-scan.sh <<'SCANEOF'
#!/bin/bash
# Scan a file or directory with ClamAV
# Usage: clamav-scan.sh <path>
if [ -z "$1" ]; then
    echo '{"error": "No path specified"}'
    exit 1
fi
RESULT=$(clamscan --no-summary --infected "$1" 2>&1)
RC=$?
if [ $RC -eq 0 ]; then
    echo '{"clean": true, "threats": []}'
elif [ $RC -eq 1 ]; then
    THREATS=$(echo "$RESULT" | grep "FOUND" | awk -F: '{print $2}' | sed 's/ FOUND//' | tr '\n' ',' | sed 's/,$//')
    echo "{\"clean\": false, \"threats\": [\"${THREATS}\"]}"
else
    echo "{\"error\": \"Scan failed: ${RESULT}\"}"
fi
SCANEOF
        chmod +x /opt/hosthive/scripts/clamav-scan.sh

        # Create quarantine directory for antivirus
        mkdir -p /opt/hosthive/quarantine
        chown hosthive:hosthive /opt/hosthive/quarantine
        chmod 700 /opt/hosthive/quarantine

        # Integrate ClamAV with Exim4 for email scanning
        if [ -d /etc/exim4/conf.d ]; then
            # Enable content scanning in Exim4 main config
            mkdir -p /etc/exim4/conf.d/main
            cat > /etc/exim4/conf.d/main/02_hosthive_clamav <<'EXIM_AV'
# HostHive: ClamAV integration for email scanning
av_scanner = clamd:/var/run/clamav/clamd.ctl
EXIM_AV

            # Add ClamAV ACL for DATA phase
            mkdir -p /etc/exim4/conf.d/acl
            cat > /etc/exim4/conf.d/acl/48_hosthive_clamav <<'EXIM_ACL'
# HostHive: Scan incoming emails with ClamAV
  warn
    malware = *
    log_message = Virus found: $malware_name in message from $sender_address to $recipients

  deny
    malware = *
    message = This message contains a virus ($malware_name) and has been rejected.
EXIM_ACL

            # Ensure clamav user can communicate with Exim
            usermod -a -G Debian-exim clamav 2>/dev/null || true

            # Restart Exim to pick up ClamAV scanning config
            systemctl restart exim4 2>/dev/null || true
            log "ClamAV integrated with Exim4 for email scanning"
        fi
    fi

    # Kernel hardening via sysctl
    cat > /etc/sysctl.d/99-hosthive-hardening.conf <<'SYSEOF'
# HostHive Security Hardening
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.conf.all.log_martians = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
kernel.randomize_va_space = 2
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
SYSEOF
    sysctl --system >/dev/null 2>&1 || true

    # Automatic security updates
    if command -v apt-get &>/dev/null; then
        apt-get install -y -qq unattended-upgrades apt-listchanges >/dev/null 2>&1 || true
        cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APTEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
APTEOF
    fi

    # Secure /tmp
    if ! mount | grep -q "on /tmp "; then
        # Add noexec to /tmp if it's not a separate partition
        echo "tmpfs /tmp tmpfs defaults,noexec,nosuid,nodev 0 0" >> /etc/fstab 2>/dev/null || true
    fi

    success "Security hardening applied"
}

configure_security

# ─── Step 14: Set permissions & start services ───
step 14 $TOTAL_STEPS "Starting HostHive services"

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
