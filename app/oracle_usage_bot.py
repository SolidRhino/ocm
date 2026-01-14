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
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from typing import Optional
from abc import ABC, abstractmethod
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from apprise import Apprise, NotifyType

load_dotenv()


# ============================================================================
# Apprise Backend Abstraction
# ============================================================================

class AppriseBackend(ABC):
    """Abstract base class for Apprise notification backends."""

    @abstractmethod
    def send_notification(self, title: str, body: str, notification_type: str) -> bool:
        """Send notification via this backend.

        Args:
            title: Notification title
            body: Notification body/message
            notification_type: One of "info", "success", "warning", "failure"

        Returns:
            True if notification sent successfully, False otherwise
        """
        pass


class AppriseServerBackend(AppriseBackend):
    """REST API backend for Apprise server (existing implementation)."""

    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key
        self.logger = logging.getLogger(__name__)

    def send_notification(self, title: str, body: str, notification_type: str) -> bool:
        """Send notification to Apprise server via REST API."""
        try:
            response = requests.post(
                f"{self.url}/notify/{self.key}",
                json={
                    "title": title,
                    "body": body,
                    "type": notification_type
                },
                timeout=10
            )
            response.raise_for_status()
            self.logger.info(f"Notification sent successfully: {title}")
            return True
        except requests.RequestException as e:
            self.logger.error(f"Failed to send notification via server: {e}")
            return False


class AppriseModuleBackend(AppriseBackend):
    """Python module backend using apprise library directly."""

    # Map string types to apprise NotifyType enum
    TYPE_MAPPING = {
        "info": NotifyType.INFO,
        "success": NotifyType.SUCCESS,
        "warning": NotifyType.WARNING,
        "failure": NotifyType.FAILURE,
    }

    def __init__(self, services: str):
        """Initialize with comma-separated service URLs.

        Args:
            services: Comma-separated Apprise service URLs
                     Example: "discord://webhook_id/token,mailto://user:pass@smtp.com"
        """
        self.apprise = Apprise()
        self.logger = logging.getLogger(__name__)

        # Parse and add services
        service_list = [s.strip() for s in services.split(',') if s.strip()]
        for service_url in service_list:
            if not self.apprise.add(service_url):
                raise ValueError(f"Invalid Apprise service URL: {service_url}")

        if len(self.apprise) == 0:
            raise ValueError("No valid Apprise services configured")

        self.logger.info(f"Initialized Apprise module with {len(self.apprise)} service(s)")

    def send_notification(self, title: str, body: str, notification_type: str) -> bool:
        """Send notification via apprise Python module."""
        try:
            notify_type = self.TYPE_MAPPING.get(notification_type, NotifyType.INFO)
            success = self.apprise.notify(
                title=title,
                body=body,
                notify_type=notify_type
            )
            if success:
                self.logger.info(f"Notification sent successfully: {title}")
            else:
                self.logger.error(f"Failed to send notification: {title}")
            return success
        except Exception as e:
            self.logger.error(f"Failed to send notification via module: {e}")
            return False


def create_apprise_backend(settings) -> AppriseBackend:
    """Create appropriate Apprise backend based on configuration.

    Args:
        settings: Settings object with apprise configuration

    Returns:
        AppriseBackend instance (Server or Module)

    Raises:
        ValueError: If mode is invalid or required settings missing
    """
    mode = settings.apprise_mode.lower()

    if mode == "server":
        if not settings.apprise_url or not settings.apprise_key:
            raise ValueError("Server mode requires APPRISE_URL and APPRISE_KEY")
        return AppriseServerBackend(settings.apprise_url, settings.apprise_key)

    elif mode == "module":
        if not settings.apprise_services:
            raise ValueError("Module mode requires APPRISE_SERVICES")
        return AppriseModuleBackend(settings.apprise_services)

    else:
        raise ValueError(f"Invalid APPRISE_MODE: {mode}. Must be 'server' or 'module'")


# ============================================================================
# Application Configuration
# ============================================================================

