# Pydantic Configuration Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace scattered `os.getenv()` calls with Pydantic BaseSettings for strict configuration validation that fails fast on startup with clear error messages.

**Architecture:** Single Settings class using Pydantic BaseSettings handles all environment variable loading and validation. Application fails immediately on startup if required fields are missing or invalid. Minimal refactoring maintains single-file architecture.

**Tech Stack:** Pydantic 2.x, Python logging, dotenv

---

## Task 1: Add Pydantic Dependency

**Files:**
- Modify: `app/requirements.txt`

**Step 1: Add pydantic to requirements**

Add this line to `app/requirements.txt`:
```
pydantic>=2.0,<3.0
pydantic-settings>=2.0,<3.0
```

**Step 2: Verify requirements file**

Run: `cat app/requirements.txt`
Expected: Should show pydantic and pydantic-settings added

**Step 3: Commit dependency addition**

```bash
git add app/requirements.txt
git commit -m "feat: add pydantic for configuration validation"
```

---

## Task 2: Create Settings Class Structure

**Files:**
- Modify: `app/oracle_usage_bot.py:1-50`

**Step 1: Add pydantic imports after existing imports**

Add after line 12 (after `from croniter import croniter`):
```python
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

**Step 2: Remove old environment loading (lines 30-44)**

Remove these lines:
```python
config = {
    "user": os.getenv("OCI_USER_OCID"),
    "key_file": "./key.pem",
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_OCID"),
    "region": os.getenv("OCI_REGION"),
}

APPRISE_URL = os.getenv("APPRISE_URL")
APPRISE_KEY = os.getenv("APPRISE_KEY")
MIN_DAILY_USAGE = float(os.getenv("MIN_DAILY_USAGE", 0))
MAX_DAILY_USAGE = float(os.getenv("MAX_DAILY_USAGE", 0))
CURRENCY = os.getenv("CURRENCY", "$")

SUMMARY_SCHEDULE = os.getenv("SUMMARY_SCHEDULE")
DAILY_LIMIT_SCHEDULE = os.getenv("DAILY_LIMIT_SCHEDULE")
```

**Step 3: Create Settings class after load_dotenv() call**

Add after line 14 (after `load_dotenv()`):
```python

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
```

**Step 4: Verify file compiles**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No output (compilation successful)

**Step 5: Commit Settings class**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: create Pydantic Settings class for configuration"
```

---

## Task 3: Add Settings Initialization with Error Handling

**Files:**
- Modify: `app/oracle_usage_bot.py` (after Settings class definition)

**Step 1: Move LOG_LEVEL and logging configuration**

Remove old logging configuration (lines 16-23):
```python
# Configure structured logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
```

**Step 2: Initialize settings with error handling**

Add after Settings class definition:
```python

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
```

**Step 3: Verify error handling works**

Test with missing env var:
```bash
cd app
unset OCI_USER_OCID
python oracle_usage_bot.py
```
Expected: Should print "Configuration validation failed" with field error

**Step 4: Commit initialization**

```bash
git add app/oracle_usage_bot.py
git commit -m "feat: add settings initialization with error handling"
```

---

## Task 4: Replace Global Variable References (Part 1 - Functions)

**Files:**
- Modify: `app/oracle_usage_bot.py` (functions: `send_apprise_notification`, `get_cron_schedules`)

**Step 1: Update send_apprise_notification function**

Replace references in `send_apprise_notification()` function:
- Line ~145: `if not APPRISE_URL or not APPRISE_KEY:` → `if not settings.apprise_url or not settings.apprise_key:`
- Line ~151: `body += f"Your daily usage is higher than your limit {CURRENCY}{limit:.2f}!\n\n"` → `body += f"Your daily usage is higher than your limit {settings.currency}{limit:.2f}!\n\n"`
- Line ~152: `body += f"Daily Usage: {CURRENCY}{daily:.2f}"` → `body += f"Daily Usage: {settings.currency}{daily:.2f}"`
- Line ~157: `body += f"📊 Daily Usage: {CURRENCY}{daily:.2f}\n"` → `body += f"📊 Daily Usage: {settings.currency}{daily:.2f}\n"`
- Line ~158: `body += f"📅 Weekly: {CURRENCY}{weekly:.2f}\n"` → `body += f"📅 Weekly: {settings.currency}{weekly:.2f}\n"`
- Line ~159: `body += f"📆 Monthly: {CURRENCY}{monthly:.2f}\n"` → `body += f"📆 Monthly: {settings.currency}{monthly:.2f}\n"`
- Line ~160: `body += f"📈 Annually: {CURRENCY}{yearly:.2f}"` → `body += f"📈 Annually: {settings.currency}{yearly:.2f}"`
- Line ~162: `apprise_endpoint = f"{APPRISE_URL}/notify/{APPRISE_KEY}"` → `apprise_endpoint = f"{settings.apprise_url}/notify/{settings.apprise_key}"`
- Line ~203: `requests.post(f"{APPRISE_URL}/notify/{APPRISE_KEY}", json=payload, timeout=10)` → `requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)`
- Line ~237: `requests.post(f"{APPRISE_URL}/notify/{APPRISE_KEY}", json=payload, timeout=10)` → `requests.post(f"{settings.apprise_url}/notify/{settings.apprise_key}", json=payload, timeout=10)`

