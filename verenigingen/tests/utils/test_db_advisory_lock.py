# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for Advisory Lock Helper.

Tests both MySQL/MariaDB and Redis backends for advisory locking.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.db_advisory_lock import (
    AdvisoryLockError,
    advisory_lock,
    advisory_lock_with_backend,
    get_lock,
    get_lock_with_backend,
    is_lock_held,
    release_lock,
    release_lock_with_backend,
    _detect_backend,
    _is_redis_available,
)


class TestAdvisoryLockError(EnhancedTestCase):
    """Test suite for AdvisoryLockError exception."""

    def test_error_with_all_attributes(self):
        """Test AdvisoryLockError with all attributes."""
        error = AdvisoryLockError(
            message="Lock failed",
            error_code="TEST_ERROR",
            lock_name="test_lock",
        )

        self.assertEqual(str(error), "Lock failed")
        self.assertEqual(error.error_code, "TEST_ERROR")
        self.assertEqual(error.lock_name, "test_lock")

    def test_error_with_minimal_attributes(self):
        """Test AdvisoryLockError with only message."""
        error = AdvisoryLockError("Simple error")

        self.assertEqual(str(error), "Simple error")
        self.assertIsNone(error.error_code)
        self.assertIsNone(error.lock_name)


class TestDatabaseAdvisoryLock(EnhancedTestCase):
    """Test suite for MySQL/MariaDB advisory locks."""

    def test_get_lock_acquires_lock(self):
        """Test that get_lock successfully acquires a lock."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        result = get_lock(lock_name, timeout=5)

        self.assertTrue(result)
        # Clean up
        release_lock(lock_name)

    def test_release_lock_releases_acquired_lock(self):
        """Test that release_lock releases an acquired lock."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Acquire lock
        get_lock(lock_name, timeout=5)

        # Release lock
        result = release_lock(lock_name)

        self.assertTrue(result)

    def test_release_lock_on_unacquired_lock(self):
        """Test that release_lock returns False for unacquired lock."""
        lock_name = f"nonexistent_lock_{frappe.generate_hash(length=8)}"

        result = release_lock(lock_name)

        self.assertFalse(result)

    def test_is_lock_held_returns_true_when_held(self):
        """Test is_lock_held returns True when lock is held."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        try:
            get_lock(lock_name, timeout=5)
            result = is_lock_held(lock_name)
            self.assertTrue(result)
        finally:
            release_lock(lock_name)

    def test_is_lock_held_returns_false_when_not_held(self):
        """Test is_lock_held returns False when lock is not held."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        result = is_lock_held(lock_name)

        self.assertFalse(result)


class TestAdvisoryLockContextManager(EnhancedTestCase):
    """Test suite for advisory_lock context manager."""

    def test_context_manager_acquires_and_releases_lock(self):
        """Test that context manager properly acquires and releases lock."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        with advisory_lock(lock_name, timeout=5) as acquired:
            self.assertTrue(acquired)
            # Lock should be held
            self.assertTrue(is_lock_held(lock_name))

        # Lock should be released after context exits
        self.assertFalse(is_lock_held(lock_name))

    def test_context_manager_releases_on_exception(self):
        """Test that lock is released even when exception occurs."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        try:
            with advisory_lock(lock_name, timeout=5):
                self.assertTrue(is_lock_held(lock_name))
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Lock should be released despite exception
        self.assertFalse(is_lock_held(lock_name))

    def test_context_manager_with_raise_on_timeout_true_mocked(self):
        """Test that context manager raises on timeout when lock unavailable."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Mock get_lock to simulate timeout (since MySQL locks are re-entrant in same session)
        with patch(
            "verenigingen.utils.db_advisory_lock.get_lock",
            return_value=False,
        ):
            with self.assertRaises(AdvisoryLockError) as context:
                with advisory_lock(lock_name, timeout=0, raise_on_timeout=True):
                    pass

            self.assertIn(lock_name, str(context.exception))

    def test_context_manager_with_raise_on_timeout_false_mocked(self):
        """Test that context manager yields False on timeout when configured."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Mock get_lock to simulate timeout (since MySQL locks are re-entrant in same session)
        with patch(
            "verenigingen.utils.db_advisory_lock.get_lock",
            return_value=False,
        ):
            with advisory_lock(lock_name, timeout=0, raise_on_timeout=False) as acquired:
                self.assertFalse(acquired)

    def test_mysql_lock_is_reentrant_in_same_session(self):
        """Test that MySQL GET_LOCK is re-entrant within same session.

        This is expected MySQL behavior - a session can re-acquire its own lock.
        This test documents this behavior.
        """
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Acquire lock first
        first_acquired = get_lock(lock_name, timeout=5)
        self.assertTrue(first_acquired)

        try:
            # Same session can re-acquire the lock (MySQL re-entrancy)
            second_acquired = get_lock(lock_name, timeout=0)
            self.assertTrue(second_acquired)  # MySQL allows this!
        finally:
            release_lock(lock_name)


