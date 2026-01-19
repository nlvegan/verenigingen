# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Advisory Lock Helper with Pluggable Backends

Provides centralized advisory locking for preventing concurrent operations.
Supports multiple backends:
- MySQL/MariaDB: GET_LOCK() / RELEASE_LOCK() (session-scoped)
- Redis: SET NX with token-based ownership (distributed, cross-process)

IMPORTANT BACKEND CONSIDERATIONS:

MySQL/MariaDB Locks:
- Session-scoped: automatically released when connection closes
- Safe within single-process apps; use with caution in connection-pooled environments
- The lock is tied to the database session, not the Python thread
- If using connection pooling, ensure sessions aren't shared while locks are held

Redis Locks:
- Token-based ownership: uses unique UUID per acquisition
- Safe release: Lua script ensures only the owner can release the lock
- TTL safety net: locks auto-expire if holder crashes
- Recommended for multi-worker/multi-process deployments

Usage:
    from verenigingen.utils.db_advisory_lock import (
        advisory_lock,
        advisory_lock_with_backend,
        get_lock,
        release_lock,
    )

    # Simple context manager - uses MySQL/MariaDB (single-process safe)
    with advisory_lock("member_id_bulk_assignment", timeout=10):
        # Critical section
        ...

    # Backend-aware context manager - use for distributed locking
    with advisory_lock_with_backend("bulk_invoice_generation", timeout=300, backend="redis"):
        # Critical section - works across multiple workers/processes
        ...

    # Auto-detect best available backend
    with advisory_lock_with_backend("my_lock", backend="auto") as acquired:
        if acquired:
            do_work()

    # Manual locking (database backend, when context manager isn't suitable)
    if get_lock("my_lock", timeout=5):
        try:
            # Critical section
            ...
        finally:
            release_lock("my_lock")

Backend Support:
    - database (default): MySQL/MariaDB GET_LOCK() / RELEASE_LOCK()
    - redis: Redis SET NX with token + Lua atomic release (requires redis_cache)
    - auto: Auto-detect (prefers Redis if available)
    - PostgreSQL: Not currently supported (raises NotImplementedError)

Production Recommendations:
    - Use Redis backend for bulk operations with multiple workers
    - Configure redis_cache in site_config.json
    - Set appropriate TTL values (default: timeout * 2 or 60s minimum)
    - Always use context managers for automatic cleanup

