# HostHive API Reference

**Base URL:** `https://your-server:8443/api/v1`
**Version:** 0.1.0

---

## Authentication

### JWT Bearer Token

Most endpoints require a JSON Web Token passed via the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Tokens are obtained from `POST /api/v1/auth/login` and refreshed via `POST /api/v1/auth/refresh`. Access tokens expire after a configurable period (default: 30 minutes). Refresh tokens expire after a configurable number of days (default: 7).

### API Keys

API keys use the `hh_` prefix and are passed via the `X-API-Key` header:

```
X-API-Key: hh_<key>
```

API keys support scoped permissions (`read_only`, `read_write`, `full_access`, `custom`) and can have an optional expiration date. Maximum 20 active keys per user.

### Billing API Key

Billing endpoints (`/api/v1/billing`) use a separate authentication mechanism: IP whitelist combined with a dedicated `X-Billing-Key` header. These endpoints do not use JWT.

### Metrics Bearer Token

The `/metrics` endpoint uses a standalone Bearer token (not JWT) configured via the `METRICS_TOKEN` environment variable.

### Rate Limits

- **Login:** Brute-force protection per IP (auto-lockout after repeated failures)
- **AI endpoints:** 20 requests per minute per user
- **General:** No global rate limit documented; per-endpoint limits may apply

---

## Endpoints

### Auth (`/api/v1/auth`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/auth/login` | Authenticate and receive JWT tokens | None |
| POST | `/auth/refresh` | Refresh an expired access token | None (refresh token in body) |
| POST | `/auth/logout` | Invalidate refresh token | Bearer |
| POST | `/auth/change-password` | Change current user's password | Bearer |
| GET | `/auth/me` | Get current authenticated user | Bearer |

---

### Users (`/api/v1/users`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/users/` | List users (paginated, filterable by role/status) | Admin |
| POST | `/users/` | Create a new user | Admin |
| GET | `/users/{user_id}` | Get user details | Admin |
| PUT | `/users/{user_id}` | Update user | Admin |
| DELETE | `/users/{user_id}` | Delete user and all resources | Admin |
| POST | `/users/{user_id}/suspend` | Suspend user | Admin |
| POST | `/users/{user_id}/unsuspend` | Unsuspend user | Admin |
| GET | `/users/{user_id}/stats` | Get user resource usage stats | Admin |

---

### Domains (`/api/v1/domains`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/domains/` | List domains (own for users, all for admins) | Bearer |
| POST | `/domains/` | Create a new domain with vhost | Bearer |
| PUT | `/domains/{domain_id}` | Update domain configuration | Bearer |
| DELETE | `/domains/{domain_id}` | Delete domain and vhost | Bearer |
| POST | `/domains/{domain_id}/enable-ssl` | Issue SSL certificate via Certbot | Bearer |
| GET | `/domains/{domain_id}/logs` | Get nginx access/error logs (last 100 lines) | Bearer |
| GET | `/domains/{domain_id}/stats` | Get domain bandwidth and request stats | Bearer |

---

### Databases (`/api/v1/databases`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/databases/` | List databases | Bearer |
| POST | `/databases/` | Create database (MySQL/MariaDB/PostgreSQL) | Bearer |
| GET | `/databases/{db_id}` | Get database details | Bearer |
| DELETE | `/databases/{db_id}` | Delete database | Bearer |
| POST | `/databases/{db_id}/reset-password` | Reset database password | Bearer |

---

### Email (`/api/v1/email`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/email/` | List mailboxes | Bearer |
| POST | `/email/` | Create mailbox | Bearer |
| GET | `/email/{email_id}` | Get mailbox details | Bearer |
| PUT | `/email/{email_id}` | Update mailbox (quota, active status) | Bearer |
| DELETE | `/email/{email_id}` | Delete mailbox | Bearer |
| POST | `/email/aliases` | Create email alias | Bearer |
| GET | `/email/aliases` | List email aliases | Bearer |
| DELETE | `/email/aliases/{alias_id}` | Delete email alias | Bearer |
| GET | `/email/queue` | View mail queue | Admin |
| POST | `/email/queue/flush` | Flush mail queue | Admin |

---

### DNS (`/api/v1/dns`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/dns/zones` | List DNS zones | Bearer |
| POST | `/dns/zones` | Create DNS zone | Bearer |
| GET | `/dns/zones/{zone_id}` | Get zone with records | Bearer |
| DELETE | `/dns/zones/{zone_id}` | Delete DNS zone | Bearer |
| GET | `/dns/zones/{zone_id}/records` | List DNS records in zone | Bearer |
| POST | `/dns/zones/{zone_id}/records` | Add DNS record | Bearer |
| DELETE | `/dns/zones/{zone_id}/records/{record_id}` | Delete DNS record | Bearer |
| POST | `/dns/zones/{zone_id}/import` | Import BIND zone file (multipart upload) | Bearer |
| GET | `/dns/zones/{zone_id}/export` | Export zone as BIND format | Bearer |

---

