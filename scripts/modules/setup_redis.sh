#!/usr/bin/env bash
###############################################################################
# HostHive — Redis Setup Module
# Configures Redis with password authentication. Idempotent.
###############################################################################
set -euo pipefail

SECRETS_FILE="/opt/hosthive/config/secrets.env"
REDIS_CONF="/etc/redis/redis.conf"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    echo "[Redis] ERROR: Secrets file not found at ${SECRETS_FILE}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "${SECRETS_FILE}"

REDIS_PASSWORD="${REDIS_PASSWORD:?REDIS_PASSWORD must be set in secrets.env}"

echo "[Redis] Configuring Redis..."

# ─── Ensure Redis is installed and config exists ─────────────────────────────
if [[ ! -f "${REDIS_CONF}" ]]; then
    echo "[Redis] ERROR: Redis config not found at ${REDIS_CONF}" >&2
    exit 1
fi

# ─── Bind to localhost only ──────────────────────────────────────────────────
# Replace any existing bind directive; keep it on loopback
if grep -q "^bind " "${REDIS_CONF}"; then
    sed -i 's/^bind .*/bind 127.0.0.1 ::1/' "${REDIS_CONF}"
else
    echo "bind 127.0.0.1 ::1" >> "${REDIS_CONF}"
fi
echo "[Redis] Bound to localhost."

# ─── Set password (idempotent) ───────────────────────────────────────────────
if grep -q "^requirepass " "${REDIS_CONF}"; then
    sed -i "s/^requirepass .*/requirepass ${REDIS_PASSWORD}/" "${REDIS_CONF}"
    echo "[Redis] Updated existing requirepass directive."
else
    echo "requirepass ${REDIS_PASSWORD}" >> "${REDIS_CONF}"
    echo "[Redis] Added requirepass directive."
fi

# ─── Harden: disable dangerous commands ──────────────────────────────────────
for cmd in FLUSHDB FLUSHALL CONFIG DEBUG; do
    if ! grep -q "rename-command ${cmd}" "${REDIS_CONF}" 2>/dev/null; then
        echo "rename-command ${cmd} \"\"" >> "${REDIS_CONF}"
    fi
done
echo "[Redis] Dangerous commands disabled."

# ─── Set max memory policy ──────────────────────────────────────────────────
if grep -q "^maxmemory-policy " "${REDIS_CONF}"; then
    sed -i 's/^maxmemory-policy .*/maxmemory-policy allkeys-lru/' "${REDIS_CONF}"
else
    echo "maxmemory-policy allkeys-lru" >> "${REDIS_CONF}"
fi

# ─── Restart Redis ──────────────────────────────────────────────────────────
systemctl enable redis-server
systemctl restart redis-server
echo "[Redis] Service restarted with password authentication."
