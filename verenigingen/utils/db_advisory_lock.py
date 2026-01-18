# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Database Advisory Lock Helper

Provides centralized advisory locking for preventing concurrent operations.
Uses MySQL/MariaDB GET_LOCK() function for database-level advisory locks.

IMPORTANT: Advisory locks are session-scoped in MySQL/MariaDB. They are
automatically released when the connection closes or when explicitly released.

Usage:
    from verenigingen.utils.db_advisory_lock import advisory_lock, get_lock, release_lock

    # Context manager (preferred)
    with advisory_lock("member_id_bulk_assignment", timeout=10):
        # Critical section
        ...

    # Manual locking (when context manager isn't suitable)
    if get_lock("my_lock", timeout=5):
        try:
            # Critical section
            ...
        finally:
            release_lock("my_lock")

Database Support:
    - MySQL/MariaDB: Uses GET_LOCK() / RELEASE_LOCK()
    - PostgreSQL: Not currently supported (raises NotImplementedError)

See: docs/patterns/ADVISORY_LOCK_PATTERN.md
"""

from contextlib import contextmanager
from typing import Generator

import frappe

from verenigingen.constants.error_codes import ErrorCodes


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


def is_lock_held(lock_name: str) -> bool:
    """
    Check if a lock is currently held (by any session).

    Uses MySQL IS_USED_LOCK() function to check lock status.

    Args:
        lock_name: Name of the lock to check

    Returns:
        True if lock is held by any session, False otherwise

    Note:
        This is a point-in-time check. The lock status may change
        immediately after this function returns.
    """
    db_type = frappe.conf.get("db_type", "mariadb")

    if db_type in ("mariadb", "mysql"):
        result = frappe.db.sql("SELECT IS_USED_LOCK(%s)", (lock_name,))
        return result and result[0][0] is not None
    else:
        return False