### FTP (`/api/v1/ftp`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/ftp/` | List FTP accounts | Bearer |
| POST | `/ftp/` | Create FTP account | Bearer |
| GET | `/ftp/{ftp_id}` | Get FTP account details | Bearer |
| PUT | `/ftp/{ftp_id}` | Update FTP account (active status) | Bearer |
| DELETE | `/ftp/{ftp_id}` | Delete FTP account | Bearer |

---

### Cron Jobs (`/api/v1/cron`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/cron/` | List cron jobs | Bearer |
| POST | `/cron/` | Create cron job | Bearer |
| GET | `/cron/{cron_id}` | Get cron job details | Bearer |
| PUT | `/cron/{cron_id}` | Update cron job | Bearer |
| DELETE | `/cron/{cron_id}` | Delete cron job | Bearer |
| POST | `/cron/{cron_id}/run-now` | Execute cron job immediately | Bearer |

---

### SSL Certificates (`/api/v1/ssl`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/ssl/` | List SSL certificates | Bearer |
| POST | `/ssl/issue/{domain_id}` | Issue Let's Encrypt certificate | Bearer |
| POST | `/ssl/install/{domain_id}` | Install custom SSL certificate | Bearer |
| POST | `/ssl/renew/{domain_id}` | Renew existing certificate | Bearer |
| GET | `/ssl/expiring` | List certificates expiring within 30 days | Bearer |

---

### Backups (`/api/v1/backups`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/backups/` | List backups | Bearer |
| POST | `/backups/create` | Trigger backup (async via Celery) | Bearer |
| POST | `/backups/{backup_id}/restore` | Restore from backup | Bearer |
| DELETE | `/backups/{backup_id}` | Delete backup | Bearer |
| GET | `/backups/{backup_id}/download` | Get signed download URL (1h expiry) | Bearer |

---

### Files (`/api/v1/files`)

All paths are sandboxed within `/home/{username}/`. Admins can access any `/home/` path.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/files/list` | List directory contents | Bearer |
| POST | `/files/upload` | Upload file (multipart) | Bearer |
| GET | `/files/download` | Download file content | Bearer |
| GET | `/files/read` | Read file content | Bearer |
| PUT | `/files/write` | Write file content | Bearer |
| POST | `/files/create-dir` | Create directory | Bearer |
| POST | `/files/rename` | Rename/move file or directory | Bearer |
| DELETE | `/files/delete` | Delete file or directory | Bearer |
| POST | `/files/chmod` | Change file permissions | Bearer |
| POST | `/files/compress` | Compress files into archive | Bearer |
| POST | `/files/extract` | Extract archive | Bearer |

---

### Packages (`/api/v1/packages`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/packages/` | List hosting packages | Admin |
| POST | `/packages/` | Create hosting package | Admin |
| GET | `/packages/{pkg_id}` | Get package details | Admin |
| PUT | `/packages/{pkg_id}` | Update package | Admin |
| DELETE | `/packages/{pkg_id}` | Delete package (fails if users assigned) | Admin |
| GET | `/packages/{pkg_id}/users` | List users on this package | Admin |

---

### Server (`/api/v1/server`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/server/stats` | Current CPU/RAM/disk/network stats | Admin |
| GET | `/server/stats/history` | Historical stats (up to 168 hours) | Admin |
| GET | `/server/services` | List all service statuses | Admin |
| POST | `/server/services/{service_name}/restart` | Restart a service | Admin |
| GET | `/server/firewall` | List firewall rules | Admin |
| POST | `/server/firewall` | Add firewall rule | Admin |
| DELETE | `/server/firewall/{rule_id}` | Delete firewall rule | Admin |
| GET | `/server/fail2ban` | List Fail2ban jails | Admin |
| POST | `/server/fail2ban/unban` | Unban an IP address | Admin |
| GET | `/server/logs/{service}` | Get service logs (up to 1000 lines) | Admin |

---

### WAF (`/api/v1/waf`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/waf/status` | WAF status for all domains | Admin |
| GET | `/waf/stats` | Global WAF statistics | Admin |
| POST | `/waf/{domain}/enable` | Enable WAF for domain | Admin |
| POST | `/waf/{domain}/disable` | Disable WAF for domain | Admin |
| GET | `/waf/{domain}/rules` | List WAF rules for domain | Admin |
| POST | `/waf/{domain}/rules` | Add custom WAF rule | Admin |
| DELETE | `/waf/{domain}/rules/{rule_id}` | Delete WAF rule | Admin |
| GET | `/waf/{domain}/log` | View blocked requests log | Admin |
| PUT | `/waf/{domain}/mode` | Set WAF mode (detect/block) | Admin |

---

### Apps (`/api/v1/apps`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/apps/` | List running applications | Bearer |
| POST | `/apps/deploy` | Deploy Node.js or Python app | Bearer |
| POST | `/apps/{domain}/stop` | Stop application | Bearer |
| POST | `/apps/{domain}/start` | Start application | Bearer |
| POST | `/apps/{domain}/restart` | Restart application | Bearer |
| GET | `/apps/{domain}/status` | Get app status and resource usage | Bearer |
| GET | `/apps/{domain}/logs` | Get application logs | Bearer |
| PUT | `/apps/{domain}/env` | Update environment variables | Bearer |

---