**Step 2: Update get_cron_schedules function**

Replace references in `get_cron_schedules()` function:
- Line ~38: `summary = SUMMARY_SCHEDULE or default_summary_cron` → `summary = settings.summary_schedule or default_summary_cron`
- Line ~39: `daily_limit = DAILY_LIMIT_SCHEDULE or default_alert_cron` → `daily_limit = settings.daily_limit_schedule or default_alert_cron`

**Step 3: Verify syntax**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No errors

**Step 4: Commit function updates**

```bash
git add app/oracle_usage_bot.py
git commit -m "refactor: use settings object in notification and schedule functions"
```

---

## Task 5: Replace Global Variable References (Part 2 - Notification Functions)

**Files:**
- Modify: `app/oracle_usage_bot.py` (functions: `send_summary_notification`, `send_daily_limit_alert`)

**Step 1: Update send_summary_notification function**

Replace all CURRENCY references with settings.currency:
- Line ~206: `logger.info(f"Daily usage fetched: {CURRENCY}{daily:.2f}")` → `logger.info(f"Daily usage fetched: {settings.currency}{daily:.2f}")`
- Line ~211: `logger.info(f"Weekly usage fetched: {CURRENCY}{weekly:.2f}")` → `logger.info(f"Weekly usage fetched: {settings.currency}{weekly:.2f}")`
- Line ~216: `logger.info(f"Monthly usage fetched: {CURRENCY}{monthly:.2f}")` → `logger.info(f"Monthly usage fetched: {settings.currency}{monthly:.2f}")`
- Line ~221: `logger.info(f"Yearly usage fetched: {CURRENCY}{yearly:.2f}")` → `logger.info(f"Yearly usage fetched: {settings.currency}{yearly:.2f}")`

**Step 2: Update send_daily_limit_alert function**

Replace MIN_DAILY_USAGE references with settings.min_daily_usage:
- Line ~253: `logger.info(f"Daily usage: {CURRENCY}{daily:.2f}, Limit: {CURRENCY}{MIN_DAILY_USAGE:.2f}")` → `logger.info(f"Daily usage: {settings.currency}{daily:.2f}, Limit: {settings.currency}{settings.min_daily_usage:.2f}")`
- Line ~255: `if daily >= MIN_DAILY_USAGE:` → `if daily >= settings.min_daily_usage:`
- Line ~256: `logger.warning(f"Daily usage {CURRENCY}{daily:.2f} exceeds limit {CURRENCY}{MIN_DAILY_USAGE:.2f}")` → `logger.warning(f"Daily usage {settings.currency}{daily:.2f} exceeds limit {settings.currency}{settings.min_daily_usage:.2f}")`
- Line ~257: `send_apprise_notification(daily, None, None, None, alert=True, limit=MIN_DAILY_USAGE)` → `send_apprise_notification(daily, None, None, None, alert=True, limit=settings.min_daily_usage)`

**Step 3: Verify syntax**

Run: `python -m py_compile app/oracle_usage_bot.py`
Expected: No errors

**Step 4: Commit notification function updates**

```bash
git add app/oracle_usage_bot.py
git commit -m "refactor: use settings object in summary and alert functions"
```

---

## Task 6: Test Configuration Validation

**Files:**
- Test: Manual testing with valid/invalid configurations

**Step 1: Test missing required field**

```bash
cd app
cp ../.env .env.backup
echo "# Missing OCI_USER_OCID" > .env
python oracle_usage_bot.py
```
Expected output:
```
Configuration validation failed:
  - oci_user_ocid: Field required
```

**Step 2: Test invalid URL format**

```bash
echo "OCI_USER_OCID=test" > .env
echo "OCI_TENANCY_OCID=test" >> .env
echo "OCI_FINGERPRINT=test" >> .env
echo "OCI_REGION=test" >> .env
echo "APPRISE_URL=invalid-url" >> .env
echo "APPRISE_KEY=test" >> .env
python oracle_usage_bot.py
```
Expected output:
```
Configuration validation failed:
  - apprise_url: must start with http:// or https://
```

**Step 3: Test invalid log level**

```bash
echo "APPRISE_URL=http://test.com" > .env
echo "OCI_USER_OCID=test" >> .env
echo "OCI_TENANCY_OCID=test" >> .env
echo "OCI_FINGERPRINT=test" >> .env
echo "OCI_REGION=test" >> .env
echo "APPRISE_KEY=test" >> .env
echo "LOG_LEVEL=TRACE" >> .env
python oracle_usage_bot.py
```
Expected output:
```
Configuration validation failed:
  - log_level: must be one of: DEBUG, INFO, WARNING, ERROR
```

