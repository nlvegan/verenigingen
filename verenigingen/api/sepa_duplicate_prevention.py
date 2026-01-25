"""
SEPA Duplicate Prevention and Safeguards
Implements robust mechanisms to prevent double debiting and duplicate processing
"""

import hashlib
import os
import threading
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.audit_logging import log_sensitive_operation

# Default TTL values (in seconds)
DEFAULT_LOCK_TTL = 300  # 5 minutes for processing locks
DEFAULT_BATCH_LOCK_TTL = 1800  # 30 minutes for batch operations
DEFAULT_CACHE_TTL = 3600  # 1 hour for idempotency cache
DEFAULT_IDEMPOTENCY_LOCK_TIMEOUT = 30  # 30 seconds to acquire idempotency lock

# Flag to track if Redis requirement has been checked this request
_redis_requirement_checked = False


# =============================================================================
# PRODUCTION SAFETY CHECKS
# =============================================================================


def _check_redis_required() -> None:
    """
    Fail fast if Redis not configured but required for multi-worker safety.

    In multi-worker deployments, in-memory locks are not safe because each
    worker has its own memory space. Redis provides distributed locking.

    Raises:
        ValidationError: If Redis is required but not configured
    """
    global _redis_requirement_checked

    # Only check once per request to avoid repeated overhead
    if _redis_requirement_checked:
        return
    _redis_requirement_checked = True

    # Allow in-memory for development mode
    if frappe.conf.get("developer_mode"):
        return

    # Check if multi-worker environment
    workers = frappe.conf.get("workers", {})
    gunicorn_workers = frappe.conf.get("gunicorn_workers", 1)

    # If more than 1 worker configured, require Redis
    is_multi_worker = gunicorn_workers > 1 or any(
        int(v) > 0 for v in workers.values() if isinstance(v, (int, str)) and str(v).isdigit()
    )

    if is_multi_worker:
        if not frappe.conf.get("use_redis_locks_for_sepa"):
            frappe.throw(
                _(
                    "SEPA processing requires Redis locks in multi-worker environment. "
                    "Set use_redis_locks_for_sepa=True in site_config.json or reduce workers to 1."
                )
            )


def _get_lock_ttl(operation_type: str = "default") -> int:
    """
    Get configurable lock TTL from site config.

    Allows operators to tune lock timeouts for their specific workload.
    Configuration keys: sepa_lock_ttl_default, sepa_lock_ttl_batch, etc.

    Args:
        operation_type: Type of operation (default, batch, reconciliation, mandate)

    Returns:
        TTL in seconds
    """
    config_key = f"sepa_lock_ttl_{operation_type}"
    configured = frappe.conf.get(config_key)
    if configured:
        return int(configured)

    defaults = {
        "default": DEFAULT_LOCK_TTL,
        "batch": DEFAULT_BATCH_LOCK_TTL,
        "reconciliation": DEFAULT_BATCH_LOCK_TTL,
        "mandate": DEFAULT_LOCK_TTL,
    }
    return defaults.get(operation_type, DEFAULT_LOCK_TTL)


# =============================================================================
# DUPLICATE PAYMENT PREVENTION
# =============================================================================