### Resources (`/api/v1/resources`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/resources/overview` | All users resource usage overview | Admin |
| GET | `/resources/users/{username}/usage` | User resource usage (cgroup) | Admin |
| GET | `/resources/users/{username}/limits` | Get user resource limits | Admin |
| PUT | `/resources/users/{username}/limits` | Set user CPU/RAM/IO limits | Admin |
| GET | `/resources/domains/{domain}/usage` | Domain resource usage | Admin |
| PUT | `/resources/domains/{domain}/php-limits` | Set PHP-FPM pool limits | Admin |

---

### Docker (`/api/v1/docker`)

Requires Docker installed on the server. Returns 503 if unavailable.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/docker/containers` | List containers | Bearer |
| POST | `/docker/containers/deploy` | Deploy new container | Bearer |
| POST | `/docker/containers/{id}/start` | Start container | Bearer |
| POST | `/docker/containers/{id}/stop` | Stop container | Bearer |
| POST | `/docker/containers/{id}/restart` | Restart container | Bearer |
| DELETE | `/docker/containers/{id}` | Remove container | Bearer |
| GET | `/docker/containers/{id}/logs` | Get container logs | Bearer |
| GET | `/docker/containers/{id}/stats` | Get container resource stats | Bearer |
| POST | `/docker/compose/deploy` | Deploy from docker-compose.yml | Bearer |
| POST | `/docker/compose/validate` | Validate compose file | Bearer |

---

### WordPress (`/api/v1/wordpress`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/wordpress/` | List detected WordPress installations | Bearer |
| GET | `/wordpress/{domain}/info` | Get WP version, plugins, themes, health | Bearer |
| POST | `/wordpress/{domain}/update-core` | Update WordPress core | Bearer |
| POST | `/wordpress/{domain}/update-plugins` | Update all plugins | Bearer |
| POST | `/wordpress/{domain}/backup` | Backup WordPress installation | Bearer |
| POST | `/wordpress/{domain}/clone` | Clone to staging domain | Bearer |
| POST | `/wordpress/{domain}/search-replace` | Search and replace in DB | Bearer |
| GET | `/wordpress/{domain}/security-check` | Run security vulnerability check | Bearer |

---

### AI (`/api/v1/ai`)

Rate limited to 20 requests/minute per user. Requires AI settings to be configured.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/ai/chat` | AI chat (supports SSE streaming) | Bearer |
| GET | `/ai/conversations` | List user's conversations | Bearer |
| GET | `/ai/conversations/{id}` | Get conversation with messages | Bearer |
| DELETE | `/ai/conversations/{id}` | Delete conversation | Bearer |
| GET | `/ai/insights` | List AI-generated insights | Bearer |
| POST | `/ai/insights/{id}/resolve` | Mark insight as resolved | Bearer |
| POST | `/ai/insights/{id}/autofix` | Execute auto-fix for insight | Admin |
| POST | `/ai/nginx/optimize` | AI-powered nginx config optimization | Bearer |
| POST | `/ai/nginx/apply` | Apply nginx optimization | Admin |
| POST | `/ai/security/scan` | Run AI security scan | Admin |
| POST | `/ai/install-app` | One-click app installer | Bearer |
| GET | `/ai/settings` | Get AI settings | Admin |
| PUT | `/ai/settings` | Update AI settings | Admin |
| GET | `/ai/usage` | Token usage statistics | Admin |

---

### Monitoring (`/api/v1/monitoring`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/monitoring/health` | Current health status for all services | Admin |
| GET | `/monitoring/health/history` | Health check history (up to 168h) | Admin |
| GET | `/monitoring/incidents` | List monitoring incidents | Admin |
| GET | `/monitoring/anomalies` | List anomaly alerts | Admin |
| POST | `/monitoring/anomalies/{id}/acknowledge` | Acknowledge anomaly alert | Admin |
| GET | `/monitoring/disk-prediction` | Predictive disk usage analysis | Admin |
| GET | `/monitoring/bandwidth/{domain}` | Domain bandwidth stats (up to 365 days) | Admin |
| GET | `/monitoring/heatmap` | Traffic heatmap (up to 30 days) | Admin |
| GET | `/monitoring/realtime` | Current real-time stats snapshot | Admin |

---

### Environments (`/api/v1/environments`)

Docker-based user isolation with per-user webserver, DB, PHP, and cache containers.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/environments/` | List all environments | Admin |
| GET | `/environments/{user_id}` | Get environment details | Bearer (own) / Admin |
| POST | `/environments/{user_id}/create` | Create isolated environment | Admin |
| DELETE | `/environments/{user_id}` | Destroy environment | Admin |
| POST | `/environments/{user_id}/switch-webserver` | Switch webserver (nginx/apache/openlitespeed) | Admin |
| POST | `/environments/{user_id}/switch-db` | Switch database version | Admin |
| POST | `/environments/{user_id}/add-php` | Add PHP version | Admin |
| POST | `/environments/{user_id}/remove-php` | Remove PHP version | Admin |
| POST | `/environments/{user_id}/toggle-redis` | Enable/disable Redis | Admin |
| POST | `/environments/{user_id}/toggle-memcached` | Enable/disable Memcached | Admin |
| PUT | `/environments/{user_id}/resources` | Update resource limits | Admin |
| GET | `/environments/{user_id}/usage` | Current resource usage | Bearer (own) / Admin |
| GET | `/environments/{user_id}/containers` | List containers with status | Bearer (own) / Admin |

---

### Analytics (`/api/v1/analytics`)

GoAccess-powered visitor analytics.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/analytics/{domain}/report` | Get or generate GoAccess report | Bearer |
| GET | `/analytics/{domain}/stats` | Parsed visitor statistics (JSON) | Bearer |
| GET | `/analytics/{domain}/visitors` | Real-time visitor count | Bearer |
| GET | `/analytics/{domain}/top-pages` | Top pages by visits | Bearer |
| GET | `/analytics/{domain}/top-countries` | Top countries | Bearer |
| POST | `/analytics/{domain}/generate` | Force regenerate report | Bearer |