See: docs/patterns/ADVISORY_LOCK_PATTERN.md
"""

import threading
from contextlib import contextmanager
from typing import Generator, Literal, Optional

import frappe

from verenigingen.constants.error_codes import ErrorCodes

# Type alias for supported backends
LockBackend = Literal["database", "redis", "auto"]


class AdvisoryLockError(Exception):
    """Raised when advisory lock acquisition fails."""

    def __init__(self, message: str, error_code: str = None, lock_name: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.lock_name = lock_name


def get_lock(lock_name: str, timeout: int = 10) -> bool:
    """
    Acquire a database-level advisory lock.

    Uses MySQL/MariaDB GET_LOCK() function to acquire a named lock.
    The lock is session-scoped and will be released when the connection
    closes or when release_lock() is called.

    Args:
        lock_name: Unique name for the lock (max 64 characters)
        timeout: Seconds to wait for lock (0 = no wait, -1 = indefinite)

    Returns:
        True if lock acquired, False if timed out

    Raises:
        AdvisoryLockError: If database doesn't support advisory locks

    Example:
        >>> if get_lock("bulk_operation", timeout=5):
        ...     try:
        ...         perform_bulk_operation()
        ...     finally:
        ...         release_lock("bulk_operation")
    """
    db_type = frappe.conf.get("db_type", "mariadb")

    if db_type in ("mariadb", "mysql"):
        result = frappe.db.sql("SELECT GET_LOCK(%s, %s)", (lock_name, timeout))
        return result and result[0][0] == 1
    elif db_type == "postgres":
        # PostgreSQL advisory locks use bigint keys, not strings
        # Would need: SELECT pg_try_advisory_lock(hashtext(%s))
        raise AdvisoryLockError(
            "PostgreSQL advisory locks not yet implemented. "
            "Contact development team if PostgreSQL support is needed.",
            error_code="ADVISORY_LOCK_UNSUPPORTED",
            lock_name=lock_name,
        )
    else:
        raise AdvisoryLockError(
            f"Advisory locks not supported for database type: {db_type}",
            error_code="ADVISORY_LOCK_UNSUPPORTED",
            lock_name=lock_name,
        )


def release_lock(lock_name: str) -> bool:
    """
    Release a database-level advisory lock.

    Uses MySQL/MariaDB RELEASE_LOCK() function to release a named lock.
    Safe to call even if lock was not acquired (returns False in that case).

    Args:
        lock_name: Name of the lock to release

    Returns:
        True if lock was held and released, False otherwise

    Note:
        Logs a warning if release fails, but does not raise an exception.
        This ensures cleanup code can always complete.
    """
    db_type = frappe.conf.get("db_type", "mariadb")

    if db_type in ("mariadb", "mysql"):
        try:
            result = frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))
            released = result and result[0][0] == 1
            if released:
                frappe.logger("advisory_lock").debug(f"Released lock: {lock_name}")
            return released
        except Exception as e:
            frappe.logger("advisory_lock").warning(f"Failed to release lock {lock_name}: {str(e)}")
            return False
    else:
        # Non-MySQL databases don't need explicit release
        return False


@contextmanager
def advisory_lock(
    lock_name: str, timeout: int = 10, raise_on_timeout: bool = True
) -> Generator[bool, None, None]:
    """
    Context manager for database advisory locks.

    Automatically acquires the lock on entry and releases it on exit,
    even if an exception occurs.

    Args:
        lock_name: Unique name for the lock (max 64 characters)
        timeout: Seconds to wait for lock (0 = no wait)
        raise_on_timeout: If True, raises AdvisoryLockError on timeout.
                          If False, yields False instead.

    Yields:
        True if lock was acquired, False if timed out (when raise_on_timeout=False)

    Raises:
        AdvisoryLockError: If lock acquisition times out (when raise_on_timeout=True)
                          or if database doesn't support advisory locks

    Example:
        >>> with advisory_lock("bulk_member_id_assignment", timeout=10):
        ...     # Critical section - only one process can be here
        ...     assign_member_ids()

        >>> # Or without exception on timeout:
        >>> with advisory_lock("my_lock", timeout=5, raise_on_timeout=False) as acquired:
        ...     if acquired:
        ...         do_work()
        ...     else:
        ...         frappe.msgprint("Another operation in progress")
    """
    lock_acquired = False
    try:
        lock_acquired = get_lock(lock_name, timeout)

        if not lock_acquired:
            frappe.logger("advisory_lock").warning(
                f"Lock acquisition timed out for {lock_name} (timeout={timeout}s)"
            )
            if raise_on_timeout:
                raise AdvisoryLockError(
                    f"Could not acquire lock '{lock_name}' within {timeout} seconds. "
                    "Another operation may be in progress.",
                    error_code=ErrorCodes.MEMBER_ID_LOCK_FAILED,
                    lock_name=lock_name,
                )

        yield lock_acquired

    finally:
        if lock_acquired:
            release_lock(lock_name)


def is_lock_held(lock_name: str, backend: LockBackend = "database") -> bool:
    """
    Check if a lock is currently held (by any session).

    Uses MySQL IS_USED_LOCK() function or Redis EXISTS for check.

    Args:
        lock_name: Name of the lock to check
        backend: Lock backend to use ("database", "redis", or "auto")

    Returns:
        True if lock is held by any session, False otherwise

    Note:
        This is a point-in-time check. The lock status may change
        immediately after this function returns.
    """
    if backend == "auto":
        backend = _detect_backend()

    if backend == "redis":
        return _is_redis_lock_held(lock_name)
    db_type = frappe.conf.get("db_type", "mariadb")

    if db_type in ("mariadb", "mysql"):
        result = frappe.db.sql("SELECT IS_USED_LOCK(%s)", (lock_name,))
        return result and result[0][0] is not None
    else:
        return False


# =============================================================================
# Redis Backend Implementation
# =============================================================================

# Thread-local storage for lock ownership tokens
_lock_tokens = threading.local()

# Lua script for atomic compare-and-delete (safe lock release)
# Only deletes the key if the value matches the owner's token
_REDIS_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def _get_lock_token(lock_name: str) -> str:
    """Get the ownership token for a lock (if we hold it)."""
    if not hasattr(_lock_tokens, "tokens"):
        _lock_tokens.tokens = {}
    return _lock_tokens.tokens.get(lock_name)


def _set_lock_token(lock_name: str, token: str) -> None:
    """Store the ownership token for a lock we acquired."""
    if not hasattr(_lock_tokens, "tokens"):
        _lock_tokens.tokens = {}
    _lock_tokens.tokens[lock_name] = token


def _clear_lock_token(lock_name: str) -> None:
    """Clear the ownership token for a lock we released."""
    if hasattr(_lock_tokens, "tokens") and lock_name in _lock_tokens.tokens:
        del _lock_tokens.tokens[lock_name]


def _detect_backend() -> LockBackend:
    """
    Auto-detect the best available lock backend.

    Returns "redis" if Redis is configured and available, otherwise "database".

    Returns:
        The detected backend type
    """
    if _is_redis_available():
        return "redis"
    return "database"


def _is_redis_available() -> bool:
    """
    Check if Redis is configured and available.

    Returns:
        True if Redis is available, False otherwise
    """
    try:
        redis_url = frappe.conf.get("redis_cache")
        if not redis_url:
            return False

        from frappe.utils.redis_wrapper import RedisWrapper

        redis = RedisWrapper.from_url(redis_url)
        redis.ping()
        return True
    except Exception:
        return False


def _get_redis_client():
    """
    Get a Redis client instance.

    Returns:
        Redis client or None if not available

    Raises:
        AdvisoryLockError: If Redis is required but not available
    """
    try:
        redis_url = frappe.conf.get("redis_cache")
        if not redis_url:
            raise AdvisoryLockError(
                "Redis not configured. Set redis_cache in site_config.json for distributed locking.",
                error_code="REDIS_NOT_CONFIGURED",
            )

        from frappe.utils.redis_wrapper import RedisWrapper

        redis = RedisWrapper.from_url(redis_url)
        redis.ping()  # Verify connectivity
        return redis
    except AdvisoryLockError:
        raise
    except Exception as e:
        raise AdvisoryLockError(
            f"Failed to connect to Redis: {str(e)}",
            error_code="REDIS_CONNECTION_FAILED",
        )


def _get_redis_lock(lock_name: str, timeout: int = 10, ttl: int = None) -> bool:
    """
    Acquire a Redis-based distributed lock with ownership token.

    Uses SET NX (set if not exists) with TTL for automatic expiry.
    Stores a unique token as the value to enable safe release (only the
    owner can release the lock).

    Args:
        lock_name: Unique name for the lock
        timeout: Seconds to wait for lock acquisition (polling interval)
        ttl: Lock TTL in seconds (defaults to timeout * 2 for safety margin)

    Returns:
        True if lock acquired, False if timed out

    Note:
        The ownership token is stored thread-locally. This ensures that
        if the TTL expires and another worker acquires the lock, our
        release call won't accidentally delete their lock.
    """
    import time
    import uuid

    if ttl is None:
        ttl = max(timeout * 2, 60)  # At least 60 seconds TTL

    redis = _get_redis_client()
    lock_key = f"advisory_lock:{lock_name}"

    # Generate unique ownership token for this acquisition attempt
    token = str(uuid.uuid4())

    # Try to acquire lock with exponential backoff
    start_time = time.time()
    attempt = 0

    while (time.time() - start_time) < timeout:
        # Try to set the lock with our token (NX = only if not exists, EX = expiry)
        if redis.set(lock_key, token, nx=True, ex=ttl):
            # Store token for safe release
            _set_lock_token(lock_name, token)
            frappe.logger("advisory_lock").debug(
                f"Acquired Redis lock: {lock_name} (TTL={ttl}s, token={token[:8]}...)"
            )
            return True

        # Lock not acquired, wait with exponential backoff
        attempt += 1
        wait_time = min(0.1 * (2**attempt), 2.0)  # Max 2 second wait
        time.sleep(wait_time)

    frappe.logger("advisory_lock").debug(f"Failed to acquire Redis lock: {lock_name} (timeout={timeout}s)")
    return False


def _release_redis_lock(lock_name: str) -> bool:
    """
    Safely release a Redis-based distributed lock.

    Uses atomic compare-and-delete via Lua script to ensure we only release
    locks we actually own. This prevents accidentally releasing another
    worker's lock if our TTL expired and they acquired it.

    Args:
        lock_name: Name of the lock to release

    Returns:
        True if lock was released, False if we didn't own it or error occurred

    Note:
        If we don't have an ownership token (e.g., process crash and restart),
        we cannot safely release the lock - it must expire via TTL.
    """
    try:
        # Get our ownership token
        token = _get_lock_token(lock_name)
        if not token:
            frappe.logger("advisory_lock").warning(
                f"Cannot release Redis lock {lock_name}: no ownership token (lock may have expired)"
            )
            return False

        redis = _get_redis_client()
        lock_key = f"advisory_lock:{lock_name}"

        # Use Lua script for atomic compare-and-delete
        # Only deletes if the value matches our token
        result = redis.eval(_REDIS_RELEASE_SCRIPT, 1, lock_key, token)

        # Clear our token regardless of result
        _clear_lock_token(lock_name)

        if result:
            frappe.logger("advisory_lock").debug(f"Released Redis lock: {lock_name}")
            return True
        else:
            frappe.logger("advisory_lock").warning(
                f"Redis lock {lock_name} not released: token mismatch (lock may have expired and been re-acquired)"
            )
            return False
    except Exception as e:
        frappe.logger("advisory_lock").warning(f"Failed to release Redis lock {lock_name}: {str(e)}")
        _clear_lock_token(lock_name)  # Clean up token even on error
        return False


def _is_redis_lock_held(lock_name: str) -> bool:
    """
    Check if a Redis lock is currently held.

    Args:
        lock_name: Name of the lock to check

    Returns:
        True if lock exists, False otherwise
    """
    try:
        redis = _get_redis_client()
        lock_key = f"advisory_lock:{lock_name}"
        return bool(redis.exists(lock_key))
    except Exception:
        return False


# =============================================================================
# Backend-aware wrapper functions
# =============================================================================


def get_lock_with_backend(
    lock_name: str,
    timeout: int = 10,
    backend: LockBackend = "database",
    ttl: int = None,
) -> bool:
    """
    Acquire a lock using the specified backend.

    Args:
        lock_name: Unique name for the lock
        timeout: Seconds to wait for lock
        backend: Lock backend ("database", "redis", or "auto")
        ttl: Lock TTL for Redis backend (defaults to timeout * 2)

    Returns:
        True if lock acquired, False if timed out
    """
    if backend == "auto":
        backend = _detect_backend()

    if backend == "redis":
        return _get_redis_lock(lock_name, timeout, ttl)
    else:
        return get_lock(lock_name, timeout)


def release_lock_with_backend(lock_name: str, backend: LockBackend = "database") -> bool:
    """
    Release a lock using the specified backend.

    Args:
        lock_name: Name of the lock to release
        backend: Lock backend ("database", "redis", or "auto")

    Returns:
        True if lock was released, False otherwise
    """
    if backend == "auto":
        backend = _detect_backend()

    if backend == "redis":
        return _release_redis_lock(lock_name)
    else:
        return release_lock(lock_name)


@contextmanager
def advisory_lock_with_backend(
    lock_name: str,
    timeout: int = 10,
    backend: LockBackend = "database",
    ttl: int = None,
    raise_on_timeout: bool = True,
) -> Generator[bool, None, None]:
    """
    Context manager for advisory locks with pluggable backend.

    Automatically acquires the lock on entry and releases it on exit,
    even if an exception occurs.

    Args:
        lock_name: Unique name for the lock
        timeout: Seconds to wait for lock
        backend: Lock backend ("database", "redis", or "auto")
        ttl: Lock TTL for Redis backend (defaults to timeout * 2)
        raise_on_timeout: If True, raises AdvisoryLockError on timeout

    Yields:
        True if lock was acquired, False if timed out (when raise_on_timeout=False)

    Example:
        >>> # Use Redis for distributed locking across workers
        >>> with advisory_lock_with_backend("bulk_generation", timeout=300, backend="redis"):
        ...     generate_invoices()

        >>> # Auto-detect best available backend
        >>> with advisory_lock_with_backend("my_lock", backend="auto") as acquired:
        ...     if acquired:
        ...         do_work()
    """
    if backend == "auto":
        backend = _detect_backend()

    lock_acquired = False
    try:
        lock_acquired = get_lock_with_backend(lock_name, timeout, backend, ttl)

        if not lock_acquired:
            frappe.logger("advisory_lock").warning(
                f"Lock acquisition timed out for {lock_name} (backend={backend}, timeout={timeout}s)"
            )
            if raise_on_timeout:
                raise AdvisoryLockError(
                    f"Could not acquire lock '{lock_name}' within {timeout} seconds. "
                    "Another operation may be in progress.",
                    error_code=ErrorCodes.MEMBER_ID_LOCK_FAILED,
                    lock_name=lock_name,
                )

        yield lock_acquired

    finally:
        if lock_acquired:
            release_lock_with_backend(lock_name, backend)
