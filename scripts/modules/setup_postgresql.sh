#!/usr/bin/env bash
###############################################################################
# HostHive — PostgreSQL Setup Module
# Creates the hosthive database and user. Idempotent.
###############################################################################
set -euo pipefail

SECRETS_FILE="/opt/hosthive/config/secrets.env"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    echo "[PostgreSQL] ERROR: Secrets file not found at ${SECRETS_FILE}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "${SECRETS_FILE}"

DB_NAME="${DB_NAME:-hosthive}"
DB_USER="${DB_USER:-hosthive}"
DB_PASSWORD="${DB_PASSWORD:?DB_PASSWORD must be set in secrets.env}"

echo "[PostgreSQL] Configuring PostgreSQL..."

# ─── Ensure PostgreSQL is running ────────────────────────────────────────────
systemctl enable postgresql
systemctl start postgresql

# ─── Create role if it does not exist ────────────────────────────────────────
ROLE_EXISTS=$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}';" 2>/dev/null || true)

if [[ "${ROLE_EXISTS}" == "1" ]]; then
    echo "[PostgreSQL] Role '${DB_USER}' already exists — updating password."
    sudo -u postgres psql -c \
        "ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" >/dev/null
else
    echo "[PostgreSQL] Creating role '${DB_USER}'..."
    sudo -u postgres psql -c \
        "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';" >/dev/null
fi

# ─── Create database if it does not exist ────────────────────────────────────
DB_EXISTS=$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}';" 2>/dev/null || true)

if [[ "${DB_EXISTS}" == "1" ]]; then
    echo "[PostgreSQL] Database '${DB_NAME}' already exists — skipping."
else
    echo "[PostgreSQL] Creating database '${DB_NAME}'..."
    sudo -u postgres psql -c \
        "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" >/dev/null
fi

# ─── Grant privileges ───────────────────────────────────────────────────────
sudo -u postgres psql -c \
    "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" >/dev/null

# ─── Ensure local md5 auth for the hosthive user ───────────────────────────
PG_HBA=$(sudo -u postgres psql -tAc "SHOW hba_file;" | tr -d ' ')
if [[ -n "${PG_HBA}" ]] && ! grep -q "hosthive" "${PG_HBA}" 2>/dev/null; then
    # Insert a host rule before the first generic local entry
    echo "# HostHive database access" >> "${PG_HBA}"
    echo "host    ${DB_NAME}    ${DB_USER}    127.0.0.1/32    md5" >> "${PG_HBA}"
    echo "host    ${DB_NAME}    ${DB_USER}    ::1/128         md5" >> "${PG_HBA}"
    systemctl reload postgresql
    echo "[PostgreSQL] Added md5 auth entries to pg_hba.conf."
fi

echo "[PostgreSQL] Setup complete."