---

### Integrations (`/api/v1/integrations`) -- Admin Only

Supports: Cloudflare, S3, Telegram, WHMCS, Stripe, and more.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/integrations/` | List all integrations with status | Admin |
| GET | `/integrations/{name}` | Get integration config (sensitive fields masked) | Admin |
| PUT | `/integrations/{name}` | Update integration config (encrypted at rest) | Admin |
| POST | `/integrations/{name}/test` | Test integration connection | Admin |
| POST | `/integrations/{name}/toggle` | Enable or disable integration | Admin |

---

### Audit (`/api/v1/audit`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/audit/` | List audit log entries (paginated, filterable) | Admin |
| GET | `/audit/export` | Export audit log as CSV (streaming) | Admin |
| GET | `/audit/suspicious` | Detect suspicious activity (>10 actions/min) | Admin |

---

### API Keys (`/api/v1/api-keys`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/api-keys/` | List user's API keys (prefix only) | Bearer |
| POST | `/api-keys/` | Generate new API key (full key shown once) | Bearer |
| DELETE | `/api-keys/{key_id}` | Revoke API key | Bearer |
| GET | `/api-keys/{key_id}/usage` | Get key usage stats | Bearer |

---

### Status (`/api/v1/status`) -- Public

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/status/` | Public status of all services | None |
| GET | `/status/incidents` | List incidents (last 30 days) | None |
| POST | `/status/incidents` | Create incident | Admin |
| PUT | `/status/incidents/{id}` | Update incident status | Admin |
| GET | `/status/widget` | Embeddable status widget (JSON or HTML) | None |

---

### Billing (`/api/v1/billing`)

Uses IP whitelist + `X-Billing-Key` header authentication (not JWT).

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/billing/provision` | Provision new account from billing system | Billing Key |
| POST | `/billing/suspend/{user_id}` | Suspend account | Billing Key |
| POST | `/billing/unsuspend/{user_id}` | Unsuspend account | Billing Key |
| POST | `/billing/terminate/{user_id}` | Terminate account | Billing Key |
| POST | `/billing/stripe/webhook` | Stripe webhook handler (signature verified) | Stripe Signature |
| GET | `/billing/stripe/plans` | List available Stripe plans | None |
| POST | `/billing/stripe/checkout` | Create Stripe checkout session | None |

---

### Metrics (`/metrics`)

Prometheus-compatible metrics in text exposition format.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/metrics/` | Prometheus metrics (CPU, RAM, disk, domains, users, uptime) | Metrics Bearer Token |

---

### Admin (`/api/v1/admin`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/admin/rotate-secrets` | Rotate JWT and agent secrets, invalidate all sessions | Admin |
| GET | `/admin/system-info` | OS version, Python version, installed services, uptime | Admin |
| POST | `/admin/maintenance-mode` | Toggle maintenance mode | Admin |

---

### Reseller (`/api/v1/reseller`) -- Reseller/Admin Only

Strict isolation: resellers can only manage users they created.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/reseller/dashboard` | Reseller overview stats | Reseller |
| GET | `/reseller/users` | List reseller's own users | Reseller |
| POST | `/reseller/users` | Create user under reseller | Reseller |
| PUT | `/reseller/users/{user_id}` | Update reseller's user | Reseller |
| DELETE | `/reseller/users/{user_id}` | Delete reseller's user | Reseller |
| POST | `/reseller/users/{user_id}/suspend` | Suspend reseller's user | Reseller |
| POST | `/reseller/users/{user_id}/unsuspend` | Unsuspend reseller's user | Reseller |
| GET | `/reseller/branding` | Get reseller branding | Reseller |
| PUT | `/reseller/branding` | Update reseller branding | Reseller |
| GET | `/reseller/limits` | View resource limits vs usage | Reseller |
| GET | `/reseller/packages` | List available packages | Reseller |

---

### WireGuard (`/api/v1/wireguard`) -- Admin Only

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/wireguard/peers` | List all WireGuard peers | Admin |
| POST | `/wireguard/peers` | Create peer (returns config + QR code) | Admin |
| DELETE | `/wireguard/peers/{peer_id}` | Remove peer | Admin |
| GET | `/wireguard/peers/{peer_id}/config` | Download client config file | Admin |
| GET | `/wireguard/peers/{peer_id}/qr` | Get QR code image (PNG) | Admin |
| GET | `/wireguard/status` | WireGuard interface status | Admin |

