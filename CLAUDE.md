# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based notification bot that monitors Oracle Cloud usage and sends notifications via an Apprise server. The bot runs as a long-lived service using cron-based scheduling to check usage at configurable intervals. Apprise provides a centralized notification hub that can route alerts to multiple services (Discord, Slack, email, etc.) configured through the Apprise web interface.

### Project Structure
```
ocm/
├── app/
│   ├── oracle_usage_bot.py    # Main application
│   ├── Dockerfile              # Container image definition
│   └── requirements.txt        # Python dependencies
├── docker-compose.yml          # Docker Compose configuration
├── env.sample                  # Environment variables template
├── CLAUDE.md                   # This file
└── README.md                   # User documentation
```

## Development Commands

### Local Development
```bash
# Navigate to app directory
cd app

# Install dependencies
pip install -r requirements.txt

# Run the bot locally (requires .env in root and key.pem accessible)
python oracle_usage_bot.py
```

### Docker Development
```bash
# Build the Docker image (from project root)
docker build -t ocm-bot ./app

# Run with docker-compose (recommended)
# Note: Requires DOCKER_DATA_DIR environment variable set
docker-compose --profile ocm up -d

# View logs
docker-compose logs -f ocm

# Stop the service
docker-compose --profile ocm down

# Run with plain Docker (alternative)
docker run -d \
  --name ocm \
  --env-file .env \
  -v /path/to/key.pem:/app/key.pem:ro \
  ocm-bot
```

**Docker Compose Notes**:
- Uses profiles: `ocm` or `all` (activate with `--profile ocm`)
- Requires `DOCKER_DATA_DIR` environment variable for key.pem mount location
- Configured for `linux/arm64` platform (modify in docker-compose.yml if needed)
- Build context: `./app` directory

## Architecture

### Core Components

**app/oracle_usage_bot.py** - Single-file application with three main responsibilities:

1. **Oracle Cloud API Integration** (`get_usage()`)
   - Uses Oracle Cloud Python SDK (`oci`) to fetch usage data
   - Supports different time granularities (DAILY, MONTHLY)
   - Queries the UsageAPI client with time ranges and granularity
   - Automatic retry logic for rate limit errors (429 status)
   - Exponential backoff with configurable max retries (default: 3 attempts)
   - Configurable delay between API calls (default: 3 seconds)

2. **Dual Scheduling System** (`start_scheduler()`)
   - **Summary notifications**: Weekly usage report (default: Sundays at midnight)
   - **Daily limit alerts**: Checks if usage exceeds MIN_DAILY_USAGE threshold (default: daily at midnight)
   - Managed by APScheduler BackgroundScheduler with CronTrigger jobs
   - Automatic misfire handling (1-hour grace period)
   - Job overlap prevention (max_instances=1)
   - Configurable via `SUMMARY_SCHEDULE` and `DAILY_LIMIT_SCHEDULE` environment variables

3. **Apprise Notifications** (`send_apprise_notification()`)
   - **Dual-mode support**: Server mode (REST API) or Module mode (Python library)
   - **Mode selection**: Configured via `APPRISE_MODE` environment variable
   - **Server mode**: Sends to Apprise server, which routes to configured services
   - **Module mode**: Direct service communication via apprise Python library
   - Summary reports include daily, weekly, monthly, and yearly usage with "info" type
   - Alert notifications trigger when daily usage >= MIN_DAILY_USAGE with "failure" type
   - Notification backend abstraction ensures consistent behavior across modes

### APScheduler Configuration

**Scheduler Settings**:
- **Timezone**: UTC (matches existing time calculations)
- **Coalesce**: True (combine multiple missed runs into one)
- **Max Instances**: 1 per job (prevent overlapping executions)
- **Misfire Grace Time**: 3600 seconds (1 hour)

**Misfire Behavior**:
- Jobs scheduled within last hour run immediately on startup
- Jobs missed by >1 hour are skipped (prevents notification spam)
- Multiple misfires combined into single execution (coalesce=True)

**Job Management**:
- Two CronTrigger jobs: summary_job and alert_job
- Jobs registered with replace_existing=True for safe reload
- Event listeners log job execution and failures
- Graceful shutdown waits for running jobs to complete

### Configuration Flow

