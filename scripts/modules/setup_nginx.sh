#!/usr/bin/env bash
###############################################################################
# HostHive — Nginx Setup Module
# Configures Nginx as a reverse proxy for the panel (port 8083) and serves
# the Vue frontend static files.
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_CONFIG_DIR="${SCRIPT_DIR}/../../config"
NGINX_CONF_SRC="${REPO_CONFIG_DIR}/nginx-panel.conf"
NGINX_CONF_DEST="/etc/nginx/sites-available/novapanel.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/novapanel.conf"

echo "[Nginx] Configuring Nginx for HostHive..."

# ─── Remove default site if it exists ────────────────────────────────────────
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
    echo "[Nginx] Removed default Nginx site."
fi

# ─── Install panel config ───────────────────────────────────────────────────
if [[ ! -f "${NGINX_CONF_SRC}" ]]; then
    echo "[Nginx] ERROR: Config template not found at ${NGINX_CONF_SRC}" >&2
    exit 1
fi

cp "${NGINX_CONF_SRC}" "${NGINX_CONF_DEST}"
echo "[Nginx] Installed config to ${NGINX_CONF_DEST}."

# ─── Create symlink in sites-enabled (idempotent) ───────────────────────────
if [[ -L "${NGINX_ENABLED}" ]]; then
    rm -f "${NGINX_ENABLED}"
fi
ln -s "${NGINX_CONF_DEST}" "${NGINX_ENABLED}"
echo "[Nginx] Enabled site via symlink."

# ─── Create directory for frontend static files ─────────────────────────────
mkdir -p /opt/novapanel/frontend/dist

# ─── Create log directory ───────────────────────────────────────────────────
mkdir -p /var/log/novapanel
chown novapanel:novapanel /var/log/novapanel

# ─── Validate config ────────────────────────────────────────────────────────
if ! nginx -t 2>&1; then
    echo "[Nginx] ERROR: Nginx configuration test failed." >&2
    exit 1
fi
echo "[Nginx] Configuration test passed."

# ─── Reload/restart Nginx ───────────────────────────────────────────────────
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx
echo "[Nginx] Service reloaded."