---

### Branding (`/api/v1/branding`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/branding/` | Get branding configuration | None |
| PUT | `/branding/` | Update branding configuration | Admin |

---

### Email Auth (`/api/v1/email/auth`)

DKIM, SPF, and DMARC management.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/email/auth/{domain}/status` | Get SPF/DKIM/DMARC status | Bearer |
| POST | `/email/auth/{domain}/setup-dkim` | Generate DKIM keys | Admin |
| GET | `/email/auth/{domain}/dns-records` | Get required DNS records for email auth | Bearer |
| POST | `/email/auth/{domain}/verify` | Verify all email auth records | Bearer |

---

### MCP (`/mcp` on port 8765)

Model Context Protocol server for AI/LLM tool integration. Uses JSON-RPC protocol with Bearer token authentication.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/mcp` | JSON-RPC endpoint (initialize, tools/list, tools/call, resources/list, resources/read) | MCP Bearer Token |

---

### TOTP Two-Factor Authentication (`/api/v1/auth/2fa`)

TOTP-based two-factor authentication. Mounted under the auth prefix. Setup generates a QR code and backup codes; login requires a pending token from the initial password auth step.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/auth/2fa/status` | Check if 2FA is enabled for current user | Bearer |
| POST | `/auth/2fa/setup` | Generate TOTP secret, QR code, and backup codes | Bearer |
| POST | `/auth/2fa/verify` | Verify TOTP code to confirm setup (enables 2FA) | Bearer |
| POST | `/auth/2fa/disable` | Disable 2FA (requires current TOTP code) | Bearer |
| POST | `/auth/2fa/login` | Complete login with TOTP code (after password auth) | None (pending token in body) |
| POST | `/auth/2fa/backup-verify` | Complete login with a one-time backup code | None (pending token in body) |

**Example -- Setup 2FA:**

```http
POST /api/v1/auth/2fa/setup HTTP/1.1
Authorization: Bearer <access_token>
```

```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "otpauth_uri": "otpauth://totp/NovaPanel:admin@example.com?secret=JBSWY3DPEHPK3PXP&issuer=NovaPanel",
  "qr_code_base64": "iVBORw0KGgo...",
  "backup_codes": ["a1b2c3d4", "e5f6g7h8", "..."]
}
```

---

### WebAuthn / Passkeys (`/api/v1/auth/webauthn`)

FIDO2/WebAuthn passwordless authentication. Supports passkey registration for logged-in users and passwordless login. Challenges are stored in Redis with a 5-minute TTL.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/auth/webauthn/register/options` | Generate registration options for a new passkey | Bearer |
| POST | `/auth/webauthn/register/verify` | Verify attestation and store new credential | Bearer |
| POST | `/auth/webauthn/login/options` | Generate authentication options (optional username hint) | None |
| POST | `/auth/webauthn/login/verify` | Verify assertion and return JWT tokens | None |
| GET | `/auth/webauthn/credentials` | List all WebAuthn credentials for current user | Bearer |
| DELETE | `/auth/webauthn/credentials/{credential_id}` | Delete a WebAuthn credential | Bearer |

---

### Dashboard (`/api/v1/dashboard`)

Aggregated dashboard statistics. Admins see full server stats and historical data; regular users see only their own resource counts.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/dashboard` | Get dashboard stats (CPU, RAM, disk, resource counts, history) | Bearer |

**Example -- Dashboard Stats (admin):**

```http
GET /api/v1/dashboard HTTP/1.1
Authorization: Bearer <access_token>
```

```json
{
  "cpu_usage": 12.5,
  "cpu_cores": 4,
  "ram_used": 2147483648,
  "ram_total": 8589934592,
  "ram_usage": 25.0,
  "disk_used": 42949672960,
  "disk_total": 107374182400,
  "disk_usage": 40,
  "domains_count": 15,
  "databases_count": 8,
  "email_count": 22,
  "ftp_count": 5,
  "user_count": 10,
  "cpu_history": [10.2, 11.5, 12.5],
  "ram_history": [24.1, 24.8, 25.0],
  "history_timestamps": ["2026-04-06T10:00:00", "2026-04-06T10:05:00", "2026-04-06T10:10:00"]
}
```

---

### PHP (`/api/v1/php`) -- Admin Only

Manage PHP installations, php.ini configuration, extensions, and FPM pools on Debian 12. Only whitelisted php.ini directives may be updated for safety.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/php/versions` | List all installed PHP versions with FPM status | Admin |
| GET | `/php/{version}/config` | Get parsed php.ini settings for a version and SAPI | Admin |
| PUT | `/php/{version}/config` | Update php.ini directives (whitelisted only) | Admin |
| GET | `/php/{version}/extensions` | List loaded and available PHP extensions | Admin |
| POST | `/php/{version}/extensions` | Enable or disable a PHP extension | Admin |
| POST | `/php/install/{version}` | Install a new PHP version from Sury repository | Admin |
| DELETE | `/php/{version}` | Uninstall a PHP version (refuses to remove last) | Admin |
| GET | `/php/{version}/fpm/status` | Get PHP-FPM service and pool status | Admin |