@critical_api(operation_type=OperationType.FINANCIAL)
def create_payment_entry_with_duplicate_check(invoice_name: str, amount: float, payment_data: Dict) -> Dict:
    """
    Create payment entry with comprehensive duplicate checking

    Args:
        invoice_name: Sales Invoice name
        amount: Payment amount
        payment_data: Payment entry data

    Returns:
        Payment entry creation result

    Raises:
        ValidationError: If duplicate payment detected
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing",
        "create_payment_entry_with_duplicate_check",
        {"invoice_name": invoice_name, "amount": amount},
    )

    # Check for existing payments
    existing_payments = frappe.get_all(
        "Payment Entry Reference",
        filters={
            "reference_name": invoice_name,
            "reference_doctype": "Sales Invoice",
            "parenttype": "Payment Entry",
        },
        fields=["parent", "allocated_amount"],
    )

    # Calculate total already allocated
    total_allocated = sum(flt(payment.allocated_amount) for payment in existing_payments)

    # Get invoice total to check against
    invoice_total = frappe.db.get_value("Sales Invoice", invoice_name, "grand_total")

    if not invoice_total:
        raise frappe.ValidationError(_("Invoice {0} not found or has no total amount").format(invoice_name))

    if total_allocated >= flt(invoice_total):
        raise frappe.ValidationError(
            _("Invoice {0} already fully paid. Total allocated: {1}, Invoice total: {2}").format(
                invoice_name, total_allocated, invoice_total
            )
        )

    if total_allocated + amount > flt(invoice_total):
        raise frappe.ValidationError(
            _(
                "Payment amount {0} would exceed invoice total. Already allocated: {1}, Invoice total: {2}"
            ).format(amount, total_allocated, invoice_total)
        )

    # Generate idempotency key
    idempotency_key = generate_idempotency_key(
        payment_data.get("custom_bank_transaction", ""),
        payment_data.get("custom_sepa_batch", ""),
        f"payment_{invoice_name}",
    )

    # Check if operation already executed
    return execute_idempotent_operation(idempotency_key, lambda: _create_payment_entry(payment_data))


def _create_payment_entry(payment_data: Dict) -> Dict:
    """Internal function to create payment entry"""
    payment_entry = frappe.get_doc(payment_data)
    payment_entry.insert()
    payment_entry.submit()

    return {"success": True, "payment_entry": payment_entry.name, "amount": payment_entry.paid_amount}


# =============================================================================
# BATCH PROCESSING PREVENTION
# =============================================================================


@critical_api(operation_type=OperationType.FINANCIAL)
def check_batch_processing_status(batch_name: str, transaction_name: str) -> None:
    """
    Check if SEPA batch has already been processed

    Args:
        batch_name: SEPA Direct Debit Batch name
        transaction_name: Bank Transaction name

    Raises:
        ValidationError: If batch already processed
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing",
        "check_batch_processing_status",
        {"batch_name": batch_name, "transaction_name": transaction_name},
    )

    # Check for existing payment entries linked to this batch
    existing_payments = frappe.get_all(
        "Payment Entry",
        filters={"custom_sepa_batch": batch_name, "docstatus": 1},  # Submitted payments only
        fields=["name", "custom_bank_transaction", "paid_amount"],
    )

    if existing_payments:
        # Check if any payments are from different bank transaction
        other_transactions = [p for p in existing_payments if p.custom_bank_transaction != transaction_name]

        if other_transactions:
            raise frappe.ValidationError(
                _("SEPA batch {0} has already been processed with different bank transaction(s): {1}").format(
                    batch_name, ", ".join([p.custom_bank_transaction for p in other_transactions[:3]])
                )
            )

        # Check if same transaction is being reprocessed
        same_transaction_payments = [
            p for p in existing_payments if p.custom_bank_transaction == transaction_name
        ]
        if same_transaction_payments:
            raise frappe.ValidationError(
                _("Bank transaction {0} has already been used to process SEPA batch {1}").format(
                    transaction_name, batch_name
                )
            )


