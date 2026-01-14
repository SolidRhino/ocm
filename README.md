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
| `APPRISE_URL`         | Yes      | Apprise server URL                                                          | `http://apprise:8000`     |
| `APPRISE_KEY`         | Yes      | Apprise configuration key (created in Apprise web UI)                       | `oracle-alerts`           |
| `MIN_DAILY_USAGE`     | No       | Minimum daily usage to trigger a notification (float, in your currency)     | `0`                       |
| `MAX_DAILY_USAGE`     | No       | Maximum daily usage to trigger an alert (float, in your currency)           | `0`                       |
| `CURRENCY`            | No       | Currency symbol for notifications                                           | `$`                       |
| `SUMMARY_SCHEDULE`    | No       | Cron for summary notifications (default: weekly)                            | `0 0 * * 0`               |
| `DAILY_LIMIT_SCHEDULE`| No       | Cron for daily limit alerts (default: daily)                                | `0 0 * * *`               |

> **Note:** The private key file (e.g., `key.pem`) must be mounted into the container at `/app/key.pem`.

---

## Apprise Server Setup

This bot requires a running Apprise server to send notifications. If you don't have one already:

### 1. Deploy Apprise Server
```bash
docker run -d -p 8000:8000 --name apprise caronc/apprise
```

Or use docker-compose:
```yaml
services:
  apprise:
    image: caronc/apprise
    container_name: apprise
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./apprise-config:/config
```

### 2. Configure Notification Services
1. Access the Apprise web UI at `http://your-server:8000`
2. Create a new configuration with a KEY (e.g., `oracle-alerts`)
3. Add your notification service URLs:
   - **Discord**: `discord://webhook_id/webhook_token`
   - **Slack**: `slack://tokenA/tokenB/tokenC`
   - **Email**: `mailto://user:password@gmail.com`
   - **And 100+ other services**

For all supported services and URL formats, see: https://github.com/caronc/apprise/wiki

### 3. Update Your Environment Variables
Set `APPRISE_URL` to your Apprise server URL and `APPRISE_KEY` to the configuration key you created.

---

## Notes
- The bot checks usage on the schedule you define and sends notifications via Apprise.
- Make sure your private key file is accessible and permissions are set correctly.
- You can use the provided `docker-compose.yml` or run the container manually.
- Apprise server must be accessible from the bot container (use Docker network if both are containerized).

## License
MIT 