**Example -- Update PHP Config:**

```http
PUT /api/v1/php/8.2/config HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "directives": {
    "memory_limit": "512M",
    "upload_max_filesize": "128M",
    "post_max_size": "128M"
  },
  "sapi": "fpm"
}
```

```json
{
  "detail": "PHP 8.2 (fpm) configuration updated.",
  "updated_directives": {
    "memory_limit": "512M",
    "upload_max_filesize": "128M",
    "post_max_size": "128M"
  },
  "ini_path": "/etc/php/8.2/fpm/php.ini",
  "backup_path": "/etc/php/8.2/fpm/php.ini.bak.hosthive",
  "warnings": []
}
```

---

### Security (`/api/v1/security`) -- Admin Only

Security scanning and hardening: comprehensive audits, ClamAV malware scanning, SSH configuration analysis and hardening, file permission checks, system update management, open port scanning, and login history analysis.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/security/scan` | Run comprehensive security audit (SSH, ports, permissions, updates) | Admin |
| GET | `/security/malware` | ClamAV service status and last scan summary | Admin |
| POST | `/security/malware/scan` | Trigger ClamAV scan on a specific path | Admin |
| GET | `/security/ssh` | Analyze current SSH configuration for security issues | Admin |
| POST | `/security/ssh/harden` | Apply SSH hardening settings to sshd_config | Admin |
| GET | `/security/permissions` | Check for common file permission security issues | Admin |
| GET | `/security/updates` | Check for available system updates | Admin |
| POST | `/security/updates/apply` | Apply security or system updates | Admin |
| GET | `/security/ports` | Scan for open listening ports | Admin |
| GET | `/security/login-history` | Parse recent login attempts from auth.log | Admin |

**Example -- Security Scan:**

```http
GET /api/v1/security/scan HTTP/1.1
Authorization: Bearer <access_token>
```

```json
{
  "timestamp": "2026-04-06T12:00:00+00:00",
  "checks": [
    {"name": "SSH root login", "status": "pass", "score": 10},
    {"name": "Open ports", "status": "warn", "score": 5}
  ],
  "score": 75,
  "max_score": 100
}
```

---

### Settings (`/api/v1/settings`)

User notification preferences.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/settings/notifications` | Get notification preferences for current user | Bearer |
| PUT | `/settings/notifications` | Update notification preferences | Bearer |

---

### Cache (`/api/v1/cache`) -- Admin Only

Manage Redis, Memcached, Varnish, and PHP OPcache cache services. Includes status monitoring, flushing, and statistics.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/cache/status` | Overview of all cache services (Redis, Memcached, Varnish, OPcache) | Admin |
| GET | `/cache/redis/info` | Parsed Redis INFO statistics | Admin |
| POST | `/cache/redis/flush` | Flush entire Redis cache (FLUSHALL) | Admin |
| POST | `/cache/redis/flush-db/{db_index}` | Flush a specific Redis database (0-15) | Admin |
| GET | `/cache/opcache/status` | OPcache statistics (memory, hit rate, cached scripts) | Admin |
| POST | `/cache/opcache/reset` | Reset PHP OPcache (CLI + FPM context) | Admin |
| GET | `/cache/varnish/status` | Varnish cache statistics | Admin |
| POST | `/cache/varnish/purge` | Purge entire Varnish cache | Admin |
| POST | `/cache/varnish/purge-url` | Purge Varnish entries matching a URL pattern | Admin |
| GET | `/cache/memcached/stats` | Memcached statistics (connections, items, hit/miss) | Admin |
| POST | `/cache/memcached/flush` | Flush entire Memcached cache | Admin |

**Example -- Redis Info:**

```http
GET /api/v1/cache/redis/info HTTP/1.1
Authorization: Bearer <access_token>
```

```json
{
  "connected_clients": "5",
  "used_memory_human": "2.50M",
  "used_memory_peak_human": "3.10M",
  "total_commands_processed": "154832",
  "keyspace_hits": "98421",
  "keyspace_misses": "1204",
  "uptime_in_seconds": "432000",
  "redis_version": "7.0.15",
  "db_count": 2
}
```

---

### Antivirus (`/api/v1/antivirus`) -- Admin Only

ClamAV antivirus management: on-demand scanning (async via Celery), quarantine file management, ClamAV status monitoring, and virus definition database updates.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/antivirus/status` | ClamAV installation status, daemon state, and database info | Admin |
| POST | `/antivirus/scan` | Trigger full antivirus scan of /home (async via Celery) | Admin |
| POST | `/antivirus/scan/path` | Trigger antivirus scan on a specific path (async) | Admin |
| GET | `/antivirus/scans` | List recent scan results (paginated) | Admin |
| GET | `/antivirus/scans/{scan_id}` | Get scan details including quarantine entries | Admin |
| POST | `/antivirus/quarantine/{file_id}/restore` | Restore a quarantined file to original location | Admin |
| POST | `/antivirus/quarantine/{file_id}/delete` | Permanently delete a quarantined file | Admin |
| POST | `/antivirus/update` | Trigger ClamAV virus definition database update via freshclam | Admin |

