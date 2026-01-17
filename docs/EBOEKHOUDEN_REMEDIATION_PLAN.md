# E-Boekhouden Integration: Audit & Remediation Plan

## Executive Summary

This document presents an independent audit of the e-Boekhouden integration code and a prioritized remediation plan. The integration is well-architected with processor/factory patterns, transaction management, and good validation. However, there are critical gaps in API resilience, client consolidation, and race condition handling that need to be addressed.

**Critical Priority:**
1. Token expiry handling is inconsistent across three different API client implementations
2. No retry mechanism for transient HTTP errors (429, 5xx)
3. Race condition handling for duplicate detection is incomplete

**Medium Priority:**
4. Date format normalization is incomplete
5. Full mutation JSON logged on errors (PII exposure risk)
6. Duplicate REST client implementations

**Low Priority:**
7. Test coverage gaps
8. Minor code cleanup opportunities

---

## Detailed Findings

### 1. API Session Token Handling — CRITICAL

**Problem:** Three different API client implementations with inconsistent token handling:

| File | Token Caching | Token Expiry Tracking | Auto-Refresh |
|------|---------------|----------------------|--------------|
| `eboekhouden_rest_client.py:77-117` | Yes (in-memory) | **No** | **No** |
| `eboekhouden_rest_iterator.py:31-62` | Yes (in-memory) | **Yes** (55min TTL) | Yes |
| `eboekhouden_api.py:52-74` | **No** (fresh each request) | N/A | N/A |

**Risk:**
- Long-running migrations will fail when tokens expire (~60 minutes)
- `EBoekhoudenRESTClient` is used by the main migration code but lacks expiry handling
- `EBoekhoudenAPI` creates unnecessary API overhead with per-request tokens
- Inconsistent behavior makes debugging difficult

**Evidence:**
```python
# eboekhouden_rest_client.py:92-93 - No expiry check
def _get_session_token(self):
    if self._session_token:  # Returns cached token WITHOUT checking expiry
        return self._session_token
```

vs.

```python
# eboekhouden_rest_iterator.py:34-36 - HAS expiry check
if self._session_token and self._session_expiry:
    if datetime.now() < self._session_expiry:
        return self._session_token
```

**Remediation:**

1. **Consolidate to single canonical client** — Use `EBoekhoudenRESTIterator` as the base (it has expiry handling)
2. **Add token expiry to `EBoekhoudenRESTClient`**:

```python
# Proposed fix for eboekhouden_rest_client.py
from datetime import datetime, timedelta

class EBoekhoudenRESTClient:
    TOKEN_TTL_MINUTES = 55  # e-Boekhouden tokens last ~60 min, use 55 for safety

    def __init__(self, settings=None):
        # ... existing code ...
        self._session_token = None
        self._token_obtained_at = None  # NEW: Track when token was obtained

    def _token_is_expired(self):
        """Check if cached token is expired or missing."""
        if not self._session_token or not self._token_obtained_at:
            return True
        expiry_time = self._token_obtained_at + timedelta(minutes=self.TOKEN_TTL_MINUTES)
        return datetime.now() >= expiry_time

    def _get_session_token(self):
        # Check expiry BEFORE returning cached token
        if not self._token_is_expired():
            return self._session_token

        # ... rest of token acquisition logic ...
        self._token_obtained_at = datetime.now()  # Track acquisition time
        return self._session_token
```

3. **Deprecate `EBoekhoudenAPI`** — Make it a thin wrapper around the canonical client or remove it entirely

---

### 2. Retry Mechanism for HTTP Errors — CRITICAL

**Problem:** No automatic retry for transient API failures (401 token expired, 429 rate limit, 500-504 server errors).

**Evidence:**
- Searched codebase for `retry|backoff` — only found in `payment_entry_handler.py:100` for database operations, not HTTP
- `eboekhouden_rest_client.py:175` returns error dict on failure without retry
- No use of `urllib3.Retry` or similar patterns

**Risk:**
- Transient network issues cause full migration failure
- Rate limiting (429) causes incomplete imports
- Manual intervention required for recoverable errors

**Remediation:**

