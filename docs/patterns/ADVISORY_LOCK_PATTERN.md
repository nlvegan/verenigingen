# Advisory Lock Pattern

## Overview

The advisory lock pattern provides distributed locking for preventing concurrent operations. This pattern is used for operations that must not run simultaneously, such as bulk invoice generation.

## Implementation

**Location:** `verenigingen/utils/db_advisory_lock.py`

### Supported Backends

1. **MySQL/MariaDB (database)** - Uses `GET_LOCK()` / `RELEASE_LOCK()`
   - Session-scoped locks
   - Automatically released when connection closes
   - Works without additional infrastructure

2. **Redis** - Uses `SET NX` with TTL
   - Distributed locking across multiple workers/processes
   - TTL-based automatic expiry for safety
   - Requires Redis infrastructure

### Usage

```python
from verenigingen.utils.db_advisory_lock import (
    advisory_lock,
    advisory_lock_with_backend,
)

# Simple usage (database backend by default)
with advisory_lock("my_operation", timeout=10):
    # Critical section - only one process can be here
    perform_operation()

# Explicit Redis backend for distributed locking
with advisory_lock_with_backend("bulk_generation", timeout=300, backend="redis"):
    # Works across multiple workers/processes
    generate_invoices()

# Auto-detect best available backend
with advisory_lock_with_backend("my_lock", backend="auto") as acquired:
    if acquired:
        do_work()
    else:
        handle_lock_unavailable()
```

### Non-Blocking Mode

For operations that should not wait for lock acquisition:

```python
with advisory_lock_with_backend(
    "operation_name",
    timeout=0,  # Non-blocking
    backend="redis",
    raise_on_timeout=False,
) as acquired:
    if not acquired:
        return "Another operation is already running"

    perform_operation()
```

## Runtime Requirements

### Development Environment

- **MySQL/MariaDB**: Always available (Frappe requirement)
- **Redis**: Optional, uses database locks if unavailable

### Production Environment (Recommended)

For bulk operations with parallel processing:

- **Redis**: Required for distributed locking across workers
- Configure in `site_config.json`:
  ```json
  {
    "redis_cache": "redis://127.0.0.1:13000"
  }
  ```

### Graceful Degradation

The system automatically degrades gracefully:

1. **Redis available** → Uses Redis distributed locks
2. **Redis unavailable** → Falls back to MySQL advisory locks
3. **Lock unavailable** → Operation proceeds without lock (logged as warning)

## Bulk Invoice Generation

`BulkInvoiceGenerationService` uses advisory locks to prevent concurrent generation:

```python
# Lock configuration
LOCK_NAME = "verenigingen_bulk_invoice_generation"
lock_timeout = settings.bulk_generation_timeout or 3600  # 1 hour default

# Lock acquisition (non-blocking)
with advisory_lock_with_backend(
    LOCK_NAME,
    timeout=0,  # Return immediately if locked
    backend="redis" if redis_available else "database",
    ttl=lock_timeout,
    raise_on_timeout=False,
) as acquired:
    if not acquired:
        return error("Another generation is running")

    generate_invoices()
```

## Lock Name Conventions

| Operation | Lock Name |
|-----------|-----------|
| Bulk invoice generation | `verenigingen_bulk_invoice_generation` |
| Member ID assignment | `member_id_bulk_assignment` |

## Error Handling

```python
from verenigingen.utils.db_advisory_lock import AdvisoryLockError

try:
    with advisory_lock("operation", timeout=10, raise_on_timeout=True):
        perform_operation()
except AdvisoryLockError as e:
    logger.warning(f"Lock acquisition failed: {e.lock_name}")
    handle_concurrency_conflict()
```

## Testing

Tests are located at: `verenigingen/tests/utils/test_db_advisory_lock.py`

Key test scenarios:
- Lock acquisition and release
- Timeout handling
- Backend detection
- Redis backend (mocked)
- MySQL re-entrancy behavior

## See Also

- [Transaction Handling Patterns](../CLAUDE.md#transaction-handling-patterns-in-services)
- [Error Handling Patterns](./ERROR_HANDLING_PATTERNS.md)
