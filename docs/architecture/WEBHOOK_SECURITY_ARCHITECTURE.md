# Webhook Security Architecture

This document describes the webhook security implementation across all Payment Service Provider (PSP) integrations.

## Overview

Each PSP uses different webhook authentication mechanisms based on their API specifications:

| PSP | Signature Method | Authentication | Implementation |
|-----|------------------|----------------|----------------|
| **Mollie** | HMAC-SHA256 | Shared secret | `mollie/utils/webhook_security.py` |
| **Ponto/Ibanity** | JWT (RS512) | JWKS public keys | `ponto/utils/webhook_security.py` |
| **ING/Pay.nl** | IP validation + HMAC | IP whitelist + secret | `ing_checkout/utils/webhook_security.py` |

## File Structure

```
verenigingen/
├── utils/
│   ├── webhook_security.py              # DEPRECATED - Legacy shared module
│   └── webhook/
│       └── logging.py                   # Unified webhook logging (HIGH-2)
│
└── verenigingen_payments/
    ├── core/
    │   ├── security/
    │   │   └── webhook_validator.py     # Enhanced Mollie validator with replay protection
    │   └── exceptions/
    │       └── __init__.py              # Shared PSP exception hierarchy (MED-3)
    │
    ├── mollie/utils/
    │   └── webhook_security.py          # AUTHORITATIVE - Mollie webhook auth
    │
    ├── ponto/utils/
    │   └── webhook_security.py          # AUTHORITATIVE - Ponto/Ibanity JWT auth
    │
    └── ing_checkout/utils/
        └── webhook_security.py          # AUTHORITATIVE - ING/Pay.nl webhook auth
```

## PSP-Specific Implementations

### Mollie (`mollie/utils/webhook_security.py`)

**Authentication Method**: HMAC-SHA256 signature verification

**Features**:
- Signature validation using shared webhook secret
- User context setting via `get_service_user()` (HIGH-3 migration)
- Rate limiting integration

**Usage**:
```python
from verenigingen.verenigingen_payments.mollie.utils.webhook_security import (
    authenticate_mollie_webhook,
)

# In webhook handler:
payload = authenticate_mollie_webhook()  # Validates & returns payload
```

**Key Functions**:
- `authenticate_mollie_webhook()` - Full authentication with rate limiting and user context
- Uses `get_service_user()` for webhook user resolution (shared utility)

---

### Ponto/Ibanity (`ponto/utils/webhook_security.py`)

**Authentication Method**: JWT with RS512 signatures using JWKS

**Features**:
- JWKS-based public key retrieval from Ibanity endpoint
- RS512 JWT signature verification
- Claims validation (audience, issuer, exp, iat)
- SHA-512 payload digest verification
- Key caching with rotation support

**Usage**:
```python
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
    verify_ponto_webhook,
)

try:
    claims = verify_ponto_webhook(payload, signature, application_id)
except PontoWebhookError as e:
    # Handle verification failure
```

**Key Functions**:
- `verify_ponto_webhook()` - Complete JWT verification
- `get_jwks_keys()` - Fetch/cache JWKS public keys
- `verify_jwt_signature()` - RS512 signature verification

---

### ING/Pay.nl (`ing_checkout/utils/webhook_security.py`)

**Authentication Method**: IP validation (primary) + HMAC-SHA256 (fallback)

**Features**:
- IP whitelist validation via Pay.nl API
- HMAC-SHA256 signature as secondary verification
- User context authentication
- Idempotency protection via webhook logging (uses unified module)

**Usage**:
```python
from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
    verify_ing_checkout_webhook,
    get_webhook_user,
    is_duplicate_webhook,
)

if not verify_ing_checkout_webhook(payload, signature):
    frappe.throw("Invalid webhook signature", frappe.AuthenticationError)
```

**Key Functions**:
- `verify_ing_checkout_webhook()` - Full verification with IP + signature
- `validate_source_ip()` - Check IP against Pay.nl whitelist
- `compute_webhook_hash()` - Thin wrapper to unified logging module
- `is_duplicate_webhook()` - Thin wrapper to unified logging module

---

## Shared Infrastructure

### Unified Webhook Logging (`utils/webhook/logging.py`)

Created as part of HIGH-2 consolidation, provides:
- `compute_webhook_hash()` - SHA256 hash for idempotency
- `is_duplicate_webhook()` - Check for duplicate webhooks
- `create_webhook_log()` - Create processing log entry
- `update_webhook_log()` - Update log status
- `get_webhook_log_by_hash()` - Retrieve by hash

All PSP webhook handlers use this for consistent logging.

### Service User Resolution (`utils/service_user.py`)

Created as part of HIGH-3 consolidation:
- `get_service_user()` - Resolve webhook user from settings

Used by Mollie, Ponto, and ING webhook handlers.

### PSP Exception Hierarchy (`core/exceptions/__init__.py`)

Created as part of MED-3:
- `PSPWebhookError` - Base webhook error
- `PSPWebhookSecurityError` - Authentication failures
- `PSPWebhookIdempotencyError` - Duplicate webhook detection

---

## Security Best Practices

### 1. Always Verify Signatures
```python
# Never process webhooks without verification
if not verify_webhook(payload, signature):
    log_security_event("Invalid signature")
    return 401
```

### 2. Use Rate Limiting
```python
from verenigingen.utils.webhook_rate_limiter import get_webhook_rate_limiter

rate_limiter = get_webhook_rate_limiter()
is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)
```

### 3. Set Proper User Context
```python
# Webhooks run as Guest but need user context for permissions
webhook_user = get_service_user(
    settings_doctype="Verenigingen Payments Settings",
    user_field="webhook_user",
    service_name="PSP Webhook",
)
frappe.set_user(webhook_user)
```

### 4. Check for Duplicates
```python
from verenigingen.utils.webhook.logging import is_duplicate_webhook

if is_duplicate_webhook(webhook_hash):
    return {"status": "already_processed"}
```

---

## Deprecated Files

### `utils/webhook_security.py`
- **Status**: Legacy, should not be used for new code
- **Reason**: Original shared module, superseded by PSP-specific implementations
- **Migration**: Use PSP-specific modules instead

### `core/security/webhook_validator.py`
- **Status**: Active but Mollie-specific
- **Note**: Provides enhanced validation with replay protection
- **Usage**: Can be used alongside `mollie/utils/webhook_security.py` for additional security

---

## Testing

Each PSP has dedicated webhook security tests:

```
verenigingen/
├── tests/
│   └── test_mollie_webhook_security.py      # Integration tests
│
└── verenigingen_payments/
    ├── mollie/tests/
    │   ├── test_mollie_webhook_security.py
    │   └── test_webhook_security.py
    │
    ├── ponto/tests/
    │   └── (webhook tests in webhook handler tests)
    │
    └── ing_checkout/tests/
        └── test_webhook_security.py
```

---

## Related Documentation

- [PSP Integration Consolidation Plan](./PSP_INTEGRATION_CONSOLIDATION_PLAN.md)
- [API Security Framework](../security/API_SECURITY_FRAMEWORK.md)

---

*Last Updated: 2026-01-10 (LOW-5 documentation)*
