import os
import sys
import oci
import requests
import datetime
import time
import signal
import logging
import threading
from pathlib import Path
from dotenv import load_dotenv
from croniter import croniter
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Required Oracle Cloud credentials
    oci_user_ocid: str
    oci_tenancy_ocid: str
    oci_fingerprint: str
    oci_region: str

    # Required Apprise configuration
    apprise_url: str
    apprise_key: str

    # Optional thresholds with defaults
    min_daily_usage: float = 0.0
    max_daily_usage: float = 0.0
    currency: str = "$"

    # Optional schedules with defaults
    summary_schedule: str = "0 0 * * 0"  # Sunday midnight
    daily_limit_schedule: str = "0 0 * * *"  # Daily midnight

    # Optional operational settings
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file='.env',
        case_sensitive=False,
        extra='ignore'
    )

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and normalize log level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f'must be one of: {", ".join(valid_levels)}')
        return v_upper

    @field_validator('apprise_url')
    @classmethod
    def validate_apprise_url(cls, v: str) -> str:
        """Validate Apprise URL format."""
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('must start with http:// or https://')
        return v


# Initialize settings with validation
try:
    settings = Settings()
except ValidationError as e:
    # Print errors to stderr before logging is configured
    print("Configuration validation failed:", file=sys.stderr)
    for error in e.errors():
        field = '.'.join(str(loc) for loc in error['loc'])
        msg = error['msg']
        print(f"  - {field}: {msg}", file=sys.stderr)
    print("\nPlease check your .env file and ensure all required fields are set.", file=sys.stderr)
    sys.exit(1)

# Configure logging after settings are loaded
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Create Oracle Cloud config dict
config = {
    "user": settings.oci_user_ocid,
    "key_file": "./key.pem",
    "fingerprint": settings.oci_fingerprint,
    "tenancy": settings.oci_tenancy_ocid,
    "region": settings.oci_region,
}

# Health check file
HEALTH_CHECK_FILE = Path("/tmp/ocm_healthy")
shutdown_event = threading.Event()

# Rate limiting settings
API_CALL_DELAY = 3  # Seconds to wait between API calls
MAX_RETRIES = 3
RETRY_DELAY = 10  # Seconds to wait before retrying after rate limit

def update_health_check():
    """Update health check file to indicate service is alive."""
    try:
        HEALTH_CHECK_FILE.touch()
        HEALTH_CHECK_FILE.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    except Exception as e:
        logger.error(f"Failed to update health check file: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal, initiating graceful shutdown")
    shutdown_event.set()

def get_cron_schedules():
    default_summary_cron = "0 0 * * 0"
    default_alert_cron = "0 0 * * *"
    summary = SUMMARY_SCHEDULE or default_summary_cron
    daily_limit = DAILY_LIMIT_SCHEDULE or default_alert_cron
    return summary, daily_limit

def check_oracle_credentials():
    try:
        usage_client = oci.usage_api.UsageapiClient(config)
        now = datetime.datetime.now(datetime.timezone.utc)
        start = (now - datetime.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        request = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=config["tenancy"],
            time_usage_started=start,
            time_usage_ended=end,
            granularity="DAILY"
        )
        usage_client.request_summarized_usages(request)
        logger.info("Oracle Cloud API credentials: SUCCESS")
        update_health_check()
    except Exception as e:
        logger.error(f"Oracle Cloud API credentials: FAILURE - {e}")
        sys.exit(1)