- Environment variables loaded via `python-dotenv` from `.env` file (root directory)
- Apprise mode selected via `APPRISE_MODE` (server or module)
- Server mode: `APPRISE_URL` and `APPRISE_KEY` required
- Module mode: `APPRISE_SERVICES` (comma-separated URLs) required
- Backend validation on startup via `create_apprise_backend()`
- Configuration errors cause immediate startup failure with clear error messages
- Oracle Cloud credentials configured in `config` dict (user OCID, tenancy OCID, fingerprint, region)
- Private key location:
  - Local development: `./key.pem` relative to app directory
  - Docker container: `/app/key.pem` (mounted from `${DOCKER_DATA_DIR}/ocm/key.pem`)
- Credentials validated on startup via `check_oracle_credentials()`
- Rate limiting configured via constants: `API_CALL_DELAY` (3s), `MAX_RETRIES` (3), `RETRY_DELAY` (10s)
- Logging level configured via `LOG_LEVEL` environment variable (default: INFO, options: DEBUG, INFO, WARNING, ERROR)

### Observability & Resilience

**Structured Logging**:
- Uses Python `logging` module with configurable log levels (DEBUG, INFO, WARNING, ERROR)
- Controlled via `LOG_LEVEL` environment variable (default: INFO)
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- All output to stdout for Docker log aggregation

**Graceful Shutdown**:
- Signal handlers for SIGTERM and SIGINT
- APScheduler shutdown waits for running jobs to complete
- Uses `threading.Event()` to coordinate main thread shutdown
- Scheduler.shutdown(wait=True) ensures job completion before exit

**Health Check**:
- File-based health check at `/tmp/ocm_healthy`
- Updated every 60 seconds and after successful operations
- Contains ISO-format timestamp of last update
- Docker HEALTHCHECK verifies file exists and was modified within last 2 minutes
- Health check settings: `--interval=60s --timeout=10s --start-period=30s --retries=3`

### Key Dependencies

- **oci**: Oracle Cloud Infrastructure Python SDK
- **requests**: HTTP calls for server mode Apprise API
- **apprise**: Python notification library for module mode (80+ services)
- **APScheduler**: Production-ready job scheduling with misfire handling
- **python-dotenv**: Environment variable management
- **logging**: Structured logging (Python stdlib)
- **signal**: Graceful shutdown handling (Python stdlib)
- **pathlib**: Health check file management (Python stdlib)

## Apprise Server Setup

This bot requires a running Apprise server. To set up notifications:

1. **Deploy Apprise Server** (if not already running):
   ```bash
   docker run -d -p 8000:8000 --name apprise caronc/apprise
   ```

2. **Configure Notification Services**:
   - Access Apprise web UI at `http://your-apprise-server:8000`
   - Create a configuration with a memorable KEY (e.g., "oracle-alerts")
   - Add notification URLs for your services (Discord, Slack, email, etc.)
   - Example Discord URL format: `discord://webhook_id/webhook_token`

3. **Set Environment Variables**:
   - `APPRISE_URL`: Base URL of your Apprise server (e.g., `http://apprise:8000`)
   - `APPRISE_KEY`: The configuration KEY you created in step 2

For more Apprise URL formats, see: https://github.com/caronc/apprise/wiki

## Important Notes

### Runtime Behavior
- The bot validates Oracle Cloud credentials on startup and exits if validation fails
- APScheduler BackgroundScheduler manages job execution automatically
- Misfire handling runs jobs if scheduled within last hour
- Job overlap prevented by max_instances=1 setting
- Scheduler shutdown waits for running jobs to complete before exit
- Time calculations are done in UTC using timezone-aware datetime objects (`datetime.now(datetime.timezone.utc)`)
- Main thread updates health check every 60 seconds and sleeps in 60-second intervals
- Jobs update health check after successful operations
- Rate limiting protects against Oracle API 429 errors with automatic retry and exponential backoff
- Summary notifications include 3-second delays between consecutive API calls to avoid rate limits
- Error notifications are sent via Apprise when API failures occur
- All operations use structured logging (no print statements) with timestamps and log levels
- Signal handlers (SIGTERM, SIGINT) trigger coordinated shutdown
- Docker health check monitors service via `/tmp/ocm_healthy` file freshness (must be < 2 minutes old)

### Deployment Considerations
- Private key file (`key.pem`) must have proper permissions and be accessible at runtime
- Apprise server must be accessible from the bot container (use Docker network if both are containerized)
- Docker Compose requires `DOCKER_DATA_DIR` environment variable to be set
- Docker platform is configured for `linux/arm64` - modify if deploying on different architecture
- Application files are in `app/` subdirectory - build context must be set accordingly

### Development Workflow
- Keep CLAUDE.md up-to-date if I change something in the code
- When modifying code, work in the `app/` directory
- Environment variables (`.env`) should be in the project root, not in `app/`
- Test locally before building Docker image