# HostHive Integrations

This guide covers all available third-party integrations, how to configure them, and troubleshooting tips.

---

## Table of Contents

- [Cloudflare](#cloudflare)
- [S3 / B2 / Wasabi](#s3--b2--wasabi)
- [Telegram](#telegram)
- [Slack](#slack)
- [Discord](#discord)
- [WHMCS](#whmcs)
- [Stripe](#stripe)
- [Grafana](#grafana)
- [WireGuard](#wireguard)

---

## Cloudflare

### What It Does

Syncs DNS records between HostHive and Cloudflare. When you add a domain or modify DNS records in HostHive, changes are automatically pushed to Cloudflare. You can also toggle Cloudflare proxy (orange cloud) per record.

### Configuration

1. Log in to your [Cloudflare dashboard](https://dash.cloudflare.com)
2. Go to **My Profile** > **API Tokens**
3. Create a token with the following permissions:
   - **Zone** > **DNS** > **Edit**
   - **Zone** > **Zone** > **Read**
4. Copy the API token
5. In HostHive, go to **Admin** > **Integrations** > **Cloudflare**
6. Paste the API token and click **Save**
7. Click **Sync Zones** to import existing zones

### Required Credentials

| Field | Description |
|---|---|
| API Token | Cloudflare API token (recommended over Global API Key) |

### Available Features

- Automatic DNS record sync (create, update, delete)
- Proxy toggle (orange/grey cloud) per record
- Zone import from Cloudflare
- Bulk enable/disable proxy
- Development mode toggle
- Cache purge

### Troubleshooting

- **Records not syncing** — Verify the API token has DNS Edit permissions for the correct zones. Check the audit log for error details.
- **"Authentication error"** — The API token may have expired or been revoked. Generate a new one.
- **Zone not found** — The domain must exist in your Cloudflare account. Add it there first, then sync.

---

## S3 / B2 / Wasabi

### What It Does

Enables remote backup storage. Backups can be automatically uploaded to Amazon S3, Backblaze B2, or Wasabi cloud storage. Supports scheduled and on-demand backups.

### Configuration

#### Amazon S3

1. Create an S3 bucket in your AWS account
2. Create an IAM user with `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` permissions
3. Generate access keys for the IAM user
4. In HostHive, go to **Admin** > **Integrations** > **Backup Storage**
5. Select **Amazon S3** as the provider
6. Enter the credentials and bucket details
7. Click **Test Connection**, then **Save**

#### Backblaze B2

1. Create a B2 bucket in your Backblaze account
2. Create an Application Key with read/write access to the bucket
3. In HostHive, select **Backblaze B2** as the provider
4. Enter the Application Key ID, Application Key, and Bucket Name
5. Click **Test Connection**, then **Save**

#### Wasabi

1. Create a bucket in your Wasabi account
2. Create an access key
3. In HostHive, select **Wasabi** as the provider
4. Enter credentials and bucket details
5. Set the region endpoint (e.g., `s3.us-east-1.wasabisys.com`)
6. Click **Test Connection**, then **Save**

### Required Credentials

| Provider | Fields |
|---|---|
| Amazon S3 | Access Key ID, Secret Access Key, Bucket Name, Region |
| Backblaze B2 | Application Key ID, Application Key, Bucket Name |
| Wasabi | Access Key ID, Secret Access Key, Bucket Name, Region Endpoint |

### Available Features

- Scheduled backup uploads (daily, weekly, monthly)
- On-demand backup upload
- Backup retention policy (auto-delete old backups)
- Restore from remote backup
- Encryption at rest (backups are encrypted before upload)
- Bandwidth throttling

### Troubleshooting

- **"Access Denied"** — Verify the IAM/application key has the correct bucket permissions.
- **"Bucket not found"** — Check the bucket name and region. Bucket names are globally unique for S3.
- **Slow uploads** — Consider using a storage region closer to your server. Check bandwidth throttle settings.
- **Connection timeout** — Verify outbound port 443 is open. Check DNS resolution.

---

## Telegram

### What It Does

Sends panel notifications to a Telegram chat or group. Alerts include server events, security warnings, backup status, and monitoring alerts.

### Configuration

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the **Bot Token** provided by BotFather
4. Start a chat with your new bot (send `/start`)
5. Get your **Chat ID**:
   - Send a message to the bot
   - Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find your `chat.id` in the response
6. In HostHive, go to **Admin** > **Integrations** > **Telegram**
7. Enter the Bot Token and Chat ID
8. Click **Test** to send a test message, then **Save**

### Required Credentials

| Field | Description |
|---|---|
| Bot Token | Token from BotFather (e.g., `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`) |
| Chat ID | Numeric chat ID (e.g., `123456789` or `-1001234567890` for groups) |

### Available Features

- Server status notifications (up/down)
- Backup completion/failure alerts
- Security alerts (failed logins, WAF blocks, fail2ban bans)
- Disk space warnings
- SSL certificate expiry warnings
- User creation notifications
- Custom notification rules

### Troubleshooting

- **No messages received** — Ensure you started a chat with the bot first. Verify the Chat ID is correct.
- **"Unauthorized"** — The bot token is invalid. Regenerate it with BotFather.
- **Group messages not working** — Add the bot to the group and use the group Chat ID (starts with `-100`).

---

## Slack

### What It Does

Sends panel notifications to a Slack channel using an incoming webhook. Same notification categories as Telegram.

### Configuration

1. Go to [Slack API](https://api.slack.com/apps) and create a new app
2. Under **Incoming Webhooks**, activate and create a new webhook
3. Select the channel to post to
4. Copy the **Webhook URL**
5. In HostHive, go to **Admin** > **Integrations** > **Slack**
6. Paste the Webhook URL
7. Click **Test** to send a test message, then **Save**

### Required Credentials

| Field | Description |
|---|---|
| Webhook URL | Slack incoming webhook URL (e.g., `https://hooks.slack.com/services/T.../B.../xxx`) |

### Available Features

- All notification types (same as Telegram)
- Rich message formatting with attachments
- Channel selection per notification type
- Notification filtering (choose which events to send)

### Troubleshooting

- **"channel_not_found"** — The webhook may have been deleted or the channel archived. Create a new webhook.
- **"invalid_payload"** — Check HostHive logs for the exact payload being sent.
- **Messages delayed** — Slack webhooks are rate-limited. HostHive queues messages to respect limits.

---

## Discord

### What It Does

Sends panel notifications to a Discord channel using a webhook. Same notification categories as Telegram and Slack.

### Configuration

1. In Discord, go to **Server Settings** > **Integrations** > **Webhooks**
2. Click **New Webhook**
3. Select the target channel and customize the name/avatar
4. Click **Copy Webhook URL**
5. In HostHive, go to **Admin** > **Integrations** > **Discord**
6. Paste the Webhook URL
7. Click **Test** to send a test message, then **Save**

### Required Credentials

| Field | Description |
|---|---|
| Webhook URL | Discord webhook URL (e.g., `https://discord.com/api/webhooks/123/abc`) |

### Available Features

- All notification types (same as Telegram)
- Rich embed formatting with colors
- Custom bot name and avatar per webhook
- Notification filtering

### Troubleshooting

- **"Unknown Webhook"** — The webhook was deleted. Create a new one in Discord.
- **Rate limited** — Discord limits webhooks to 30 requests per minute. HostHive queues excess messages.
- **Embeds not showing** — Ensure the webhook has permission to post embeds in the channel.

---

## WHMCS

### What It Does

Integrates HostHive with WHMCS (or FossBilling) for automated provisioning. When a customer purchases a hosting plan through WHMCS, HostHive automatically creates the user account with the correct package.

### Configuration

1. Download the HostHive WHMCS module from the panel (**Admin** > **Integrations** > **WHMCS** > **Download Module**)
2. Upload the module to your WHMCS installation:
   ```
   /path/to/whmcs/modules/servers/hosthive/
   ```
3. In WHMCS, go to **Setup** > **Servers** > **Add New Server**
4. Enter your HostHive panel details:
   - Hostname: `panel.example.com`
   - Port: `8083`
   - Username: `admin`
   - API Key: (generate in HostHive under Admin > API Keys)
5. Create a **Server Group** with the HostHive server
6. Create **Products** linked to HostHive packages

### Required Credentials

| Field | Description |
|---|---|
| Panel URL | HostHive panel URL (e.g., `https://panel.example.com:8083`) |
| Admin Username | Admin username |
| API Key | API key generated in HostHive |

### Available Features

- Automatic account creation on order
- Automatic suspension/unsuspension
- Automatic termination
- Package upgrades/downgrades
- Single sign-on from WHMCS to HostHive
- Usage statistics sync
- Custom field mapping

### Troubleshooting

- **"Connection refused"** — Verify the panel URL and port are correct and accessible from the WHMCS server.
- **"Authentication failed"** — Check the API key is valid and has admin permissions.
- **Account not created** — Check the WHMCS module debug log and HostHive audit log.
- **FossBilling** — Use the same module; FossBilling is compatible with WHMCS server modules.

---

## Stripe

### What It Does

Enables built-in billing for hosting services. Users can be billed directly through HostHive with Stripe handling payment processing. Supports one-time and recurring payments.

### Configuration

1. Create a [Stripe account](https://dashboard.stripe.com/register) (or log in)
2. Go to **Developers** > **API Keys**
3. Copy the **Secret Key** (starts with `sk_live_` or `sk_test_`)
4. Copy the **Publishable Key** (starts with `pk_live_` or `pk_test_`)
5. Set up a **Webhook Endpoint**:
   - URL: `https://panel.example.com:8083/api/v1/billing/webhook`
   - Events: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `customer.subscription.updated`
   - Copy the **Webhook Signing Secret** (starts with `whsec_`)
6. In HostHive, go to **Admin** > **Integrations** > **Stripe**
7. Enter all three keys and click **Save**

### Required Credentials

| Field | Description |
|---|---|
| Secret Key | Stripe secret API key |
| Publishable Key | Stripe publishable key (for frontend) |
| Webhook Secret | Stripe webhook signing secret |

### Available Features

- Recurring subscriptions tied to hosting packages
- Automatic invoice generation
- Payment history for users
- Dunning management (retry failed payments)
- Proration on package changes
- Credit card and other payment methods
- Tax configuration
- Coupon/discount support

### Troubleshooting

- **Webhook not receiving events** — Verify the webhook URL is publicly accessible. Check Stripe's webhook logs for delivery attempts.
- **"Invalid API key"** — Ensure you are using live keys for production (not test keys).
- **Subscription not activating** — Check that the webhook events are configured correctly and the signing secret matches.
- **Currency mismatch** — Set the default currency in HostHive billing settings to match your Stripe account.

---

## Grafana

### What It Does

HostHive exposes a Prometheus-compatible metrics endpoint that Grafana can scrape for advanced visualization. Includes a pre-built dashboard template.

### Configuration

1. Install Prometheus and Grafana on your monitoring server (or use Grafana Cloud)
2. Add HostHive as a Prometheus scrape target:
   ```yaml
   # prometheus.yml
   scrape_configs:
     - job_name: 'hosthive'
       scheme: https
       bearer_token: '<your_api_key>'
       static_configs:
         - targets: ['panel.example.com:8083']
       metrics_path: /api/v1/metrics/prometheus
       tls_config:
         insecure_skip_verify: true  # if using self-signed cert
   ```
3. In Grafana, add Prometheus as a data source
4. Import the HostHive dashboard:
   - In HostHive, go to **Admin** > **Integrations** > **Grafana**
   - Click **Download Dashboard JSON**
   - In Grafana, go to **Dashboards** > **Import** and upload the JSON

### Required Credentials

| Field | Description |
|---|---|
| API Key | HostHive API key with `metrics:read` scope |

### Available Metrics

- CPU, RAM, disk, network usage (per server and per user)
- Number of domains, databases, email accounts
- Request rates and latencies
- Docker container stats per user
- Backup status and sizes
- SSL certificate expiry dates
- Active connections
- Mail queue size

### Troubleshooting

- **No data in Grafana** — Verify Prometheus can reach the HostHive metrics endpoint. Check `curl -H "Authorization: Bearer <key>" https://panel:8083/api/v1/metrics/prometheus`.
- **"401 Unauthorized"** — The API key is missing or invalid. Ensure the key has `metrics:read` scope.
- **Stale data** — Check the Prometheus scrape interval (recommended: 15s).

---

## WireGuard

### What It Does

Manages WireGuard VPN directly from the HostHive panel. Create VPN peers, generate client configurations, and manage tunnels without touching the command line.

### Configuration

1. In HostHive, go to **Admin** > **Integrations** > **WireGuard**
2. Click **Initialize WireGuard** (this installs WireGuard and generates server keys)
3. Configure the VPN settings:
   - **Listen Port**: Default `51820`
   - **Server Address**: VPN subnet (e.g., `10.10.0.1/24`)
   - **DNS**: DNS server for clients (e.g., `1.1.1.1`)
   - **Endpoint**: Your server's public IP or hostname
4. Click **Save** and **Start WireGuard**

### Adding Peers (Clients)

1. Go to **WireGuard** > **Add Peer**
2. Enter a name for the peer
3. The system automatically generates keys and assigns an IP
4. Download the client configuration file or scan the QR code

### Required Credentials

No external API keys needed. WireGuard keys are generated locally.

### Available Features

- Server and peer key generation
- Client configuration download (`.conf` file)
- QR code generation for mobile clients
- Peer enable/disable
- Traffic statistics per peer
- Multiple VPN interfaces
- Auto-start on boot

### Troubleshooting

- **Cannot connect** — Ensure UDP port 51820 (or your configured port) is open in the firewall.
- **"RTNETLINK operation not supported"** — WireGuard kernel module is not loaded. Run `modprobe wireguard` or reboot.
- **No internet through VPN** — Check that IP forwarding is enabled: `sysctl net.ipv4.ip_forward` should return `1`.
- **Handshake but no traffic** — Verify the AllowedIPs configuration on both server and client.

---

## General Tips

### Testing Integrations

All integrations include a **Test** button that sends a test request to verify connectivity before saving.

### API Key Scopes

When generating API keys for integrations, use the minimum required scope:

| Integration | Required Scope |
|---|---|
| WHMCS | `admin:full` |
| Grafana | `metrics:read` |
| Cloudflare | N/A (uses Cloudflare token) |
| S3/B2/Wasabi | N/A (uses provider credentials) |

### Logs

Integration activity is logged in:

- **Panel**: Admin > Audit Log (filter by "integration")
- **Filesystem**: `/opt/hosthive/logs/integrations.log`
