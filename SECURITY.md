# HostHive Security Architecture

This document describes the security architecture, mechanisms, and policies of HostHive.

---

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Authorization](#authorization)
- [Encryption](#encryption)
- [Input Validation](#input-validation)
- [Path Traversal Prevention](#path-traversal-prevention)
- [Command Injection Prevention](#command-injection-prevention)
- [CSRF Protection](#csrf-protection)
- [Rate Limiting](#rate-limiting)
- [Web Application Firewall (WAF)](#web-application-firewall-waf)
- [Fail2ban Integration](#fail2ban-integration)
- [Audit Logging](#audit-logging)
- [Docker Isolation](#docker-isolation)
- [Agent Authentication](#agent-authentication)
- [Security Headers](#security-headers)
- [Responsible Disclosure](#responsible-disclosure)

---

## Overview

HostHive follows a defense-in-depth security model with multiple layers of protection:

1. **Perimeter** — Firewall, fail2ban, rate limiting, WAF
2. **Transport** — TLS everywhere, HSTS, secure headers
3. **Authentication** — JWT with refresh tokens, bcrypt password hashing
4. **Authorization** — Role-based access control (admin, reseller, user)
5. **Application** — Input validation, CSRF tokens, path traversal prevention
6. **Data** — Fernet encryption for secrets, parameterized queries
7. **Isolation** — Per-user Docker containers with resource limits
8. **Audit** — Full audit log of all administrative actions

---

## Authentication

HostHive uses JWT (JSON Web Tokens) with short-lived access tokens and long-lived refresh tokens.

### Token Flow

1. User submits username + password
2. Server verifies password against bcrypt hash
3. Server issues:
   - **Access token** — expires in 15 minutes, used for API calls
   - **Refresh token** — expires in 7 days, stored as HttpOnly cookie
4. When the access token expires, the client uses the refresh token to obtain a new pair
5. On logout, the refresh token is revoked server-side

### Token Details

| Property | Access Token | Refresh Token |
|---|---|---|
| Lifetime | 15 minutes | 7 days |
| Storage | Memory / Authorization header | HttpOnly secure cookie |
| Revocable | No (short-lived) | Yes (stored in DB) |
| Contains | user_id, role, permissions | user_id, token_family |

### Password Policy

- Minimum 8 characters
- Hashed with **bcrypt** (cost factor 12)
- Passwords are never logged or stored in plaintext
- Failed login attempts are tracked and rate-limited

---

## Authorization

HostHive implements role-based access control (RBAC) with three roles:

| Role | Description | Permissions |
|---|---|---|
| **admin** | Full system access | All operations, server settings, user management |
| **reseller** | Manages own users | Create/manage users within allocated resources |
| **user** | Standard hosting user | Manage own domains, databases, email, files |

### Permission Enforcement

- Every API endpoint declares its required role
- Middleware checks the JWT role claim before handler execution
- Users can only access their own resources (enforced at query level)
- Resellers can only manage users they created
- Admin can impersonate any user for debugging

---

## Encryption

### Passwords

- User passwords: **bcrypt** with cost factor 12
- No reversible encryption for user passwords

### Stored Secrets

- Database passwords, API keys, and integration tokens are encrypted at rest using **Fernet** (symmetric encryption from the `cryptography` library)
- Fernet key is generated during installation and stored in `/opt/hosthive/data/.fernet_key` (mode 0600, owned by root)
- Fernet provides AES-128-CBC encryption with HMAC-SHA256 authentication

### Transport

- All panel traffic served over HTTPS (TLS 1.2+)
- HSTS header enabled
- Internal agent communication uses HMAC-signed requests

---

## Input Validation

All user input is validated before processing. The following validators are applied:

| Validator | Purpose | Rules |
|---|---|---|
| `validate_domain` | Domain names | RFC 1035 compliant, max 253 chars, valid TLD |
| `validate_username` | System usernames | Alphanumeric + underscore, 3-32 chars, no reserved names |
| `validate_email` | Email addresses | RFC 5322 format validation |
| `validate_password` | Password strength | Minimum 8 chars |
| `validate_database_name` | DB names | Alphanumeric + underscore, 1-64 chars |
| `validate_path` | File paths | No null bytes, no `..`, must be within user home |
| `validate_cron` | Cron expressions | Valid cron syntax (5 fields) |
| `validate_dns_record` | DNS records | Valid record type, name, and value |
| `validate_port` | Port numbers | Integer 1-65535 |
| `validate_ip` | IP addresses | Valid IPv4 or IPv6 |
| `validate_php_version` | PHP version | Must be in allowed list |
| `validate_webserver` | Webserver type | Must be in allowed list |

All database queries use **parameterized statements** (SQLAlchemy ORM) — no string concatenation for SQL.

---

## Path Traversal Prevention

HostHive prevents path traversal attacks through multiple layers:

1. **Input validation** — Paths are validated to reject `..`, null bytes, and absolute paths
2. **Canonical path resolution** — `os.path.realpath()` resolves symlinks and relative components
3. **Jail check** — The resolved path must start with the user's home directory (`/home/<username>/`)
4. **File manager API** — All file operations are jailed to the user's document root
5. **Docker isolation** — Even if traversal occurred, the user is confined to their container

```
User Input: ../../../../etc/passwd
Resolved:   /etc/passwd
Jail:       /home/user1/
Result:     BLOCKED — path is outside jail
```

---

## Command Injection Prevention

HostHive never uses `shell=True` in subprocess calls. All system commands are executed with:

- `subprocess.run()` with argument lists (not strings)
- No shell interpolation of user input
- Allowlists for command arguments where applicable
- Docker exec for user-context commands (isolated from host)

Example of safe execution:

```python
# CORRECT — argument list, no shell
subprocess.run(["nginx", "-t", "-c", config_path], check=True)

# NEVER USED — shell=True with user input
# subprocess.run(f"nginx -t -c {config_path}", shell=True)
```

---

## CSRF Protection

All state-changing operations (POST, PUT, DELETE) require a valid CSRF token.

- CSRF tokens are generated per session and embedded in HTML forms as hidden fields
- API requests using JWT Bearer tokens in the `Authorization` header are exempt (token-based auth is not vulnerable to CSRF)
- The `SameSite=Strict` attribute is set on session cookies

---

## Rate Limiting

HostHive applies rate limiting at multiple levels:

| Endpoint | Limit | Window |
|---|---|---|
| Login (`/api/v1/auth/login`) | 5 requests | 1 minute |
| API (authenticated) | 100 requests | 1 minute |
| API (unauthenticated) | 20 requests | 1 minute |
| File upload | 10 requests | 1 minute |
| Password reset | 3 requests | 15 minutes |

Rate limiting is enforced per IP address using an in-memory sliding window counter. When the limit is exceeded, the server responds with `429 Too Many Requests` and a `Retry-After` header.

---

## Web Application Firewall (WAF)

HostHive includes a built-in WAF that inspects incoming HTTP requests:

### Rules

- **SQL Injection** — Blocks common SQLi patterns in query strings and POST bodies
- **XSS** — Blocks script injection attempts
- **Path Traversal** — Blocks `../` sequences in URLs
- **Scanner Detection** — Blocks known vulnerability scanner user agents
- **Bad Bots** — Blocks known malicious bot signatures
- **File Inclusion** — Blocks remote/local file inclusion attempts
- **Protocol Enforcement** — Rejects malformed HTTP requests

### Configuration

WAF rules can be managed through the panel:

1. Go to **Admin** > **Security** > **WAF**
2. Enable/disable individual rule categories
3. Add custom rules or whitelist IPs
4. View blocked request log

---

## Fail2ban Integration

HostHive integrates with fail2ban to block brute-force attacks:

### Jails

| Jail | Log Source | Max Retries | Ban Time |
|---|---|---|---|
| `hosthive-auth` | Panel auth log | 5 | 10 minutes |
| `hosthive-api` | API access log | 20 | 5 minutes |
| `sshd` | SSH auth log | 5 | 10 minutes |
| `exim4` | Mail log | 10 | 10 minutes |
| `dovecot` | Mail log | 5 | 10 minutes |

### Management

```bash
# View banned IPs
fail2ban-client status hosthive-auth

# Unban an IP
fail2ban-client set hosthive-auth unbanip 1.2.3.4
```

Fail2ban status is also visible in the panel under **Admin** > **Security** > **Fail2ban**.

---

## Audit Logging

Every administrative action is recorded in the audit log with:

| Field | Description |
|---|---|
| `timestamp` | ISO 8601 timestamp |
| `user_id` | ID of the user who performed the action |
| `username` | Username |
| `role` | Role at the time of action |
| `action` | Action identifier (e.g., `domain.create`) |
| `resource` | Affected resource (e.g., `example.com`) |
| `ip_address` | Client IP address |
| `user_agent` | Client user agent |
| `details` | JSON with action-specific details |
| `status` | `success` or `failure` |

### Logged Actions

- User login/logout
- User creation/modification/deletion
- Domain creation/modification/deletion
- Database operations
- Email account changes
- DNS record changes
- SSL certificate operations
- Backup creation/restoration
- Settings changes
- Security events (WAF blocks, failed logins)

### Viewing Audit Logs

- **Panel**: Admin > Audit Log (with search and filters)
- **API**: `GET /api/v1/audit`
- **CLI**: `hosthive audit list`

Audit logs are retained for 90 days by default (configurable).

---

## Docker Isolation

Each hosting user runs inside an isolated Docker container:

### Isolation Boundaries

- **Filesystem** — Each user has their own filesystem; no access to other users or the host
- **Processes** — Users can only see their own processes
- **Network** — User containers are on isolated Docker networks
- **Resources** — CPU, RAM, and IO limits enforced via Docker cgroups
- **Capabilities** — Containers run with minimal Linux capabilities (no `SYS_ADMIN`, `NET_RAW`, etc.)

### Resource Limits

Resource limits are defined by the user's hosting package:

```
CPU:    1 core (soft), 2 cores (hard)
RAM:    512 MB (soft), 1 GB (hard)
Disk:   10 GB (quota)
IO:     50 MB/s read, 25 MB/s write
PIDs:   256 max
```

---

## Agent Authentication

HostHive uses a host-to-container agent for executing commands inside user Docker environments. Communication between the panel and agents is authenticated using HMAC-SHA256:

1. Each request includes a timestamp and nonce
2. The payload is signed with a shared secret using HMAC-SHA256
3. The agent verifies the signature and checks timestamp freshness (5-minute window)
4. Replay attacks are prevented by the nonce check

```
Signature = HMAC-SHA256(secret, timestamp + nonce + body)
```

The shared secret is generated during installation and stored securely on the host (mode 0600).

---

## Security Headers

HostHive sets the following security headers on all responses:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

---

## Responsible Disclosure

If you discover a security vulnerability in HostHive, please report it responsibly:

1. **Email**: security@hosthive.io
2. **Subject**: `[SECURITY] Brief description`
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Policy

- We will acknowledge receipt within 48 hours
- We will investigate and provide an update within 7 days
- We will credit you in the security advisory (unless you prefer anonymity)
- Please do not publicly disclose until we have released a fix
- Do not access or modify other users' data
- Do not perform denial-of-service attacks

We do not currently offer a bug bounty program, but we deeply appreciate responsible disclosures.
