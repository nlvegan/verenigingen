# PSP Integration Consolidation Plan

**Created**: 2026-01-10
**Updated**: 2026-01-10
**Status**: In Progress (Phase 1 Critical Security - COMPLETED)
**Review Date**: Architecture review by 5 parallel agents
**Scope**: Mollie, Ponto, ING Checkout payment integrations

---

## Executive Summary

This document captures findings and recommendations from a comprehensive architecture review of the three Payment Service Provider (PSP) integrations in the verenigingen app. The review identified security gaps, consolidation opportunities, and technical debt that should be addressed.

### Current State Assessment

| PSP | Maturity | Architecture Quality | Key Strength | Key Concern |
|-----|----------|---------------------|--------------|-------------|
| **Mollie** | B+ (Mature) | Well-layered, comprehensive | Unified idempotency manager | Missing webhook signature validation |
| **Ponto** | 8/10 (Strong) | Enterprise-grade | JWT/JWKS webhook security + mTLS | Monolithic webhook.py (1278 lines) |
| **ING Checkout** | Production-ready | Clean, simple | IP whitelist + HMAC security | No resilience patterns |

---

## Critical Security Issues

### CRITICAL-1: Mollie Webhook Signature Validation Missing - ✅ COMPLETED

**Priority**: CRITICAL
**Effort**: 1-2 days
**Risk**: Webhook spoofing - anyone who knows the endpoint URL can trigger fake payment events
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
- Consolidated `authenticate_mollie_webhook()` in `mollie/utils/webhook_security.py`
- Function now performs 3 security steps:
  1. Rate limiting (DoS protection)
  2. HMAC-SHA256 signature validation via `verify_mollie_webhook_signature()`
  3. Webhook user context setting
- All Mollie webhook handlers updated to use consolidated authentication
- Returns validated payload for processing

**Files Modified**:
- `verenigingen/verenigingen_payments/mollie/utils/webhook_security.py` - Consolidated auth with signature validation
- `verenigingen/verenigingen_payments/mollie/api/unified_payment_api.py` - Updated handlers
- `verenigingen/verenigingen_payments/mollie/utils/relationship_manager.py` - Updated enhanced webhook

---

### CRITICAL-2: Rate Limiter Exists But Is Not Integrated - ✅ COMPLETED

**Priority**: CRITICAL
**Effort**: 1 day
**Risk**: DoS attacks on webhook endpoints
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
- Rate limiting added as STEP 0 (before expensive operations) to all webhook handlers
- HTTP 429 response handling added for all PSPs
- Multi-tier rate limiting (IP, webhook ID, global) now active

**Files Modified**:
- **Mollie**:
  - `mollie/utils/webhook_security.py` - Rate limiting in `authenticate_mollie_webhook()`
  - `mollie/api/unified_payment_api.py` - 429 handling for payment, refund, chargeback webhooks
  - `mollie/utils/relationship_manager.py` - 429 handling for enhanced webhook
- **Ponto**:
  - `ponto/api/webhook.py` - Rate limiting + 429 handling in `handle_ponto_webhook()`
- **ING Checkout**:
  - `ing_checkout/api/webhook.py` - Rate limiting + 429 handling in all 3 handlers (payment, mandate, direct_debit)

---

## High Priority Consolidation

### HIGH-1: Move Resilience Utilities to Shared Location - ✅ COMPLETED

**Priority**: HIGH
**Effort**: 1 day
**Impact**: Formalizes existing de-facto sharing, cleaner imports
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
- Created `core/resilience/__init__.py` with compatibility adapters for Mollie/Ponto interface
- Existing implementations in `core/resilience/` already contained:
  - `circuit_breaker.py` - Full CircuitBreaker class with state management
  - `retry_policy.py` - ExponentialBackoffRetry with jitter
  - `rate_limiter.py` - Rate limiting utilities
- Added decorator wrappers (`with_retry`, `with_circuit_breaker`) compatible with Mollie API
- Added `RetryConfig` and `CircuitBreakerConfig` dataclasses

**Files Modified**:
- `core/resilience/__init__.py` - Created compatibility layer
- `mollie/core/client.py` - Updated imports to use shared module
- `mollie/services/webhook_wrapper_service_unified.py` - Updated imports
- `ponto/core/ponto_client.py` - Updated imports to use shared module

---

### HIGH-2: Extract Unified Webhook Logging - ✅ COMPLETED

