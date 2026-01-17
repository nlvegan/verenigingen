# Plan: eBoekhouden HTTP Client Enhancements

## Context

Code review identified gaps in the HTTP client mixin. After verification, 3 of 6 issues were already addressed. This plan covers the remaining valid concerns.

## Issues to Address

### 1. Retry-After Header Handling (Issue #3)

**Problem**: When API returns 429 (rate limit), we retry with exponential backoff but ignore the `Retry-After` header that tells us exactly how long to wait.

**Solution**: Enhance `_request_with_retry()` to:
- Check for `Retry-After` header on 429 responses
- Use header value instead of calculated backoff when present
- Cap maximum wait to prevent excessive delays

**Changes**:
- `http_client_mixin.py`: Add `_get_retry_delay()` method that checks headers

```python
def _get_retry_delay(self, response, attempt: int) -> float:
    """Calculate retry delay, preferring Retry-After header if present."""
    # Check for Retry-After header (can be seconds or HTTP date)
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            # Try parsing as seconds first
            delay = float(retry_after)
            return min(delay, 60.0)  # Cap at 60 seconds
        except ValueError:
            pass  # Could be HTTP date, fall through to default

    # Default exponential backoff
    return self.RETRY_BACKOFF_FACTOR * (2 ** attempt)
```

---

### 2. Thread Safety for Token Management (Issue #4)

**Problem**: Multiple threads could race to refresh tokens or update caches, causing:
- Double token refresh
- Stale token usage
- Cache corruption

**Solution**: Add `threading.Lock()` around critical sections.

**Changes**:
- `http_client_mixin.py`: Add lock for token operations

```python
import threading

class EBoekhoudenHTTPClientMixin:
    def _init_http_client(self, settings=None) -> None:
        # ... existing code ...
        self._token_lock = threading.Lock()

    def _get_session_token(self) -> Optional[str]:
        with self._token_lock:
            if not self._token_is_expired():
                return self._session_token
            # ... fetch new token ...

    def invalidate_token(self) -> None:
        with self._token_lock:
            self._session_token = None
            self._token_obtained_at = None
```

- `eboekhouden_rest_client.py`: Add lock for cache operations

```python
def __init__(self, settings=None):
    self._init_http_client(settings)
    self._cache_lock = threading.Lock()
    self._ledger_cache = None
    self._relation_cache = None

def get_ledgers(self) -> Dict[str, Any]:
    with self._cache_lock:
        if self._ledger_cache is not None:
            return {"success": True, "ledgers": self._ledger_cache}
    # ... fetch and cache ...
```

---

### 3. Metrics/Instrumentation (Issue #5)

**Problem**: No visibility into API behavior during migrations. Hard to diagnose issues or monitor health.

**Solution**: Add lightweight counters for key metrics.

**Changes**:
- `http_client_mixin.py`: Add metrics tracking

```python
from dataclasses import dataclass, field

@dataclass
class HTTPClientMetrics:
    """Metrics for HTTP client operations."""
    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    retries_total: int = 0
    token_refreshes: int = 0
    rate_limits_hit: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "requests_total": self.requests_total,
            "requests_success": self.requests_success,
            "requests_failed": self.requests_failed,
            "retries_total": self.retries_total,
            "token_refreshes": self.token_refreshes,
            "rate_limits_hit": self.rate_limits_hit,
        }

class EBoekhoudenHTTPClientMixin:
    def _init_http_client(self, settings=None) -> None:
        # ... existing code ...
        self.metrics = HTTPClientMetrics()

    def get_metrics(self) -> Dict[str, int]:
        """Return current metrics for monitoring."""
        return self.metrics.to_dict()

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        self.metrics = HTTPClientMetrics()
```

Update `_request_with_retry()` to increment counters at appropriate points.

---

## New Tests Required

Add tests for:
1. `Retry-After` header handling (seconds and edge cases)
2. Thread safety (concurrent token refresh)
3. Metrics collection accuracy

---

## Implementation Order

1. **Thread safety** (highest risk if not addressed)
2. **Retry-After handling** (improves reliability)
3. **Metrics** (nice to have for observability)

---

## Files to Modify

| File | Changes |
|------|---------|
| `http_client_mixin.py` | Add lock, Retry-After handling, metrics |
| `eboekhouden_rest_client.py` | Add cache lock |
| `test_http_client_mixin.py` | Add new tests |

## Estimated Scope

- ~100 lines of new code
- ~50 lines of new tests
- No breaking changes to existing API
