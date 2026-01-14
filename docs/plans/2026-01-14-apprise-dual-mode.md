# Apprise Dual-Mode Implementation Plan

**Created**: 2026-01-14
**Status**: Ready for Implementation
**Complexity**: Low (estimated 2-3 hours)

## Overview

Add support for two Apprise notification modes:
1. **Server mode** (existing): REST API calls to Apprise server
2. **Module mode** (new): Direct Python apprise library integration

This allows users to deploy the bot without running a separate Apprise server.

## Requirements

### Functional Requirements
- ✅ Explicit mode selection via `APPRISE_MODE` environment variable
- ✅ Feature parity: Both modes support identical notification types
- ✅ Multi-service support in module mode (all services receive all notifications)
- ✅ Clean abstraction: Calling code doesn't need to know which backend is used

### Non-Functional Requirements
- ✅ Simple configuration (no auto-detection magic)
- ✅ Consistent error handling across both modes
- ✅ Clear migration guide for existing deployments
- ✅ Graceful startup validation (fail fast on misconfiguration)

## Architecture Design

### Backend Abstraction Pattern

```python
from abc import ABC, abstractmethod
from apprise import Apprise, NotifyType

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


# Factory function
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
```

## Implementation Tasks

### Task 1: Update Pydantic Settings
**File**: `app/oracle_usage_bot.py` (lines ~21-83)

Add new fields to Settings class:
```python
class Settings(BaseSettings):
    # Existing fields...

    # Apprise mode selection (REQUIRED)
    apprise_mode: str = Field(..., description="Apprise mode: 'server' or 'module'")

    # Server mode settings (existing)
    apprise_url: Optional[str] = Field(None, description="Apprise server URL")
    apprise_key: Optional[str] = Field(None, description="Apprise server configuration key")

    # Module mode settings (NEW)
    apprise_services: Optional[str] = Field(None, description="Comma-separated Apprise service URLs")

    @field_validator('apprise_mode')
    @classmethod
    def validate_apprise_mode(cls, v: str) -> str:
        """Validate apprise_mode is 'server' or 'module'."""
        valid_modes = ['server', 'module']
        if v.lower() not in valid_modes:
            raise ValueError(f"apprise_mode must be one of {valid_modes}, got: {v}")
        return v.lower()

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
```

### Task 2: Add Backend Classes
**File**: `app/oracle_usage_bot.py` (after imports, before Settings)

Add the complete backend implementation (AppriseBackend, AppriseServerBackend, AppriseModuleBackend, create_apprise_backend) as shown in Architecture Design section above.

Add import:
```python
from apprise import Apprise, NotifyType
```

### Task 3: Initialize Global Backend
**File**: `app/oracle_usage_bot.py` (after settings initialization, ~line 95)

Replace existing apprise setup with:
```python
# Initialize Apprise backend based on mode
try:
    apprise_backend = create_apprise_backend(settings)
    logger.info(f"Apprise backend initialized in {settings.apprise_mode} mode")
except ValueError as e:
    logger.error(f"Failed to initialize Apprise backend: {e}")
    sys.exit(1)
```

### Task 4: Update Notification Function
**File**: `app/oracle_usage_bot.py` (lines ~220-244)

Replace `send_apprise_notification` function:
```python
def send_apprise_notification(title: str, body: str, notification_type: str) -> bool:
    """Send notification via configured Apprise backend.

    Args:
        title: Notification title
        body: Notification message
        notification_type: One of "info", "success", "warning", "failure"

    Returns:
        True if notification sent successfully
    """
    return apprise_backend.send_notification(title, body, notification_type)
```

### Task 5: Update requirements.txt
**File**: `app/requirements.txt`

Add apprise dependency:
```
oci
python-dotenv
requests
APScheduler>=3.10,<4.0
pydantic>=2.0,<3.0
pydantic-settings>=2.0,<3.0
apprise>=1.7.0,<2.0
```

### Task 6: Update env.sample
**File**: `env.sample`