**Priority**: HIGH
**Effort**: 1-2 days
**Impact**: Eliminates ~95% duplicate code between Ponto and ING
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
Created `verenigingen/utils/webhook/logging.py` with unified webhook logging utilities:
- `compute_webhook_hash()` - SHA256 hash for idempotency
- `is_duplicate_webhook()` - Check for already-processed webhooks
- `create_webhook_log()` - Create Webhook Processing Log entry
- `update_webhook_log()` - Update existing log entries
- `get_webhook_log_by_hash()` - Retrieve log by hash

Both Ponto and ING Checkout now use thin wrappers that delegate to the unified module.

**Files Created/Modified**:
- Created `verenigingen/utils/webhook/__init__.py` - Package exports
- Created `verenigingen/utils/webhook/logging.py` - Unified implementation
- Updated `ponto/api/webhook.py` - `_create_webhook_log()` now calls unified module
- Updated `ing_checkout/utils/webhook_security.py` - `log_webhook()`, `compute_webhook_hash()`, `is_duplicate_webhook()` now call unified module

---

### HIGH-3: Migrate Mollie to Shared Service User Resolution - ✅ COMPLETED

**Priority**: HIGH
**Effort**: 0.5 days
**Impact**: Consistency across PSPs
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
Refactored `authenticate_mollie_webhook()` in `mollie/utils/webhook_security.py` to use the
shared `get_service_user()` utility. This provides consistent behavior with Ponto and ING Checkout:
- User validation is now handled by the shared utility
- Fallback to Administrator with audit logging
- Error handling consistent across all PSPs

**Files Modified**:
- `mollie/utils/webhook_security.py` - Now imports and uses `get_service_user()`

---

### HIGH-4: Split Ponto webhook.py (1278 lines)

**Priority**: HIGH
**Effort**: 2-3 days
**Impact**: Maintainability, testability

**Current State**:
- Single monolithic file handles 18+ event types
- Event handlers, utilities, and routing all mixed together

**Required Fix**:
```
# Split into:
ponto/api/
├── webhook.py              # Entry point, routing only (~200 lines)
├── webhook_handlers.py     # Event type handlers (~600 lines)
└── webhook_utils.py        # Extraction/parsing utilities (~200 lines)
```

---

### HIGH-5: Add Resilience Patterns to ING Checkout - ✅ COMPLETED

**Priority**: HIGH
**Effort**: 1-2 days
**Impact**: Production stability, consistent behavior across PSPs
**Depends On**: HIGH-1 (resilience utilities must be in shared location first)
**Status**: ✅ COMPLETED (2026-01-10)

**Implementation Summary**:
- Added circuit breaker protection to critical ING Checkout API operations
- PayNLClient already had basic retry via urllib3's Retry adapter
- Circuit breaker provides protection against cascading failures

**Methods Protected with Circuit Breaker**:
- `create_order()` - Payment order creation (circuit: `paynl_orders`)
- `create_mandate()` - SEPA mandate creation (circuit: `paynl_mandates`)
- `create_direct_debit()` - Direct debit execution (circuit: `paynl_directdebits`)

**Files Modified**:
- `verenigingen/verenigingen_payments/ing_checkout/client.py` - Added circuit breaker decorators

---

## Medium Priority Items

### MED-1: Adopt WebhookErrorHandler in Ponto/ING

**Priority**: MEDIUM
**Effort**: 2-3 days
**Impact**: Consistent error handling, correlation IDs for debugging

**Current State**:
- `WebhookErrorHandler` exists and is used by Mollie
- Ponto/ING use inline `try/except` with `frappe.log_error()`

**Required Fix**:
```python
# In Ponto/ING webhook handlers:
error_handler = WebhookErrorHandler("ponto_webhook", correlation_id)
result = error_handler.wrap_with_error_handling("payment_processing", process_func)
```

---

### MED-2: Create Base Idempotency Manager

**Priority**: MEDIUM
**Effort**: 2-3 days
**Impact**: DRY principle, consistent idempotency across PSPs

**Current State**:
- Mollie has sophisticated `UnifiedIdempotencyManager`
- Ponto/ING use simple hash-based checks (identical implementations)

**Required Fix**:
```python
# Create: core/idempotency/base_manager.py
class BaseIdempotencyManager:
    """Base idempotency manager using Webhook Processing Log"""

    def compute_hash(self, event_id: str, payload: str) -> str:
        return hashlib.sha256(f"{event_id}:{payload}".encode()).hexdigest()

    def is_duplicate(self, event_id: str, payload: str) -> bool:
        webhook_hash = self.compute_hash(event_id, payload)
        return frappe.db.exists("Webhook Processing Log", {"webhook_hash": webhook_hash})

# Mollie's UnifiedIdempotencyManager extends this with advanced features
```