@critical_api(operation_type=OperationType.FINANCIAL)
def check_return_file_processed(return_file_hash: str) -> None:
    """
    Check if return file has already been processed

    Args:
        return_file_hash: SHA256 hash of return file content

    Raises:
        ValidationError: If return file already processed
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing", "check_return_file_processed", {"file_hash": return_file_hash[:16] + "..."}
    )

    if frappe.db.exists("SEPA Return File Log", {"file_hash": return_file_hash}):
        raise frappe.ValidationError(_("Return file already processed"))


# =============================================================================
# PROCESSING LOCKS
# =============================================================================

# In-memory locks with TTL and owner tracking.
# Structure: {lock_key: (timestamp, ttl, lock_token)}
# NOTE: For production multi-worker deployments, set use_redis_locks_for_sepa=True
# in site_config to use Redis-based distributed locking.
_processing_locks: Dict[str, Tuple[float, int, str]] = {}

# Thread-local storage for lock tokens (allows release to verify ownership)
_lock_tokens: Dict[str, str] = {}

# Lock for thread-safe access to in-memory structures
_lock_mutex = threading.Lock()


def _generate_lock_token() -> str:
    """
    Generate a unique lock token for ownership verification.

    Uses UUID + PID + timestamp for uniqueness across processes and restarts.
    Does NOT use frappe.session.sid as it may be unavailable in background jobs.
    """
    return f"{uuid.uuid4().hex}:{os.getpid()}:{time.time()}"


def _get_redis_lock_key(resource_type: str, resource_id: str) -> str:
    """Generate Redis-compatible lock key"""
    return f"sepa_lock:{resource_type}:{resource_id}"


def _try_redis_lock(lock_key: str, timeout: int) -> Tuple[Optional[bool], Optional[str]]:
    """
    Try to acquire lock via Redis if available.

    Returns:
        (None, None) if Redis is not available/configured
        (True, lock_token) if lock acquired
        (False, None) if lock not acquired (held by another process)
    """
    try:
        # Check if Redis-based locking is enabled in site config
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            return (None, None)

        cache = frappe.cache()

        # Verify cache.set supports nx parameter (Redis SETNX semantics)
        # Some cache backends may not support this
        if not hasattr(cache, "set"):
            frappe.logger().warning(
                "Redis cache does not support set() method. Falling back to in-memory locks."
            )
            return (None, None)

        # Generate unique lock token for ownership verification
        lock_token = _generate_lock_token()

        # Use Redis SETNX pattern for atomic lock acquisition
        # nx=True means "only set if key does not exist"
        # ex=timeout sets expiration in seconds
        result = cache.set(lock_key, lock_token, ex=timeout, nx=True)

        if result:
            # Store token for later release verification
            _lock_tokens[lock_key] = lock_token
            return (True, lock_token)
        return (False, None)

    except TypeError as e:
        # cache.set doesn't support nx/ex parameters
        frappe.logger().warning(
            f"Redis cache.set() does not support nx/ex parameters: {e}. " "Falling back to in-memory locks."
        )
        return (None, None)
    except Exception as e:
        # Redis not available or other error
        frappe.logger().debug(f"Redis lock acquisition failed: {e}. Using in-memory locks.")
        return (None, None)


def _release_redis_lock(lock_key: str) -> bool:
    """
    Release Redis lock with ownership verification.

    Only deletes the lock if the current process owns it (compare-and-delete).
    This prevents accidentally releasing a lock held by another process.
    """
    try:
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            return False

        # Get the token we used to acquire this lock
        our_token = _lock_tokens.get(lock_key)
        if not our_token:
            # We don't have a token for this lock - we didn't acquire it
            frappe.logger().debug(
                f"No lock token found for {lock_key}. Lock may have been acquired by another process."
            )
            return False

        cache = frappe.cache()

        # Compare-and-delete: only delete if the lock value matches our token
        # This is the safe pattern to avoid releasing another process's lock
        current_value = cache.get(lock_key)

        if current_value == our_token:
            cache.delete(lock_key)
            del _lock_tokens[lock_key]
            return True
        elif current_value is None:
            # Lock already expired or was released
            if lock_key in _lock_tokens:
                del _lock_tokens[lock_key]
            return True
        else:
            # Lock is held by another process (ours expired, they acquired it)
            frappe.logger().warning(f"Lock {lock_key} is now held by another process. Not releasing.")
            if lock_key in _lock_tokens:
                del _lock_tokens[lock_key]
            return False

    except Exception as e:
        frappe.logger().error(f"Error releasing Redis lock {lock_key}: {e}")
        return False


@high_security_api(operation_type=OperationType.FINANCIAL)
def acquire_processing_lock(resource_type: str, resource_id: str, timeout: int = None) -> bool:
    """
    Acquire processing lock to prevent concurrent operations.

    Uses Redis if available and configured (set use_redis_locks_for_sepa=True in site_config),
    otherwise falls back to in-memory locks (suitable for single-worker deployments only).

    In multi-worker production environments, Redis is REQUIRED. This function will
    fail fast if Redis is not configured but multiple workers are detected.

    Args:
        resource_type: Type of resource (e.g., 'sepa_batch', 'bank_transaction')
        resource_id: Unique identifier for resource
        timeout: Lock timeout in seconds (default: from _get_lock_ttl)

    Returns:
        True if lock acquired, False otherwise

    Raises:
        ValidationError: If Redis is required but not configured
    """
    # Check Redis requirement for multi-worker safety
    _check_redis_required()

    if timeout is None:
        timeout = _get_lock_ttl(resource_type)

    lock_key = f"{resource_type}:{resource_id}"
    redis_key = _get_redis_lock_key(resource_type, resource_id)

    # Try Redis first
    redis_result, lock_token = _try_redis_lock(redis_key, timeout)
    if redis_result is not None:
        return redis_result

    # Fall back to in-memory locking with thread safety
    with _lock_mutex:
        current_time = time.time()

        # Check if lock exists and is still valid
        if lock_key in _processing_locks:
            lock_time, lock_ttl, _ = _processing_locks[lock_key]
            if current_time - lock_time < lock_ttl:
                return False  # Lock still active
            else:
                # Lock expired, remove it
                del _processing_locks[lock_key]

        # Acquire new lock with TTL and ownership token
        lock_token = _generate_lock_token()
        _processing_locks[lock_key] = (current_time, timeout, lock_token)
        _lock_tokens[lock_key] = lock_token
        return True


@high_security_api(operation_type=OperationType.FINANCIAL)
def release_processing_lock(resource_type: str, resource_id: str) -> None:
    """
    Release processing lock with ownership verification.

    Only releases the lock if the current process/thread owns it.
    This prevents accidentally releasing locks held by other processes.
    """
    lock_key = f"{resource_type}:{resource_id}"
    redis_key = _get_redis_lock_key(resource_type, resource_id)

    # Try to release Redis lock (with ownership check)
    _release_redis_lock(redis_key)

    # Also release in-memory lock (with ownership check)
    with _lock_mutex:
        our_token = _lock_tokens.get(lock_key)
        if lock_key in _processing_locks:
            _, _, stored_token = _processing_locks[lock_key]
            if our_token and stored_token == our_token:
                del _processing_locks[lock_key]
                if lock_key in _lock_tokens:
                    del _lock_tokens[lock_key]
            else:
                frappe.logger().debug(f"Not releasing in-memory lock {lock_key}: ownership mismatch")


# =============================================================================
# IDEMPOTENCY HANDLING
# =============================================================================

# In-memory cache with TTL support. Structure: {key: (result, timestamp, ttl)}
# NOTE: For production multi-worker deployments, set use_redis_idempotency_cache=True
# in site_config to use Redis-based caching.
_operation_cache: Dict[str, Tuple[Any, float, int]] = {}

# Idempotency lock tokens for ownership verification
_idempotency_lock_tokens: Dict[str, str] = {}

# Lua script for atomic compare-and-delete (safe lock release)
# Only deletes the lock if the stored value matches our token
_REDIS_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class ConcurrentOperationError(Exception):
    """Raised when an operation is already in progress by another worker."""

    pass


def _acquire_idempotency_lock(lock_key: str, timeout: int = None) -> Optional[str]:
    """
    Acquire an idempotency lock using Redis SETNX for atomic acquisition.

    This ensures only one worker can execute an idempotent operation at a time.
    Uses exponential backoff for retries.

    Args:
        lock_key: The lock key (should include idempotency key)
        timeout: Maximum time to wait for lock acquisition in seconds

    Returns:
        Lock token if acquired, None if lock could not be acquired
    """
    if timeout is None:
        timeout = DEFAULT_IDEMPOTENCY_LOCK_TIMEOUT

    # Check Redis requirement for multi-worker safety
    _check_redis_required()

    # Generate unique token for ownership verification
    lock_token = f"{uuid.uuid4().hex}:{os.getpid()}:{time.time()}"
    lock_ttl = timeout * 2  # Lock TTL is 2x the acquisition timeout

    # Try Redis first if configured
    if frappe.conf.get("use_redis_locks_for_sepa", False):
        try:
            cache = frappe.cache()
            redis_key = f"sepa_idempotency_lock:{lock_key}"

            start_time = time.time()
            attempt = 0

            while (time.time() - start_time) < timeout:
                # Try to set the lock with our token (NX = only if not exists)
                result = cache.set(redis_key, lock_token, ex=lock_ttl, nx=True)

                if result:
                    # Lock acquired - store token for release verification
                    _idempotency_lock_tokens[lock_key] = lock_token
                    return lock_token

                # Lock not acquired, wait with exponential backoff
                attempt += 1
                wait_time = min(0.1 * (2**attempt), 2.0)  # Max 2 second wait
                time.sleep(wait_time)

            # Timeout - could not acquire lock
            return None

        except Exception as e:
            frappe.logger().warning(f"Redis idempotency lock failed: {e}. Falling back to in-memory.")

    # In-memory fallback (single-worker only)
    with _lock_mutex:
        current_time = time.time()

        # Check if lock exists and is still valid
        if lock_key in _idempotency_lock_tokens:
            # Lock exists - check if expired (using processing_locks for TTL tracking)
            if lock_key in _processing_locks:
                lock_time, ttl, _ = _processing_locks[lock_key]
                if current_time - lock_time < ttl:
                    return None  # Lock still active

        # Acquire lock
        _idempotency_lock_tokens[lock_key] = lock_token
        _processing_locks[lock_key] = (current_time, lock_ttl, lock_token)
        return lock_token


def _release_idempotency_lock(lock_key: str, lock_token: str) -> bool:
    """
    Release an idempotency lock with ownership verification.

    Uses Lua script for atomic compare-and-delete to prevent accidentally
    releasing a lock that was acquired by another process (after our lock
    expired and they re-acquired it).

    Args:
        lock_key: The lock key
        lock_token: Token returned by _acquire_idempotency_lock

    Returns:
        True if lock was released, False otherwise
    """
    # Try Redis first if configured
    if frappe.conf.get("use_redis_locks_for_sepa", False):
        try:
            cache = frappe.cache()
            redis_key = f"sepa_idempotency_lock:{lock_key}"

            # Use Lua script for atomic compare-and-delete
            # This is safer than get-then-delete as it's atomic
            redis_client = cache.connection
            if hasattr(redis_client, "eval"):
                result = redis_client.eval(_REDIS_RELEASE_LOCK_SCRIPT, 1, redis_key, lock_token)
            else:
                # Fallback: check and delete (slightly less safe but functional)
                current_value = cache.get(redis_key)
                if current_value == lock_token:
                    cache.delete(redis_key)
                    result = 1
                else:
                    result = 0

            # Clean up local token regardless of result
            if lock_key in _idempotency_lock_tokens:
                del _idempotency_lock_tokens[lock_key]

            return bool(result)

        except Exception as e:
            frappe.logger().warning(f"Redis idempotency lock release failed: {e}")
            # Clean up local token
            if lock_key in _idempotency_lock_tokens:
                del _idempotency_lock_tokens[lock_key]
            return False

    # In-memory fallback
    with _lock_mutex:
        stored_token = _idempotency_lock_tokens.get(lock_key)
        if stored_token == lock_token:
            del _idempotency_lock_tokens[lock_key]
            if lock_key in _processing_locks:
                del _processing_locks[lock_key]
            return True
        return False


# Lock for thread-safe cache operations
_cache_mutex = threading.Lock()

# Maximum cache entries to prevent unbounded memory growth (in-memory only)
_MAX_CACHE_ENTRIES = 10000


def _extract_cacheable_result(result: Dict) -> Dict:
    """
    Extract minimal cacheable data from operation result.

    Stores only essential fields to minimize serialization overhead and memory usage.
    Full audit details should be written to database, not cached.
    """
    if not isinstance(result, dict):
        return {"success": bool(result), "cached": True}

    # Extract only essential fields for idempotency verification
    cacheable = {
        "success": result.get("success", True),
        "cached": True,  # Mark as cached result
    }

    # Include key identifiers if present
    if "payment_entry" in result:
        cacheable["payment_entry"] = result["payment_entry"]
    if "payment_entry_name" in result:
        cacheable["payment_entry_name"] = result["payment_entry_name"]
    if "batch" in result:
        cacheable["batch"] = result["batch"]
    if "error" in result:
        cacheable["error"] = str(result["error"])[:200]  # Truncate long errors

    return cacheable


def _cleanup_expired_cache_entries() -> None:
    """
    Remove expired entries from in-memory cache.

    Must be called with _cache_mutex held for thread safety.
    """
    current_time = time.time()
    expired_keys = [
        key for key, (_, timestamp, ttl) in _operation_cache.items() if current_time - timestamp >= ttl
    ]
    for key in expired_keys:
        del _operation_cache[key]


def _get_cached_result(idempotency_key: str, ttl: int = None) -> Tuple[bool, Optional[Dict]]:
    """
    Get cached result for idempotency key.
    Returns (found, result) tuple.
    """
    if ttl is None:
        ttl = DEFAULT_CACHE_TTL

    # Try Redis first if configured
    try:
        if frappe.conf.get("use_redis_idempotency_cache", False):
            cache = frappe.cache()
            redis_key = f"sepa_idempotency:{idempotency_key}"
            cached = cache.get(redis_key)
            if cached is not None:
                return (True, cached)
            return (False, None)
    except Exception as e:
        frappe.logger().debug(f"Redis cache get failed for {idempotency_key}: {e}. Using in-memory cache.")

    # Check in-memory cache (thread-safe read)
    with _cache_mutex:
        if idempotency_key in _operation_cache:
            result, timestamp, entry_ttl = _operation_cache[idempotency_key]
            current_time = time.time()
            if current_time - timestamp < entry_ttl:
                return (True, result)
            else:
                # Expired, remove it
                del _operation_cache[idempotency_key]

    return (False, None)


def _set_cached_result(idempotency_key: str, result: Dict, ttl: int = None) -> None:
    """
    Store minimal result data in cache with TTL.

    Only stores essential fields (success, key identifiers) to minimize
    serialization overhead. Full results should be in database audit logs.
    """
    if ttl is None:
        ttl = DEFAULT_CACHE_TTL

    # Extract minimal cacheable data
    cacheable_result = _extract_cacheable_result(result)

    # Try Redis first if configured
    try:
        if frappe.conf.get("use_redis_idempotency_cache", False):
            cache = frappe.cache()
            redis_key = f"sepa_idempotency:{idempotency_key}"
            # Use frappe.as_json for consistent serialization
            cache.set(redis_key, frappe.as_json(cacheable_result), ex=ttl)
            return
    except Exception as e:
        frappe.logger().warning(f"Redis cache set failed for {idempotency_key}: {e}. Using in-memory cache.")

    # Store in in-memory cache with thread safety
    with _cache_mutex:
        # Cleanup old entries if cache is getting too large
        if len(_operation_cache) >= _MAX_CACHE_ENTRIES:
            _cleanup_expired_cache_entries()
            # If still too large after cleanup, remove oldest entries
            if len(_operation_cache) >= _MAX_CACHE_ENTRIES:
                oldest_keys = sorted(_operation_cache.keys(), key=lambda k: _operation_cache[k][1])[
                    : _MAX_CACHE_ENTRIES // 10
                ]
            for key in oldest_keys:
                del _operation_cache[key]

    _operation_cache[idempotency_key] = (result, time.time(), ttl)


@standard_api(operation_type=OperationType.FINANCIAL)
def generate_idempotency_key(bank_transaction: str, batch: str, operation: str) -> str:
    """
    Generate unique idempotency key for operation.

    Note: The key is based on the operation inputs only, not on the user,
    to ensure the same operation produces the same key regardless of who
    executes it (important for scheduled jobs and retry scenarios).

    Args:
        bank_transaction: Bank transaction identifier
        batch: SEPA batch identifier
        operation: Operation type

    Returns:
        SHA256 hash as idempotency key
    """
    # Note: frappe.session.user is intentionally NOT included in the key
    # to ensure idempotency works across different users/scheduled jobs
    content = f"{bank_transaction}:{batch}:{operation}"
    return hashlib.sha256(content.encode()).hexdigest()


@critical_api(operation_type=OperationType.FINANCIAL)
def execute_idempotent_operation(idempotency_key: str, operation_func, ttl: int = None) -> Dict:
    """
    Execute operation with atomic idempotency protection.

    Uses lock-then-check pattern to ensure only one worker executes an operation:
    1. Acquire exclusive lock on idempotency key
    2. Check cache (double-check after acquiring lock)
    3. Execute operation if not cached
    4. Cache result
    5. Release lock

    This prevents race conditions where two workers both find nothing in cache
    and both execute the operation.

    Args:
        idempotency_key: Unique key for operation
        operation_func: Function to execute
        ttl: Cache TTL in seconds (default: DEFAULT_CACHE_TTL)

    Returns:
        Operation result

    Raises:
        ConcurrentOperationError: If another worker is executing this operation
    """
    if ttl is None:
        ttl = DEFAULT_CACHE_TTL

    # Step 1: Quick check before acquiring lock (optimization)
    found, cached_result = _get_cached_result(idempotency_key, ttl)
    if found:
        frappe.logger().info(f"Returning cached result for idempotency key: {idempotency_key[:16]}...")
        return cached_result

    # Step 2: Acquire exclusive lock on this idempotency key
    lock_token = _acquire_idempotency_lock(idempotency_key, timeout=DEFAULT_IDEMPOTENCY_LOCK_TIMEOUT)

    if not lock_token:
        # Another worker is processing this operation
        # Wait briefly and check if result is now cached
        time.sleep(0.5)
        found, cached_result = _get_cached_result(idempotency_key, ttl)
        if found:
            frappe.logger().info(
                f"Returning result from concurrent worker for idempotency key: {idempotency_key[:16]}..."
            )
            return cached_result

        # Still no result - operation may be in progress or failed
        raise ConcurrentOperationError(_("Operation in progress by another worker. Please wait and retry."))

    try:
        # Step 3: Double-check cache after acquiring lock
        # This handles the case where another worker completed just before we got the lock
        found, cached_result = _get_cached_result(idempotency_key, ttl)
        if found:
            frappe.logger().info(
                f"Returning cached result (post-lock) for idempotency key: {idempotency_key[:16]}..."
            )
            return cached_result

        # Step 4: Execute operation (we have exclusive lock)
        try:
            result = operation_func()
            _set_cached_result(idempotency_key, result, ttl)
            return result
        except Exception as e:
            # Don't cache failures - allow retry
            frappe.logger().error(f"Operation failed for idempotency key {idempotency_key[:16]}...: {str(e)}")
            raise

    finally:
        # Step 5: Always release lock
        _release_idempotency_lock(idempotency_key, lock_token)


# =============================================================================
# AMOUNT MATCHING WITH TOLERANCE
# =============================================================================


def _to_decimal(value: Any) -> Decimal:
    """
    Safely convert a value to Decimal for precise monetary arithmetic.

    Args:
        value: Value to convert (float, int, str, or Decimal)

    Returns:
        Decimal representation of the value
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    # Convert via string to avoid float precision issues
    return Decimal(str(value))


