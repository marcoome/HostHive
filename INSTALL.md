# HostHive Installation Guide

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Operating System | Debian 12 (Bookworm) | Debian 12 (Bookworm) |
| RAM | 2 GB | 4 GB+ |
| Disk Space | 20 GB | 40 GB+ |
| CPU | 1 vCPU | 2+ vCPU |
| Access | Root | Root |
| Network | Public IP | Public IP with PTR record |

### Supported Only

- **Debian 12 (Bookworm)** — fresh installation only.
- Other distributions (Ubuntu, CentOS, etc.) are not supported.

---

## Pre-Installation Checklist

Before installing HostHive, confirm the following:

- [ ] Fresh Debian 12 server (no other panels installed)
- [ ] Root access (SSH as root or `sudo -i`)
- [ ] Public IP address assigned
- [ ] Hostname configured (`hostnamectl set-hostname panel.example.com`)
- [ ] DNS A record pointing to your server IP (optional but recommended)
- [ ] Ports 80, 443, and 8083 open in your cloud provider firewall
- [ ] No other web server, database server, or mail server running

---

## One-Command Install

```bash
bash <(curl -sSL https://hosthive.io/install)
```

The installer will:

1. Verify system requirements
2. Install all dependencies (Docker, Nginx, Python, etc.)
3. Configure the panel database
4. Set up Docker networks and base images
5. Generate SSL certificate for the panel
6. Create the admin account
7. Start all services

Installation takes approximately 5-15 minutes depending on your server specs and network speed.

At the end, the installer displays:

```
============================================
  HostHive installed successfully!

  Panel URL:  https://<YOUR_IP>:8083
  Username:   admin
  Password:   <generated_password>

  Save these credentials securely.
============================================
```

---

## Manual Installation

If you prefer to install step by step:

### Step 1 — Update the System

```bash
apt update && apt upgrade -y
```

### Step 2 — Install Prerequisites

```bash
apt install -y curl wget git sudo software-properties-common \
  apt-transport-https ca-certificates gnupg lsb-release
```

### Step 3 — Install Docker

```bash
curl -fsSL https://get.docker.com | bash
systemctl enable docker
systemctl start docker
```

### Step 4 — Install Python 3.11

```bash
apt install -y python3 python3-pip python3-venv
```

### Step 5 — Clone HostHive

```bash
git clone https://github.com/hosthive/hosthive.git /opt/hosthive
cd /opt/hosthive
```

### Step 6 — Create Virtual Environment

```bash
python3 -m venv /opt/hosthive/venv
source /opt/hosthive/venv/bin/activate
pip install -r requirements.txt
```

### Step 7 — Run Setup Script

```bash
bash scripts/setup.sh
```

This script will:

- Install and configure Nginx, BIND9, Exim4, Dovecot, ProFTPD
- Initialize the SQLite panel database
- Build Docker base images
- Generate cryptographic keys
- Create the admin user

### Step 8 — Start HostHive

```bash
systemctl enable hosthive
systemctl start hosthive
```

---

## Post-Installation

### Access the Panel

Open your browser and navigate to:

```
https://<YOUR_SERVER_IP>:8083
```

Accept the self-signed certificate warning on first access (you will configure a proper SSL certificate below).

### Default Credentials

The installer generates a random admin password. If you used the one-command installer, it was displayed at the end. For manual installation, find it with:

```bash
cat /opt/hosthive/data/admin_credentials.txt
```

### Change the Admin Password

1. Log in to the panel
2. Go to **Settings** > **Profile**
3. Click **Change Password**
4. Enter a strong password and save

Or via CLI:

```bash
hosthive admin password --user admin --password 'YourNewSecurePassword'
```

### Configure DNS

