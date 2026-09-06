"""
Coverage + behavioural tests for three security utilities:

  - csrf_protection.py        (CSRFProtection wrapper + whitelisted API endpoints)
  - rate_limit_engine.py      (RateLimitEngine: effective-limit selection, cache keys,
                               header generation, COR fail-closed behaviour)
  - cache_invalidation.py     (the User / Role Profile / Has Role hooks)

These complement (do NOT duplicate) test_cor_rate_limiting.py, which focuses on
end-to-end enforcement counting. Here we target the uncovered branches:
batch-limit selection (bypass / inherited), per_ip / global cache-key scopes,
rate-limit header math, CSRF token extraction precedence, and the cache
invalidation hook bodies.
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.cache_invalidation import (
    invalidate_all_user_caches_on_role_profile_update,
    invalidate_user_cache_on_user_role_update,
    invalidate_user_role_cache_on_user_update,
)
from verenigingen.utils.security.csrf_protection import (
    CSRFError,
    CSRFProtection,
    get_csrf_token,
    require_csrf_token,
    setup_csrf_protection,
    validate_csrf_token,
)
from verenigingen.utils.security.rate_limit_engine import (
    RateLimitEngine,
    get_rate_limit_engine,
)
from verenigingen.utils.security.types import ExecutionContext


# ======================================================================
# CSRF
# ======================================================================
class TestCSRFProtectionCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._orig_request = getattr(frappe.local, "request", None)

    def tearDown(self):
        frappe.local.request = self._orig_request
        super().tearDown()

    def _bind_request(self, method="POST", headers=None):
        builder = EnvironBuilder(method=method, headers=headers or {})
        frappe.local.request = Request(builder.get_environ())

    def _disable_harness_csrf_mock(self):
        """Stop the base-class mock of CSRFProtection.validate_request for this test.

        VereningingenTestCase.setUp() patches CSRFProtection.validate_request to
        always return True (operational convenience). To exercise the REAL
        validate_request logic we must stop that mock; the harness tearDown then
        no-ops the already-stopped patcher. This is un-patching infrastructure, not
        patching the function under test.
        """
        for m in list(getattr(self, "_active_mocks", [])):
            target = getattr(getattr(m, "target", None), "__name__", "")
            attr = getattr(m, "attribute", "")
            if attr == "validate_request" or "CSRFProtection" in str(getattr(m, "target", "")):
                m.stop()
                self._active_mocks.remove(m)

    # ---- validate_token ----
    def test_validate_token_empty_raises(self):
        with self.assertRaises(CSRFError):
            CSRFProtection.validate_token("")

    def test_validate_token_matches_session(self):
        frappe.session.data["csrf_token"] = "match-me"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        self.assertTrue(CSRFProtection.validate_token("match-me"))

    def test_validate_token_mismatch_raises(self):
        frappe.session.data["csrf_token"] = "expected"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        with self.assertRaises(CSRFError) as ctx:
            CSRFProtection.validate_token("not-expected")
        self.assertIn("invalid", str(ctx.exception).lower())

    def test_validate_token_no_session_token_for_logged_in_user_raises(self):
        # Administrator (logged in, not Guest) with no session csrf_token -> "No CSRF token in session"
        frappe.session.data.pop("csrf_token", None)
        with self.assertRaises(CSRFError) as ctx:
            CSRFProtection.validate_token("anything")
        self.assertIn("session", str(ctx.exception).lower())

    # ---- get_token_from_request precedence ----
    def test_get_token_prefers_frappe_csrf_header(self):
        self._bind_request(headers={"X-Frappe-CSRF-Token": "frappe-hdr"})
        self.assertEqual(CSRFProtection.get_token_from_request(), "frappe-hdr")

    def test_get_token_falls_back_to_custom_header(self):
        self._bind_request(headers={"X-CSRF-Token": "custom-hdr"})
        self.assertEqual(CSRFProtection.get_token_from_request(), "custom-hdr")

    def test_get_token_falls_back_to_form_dict(self):
        self._bind_request(headers={})
        orig_form = frappe.form_dict.get("csrf_token")
        frappe.form_dict["csrf_token"] = "form-token"
        self.addCleanup(
            lambda: (
                frappe.form_dict.update({"csrf_token": orig_form})
                if orig_form
                else frappe.form_dict.pop("csrf_token", None)
            )
        )
        self.assertEqual(CSRFProtection.get_token_from_request(), "form-token")

    # ---- validate_request short-circuits (real method, harness mock disabled) ----
    def test_validate_request_skips_without_request_context(self):
        self._disable_harness_csrf_mock()
        frappe.local.request = None
        # No request context (background job / migration) -> validation is a no-op pass.
        self.assertTrue(CSRFProtection.validate_request())

    def test_validate_request_skips_safe_methods(self):
        self._disable_harness_csrf_mock()
        self._bind_request(method="GET")
        self.assertTrue(CSRFProtection.validate_request())

    def test_validate_request_missing_token_raises(self):
        # Unsafe method, no token anywhere -> CSRFError (request rejected).
        self._disable_harness_csrf_mock()
        if frappe.conf.get("ignore_csrf"):
            self.skipTest("ignore_csrf is enabled in this site config")
        self._bind_request(method="POST", headers={})
        frappe.form_dict.pop("csrf_token", None)
        frappe.session.data.pop("csrf_token", None)
        with self.assertRaises(CSRFError) as ctx:
            CSRFProtection.validate_request()
        self.assertIn("missing", str(ctx.exception).lower())

    def test_validate_request_valid_token_passes(self):
        self._disable_harness_csrf_mock()
        frappe.session.data["csrf_token"] = "good-token"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        self._bind_request(method="POST", headers={"X-Frappe-CSRF-Token": "good-token"})
        self.assertTrue(CSRFProtection.validate_request())

    def test_validate_request_rejects_when_only_session_token_present(self):
        """Security regression (audit #9): a request that omits the CSRF
        header/field must be rejected even when the session holds a token.

        Previously get_token_from_request fell back to the session's own token,
        so validate_request compared it against itself and always passed -
        defeating CSRF protection for any request that simply sent no token.
        """
        self._disable_harness_csrf_mock()
        if frappe.conf.get("ignore_csrf"):
            self.skipTest("ignore_csrf is enabled in this site config")
        frappe.session.data["csrf_token"] = "session-secret"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        self._bind_request(method="POST", headers={})
        frappe.form_dict.pop("csrf_token", None)
        with self.assertRaises(CSRFError):
            CSRFProtection.validate_request()

    # ---- whitelisted API endpoints ----
    def test_get_csrf_token_api_returns_token_payload(self):
        result = get_csrf_token()
        self.assertTrue(result["success"])
        self.assertIn("csrf_token", result)
        self.assertEqual(result["header_name"], CSRFProtection.HEADER_NAME)
        self.assertEqual(result["form_field_name"], CSRFProtection.FORM_FIELD_NAME)

    def test_validate_csrf_token_api_valid(self):
        frappe.session.data["csrf_token"] = "api-token"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        result = validate_csrf_token("api-token")
        self.assertTrue(result["success"])
        self.assertTrue(result["valid"])

    def test_validate_csrf_token_api_invalid_returns_structured_error(self):
        frappe.session.data["csrf_token"] = "api-token"
        self.addCleanup(lambda: frappe.session.data.pop("csrf_token", None))
        result = validate_csrf_token("wrong-one")
        # CSRFError branch: success True, valid False, structured error message.
        self.assertTrue(result["success"])
        self.assertFalse(result["valid"])
        self.assertIn("error", result)

    # ---- no-op compatibility shims ----
    def test_require_csrf_token_is_passthrough(self):
        def target():
            return "ran"

        wrapped = require_csrf_token(target)
        self.assertIs(wrapped, target)
        self.assertEqual(wrapped(), "ran")

    def test_setup_csrf_protection_is_noop(self):
        self.assertIsNone(setup_csrf_protection())


# ======================================================================
# Rate Limit Engine
# ======================================================================
class TestRateLimitEngineCoverage(VereningingenTestCase):
    """Targets the effective-limit selection, cache keys, headers and fail-closed paths."""

    def setUp(self):
        super().setUp()
        self.engine = RateLimitEngine()
        self._created_cors = []

    def tearDown(self):
        for name in self._created_cors:
            try:
                frappe.delete_doc("Critical Operation Rule", name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _make_cor(self, operation_name, **fields):
        """Create a real Critical Operation Rule for the test (factory method)."""
        if frappe.db.exists("Critical Operation Rule", {"operation_name": operation_name}):
            existing = frappe.get_all(
                "Critical Operation Rule",
                filters={"operation_name": operation_name},
                pluck="name",
            )
            for n in existing:
                frappe.delete_doc("Critical Operation Rule", n, force=True)
        doc = frappe.new_doc("Critical Operation Rule")
        doc.operation_name = operation_name
        doc.enabled = 1
        for k, v in fields.items():
            setattr(doc, k, v)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_cors.append(doc.name)
        return doc

    # ---- get_singleton ----
    def test_get_rate_limit_engine_is_singleton(self):
        self.assertIs(get_rate_limit_engine(), get_rate_limit_engine())

    # ---- COR resolution: specific vs generic fallback vs fail-closed ----
    def test_unknown_op_uses_generic_fallback_when_present(self):
        """An op with no specific COR falls back to '_generic_api_fallback' if it exists.

        This site ships a '_generic_api_fallback' COR, so an unknown op resolves to
        it rather than failing closed. If no fallback exists, the engine raises
        VPermissionError (fail-closed). We assert whichever holds for this site so the
        test is correct on any configuration.
        """
        fallback = frappe.db.get_value(
            "Critical Operation Rule",
            {"operation_name": "_generic_api_fallback", "enabled": 1},
            "rate_limit_calls",
        )
        if fallback is None:
            with self.assertRaises(VPermissionError):
                self.engine.check_rate_limit("module.no_such_operation_zzz", force_check=True)
        else:
            result = self.engine.check_rate_limit(
                "module.no_such_operation_zzz",
                context=ExecutionContext.INTERACTIVE,
                force_check=True,
            )
            # Resolved via the generic fallback -> a real (non-test) result.
            self.assertNotEqual(result.limit_type, "test_bypass")
            self.assertEqual(result.max_calls, fallback)
            self.addCleanup(
                lambda: frappe.cache().delete(
                    f"cor_rate_limit:{frappe.local.site}:{result.limit_type}:no_such_operation_zzz:{frappe.session.user}"
                )
            )

    # ---- _get_effective_limits: interactive defaults ----
    def test_effective_limits_interactive_defaults(self):
        cor = {"rate_limit_calls": None, "rate_limit_period_seconds": None}
        calls, period, limit_type = self.engine._get_effective_limits(cor, ExecutionContext.INTERACTIVE, "op")
        self.assertEqual(calls, 10)
        self.assertEqual(period, 3600)
        self.assertEqual(limit_type, "interactive")

    # ---- _get_effective_limits: batch limits applied ----
    def test_effective_limits_batch_applied(self):
        cor = {
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 60,
            "batch_rate_limit_calls": 100,
            "batch_rate_limit_period_seconds": 600,
            "apply_batch_limits_to": "Both",
        }
        calls, period, limit_type = self.engine._get_effective_limits(
            cor, ExecutionContext.BACKGROUND_JOB, "op"
        )
        self.assertEqual(calls, 100)
        self.assertEqual(period, 600)
        self.assertEqual(limit_type, "batch")

    # ---- _get_effective_limits: low/medium bypass in batch with no batch limits ----
    def test_effective_limits_bypass_for_low_security_batch(self):
        cor = {
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 60,
            "batch_rate_limit_calls": None,
            "security_level": "medium",
        }
        _, _, limit_type = self.engine._get_effective_limits(cor, ExecutionContext.BACKGROUND_JOB, "op")
        self.assertEqual(limit_type, "bypass")

    # ---- _get_effective_limits: critical/high inherit interactive limits in batch ----
    def test_effective_limits_inherited_for_critical_batch(self):
        cor = {
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 60,
            "batch_rate_limit_calls": None,
            "security_level": "critical",
        }
        calls, period, limit_type = self.engine._get_effective_limits(
            cor, ExecutionContext.BACKGROUND_JOB, "op"
        )
        # Inherits the interactive limits rather than bypassing - security-sensitive.
        self.assertEqual(limit_type, "batch_inherited")
        self.assertEqual(calls, 5)
        self.assertEqual(period, 60)

    # ---- _get_effective_limits: apply_batch_limits_to scoping ----
    def test_effective_limits_apply_to_scheduled_only_skips_background(self):
        cor = {
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 60,
            "batch_rate_limit_calls": 50,
            "apply_batch_limits_to": "Scheduled Tasks",
            "security_level": "medium",
        }
        # In a BACKGROUND_JOB context, "Scheduled Tasks" scope shouldn't use batch limits.
        _, _, limit_type = self.engine._get_effective_limits(cor, ExecutionContext.BACKGROUND_JOB, "op")
        self.assertEqual(limit_type, "bypass")

    # ---- _build_cache_key scopes ----
    def test_build_cache_key_global(self):
        key = self.engine._build_cache_key("op", "global", "interactive")
        # Keys are site-namespaced (audit #7) to isolate counters on shared Redis.
        self.assertEqual(key, f"cor_rate_limit:{frappe.local.site}:interactive:op")

    def test_build_cache_key_per_user(self):
        key = self.engine._build_cache_key("op", "per_user", "interactive")
        self.assertEqual(
            key, f"cor_rate_limit:{frappe.local.site}:interactive:op:{frappe.session.user}"
        )

    def test_build_cache_key_per_ip(self):
        key = self.engine._build_cache_key("op", "per_ip", "interactive")
        self.assertTrue(key.startswith(f"cor_rate_limit:{frappe.local.site}:interactive:op:"))
        # The IP segment comes from get_client_ip(); off-request that's "test_environment".
        self.assertIn(self.engine._get_client_ip(), key)

    # ---- end-to-end batch limits applied in a background context ----
    def test_check_rate_limit_applies_batch_limits_end_to_end(self):
        # A COR with explicit batch limits, invoked in a BACKGROUND_JOB context,
        # must enforce the BATCH limit (not the interactive one) and count under
        # the "batch" cache key.
        # Doctype enforces batch >= interactive, so interactive=1, batch=2.
        self._make_cor(
            "test_cov_batch_e2e_op",
            rate_limit_calls=1,
            rate_limit_period_seconds=3600,
            batch_rate_limit_calls=2,
            batch_rate_limit_period_seconds=600,
            apply_batch_limits_to="Both",
            rate_limit_scope="per_user",
            security_level="medium",
        )
        key = f"cor_rate_limit:{frappe.local.site}:batch:test_cov_batch_e2e_op:" + frappe.session.user
        frappe.cache().delete(key)
        self.addCleanup(lambda: frappe.cache().delete(key))

        r1 = self.engine.check_rate_limit(
            "mod.test_cov_batch_e2e_op",
            context=ExecutionContext.BACKGROUND_JOB,
            force_check=True,
        )
        r2 = self.engine.check_rate_limit(
            "mod.test_cov_batch_e2e_op",
            context=ExecutionContext.BACKGROUND_JOB,
            force_check=True,
        )
        r3 = self.engine.check_rate_limit(
            "mod.test_cov_batch_e2e_op",
            context=ExecutionContext.BACKGROUND_JOB,
            force_check=True,
        )
        self.assertEqual(r1.limit_type, "batch")
        self.assertEqual(r1.max_calls, 2, "batch limit (2) must be used in background context")
        self.assertTrue(r1.allowed)
        self.assertTrue(r2.allowed)
        self.assertFalse(r3.allowed, "3rd batch call past batch limit of 2 must be denied")

    # ---- end-to-end enforcement increments + denies ----
    def test_check_rate_limit_enforces_interactive_limit(self):
        self._make_cor(
            "test_cov_enforce_op",
            rate_limit_calls=2,
            rate_limit_period_seconds=3600,
            rate_limit_scope="per_user",
            security_level="medium",
        )
        key = f"cor_rate_limit:{frappe.local.site}:interactive:test_cov_enforce_op:" + frappe.session.user
        frappe.cache().delete(key)
        self.addCleanup(lambda: frappe.cache().delete(key))

        r1 = self.engine.check_rate_limit(
            "mod.test_cov_enforce_op", context=ExecutionContext.INTERACTIVE, force_check=True
        )
        r2 = self.engine.check_rate_limit(
            "mod.test_cov_enforce_op", context=ExecutionContext.INTERACTIVE, force_check=True
        )
        r3 = self.engine.check_rate_limit(
            "mod.test_cov_enforce_op", context=ExecutionContext.INTERACTIVE, force_check=True
        )
        self.assertTrue(r1.allowed)
        self.assertTrue(r2.allowed)
        self.assertFalse(r3.allowed, "3rd call past a limit of 2 must be denied")
        self.assertIn("exceeded", r3.reason.lower())

    # ---- test-environment bypass (force_check=False) ----
    def test_check_rate_limit_skips_in_test_env(self):
        # Without force_check, the engine returns a test_bypass result without touching COR.
        result = self.engine.check_rate_limit("mod.anything_at_all", force_check=False)
        self.assertTrue(result.allowed)
        self.assertEqual(result.limit_type, "test_bypass")

    # ---- headers ----
    def test_get_rate_limit_headers_for_configured_op(self):
        self._make_cor(
            "test_cov_headers_op",
            rate_limit_calls=20,
            rate_limit_period_seconds=600,
            rate_limit_scope="per_user",
            security_level="medium",
        )
        key = f"cor_rate_limit:{frappe.local.site}:interactive:test_cov_headers_op:" + frappe.session.user
        frappe.cache().delete(key)
        self.addCleanup(lambda: frappe.cache().delete(key))

        headers = self.engine.get_rate_limit_headers("mod.test_cov_headers_op")
        self.assertEqual(headers["X-RateLimit-Limit"], "20")
        self.assertEqual(headers["X-RateLimit-Window"], "600")
        # No requests counted yet -> remaining equals the limit.
        self.assertEqual(headers["X-RateLimit-Remaining"], "20")
        self.assertIn("X-RateLimit-Reset", headers)

    def test_get_rate_limit_headers_unknown_op(self):
        """Headers for an unknown op: empty dict if no generic fallback, else fallback headers.

        get_rate_limit_headers returns {} only when _get_cor_config finds nothing.
        This site ships a generic fallback, so headers reflect that fallback instead.
        """
        fallback = frappe.db.get_value(
            "Critical Operation Rule",
            {"operation_name": "_generic_api_fallback", "enabled": 1},
            "rate_limit_calls",
        )
        headers = self.engine.get_rate_limit_headers("mod.no_cor_for_headers_zzz")
        if fallback is None:
            self.assertEqual(headers, {})
        else:
            self.assertEqual(headers["X-RateLimit-Limit"], str(fallback))

    # ---- _detect_execution_context ----
    def test_detect_execution_context_background_job_flag(self):
        original = getattr(frappe.flags, "in_background_job", False)
        frappe.flags.in_background_job = True
        try:
            self.assertEqual(self.engine._detect_execution_context(), ExecutionContext.BACKGROUND_JOB)
        finally:
            frappe.flags.in_background_job = original

    def test_detect_execution_context_scheduler_flag(self):
        original = getattr(frappe.flags, "in_scheduler", False)
        frappe.flags.in_scheduler = True
        try:
            self.assertEqual(self.engine._detect_execution_context(), ExecutionContext.SCHEDULED_TASK)
        finally:
            frappe.flags.in_scheduler = original


# ======================================================================
# Cache Invalidation Hooks
# ======================================================================
class TestCacheInvalidationCoverage(VereningingenTestCase):
    """Exercise the User / Role Profile / Has Role cache-invalidation hooks.

    The hooks call APISecurityFramework.invalidate_user_role_cache(...) and must
    not raise even when the framework call fails. We assert they run cleanly and
    actually drop the per-user cache entry.
    """

    def _make_user(self):
        email = f"cache-inv-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Cache"
        user.last_name = "Inval"
        user.send_welcome_email = 0
        user.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("User", email, force=True, ignore_permissions=True))
        return user

    def test_user_update_hook_invalidates_unconditionally_on_update(self):
        """#693: doc_events.py only ever calls this with method="on_update"
        (on_update fires on insert too -- there is no separate after_insert
        registration for "User"), and it must invalidate on every such call
        rather than gating on has_value_changed("role_profile_name"), which
        misses role grants/withdrawals made via user_doc.append("roles", ...)
        + user_doc.save()."""
        from verenigingen.utils.security.authorization_engine import get_authorization_engine

        user = self._make_user()
        engine = get_authorization_engine()
        # Seed the per-user role-profile cache and confirm the versioned key lands.
        engine.get_user_role_profiles(user.name)
        cache_key = engine._get_versioned_cache_key(user.name)
        self.assertIsNotNone(frappe.cache.get_value(cache_key), "cache should be seeded")
        invalidate_user_role_cache_on_user_update(user, "on_update")
        self.assertIsNone(frappe.cache.get_value(cache_key), "hook must actually drop the user's cache entry")

    def test_user_update_hook_ignores_unrelated_methods(self):
        user = self._make_user()
        # A method not in the watched list must be a no-op (no raise).
        invalidate_user_role_cache_on_user_update(user, "validate")

    def test_role_profile_update_hook_invalidates_all(self):
        # Build a lightweight stand-in doc object; the hook only reads doc.name.
        fake_doc = frappe._dict(name="Some Role Profile")
        # Should invalidate ALL caches without raising.
        invalidate_all_user_caches_on_role_profile_update(fake_doc, "on_update")

    def test_role_profile_hook_ignores_unrelated_methods(self):
        fake_doc = frappe._dict(name="Some Role Profile")
        invalidate_all_user_caches_on_role_profile_update(fake_doc, "before_save")

    def test_has_role_hook_invalidates_for_parent_user(self):
        from verenigingen.utils.security.authorization_engine import get_authorization_engine

        user = self._make_user()
        engine = get_authorization_engine()
        engine.get_user_role_profiles(user.name)
        cache_key = engine._get_versioned_cache_key(user.name)
        self.assertIsNotNone(frappe.cache.get_value(cache_key), "cache should be seeded")
        # Has Role child rows carry parent (User name) + parenttype.
        fake_has_role = frappe._dict(parent=user.name, parenttype="User")
        invalidate_user_cache_on_user_role_update(fake_has_role, "after_insert")
        self.assertIsNone(frappe.cache.get_value(cache_key), "hook must drop the parent user's cache entry")

    def test_has_role_hook_skips_non_user_parent(self):
        # parenttype != "User" -> the invalidation branch is skipped (no raise).
        fake_has_role = frappe._dict(parent="SOME-DOC", parenttype="Role Profile")
        invalidate_user_cache_on_user_role_update(fake_has_role, "on_update")
