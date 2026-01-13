# APScheduler Upgrade Design

**Date**: 2026-01-13
**Status**: Validated
**Implementation Priority**: Medium (Medium effort, High impact, Low risk)

## Overview

Replace croniter-based manual threading implementation with APScheduler's BackgroundScheduler for better job management, misfire handling, and cleaner integration with application lifecycle.

## Goals

1. **Simpler Code**: Eliminate 30-40 lines of manual threading and cron iteration logic
2. **Better Reliability**: Automatic misfire handling with 1-hour grace period
3. **Cleaner Shutdown**: Integrated graceful shutdown that waits for running jobs
4. **No Overlap**: Prevent job overlap with max_instances control
5. **Minimal Refactoring**: Maintain single-file architecture and existing function signatures

## Current Implementation Issues

**croniter-based approach:**
- Manual threading with `run_cron()` inner function
- Manual sleep chunking for responsive shutdown
- No misfire handling (missed jobs never run)
- Manual next-run calculation and timing
- ~40 lines of custom scheduling logic

**Problems:**
- If server restarts at 1 AM and job scheduled at midnight, job is skipped
- Manual threading is error-prone
- Complex shutdown coordination with thread.join()
- No protection against job overlap

## APScheduler Benefits

**What APScheduler Provides:**
1. **Automatic Job Execution** - No manual threading required
2. **Misfire Handling** - Missed jobs run if within grace period
3. **Max Instances Control** - Prevents overlapping executions
4. **Event Listeners** - Job lifecycle logging (start/complete/error)
5. **Better Error Isolation** - One job failure doesn't crash scheduler
6. **Industry Standard** - Used by Flask-APScheduler, Airflow, many production apps

## Architecture

### Core Components

**1. BackgroundScheduler**
```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(
    timezone='UTC',
    job_defaults={
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': 3600
    }
)
```

**Configuration:**
- `timezone='UTC'` - Explicit UTC matching existing time calculations
- `coalesce=True` - Combine multiple missed runs into one (prevents spam)
- `max_instances=1` - Only one instance per job runs at a time
- `misfire_grace_time=3600` - Run if scheduled within last hour (1 hour grace)

**2. CronTrigger Jobs**

Two jobs configured from environment variables:

```python
# Summary notification (default: Sunday midnight)
scheduler.add_job(
    func=send_summary_notification,
    trigger=CronTrigger.from_crontab(settings.summary_schedule, timezone='UTC'),
    id='summary_job',
    name='Weekly Usage Summary',
    replace_existing=True
)

# Daily limit alert (default: daily midnight)
scheduler.add_job(
    func=send_daily_limit_alert,
    trigger=CronTrigger.from_crontab(settings.daily_limit_schedule, timezone='UTC'),
    id='alert_job',
    name='Daily Limit Check',
    replace_existing=True
)
```

**Job Configuration:**
- `id` - Unique identifier for the job
- `name` - Human-readable description for logging
- `replace_existing=True` - Safe re-registration on config reload
- `trigger` - CronTrigger parsed from cron expression string

**3. Event Listeners (Optional)**

```python
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

def job_listener(event):
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        logger.debug(f"Job {event.job_id} completed successfully")

scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
```

## Implementation Strategy

### 1. Code Removal

**Delete these sections from `oracle_usage_bot.py`:**

1. Manual threading function (lines ~345-366):
   ```python
   def run_cron(cron_expr, func, label):
       # ... ~20 lines of manual cron iteration and threading
   ```

2. Thread creation (lines ~368-372):
   ```python
   summary_thread = threading.Thread(...)
   alert_thread = threading.Thread(...)
   summary_thread.start()
   alert_thread.start()
   ```

3. Thread cleanup (lines ~380-381):
   ```python
   summary_thread.join(timeout=5)
   alert_thread.join(timeout=5)
   ```

**Total lines removed: ~30-40**

### 2. New Scheduler Initialization

**Replace `cron_loop()` function with:**

```python
def start_scheduler():
    """Initialize and start the APScheduler."""
    check_oracle_credentials()

    # Log configuration
    logger.info(f"Using SUMMARY_SCHEDULE: {settings.summary_schedule}")
    logger.info(f"Using DAILY_LIMIT_SCHEDULE: {settings.daily_limit_schedule}")
    logger.info(f"API call delay: {API_CALL_DELAY}s between requests")
    logger.info(f"Rate limit retry: {MAX_RETRIES} attempts with {RETRY_DELAY}s base delay")

    # Add jobs to scheduler
    scheduler.add_job(
        func=send_summary_notification,
        trigger=CronTrigger.from_crontab(settings.summary_schedule, timezone='UTC'),
        id='summary_job',
        name='Weekly Usage Summary',
        replace_existing=True
    )

    scheduler.add_job(
        func=send_daily_limit_alert,
        trigger=CronTrigger.from_crontab(settings.daily_limit_schedule, timezone='UTC'),
        id='alert_job',
        name='Daily Limit Check',
        replace_existing=True
    )

    # Add event listener for job logging
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started successfully")
    logger.info(f"Next summary run: {scheduler.get_job('summary_job').next_run_time}")
    logger.info(f"Next alert run: {scheduler.get_job('alert_job').next_run_time}")
```

