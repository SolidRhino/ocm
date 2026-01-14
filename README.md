# Oracle Cloud Usage Monitor

This bot monitors your Oracle Cloud usage and sends notifications via Apprise, helping you avoid exceeding your free tier or incurring charges.

## Features
- Fetches daily Oracle Cloud usage via the Oracle Cloud API
- Sends notifications through Apprise server to any supported service (Discord, Slack, email, etc.)
- Customizable notification thresholds and schedule

---

## Quick Start (Docker)

### 1. Prepare your environment
- Copy `env.sample` to `.env` and fill in your values:
  ```bash
  cp env.sample .env
  # Edit .env with your credentials and preferences
  ```
- Make sure your Oracle Cloud API private key (e.g., `key.pem`) is in the project directory.
- **You can obtain your Oracle Cloud credentials (User OCID, Tenancy OCID, API Key, etc.) from the [Oracle Cloud Auth Tokens page](https://cloud.oracle.com/identity/domains/my-profile/auth-tokens).**

### 2. Build the Docker image (optional)
If you want to build locally:
```bash
docker build -t ocm-bot .
```

### 3. Run with Docker Compose (recommended)
```yaml
version: '3.8'
services:
  ocm:
    image: ghcr.io/iamneuro/ocm:latest  # or use 'ocm-bot' if you built locally
    container_name: ocm
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./key.pem:/app/key.pem:ro
```
Start the service:
```bash
docker-compose up -d
```

### 4. Run with plain Docker
```bash
docker run -d \
  --name ocm \
  --env-file .env \
  -v $(pwd)/key.pem:/app/key.pem:ro \
  ghcr.io/iamneuro/ocm:latest
```

---

## Environment Variables

| Variable              | Required | Description                                                                 | Example / Default         |
|-----------------------|----------|-----------------------------------------------------------------------------|---------------------------|
| `OCI_USER_OCID`       | Yes      | Oracle Cloud User OCID                                                      | `ocid1.user.oc1..xxxx`    |
| `OCI_TENANCY_OCID`    | Yes      | Oracle Cloud Tenancy OCID                                                   | `ocid1.tenancy.oc1..xxxx` |
| `OCI_FINGERPRINT`     | Yes      | API Key fingerprint                                                         | `12:34:56:78:90:ab:cd:ef` |
| `OCI_REGION`          | Yes      | Oracle Cloud region                                                         | `us-ashburn-1`            |
| `APPRISE_MODE`        | Yes      | Notification mode: `server` or `module`                                     | `server`                  |
| `APPRISE_URL`         | If mode=server | Apprise server URL                                                    | `http://apprise:8000`     |
| `APPRISE_KEY`         | If mode=server | Apprise configuration key (created in Apprise web UI)                 | `oracle-alerts`           |
| `APPRISE_SERVICES`    | If mode=module | Comma-separated list of service URLs                                  | `discord://xxx,slack://yyy` |
| `MIN_DAILY_USAGE`     | No       | Minimum daily usage to trigger a notification (float, in your currency)     | `0`                       |
| `MAX_DAILY_USAGE`     | No       | Maximum daily usage to trigger an alert (float, in your currency)           | `0`                       |
| `CURRENCY`            | No       | Currency symbol for notifications                                           | `$`                       |
| `SUMMARY_SCHEDULE`    | No       | Cron for summary notifications (default: weekly)                            | `0 0 * * 0`               |
| `DAILY_LIMIT_SCHEDULE`| No       | Cron for daily limit alerts (default: daily)                                | `0 0 * * *`               |

> **Note:** The private key file (e.g., `key.pem`) must be mounted into the container at `/app/key.pem`.

---

## Notification Configuration

This bot supports two modes for sending notifications:

### Option 1: Apprise Server Mode (Recommended for Multiple Bots)

Use this if you want centralized notification management with a web UI.

**1. Deploy Apprise Server**:
```bash
docker run -d -p 8000:8000 --name apprise caronc/apprise
```

**2. Configure Notifications**:
- Access Apprise web UI at `http://your-apprise-server:8000`
- Create a configuration with a memorable KEY (e.g., "oracle-alerts")
- Add notification URLs for your services (Discord, Slack, email, etc.)

**3. Configure Bot** (`.env`):
```bash
APPRISE_MODE=server
APPRISE_URL=http://apprise:8000
APPRISE_KEY=oracle-alerts
```

**Advantages**:
- Change notification destinations without redeploying bot
- Centralized management for multiple bots
- Web UI for configuration

### Option 2: Module Mode (Simple Deployment)

Use this if you want a self-contained bot without external dependencies.

**1. Find Service URLs**:
- Visit https://github.com/caronc/apprise/wiki
- Get URL format for your services (Discord, Slack, email, etc.)
- Example Discord: `discord://webhook_id/webhook_token`

**2. Configure Bot** (`.env`):
```bash
APPRISE_MODE=module
APPRISE_SERVICES=discord://webhook_id/token,mailto://user:pass@smtp.com
```

**Advantages**:
- No separate Apprise server needed
- Simpler deployment (one container)
- Direct service communication

**Note**: To change notification destinations in module mode, you must update `.env` and restart the bot.

## Migration Guide

### Existing Deployments (Server Mode)

If you're already using Apprise server mode, add one line to your `.env`:

```bash
APPRISE_MODE=server
```

Then restart:
```bash
docker-compose --profile ocm restart
```

---

## Notes
- The bot checks usage on the schedule you define and sends notifications via Apprise.
- Make sure your private key file is accessible and permissions are set correctly.
- You can use the provided `docker-compose.yml` or run the container manually.
- Apprise server must be accessible from the bot container (use Docker network if both are containerized).

## License
MIT 