class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Required Oracle Cloud credentials
    oci_user_ocid: str
    oci_tenancy_ocid: str
    oci_fingerprint: str
    oci_region: str

    # Apprise mode selection (REQUIRED)
    apprise_mode: str

    # Server mode settings
    apprise_url: Optional[str] = None
    apprise_key: Optional[str] = None

    # Module mode settings
    apprise_services: Optional[str] = None

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

    @field_validator('apprise_mode')
    @classmethod
    def validate_apprise_mode(cls, v: str) -> str:
        """Validate apprise_mode is 'server' or 'module'."""
        valid_modes = ['server', 'module']
        if v.lower() not in valid_modes:
            raise ValueError(f"apprise_mode must be one of {valid_modes}, got: {v}")
        return v.lower()

    @field_validator('apprise_url')
    @classmethod
    def validate_apprise_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate Apprise URL format."""
        if v is not None and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('must start with http:// or https://')
        return v

    @model_validator(mode='after')
    def validate_apprise_config(self) -> 'Settings':
        """Validate mode-specific configuration is present."""
        if self.apprise_mode == 'server':
            if not self.apprise_url or not self.apprise_key:
                raise ValueError("Server mode requires APPRISE_URL and APPRISE_KEY")
        elif self.apprise_mode == 'module':
            if not self.apprise_services:
                raise ValueError("Module mode requires APPRISE_SERVICES")
        return self


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

# Initialize Apprise backend based on mode
try:
    apprise_backend = create_apprise_backend(settings)
    logger.info(f"Apprise backend initialized in {settings.apprise_mode} mode")
except ValueError as e:
    logger.error(f"Failed to initialize Apprise backend: {e}")
    sys.exit(1)

# Health check file
HEALTH_CHECK_FILE = Path("/tmp/ocm_healthy")
shutdown_event = threading.Event()

# Initialize APScheduler
scheduler = BackgroundScheduler(
    timezone='UTC',
    job_defaults={
        'coalesce': True,  # Combine multiple missed runs into one
        'max_instances': 1,  # Prevent overlapping executions
        'misfire_grace_time': 3600  # Run if missed within last hour
    }
)

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

    # Shutdown scheduler gracefully, waiting for running jobs to complete
    if scheduler.running:
        logger.info("Shutting down scheduler, waiting for running jobs to complete...")
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")

def job_listener(event):
    """Log APScheduler job lifecycle events."""
    if event.exception:
        logger.error(f"Job {event.job_id} failed with exception: {event.exception}")
    else:
        logger.debug(f"Job {event.job_id} completed successfully")

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
    """Send notification via configured Apprise backend with proper error handling.

    Args:
        daily: Daily usage amount
        weekly: Weekly usage amount
        monthly: Monthly usage amount
        yearly: Yearly usage amount
        alert: If True, send alert notification; otherwise send summary
        limit: Usage limit for alert notifications

    Returns:
        True if notification sent successfully, False otherwise
    """
    if alert:
        title = "🚨 Oracle Cloud Usage Limit Exceeded!"
        body = f"Your daily usage is higher than your limit {settings.currency}{limit:.2f}!\n\n"
        body += f"Daily Usage: {settings.currency}{daily:.2f}"
        notification_type = "failure"
    else:
        title = "📊 Oracle Cloud Usage Report"
        body = "Here is your Oracle Cloud usage summary:\n\n"
        body += f"📊 Daily Usage: {settings.currency}{daily:.2f}\n"
        body += f"📅 Weekly: {settings.currency}{weekly:.2f}\n"
        body += f"📆 Monthly: {settings.currency}{monthly:.2f}\n"
        body += f"📈 Annually: {settings.currency}{yearly:.2f}"
        notification_type = "info"

    # Send via configured backend (server or module)
    success = apprise_backend.send_notification(title, body, notification_type)

    if success:
        update_health_check()

    return success


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
        logger.info(f"Daily usage fetched: {settings.currency}{daily:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch weekly usage
        weekly = get_usage(start_of_week, start_of_next_week, "DAILY")
        logger.info(f"Weekly usage fetched: {settings.currency}{weekly:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch monthly usage
        monthly = get_usage(start_of_month, start_of_next_month, "MONTHLY")
        logger.info(f"Monthly usage fetched: {settings.currency}{monthly:.2f}")
        time.sleep(API_CALL_DELAY)  # Rate limiting delay

        # Fetch yearly usage
        yearly = get_usage(start_of_year, start_of_next_year, "MONTHLY")
        logger.info(f"Yearly usage fetched: {settings.currency}{yearly:.2f}")

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
            requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)
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
        logger.info(f"Daily usage: {settings.currency}{daily:.2f}, Limit: {settings.currency}{settings.min_daily_usage:.2f}")

        if daily >= settings.min_daily_usage:
            logger.warning(f"Daily usage {settings.currency}{daily:.2f} exceeds limit {settings.currency}{settings.min_daily_usage:.2f}")
            send_apprise_notification(daily, None, None, None, alert=True, limit=settings.min_daily_usage)
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
            requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)
        except:
            logger.error("Failed to send error notification")


def start_scheduler():
    """Initialize and start the APScheduler with configured jobs."""
    # Validate Oracle credentials before starting
    check_oracle_credentials()

    # Get cron schedules from settings
    summary_cron, alert_cron = get_cron_schedules()

    # Log configuration
    logger.info(f"Using SUMMARY_SCHEDULE: {summary_cron}")
    logger.info(f"Using DAILY_LIMIT_SCHEDULE: {alert_cron}")
    logger.info(f"API call delay: {API_CALL_DELAY}s between requests")
    logger.info(f"Rate limit retry: {MAX_RETRIES} attempts with {RETRY_DELAY}s base delay")

    # Add summary notification job
    scheduler.add_job(
        func=send_summary_notification,
        trigger=CronTrigger.from_crontab(summary_cron, timezone='UTC'),
        id='summary_job',
        name='Weekly Usage Summary',
        replace_existing=True
    )

    # Add daily limit alert job
    scheduler.add_job(
        func=send_daily_limit_alert,
        trigger=CronTrigger.from_crontab(alert_cron, timezone='UTC'),
        id='alert_job',
        name='Daily Limit Check',
        replace_existing=True
    )

    # Add event listener for job logging
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started successfully")

    # Log next run times
    summary_job = scheduler.get_job('summary_job')
    alert_job = scheduler.get_job('alert_job')
    if summary_job:
        logger.info(f"Next summary run: {summary_job.next_run_time}")
    if alert_job:
        logger.info(f"Next alert run: {alert_job.next_run_time}")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("=" * 60)
    logger.info("Oracle Cloud Monitor with Apprise")
    logger.info("=" * 60)

    try:
        start_scheduler()

        # Main thread keeps service alive and updates health check
        while not shutdown_event.is_set():
            time.sleep(60)
            update_health_check()

        logger.info("Shutdown complete")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        shutdown_event.set()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