---

### MED-3: Create Shared Exception Hierarchy

**Priority**: MEDIUM
**Effort**: 2 days
**Impact**: Consistent error handling, easier debugging

**Required Structure**:
```python
# core/exceptions/base.py
class PSPIntegrationError(Exception):
    """Base exception for all PSP integration errors."""
    def __init__(self, message: str, details: Dict = None,
                 status_code: int = None, psp_name: str = ""):
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        self.psp_name = psp_name
        super().__init__(self.message)

class PSPAuthenticationError(PSPIntegrationError): pass
class PSPRateLimitError(PSPIntegrationError):
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)
class PSPValidationError(PSPIntegrationError): pass
class PSPConfigurationError(PSPIntegrationError): pass
class PSPWebhookError(PSPIntegrationError): pass
```

---

### MED-4: Add Models to ING Checkout

**Priority**: MEDIUM
**Effort**: 2 days
**Impact**: Type safety, consistency with Mollie/Ponto

**Current State**:
- ING Checkout uses raw dicts throughout
- Mollie has `BaseModel` class hierarchy
- Ponto has dataclasses with `from_api_response()`

**Required Fix**:
- Create `ing_checkout/models.py` with dataclasses
- Models needed: `Transaction`, `Mandate`, `PaymentStatus`

---

### MED-5: Standardize Error Response Formats

**Priority**: MEDIUM
**Effort**: 1-2 days
**Impact**: API consistency

**Current State**:
- Some methods return `{"status": "error", "message": ...}` dicts
- Others raise exceptions
- Inconsistent across and within PSPs

**Required Fix**:
- Define standard: exceptions for unexpected failures, Result types for expected failures
- Document pattern in CLAUDE.md or developer guide

---

## Lower Priority / Technical Debt

### LOW-1: Remove Deprecated mollie_client.py

**Priority**: LOW
**Effort**: 1 day
**Impact**: Reduces confusion, cleaner codebase

**Current State**:
- `mollie/core/mollie_client.py` exists with deprecation warnings
- `mollie/core/client.py` is the current implementation
- Some code may still reference deprecated version

**Required Fix**:
- Search for all imports of deprecated client
- Update imports to use current client
- Remove deprecated file

---

### LOW-2: Clarify MollieConnector vs MollieClient Responsibilities

**Priority**: LOW
**Effort**: 2 days
**Impact**: Clearer architecture

**Current State**:
- `MollieConnector` in `integration/mollie_connector.py` - settlements/balances
- `MollieClient` in `core/client.py` - payments/subscriptions
- Some overlap in responsibilities

**Required Fix**:
- Document clear boundaries
- Consider merging or clearly separating concerns

---

### LOW-3: Consolidate Mollie Orchestration Paths

**Priority**: LOW
**Effort**: 1 week
**Impact**: Maintainability, reduced bugs

**Current State**:
Three overlapping orchestration mechanisms:
1. `MolliePaymentOrchestrator` (canonical)
2. `DuesPaymentProcessor`
3. `WebhookService._process_payment_webhook()`

**Required Fix**:
- Route all paths through `MolliePaymentOrchestrator`
- Keep `DuesPaymentProcessor` as thin wrapper if needed

---

### LOW-4: Make Debug Logging Conditional

**Priority**: LOW
**Effort**: 0.5 days
**Impact**: Performance, log cleanliness

**Current State**:
```python
# In webhook_service.py - logs on EVERY webhook
frappe.log_error(
    f"WEBHOOK_DEBUG: Called at {frappe.utils.now()}\n"
    f"Form dict: {frappe.form_dict}\n"
    ...
)
```

**Required Fix**:
```python
if frappe.conf.get("mollie_debug_webhooks"):
    frappe.log_error(...)
```

---

### LOW-5: Document/Consolidate Webhook Security Files

**Priority**: LOW
**Effort**: 1 day
**Impact**: Reduces confusion

**Current State**:
Three Mollie webhook security files:
- `vereinigingen/utils/webhook_security.py`
- `verenigingen_payments/mollie/utils/webhook_security.py`
- `verenigingen_payments/core/security/webhook_validator.py`

**Required Fix**:
- Document which file serves which purpose
- Consider consolidating into single authoritative location

---

### LOW-6: Create Shared Webhook Test Helpers

**Priority**: LOW
**Effort**: 3-4 days
**Impact**: Better test coverage