**Step 4: Test valid configuration**

```bash
mv .env.backup .env
python oracle_usage_bot.py
```
Expected: Should start normally and validate Oracle credentials

**Step 5: Document test results**

Create test results note:
```bash
echo "Configuration validation tests passed:
- Missing required fields detected
- Invalid URL format detected
- Invalid log level detected
- Valid configuration works" > ../docs/test-results-config-validation.txt
git add ../docs/test-results-config-validation.txt
git commit -m "test: verify configuration validation error handling"
```

---

## Task 7: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (if exists)

**Step 1: Update CLAUDE.md Configuration Flow section**

Find the "Configuration Flow" section and update:

Before:
```markdown
- Environment variables loaded via `python-dotenv` from `.env` file (root directory)
- Oracle Cloud credentials configured in `config` dict (user OCID, tenancy OCID, fingerprint, region)
```

After:
```markdown
- Environment variables loaded and validated via Pydantic `Settings` class from `.env` file (root directory)
- Configuration validation fails fast on startup with clear error messages if required fields are missing or invalid
- Oracle Cloud credentials: user OCID, tenancy OCID, fingerprint, region (all required)
- Apprise configuration: URL and key (both required, URL format validated)
```

**Step 2: Update CLAUDE.md Key Dependencies section**

Add pydantic to the dependencies list:
```markdown
- **pydantic**: Configuration validation and type safety (Python stdlib)
- **pydantic-settings**: Environment variable loading with BaseSettings
```

**Step 3: Update CLAUDE.md Runtime Behavior section**

Update the first bullet:
```markdown
- The bot validates all configuration using Pydantic on startup and exits with clear error messages if any required fields are missing or invalid
```

**Step 4: Add Configuration Validation section**

Add new section after "Configuration Flow":
```markdown
### Configuration Validation

**Validation Rules**:
- **Required fields**: OCI credentials (user, tenancy, fingerprint, region), Apprise URL and key
- **Optional fields**: thresholds, schedules, currency, log level (sensible defaults provided)
- **Type validation**: Automatic conversion and validation (float for thresholds, URL format for Apprise)
- **Custom validators**: Log level must be DEBUG/INFO/WARNING/ERROR (case insensitive)

**Error Handling**:
- Application exits immediately on startup if validation fails
- Each validation error printed to stderr with field name and specific issue
- Clear guidance message: "Please check your .env file and ensure all required fields are set"
```

**Step 5: Verify documentation accuracy**

Run: `cat CLAUDE.md | grep -A5 "Configuration Validation"`
Expected: Should show new section with validation details

**Step 6: Commit documentation updates**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Pydantic configuration validation"
```

---

## Task 8: Final Verification and Cleanup

**Files:**
- Verify: `app/oracle_usage_bot.py`
- Verify: `app/requirements.txt`
- Verify: `CLAUDE.md`

**Step 1: Search for remaining os.getenv calls**

```bash
grep -n "os.getenv" app/oracle_usage_bot.py
```
Expected: Should find no matches (all replaced with settings object)

**Step 2: Verify all imports are used**

Check that pydantic imports are used:
```bash
grep -n "ValidationError\|field_validator\|BaseSettings\|SettingsConfigDict" app/oracle_usage_bot.py
```
Expected: Should show usage of all imported items

**Step 3: Run full application test**

```bash
cd app
python oracle_usage_bot.py
```
Expected: Should start successfully with real .env configuration

**Step 4: Verify Docker build still works**

```bash
cd app
docker build -t ocm-test .
```
Expected: Build succeeds with no errors

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete Pydantic configuration validation implementation

- Add pydantic and pydantic-settings dependencies
- Create Settings class with all environment variables
- Add validators for log level and Apprise URL
- Replace all os.getenv() calls with settings object
- Implement startup validation with clear error messages
- Update documentation with validation rules

Closes configuration validation requirement"
```

---

## Testing Checklist

- [ ] Missing OCI_USER_OCID shows clear error
- [ ] Missing APPRISE_URL shows clear error
- [ ] Invalid APPRISE_URL format shows validation error
- [ ] Invalid LOG_LEVEL shows validation error with valid options
- [ ] Valid configuration starts application successfully
- [ ] All global variables replaced with settings object
- [ ] No remaining os.getenv() calls in code
- [ ] Docker build succeeds
- [ ] Documentation updated accurately

## Rollback Plan

If implementation fails:
```bash
git reset --hard HEAD~8  # Reset to before Task 1
```

## Success Criteria

1. ✅ Application validates configuration on startup
2. ✅ Clear error messages for missing/invalid fields
3. ✅ No os.getenv() calls remain in code
4. ✅ Type safety with Pydantic models
5. ✅ Documentation updated
6. ✅ All tests pass