class TestBackendDetection(EnhancedTestCase):
    """Test suite for backend detection."""

    def test_detect_backend_returns_database_when_redis_unavailable(self):
        """Test that _detect_backend returns 'database' when Redis unavailable."""
        with patch(
            "verenigingen.utils.db_advisory_lock._is_redis_available",
            return_value=False,
        ):
            result = _detect_backend()
            self.assertEqual(result, "database")

    def test_detect_backend_returns_redis_when_available(self):
        """Test that _detect_backend returns 'redis' when Redis available."""
        with patch(
            "verenigingen.utils.db_advisory_lock._is_redis_available",
            return_value=True,
        ):
            result = _detect_backend()
            self.assertEqual(result, "redis")

    def test_is_redis_available_returns_false_without_config(self):
        """Test that _is_redis_available returns False without Redis config."""
        # Store original value and temporarily remove redis_cache
        original_value = frappe.conf.get("redis_cache")
        try:
            frappe.conf["redis_cache"] = None
            result = _is_redis_available()
            self.assertFalse(result)
        finally:
            # Restore original value
            if original_value is not None:
                frappe.conf["redis_cache"] = original_value


class TestBackendAwareLocking(EnhancedTestCase):
    """Test suite for backend-aware locking functions."""

    def test_get_lock_with_database_backend(self):
        """Test get_lock_with_backend using database backend."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        try:
            result = get_lock_with_backend(lock_name, timeout=5, backend="database")
            self.assertTrue(result)
            self.assertTrue(is_lock_held(lock_name, backend="database"))
        finally:
            release_lock_with_backend(lock_name, backend="database")

    def test_release_lock_with_database_backend(self):
        """Test release_lock_with_backend using database backend."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        get_lock_with_backend(lock_name, timeout=5, backend="database")
        result = release_lock_with_backend(lock_name, backend="database")

        self.assertTrue(result)
        self.assertFalse(is_lock_held(lock_name, backend="database"))

    def test_advisory_lock_with_database_backend(self):
        """Test advisory_lock_with_backend using database backend."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        with advisory_lock_with_backend(
            lock_name, timeout=5, backend="database"
        ) as acquired:
            self.assertTrue(acquired)
            self.assertTrue(is_lock_held(lock_name, backend="database"))

        self.assertFalse(is_lock_held(lock_name, backend="database"))

    def test_advisory_lock_with_auto_backend(self):
        """Test advisory_lock_with_backend with auto backend detection."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Force database backend for predictable test
        with patch(
            "verenigingen.utils.db_advisory_lock._detect_backend",
            return_value="database",
        ):
            with advisory_lock_with_backend(
                lock_name, timeout=5, backend="auto"
            ) as acquired:
                self.assertTrue(acquired)