**Current State**:
- Mollie has `webhook_testing.py` with test utilities
- Ponto and ING have no equivalent

**Required Fix**:
```python
# utils/webhook/testing.py
class WebhookTestHelper(ABC):
    @abstractmethod
    def create_test_payload(self, **kwargs) -> dict: ...

    @abstractmethod
    def simulate_webhook_call(self, payload: dict) -> dict: ...

    def verify_idempotency(self, payload: dict) -> bool: ...
```

---

## Security Hardening (Non-Critical)

### SEC-1: Add OAuth2 Token Audit Logging for Ponto

**Priority**: MEDIUM
**Effort**: 0.5 days
**Impact**: Compliance, debugging

**Required**: Log token refresh events with timestamp and reason

---

### SEC-2: Consider HSM/Vault for Ponto Private Keys

**Priority**: LOW (production consideration)
**Effort**: 1 week
**Impact**: Enhanced key security

**Current State**: Private keys stored in Frappe encrypted text fields

---

### SEC-3: Audit All ignore_permissions=True Usage - 🔄 IN PROGRESS

**Priority**: MEDIUM
**Effort**: 1 day
**Impact**: Security documentation
**Status**: 🔄 IN PROGRESS (2026-01-10)

**Phase 1 COMPLETED - Added Webhook User Permissions**:
The "Verenigingen Webhook User" role was missing permissions for several DocTypes used during webhook processing. Added permissions to:

| DocType | Permissions Added |
|---------|------------------|
| Webhook Processing Log | create, read |
| ING Checkout Transaction | create, read, write |
| ING Checkout Mandate | create, read, write |
| Ponto Payment Link | write (already had read) |
| Ponto Payment Request | read, write |
| Ponto Sync Log | create, write (already had read) |
| SEPA Audit Log | create, read |

**Files Modified**:
- `vereinigingen_payments/doctype/webhook_processing_log/webhook_processing_log.json`
- `vereinigingen_payments/doctype/ing_checkout_transaction/ing_checkout_transaction.json`
- `vereinigingen_payments/doctype/ing_checkout_mandate/ing_checkout_mandate.json`
- `vereinigingen_payments/doctype/ponto_payment_link/ponto_payment_link.json`
- `vereinigingen_payments/doctype/ponto_payment_request/ponto_payment_request.json`
- `vereinigingen_payments/doctype/ponto_sync_log/ponto_sync_log.json`
- `vereinigingen_payments/doctype/sepa_audit_log/sepa_audit_log.json`

**Phase 2 PENDING - Remove ignore_permissions calls**:
With webhook user permissions in place, the following `ignore_permissions=True` usages can be removed:

**Can Now Remove** (webhook user has permissions):
- `ing_checkout/api/webhook.py` - mandate/transaction saves
- `ing_checkout/utils/webhook_security.py` - log_webhook() insert
- `ponto/api/webhook.py` - payment link and sync log saves
- `ponto/api/betaalverzoek_callback.py` - doc saves
- `ponto/api/payment_callback.py` - doc saves

**Must Keep** (legitimate system operations):
- Ponto Settings OAuth token saves (credential management)
- OAuth2 service token saves (no user context during OAuth flow)
- Test fixtures (need to create data without user context)

---

### SEC-4: Add Webhook Replay Protection for Ponto

**Priority**: LOW
**Effort**: 0.5 days
**Impact**: Defense in depth

**Current**: JWT expiry provides some protection
**Enhancement**: Add time-based rejection of very old webhooks beyond JWT expiry

---

### SEC-5: Add mTLS Integration Tests for Ponto

**Priority**: LOW
**Effort**: 2 days
**Impact**: Test coverage for critical security path

**Current**: Certificate handling code paths aren't tested

---

## Target Architecture

### Proposed File Structure After Consolidation