```python
# Proposed: Add to eboekhouden_rest_client.py

import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class EBoekhoudenRESTClient:
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 1  # 1s, 2s, 4s
    RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

    def __init__(self, settings=None):
        # ... existing code ...
        self.session = self._create_session_with_retry()

    def _create_session_with_retry(self):
        """Create requests session with automatic retry for transient errors."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_CODES,
            allowed_methods=["GET", "POST"],  # Retry both GET and POST
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _request_with_token_refresh(self, method, url, **kwargs):
        """Make request with automatic token refresh on 401."""
        headers = kwargs.pop("headers", {})
        headers.update(self._get_headers())
        kwargs["headers"] = headers

        response = self.session.request(method, url, **kwargs)

        # On 401/403, try refreshing token once
        if response.status_code in (401, 403):
            self._session_token = None  # Force token refresh
            self._token_obtained_at = None
            headers.update(self._get_headers())
            response = self.session.request(method, url, **kwargs)

        return response
```

---

### 3. Race Condition in Duplicate Detection — HIGH

**Problem:** `check_duplicate()` in `base_processor.py:91-107` uses optimistic checking, but if two workers process the same mutation concurrently, the DB unique constraint will raise `DuplicateEntryError` which isn't gracefully handled everywhere.

**Evidence:**
```python
# base_processor.py:91-107
def check_duplicate(self, mutation_id: str, doctype: str) -> Optional[str]:
    existing = frappe.db.get_value(doctype, {"eboekhouden_mutation_nr": mutation_id}, "name")
    # TOCTOU: Between this check and insert(), another process could insert
```

**Risk:**
- Concurrent imports can fail with unhandled exceptions
- Partial imports that require manual cleanup

**Remediation:**

```python
# Add to base_processor.py or a new utils/duplicate_handling.py

import frappe
from frappe.exceptions import DuplicateEntryError

def insert_with_duplicate_handling(doc, mutation_id_field="eboekhouden_mutation_nr"):
    """
    Insert document with graceful duplicate handling.

    On DuplicateEntryError, fetches and returns the existing document
    instead of failing. This handles race conditions where two workers
    check for duplicates simultaneously.
    """
    try:
        doc.insert()
        return doc, False  # (document, was_duplicate)
    except DuplicateEntryError:
        # Race condition: another process inserted first
        mutation_id = getattr(doc, mutation_id_field)
        existing_name = frappe.db.get_value(
            doc.doctype,
            {mutation_id_field: mutation_id},
            "name"
        )
        if existing_name:
            frappe.logger().info(
                f"Duplicate handled gracefully: {doc.doctype} with "
                f"{mutation_id_field}={mutation_id} already exists as {existing_name}"
            )
            existing_doc = frappe.get_doc(doc.doctype, existing_name)
            return existing_doc, True
        raise  # Re-raise if we can't find the duplicate (shouldn't happen)
```

---

### 4. Date Format Normalization — MEDIUM

**Problem:** `get_posting_date()` in `base_processor.py:109-126` handles YYYYMMDD format but returns other formats (like ISO datetime) as-is.

**Evidence:**
```python
# base_processor.py:121-126
if len(date_str) == 8 and date_str.isdigit():
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
# Return as-is if already in correct format
return date_str  # Could be "2025-01-10T00:00:00" — not normalized!
```

**Risk:**
- DB date comparisons may fail
- Filter queries might not match expected dates
- Inconsistent data in ERPNext

**Remediation:**

```python
# base_processor.py - Enhanced get_posting_date

def get_posting_date(self, mutation: Dict[str, Any]) -> str:
    """
    Extract and normalize posting date to YYYY-MM-DD format.

    Handles:
    - YYYYMMDD (eBoekhouden format)
    - ISO datetime (2025-01-10T00:00:00)
    - YYYY-MM-DD (already correct)
    """
    date_str = mutation.get("Datum", "") or mutation.get("date", "")

    if not date_str:
        return ""

    date_str = str(date_str).strip()

    # Handle eBoekhouden YYYYMMDD format
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Handle ISO datetime format (2025-01-10T00:00:00)
    if "T" in date_str:
        return date_str.split("T")[0]

    # Handle already-correct YYYY-MM-DD
    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        return date_str

    # Fallback: try dateutil for other formats
    try:
        from dateutil import parser
        parsed = parser.parse(date_str)
        return parsed.date().isoformat()
    except Exception:
        self.add_debug_info(f"⚠️ Could not normalize date: {date_str}")
        return date_str
```

---

### 5. PII Exposure in Error Logs — MEDIUM

