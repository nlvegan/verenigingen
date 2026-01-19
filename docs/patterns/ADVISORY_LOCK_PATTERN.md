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
   - **Caution**: Session-scoped means locks are tied to the DB connection, not the Python thread. Use with care in connection-pooled environments.

2. **Redis** - Uses native `redis.lock.Lock` from the redis package
   - Distributed locking across multiple workers/processes
   - **Token-based ownership**: Handled internally by `redis.lock.Lock`
   - **Safe release**: `Lock.release()` uses Lua scripts for atomic compare-and-delete
   - **Ownership check**: `Lock.owned()` verifies we still hold the lock before release
   - TTL-based automatic expiry as safety net (if holder crashes)
   - Requires Redis infrastructure
   - **Recommended for production multi-worker deployments**

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

### Backend Selection

The system selects backends as follows:

1. **Redis available** → Uses Redis distributed locks (preferred for multi-worker)
2. **Redis unavailable** → Falls back to MySQL advisory locks (single-process safe)

### Lock Failure Handling

**Critical operations (like bulk invoice generation) MUST NOT proceed without a lock.**

If lock acquisition fails:
- The operation is aborted with a clear error message
- No partial or duplicate work is performed
- The caller receives an error they can report to the user

This prevents duplicate invoice generation and other race conditions.

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

## Redis Safe Release Pattern

The Redis implementation uses `redis.lock.Lock` which handles token-based ownership internally:

```python
from redis.lock import Lock

# On acquisition:
lock = Lock(redis_client, lock_key, timeout=ttl, blocking_timeout=timeout)
if lock.acquire():
    store_lock_object(lock_name, lock)  # Store Lock object for later release

# On release:
lock = get_lock_object(lock_name)
if lock and lock.owned():  # Verify we still own the lock
    lock.release()  # Uses Lua script internally for atomic compare-and-delete
```

The `redis.lock.Lock` class prevents the following race condition:
1. Worker A acquires lock with TTL=60s
2. Worker A takes longer than 60s (lock expires)
3. Worker B acquires the same lock with a new token
4. Worker A tries to release "its" lock
5. `lock.owned()` returns `False` - Worker A's release is skipped safely

## Testing

Tests are located at: `verenigingen/tests/utils/test_db_advisory_lock.py`

Key test scenarios:
- Lock acquisition and release
- Timeout handling
- Backend detection
- Redis backend (mocked with `redis.lock.Lock`)
- MySQL re-entrancy behavior
- **Lock object stored on acquisition** (Redis)
- **Release without Lock object fails** (Redis)
- **Release when not owned fails** (Redis - TTL expiry scenario)

## See Also

- [Transaction Handling Patterns](../CLAUDE.md#transaction-handling-patterns-in-services)
- [Error Handling Patterns](./ERROR_HANDLING_PATTERNS.md)