def amounts_match_with_tolerance(expected: Any, actual: Any, tolerance: Any = "0.02") -> bool:
    """
    Check if amounts match within tolerance using Decimal arithmetic.

    Uses Decimal for precise monetary comparisons to avoid floating-point
    rounding errors that could cause false positives/negatives.

    Args:
        expected: Expected amount (float, int, str, or Decimal)
        actual: Actual amount received (float, int, str, or Decimal)
        tolerance: Maximum difference allowed (default: "0.02" EUR/2 cents).
            Note: Default is a string to avoid float precision issues when
            converting to Decimal. Using 0.02 (float) could introduce subtle
            rounding errors; "0.02" (string) converts exactly to Decimal.

    Returns:
        True if amounts match within tolerance
    """
    expected_decimal = _to_decimal(expected)
    actual_decimal = _to_decimal(actual)
    tolerance_decimal = _to_decimal(tolerance)

    difference = abs(expected_decimal - actual_decimal)
    return difference <= tolerance_decimal


# =============================================================================
# SPLIT PAYMENT DETECTION
# =============================================================================

# Limits for combinatorial search to prevent exponential blowup
MAX_BATCHES_FOR_COMBINATION = 20  # Max batches to consider for combination search
MAX_COMBINATION_DEPTH = 5  # Max number of batches in a combination
MAX_COMBINATION_ITERATIONS = 1000  # Max recursive calls before giving up


