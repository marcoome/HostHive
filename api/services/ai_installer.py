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
    # ------------------------------------------------------------------
    # E-Commerce
    # ------------------------------------------------------------------
    "prestashop": {
        "display_name": "PrestaShop",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "wget -q https://github.com/PrestaShop/PrestaShop/releases/download/8.2.0/prestashop_8.2.0.zip "
            "-O /tmp/prestashop.zip && "
            "mkdir -p {doc_root} && "
            "unzip -q /tmp/prestashop.zip -d {doc_root} && "
            "rm /tmp/prestashop.zip"
        ),
        "configure_cmd": (
            "cd {doc_root} && php install-dev/index_cli.php "
            "--domain={domain} --db_server=127.0.0.1 --db_name={db_name} "
            "--db_user={db_user} --db_password='{db_pass}' "
            "--email=admin@{domain} --password='{admin_pass}' "
            "--name='{domain} Store' --language=en --country=US && "
            "rm -rf {doc_root}/install-dev"
        ),
    },
    "magento": {
        "display_name": "Magento / OpenMage",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "composer create-project openmage/magento-lts {doc_root} --no-interaction --no-dev"
        ),
        "configure_cmd": (
            "cd {doc_root} && php install.php -- "
            "--license_agreement_accepted yes "
            "--locale en_US --timezone America/New_York --default_currency USD "
            "--db_host 127.0.0.1 --db_name {db_name} --db_user {db_user} "
            "--db_pass '{db_pass}' "
            "--url https://{domain}/ --use_rewrites yes "
            "--use_secure yes --secure_base_url https://{domain}/ "
            "--admin_firstname Admin --admin_lastname User "
            "--admin_email admin@{domain} "
            "--admin_username admin --admin_password '{admin_pass}'"
        ),
    },
    # ------------------------------------------------------------------
    # CMS
    # ------------------------------------------------------------------
    "drupal": {
        "display_name": "Drupal",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.3",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "composer create-project drupal/recommended-project {doc_root} --no-interaction"
        ),
        "configure_cmd": (
            "cd {doc_root} && php vendor/bin/drush site:install standard "
            "--db-url=mysql://{db_user}:'{db_pass}'@127.0.0.1/{db_name} "
            "--site-name='{domain}' "
            "--account-name=admin --account-pass='{admin_pass}' "
            "--account-mail=admin@{domain} -y"
        ),
    },
    "joomla": {
        "display_name": "Joomla",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "wget -q https://downloads.joomla.org/cms/joomla5/5-2-0/Joomla_5-2-0-Stable-Full_Package.zip "
            "-O /tmp/joomla.zip && "
            "mkdir -p {doc_root} && "
            "unzip -q /tmp/joomla.zip -d {doc_root} && "
            "rm /tmp/joomla.zip"
        ),
        "configure_cmd": (
            "cd {doc_root} && php installation/joomla.php install "
            "--site-name='{domain}' "
            "--admin-user=admin --admin-username=admin "
            "--admin-password='{admin_pass}' --admin-email=admin@{domain} "
            "--db-type=mysql --db-host=127.0.0.1 "
            "--db-name={db_name} --db-user={db_user} --db-pass='{db_pass}' "
            "--db-prefix=jml_ --db-encryption=0 && "
            "rm -rf {doc_root}/installation"
        ),
    },
    # ------------------------------------------------------------------
    # Wiki / Documentation
    # ------------------------------------------------------------------
    "mediawiki": {
        "display_name": "MediaWiki",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "wget -q https://releases.wikimedia.org/mediawiki/1.42/mediawiki-1.42.3.tar.gz "
            "-O /tmp/mediawiki.tar.gz && "
            "mkdir -p $(dirname {doc_root}) && "
            "tar -xzf /tmp/mediawiki.tar.gz -C $(dirname {doc_root}) && "
            "mv $(dirname {doc_root})/mediawiki-* {doc_root} && "
            "rm /tmp/mediawiki.tar.gz"
        ),
        "configure_cmd": (
            "cd {doc_root} && php maintenance/install.php "
            "--dbtype=mysql --dbserver=127.0.0.1 "
            "--dbname={db_name} --dbuser={db_user} --dbpass='{db_pass}' "
            "--server=https://{domain} --scriptpath= "
            "--lang=en --pass='{admin_pass}' "
            "'{domain} Wiki' 'admin'"
        ),
    },
    "bookstack": {
        "display_name": "BookStack",
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
        "download_cmd": (
            "composer create-project bookstackapp/bookstack {doc_root} --no-interaction --no-dev"
        ),
        "configure_cmd": (
            "cd {doc_root} && cp .env.example .env && "
            "sed -i 's|APP_URL=.*|APP_URL=https://{domain}|' .env && "
            "sed -i 's|DB_DATABASE=.*|DB_DATABASE={db_name}|' .env && "
            "sed -i 's|DB_USERNAME=.*|DB_USERNAME={db_user}|' .env && "
            "sed -i 's|DB_PASSWORD=.*|DB_PASSWORD={db_pass}|' .env && "
            "php artisan key:generate --force && "
            "php artisan migrate --force"
        ),
    },
    # ------------------------------------------------------------------
    # Forum
    # ------------------------------------------------------------------
    "phpbb": {
        "display_name": "phpBB",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "wget -q https://download.phpbb.com/pub/release/3.3/3.3.12/phpBB-3.3.12.tar.bz2 "
            "-O /tmp/phpbb.tar.bz2 && "
            "mkdir -p $(dirname {doc_root}) && "
            "tar -xjf /tmp/phpbb.tar.bz2 -C $(dirname {doc_root}) && "
            "mv $(dirname {doc_root})/phpBB3 {doc_root} && "
            "rm /tmp/phpbb.tar.bz2"
        ),
        "configure_cmd": (
            "cd {doc_root} && php install/phpbbcli.php install "
            "{doc_root}/install/install-config.yml "
            "--db-driver=mysqli --db-host=127.0.0.1 "
            "--db-name={db_name} --db-user={db_user} --db-passwd='{db_pass}' "
            "--db-port=3306 --table-prefix=phpbb_ "
            "--admin-name=admin --admin-pass1='{admin_pass}' "
            "--admin-email=admin@{domain} "
            "--server-name={domain} --server-protocol=https:// --server-port=443 && "
            "rm -rf {doc_root}/install"
        ),
    },
    "discourse": {
        "display_name": "Discourse",
        "db_type": None,
        "needs_php": False,
        "runtime": "docker",
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "mkdir -p {doc_root} && cd {doc_root} && "
            "git clone --depth 1 https://github.com/discourse/discourse_docker.git . && "
            "cp samples/standalone.yml containers/app.yml"
        ),
        "configure_cmd": (
            "cd {doc_root} && "
            "sed -i 's|DISCOURSE_HOSTNAME:.*|DISCOURSE_HOSTNAME: \"{domain}\"|' containers/app.yml && "
            "sed -i 's|DISCOURSE_DEVELOPER_EMAILS:.*|DISCOURSE_DEVELOPER_EMAILS: \"admin@{domain}\"|' containers/app.yml && "
            "sed -i 's|DISCOURSE_SMTP_ADDRESS:.*|DISCOURSE_SMTP_ADDRESS: \"localhost\"|' containers/app.yml && "
            "./launcher bootstrap app && "
            "./launcher start app"
        ),
    },
    # ------------------------------------------------------------------
    # Billing / Invoicing
    # ------------------------------------------------------------------
    "invoiceninja": {
        "display_name": "Invoice Ninja",
        "db_type": "mysql",
        "needs_php": False,
        "runtime": "docker",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "mkdir -p {doc_root} && cd {doc_root} && "
            "cat > docker-compose.yml << 'COMPOSE_EOF'\n"
            "version: '3.8'\n"
            "services:\n"
            "  invoiceninja:\n"
            "    image: invoiceninja/invoiceninja:latest\n"
            "    restart: always\n"
            "    ports:\n"
            "      - '127.0.0.1:9080:80'\n"
            "    environment:\n"
            "      - APP_URL=https://{domain}\n"
            "      - DB_HOST=host.docker.internal\n"
            "      - DB_DATABASE={db_name}\n"
            "      - DB_USERNAME={db_user}\n"
            "      - DB_PASSWORD={db_pass}\n"
            "      - IN_USER_EMAIL=admin@{domain}\n"
            "      - IN_PASSWORD={admin_pass}\n"
            "    volumes:\n"
            "      - ninja-public:/var/www/app/public\n"
            "      - ninja-storage:/var/www/app/storage\n"
            "volumes:\n"
            "  ninja-public:\n"
            "  ninja-storage:\n"
            "COMPOSE_EOF"
        ),
        "configure_cmd": (
            "cd {doc_root} && docker compose up -d && "
            "sleep 10 && "
            "docker compose exec invoiceninja php artisan key:generate --force && "
            "docker compose exec invoiceninja php artisan migrate --force"
        ),
        "service_port": 9080,
    },
    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    "uptimekuma": {
        "display_name": "Uptime Kuma",
        "db_type": None,
        "needs_php": False,
        "runtime": "docker",
        "install_steps": [
            "download_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "docker run -d --name uptime-kuma-{domain} "
            "--restart=always "
            "-p 127.0.0.1:3001:3001 "
            "-v uptime-kuma-{domain}:/app/data "
            "louislam/uptime-kuma:latest"
        ),
        "service_port": 3001,
    },
    "grafana": {
        "display_name": "Grafana",
        "db_type": None,
        "needs_php": False,
        "runtime": "docker",
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "docker run -d --name grafana-{domain} "
            "--restart=always "
            "-p 127.0.0.1:3100:3000 "
            "-e GF_SECURITY_ADMIN_PASSWORD='{admin_pass}' "
            "-e GF_SERVER_ROOT_URL=https://{domain} "
            "-v grafana-{domain}:/var/lib/grafana "
            "grafana/grafana-oss:latest"
        ),
        "configure_cmd": "",
        "service_port": 3100,
    },
    # ------------------------------------------------------------------
    # DevOps / Infrastructure
    # ------------------------------------------------------------------
    "portainer": {
        "display_name": "Portainer",
        "db_type": None,
        "needs_php": False,
        "runtime": "docker",
        "install_steps": [
            "download_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "docker volume create portainer_data && "
            "docker run -d --name portainer-{domain} "
            "--restart=always "
            "-p 127.0.0.1:9443:9443 "
            "-v /var/run/docker.sock:/var/run/docker.sock "
            "-v portainer_data:/data "
            "portainer/portainer-ce:latest"
        ),
        "service_port": 9443,
    },
    "minio": {
        "display_name": "MinIO",
        "db_type": None,
        "needs_php": False,
        "runtime": "binary",
        "install_steps": [
            "download_app",
            "configure_app",
            "setup_ssl",
        ],
        "download_cmd": (
            "mkdir -p {doc_root} /data/minio && "
            "wget -q https://dl.min.io/server/minio/release/linux-amd64/minio "
            "-O {doc_root}/minio && "
            "chmod +x {doc_root}/minio"
        ),
        "configure_cmd": (
            "cat > /etc/systemd/system/minio-{user}.service << 'SVCEOF'\n"
            "[Unit]\n"
            "Description=MinIO Object Storage\n"
            "After=network-online.target\n"
            "[Service]\n"
            "Type=simple\n"
            "User={user}\n"
            "Environment=MINIO_ROOT_USER=admin\n"
            "Environment=MINIO_ROOT_PASSWORD={admin_pass}\n"
            "Environment=MINIO_BROWSER_REDIRECT_URL=https://{domain}\n"
            "ExecStart={doc_root}/minio server /data/minio --console-address :9001 --address :9000\n"
            "Restart=always\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "SVCEOF\n"
            "systemctl daemon-reload && systemctl enable --now minio-{user}.service"
        ),
        "service_port": 9001,
    },
    # ------------------------------------------------------------------
    # Database Tools
    # ------------------------------------------------------------------
    "adminer": {
        "display_name": "Adminer",
        "db_type": None,
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "download_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "mkdir -p {doc_root} && "
            "wget -q https://github.com/vrana/adminer/releases/download/v4.8.4/adminer-4.8.4.php "
            "-O {doc_root}/index.php"
        ),
    },
    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    "roundcube": {
        "display_name": "Roundcube",
        "db_type": "mysql",
        "needs_php": True,
        "php_version": "8.1",
        "install_steps": [
            "create_database",
            "download_app",
            "configure_app",
            "set_permissions",
            "setup_ssl",
        ],
        "download_cmd": (
            "composer create-project roundcube/roundcubemail {doc_root} --no-interaction --no-dev"
        ),
        "configure_cmd": (
            "cd {doc_root} && cp config/config.inc.php.sample config/config.inc.php && "
            "sed -i \"s|\\$config\\['db_dsnw'\\].*|\\$config['db_dsnw'] = "
            "'mysql://{db_user}:{db_pass}@127.0.0.1/{db_name}';|\" config/config.inc.php && "
            "sed -i \"s|\\$config\\['imap_host'\\].*|\\$config['imap_host'] = "
            "'localhost:143';|\" config/config.inc.php && "
            "sed -i \"s|\\$config\\['smtp_host'\\].*|\\$config['smtp_host'] = "
            "'localhost:587';|\" config/config.inc.php && "
            "php bin/initdb.sh --dir=SQL/mysql || true && "
            "rm -rf {doc_root}/installer"
        ),
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
    email: str | None = None,
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
                await agent_client.issue_ssl(domain, email or f"admin@{domain}")
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
