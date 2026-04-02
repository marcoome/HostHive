#!/usr/bin/env bash
###############################################################################
# HostHive — UFW Firewall Setup Module
# Opens required ports and enables the firewall. Idempotent.
###############################################################################
set -euo pipefail

echo "[Firewall] Configuring UFW..."

# ─── Reset to defaults (idempotent starting point) ──────────────────────────
ufw --force reset > /dev/null 2>&1

# ─── Default policies ───────────────────────────────────────────────────────
ufw default deny incoming
ufw default allow outgoing

# ─── Allow required ports ───────────────────────────────────────────────────
# SSH
ufw allow 22/tcp comment "SSH"

# HTTP / HTTPS
ufw allow 80/tcp  comment "HTTP"
ufw allow 443/tcp comment "HTTPS"

# HostHive web interface
ufw allow 8083/tcp comment "HostHive UI"

# FTP (proftpd)
ufw allow 21/tcp comment "FTP"

# Mail: SMTP, submission, IMAPS
ufw allow 25/tcp  comment "SMTP"
ufw allow 587/tcp comment "SMTP Submission"
ufw allow 993/tcp comment "IMAPS"

# MariaDB (local connections; remove if not needed externally)
ufw allow 3306/tcp comment "MariaDB"

# ─── Enable UFW (non-interactive) ───────────────────────────────────────────
ufw --force enable
echo "[Firewall] UFW enabled."

# ─── Show status ────────────────────────────────────────────────────────────
ufw status verbose
echo "[Firewall] Setup complete."