Add dual-mode examples:
```bash
# ============================================================================
# Apprise Notification Configuration
# ============================================================================

# Mode selection (REQUIRED): "server" or "module"
# - server: Use Apprise server REST API (requires separate Apprise server)
# - module: Use apprise Python library directly (no server needed)
APPRISE_MODE=server

# ---------- Server Mode Settings (if APPRISE_MODE=server) ----------
# Base URL of your Apprise server
APPRISE_URL=http://apprise:8000

# Configuration key created in Apprise web interface
# This key should be configured with your notification services
APPRISE_KEY=oracle-alerts

# ---------- Module Mode Settings (if APPRISE_MODE=module) ----------
# Comma-separated list of Apprise service URLs
# Examples:
#   Discord: discord://webhook_id/webhook_token
#   Slack: slack://TokenA/TokenB/TokenC
#   Email: mailto://user:password@smtp.gmail.com
#   Multiple: discord://xxx,slack://yyy,mailto://zzz
#
# Full list of supported services: https://github.com/caronc/apprise/wiki
# APPRISE_SERVICES=discord://webhook_id/webhook_token

# ============================================================================
# Oracle Cloud Configuration
# ============================================================================
# (rest of file unchanged)
```

### Task 7: Update README.md
**File**: `README.md`

Add section after "Apprise Server Setup":

```markdown
## Notification Configuration

This bot supports two modes for sending notifications:

### Option 1: Apprise Server Mode (Recommended for Multiple Bots)

Use this if you want centralized notification management with a web UI.

1. **Deploy Apprise Server**:
   ```bash
   docker run -d -p 8000:8000 --name apprise caronc/apprise
   ```

2. **Configure Notifications**:
   - Access Apprise web UI at `http://your-apprise-server:8000`
   - Create a configuration with a memorable KEY (e.g., "oracle-alerts")
   - Add notification URLs for your services (Discord, Slack, email, etc.)

3. **Configure Bot** (`.env`):
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

1. **Find Service URLs**:
   - Visit https://github.com/caronc/apprise/wiki
   - Get URL format for your services (Discord, Slack, email, etc.)
   - Example Discord: `discord://webhook_id/webhook_token`

2. **Configure Bot** (`.env`):
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
```

### Task 8: Update CLAUDE.md
**File**: `CLAUDE.md`

Update "Apprise Notifications" section (~line 40):

```markdown
3. **Apprise Notifications** (`send_apprise_notification()`)
   - **Dual-mode support**: Server mode (REST API) or Module mode (Python library)
   - **Mode selection**: Configured via `APPRISE_MODE` environment variable
   - **Server mode**: Sends to Apprise server, which routes to configured services
   - **Module mode**: Direct service communication via apprise Python library
   - Summary reports include daily, weekly, monthly, and yearly usage with "info" type
   - Alert notifications trigger when daily usage >= MIN_DAILY_USAGE with "failure" type
   - Notification backend abstraction ensures consistent behavior across modes
```

Update "Configuration Flow" section (~line 60):

```markdown
### Configuration Flow

- Environment variables loaded via `python-dotenv` from `.env` file (root directory)
- Apprise mode selected via `APPRISE_MODE` (server or module)
- Server mode: `APPRISE_URL` and `APPRISE_KEY` required
- Module mode: `APPRISE_SERVICES` (comma-separated URLs) required
- Backend validation on startup via `create_apprise_backend()`
- Configuration errors cause immediate startup failure with clear error messages
- Oracle Cloud credentials configured in `config` dict (user OCID, tenancy OCID, fingerprint, region)
- (rest unchanged)
```

Update "Key Dependencies" section (~line 110):

```markdown
### Key Dependencies

- **oci**: Oracle Cloud Infrastructure Python SDK
- **requests**: HTTP calls for server mode Apprise API
- **apprise**: Python notification library for module mode (80+ services)
- **APScheduler**: Production-ready job scheduling with misfire handling
- **python-dotenv**: Environment variable management
- **logging**: Structured logging (Python stdlib)
- **signal**: Graceful shutdown handling (Python stdlib)
- **pathlib**: Health check file management (Python stdlib)
```

### Task 9: Manual Testing

Test both modes to ensure functionality:

**Server Mode Test**:
```bash
# Set environment variables
cat > .env << EOF
APPRISE_MODE=server
APPRISE_URL=http://apprise:8000
APPRISE_KEY=oracle-alerts
# (other vars...)
EOF

