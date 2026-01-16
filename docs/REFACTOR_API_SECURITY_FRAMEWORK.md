# API Security Framework Refactoring Plan

## Current State

`api_security_framework.py` is a 2270-line "god module" mixing multiple concerns:
- Frappe whitelist/decorator integration
- Authorization engine
- Rate limiting
- Audit logging
- Input validation
- Self-service access control
- Critical operation integration
- Environment validation
- Convenience decorators

## Target Architecture

Split into focused modules with clear boundaries:

```
verenigingen/utils/security/
├── __init__.py                      # Re-export public API (backwards compat)
├── api_security_framework.py        # Orchestration only (~300 lines)
├── authorization_engine.py          # Auth decisions (~250 lines)
├── rate_limit_engine.py             # Rate limiting (~300 lines)
├── frappe_whitelist_adapter.py      # Frappe integration (~200 lines)
├── audit_emitter.py                 # Audit logging (~150 lines)
├── input_validator.py               # Input sanitization (~150 lines)
├── self_service_access.py           # Self-service checks (~150 lines)
├── environment_validator.py         # Environment checks (~100 lines)
└── decorators.py                    # Convenience decorators (~200 lines)
```

## Module Responsibilities

### 1. `authorization_engine.py` (~250 lines)

**Responsibility:** Authorization decisions only

```python
class AuthorizationEngine:
    """
    Single source of truth for authorization decisions.

    Decision Table:
    1. PUBLIC → allow
    2. Guest → deny
    3. LOW → any authenticated
    4. Role Profile match → allow
    5. Individual role match → allow
    6. System Manager + MEDIUM → allow
    7. Default → deny
    """

    ROLE_PROFILE_SECURITY_MAPPING = {...}  # Move from APISecurityFramework

    def authorize(self, user: str, level: SecurityLevel) -> AuthResult
    def get_user_role_profiles(self, user: str) -> List[str]
    def invalidate_cache(self, user: str = None)
```

**Dependencies:** None (pure authorization logic)

### 2. `rate_limit_engine.py` (~300 lines)

**Responsibility:** Rate limiting with COR integration

```python
class RateLimitEngine:
    """Atomic rate limiting with Redis."""

    def check_rate_limit(self, operation_key: str, context: ExecutionContext) -> RateLimitResult
    def get_cor_config(self, operation_name: str) -> Optional[Dict]
    def get_rate_limit_headers(self, operation_key: str) -> Dict[str, str]
```

**Dependencies:** Redis cache, COR DocType

### 3. `frappe_whitelist_adapter.py` (~200 lines)

**Responsibility:** Frappe whitelist registration and HTTP method handling

```python
class FrappeWhitelistAdapter:
    """
    Adapter for Frappe's whitelist system.

    Handles:
    - Wrapper registration in frappe.whitelisted
    - HTTP method configuration
    - Attribute preservation from inner functions
    """

    def register_wrapper(self, wrapper: Callable, inner: Callable, http_methods: List[str])
    def preserve_attributes(self, wrapper: Callable, inner: Callable)
    def get_effective_http_methods(self, func: Callable) -> List[str]
```

**Dependencies:** frappe.whitelisted, frappe.allowed_http_methods_for_whitelisted_func

### 4. `audit_emitter.py` (~150 lines)

**Responsibility:** Security audit event emission

```python
class AuditEmitter:
    """Emit security audit events consistently."""

    def log_access_granted(self, user: str, operation: str, auth_path: str)
    def log_access_denied(self, user: str, operation: str, reason: str)
    def log_rate_limit_exceeded(self, user: str, operation: str)
    def log_validation_failure(self, user: str, operation: str, errors: List[str])
```

**Dependencies:** audit_logging module

### 5. `input_validator.py` (~150 lines)

**Responsibility:** Input data validation and sanitization

```python
class InputValidator:
    """Validate and sanitize API input data."""

    def validate(self, data: Any, max_size: int) -> Any
    def validate_dict(self, data: Dict, max_length: int) -> Dict
    def validate_list(self, data: List, max_length: int) -> List
```

**Dependencies:** None (pure validation)

### 6. `self_service_access.py` (~150 lines)

**Responsibility:** Self-service access control

```python
class SelfServiceAccessController:
    """Control self-service member access."""

    def validate_access(self, user: str, **kwargs) -> bool
    def validate_request_content(self, user_member: str, **kwargs) -> bool
```

