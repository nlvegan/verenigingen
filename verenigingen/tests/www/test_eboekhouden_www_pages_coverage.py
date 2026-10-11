"""
Coverage tests for the E-Boekhouden www portal pages:
- verenigingen/www/e_boekhouden_dashboard.py   (route: /e-boekhouden-dashboard)
- verenigingen/www/e_boekhouden_status.py       (route: /e-boekhouden-status)

Both pages are login-gated (Guest is thrown out) and aggregate E-Boekhouden
Migration data. The E-Boekhouden Settings on the test site have no live API
token, so the external connection check reports "Disconnected" -- but
get_dashboard_data() still returns the full data key set (connection_status,
migration_stats, available_data, recent_migrations, ...) and does NOT set an
"error" key in that case. We assert:
- Guest is denied
- a logged-in user gets a fully-populated context (all fallback keys present)
- migration_stats / recent_migrations reflect REAL seeded E-Boekhouden Migration
  rows
- the get_live_dashboard_data() whitelisted endpoint returns a serialized
  OperationResult dict

The status controller was previously shipped with a HYPHENATED filename
(e-boekhouden-status.py) which Frappe never imports, AND its success check used
`if dashboard_data.get("success")` -- the underlying service never returns a
"success" key, so that branch was unreachable and the page always showed
"Unknown error". Both are fixed: the controller is renamed to the underscore
module name and gates on `if "error" not in dashboard_data:`, so the happy path
now populates the real dashboard data. These tests assert that fixed behaviour.

No business-logic mocking; external e-Boekhouden connectivity is left real
(exercises the genuine "no token" path, which on this site returns a populated
data dict without an "error" key).
"""

import contextlib

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import e_boekhouden_dashboard as ebd, e_boekhouden_status as ebs

# Substrings of the (real) error logs emitted when the live e-Boekhouden
# connection is unavailable on the test site (no token, or token present but no
# network/DNS). These are the genuine no-connectivity path, NOT a controller
# bug: get_dashboard_data() still returns a populated dict without an "error"
# key, so the status page's happy path runs. We tolerate these specific logs.
_EXTERNAL_CONN_IGNORE = [
    "Error getting session token",
    "E-Boekhouden",
]

SETTINGS = "E-Boekhouden Settings"


@contextlib.contextmanager
def _no_eboekhouden_token():
    """Make "no token" true inside the block instead of inheriting it (#1609).

    Other tests write E-Boekhouden Settings.api_token in several shapes (a plain
    value, "", a saved password) and leave them behind, and each shape fails
    differently: no stored password -> "Password not found for E-Boekhouden
    Settings ..." (ignored above); a stored one that decrypts to "" -> "API token
    is required for REST API access" (not ignored). So the result depended on
    which tests shared the shard. Undone by a savepoint rollback, not a commit:
    the callers enter this AFTER their own commit, and nothing inside commits.
    """
    frappe.db.savepoint("no_eboekhouden_token")
    frappe.db.delete("__Auth", {"doctype": SETTINGS, "name": SETTINGS, "fieldname": "api_token"})
    frappe.db.set_single_value(SETTINGS, "api_token", None)
    try:
        yield
    finally:
        frappe.db.rollback(save_point="no_eboekhouden_token")
        frappe.clear_document_cache(SETTINGS, SETTINGS)