@standard_api(operation_type=OperationType.FINANCIAL)
def identify_split_payment_scenario(
    bank_transaction, max_depth: int = None, max_iterations: int = None
) -> List[Dict]:
    """
    Identify scenarios where one bank transaction covers multiple SEPA batches.

    Uses bounded combinatorial search with configurable limits to prevent
    exponential blowup with large numbers of batches.

    Args:
        bank_transaction: Bank transaction document
        max_depth: Max batches in a combination (default: MAX_COMBINATION_DEPTH)
        max_iterations: Max search iterations (default: MAX_COMBINATION_ITERATIONS)

    Returns:
        List of possible batch combinations, sorted by preference (fewer batches first)
    """
    if max_depth is None:
        max_depth = MAX_COMBINATION_DEPTH
    if max_iterations is None:
        max_iterations = MAX_COMBINATION_ITERATIONS

    transaction_amount = _to_decimal(bank_transaction.deposit)
    transaction_date = bank_transaction.date

    # Get potential batches within date range
    date_range_start = transaction_date if transaction_date else getdate()
    date_range_end = date_range_start  # Same day for split payments

    potential_batches = frappe.get_all(
        "Direct Debit Batch",
        filters={
            "batch_date": ["between", [date_range_start, date_range_end]],
            "docstatus": 1,
            "status": ["in", ["Submitted", "Generated"]],
        },
        fields=["name", "total_amount", "batch_date", "entry_count"],
        limit=MAX_BATCHES_FOR_COMBINATION,  # Limit number of batches to consider
    )

    # If too many batches, log warning and return empty (manual review needed)
    if len(potential_batches) >= MAX_BATCHES_FOR_COMBINATION:
        frappe.logger().warning(
            f"Too many potential batches ({len(potential_batches)}) for combination search. "
            "Manual review required."
        )

    # Find combinations that sum to transaction amount
    valid_combinations = []
    iteration_count = [0]  # Use list to allow mutation in nested function

    def find_combinations(batches, target_amount, current_combination=None, start_index=0, depth=0):
        # Check iteration limit
        iteration_count[0] += 1
        if iteration_count[0] > max_iterations:
            return

        # Check depth limit
        if depth > max_depth:
            return

        if current_combination is None:
            current_combination = []

        current_sum = sum(_to_decimal(batch["total_amount"]) for batch in current_combination)

        # Check if we've found a valid combination
        if amounts_match_with_tolerance(current_sum, target_amount):
            valid_combinations.append(
                {
                    "batches": current_combination.copy(),
                    "total_amount": float(current_sum),
                    "batch_count": len(current_combination),
                }
            )
            return

        # If sum exceeds target, stop exploring this path
        if current_sum > target_amount:
            return

        # Try adding each remaining batch
        for i in range(start_index, len(batches)):
            if iteration_count[0] > max_iterations:
                break
            batch = batches[i]
            current_combination.append(batch)
            find_combinations(batches, target_amount, current_combination, i + 1, depth + 1)
            current_combination.pop()

    find_combinations(potential_batches, transaction_amount)

    # Log if we hit iteration limit
    if iteration_count[0] > max_iterations:
        frappe.logger().warning(
            f"Hit iteration limit ({max_iterations}) in split payment detection. "
            f"Found {len(valid_combinations)} combinations before stopping."
        )

    # Sort by preference (fewer batches preferred)
    valid_combinations.sort(key=lambda x: x["batch_count"])

    return valid_combinations