### 3. Simplified Main Loop

**Main loop becomes simpler:**

```python
if __name__ == "__main__":
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
```

### 4. Enhanced Signal Handler

**Update signal handler to shutdown scheduler:**

```python
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal, initiating graceful shutdown")
    shutdown_event.set()

    # Shutdown scheduler gracefully (wait for running jobs)
    if scheduler.running:
        logger.info("Shutting down scheduler, waiting for running jobs...")
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")
```

## Misfire Handling Details

**Grace Period: 3600 seconds (1 hour)**

**Scenarios:**

1. **Server restart at 12:30 AM, job scheduled at midnight:**
   - Misfire within 30 minutes (< 1 hour)
   - ✅ Job runs immediately on startup
   - User still gets daily/weekly notification

2. **Server down for 6 hours:**
   - Misfire > 1 hour grace period
   - ❌ Job skipped
   - Next run: Next scheduled time
   - Prevents notification spam from old missed jobs

3. **Job takes 2 minutes, scheduled every minute:**
   - `max_instances=1` prevents second instance
   - Next run waits for first to complete
   - No overlapping API calls

4. **Multiple misfires during downtime:**
   - `coalesce=True` combines into one execution
   - Run once, not multiple times
   - Example: Missed 3 times → Run once, not 3x

## Backward Compatibility

**What Stays the Same:**
- ✅ All existing functions (`send_summary_notification`, `send_daily_limit_alert`) unchanged
- ✅ Health check mechanism preserved
- ✅ Signal handling pattern maintained
- ✅ Configuration via same environment variables
- ✅ Same cron expression syntax
- ✅ Single-file architecture
- ✅ UTC timezone calculations

**What Changes:**
- ⚠️ `cron_loop()` function removed
- ⚠️ Manual threading removed
- ⚠️ Manual cron iteration removed
- ✅ Replaced with simpler APScheduler setup

## Dependencies

**New Dependency:**
- `APScheduler>=3.10,<4.0` - Add to requirements.txt

**APScheduler 3.x Features Used:**
- BackgroundScheduler for non-blocking execution
- CronTrigger for cron expression parsing
- Event listeners for job lifecycle logging
- Graceful shutdown with wait=True

**Note:** APScheduler 4.0 is in development but not stable yet (2026). Use 3.x stable branch.

## Testing Strategy

**Functional Tests:**
1. Jobs run at scheduled times
2. Misfire handling works (restart server before scheduled time)
3. Max instances prevents overlap (simulate long-running job)
4. Graceful shutdown waits for running jobs
5. Health check continues updating

**Validation Commands:**
```bash
# Check next run times
# Should log on startup

# Test graceful shutdown
docker kill -s SIGTERM <container>
# Should log "waiting for running jobs" and complete

# Test misfire
# Stop server at 11:50 PM, restart at 12:10 AM
# Job scheduled at midnight should run immediately
```

## Migration Steps

1. **Add dependency**: Update `app/requirements.txt` with APScheduler
2. **Add imports**: Import BackgroundScheduler, CronTrigger, events
3. **Initialize scheduler**: Create global scheduler instance with config
4. **Create start_scheduler()**: New function to add jobs and start
5. **Remove manual threading**: Delete `run_cron()` and thread management
6. **Update signal handler**: Add scheduler.shutdown() call
7. **Simplify main loop**: Call start_scheduler(), keep health check loop
8. **Test thoroughly**: Verify scheduling, misfires, shutdown

## Benefits Summary

**Code Quality:**
- ✅ 30-40 lines removed (manual threading eliminated)
- ✅ Simpler, more maintainable code
- ✅ Industry-standard library

**Reliability:**
- ✅ Automatic misfire handling (1-hour grace period)
- ✅ Job overlap prevention
- ✅ Better error isolation (one job failure doesn't crash scheduler)

**Operations:**
- ✅ Cleaner shutdown (waits for running jobs)
- ✅ Better logging (job lifecycle events)
- ✅ Next run times visible on startup

**Developer Experience:**
- ✅ Well-documented library with large community
- ✅ Easy to add new jobs in future
- ✅ Better debugging with event listeners

## Trade-offs

**Pros:**
- Significantly simpler code
- Better reliability with misfire handling
- Industry standard solution
- Future-proof (widely adopted in 2026)

**Cons:**
- One additional dependency (APScheduler)
- Learning curve for APScheduler concepts (minimal)
- Slightly different shutdown timing (waits for jobs vs 5-second timeout)

**Decision:** Benefits far outweigh minimal cost of one dependency.

## References

- [APScheduler 3.x Documentation](https://apscheduler.readthedocs.io/en/3.x/)
- [APScheduler User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- [CronTrigger Documentation](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html)
- Research: APScheduler vs croniter Python scheduling 2026
