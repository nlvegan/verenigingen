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
├── authorization_policy.py          # Pure decision logic (~100 lines)
├── authorization_engine.py          # Auth I/O + policy (~200 lines)
├── rate_limit_engine.py             # Rate limiting (~350 lines)
├── frappe_whitelist_adapter.py      # Frappe integration (~200 lines)
├── audit_emitter.py                 # Audit logging (~150 lines)
├── input_validator.py               # Input sanitization (~150 lines)
├── self_service_access.py           # Self-service checks (~150 lines)
├── environment_validator.py         # Environment checks (~100 lines)
└── decorators.py                    # Convenience decorators (~200 lines)
```

## Dependency Graph

Explicit layering to prevent circular imports:

```
                    ┌─────────────────────────────────┐
                    │      decorators.py              │  ← Public API
                    │  api_security_framework.py      │  ← Orchestrator
                    └───────────────┬─────────────────┘
                                    │ imports
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ authorization_    │   │ rate_limit_       │   │ frappe_whitelist_ │
│ engine.py         │   │ engine.py         │   │ adapter.py        │
└────────┬──────────┘   └───────────────────┘   └───────────────────┘
         │ imports                │                       │
         ▼                        │                       │
┌───────────────────┐             │                       │
│ authorization_    │             │                       │
│ policy.py         │             │                       │
└───────────────────┘             │                       │
                                  │                       │
        ┌─────────────────────────┼───────────────────────┘
        │                         │
        ▼                         ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ audit_emitter.py  │   │ self_service_     │   │ input_validator.py│
│                   │   │ access.py         │   │ environment_      │
│                   │   │                   │   │ validator.py      │
└───────────────────┘   └───────────────────┘   └───────────────────┘
                                  │
                                  ▼
                        ┌───────────────────┐
                        │    types.py       │  ← Shared types (SecurityLevel, etc.)
                        └───────────────────┘

IMPORT RULES:
- Lower layers MUST NOT import higher layers
- Siblings at same level MAY import each other only if documented
- All modules MAY import types.py
- Only orchestrator imports frappe_whitelist_adapter
```

## Module Responsibilities

### 1a. `authorization_policy.py` (~100 lines) - NEW

**Responsibility:** Pure authorization decision logic (no I/O)

```python
@dataclass
class AuthResult:
    granted: bool
    rule_matched: str  # e.g., "rule_4_role_profile", "rule_7_deny"
    auth_path: str     # e.g., "role_profile:Verenigingen Administrator"

class AuthorizationPolicy:
    """
    Pure decision table - no Frappe, no cache, no I/O.

    INVARIANTS:
    - Deny by default (Rule 7 always exists)
    - Every decision logs auth_path for audit
    - Error categories are consistent (AuthDenied, AuthExpired, etc.)
    """

    ROLE_PROFILE_SECURITY_MAPPING = {...}

    def decide(
        self,
        level: SecurityLevel,
        user_profiles: List[str],
        user_roles: List[str],
        is_authenticated: bool
    ) -> AuthResult:
        """Pure function: inputs → decision. No side effects."""
```

**Dependencies:** types.py only (truly pure)

### 1b. `authorization_engine.py` (~200 lines)

**Responsibility:** Fetch user data, call policy, manage cache

```python
class AuthorizationEngine:
    """
    I/O layer for authorization. Fetches roles/profiles, delegates to policy.
    """

    def __init__(self, policy: AuthorizationPolicy = None, cache_backend=None):
        self.policy = policy or AuthorizationPolicy()
        self.cache = cache_backend or FrappeCache()

    def authorize(self, user: str, level: SecurityLevel) -> AuthResult:
        """Fetch user data from Frappe, delegate to policy."""
        profiles = self.get_user_role_profiles(user)
        roles = frappe.get_roles(user)
        is_auth = user != "Guest"
        return self.policy.decide(level, profiles, roles, is_auth)

    def get_user_role_profiles(self, user: str) -> List[str]
    def invalidate_cache(self, user: str = None)
```

**Dependencies:** authorization_policy.py, Frappe (for DB/cache)

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

    Components are injectable for testing and future evolution.
    """

    def __init__(
        self,
        auth_engine: AuthorizationEngine = None,
        rate_limiter: RateLimitEngine = None,
        audit: AuditEmitter = None,
        input_validator: InputValidator = None,
        whitelist_adapter: FrappeWhitelistAdapter = None,
    ):
        # Injectable components with sensible defaults
        self.auth_engine = auth_engine or AuthorizationEngine()
        self.rate_limiter = rate_limiter or RateLimitEngine()
        self.audit = audit or AuditEmitter()
        self.input_validator = input_validator or InputValidator()
        self.whitelist_adapter = whitelist_adapter or FrappeWhitelistAdapter()

    def validate_request(self, profile: SecurityProfile) -> bool:
        """Main validation entry point."""
        ...

def api_security_framework(...):
    """Main decorator - orchestrates all security checks."""
    ...
```

