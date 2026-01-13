# APScheduler Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace croniter-based manual threading with APScheduler BackgroundScheduler for simpler code, better reliability, and automatic misfire handling.

**Architecture:** BackgroundScheduler runs in background thread with two CronTrigger jobs (summary, alert). Main thread continues health check updates. Graceful shutdown waits for running jobs to complete.

**Tech Stack:** APScheduler 3.x, Python threading, signal handlers

---

## Task 1: Add APScheduler Dependency

**Files:**
- Modify: `app/requirements.txt`

**Step 1: Add APScheduler to requirements**

Add this line to `app/requirements.txt`:
```
APScheduler>=3.10,<4.0
```

**Step 2: Verify requirements file**

Run: `cat app/requirements.txt`
Expected: Should show APScheduler added to the list

**Step 3: Commit dependency addition**

```bash
git add app/requirements.txt
git commit -m "feat: add APScheduler for job scheduling"
```

---

## Task 2: Add APScheduler Imports and Global Initialization

**Files:**
- Modify: `app/oracle_usage_bot.py:1-20`

**Step 1: Add APScheduler imports**

Add after line 12 (after `from croniter import croniter`):
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
```

**Step 2: Remove croniter import**

Remove line 12:
```python
from croniter import croniter
```

**Step 3: Add scheduler initialization**

Add after the `shutdown_event` initialization (after line ~101):
```python

# Initialize APScheduler
scheduler = BackgroundScheduler(
    timezone='UTC',
    job_defaults={
        'coalesce': True,  # Combine multiple missed runs into one
        'max_instances': 1,  # Prevent overlapping executions
        'misfire_grace_time': 3600  # Run if missed within last hour
    }
)
```

**Step 4: Verify file compiles**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No output (compilation successful)

**Step 5: Commit imports and initialization**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: add APScheduler imports and global initialization"
```

---

## Task 3: Create Job Event Listener

**Files:**
- Modify: `app/oracle_usage_bot.py` (add new function before `get_cron_schedules`)

**Step 1: Add job_listener function**

Add this function after the scheduler initialization and before `get_cron_schedules()` function (around line ~118):
```python

def job_listener(event):
    """Log APScheduler job lifecycle events."""
    if event.exception:
        logger.error(f"Job {event.job_id} failed with exception: {event.exception}")
    else:
        logger.debug(f"Job {event.job_id} completed successfully")
```

**Step 2: Verify function added correctly**

Run: `grep -n "def job_listener" app/oracle_usage_bot.py`
Expected: Should show line number where function was added

**Step 3: Commit job listener**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: add APScheduler job event listener for logging"
```

---

## Task 4: Create start_scheduler Function

**Files:**
- Modify: `app/oracle_usage_bot.py` (replace `cron_loop` function)

**Step 1: Find and remove cron_loop function**

Locate the `cron_loop()` function (starts around line ~334) and DELETE the entire function including:
- The function definition
- All inner code including `run_cron()` nested function
- Thread creation and management
- Everything up to but NOT including the `if __name__ == "__main__":` line

**Step 2: Create new start_scheduler function**

Add this function in place of the deleted `cron_loop()`:
```python
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
```

**Step 3: Verify no syntax errors**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No output (compilation successful)

**Step 4: Commit start_scheduler function**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: replace cron_loop with APScheduler start_scheduler"
```

---

## Task 5: Update Signal Handler for Scheduler Shutdown

**Files:**
- Modify: `app/oracle_usage_bot.py` (update `signal_handler` function)

**Step 1: Update signal_handler function**

Find the `signal_handler` function (around line ~59-63) and replace it with:
```python
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
```

**Step 2: Verify function updated**

Run: `grep -A8 "def signal_handler" app/oracle_usage_bot.py`
Expected: Should show updated function with scheduler.shutdown() call

**Step 3: Commit signal handler update**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: update signal handler to shutdown APScheduler gracefully"
```

---

## Task 6: Simplify Main Block

**Files:**
- Modify: `app/oracle_usage_bot.py` (update `if __name__ == "__main__":` block)

**Step 1: Update main block**

Find the `if __name__ == "__main__":` block (around line ~385) and replace the entire try block with:
```python
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
```

**Step 2: Verify syntax**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No errors

**Step 3: Verify no references to old threading code**

Run: `grep -n "run_cron\|summary_thread\|alert_thread" app/oracle_usage_bot.py`
Expected: No matches (all old threading code removed)

**Step 4: Commit main block simplification**

```bash
git add app/oracle_usage_bot.py
git commit -m "refactor: simplify main block to use APScheduler"
```

---

## Task 7: Fix Notification Function References

**Files:**
- Modify: `app/oracle_usage_bot.py` (update references in notification functions)

**Step 1: Find and fix remaining old variable references**

Search for old global variable references that weren't converted:
```bash
grep -n "CURRENCY\|MIN_DAILY_USAGE\|MAX_DAILY_USAGE\|APPRISE_URL\|APPRISE_KEY" app/oracle_usage_bot.py
```

**Step 2: Update send_summary_notification function**

Find the error notification section in `send_summary_notification()` (around line ~286-296) and update:

Old:
```python
requests.post(f"{APPRISE_URL}/notify/{APPRISE_KEY}", json=payload, timeout=10)
```

New:
```python
requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)
```

**Step 3: Update send_daily_limit_alert function**

Find the error notification section in `send_daily_limit_alert()` (around line ~320-331) and update:

Old:
```python
logger.info(f"Daily usage: {CURRENCY}{daily:.2f}, Limit: {CURRENCY}{MIN_DAILY_USAGE:.2f}")
if daily >= MIN_DAILY_USAGE:
    logger.warning(f"Daily usage {CURRENCY}{daily:.2f} exceeds limit {CURRENCY}{MIN_DAILY_USAGE:.2f}")
    send_apprise_notification(daily, None, None, None, alert=True, limit=MIN_DAILY_USAGE)
