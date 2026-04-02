```
 _   _           _   _   _ _
| | | | ___  ___| |_| | | (_)_   _____
| |_| |/ _ \/ __| __| |_| | \ \ / / _ \
|  _  | (_) \__ \ |_|  _  | |\ V /  __/
|_| |_|\___/|___/\__|_| |_|_| \_/ \___|
```

# HostHive — The Hosting Panel That Thinks

HostHive is a production-grade hosting control panel for Debian 12 that combines traditional server management with AI-powered automation and Docker-based user isolation. It provides a modern, glassmorphism UI for managing domains, databases, email, DNS, SSL, backups, and more — all from a single panel.

> **AI-assisted. Docker-isolated. Developer-friendly.**

![HostHive Screenshot](https://hosthive.io/screenshot.png)
<!-- Replace with actual screenshot -->

---

## Key Features

### Core Hosting

- **Domain Management** — Nginx virtual hosts with templates
- **Database Management** — MySQL/MariaDB and PostgreSQL
- **Email** — Exim4 + Dovecot with DKIM/SPF/DMARC
- **DNS** — BIND9 zone management
- **FTP** — ProFTPD account management
- **SSL** — Let's Encrypt auto-renewal + custom certificates
- **Cron Jobs** — Visual cron builder
- **Backups** — Scheduled backups with S3/B2/Wasabi storage
- **File Manager** — Browser-based file manager with code editor

### AI Features

- **AI Assistant** — Built-in chat (OpenAI / Anthropic / Ollama)
- **AI Log Analyzer** — Detects errors and suggests fixes automatically
- **AI Nginx Optimizer** — Analyzes and improves Nginx configurations
- **AI Security Scanner** — Scores your server security 0-100 with recommendations
- **AI One-Click Installer** — Deploy 12+ apps (WordPress, Ghost, Nextcloud, etc.)

### MCP (Model Context Protocol)

- MCP server for **Claude Desktop** and **Cursor** integration
- 30+ MCP tools for managing servers through natural language
- Bearer token authentication

### Docker Isolation

- **Per-user Docker environments** with resource limits (CPU, RAM, IO)
- **Multi-webserver**: Nginx, Apache, OpenLiteSpeed, Caddy, Varnish
- **Multi-PHP**: 7.4, 8.0, 8.1, 8.2, 8.3
- **Multi-DB**: MySQL 8/9, MariaDB 11, Percona 8
- **Per-user Redis and Memcached**

### WordPress Manager

- Auto-detection of WordPress installations
- Core and plugin updates via WP-CLI
- Clone to staging environment
- Security check and hardening

### Monitoring

- Real-time server stats with animated gauges
- Anomaly detection (statistical analysis)
- Predictive disk usage forecasting
- Service health checks with auto-restart
- Traffic heatmap and GoAccess visitor reports

### Integrations

- **Cloudflare** — DNS sync + proxy toggle
- **S3 / B2 / Wasabi** — Remote backup storage
- **Telegram / Slack / Discord** — Notifications
- **Stripe** — Billing and invoicing
- **WHMCS / FossBilling** — Provisioning module
- **Prometheus + Grafana** — Metrics export
- **WireGuard** — VPN management

### Security

- Web Application Firewall (WAF)
- Fail2ban integration
- CSRF protection on all forms
- Rate limiting (per-IP and per-user)
- Full audit logging
- Fernet encryption for stored secrets
- HMAC-SHA256 agent authentication
- Path traversal and command injection prevention
- Docker-based user isolation

### UI / UX

- Dark and Light mode with smooth toggle
- Glassmorphism design language
- Parallax animated backgrounds
- Command Palette (`Ctrl+K`)
- 20+ keyboard shortcuts
- Multi-language support (English, Polish)
- Admin impersonation mode
- Responsive design with loading skeletons and toast notifications

---

## Quick Install

```bash
bash <(curl -sSL https://hosthive.io/install)
```

See [INSTALL.md](INSTALL.md) for detailed instructions.

## Requirements

| Requirement | Minimum |
|---|---|
| OS | Debian 12 (Bookworm) |
| RAM | 2 GB |
| Disk | 20 GB |
| CPU | 1 vCPU |
| Access | Root |

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy, Celery |
| Frontend | Vue 3, Vite, TailwindCSS, Pinia |
| Database | PostgreSQL 15 (panel), MySQL/MariaDB/PostgreSQL (users) |
| Web Server | Nginx (reverse proxy + user vhosts) |
| Containers | Docker, Docker Compose |
| Queue | Redis |
| Auth | JWT + refresh tokens, bcrypt, Fernet |
| AI | OpenAI API, Anthropic API, Ollama (local) |
| MCP | Model Context Protocol (stdio + SSE) |
| Monitoring | Prometheus, Grafana, GoAccess |

## Comparison

| Feature | HostHive | OpenPanel | cPanel | HestiaCP |
|---|:---:|:---:|:---:|:---:|
| AI Assistant | Yes | No | No | No |
| MCP Server (Claude/Cursor) | Yes | No | No | No |
| Docker Isolation | Yes | Yes | No | No |
| Multi-Webserver | Yes | Yes | No | Limited |
| Multi-PHP | Yes | Yes | Yes | Yes |
| Glassmorphism UI | Yes | No | No | No |
| Command Palette | Yes | No | No | No |
| AI Log Analyzer | Yes | No | No | No |
| AI Security Scanner | Yes | No | No | No |
| WordPress Manager | Yes | Yes | Yes | No |
| Anomaly Detection | Yes | No | No | No |
| Predictive Disk Usage | Yes | No | No | No |
| Cloudflare Integration | Yes | Yes | Yes | No |
| WireGuard VPN | Yes | No | No | No |
| Reseller System | Yes | No | Yes | Yes |
| White-label Branding | Yes | No | Yes | No |
| WHMCS Integration | Yes | Yes | Yes | Yes |
| Stripe Billing | Yes | No | No | No |
| Free & Open Source | Yes | Yes | No | Yes |

## Documentation

- [Installation Guide](INSTALL.md)
- [Security Architecture](SECURITY.md)
- [API Reference](API.md)
- [Integrations](INTEGRATIONS.md)
- [Changelog](CHANGELOG.md)

## Contributing

Contributions are welcome. Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and add tests
4. Run the test suite: `pytest tests/`
5. Commit with a descriptive message
6. Push to your fork and open a Pull Request

Please read the [Security Policy](SECURITY.md) before reporting vulnerabilities.

### Development Setup

```bash
git clone https://github.com/hosthive/hosthive.git
cd hosthive
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config/hosthive.conf.example config/hosthive.conf
python api/main.py --dev
```

## License

HostHive is released under the [MIT License](LICENSE).

---

**HostHive** — The Hosting Panel That Thinks.