For full functionality (email, Let's Encrypt, etc.), configure DNS records:

| Type | Name | Value |
|---|---|---|
| A | panel.example.com | YOUR_SERVER_IP |
| A | ns1.example.com | YOUR_SERVER_IP |
| A | ns2.example.com | YOUR_SERVER_IP |
| NS | example.com | ns1.example.com |
| NS | example.com | ns2.example.com |

### Set Up SSL for the Panel

Once DNS is configured and pointing to your server:

1. Go to **Admin** > **Settings** > **Panel SSL**
2. Enter your panel hostname (e.g., `panel.example.com`)
3. Click **Issue Let's Encrypt Certificate**

Or via CLI:

```bash
hosthive admin ssl --hostname panel.example.com
```

The panel will restart and be available at `https://panel.example.com:8083`.

---

## Upgrading

### Automatic Upgrade

```bash
hosthive update
```

This will:

1. Back up the current installation
2. Pull latest changes
3. Run database migrations
4. Restart services

### Manual Upgrade

```bash
cd /opt/hosthive
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python scripts/migrate.py
systemctl restart hosthive
```

### Check Version

```bash
hosthive version
```

---

## Uninstalling

To completely remove HostHive:

```bash
bash /opt/hosthive/scripts/uninstall.sh
```

This will:

- Stop and remove all HostHive services
- Remove Docker containers and images created by HostHive
- Remove configuration files
- Optionally remove user data and databases

**Warning:** This is irreversible. Back up your data first.

---

## Troubleshooting

### Service Not Starting

Check the service status and logs:

```bash
systemctl status hosthive
journalctl -u hosthive -n 50 --no-pager
```

Common causes:

- **Port 8083 already in use** — Check with `ss -tlnp | grep 8083` and stop the conflicting service.
- **Python venv missing** — Recreate with `python3 -m venv /opt/hosthive/venv && source /opt/hosthive/venv/bin/activate && pip install -r requirements.txt`.
- **Database locked** — Restart the service: `systemctl restart hosthive`.

### Cannot Access the Panel

1. Verify the service is running: `systemctl is-active hosthive`
2. Check firewall rules: `iptables -L -n | grep 8083`
3. Open port in firewall: `ufw allow 8083/tcp` (if using UFW)
4. Check cloud provider firewall/security group for port 8083
5. Try accessing via HTTP: `http://<IP>:8080` (fallback port)

### Database Connection Issues

For the panel database (SQLite):

```bash
# Check database file exists and permissions
ls -la /opt/hosthive/data/hosthive.db

# Test database integrity
sqlite3 /opt/hosthive/data/hosthive.db "PRAGMA integrity_check;"
```

For user databases (MySQL/MariaDB):

```bash
# Check MySQL is running inside Docker
docker ps | grep mysql

# Check MySQL logs
docker logs hosthive-mysql

# Test connection
docker exec hosthive-mysql mysql -u root -p -e "SELECT 1;"
```

### SSL Certificate Issues

**Let's Encrypt failing:**

- Ensure ports 80 and 443 are open and accessible from the internet
- Ensure DNS A record is pointing to the correct IP
- Check rate limits: Let's Encrypt has a limit of 5 duplicate certificates per week
- View Certbot logs: `cat /var/log/letsencrypt/letsencrypt.log`

**Self-signed certificate warnings:**

- This is normal before configuring Let's Encrypt
- Configure panel SSL (see Post-Installation above) to resolve

### Firewall Blocking

HostHive requires the following ports:

| Port | Protocol | Service |
|---|---|---|
| 22 | TCP | SSH |
| 25 | TCP | SMTP |
| 53 | TCP/UDP | DNS |
| 80 | TCP | HTTP |
| 110 | TCP | POP3 |
| 143 | TCP | IMAP |
| 443 | TCP | HTTPS |
| 465 | TCP | SMTPS |
| 587 | TCP | Submission |
| 993 | TCP | IMAPS |
| 995 | TCP | POP3S |
| 8083 | TCP | HostHive Panel |

Open all required ports:

```bash
ufw allow 22,25,53,80,110,143,443,465,587,993,995,8083/tcp
ufw allow 53/udp
ufw reload
```

---

For further help, see the [API Reference](API.md) or open an issue on GitHub.