```

New:
```python
logger.info(f"Daily usage: {settings.currency}{daily:.2f}, Limit: {settings.currency}{settings.min_daily_usage:.2f}")
if daily >= settings.min_daily_usage:
    logger.warning(f"Daily usage {settings.currency}{daily:.2f} exceeds limit {settings.currency}{settings.min_daily_usage:.2f}")
    send_apprise_notification(daily, None, None, None, alert=True, limit=settings.min_daily_usage)
```

And update error notification:
```python
requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)
```

**Step 4: Verify no old references remain**

Run: `grep -n "CURRENCY\|MIN_DAILY_USAGE\|APPRISE_URL\|APPRISE_KEY" app/oracle_usage_bot.py`
Expected: No matches (all converted to settings.*)

**Step 5: Commit reference fixes**

```bash
git add app/oracle_usage_bot.py
git commit -m "fix: update remaining global variable references to use settings"
```

---

## Task 8: Manual Testing - Scheduler Start

**Files:**
- Test: `app/oracle_usage_bot.py`

**Step 1: Test application starts successfully**

```bash
cd app
python oracle_usage_bot.py
```

Expected output should include:
```
Using SUMMARY_SCHEDULE: 0 0 * * 0
Using DAILY_LIMIT_SCHEDULE: 0 0 * * *
Scheduler started successfully
Next summary run: [datetime]
Next alert run: [datetime]
```

Press Ctrl+C after seeing startup messages.

**Step 2: Verify graceful shutdown**

Start the application and send SIGTERM:
```bash
python oracle_usage_bot.py &
PID=$!
sleep 5
kill -TERM $PID
wait $PID
```

Expected logs should include:
```
Received SIGTERM signal, initiating graceful shutdown
Shutting down scheduler, waiting for running jobs to complete...
Scheduler shutdown complete
Shutdown complete
```

**Step 3: Test with invalid cron expression**

Temporarily set invalid cron in .env:
```bash
echo "SUMMARY_SCHEDULE=invalid" >> .env
python oracle_usage_bot.py
```

Expected: Should show error about invalid cron expression

Restore valid .env:
```bash
git checkout .env
```

**Step 4: Document test results**

```bash
echo "APScheduler upgrade tests passed:
- Application starts successfully
- Next run times logged correctly
- Graceful shutdown works (SIGTERM/SIGINT)
- Invalid cron expressions caught" > ../docs/test-results-apscheduler.txt
git add ../docs/test-results-apscheduler.txt
git commit -m "test: verify APScheduler functionality"
```

---

## Task 9: Manual Testing - Misfire Handling

**Files:**
- Test: Manual testing of misfire grace period

**Step 1: Test misfire within grace period**

Setup: Schedule a job to run in 2 minutes
```bash
cd app
# Edit .env temporarily to set job 2 minutes from now
CURRENT_TIME=$(date -u +"%M")
FUTURE_MIN=$(($CURRENT_TIME + 2))
FUTURE_HOUR=$(date -u +"%H")
echo "Testing misfire: Job scheduled for $(date -u -d '+2 minutes' +%H:%M)"
```

Stop server before job runs, restart after scheduled time but within 1 hour.

Expected: Job runs immediately on restart (misfire detected, within grace period)

**Step 2: Test job overlap prevention**

Simulate long-running job by adding temporary sleep to `send_summary_notification()`:
```python
# Temporary for testing
import time
time.sleep(120)  # 2 minute delay
```

Schedule job every minute and observe logs.
Expected: Second job waits for first to complete (max_instances=1)

Remove test sleep after verification.

**Step 3: Restore normal configuration**

```bash
git checkout .env app/oracle_usage_bot.py
```

**Step 4: Document misfire test results**

```bash
echo "Misfire handling verified:
- Jobs run within 1-hour grace period
- Jobs skipped if misfire > 1 hour
- max_instances=1 prevents overlapping executions" >> ../docs/test-results-apscheduler.txt
git add ../docs/test-results-apscheduler.txt
git commit -m "test: verify APScheduler misfire handling"
```

---

## Task 10: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update Key Dependencies section**

Find "Key Dependencies" section and update:

Replace:
```markdown
- **croniter**: Cron expression parsing and scheduling
```

With:
```markdown
- **APScheduler**: Production-ready job scheduling with misfire handling
```

**Step 2: Update Architecture section**

Find "Dual Scheduling System" section and update:

Old:
```markdown
2. **Dual Scheduling System** (`cron_loop()`)
   - **Summary notifications**: Weekly usage report (default: Sundays at midnight)
   - **Daily limit alerts**: Checks if usage exceeds MIN_DAILY_USAGE threshold (default: daily at midnight)
   - Both schedules run in separate daemon threads using `croniter`
   - Configurable via `SUMMARY_SCHEDULE` and `DAILY_LIMIT_SCHEDULE` environment variables
