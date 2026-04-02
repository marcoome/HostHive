"""AI-powered one-click application installer."""

from __future__ import annotations

import logging
import secrets
import string
from typing import Any

from api.core.ai_client import AIClient

logger = logging.getLogger("hosthive.ai.installer")

# Supported applications and their install configurations
APP_CONFIGS: dict[str, dict[str, Any]] = {
    "wordpress": {
        "display_name": "WordPress",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.2",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
            "setup_cron",
        ],
        "download_cmd": "wp core download --path={doc_root} --allow-root",
        "configure_cmd": (
            "wp config create --dbname={db_name} --dbuser={db_user} "
            "--dbpass={db_pass} --path={doc_root} --allow-root && "
            "wp core install --url=https://{domain} --title='{domain}' "
            "--admin_user=admin --admin_password='{admin_pass}' "
            "--admin_email=admin@{domain} --path={doc_root} --allow-root"
        ),
        "cron_cmd": "*/15 * * * * php {doc_root}/wp-cron.php > /dev/null 2>&1",
    },
    "laravel": {
        "display_name": "Laravel",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.2",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": "composer create-project laravel/laravel {doc_root} --no-interaction",
        "configure_cmd": (
            "cd {doc_root} && "
            "sed -i 's/DB_DATABASE=laravel/DB_DATABASE={db_name}/' .env && "
            "sed -i 's/DB_USERNAME=root/DB_USERNAME={db_user}/' .env && "
            "sed -i 's/DB_PASSWORD=/DB_PASSWORD={db_pass}/' .env && "
            "php artisan key:generate --force && "
            "php artisan migrate --force"
        ),
    },
    "nextjs": {
        "display_name": "Next.js",
        "db_type": None,
        "needs_php": False,
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "npx create-next-app@latest {doc_root} --use-npm --no-git --yes",
        "configure_cmd": "cd {doc_root} && npm run build",
        "service_cmd": "cd {doc_root} && npm start",
    },
    "nuxtjs": {
        "display_name": "Nuxt.js",
        "db_type": None,
        "needs_php": False,
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "npx nuxi@latest init {doc_root} --no-git --force",
        "configure_cmd": "cd {doc_root} && npm install && npm run build",
        "service_cmd": "cd {doc_root} && node .output/server/index.mjs",
    },
    "ghost": {
        "display_name": "Ghost",
        "db_type": "mysql",
        "needs_php": False,
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "mkdir -p {doc_root} && cd {doc_root} && ghost install local --no-prompt --db mysql --dbhost localhost --dbuser {db_user} --dbpass {db_pass} --dbname {db_name} --url https://{domain}",
        "configure_cmd": "cd {doc_root} && ghost setup",
    },
    "nextcloud": {
        "display_name": "Nextcloud",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.2",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
            "setup_cron",
        ],
        "download_cmd": (
            "wget -q https://download.nextcloud.com/server/releases/latest.tar.bz2 -O /tmp/nextcloud.tar.bz2 && "
            "tar -xjf /tmp/nextcloud.tar.bz2 -C $(dirname {doc_root}) && "
            "mv $(dirname {doc_root})/nextcloud {doc_root} && "
            "rm /tmp/nextcloud.tar.bz2"
        ),
        "configure_cmd": (
            "cd {doc_root} && php occ maintenance:install "
            "--database mysql --database-name {db_name} "
            "--database-user {db_user} --database-pass '{db_pass}' "
            "--admin-user admin --admin-pass '{admin_pass}'"
        ),
        "cron_cmd": "*/5 * * * * php -f {doc_root}/cron.php > /dev/null 2>&1",
    },
    "gitea": {
        "display_name": "Gitea",
        "db_type": "mysql",
        "needs_php": False,
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "mkdir -p {doc_root} && "
            "wget -q https://dl.gitea.com/gitea/latest/gitea-latest-linux-amd64 -O {doc_root}/gitea && "
            "chmod +x {doc_root}/gitea"
        ),
        "configure_cmd": "cd {doc_root} && ./gitea web --install-port 3000",
    },
    "n8n": {
        "display_name": "n8n",
        "db_type": None,
        "needs_php": False,
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "npm install -g n8n",
        "configure_cmd": "N8N_HOST={domain} N8N_PROTOCOL=https n8n start --tunnel",
    },
    "directus": {
        "display_name": "Directus",
        "db_type": "mysql",
        "needs_php": False,
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "mkdir -p {doc_root} && cd {doc_root} && npm init -y && npm install directus",
        "configure_cmd": (
            "cd {doc_root} && npx directus bootstrap --skipAdminInit && "
            "npx directus roles create --role admin --admin true"
        ),
    },
    "strapi": {
        "display_name": "Strapi",
        "db_type": "mysql",
        "needs_php": False,
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": "npx create-strapi-app@latest {doc_root} --quickstart --no-run --dbclient mysql --dbhost 127.0.0.1 --dbport 3306 --dbname {db_name} --dbusername {db_user} --dbpassword {db_pass}",
        "configure_cmd": "cd {doc_root} && npm run build",
    },
    "moodle": {
        "display_name": "Moodle",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
            "setup_cron",
        ],
        "download_cmd": (
            "git clone -b MOODLE_404_STABLE --depth 1 https://github.com/moodle/moodle.git {doc_root}"
        ),
        "configure_cmd": (
            "cd {doc_root} && php admin/cli/install.php "
            "--wwwroot=https://{domain} --dataroot=/home/{user}/moodledata "
            "--dbtype=mariadb --dbname={db_name} --dbuser={db_user} --dbpass='{db_pass}' "
            "--adminuser=admin --adminpass='{admin_pass}' --adminemail=admin@{domain} "
            "--fullname='{domain} Moodle' --shortname=Moodle --agree-license --non-interactive"
        ),
        "cron_cmd": "*/1 * * * * php {doc_root}/admin/cli/cron.php > /dev/null 2>&1",
    },
    "matomo": {
        "display_name": "Matomo",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.2",
        "install_steps": [
            "create_database",
            "download_app",
            "set_permissions",
            "setup_ssl",
            "setup_cron",
        ],
        "download_cmd": (
            "wget -q https://builds.matomo.org/matomo-latest.tar.gz -O /tmp/matomo.tar.gz && "
            "tar -xzf /tmp/matomo.tar.gz -C $(dirname {doc_root}) && "
            "mv $(dirname {doc_root})/matomo {doc_root} && "
            "rm /tmp/matomo.tar.gz"
        ),
        "cron_cmd": "*/5 * * * * php {doc_root}/console core:archive > /dev/null 2>&1",
    },
}