def get_usage(start_time, end_time, granularity, retry_count=0):
    """
    Fetch usage data with automatic retry on rate limiting.
    """
    logger.debug(f"get_usage called with start_time={start_time}, end_time={end_time}, granularity={granularity}")
    usage_client = oci.usage_api.UsageapiClient(config)
    request = oci.usage_api.models.RequestSummarizedUsagesDetails(
        tenant_id=config["tenancy"],
        time_usage_started=start_time,
        time_usage_ended=end_time,
        granularity=granularity
    )

    try:
        response = usage_client.request_summarized_usages(request)
        logger.debug("API response received successfully")
    except Exception as e:
        # Check if it's a rate limit error (429)
        if hasattr(e, 'status') and e.status == 429:
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_DELAY * (retry_count + 1)  # Exponential backoff
                logger.warning(f"Rate limit hit (429). Retry {retry_count + 1}/{MAX_RETRIES} after {wait_time}s...")
                time.sleep(wait_time)
                return get_usage(start_time, end_time, granularity, retry_count + 1)
            else:
                logger.error("Max retries reached for rate limit. Skipping this data point.")
                return 0.0
        else:
            logger.error(f"Exception during API call: {e}")
            raise

    usage = 0.0
    if hasattr(response.data, 'items') and response.data.items:
        for idx, item in enumerate(response.data.items):
            value = getattr(item, 'computed_amount', None)
            if value is None:
                value = 0.0
            try:
                usage += float(value)
            except Exception as e:
                logger.error(f"Failed to add value for item {idx}: {value} ({type(value)}): {e}")
    else:
        logger.debug("No items in response")

    logger.debug(f"Final usage sum: {usage}")
    return usage


def send_apprise_notification(daily, weekly, monthly, yearly, alert=False, limit=None):
    """
    Send notification via Apprise API with proper error handling.
    """
    if not APPRISE_URL or not APPRISE_KEY:
        logger.error("APPRISE_URL and APPRISE_KEY must be configured")
        return False

    if alert:
        title = "🚨 Oracle Cloud Usage Limit Exceeded!"
        body = f"Your daily usage is higher than your limit {CURRENCY}{limit:.2f}!\n\n"
        body += f"Daily Usage: {CURRENCY}{daily:.2f}"
        notification_type = "failure"
    else:
        title = "📊 Oracle Cloud Usage Report"
        body = "Here is your Oracle Cloud usage summary:\n\n"
        body += f"📊 Daily Usage: {CURRENCY}{daily:.2f}\n"
        body += f"📅 Weekly: {CURRENCY}{weekly:.2f}\n"
        body += f"📆 Monthly: {CURRENCY}{monthly:.2f}\n"
        body += f"📈 Annually: {CURRENCY}{yearly:.2f}"
        notification_type = "info"

    apprise_endpoint = f"{APPRISE_URL}/notify/{APPRISE_KEY}"
    payload = {
        "title": title,
        "body": body,
        "type": notification_type,
        "format": "text"
    }

    try:
        response = requests.post(apprise_endpoint, json=payload, timeout=10)
        if response.status_code not in (200, 204):
            logger.error(f"Failed to send Apprise notification: {response.status_code} {response.text}")
            return False
        else:
            logger.info(f"✅ Apprise notification sent successfully: {title}")
            update_health_check()
            return True
    except Exception as e:
        logger.error(f"Exception sending notification: {e}")
        return False


