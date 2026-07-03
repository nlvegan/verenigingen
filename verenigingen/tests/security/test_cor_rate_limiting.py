"""
COR (Critical Operation Rule) Rate Limiting Integration Tests

These tests verify that COR-based rate limiting actually enforces limits.
"""

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.rate_limit_engine import ExecutionContext


def _get_fresh_framework():
    """Return a fresh security-framework instance.

    Historically this deleted the api_security_framework module from sys.modules
    and re-imported it. That left the already-imported rate_limit_engine module
    in place while rebinding the framework, so the framework's rate_limiter ended
    up out of sync with the freshly-imported wrapper and silently bypassed the
    engine's force_check path. Resetting the module-level singleton and asking for
    a new instance is sufficient and keeps every component on the same module.
    """
    import importlib

    asf_module = importlib.import_module(
        "verenigingen.utils.security.api_security_framework"
    )
    # Reset the cached singleton so a brand-new framework (and rate limiter) is built.
    asf_module._security_framework = None
    return asf_module.get_security_framework()


def _clear_all_test_rate_limit_counters():
    """Clear all rate limit counters used by tests

    Note: We use delete() instead of delete_value() because setex() uses raw keys
    while delete_value() transforms keys with make_key().
    """
    test_operations = [
        "test_rate_limit_op_1",
        "test_rate_limit_op_3",
        "test_rate_limit_headers",
        "test_global_scope",
        "nonexistent_operation_xyz",
    ]
    site = frappe.local.site
    for op_name in test_operations:
        # Clear per-user counters (use delete() for raw key deletion).
        # Keys are site-namespaced (see RateLimitEngine._build_cache_key).
        frappe.cache().delete(f"cor_rate_limit:{site}:interactive:{op_name}:Administrator")
        # Clear global counters
        frappe.cache().delete(f"cor_rate_limit:{site}:interactive:{op_name}")


@contextmanager
def mock_http_request():
    """Mock an HTTP request context to force INTERACTIVE execution context.

    The rate limiting framework detects execution context based on the presence
    of frappe.local.request. Without an HTTP request, it defaults to BACKGROUND_JOB
    which skips rate limiting for operations without batch limits configured.
    """
    original_request = getattr(frappe.local, "request", None)
    try:
        # Create a mock request object with minimum required attributes
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}
        frappe.local.request = mock_request
        yield
    finally:
        if original_request is None:
            if hasattr(frappe.local, "request"):
                delattr(frappe.local, "request")
        else:
            frappe.local.request = original_request