# Build and run
cd app
docker build -t ocm-bot .
docker run --env-file ../.env ocm-bot

# Expected: Logs show "Apprise backend initialized in server mode"
# Trigger notification and verify it reaches your services
```

**Module Mode Test**:
```bash
# Set environment variables
cat > .env << EOF
APPRISE_MODE=module
APPRISE_SERVICES=discord://your_webhook_id/your_webhook_token
# (other vars...)
EOF

# Build and run
cd app
docker build -t ocm-bot .
docker run --env-file ../.env ocm-bot

# Expected: Logs show "Apprise backend initialized in module mode"
# Expected: Logs show "Initialized Apprise module with 1 service(s)"
# Trigger notification and verify it reaches Discord
```

**Validation Tests**:
```bash
# Test missing APPRISE_MODE
# Expected: Validation error on startup

# Test server mode without URL/KEY
APPRISE_MODE=server
# Expected: "Server mode requires APPRISE_URL and APPRISE_KEY"

# Test module mode without APPRISE_SERVICES
APPRISE_MODE=module
# Expected: "Module mode requires APPRISE_SERVICES"

# Test invalid APPRISE_MODE
APPRISE_MODE=invalid
# Expected: "apprise_mode must be one of ['server', 'module']"

# Test invalid service URL
APPRISE_MODE=module
APPRISE_SERVICES=invalid://url
# Expected: "Invalid Apprise service URL: invalid://url"
```

### Task 10: Update Docker Compose
**File**: `docker-compose.yml`

No changes needed - environment variables are already passed through from `.env`.

Verify in comments that both modes are supported:
```yaml
services:
  ocm:
    # Oracle Cloud Monitor - supports both Apprise server and module modes
    # Configure mode via APPRISE_MODE in .env file
```

## Testing Checklist

- [ ] Server mode works with existing Apprise server setup
- [ ] Module mode sends notifications directly to services
- [ ] Invalid APPRISE_MODE fails gracefully with clear error
- [ ] Server mode without URL/KEY fails validation
- [ ] Module mode without APPRISE_SERVICES fails validation
- [ ] Invalid service URL in module mode fails gracefully
- [ ] Summary notifications work in both modes
- [ ] Alert notifications work in both modes
- [ ] Error notifications work in both modes
- [ ] Logs clearly indicate which mode is active
- [ ] Docker build succeeds with new apprise dependency
- [ ] Existing deployment can migrate by adding APPRISE_MODE=server

## Migration Impact

### Breaking Changes
- ✅ **APPRISE_MODE** is now required
- Users must add `APPRISE_MODE=server` to continue using server mode

### Migration Steps for Existing Users
1. Add `APPRISE_MODE=server` to `.env`
2. Restart container: `docker-compose --profile ocm restart`
3. Verify logs show "Apprise backend initialized in server mode"

### Estimated Migration Time
- 30 seconds (add one line, restart container)

## Success Criteria

- ✅ Both modes fully functional with feature parity
- ✅ Clean abstraction - notification calling code unchanged
- ✅ Clear error messages for configuration mistakes
- ✅ Documentation updated (README, CLAUDE.md, env.sample)
- ✅ Backward compatible migration path (just add APPRISE_MODE)
- ✅ No regression in existing server mode functionality

## Rollback Plan

If issues arise:
1. Revert all changes: `git revert <commit-hash>`
2. Rebuild Docker image
3. Restart with original configuration

Risk: **Low** - changes are additive, server mode logic unchanged

## Future Enhancements (Out of Scope)

- [ ] Hybrid mode: Try server first, fallback to module
- [ ] Per-notification-type service routing
- [ ] Configuration UI for module mode
- [ ] Notification history/logging
- [ ] Metrics on notification success/failure rates

These can be added later if needed.

## References

- Apprise Python Library: https://github.com/caronc/apprise
- Apprise Service List: https://github.com/caronc/apprise/wiki
- Current Implementation: `app/oracle_usage_bot.py:220-244`
- Settings Validation: `app/oracle_usage_bot.py:21-83`