class TestRedisBackendMocked(EnhancedTestCase):
    """Test suite for Redis backend with mocked Redis client."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.mock_redis = MagicMock()
        self.mock_redis.ping.return_value = True
        self.mock_redis.set.return_value = True
        self.mock_redis.delete.return_value = 1
        self.mock_redis.exists.return_value = False

    def test_redis_lock_acquisition_mocked(self):
        """Test Redis lock acquisition with mocked client."""
        with patch(
            "verenigingen.utils.db_advisory_lock._get_redis_client",
            return_value=self.mock_redis,
        ):
            from verenigingen.utils.db_advisory_lock import _get_redis_lock

            result = _get_redis_lock("test_lock", timeout=5, ttl=60)

            self.assertTrue(result)
            self.mock_redis.set.assert_called()

    def test_redis_lock_release_mocked(self):
        """Test Redis lock release with mocked client."""
        with patch(
            "verenigingen.utils.db_advisory_lock._get_redis_client",
            return_value=self.mock_redis,
        ):
            from verenigingen.utils.db_advisory_lock import _release_redis_lock

            result = _release_redis_lock("test_lock")

            self.assertTrue(result)
            self.mock_redis.delete.assert_called_with("advisory_lock:test_lock")

    def test_redis_is_lock_held_mocked(self):
        """Test Redis lock check with mocked client."""
        self.mock_redis.exists.return_value = True

        with patch(
            "verenigingen.utils.db_advisory_lock._get_redis_client",
            return_value=self.mock_redis,
        ):
            from verenigingen.utils.db_advisory_lock import _is_redis_lock_held

            result = _is_redis_lock_held("test_lock")

            self.assertTrue(result)
            self.mock_redis.exists.assert_called_with("advisory_lock:test_lock")

    def test_redis_lock_timeout_returns_false(self):
        """Test Redis lock returns False on timeout."""
        # Simulate lock already held
        self.mock_redis.set.return_value = False

        with patch(
            "verenigingen.utils.db_advisory_lock._get_redis_client",
            return_value=self.mock_redis,
        ):
            from verenigingen.utils.db_advisory_lock import _get_redis_lock

            # Short timeout for fast test
            result = _get_redis_lock("test_lock", timeout=0.1, ttl=60)

            self.assertFalse(result)


class TestConcurrentLockAcquisition(EnhancedTestCase):
    """Test suite for concurrent lock acquisition scenarios."""

    def test_lock_contention_code_path_mocked(self):
        """Test that lock contention returns False via the backend-aware function.

        Note: MySQL GET_LOCK is session-scoped, so we mock the behavior
        to test the code path where lock is held by another session.
        """
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Mock at the point where get_lock_with_backend calls get_lock internally
        with patch(
            "verenigingen.utils.db_advisory_lock.get_lock",
            return_value=False,
        ):
            # Use get_lock_with_backend which calls the patched get_lock internally
            acquired = get_lock_with_backend(lock_name, timeout=0, backend="database")
            self.assertFalse(acquired)

    def test_lock_released_after_context_allows_reacquisition(self):
        """Test that lock can be reacquired after context manager exits."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # First acquisition
        with advisory_lock(lock_name, timeout=5) as acquired:
            self.assertTrue(acquired)

        # Second acquisition should succeed
        with advisory_lock(lock_name, timeout=5) as acquired:
            self.assertTrue(acquired)

    def test_lock_held_check_after_release(self):
        """Test that is_lock_held returns False after lock release."""
        lock_name = f"test_lock_{frappe.generate_hash(length=8)}"

        # Acquire and release
        get_lock(lock_name, timeout=5)
        release_lock(lock_name)

        # Should no longer be held
        self.assertFalse(is_lock_held(lock_name))


class TestLockNameValidation(EnhancedTestCase):
    """Test suite for lock name handling."""

    def test_long_lock_name_handling(self):
        """Test that long lock names are handled (max 64 chars in MySQL)."""
        # MySQL GET_LOCK has 64 char limit
        long_name = "a" * 64

        try:
            result = get_lock(long_name, timeout=5)
            self.assertTrue(result)
        finally:
            release_lock(long_name)

    def test_special_characters_in_lock_name(self):
        """Test lock names with special characters."""
        lock_name = f"test:lock:with:colons:{frappe.generate_hash(length=8)}"

        try:
            result = get_lock(lock_name, timeout=5)
            self.assertTrue(result)
        finally:
            release_lock(lock_name)