class TestCORRateLimitingEnforcement(EnhancedTestCase):
    """Test that COR rate limiting actually enforces limits"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Force reload module to pick up any code changes
        cls.framework = _get_fresh_framework()

    def setUp(self):
        super().setUp()
        frappe.cache().delete_value("critical_operation_rules")
        self._created_cors = []
        # Clean up leftover test COR records from previous runs
        self._cleanup_test_cors()
        # Clear all rate limit counters
        _clear_all_test_rate_limit_counters()

    def _cleanup_test_cors(self):
        """Clean up any leftover test COR records from previous test runs"""
        test_cor_patterns = [
            "test_rate_limit_op_%",
            "test_global_scope",
            "test_rate_limit_headers",
        ]
        for pattern in test_cor_patterns:
            try:
                existing = frappe.get_all(
                    "Critical Operation Rule",
                    filters={"operation_name": ["like", pattern]},
                    pluck="name",
                )
                for name in existing:
                    frappe.delete_doc("Critical Operation Rule", name, force=True)
                if existing:
                    frappe.db.commit()
            except Exception:
                pass

    def tearDown(self):
        for cor_name in self._created_cors:
            try:
                frappe.delete_doc("Critical Operation Rule", cor_name, force=True)
                frappe.db.commit()
            except Exception:
                pass
        frappe.cache().delete_value("critical_operation_rules")
        super().tearDown()

    def _create_test_cor(
        self,
        operation_name: str,
        rate_limit_calls: int = 3,
        rate_limit_period_seconds: int = 60,
        rate_limit_scope: str = "per_user",
    ) -> str:
        """Create a test COR record and track it for cleanup"""
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": operation_name,
            "operation_type": "utility",
            "security_level": "low",
            "enabled": 1,
            "rate_limit_calls": rate_limit_calls,
            "rate_limit_period_seconds": rate_limit_period_seconds,
            "rate_limit_scope": rate_limit_scope,
            "audit_level": "minimal",
            "requires_justification": 0,
        })
        cor.flags.ignore_permissions = True
        cor.insert()
        frappe.db.commit()  # Commit to ensure COR is visible to db.get_value
        self._created_cors.append(cor.name)
        frappe.cache().delete_value(f"critical_operation_rule:{operation_name}")
        return cor.name

    def _clear_rate_limit_counter(self, operation_name: str, user: str = "Administrator"):
        """Clear the Redis rate limit counter for a specific operation

        Note: We use delete() instead of delete_value() because setex() uses raw keys
        while delete_value() transforms keys with make_key().
        """
        cache_key = f"cor_rate_limit:{frappe.local.site}:interactive:{operation_name}:{user}"
        frappe.cache().delete(cache_key)

    def test_cor_rate_limit_enforces_after_max_calls(self):
        """Verify that rate limit is enforced after max calls exceeded"""
        operation_name = "test_rate_limit_op_1"
        self._create_test_cor(
            operation_name=operation_name,
            rate_limit_calls=3,
            rate_limit_period_seconds=300,
        )
        self._clear_rate_limit_counter(operation_name)

        with self.set_user("Administrator"):
            original_in_test = getattr(frappe.flags, "in_test", False)
            try:
                frappe.flags.in_test = False

                # Mock HTTP request to force INTERACTIVE context
                with mock_http_request():
                    self._clear_rate_limit_counter(operation_name)
                    interactive = ExecutionContext.INTERACTIVE
                    # First 3 calls should be allowed
                    for i in range(3):
                        result = self.framework.rate_limiter.check_rate_limit(
                            operation_name, context=interactive, force_check=True
                        )
                        self.assertTrue(result.allowed, f"Call {i+1} should succeed")
                        self.assertEqual(result.current_count, i + 1)

                    # 4th call should be rate limited
                    result = self.framework.rate_limiter.check_rate_limit(
                        operation_name, context=interactive, force_check=True
                    )
                    self.assertFalse(result.allowed, "4th call should exceed the limit")
                    self.assertEqual(result.current_count, 4)
                    self.assertEqual(result.max_calls, 3)

            finally:
                frappe.flags.in_test = original_in_test

    def test_cor_rate_limit_counter_in_redis(self):
        """Verify that rate limit counters are stored correctly in Redis"""
        operation_name = "test_rate_limit_op_3"
        self._create_test_cor(
            operation_name=operation_name,
            rate_limit_calls=5,
            rate_limit_period_seconds=300,
        )

        with self.set_user("Administrator"):
            self._clear_rate_limit_counter(operation_name)
            cache_key = f"cor_rate_limit:{frappe.local.site}:interactive:{operation_name}:Administrator"

            original_in_test = getattr(frappe.flags, "in_test", False)
            try:
                frappe.flags.in_test = False

                # Mock HTTP request to force INTERACTIVE context
                with mock_http_request():
                    # Make 3 calls through the rate limit engine
                    for _ in range(3):
                        self.framework.rate_limiter.check_rate_limit(
                            operation_name,
                            context=ExecutionContext.INTERACTIVE,
                            force_check=True,
                        )

                    # Counter should be 3
                    current = int(frappe.cache().get(cache_key) or 0)
                    self.assertEqual(current, 3, "Redis counter should be 3 after 3 calls")

            finally:
                frappe.flags.in_test = original_in_test

    def test_cor_not_found_raises_error(self):
        """Verify that missing COR configuration raises an error"""
        operation_name = "nonexistent_operation_xyz"

        with self.set_user("Administrator"):
            original_in_test = getattr(frappe.flags, "in_test", False)
            fallback_was_enabled = False

            try:
                frappe.flags.in_test = False

                # Temporarily disable the _generic_api_fallback COR
                fallback_cor = frappe.db.get_value(
                    "Critical Operation Rule",
                    {"operation_name": "_generic_api_fallback"},
                    "name",
                )
                if fallback_cor:
                    fallback_was_enabled = frappe.db.get_value(
                        "Critical Operation Rule", fallback_cor, "enabled"
                    )
                    frappe.db.set_value(
                        "Critical Operation Rule", fallback_cor, "enabled", 0
                    )
                    frappe.db.commit()

                # Mock HTTP request to force INTERACTIVE context
                with mock_http_request():
                    with self.assertRaises(VPermissionError) as context:
                        self.framework.rate_limiter.check_rate_limit(
                            operation_name,
                            context=ExecutionContext.INTERACTIVE,
                            force_check=True,
                        )

                    self.assertIn("No rate limiting configuration found", str(context.exception))

            finally:
                frappe.flags.in_test = original_in_test
                # Restore the _generic_api_fallback COR
                if fallback_cor and fallback_was_enabled:
                    frappe.db.set_value(
                        "Critical Operation Rule", fallback_cor, "enabled", 1
                    )
                    frappe.db.commit()

    def test_maintenance_flags_bypass_rate_limit(self):
        """Install/migrate/patch phases must skip the fail-closed COR lookup.

        The COR fixture (_generic_api_fallback) is loaded by sync_fixtures, which
        runs AFTER after_install hooks and after patches. A security-decorated
        function reached from a lifecycle hook or patch would otherwise raise
        "No rate limiting configuration found" and abort the install/migrate.
        With no COR configured, each maintenance flag must yield an allowed
        result rather than raising.
        """
        operation_name = "nonexistent_operation_during_setup"

        with self.set_user("Administrator"):
            original_in_test = getattr(frappe.flags, "in_test", False)
            fallback_cor = None
            fallback_was_enabled = False

            try:
                frappe.flags.in_test = False

                # Disable the generic fallback so the fail-closed branch is the
                # only thing that could stop us.
                fallback_cor = frappe.db.get_value(
                    "Critical Operation Rule",
                    {"operation_name": "_generic_api_fallback"},
                    "name",
                )
                if fallback_cor:
                    fallback_was_enabled = frappe.db.get_value(
                        "Critical Operation Rule", fallback_cor, "enabled"
                    )
                    frappe.db.set_value("Critical Operation Rule", fallback_cor, "enabled", 0)
                    frappe.db.commit()

                for flag in ("in_install", "in_migrate", "in_patch"):
                    with mock_http_request():
                        original_flag = getattr(frappe.flags, flag, False)
                        try:
                            setattr(frappe.flags, flag, True)
                            result = self.framework.rate_limiter.check_rate_limit(
                                operation_name,
                                context=ExecutionContext.INTERACTIVE,
                            )
                            self.assertTrue(
                                result.allowed,
                                f"rate limit should be bypassed while frappe.flags.{flag} is set",
                            )
                        finally:
                            setattr(frappe.flags, flag, original_flag)

            finally:
                frappe.flags.in_test = original_in_test
                if fallback_cor and fallback_was_enabled:
                    frappe.db.set_value("Critical Operation Rule", fallback_cor, "enabled", 1)
                    frappe.db.commit()

    def test_cor_rate_limit_headers_generation(self):
        """Verify that rate limit headers are generated correctly"""
        operation_name = "test_rate_limit_headers"
        self._create_test_cor(
            operation_name=operation_name,
            rate_limit_calls=10,
            rate_limit_period_seconds=600,
        )

        with self.set_user("Administrator"):
            self._clear_rate_limit_counter(operation_name)

            headers = self.framework.get_cor_rate_limit_headers(operation_name)

            self.assertIn("X-RateLimit-Limit", headers)
            self.assertIn("X-RateLimit-Remaining", headers)
            self.assertEqual(headers["X-RateLimit-Limit"], "10")


class TestCORRateLimitingScopes(EnhancedTestCase):
    """Test different rate limit scopes"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Force reload module to pick up any code changes
        cls.framework = _get_fresh_framework()

    def setUp(self):
        super().setUp()
        self._created_cors = []
        frappe.cache().delete_value("critical_operation_rules")
        # Clean up leftover test COR records from previous runs
        self._cleanup_test_cors()
        # Clear all rate limit counters
        _clear_all_test_rate_limit_counters()

    def _cleanup_test_cors(self):
        """Clean up any leftover test COR records from previous test runs"""
        test_cor_patterns = ["test_global_scope"]
        for pattern in test_cor_patterns:
            try:
                existing = frappe.get_all(
                    "Critical Operation Rule",
                    filters={"operation_name": pattern},
                    pluck="name",
                )
                for name in existing:
                    frappe.delete_doc("Critical Operation Rule", name, force=True)
                if existing:
                    frappe.db.commit()
            except Exception:
                pass

    def tearDown(self):
        for cor_name in self._created_cors:
            try:
                frappe.delete_doc("Critical Operation Rule", cor_name, force=True)
                frappe.db.commit()
            except Exception:
                pass
        frappe.cache().delete_value("critical_operation_rules")
        super().tearDown()

    def _create_test_cor(self, operation_name: str, **kwargs) -> str:
        defaults = {
            "operation_type": "utility",
            "security_level": "low",
            "enabled": 1,
            "rate_limit_calls": 3,
            "rate_limit_period_seconds": 60,
            "rate_limit_scope": "per_user",
            "audit_level": "minimal",
            "requires_justification": 0,
        }
        defaults.update(kwargs)

        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": operation_name,
            **defaults
        })
        cor.flags.ignore_permissions = True
        cor.insert()
        frappe.db.commit()  # Commit to ensure COR is visible to db.get_value
        self._created_cors.append(cor.name)
        frappe.cache().delete_value(f"critical_operation_rule:{operation_name}")
        return cor.name

    def test_global_scope_shared_across_users(self):
        """Verify that global scope shares counter across all users"""
        operation_name = "test_global_scope"
        self._create_test_cor(
            operation_name=operation_name,
            rate_limit_calls=4,
            rate_limit_scope="global",
        )

        user1 = self.create_test_user("global_user1@test.com", roles=["Verenigingen Staff"])
        user2 = self.create_test_user("global_user2@test.com", roles=["Verenigingen Staff"])

        # Raw delete (not delete_value) to match the raw incrby key written by the
        # engine; keys are site-namespaced. Global scope has no user/ip suffix.
        frappe.cache().delete(f"cor_rate_limit:{frappe.local.site}:interactive:{operation_name}")

        original_in_test = getattr(frappe.flags, "in_test", False)
        try:
            frappe.flags.in_test = False

            # Mock HTTP request to force INTERACTIVE context
            with mock_http_request():
                # User 1 makes 2 calls
                with self.set_user(user1.email):
                    for _ in range(2):
                        r = self.framework.rate_limiter.check_rate_limit(
                            operation_name,
                            context=ExecutionContext.INTERACTIVE,
                            force_check=True,
                        )
                        self.assertTrue(r.allowed)

                # User 2 makes 2 more calls - global scope shares the counter
                with self.set_user(user2.email):
                    r3 = self.framework.rate_limiter.check_rate_limit(
                        operation_name, context=ExecutionContext.INTERACTIVE, force_check=True
                    )
                    self.assertTrue(r3.allowed, "3rd global call should still be allowed")
                    r4 = self.framework.rate_limiter.check_rate_limit(
                        operation_name, context=ExecutionContext.INTERACTIVE, force_check=True
                    )
                    self.assertTrue(r4.allowed, "4th global call should still be allowed")

                    # 5th total call should exceed the shared global limit of 4
                    r5 = self.framework.rate_limiter.check_rate_limit(
                        operation_name, context=ExecutionContext.INTERACTIVE, force_check=True
                    )
                    self.assertFalse(
                        r5.allowed, "5th global call should exceed the shared limit"
                    )
                    self.assertEqual(r5.current_count, 5)

        finally:
            frappe.flags.in_test = original_in_test


class TestRateLimitKeyNamespacing(EnhancedTestCase):
    """Audit #7: rate-limit counter keys must be namespaced per site.

    The engine reads/writes counters via raw redis ops (incrby/expire/get) that
    bypass RedisWrapper.make_key, so without an explicit site prefix a shared
    Redis would collapse counters across tenants. Guard the key format directly.
    """

    def test_build_cache_key_includes_site(self):
        from verenigingen.utils.security.rate_limit_engine import get_rate_limit_engine

        engine = get_rate_limit_engine()
        site = frappe.local.site

        global_key = engine._build_cache_key("some_op", "global", "interactive")
        self.assertEqual(global_key, f"cor_rate_limit:{site}:interactive:some_op")

        user_key = engine._build_cache_key("some_op", "per_user", "interactive")
        self.assertTrue(user_key.startswith(f"cor_rate_limit:{site}:interactive:some_op:"))
        # The site segment must sit between the prefix and the operation, so two
        # different sites can never produce the same key for the same op/user.
        self.assertIn(f":{site}:", user_key)
