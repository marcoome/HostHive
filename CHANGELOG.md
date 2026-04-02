# Changelog

## v1.0.0 (2026-04-02) — Initial Release

### Core Features
- Complete hosting control panel for Debian 12
- Domain management with Nginx virtual hosts
- MySQL/MariaDB and PostgreSQL database management
- Email management (Exim4 + Dovecot) with DKIM/SPF/DMARC
- DNS zone management (BIND9)
- FTP account management (ProFTPD)
- SSL certificate management (Let's Encrypt + custom)
- Cron job management with visual builder
- Backup system with S3/B2/Wasabi support
- File manager with code editor
- Web terminal (xterm.js)

### AI Features
- Built-in AI assistant (OpenAI/Anthropic/Ollama)
- AI log analyzer with auto-fix
- AI nginx config optimizer
- AI security scanner (score 0-100)
- AI one-click app installer (12+ apps)

### MCP Server
- Model Context Protocol server for Claude Desktop/Cursor
- 30+ MCP tools for server management
- Bearer token authentication

### Docker Isolation
- Per-user Docker environments
- Multi-webserver: Nginx, Apache, OpenLiteSpeed, Caddy, Varnish
- Multi-PHP: 7.4, 8.0, 8.1, 8.2, 8.3
- Multi-DB: MySQL 8/9, MariaDB 11, Percona 8
- Per-user Redis and Memcached
- Resource limits via Docker (CPU, RAM, IO)

### WordPress Manager
- Auto-detection of WP installations
- Core and plugin updates via WP-CLI
- Clone to staging
- Security check

### Monitoring
- Real-time server stats with gauges
- Anomaly detection (statistical)
- Predictive disk usage
- Service health checks with auto-restart
- Traffic heatmap
- GoAccess visitor reports

### Integrations
- Cloudflare DNS sync + proxy
- S3/B2/Wasabi backup storage
- Telegram/Slack/Discord notifications
- Stripe billing
- WHMCS/FossBilling provisioning
- Prometheus metrics + Grafana
- WireGuard VPN management

### Security
- Web Application Firewall (WAF)
- Fail2ban integration
- CSRF protection
- Rate limiting
- Audit logging
- Fernet encryption for stored secrets
- HMAC-SHA256 agent auth
- Path traversal prevention
- Docker-based user isolation

### UI/UX
- Dark and Light mode with toggle
- Glassmorphism design
- Parallax animated backgrounds
- Command Palette (Ctrl+K)
- Keyboard shortcuts (20+)
- Multi-language (English, Polish)
- Admin impersonation
- Responsive design
- Loading skeletons
- Toast notifications

### Reseller System
- White-label branding per reseller
- Custom domains per reseller
- User isolation
- Resource limits

### Other
- One-command installer
- CLI tool (hosthive)
- Public status page
- API keys with scoped permissions
- Landing page with comparison table
