#!/usr/bin/env bash
###############################################################################
# HostHive — Fail2ban Setup Module
# Configures jails for SSH brute-force and HostHive login attempts.
# Idempotent: overwrites jail config each run.
###############################################################################
set -euo pipefail

JAIL_LOCAL="/etc/fail2ban/jail.local"
FILTER_DIR="/etc/fail2ban/filter.d"
HOSTHIVE_FILTER="${FILTER_DIR}/hosthive-auth.conf"
HOSTHIVE_LOG="/var/log/hosthive/access.log"

echo "[Fail2ban] Configuring fail2ban..."

# ─── Ensure log file exists for the panel filter ────────────────────────────
mkdir -p "$(dirname "${HOSTHIVE_LOG}")"
touch "${HOSTHIVE_LOG}"
chown hosthive:hosthive "${HOSTHIVE_LOG}"

# ─── Write jail.local ───────────────────────────────────────────────────────
cat > "${JAIL_LOCAL}" <<'JAIL_EOF'
# HostHive fail2ban configuration
# Managed by HostHive installer — manual edits may be overwritten.

[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5
backend  = systemd

# ─── SSH jail ────────────────────────────────────────────────────────────────
[sshd]
enabled  = true
port     = ssh
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 5
bantime  = 3600

# ─── HostHive login jail ────────────────────────────────────────────────────
[hosthive-auth]
enabled  = true
port     = 8083
filter   = hosthive-auth
logpath  = /var/log/hosthive/access.log
maxretry = 5
findtime = 300
bantime  = 1800
JAIL_EOF

echo "[Fail2ban] Wrote ${JAIL_LOCAL}."

# ─── Write custom filter for panel authentication failures ──────────────────
cat > "${HOSTHIVE_FILTER}" <<'FILTER_EOF'
# HostHive authentication failure filter
# Matches log lines written by the API on failed login attempts.
#
# Expected log format (JSON or structured):
#   {"timestamp": "...", "ip": "<HOST>", "event": "auth_failure", ...}
#   or plain:  YYYY-MM-DD HH:MM:SS AUTH_FAILURE ip=<HOST> ...

[Definition]
failregex = ^.*AUTH_FAILURE\s+ip=<HOST>.*$
            ^.*"event"\s*:\s*"auth_failure".*"ip"\s*:\s*"<HOST>".*$

ignoreregex =
FILTER_EOF

echo "[Fail2ban] Wrote filter ${HOSTHIVE_FILTER}."

# ─── Enable and restart ─────────────────────────────────────────────────────
systemctl enable fail2ban
systemctl restart fail2ban
echo "[Fail2ban] Service restarted."