**Problem:** Full mutation JSON is logged on errors, potentially exposing PII.

**Evidence:**
```python
# payment_processor.py:69-76
frappe.log_error(
    title=f"Unexpected Negative Row Amount - Mutation {mutation_id}",
    message=f"...Full mutation: {frappe.as_json(mutation, indent=2)}",  # ⚠️ Full data
)
```

Similar patterns in:
- `base_processor.py:243-246`
- `payment_processor.py:317-320, 495-497`

**Risk:**
- Customer emails, names, addresses exposed in error logs
- GDPR/privacy compliance concerns
- Log storage bloat

**Remediation:**

```python
# Add to a new file: e_boekhouden/utils/logging_utils.py

def mask_pii_in_mutation(mutation: dict) -> dict:
    """
    Create a copy of mutation with PII fields masked for safe logging.
    """
    import copy

    masked = copy.deepcopy(mutation)

    PII_FIELDS = [
        "email", "phone", "mobile", "address", "postcode", "city",
        "contactName", "contactEmail", "bankAccount", "iban", "bic"
    ]

    def mask_value(value):
        if not value or not isinstance(value, str):
            return value
        if len(value) <= 4:
            return "***"
        return value[:2] + "***" + value[-2:]

    def mask_dict(d):
        for key in d:
            if isinstance(d[key], dict):
                mask_dict(d[key])
            elif isinstance(d[key], list):
                for item in d[key]:
                    if isinstance(item, dict):
                        mask_dict(item)
            elif key.lower() in [f.lower() for f in PII_FIELDS]:
                d[key] = mask_value(d[key])

    mask_dict(masked)
    return masked

# Usage in error logging:
from .logging_utils import mask_pii_in_mutation

frappe.log_error(
    title=f"Error - Mutation {mutation_id}",
    message=f"...Mutation (PII masked): {frappe.as_json(mask_pii_in_mutation(mutation))}",
)
```

---

### 6. Duplicate REST Client Implementations — MEDIUM

**Problem:** Three client implementations with overlapping functionality:

| File | Purpose | Status |
|------|---------|--------|
| `eboekhouden_rest_client.py` | Main migration client | Needs token expiry fix |
| `eboekhouden_rest_iterator.py` | ID-based iteration | Has token expiry, good |
| `eboekhouden_api.py` | General API access | Fresh token per request |

**Risk:**
- Maintenance burden
- Inconsistent behavior
- Bug fixes need to be applied to multiple places

**Remediation:**

1. **Create abstract base class or mixin** for common HTTP functionality:

```python
# e_boekhouden/utils/http_client_base.py

class EBoekhoudenHTTPClientMixin:
    """Common HTTP functionality for e-Boekhouden clients."""

    TOKEN_TTL_MINUTES = 55
    MAX_RETRIES = 3

    def _init_http(self):
        """Initialize HTTP session and token tracking."""
        self._session_token = None
        self._token_obtained_at = None
        self.session = self._create_session_with_retry()

    def _create_session_with_retry(self):
        # ... retry logic ...

    def _get_session_token(self):
        # ... unified token logic with expiry ...

    def _request_with_token_refresh(self, method, url, **kwargs):
        # ... request with auto-refresh ...
```

2. **Refactor existing clients** to use the mixin
3. **Consider deprecating `EBoekhoudenAPI`** in favor of `EBoekhoudenRESTClient`

---

### 7. Test Coverage Gaps — LOW

**Problem:** Limited tests for critical paths.

**Found tests:**
- `test_bank_transaction_parser.py`
- `test_party_extractor.py`
- `test_configurable_account_mapper.py`
- `test_cost_center_*.py`
- `test_relation_migration_service.py`

**Missing tests for:**
- Token expiry handling
- Retry behavior on 401/429/5xx
- Concurrent duplicate insertion (race condition)
- Date format normalization edge cases
- Amount sign variations for all mutation types
- Multi-invoice payment reconciliation

**Remediation:**

Create new test file: `tests/e_boekhouden/test_api_resilience.py`