def send_summary_notification():
    """
    Send summary notification with rate limiting between API calls.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_tomorrow = start_of_today + datetime.timedelta(days=1)
        start_of_week = (start_of_today - datetime.timedelta(days=start_of_today.weekday()))
        start_of_next_week = start_of_week + datetime.timedelta(days=7)
        start_of_month = start_of_today.replace(day=1)
        if start_of_month.month == 12:
            start_of_next_month = start_of_month.replace(year=start_of_month.year + 1, month=1)
        else:
            start_of_next_month = start_of_month.replace(month=start_of_month.month + 1)
        start_of_year = start_of_today.replace(month=1, day=1)
        start_of_next_year = start_of_year.replace(year=start_of_year.year + 1)

        logger.info("Fetching usage data with rate limiting...")

        # Fetch daily usage
        daily = get_usage(start_of_today, start_of_tomorrow, "DAILY")
        logger.info(f"Daily usage fetched: {CURRENCY}{daily:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch weekly usage
        weekly = get_usage(start_of_week, start_of_next_week, "DAILY")
        logger.info(f"Weekly usage fetched: {CURRENCY}{weekly:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch monthly usage
        monthly = get_usage(start_of_month, start_of_next_month, "MONTHLY")
        logger.info(f"Monthly usage fetched: {CURRENCY}{monthly:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch yearly usage
        yearly = get_usage(start_of_year, start_of_next_year, "MONTHLY")
        logger.info(f"Yearly usage fetched: {CURRENCY}{yearly:.2f}")

        # Send notification
        logger.info("Sending summary notification...")
        send_apprise_notification(daily, weekly, monthly, yearly)
        update_health_check()

    except Exception as e:
        logger.error(f"[SUMMARY] Exception: {e}")
        # Try to send error notification
        try:
            payload = {
                "title": "⚠️ Oracle Cloud Monitor Error",
                "body": f"Error fetching Oracle Cloud usage (summary): {str(e)[:200]}",
                "type": "failure"
            }
            requests.post(f"{APPRISE_URL}/notify/{APPRISE_KEY}", json=payload, timeout=10)
        except:
            logger.error("Failed to send error notification")


def send_daily_limit_alert():
    """
    Send alert if daily usage exceeds the configured minimum.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_tomorrow = start_of_today + datetime.timedelta(days=1)

        logger.info("Checking daily usage limit...")
        daily = get_usage(start_of_today, start_of_tomorrow, "DAILY")
        logger.info(f"Daily usage: {CURRENCY}{daily:.2f}, Limit: {CURRENCY}{MIN_DAILY_USAGE:.2f}")

        if daily >= MIN_DAILY_USAGE:
            logger.warning(f"Daily usage {CURRENCY}{daily:.2f} exceeds limit {CURRENCY}{MIN_DAILY_USAGE:.2f}")
            send_apprise_notification(daily, None, None, None, alert=True, limit=MIN_DAILY_USAGE)
        else:
            logger.info("Daily usage is within limits")

        update_health_check()

    except Exception as e:
        logger.error(f"[ALERT] Exception: {e}")
        # Try to send error notification
        try:
            payload = {
                "title": "⚠️ Oracle Cloud Monitor Error",
                "body": f"Error checking daily usage limit: {str(e)[:200]}",
                "type": "failure"
            }
            requests.post(f"{APPRISE_URL}/notify/{APPRISE_KEY}", json=payload, timeout=10)
        except:
            logger.error("Failed to send error notification")


def cron_loop():
    """
    Main loop that runs scheduled tasks with graceful shutdown support.
    """
    check_oracle_credentials()
    summary_cron, alert_cron = get_cron_schedules()
    logger.info(f"Using SUMMARY_SCHEDULE: {summary_cron}")
    logger.info(f"Using DAILY_LIMIT_SCHEDULE: {alert_cron}")
    logger.info(f"API call delay: {API_CALL_DELAY}s between requests")
    logger.info(f"Rate limit retry: {MAX_RETRIES} attempts with {RETRY_DELAY}s base delay")

    def run_cron(cron_expr, func, label):
        now = datetime.datetime.now()
        cron = croniter(cron_expr, now)
        while not shutdown_event.is_set():
            next_run = cron.get_next(datetime.datetime)
            sleep_seconds = (next_run - datetime.datetime.now()).total_seconds()
            logger.info(f"Next {label} check at {next_run} (in {sleep_seconds:.0f} seconds)")

            # Sleep in small chunks to allow responsive shutdown
            sleep_end_time = time.time() + sleep_seconds
            while time.time() < sleep_end_time and not shutdown_event.is_set():
                time.sleep(min(60, sleep_end_time - time.time()))
                if not shutdown_event.is_set():
                    update_health_check()

            if shutdown_event.is_set():
                logger.info(f"{label} thread shutting down gracefully")
                break

            logger.info(f"⏰ Running {label} check...")
            func()
            logger.info(f"✓ {label} check completed")

    summary_thread = threading.Thread(target=run_cron, args=(summary_cron, send_summary_notification, "SUMMARY"), daemon=True)
    alert_thread = threading.Thread(target=run_cron, args=(alert_cron, send_daily_limit_alert, "ALERT"), daemon=True)

    summary_thread.start()
    alert_thread.start()

    # Main thread keeps service alive and updates health check
    while not shutdown_event.is_set():
        time.sleep(60)
        update_health_check()

    logger.info("Main thread shutting down, waiting for worker threads...")
    summary_thread.join(timeout=5)
    alert_thread.join(timeout=5)
    logger.info("Shutdown complete")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("=" * 60)
    logger.info("Oracle Cloud Monitor with Apprise")
    logger.info("=" * 60)

    try:
        cron_loop()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        shutdown_event.set()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