```
verenigingen/verenigingen_payments/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── base_client.py          # BasePSPClient abstract class
│   │   └── http_client.py          # ResilientHTTPClient (shared)
│   ├── exceptions/
│   │   ├── __init__.py
│   │   └── base.py                 # PSPIntegrationError hierarchy
│   ├── models/
│   │   ├── __init__.py
│   │   └── base.py                 # BasePSPModel + Amount
│   ├── resilience/
│   │   ├── __init__.py
│   │   ├── circuit_breaker.py      # Moved from mollie/utils/
│   │   ├── rate_limiter.py
│   │   ├── retry_policy.py
│   │   └── decorators.py           # @with_retry, @with_circuit_breaker
│   ├── security/
│   │   ├── __init__.py
│   │   ├── webhook_validators.py   # Base + HMAC + JWT validator classes
│   │   └── webhook_logging.py      # Shared create_webhook_log()
│   ├── idempotency/
│   │   ├── __init__.py
│   │   └── base_manager.py         # BaseIdempotencyManager
│   └── factory.py                  # PSPRegistry + PSPFactory (future)
├── mollie/
│   ├── __init__.py
│   ├── core/
│   │   ├── client.py               # MollieClient(BasePSPClient)
│   │   └── models.py               # Mollie-specific models
│   ├── exceptions/
│   │   └── __init__.py             # MollieAPIError(PSPIntegrationError)
│   ├── services/
│   │   ├── webhook_service.py
│   │   ├── payment_service.py
│   │   └── subscription_sync_service.py
│   ├── utils/
│   │   └── idempotency_manager.py  # UnifiedIdempotencyManager
│   └── api/
│       └── webhooks.py
├── ponto/
│   ├── __init__.py
│   ├── core/
│   │   ├── ponto_client.py         # PontoClient(BasePSPClient)
│   │   └── ponto_models.py
│   ├── exceptions/
│   │   └── __init__.py
│   ├── services/
│   │   ├── oauth2_service.py
│   │   ├── payment_initiation_service.py
│   │   └── transaction_import_service.py
│   ├── utils/
│   │   ├── token_manager.py
│   │   └── webhook_security.py     # JWT/JWKS validator
│   └── api/
│       ├── webhook.py              # Entry point only
│       ├── webhook_handlers.py     # Event handlers (split from monolith)
│       └── webhook_utils.py        # Utilities (split from monolith)
└── ing_checkout/
    ├── __init__.py
    ├── client.py                   # PayNLClient(BasePSPClient)
    ├── models.py                   # NEW: Transaction, Mandate dataclasses
    ├── exceptions/
    │   └── __init__.py
    ├── services/
    │   └── mandate_service.py
    ├── utils/
    │   └── webhook_security.py
    └── api/
        ├── payment.py
        ├── mandate.py
        └── webhook.py
```

---

## Dependency Graph

Some items must be completed before others. This graph shows blocking dependencies:

```
CRITICAL-1 (Mollie signatures)     ──┐
CRITICAL-2 (Rate limiter)          ──┼──► Can proceed in parallel (no deps)
SEC-3 (Audit ignore_permissions)   ──┘

HIGH-1 (Move resilience to core/)
    │
    ├──► HIGH-5 (Add resilience to ING Checkout)
    │         │
    │         └──► ING now has same resilience as Mollie/Ponto
    │
    └──► Updates imports in Mollie and Ponto

HIGH-2 (Unified webhook logging)   ──► No dependencies

HIGH-3 (Mollie service user)       ──► No dependencies

HIGH-4 (Split Ponto webhook.py)    ──► No dependencies (can parallelize)

MED-3 (Exception hierarchy)
    │
    └──► MED-1 (WebhookErrorHandler adoption)
              │
              └──► Benefits from shared exceptions

MED-2 (Base idempotency)           ──► No dependencies

MED-4 (ING models)                 ──► No dependencies

LOW-1 (Remove deprecated client)
    │
    └──► Verify no code still imports deprecated mollie_client.py

LOW-6 (Webhook test helpers)
    │
    └──► Ideally after HIGH-2 (unified logging) for consistency
```

### Key Sequencing Constraints

| Item | Must Complete First | Reason |
|------|---------------------|--------|
| HIGH-5 (ING resilience) | HIGH-1 | Can't import decorators until they're in shared location |
| MED-1 (Error handler adoption) | MED-3 | More effective with shared exception types |
| LOW-6 (Test helpers) | HIGH-2 | Should test unified logging, not three different implementations |

### Items That Can Run in Parallel

These have no dependencies and can be tackled simultaneously:
- CRITICAL-1, CRITICAL-2, SEC-3 (all security items)
- HIGH-2, HIGH-3, HIGH-4 (independent consolidation)
- MED-2, MED-4, MED-5 (independent standardization)

---

## Implementation Phases

### Phase 1: Critical Security ✅ COMPLETED
- [x] CRITICAL-1: Implement Mollie webhook signature validation
- [x] CRITICAL-2: Integrate rate limiter into all webhook endpoints
- [x] SEC-3: Audit and document all `ignore_permissions=True` usage

