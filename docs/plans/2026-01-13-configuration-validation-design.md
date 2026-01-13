# Configuration Validation Design - Pydantic Implementation

**Date**: 2026-01-13
**Status**: Validated
**Implementation Priority**: High (Medium effort, High impact, Low risk)

## Overview

Implement strict configuration validation using Pydantic BaseSettings to catch configuration errors immediately on startup rather than during scheduled execution.

## Goals

1. **Fail Fast**: Validate all configuration at startup, exit immediately with clear errors
2. **Type Safety**: Automatic type validation and conversion for all configuration fields
3. **Clear Errors**: Show exactly which fields are missing or invalid
4. **Minimal Refactoring**: Maintain single-file architecture, minimal changes to existing code

## Configuration Structure

### Required Fields (Application exits if missing)

**Oracle Cloud API:**
- `oci_user_ocid`: str - User OCID for Oracle Cloud API authentication
- `oci_tenancy_ocid`: str - Tenancy OCID
- `oci_fingerprint`: str - API key fingerprint
- `oci_region`: str - Oracle Cloud region (e.g., "us-ashburn-1")

**Apprise Notifications:**
- `apprise_url`: HttpUrl - Apprise server URL (validates HTTP/HTTPS format automatically)
- `apprise_key`: str - Configuration key from Apprise web UI

### Optional Fields (Sensible defaults provided)

**Usage Thresholds:**
- `min_daily_usage`: float = 0.0 - Minimum usage to trigger alerts
- `max_daily_usage`: float = 0.0 - Maximum usage threshold
- `currency`: str = "$" - Currency symbol for notifications

**Scheduling:**
- `summary_schedule`: str = "0 0 * * 0" - Cron expression for weekly summaries (default: Sundays midnight)
- `daily_limit_schedule`: str = "0 0 * * *" - Cron expression for daily checks (default: daily midnight)

**Operational:**
- `log_level`: str = "INFO" - Logging level (DEBUG/INFO/WARNING/ERROR)

## Implementation Approach

### 1. Pydantic Settings Class

```python
from pydantic import BaseSettings, HttpUrl, validator, ValidationError

class Settings(BaseSettings):
    # Required Oracle Cloud fields
    oci_user_ocid: str
    oci_tenancy_ocid: str
    oci_fingerprint: str
    oci_region: str

    # Required Apprise fields
    apprise_url: HttpUrl
    apprise_key: str

    # Optional with defaults
    min_daily_usage: float = 0.0
    max_daily_usage: float = 0.0
    currency: str = "$"
    summary_schedule: str = "0 0 * * 0"
    daily_limit_schedule: str = "0 0 * * *"
    log_level: str = "INFO"

    @validator('log_level')
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f'must be one of: {valid_levels}')
        return v_upper

    class Config:
        env_file = '.env'
        case_sensitive = False
```

### 2. Validation Logic

**Automatic Validations:**
- `HttpUrl` type validates URL format for `apprise_url`
- Required fields automatically checked by Pydantic
- Type conversions (str to float) handled automatically

**Custom Validators:**
- Log level validator: ensures value is in [DEBUG, INFO, WARNING, ERROR], converts to uppercase

**Error Format:**
- One error message per invalid field
- Shows field name and specific problem
- Final summary message guides user to fix and restart

### 3. Startup Error Handling

```python
try:
    settings = Settings()
except ValidationError as e:
    for error in e.errors():
        field = error['loc'][0]
        msg = error['msg']
        logger.error(f"Configuration Error - {field}: {msg}")
    logger.error("Configuration validation failed. Fix issues above and restart.")
    sys.exit(1)
```

**Error Flow:**
1. Application starts
2. Settings initialization attempts to load .env
3. Pydantic validates all fields
4. If validation fails: log each error, exit with status 1
5. If validation succeeds: proceed to credential check

### 4. Integration with Existing Code

**Replace Global Variables:**

Before:
```python
config = {
    "user": os.getenv("OCI_USER_OCID"),
    ...
}
APPRISE_URL = os.getenv("APPRISE_URL")
APPRISE_KEY = os.getenv("APPRISE_KEY")
```

After:
```python
settings = Settings()  # With error handling

config = {
    "user": settings.oci_user_ocid,
    "fingerprint": settings.oci_fingerprint,
    "tenancy": settings.oci_tenancy_ocid,
    "region": settings.oci_region,
    "key_file": "./key.pem",
}
```

**Function Updates:**
- Reference `settings.apprise_url` instead of `APPRISE_URL`
- Reference `settings.min_daily_usage` instead of `MIN_DAILY_USAGE`
- No function signature changes needed

**Logging Configuration:**
- Move logging setup AFTER settings initialization
- Use `settings.log_level` for configuration

## Dependencies

**New Dependency:**
- `pydantic>=2.0` - Add to requirements.txt

**Pydantic 2.0+ Features Used:**
- BaseSettings for environment variable management
- HttpUrl for automatic URL validation
- ValidationError for structured error handling
- @validator decorator for custom validation

## Migration Steps

1. **Add dependency**: Update `app/requirements.txt` with pydantic
2. **Create Settings class**: Add to top of `oracle_usage_bot.py` after imports
3. **Initialize with error handling**: Wrap Settings() in try/except
4. **Replace variables**: Update all `os.getenv()` calls and global variables to use `settings.*`
5. **Move logging config**: Setup logging after settings initialization
6. **Test validation**:
   - Missing required field (should fail with clear error)
   - Invalid URL format (should fail with URL error)
   - Invalid log level (should fail with level error)
   - Valid configuration (should start normally)

## Testing Strategy

**Invalid Configuration Tests:**
1. Remove `OCI_USER_OCID` → Should show "field required" error
2. Set `APPRISE_URL=invalid` → Should show "invalid URL format" error
3. Set `LOG_LEVEL=TRACE` → Should show "must be one of: DEBUG, INFO, WARNING, ERROR"
4. Set `MIN_DAILY_USAGE=abc` → Should show type conversion error

**Valid Configuration Tests:**
1. All required fields set → Should start successfully
2. Optional fields omitted → Should use defaults
3. Mixed case env vars (oci_user_ocid vs OCI_USER_OCID) → Should work (case insensitive)

## Benefits

1. **Immediate Feedback**: Configuration errors caught at startup, not during scheduled execution
2. **Type Safety**: Prevents runtime type errors (e.g., invalid float conversion)
3. **Better DX**: IDE autocomplete and type hints with settings object
4. **Clear Errors**: Users know exactly what to fix
5. **Maintainability**: Centralized configuration management
6. **Production Ready**: Industry standard approach (used by FastAPI, many modern Python apps)

## Trade-offs

**Pros:**
- Strong type safety and validation
- Industry standard library (Pydantic)
- Excellent error messages
- Future-proof (widely adopted in 2026)

**Cons:**
- Adds one new dependency (pydantic)
- Minor refactoring needed (~30 lines changed)
- Slightly more complex than simple os.getenv() calls

**Decision**: Benefits far outweigh the minimal cost of one dependency.

## References

- [Pydantic BaseSettings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Pydantic V2 Migration Guide](https://docs.pydantic.dev/latest/migration/)
- Research: Python configuration validation best practices 2026