def _generate_password(length: int = 24) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def install_app(
    domain: str,
    app_name: str,
    agent_client: Any,
    ai_client: AIClient | None = None,
    user: str = "www-data",
) -> dict[str, Any]:
    """Install an application on the specified domain.

    Returns dict with url, credentials, and status info.
    """
    app_key = app_name.lower().replace(".", "").replace("-", "")
    if app_key not in APP_CONFIGS:
        raise ValueError(
            f"Unsupported application: {app_name}. "
            f"Supported: {', '.join(APP_CONFIGS.keys())}"
        )

    config = APP_CONFIGS[app_key]
    doc_root = f"/home/{user}/{domain}/public_html"
    db_name = f"{user}_{app_key}"[:64]
    db_user = f"{user}_{app_key}"[:32]
    db_pass = _generate_password(20)
    admin_pass = _generate_password(16)

    credentials = {"admin_user": "admin", "admin_password": admin_pass}
    template_vars = {
        "domain": domain,
        "doc_root": doc_root,
        "db_name": db_name,
        "db_user": db_user,
        "db_pass": db_pass,
        "admin_pass": admin_pass,
        "user": user,
    }

    # Execute install steps
    for step in config["install_steps"]:
        if step == "create_database" and config.get("db_type"):
            await _step_create_database(
                agent_client, db_name, db_user, db_pass, config["db_type"],
            )
            credentials["db_name"] = db_name
            credentials["db_user"] = db_user
            credentials["db_password"] = db_pass

        elif step == "download_app":
            cmd = config["download_cmd"].format(**template_vars)
            await _run_agent_command(agent_client, cmd)

        elif step == "configure_app":
            cmd = config.get("configure_cmd", "")
            if cmd:
                cmd = cmd.format(**template_vars)
                await _run_agent_command(agent_client, cmd)

        elif step == "set_permissions":
            await _step_set_permissions(agent_client, doc_root, user)

        elif step == "setup_ssl":
            try:
                await agent_client.issue_ssl(domain)
            except Exception as exc:
                logger.warning("SSL setup failed for %s: %s", domain, exc)

        elif step == "setup_cron":
            cron_cmd = config.get("cron_cmd", "")
            if cron_cmd:
                cron_cmd = cron_cmd.format(**template_vars)
                await _step_setup_cron(agent_client, user, cron_cmd)

    ssl_configured = False
    try:
        # Check if SSL was configured
        result = await agent_client._request("POST", "/exec", json_body={
            "command": f"test -f /etc/letsencrypt/live/{domain}/cert.pem && echo yes || echo no",
        })
        ssl_configured = result.get("stdout", "").strip() == "yes"
    except Exception:
        pass

    cron_configured = "setup_cron" in config["install_steps"]

    return {
        "domain": domain,
        "app_name": config["display_name"],
        "url": f"https://{domain}" if ssl_configured else f"http://{domain}",
        "credentials": credentials,
        "ssl_configured": ssl_configured,
        "cron_configured": cron_configured,
    }


async def _step_create_database(
    agent: Any,
    db_name: str,
    db_user: str,
    db_pass: str,
    db_type: str,
) -> None:
    """Create database and user via agent."""
    await agent.create_database(db_name, db_user, db_pass, db_type)
    logger.info("Created database %s for app install", db_name)


async def _step_set_permissions(agent: Any, doc_root: str, user: str) -> None:
    """Set correct file ownership and permissions."""
    await _run_agent_command(agent, f"chown -R {user}:{user} {doc_root}")
    await _run_agent_command(agent, f"find {doc_root} -type d -exec chmod 755 {{}} \\;")
    await _run_agent_command(agent, f"find {doc_root} -type f -exec chmod 644 {{}} \\;")


async def _step_setup_cron(agent: Any, user: str, cron_cmd: str) -> None:
    """Add a cron job for the application."""
    try:
        await agent.set_crontab(user, [{"expression": cron_cmd}])
        logger.info("Cron job added for %s", user)
    except Exception as exc:
        logger.warning("Failed to setup cron: %s", exc)


async def _run_agent_command(agent: Any, command: str) -> dict[str, Any]:
    """Run a shell command via the agent."""
    result = await agent._request("POST", "/exec", json_body={"command": command})
    exit_code = result.get("exit_code", -1)
    if exit_code != 0:
        stderr = result.get("stderr", "unknown error")
        logger.error("Command failed (exit %d): %s\nStderr: %s", exit_code, command, stderr)
        raise RuntimeError(f"Install command failed: {stderr}")
    return result