**Example -- Trigger Path Scan:**

```http
POST /api/v1/antivirus/scan/path HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "path": "/home/johndoe"
}
```

```json
{
  "scan_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "celery_task_id": "abc123-task-id",
  "status": "pending",
  "path": "/home/johndoe"
}
```

---

### IP Manager (`/api/v1/ip`) -- Admin Only

Manage server IP addresses, IP blacklist (UFW deny rules), and IP whitelist (UFW allow rules).

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/ip/addresses` | List all IP addresses on network interfaces | Admin |
| POST | `/ip/addresses` | Add an IP address to a network interface | Admin |
| DELETE | `/ip/addresses/{ip}` | Remove an IP address from a network interface | Admin |
| GET | `/ip/blacklist` | List all blocked (denied) IPs from UFW/iptables | Admin |
| POST | `/ip/blacklist` | Block an IP address (UFW deny rule) | Admin |
| DELETE | `/ip/blacklist/{ip}` | Unblock an IP address (remove UFW deny rule) | Admin |
| GET | `/ip/whitelist` | List all whitelisted (allowed) IPs from UFW | Admin |
| POST | `/ip/whitelist` | Whitelist an IP address (UFW allow rule) | Admin |

**Example -- Block IP:**

```http
POST /api/v1/ip/blacklist HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "ip": "203.0.113.50",
  "comment": "Brute force attacker"
}
```

```json
{
  "status": "blocked",
  "ip": "203.0.113.50",
  "comment": "Brute force attacker",
  "detail": "IP 203.0.113.50 has been blocked."
}
```

---

### Logs (`/api/v1/logs`) -- Admin Only

Advanced log browsing, searching, rotation, and access log statistics. Extends basic log reading with paginated reading, regex search, logrotate integration, and parsed nginx access stats. Falls back to journalctl when log files are unavailable.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/logs/available` | List all known log files with size and availability | Admin |
| GET | `/logs/{name}` | Read a log file with pagination (lines, offset, order) | Admin |
| GET | `/logs/{name}/search` | Search through a log file (regex supported) | Admin |
| POST | `/logs/rotate` | Force log rotation using logrotate | Admin |
| GET | `/logs/access-stats` | Parsed nginx access log statistics (top IPs, URIs, status codes) | Admin |

**Example -- Search Logs:**

```http
GET /api/v1/logs/nginx-error/search?q=502&lines=1000&case_sensitive=false HTTP/1.1
Authorization: Bearer <access_token>
```

```json
{
  "name": "nginx-error",
  "file": "/var/log/nginx/error.log",
  "query": "502",
  "case_sensitive": false,
  "matches": ["123:2026/04/06 ... 502 Bad Gateway ..."],
  "match_count": 5,
  "searched_lines": 1000
}
```

---

### System (`/api/v1/system`) -- Admin Only

Detailed system information: OS, kernel, CPU, RAM, disks, network interfaces, SMART disk health, top processes, hostname management, and server reboot control.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/system/info` | Comprehensive system info (OS, kernel, CPU, RAM, disks, uptime) | Admin |
| GET | `/system/processes` | Top processes sorted by CPU or memory usage | Admin |
| GET | `/system/network` | Network interfaces, routes, DNS resolvers, public IP | Admin |
| GET | `/system/disk/smart` | SMART disk health information (requires smartmontools) | Admin |
| GET | `/system/hostname` | Get current system hostname and FQDN | Admin |
| PUT | `/system/hostname` | Change system hostname | Admin |
| POST | `/system/reboot` | Reboot server (requires explicit confirmation) | Admin |

**Example -- Reboot Server:**

```http
POST /api/v1/system/reboot HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "confirm": true,
  "delay_minutes": 5
}
```

```json
{
  "status": "rebooting",
  "delay_minutes": 5,
  "detail": "Server reboot initiated. System will reboot in 5 minute(s)."
}
```

---

### Translations (`/api/v1/translations`)

i18n language management with AI-powered auto-translation. Manages locale JSON files for the frontend. Includes listing, editing, import/export, missing key detection, and AI batch translation via the unified AIClient.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/translations/languages` | List all available languages with translation progress | Bearer |
| POST | `/translations/languages` | Add a new language (creates empty locale skeleton) | Admin |
| DELETE | `/translations/languages/{lang}` | Delete a language (cannot delete English) | Admin |
| GET | `/translations/{lang}` | Get all translation strings for a language | Bearer |
| PUT | `/translations/{lang}` | Update translations for a language | Admin |
| GET | `/translations/missing/{lang}` | List missing/empty keys compared to English | Bearer |
| POST | `/translations/export/{lang}` | Export language file as JSON download | Bearer |
| POST | `/translations/import` | Import a JSON translation file (multipart upload) | Admin |
| POST | `/translations/auto-translate` | AI-powered auto-translation of UI strings (rate limited: 5/min) | Admin |

**Example -- Auto-translate Missing Keys:**

```http
POST /api/v1/translations/auto-translate HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "target_lang": "de",
  "all_missing": true
}
```

```json
{
  "target_lang": "de",
  "language_name": "German",
  "translated_count": 42,
  "translations": {
    "common": {
      "save": "Speichern",
      "cancel": "Abbrechen"
    }
  },
  "saved": true
}
```