```python
# Proposed test structure

import unittest
from unittest.mock import Mock, patch
import frappe

class TestTokenExpiry(unittest.TestCase):
    def test_expired_token_triggers_refresh(self):
        """Token refresh should occur when TTL exceeded."""
        pass

    def test_401_response_triggers_token_refresh(self):
        """401 from API should trigger token refresh and retry."""
        pass

class TestRetryBehavior(unittest.TestCase):
    def test_429_triggers_backoff_retry(self):
        """Rate limit should trigger exponential backoff."""
        pass

    def test_500_triggers_retry(self):
        """Server error should trigger retry."""
        pass

    def test_max_retries_exceeded_raises_error(self):
        """After max retries, error should propagate."""
        pass

class TestDuplicateHandling(unittest.TestCase):
    def test_concurrent_insert_handled_gracefully(self):
        """DuplicateEntryError should return existing document."""
        pass

    def test_duplicate_detection_with_unique_constraint(self):
        """DB unique constraint should catch race conditions."""
        pass
```

---

## Prioritized Implementation Plan

### Phase 1: Critical API Resilience (Week 1)

| Task | File(s) | Effort |
|------|---------|--------|
| Add token expiry tracking to `EBoekhoudenRESTClient` | `eboekhouden_rest_client.py` | 2h |
| Add retry mechanism with backoff | `eboekhouden_rest_client.py` | 3h |
| Add 401 token refresh logic | `eboekhouden_rest_client.py` | 2h |
| Write tests for token/retry | `test_api_resilience.py` | 4h |
| **Subtotal** | | **11h** |

### Phase 2: Data Integrity (Week 2)

| Task | File(s) | Effort |
|------|---------|--------|
| Add `insert_with_duplicate_handling()` | `base_processor.py` or new file | 2h |
| Update all processors to use new helper | All processors | 3h |
| Enhance date normalization | `base_processor.py` | 2h |
| Add PII masking for logs | New `logging_utils.py` + updates | 3h |
| Write tests for race conditions | `test_api_resilience.py` | 3h |
| **Subtotal** | | **13h** |

### Phase 3: Consolidation (Week 3)

| Task | File(s) | Effort |
|------|---------|--------|
| Create `EBoekhoudenHTTPClientMixin` | New file | 3h |
| Refactor `EBoekhoudenRESTClient` | `eboekhouden_rest_client.py` | 2h |
| Refactor `EBoekhoudenRESTIterator` | `eboekhouden_rest_iterator.py` | 2h |
| Deprecate/remove `EBoekhoudenAPI` | `eboekhouden_api.py` | 2h |
| Update all usages | Multiple files | 3h |
| Integration testing | - | 4h |
| **Subtotal** | | **16h** |

### Total Estimated Effort: ~40 hours

---

## Risk Mitigation

1. **Backward Compatibility:** All changes should be backward-compatible. New retry/token logic should be additive.

2. **Rollback Plan:** Feature flags can be added to disable new behavior if issues arise:
   ```python
   settings.get("enable_api_retry", True)
   settings.get("enable_token_expiry_tracking", True)
   ```

3. **Monitoring:** Add metrics/logging for:
   - Token refresh events
   - Retry attempts and outcomes
   - Duplicate detection race conditions caught

4. **Staged Rollout:**
   - Phase 1: Deploy to staging, run full migration test
   - Phase 2: Deploy to production with monitoring
   - Phase 3: Client consolidation only after Phase 1+2 stable

---

## Appendix: File Reference

| Category | File | Lines of Interest |
|----------|------|-------------------|
| REST Client (no expiry) | `e_boekhouden/utils/eboekhouden_rest_client.py` | 77-117 |
| REST Iterator (has expiry) | `e_boekhouden/utils/eboekhouden_rest_iterator.py` | 31-62 |
| API Client (fresh token) | `e_boekhouden/utils/eboekhouden_api.py` | 52-74 |
| Base Processor | `e_boekhouden/utils/processors/base_processor.py` | 91-126, 170-256 |
| Payment Processor | `e_boekhouden/utils/processors/payment_processor.py` | 64-76, 293-298 |
| Transaction Coordinator | `e_boekhouden/utils/processors/transaction_coordinator.py` | 129-199 |
| Security Helper | `e_boekhouden/utils/security_helper.py` | 286-460 |
| Custom Fields | `e_boekhouden/utils/create_eboekhouden_custom_fields.py` | 14-144 |
| Settings DocType | `e_boekhouden/doctype/e_boekhouden_settings/e_boekhouden_settings.py` | 345-365 |

---

*Document created: 2026-01-17*
*Author: Claude Code Audit*
*Version: 1.0*