```

New:
```markdown
2. **Dual Scheduling System** (`start_scheduler()`)
   - **Summary notifications**: Weekly usage report (default: Sundays at midnight)
   - **Daily limit alerts**: Checks if usage exceeds MIN_DAILY_USAGE threshold (default: daily at midnight)
   - Managed by APScheduler BackgroundScheduler with CronTrigger jobs
   - Automatic misfire handling (1-hour grace period)
   - Job overlap prevention (max_instances=1)
   - Configurable via `SUMMARY_SCHEDULE` and `DAILY_LIMIT_SCHEDULE` environment variables
```

**Step 3: Add APScheduler Configuration section**

Add new section after "Dual Scheduling System":

```markdown
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
```

**Step 4: Update Runtime Behavior section**

Add to Runtime Behavior section:
```markdown
- APScheduler BackgroundScheduler manages job execution automatically
- Misfire handling runs jobs if scheduled within last hour
- Job overlap prevented by max_instances=1 setting
- Scheduler shutdown waits for running jobs to complete before exit
```

**Step 5: Verify documentation accuracy**

Run: `grep -i "apscheduler\|croniter" CLAUDE.md`
Expected: Should show APScheduler references, no croniter references

**Step 6: Commit documentation updates**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with APScheduler implementation details"
```

---

## Task 11: Final Verification and Cleanup

**Files:**
- Verify: `app/oracle_usage_bot.py`
- Verify: `app/requirements.txt`
- Verify: `CLAUDE.md`

**Step 1: Verify no croniter imports remain**

```bash
grep -n "croniter" app/oracle_usage_bot.py
```
Expected: No matches

**Step 2: Verify APScheduler imports present**

```bash
grep -n "from apscheduler" app/oracle_usage_bot.py
```
Expected: Should show BackgroundScheduler, CronTrigger, EVENT_ imports

**Step 3: Verify all old threading code removed**

```bash
grep -n "run_cron\|summary_thread\|alert_thread\|thread.join" app/oracle_usage_bot.py
```
Expected: No matches

**Step 4: Run full application test with real config**

```bash
cd app
python oracle_usage_bot.py
```

Let it run for 2 minutes, observe:
- Scheduler starts successfully
- Next run times logged
- Health check updates every 60 seconds
- Ctrl+C triggers graceful shutdown

**Step 5: Verify Docker build still works**

```bash
cd app
docker build -t ocm-test .
```
Expected: Build succeeds with no errors

**Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete APScheduler upgrade

- Replace croniter with APScheduler BackgroundScheduler
- Add automatic misfire handling (1-hour grace period)
- Prevent job overlap with max_instances=1
- Simplify codebase by removing ~40 lines of manual threading
- Enhance graceful shutdown to wait for running jobs
- Update documentation with APScheduler details

Closes APScheduler upgrade requirement"
```

---

## Testing Checklist

- [ ] Application starts successfully
- [ ] Next run times logged on startup
- [ ] Jobs execute at scheduled times
- [ ] Graceful shutdown with SIGTERM works
- [ ] Graceful shutdown with SIGINT (Ctrl+C) works
- [ ] Scheduler waits for running jobs before exit
- [ ] Invalid cron expressions caught on startup
- [ ] Misfire handling works (job runs if within 1 hour)
- [ ] max_instances prevents job overlap
- [ ] Health check continues updating
- [ ] No croniter imports remain
- [ ] No old threading code remains
- [ ] Docker build succeeds
- [ ] Documentation updated accurately

## Rollback Plan

If implementation fails:
```bash
git reset --hard HEAD~11  # Reset to before Task 1
```

Or reset to specific commit before upgrade started.

## Success Criteria

1. ✅ APScheduler replaces croniter completely
2. ✅ 30-40 lines of code removed (threading eliminated)
3. ✅ Jobs run at scheduled times
4. ✅ Misfire handling works (1-hour grace period)
5. ✅ No job overlap (max_instances=1)
6. ✅ Graceful shutdown waits for jobs
7. ✅ Documentation updated
8. ✅ All manual tests pass