---

### Migration (`/api/v1/admin/migration`) -- Admin Only

Import server accounts from cPanel and HestiaCP backups. Supports upload (up to 10 GB), analysis, and async execution via Celery.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/admin/migration/upload` | Upload a cPanel or HestiaCP backup file (.tar.gz) | Admin |
| POST | `/admin/migration/analyze` | Extract and analyze uploaded backup contents | Admin |
| POST | `/admin/migration/execute` | Start migration asynchronously (requires prior analyze) | Admin |
| GET | `/admin/migration/status` | Poll migration progress by backup_id | Admin |

**Example -- Upload Backup:**

```http
POST /api/v1/admin/migration/upload HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

[file: backup-johndoe.tar.gz]
```

```json
{
  "backup_id": "abc123def456",
  "filename": "backup-johndoe.tar.gz",
  "size_bytes": 524288000,
  "detail": "Backup uploaded successfully. Call /analyze to inspect contents."
}
```

---

## WebSocket Endpoints

All WebSocket endpoints authenticate via a `token` query parameter containing a valid JWT access token.

| Path | Description | Auth |
|------|-------------|------|
| `/ws/terminal` | Bidirectional admin terminal | Admin (query param `token`) |
| `/ws/logs/{service}` | Live service log streaming (polls every 2s) | Admin (query param `token`) |
| `/ws/monitoring` | Real-time server stats stream (every 2s) | Admin (query param `token`) |
| `/ws/containers/{container_id}/logs` | Live Docker container log streaming | Bearer (query param `token`) |
| `/ws/apps/{domain}/logs` | Live application log streaming | None (no auth check) |

---

## Example Requests and Responses

### Login

**Request:**

```http
POST /api/v1/auth/login HTTP/1.1
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password"
}
```

**Response (200):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 1800
}
```

**Error (401):**

```json
{
  "detail": "Invalid username or password."
}
```

---

### Create Domain

**Request:**

```http
POST /api/v1/domains/ HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "domain_name": "example.com",
  "php_version": "8.2",
  "document_root": "/home/johndoe/example.com/public_html"
}
```

**Response (201):**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "f0e1d2c3-b4a5-6789-0abc-def123456789",
  "domain_name": "example.com",
  "document_root": "/home/johndoe/example.com/public_html",
  "php_version": "8.2",
  "ssl_enabled": false,
  "ssl_cert_path": null,
  "ssl_key_path": null,
  "created_at": "2026-04-02T10:30:00Z",
  "updated_at": "2026-04-02T10:30:00Z"
}
```

**Error (409):**

```json
{
  "detail": "Domain already exists."
}
```

---

### Create Database

**Request:**

```http
POST /api/v1/databases/ HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "db_name": "myapp_db",
  "db_user": "myapp_user",
  "db_password": "SecureP@ssw0rd!",
  "db_type": "mysql"
}
```

**Response (201):**

```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
  "user_id": "f0e1d2c3-b4a5-6789-0abc-def123456789",
  "db_name": "myapp_db",
  "db_user": "myapp_user",
  "db_type": "mysql",
  "created_at": "2026-04-02T10:35:00Z"
}
```

**Error (409):**

```json
{
  "detail": "Database name already exists."
}
```

---

## Error Codes

| Code | Status | Description |
|------|--------|-------------|
| 400 | Bad Request | Invalid input, validation failure, or incorrect current password |
| 401 | Unauthorized | Missing, expired, or invalid authentication credentials |
| 403 | Forbidden | Authenticated but insufficient permissions (wrong role, suspended account, path traversal) |
| 404 | Not Found | Requested resource does not exist or is not accessible to the current user |
| 409 | Conflict | Resource already exists (duplicate username, domain, database name, etc.) |
| 422 | Validation Error | Request body fails Pydantic schema validation |
| 429 | Too Many Requests | Rate limit exceeded (AI endpoints: 20/min; login: brute-force lockout) |
| 500 | Internal Server Error | Unexpected server error |
| 502 | Bad Gateway | Agent communication failure (server-side agent unreachable or returned error) |
| 503 | Service Unavailable | Feature not available (Docker not installed, AI not configured, billing integration missing) |

All error responses follow the format:

```json
{
  "detail": "Human-readable error message."
}
```

Validation errors (422) include field-level details:

```json
{
  "detail": [
    {
      "loc": ["body", "domain_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Pagination

List endpoints support pagination via query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `skip` | 0 | Number of records to skip |
| `limit` | 50 | Number of records to return (max 200) |

Paginated responses include:

```json
{
  "items": [...],
  "total": 142
}
```

Some endpoints also include `page` and `per_page` fields.

---

## Notes

- All IDs are UUIDs (v4).
- Timestamps are in ISO 8601 format with UTC timezone.
- The API uses FastAPI with async SQLAlchemy and Redis for session/rate-limit storage.
- All mutating operations are logged in the activity log (audit trail).
- File operations are sandboxed to prevent path traversal attacks.
- Sensitive configuration values (integration API keys, database passwords) are encrypted at rest using Fernet encryption derived from the application `SECRET_KEY`.