**Dependencies:** Member DocType

### 7. `environment_validator.py` (~100 lines)

**Responsibility:** Environment-based access control

```python
class EnvironmentValidator:
    """Validate deployment environment access."""

    def get_current_environment(self) -> EnvironmentLevel
    def validate_access(self, required_env: EnvironmentLevel) -> bool
```

**Dependencies:** frappe.conf

### 8. `decorators.py` (~200 lines)

**Responsibility:** Convenience decorator definitions

```python
# Simple wrappers around api_security_framework()
def critical_api(...): ...
def high_security_api(...): ...
def standard_api(...): ...
def utility_api(...): ...
def public_api(...): ...
def webhook_api(...): ...
```

**Dependencies:** api_security_framework

### 9. `api_security_framework.py` (Orchestrator, ~300 lines)

**Responsibility:** Orchestration and public API

```python
class APISecurityFramework:
    """
    Orchestrates security components.

    This is the main entry point. It coordinates:
    - Authorization (via AuthorizationEngine)
    - Rate limiting (via RateLimitEngine)
    - Audit logging (via AuditEmitter)
    - Input validation (via InputValidator)
    """

    def __init__(self):
        self.auth_engine = AuthorizationEngine()
        self.rate_limiter = RateLimitEngine()
        self.audit = AuditEmitter()
        self.input_validator = InputValidator()
        self.whitelist_adapter = FrappeWhitelistAdapter()

    def validate_request(self, profile: SecurityProfile) -> bool:
        """Main validation entry point."""
        ...

def api_security_framework(...):
    """Main decorator - orchestrates all security checks."""
    ...
```

## Migration Strategy

### Phase 1: Extract Pure Logic (Low Risk)
1. Extract `InputValidator` (no dependencies)
2. Extract `EnvironmentValidator` (minimal dependencies)
3. Add re-exports in `__init__.py` for backwards compatibility

### Phase 2: Extract Auth & Rate Limiting (Medium Risk)
4. Extract `AuthorizationEngine` (cache logic, role profiles)
5. Extract `RateLimitEngine` (COR integration, Redis)
6. Update `APISecurityFramework` to use new classes

### Phase 3: Extract Frappe Integration (Higher Risk)
7. Extract `FrappeWhitelistAdapter` (Frappe internals)
8. Extract `AuditEmitter`
9. Extract `SelfServiceAccessController`

### Phase 4: Finalize (Cleanup)
10. Extract `decorators.py`
11. Slim down `api_security_framework.py` to orchestrator
12. Update all imports across codebase
13. Comprehensive test suite for each module

## Backwards Compatibility

Maintain backwards compatibility via `__init__.py`:

```python
# verenigingen/utils/security/__init__.py

# Re-export everything for backwards compatibility
from .api_security_framework import (
    APISecurityFramework,
    api_security_framework,
    get_security_framework,
    SecurityProfile,
)
from .decorators import (
    critical_api,
    high_security_api,
    standard_api,
    utility_api,
    public_api,
    webhook_api,
)
from .authorization_engine import AuthorizationEngine
from .rate_limit_engine import RateLimitEngine

# Deprecated aliases (remove in v3.0)
# None needed if we keep same names
```

## Testing Strategy

Each new module gets its own test file:
- `test_authorization_engine.py`
- `test_rate_limit_engine.py`
- `test_frappe_whitelist_adapter.py`
- `test_input_validator.py`
- etc.

The existing `test_api_security_framework.py` becomes an integration test suite.

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| 1 | Low | Pure functions, easy rollback |
| 2 | Medium | Caching logic - extensive testing |
| 3 | Higher | Frappe internals - careful testing |
| 4 | Low | Just moving code, tests verify |

## Estimated Effort

- Phase 1: 2-3 hours
- Phase 2: 4-6 hours
- Phase 3: 4-6 hours
- Phase 4: 2-3 hours
- Total: ~15-20 hours

## Success Criteria

1. All existing tests pass
2. No public API changes (backwards compatible)
3. Each module < 300 lines
4. Each module has single responsibility
5. Clear dependency graph (no cycles)
6. Performance unchanged (benchmark before/after)

## Not In Scope

- Changing the authorization model
- Changing the rate limiting algorithm
- Changing the decorator API
- Breaking backwards compatibility

This refactor is purely structural - same behavior, better organization.