# =============================================================================
# PARTIAL SUCCESS ITEM IDENTIFICATION
# =============================================================================

# Limits for partial success item matching
MAX_ITEMS_FOR_PARTIAL_MATCH = 50  # Max items to consider for combination search
MAX_PARTIAL_MATCH_DEPTH = 10  # Max items in a combination
MAX_PARTIAL_MATCH_ITERATIONS = 5000  # Max recursive calls before giving up


@standard_api(operation_type=OperationType.FINANCIAL)
def identify_partial_success_items(
    batch_items: List[Dict],
    received_amount: Any,
    max_depth: int = None,
    max_iterations: int = None,
) -> List[List[Dict]]:
    """
    Identify which batch items match the received amount in partial success scenarios.

    Uses bounded combinatorial search with configurable limits to prevent
    exponential blowup with large batches.

    Args:
        batch_items: List of items in SEPA batch
        received_amount: Amount actually received (float, int, str, or Decimal)
        max_depth: Max items in a combination (default: MAX_PARTIAL_MATCH_DEPTH)
        max_iterations: Max search iterations (default: MAX_PARTIAL_MATCH_ITERATIONS)

    Returns:
        List of possible item combinations
    """
    if max_depth is None:
        max_depth = MAX_PARTIAL_MATCH_DEPTH
    if max_iterations is None:
        max_iterations = MAX_PARTIAL_MATCH_ITERATIONS

    # Convert received amount to Decimal
    target_amount = _to_decimal(received_amount)

    # Limit items to consider
    items_to_search = batch_items[:MAX_ITEMS_FOR_PARTIAL_MATCH]

    if len(batch_items) > MAX_ITEMS_FOR_PARTIAL_MATCH:
        frappe.logger().warning(
            f"Batch has {len(batch_items)} items, limiting partial match search to "
            f"{MAX_ITEMS_FOR_PARTIAL_MATCH} items. Manual review may be needed."
        )

    valid_combinations = []
    iteration_count = [0]  # Use list to allow mutation in nested function

    def find_item_combinations(items, target, current_combination=None, start_index=0, depth=0):
        # Check iteration limit
        iteration_count[0] += 1
        if iteration_count[0] > max_iterations:
            return

        # Check depth limit
        if depth > max_depth:
            return

        if current_combination is None:
            current_combination = []

        current_sum = sum(_to_decimal(item["amount"]) for item in current_combination)

        # Check if we've found a valid combination
        if amounts_match_with_tolerance(current_sum, target):
            valid_combinations.append(current_combination.copy())
            return

        # If sum exceeds target, stop exploring this path
        if current_sum > target:
            return

        # Try adding each remaining item
        for i in range(start_index, len(items)):
            if iteration_count[0] > max_iterations:
                break
            item = items[i]
            current_combination.append(item)
            find_item_combinations(items, target, current_combination, i + 1, depth + 1)
            current_combination.pop()

    find_item_combinations(items_to_search, target_amount)

    # Log if we hit iteration limit
    if iteration_count[0] > max_iterations:
        frappe.logger().warning(
            f"Hit iteration limit ({max_iterations}) in partial success item matching. "
            f"Found {len(valid_combinations)} combinations before stopping."
        )

    return valid_combinations