**Testing benefits of injection:**
```python
# Test: rate limiter denies
mock_limiter = Mock(spec=RateLimitEngine)
mock_limiter.check_rate_limit.return_value = RateLimitResult(allowed=False)
framework = APISecurityFramework(rate_limiter=mock_limiter)
# No monkeypatching needed!

# Test: auth engine returns specific path
mock_auth = Mock(spec=AuthorizationEngine)
mock_auth.authorize.return_value = AuthResult(granted=True, rule="rule_5")
framework = APISecurityFramework(auth_engine=mock_auth)
```

## Migration Strategy

### Phase 1: Extract Pure Logic + Create Façades (Low Risk)

**Goal:** Extract no-dependency modules AND create façade classes for risky extractions.

| Step | Action | Verify |
|------|--------|--------|
| 1.1 | Extract `types.py` (SecurityLevel, AuthResult, etc.) | `import types` works |
| 1.2 | Extract `InputValidator` class | Input validation tests pass |
| 1.3 | Extract `EnvironmentValidator` class | Environment tests pass |
| 1.4 | Extract `AuthorizationPolicy` (pure decision logic) | Policy unit tests pass |
| 1.5 | **Create `FrappeWhitelistAdapter` façade IN SAME FILE** | All decorator tests pass |
| 1.6 | Add re-exports in `__init__.py` | Import from package works |

**Why 1.5 matters:** The Frappe whitelist adapter is "spooky action at a distance." Creating
the façade class NOW (same file, same behavior) means Phase 3 becomes a FILE MOVE, not a
BEHAVIOR CHANGE. This dramatically reduces risk.

```python
# In api_security_framework.py (Phase 1)
class FrappeWhitelistAdapter:
    """Façade for Frappe whitelist registration. Will be moved to own file in Phase 3."""

    def register_wrapper(self, wrapper, inner, http_methods):
        # Same code that's currently inline in the decorator
        ...

    def preserve_attributes(self, wrapper, inner):
        # Same code that's currently inline
        ...

# Decorator now calls:
adapter = FrappeWhitelistAdapter()
adapter.register_wrapper(wrapper, inner, methods)
```

### Phase 2: Extract Auth & Rate Limiting (Medium Risk)

**Goal:** Extract I/O-dependent engines with injectable dependencies.

| Step | Action | Verify |
|------|--------|--------|
| 2.1 | Extract `AuthorizationEngine` (uses policy) | Auth integration tests pass |
| 2.2 | Extract `RateLimitEngine` | Rate limit tests pass |
| 2.3 | Extract `AuditEmitter` | Audit logging tests pass |
| 2.4 | Update `APISecurityFramework.__init__` for injection | Injection tests pass |
| 2.5 | Verify all existing tests still pass | Full test suite green |

### Phase 3: Extract Adapters (File Moves, Low Risk Now)

**Goal:** Move façades to own files. Behavior already verified in Phase 1.

| Step | Action | Verify |
|------|--------|--------|
| 3.1 | Move `FrappeWhitelistAdapter` to own file | Import works, tests pass |
| 3.2 | Extract `SelfServiceAccessController` | Self-service tests pass |
| 3.3 | Update imports in orchestrator | No import errors |

### Phase 4: Finalize (Cleanup)

**Goal:** Final organization and documentation.

| Step | Action | Verify |
|------|--------|--------|
| 4.1 | Extract `decorators.py` | All decorator imports work |
| 4.2 | Slim `api_security_framework.py` to orchestrator only | < 350 lines |
| 4.3 | Update all imports across codebase | `grep` shows no old imports |
| 4.4 | Add module docstrings with dependency rules | Docs complete |
| 4.5 | Comprehensive integration test suite | All tests pass |

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
3. Each module is "small enough to review" (~300 lines guideline, not hard gate)
4. Each module has single responsibility
5. Clear dependency graph (no cycles) - see diagram above
6. Performance unchanged (benchmark before/after)
7. **Invariants codified:**
   - Deny-by-default enforced in AuthorizationPolicy
   - Every auth decision includes `auth_path` for audit trail
   - Consistent error categories (AuthDenied, RateLimitExceeded, ValidationFailed)
   - No Frappe imports in pure modules (types.py, authorization_policy.py, input_validator.py)

## Not In Scope

- Changing the authorization model
- Changing the rate limiting algorithm
- Changing the decorator API
- Breaking backwards compatibility

This refactor is purely structural - same behavior, better organization.
