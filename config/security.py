"""Security constants and hardening configuration for HostHive."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Service whitelist — only these may be restarted via the panel
# ---------------------------------------------------------------------------

ALLOWED_SERVICES: list[str] = [
    "nginx",
    "postgresql",
    "redis-server",
    "exim4",
    "dovecot",
    "bind9",
    "proftpd",
    "php8.2-fpm",
    "php8.3-fpm",
    "fail2ban",
    "clamav-freshclam",
    "clamav-daemon",
    "hosthive-api",
    "hosthive-agent",
    "hosthive-worker",
    "docker",
    "mariadb",
    "named",
]

# ---------------------------------------------------------------------------
# File upload restrictions
# ---------------------------------------------------------------------------

ALLOWED_FILE_EXTENSIONS: set[str] = {
    ".html", ".htm", ".css", ".js", ".json", ".xml", ".svg",
    ".txt", ".md", ".csv", ".log",
    ".php", ".py", ".rb", ".pl", ".sh",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".bmp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".webm", ".ogg",
    ".conf", ".ini", ".yaml", ".yml", ".toml",
    ".sql", ".sqlite",
    ".htaccess",
}

MAX_UPLOAD_SIZE: int = 512 * 1024 * 1024  # 512 MB

# ---------------------------------------------------------------------------
# Blocked paths — requests to these must always be rejected
# ---------------------------------------------------------------------------

BLOCKED_PATHS: list[str] = [
    "/.env",
    "/config/secrets.env",
    "/.git",
    "/.gitignore",
    "/.htpasswd",
    "/.ssh",
    "/wp-config.php",
    "/.DS_Store",
    "/docker-compose.yml",
    "/Dockerfile",
    "/.dockerignore",
    "/node_modules",
    "/__pycache__",
    "/.vscode",
    "/.idea",
]

# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

PASSWORD_MIN_LENGTH: int = 12

# ---------------------------------------------------------------------------
# Rate-limit defaults (requests per minute)
# ---------------------------------------------------------------------------

RATE_LIMIT_AUTH_LOGIN: str = "10/minute"
RATE_LIMIT_AUTH_REFRESH: str = "20/minute"
RATE_LIMIT_FILE_UPLOAD: str = "30/minute"
RATE_LIMIT_DEFAULT: str = "100/minute"