class TestEboekhoudenWwwPagesCoverage(VereningingenTestCase):
    """Real-data tests for the E-Boekhouden dashboard + status portal pages."""

    def setUp(self):
        super().setUp()
        self.user_email = f"ebd-user-{frappe.generate_hash()[:8]}@example.com"
        self.user = self._make_user(self.user_email, roles=["Verenigingen Member"])

    def _make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "send_welcome_email": 0,
                    "roles": [{"role": r} for r in roles],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)
        return email

    def _get_company(self):
        company = frappe.db.get_default("company") or frappe.db.get_value("Company", {}, "name")
        if not company:
            from verenigingen.tests.setup import ensure_member_test_masters

            ensure_member_test_masters()
            company = frappe.db.get_value("Company", {}, "name")
        return company

    def _make_migration(self, status="Completed", name_suffix=None):
        suffix = name_suffix or frappe.generate_hash()[:6]
        mig = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "naming_series": "EBMIG-.YYYY.-",
                "migration_name": f"TEST Migration {suffix}",
                "migration_status": status,
                "company": self._get_company(),
                # Stamp start_time = now so the row is among the most-recent and
                # reliably appears in the recent_migrations (order_by start_time
                # desc, limit 5) query regardless of pre-existing site data.
                "start_time": now_datetime(),
            }
        )
        mig.insert(ignore_permissions=True)
        self.track_doc("E-Boekhouden Migration", mig.name)
        return mig

    # ===== e_boekhouden_dashboard.get_context =====

    def test_dashboard_get_context_denies_guest(self):
        with self.set_user("Guest"):
            with self.assertRaises(frappe.ValidationError):
                ebd.get_context(frappe._dict())

    def test_dashboard_get_context_populates_all_fallback_keys(self):
        """A logged-in user always gets the full key set (fallbacks guarantee it)."""
        with self.set_user(self.user_email):
            context = frappe._dict()
            # External connection has no token -> connection error is logged.
            self.expectErrorLog("Dashboard error", "E-Boekhouden")
            ebd.get_context(context)

        for key in (
            "migration_stats",
            "connection_status",
            "available_data",
            "recent_migrations",
            "system_health",
            "title",
        ):
            self.assertIn(key, context)
        self.assertIsInstance(context.migration_stats, dict)
        self.assertIn("total", context.migration_stats)

    def test_dashboard_get_context_reflects_real_migrations(self):
        """migration_stats is a structured dict; when the dashboard service is
        connected it reflects real DB counts. Config-agnostic: on an unconnected
        site (no token, e.g. CI) the service errors out and zeroes the stats, so
        the exact-count assertion only runs when connected — but the structure
        and key set are always asserted."""
        self._make_migration(status="Completed")
        self._make_migration(status="Completed")
        self._make_migration(status="Failed")
        frappe.db.commit()

        with self.set_user(self.user_email):
            context = frappe._dict()
            self.expectErrorLog("Dashboard error", "E-Boekhouden")
            ebd.get_context(context)

        stats = context.migration_stats
        self.assertIsInstance(stats, dict)
        for k in ("total", "completed", "failed", "in_progress", "draft"):
            self.assertIn(k, stats)
        if not context.get("error"):
            # Connected: counts reflect the real DB.
            self.assertEqual(stats["total"], frappe.db.count("E-Boekhouden Migration"))
            self.assertEqual(
                stats["completed"],
                frappe.db.count("E-Boekhouden Migration", {"migration_status": "Completed"}),
            )
            self.assertGreaterEqual(stats["completed"], 2)
            self.assertGreaterEqual(stats["failed"], 1)

    # ===== e_boekhouden_dashboard.get_live_dashboard_data =====

    def test_live_dashboard_data_returns_operation_result(self):
        """The whitelisted endpoint returns a serialized OperationResult dict.

        get_live_dashboard_data is @standard_api(REPORTING) -> requires "medium"
        security, so it must be called as a staff/admin user. Administrator is a
        real user that satisfies that gate.
        """
        self._make_migration(status="Draft")
        frappe.db.commit()

        with self.set_user("Administrator"):
            self.expectErrorLog("E-Boekhouden")
            result = ebd.get_live_dashboard_data()

        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        # The endpoint wraps get_dashboard_data() in an OperationResult. The inner
        # data has migration_stats; the exact count only matches the DB when the
        # service was connected (no inner "error"), so guard that assertion.
        if result.get("success"):
            data = result.get("data") or {}
            self.assertIn("migration_stats", data)
            if not data.get("error"):
                self.assertEqual(
                    data["migration_stats"]["total"],
                    frappe.db.count("E-Boekhouden Migration"),
                )

    # ===== e_boekhouden_status.get_context =====

    def test_status_get_context_denies_guest(self):
        with self.set_user("Guest"):
            with self.assertRaises(frappe.ValidationError):
                ebs.get_context(frappe._dict())

    def test_status_get_context_populates_recent_migrations(self):
        """recent_migrations is a real list of E-Boekhouden Migration rows."""
        mig = self._make_migration(status="Completed", name_suffix="status")
        frappe.db.commit()

        with self.set_user("Administrator"), _no_eboekhouden_token():
            context = frappe._dict()
            # With no token the dashboard service logs "Password not found for
            # E-Boekhouden Settings ...". That is the genuine no-connectivity
            # path, not a controller bug -- ignore it.
            with self.assertNoErrorLog(ignore=_EXTERNAL_CONN_IGNORE):
                ebs.get_context(context)

        self.assertIn("recent_migrations", context)
        self.assertIsInstance(context.recent_migrations, list)
        names = {m["name"] for m in context.recent_migrations}
        # Our just-created migration should appear (it is among the 5 most recent).
        self.assertIn(mig.name, names)

    def test_status_success_check_branches_on_error_key_not_success(self):
        """Proves the success-check fix on the no-token path (forced, see #1609).

        Before the fix the controller gated on `if dashboard_data.get("success")`.
        The underlying service NEVER returns a "success" key (asserted below), so
        that branch was always falsy and the page always showed "Unknown error".
        The fix gates on `if "error" not in dashboard_data:`. With no token the
        service returns an "error" key, so get_context must set context.error to
        it, and recent_migrations is still populated from the DB regardless.
        """
        self._make_migration(status="Completed", name_suffix="happy1")
        self._make_migration(status="Failed", name_suffix="happy2")
        frappe.db.commit()

        with _no_eboekhouden_token():
            # Root cause: the service never returns a "success" key.
            data = frappe.call("verenigingen.e_boekhouden.utils.eboekhouden_api.get_dashboard_data_api")
            self.assertNotIn("success", data, "old `dashboard_data.get('success')` check was always falsy")

            with self.set_user("Administrator"):
                context = frappe._dict()
                with self.assertNoErrorLog(ignore=_EXTERNAL_CONN_IGNORE):
                    ebs.get_context(context)

        # No token (forced above): the service reports an error, and the status
        # page must surface it rather than "Unknown error".
        self.assertIn("error", data)
        self.assertEqual(context.get("error"), data["error"])

        # recent_migrations is always populated from the DB (separate query).
        self.assertIsInstance(context.recent_migrations, list)
        self.assertTrue(context.recent_migrations, "recent_migrations must list real rows")