# =============================================================================
# TRANSACTION ORDERING
# =============================================================================


def process_out_of_order_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    Sort transactions in chronological order for proper processing

    Args:
        transactions: List of bank transactions

    Returns:
        Transactions sorted by date
    """
    return sorted(transactions, key=lambda t: t.get("date", getdate()))


# =============================================================================
# DATA INTEGRITY CHECKS
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def detect_orphaned_payments() -> List[Dict]:
    """
    Detect payment entries without corresponding bank transactions

    Returns:
        List of orphaned payment entries
    """
    # Get all SEPA-related payment entries
    sepa_payments = frappe.get_all(
        "Payment Entry",
        filters={"custom_sepa_batch": ["!=", ""], "docstatus": 1},
        fields=["name", "custom_bank_transaction", "custom_sepa_batch", "paid_amount"],
    )

    orphaned = []

    for payment in sepa_payments:
        bank_transaction = payment.custom_bank_transaction

        if not bank_transaction:
            orphaned.append(
                {
                    "name": payment.name,
                    "reason": "Missing bank transaction reference",
                    "sepa_batch": payment.custom_sepa_batch,
                }
            )
        elif not frappe.db.exists("Bank Transaction", bank_transaction):
            orphaned.append(
                {
                    "name": payment.name,
                    "reason": "Referenced bank transaction does not exist",
                    "missing_transaction": bank_transaction,
                    "sepa_batch": payment.custom_sepa_batch,
                }
            )

    return orphaned


@standard_api(operation_type=OperationType.FINANCIAL)
def detect_incomplete_reversals() -> List[Dict]:
    """
    Detect incomplete payment reversals from return processing

    Returns:
        List of incomplete reversals
    """
    # Find return file logs that have been processed
    return_records = frappe.get_all(
        "SEPA Return File Log",
        filters={"status": "Completed"},
        fields=["name", "processing_result", "return_count", "processed_by"],
    )

    incomplete = []

    for return_record in return_records:
        # Parse return data from processing result
        try:
            if not return_record.processing_result:
                continue

            # This is a simplified check - actual implementation would need
            # to parse the SEPA return file format and check individual returns
            # TODO: Parse return_data = json.loads(return_record.processing_result) for detailed analysis
            if return_record.return_count > 0:
                incomplete.append(
                    {
                        "return_file_log": return_record.name,
                        "return_count": return_record.return_count,
                        "reason": "Return file processed but individual return handling may need review",
                        "processed_by": return_record.processed_by,
                    }
                )

        except Exception as e:
            # Skip records with invalid JSON
            frappe.logger().warning(f"Could not parse processing_result for {return_record.name}: {str(e)}")
            continue

    return incomplete


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def validate_batch_mandates(batch_data: Dict) -> Dict:
    """
    Validate that all batch items have valid SEPA mandates

    Args:
        batch_data: SEPA batch data

    Returns:
        Validation result with missing mandates
    """
    missing_mandates = []

    for item in batch_data.get("invoices", []):
        customer = item.get("customer")

        if not customer:
            missing_mandates.append({"invoice": item.get("invoice"), "reason": "No customer specified"})
            continue

        # Check for active SEPA mandate
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": customer, "status": "Active", "is_active": 1, "used_for_memberships": 1},
            fields=["name", "mandate_id"],
        )

        if not active_mandates:
            missing_mandates.append(
                {
                    "customer": customer,
                    "invoice": item.get("invoice"),
                    "reason": "No active SEPA mandate found",
                }
            )

    return {
        "valid": len(missing_mandates) == 0,
        "missing_mandates": missing_mandates,
        "total_items": len(batch_data.get("invoices", [])),
        "valid_items": len(batch_data.get("invoices", [])) - len(missing_mandates),
    }


@standard_api(operation_type=OperationType.FINANCIAL)
def validate_bank_details_consistency(batch_data: Dict) -> Dict:
    """
    Validate consistency of bank details between batch creation and processing

    Args:
        batch_data: SEPA batch data

    Returns:
        Validation result with inconsistencies
    """
    iban_mismatches = []

    for item in batch_data.get("invoices", []):
        mandate_name = item.get("mandate")
        customer = item.get("customer")

        if not mandate_name or not customer:
            continue

        try:
            # Get mandate IBAN
            mandate = frappe.get_doc("SEPA Mandate", mandate_name)
            mandate_iban = mandate.iban.replace(" ", "").upper() if mandate.iban else ""

            # Get current member IBAN
            member = frappe.get_doc("Member", {"customer": customer})
            current_iban = member.iban.replace(" ", "").upper() if member.iban else ""

            if mandate_iban != current_iban:
                iban_mismatches.append(
                    {
                        "customer": customer,
                        "mandate": mandate_name,
                        "mandate_iban": mandate.iban,
                        "current_iban": member.iban,
                        "invoice": item.get("invoice"),
                    }
                )

        except frappe.DoesNotExistError:
            # Handle missing mandate or member gracefully
            pass

    return {
        "valid": len(iban_mismatches) == 0,
        "iban_mismatches": iban_mismatches,
        "total_items": len(batch_data.get("invoices", [])),
        "consistent_items": len(batch_data.get("invoices", [])) - len(iban_mismatches),
    }