### Phase 2: Infrastructure Consolidation
- [x] HIGH-1: Move resilience utilities to `core/resilience/`
- [x] HIGH-5: Add resilience patterns to ING Checkout *(depends on HIGH-1)*
- [x] HIGH-2: Extract unified webhook logging
- [x] HIGH-3: Migrate Mollie to shared service user resolution
- [x] MED-3: Create shared exception hierarchy

**MED-3 Implementation Summary** (2026-01-10):
- Created `core/exceptions/__init__.py` with comprehensive PSP exception hierarchy
- Base class: `PSPIntegrationError` with rich context (psp_name, details, status_code)
- API errors: `PSPAPIError`, `PSPAuthenticationError`, `PSPRateLimitError`, `PSPValidationError`
- Configuration: `PSPConfigurationError` with config_field tracking
- Webhook errors: `PSPWebhookError`, `PSPWebhookSecurityError`, `PSPWebhookIdempotencyError`
- Resource errors: `PSPResourceNotFoundError` with resource_type/resource_id
- All exceptions include `to_dict()` method for logging/serialization
- Ready for MED-1 (WebhookErrorHandler adoption) in Phase 4

### Phase 3: Code Cleanup
- [ ] HIGH-4: Split Ponto webhook.py
- [ ] LOW-1: Remove deprecated mollie_client.py
- [ ] LOW-4: Make debug logging conditional
- [ ] LOW-5: Document/consolidate webhook security files

### Phase 4: Pattern Standardization
- [ ] MED-1: Adopt WebhookErrorHandler in Ponto/ING *(benefits from MED-3)*
- [ ] MED-2: Create base idempotency manager
- [ ] MED-4: Add models to ING Checkout
- [ ] MED-5: Standardize error response formats

### Phase 5: Advanced Consolidation
- [ ] LOW-2: Clarify MollieConnector vs MollieClient
- [ ] LOW-3: Consolidate Mollie orchestration paths
- [ ] LOW-6: Create shared webhook test helpers *(benefits from HIGH-2)*
- [ ] Future: Implement PSPFactory pattern for runtime PSP selection

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Duplicate webhook code | ~40% | <10% |
| Shared infrastructure modules | 2 files | 8+ modules |
| Security gaps | 2 (signatures, rate limiting) | 0 |
| PSPs using shared exception base | 0/3 | 3/3 |
| PSPs using shared resilience | 1/3 (Ponto imports Mollie) | 3/3 |
| New PSP integration effort | ~3 weeks | ~1 week |

---

## References

### Key Files by PSP

**Mollie**:
- Client: `verenigingen_payments/mollie/core/client.py`
- Webhook: `verenigingen_payments/mollie/api/webhooks.py`
- Idempotency: `verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py`
- Orchestrator: `verenigingen_payments/services/mollie_payment_orchestrator.py`

**Ponto**:
- Client: `verenigingen_payments/ponto/core/ponto_client.py`
- OAuth2: `verenigingen_payments/ponto/services/oauth2_service.py`
- Webhook: `verenigingen_payments/ponto/api/webhook.py` (1278 lines)
- Security: `verenigingen_payments/ponto/utils/webhook_security.py`

**ING Checkout**:
- Client: `verenigingen_payments/ing_checkout/client.py`
- Webhook: `verenigingen_payments/ing_checkout/api/webhook.py`
- Security: `verenigingen_payments/ing_checkout/utils/webhook_security.py`

**Shared**:
- Rate Limiter (unused): `verenigingen/utils/webhook_rate_limiter.py`
- Error Handler: `verenigingen/utils/webhook_error_handler.py`
- Service User: `verenigingen/utils/service_user.py`
- Resilience (in wrong place): `verenigingen_payments/mollie/utils/error_recovery.py`

---

## Appendix: Webhook Security Comparison

| Aspect | Mollie | Ponto | ING Checkout |
|--------|--------|-------|--------------|
| **Signature Method** | HMAC-SHA256 (NOT IMPLEMENTED) | JWT RS512 + JWKS | HMAC-SHA256 + IP whitelist |
| **Idempotency** | UnifiedIdempotencyManager | Hash in WebhookProcessingLog | Hash in WebhookProcessingLog |
| **Rate Limiting** | Not integrated | Not integrated | Not integrated |
| **Error Handler** | WebhookErrorHandler | Inline try/except | Inline try/except |
| **User Context** | Custom authenticate_mollie_webhook() | get_service_user() | get_service_user() |
| **Logging** | Partial WebhookProcessingLog | Consistent | Consistent |

---

*Document created from architecture review conducted 2026-01-10*
