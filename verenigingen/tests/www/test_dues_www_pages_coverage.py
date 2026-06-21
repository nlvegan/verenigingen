"""
Coverage tests for the dues-related www/ portal pages.

Pages covered:
  * verenigingen/www/dues_invoice_manager.py        (LIVE: paired with dues-invoice-manager.html)
  * verenigingen/www/dues_coverage_manager.py       (LIVE: paired with dues-coverage-manager.html)
  * verenigingen/www/dues_invoice_debugger.py       (LIVE: route /dues-invoice-debugger)

The dues_invoice_debugger controller was previously shipped with a HYPHENATED
filename (dues-invoice-debugger.py) which Frappe never imports (it resolves the
controller by converting template-basename hyphens to underscores), AND its
get_context crashed on a str.replace(day=1) because it used today() (a string)
instead of getdate(today()). Both are now fixed: the controller is renamed to
the underscore module name and uses getdate(today()), so get_context populates
the billing period without crashing.
"""

import datetime

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import dues_coverage_manager, dues_invoice_debugger, dues_invoice_manager


class TestDuesInvoiceManagerPage(VereningingenTestCase):
    """www/dues_invoice_manager.py - LIVE financial management page."""

    def setUp(self):
        super().setUp()
        self.admin_user = self.create_test_user("dues-mgr-admin@example.com", roles=["System Manager"])
        self.plain_user = self.create_test_user("dues-mgr-plain@example.com", roles=["Verenigingen Member"])

    def test_get_context_populates_period_and_permission_keys_for_admin(self):
        """get_context must populate the billing period + permission flags from real settings."""
        with self.set_user(self.admin_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                dues_invoice_manager.get_context(context)

        # Title + breadcrumbs
        self.assertEqual(context.title, "Dues Invoice Manager")
        self.assertEqual(context.parents[0]["name"], "financial-management")

        # Billing period: real dates derived from CoverageCalculator / settings, not blanks.
        self.assertTrue(context.current_period_start, "period start must be populated")
        self.assertTrue(context.current_period_end, "period end must be populated")
        # Parse to prove they are valid ISO dates and start <= end.
        start = getdate(context.current_period_start)
        end = getdate(context.current_period_end)
        self.assertLessEqual(start, end, "period start must be on/before period end")

        # System Manager must be granted both financial capabilities.
        self.assertIn("System Manager", context.user_roles)
        self.assertTrue(context.can_approve)
        self.assertTrue(context.can_generate_invoices)

        # JS config is real JSON carrying the same flags through to the browser.
        import json

        cfg = json.loads(context.js_config)
        self.assertTrue(cfg["can_approve"])
        self.assertEqual(cfg["period_start"], context.current_period_start)
        # CSRF token must be present for the page's API calls.
        self.assertTrue(context.csrf_token)

    def test_get_context_denies_non_financial_user(self):
        """A plain member must NOT be granted approve/generate capabilities."""
        with self.set_user(self.plain_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                dues_invoice_manager.get_context(context)

        self.assertFalse(context.can_approve, "plain member must not approve invoices")
        self.assertFalse(context.can_generate_invoices, "plain member must not generate invoices")

    def test_get_context_rejects_guest(self):
        """Guests must be hard-blocked with a PermissionError before any data renders."""
        with self.set_user("Guest"):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                dues_invoice_manager.get_context(context)

    def test_workflow_status_skeleton_is_present_and_empty(self):
        """Page intentionally renders an EMPTY workflow skeleton (loaded later via button).

        This guards against a regression where the expensive aggregation gets pulled
        back into page render.
        """
        with self.set_user(self.admin_user.name):
            context = frappe._dict()
            dues_invoice_manager.get_context(context)

        ws = context.workflow_status
        self.assertEqual(ws["pending_invoices"], 0)
        self.assertEqual(ws["recent_batches"], [])
        self.assertEqual(ws["members_analysis"]["total_active_members"], 0)
        self.assertIn("coverage_mismatches", ws)


class TestDuesCoverageManagerPage(VereningingenTestCase):
    """www/dues_coverage_manager.py - LIVE page + get_coverage_data API."""

    def setUp(self):
        super().setUp()
        self.admin_user = self.create_test_user("dues-cov-admin@example.com", roles=["System Manager"])

    def test_get_context_populates_csrf_for_authenticated_user(self):
        with self.set_user(self.admin_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                dues_coverage_manager.get_context(context)

        self.assertEqual(context.title, "Dues Coverage Manager")
        self.assertEqual(context.parents[0]["name"], "financial-management")
        self.assertTrue(context.csrf_token, "CSRF token required for API calls")
        self.assertEqual(context.no_cache, 1)

    def test_get_context_rejects_guest(self):
        with self.set_user("Guest"):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                dues_coverage_manager.get_context(context)

    def test_get_coverage_data_returns_ok_with_summary_shape(self):
        """get_coverage_data must return an OperationResult.ok with a summary block."""
        with self.set_user(self.admin_user.name):
            with self.assertNoErrorLog():
                result = dues_coverage_manager.get_coverage_data(None)

        # @standard_api may serialize the OperationResult to a dict in-process.
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        self.assertTrue(payload["success"], f"expected success, got {payload}")
        data = payload["data"]
        self.assertIn("summary", data)
        self.assertIn("data", data)
        summary = data["summary"]
        # Summary keys are the contract the front-end renders.
        for key in (
            "total_members",
            "members_with_gaps",
            "catchup_required",
            "total_catchup_amount",
        ):
            self.assertIn(key, summary)
        # total_members must equal the row count it summarizes (internal consistency).
        self.assertEqual(summary["total_members"], len(data["data"]))

    def test_get_coverage_data_accepts_json_string_filters(self):
        """Filters passed as a JSON string (how the browser sends them) must parse."""
        with self.set_user(self.admin_user.name):
            with self.assertNoErrorLog():
                result = dues_coverage_manager.get_coverage_data('{"member": ""}')
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        self.assertTrue(payload["success"])

    def test_get_coverage_data_tolerates_malformed_filter_string(self):
        """A garbage filter string must degrade to {} rather than crash."""
        with self.set_user(self.admin_user.name):
            with self.assertNoErrorLog():
                result = dues_coverage_manager.get_coverage_data("not-json{{{")
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        self.assertTrue(payload["success"])


class TestDuesInvoiceDebuggerPage(VereningingenTestCase):
    """www/dues_invoice_debugger.py - LIVE page (route /dues-invoice-debugger)."""

    def setUp(self):
        super().setUp()
        self.admin_user = self.create_test_user("dbg-admin@example.com", roles=["System Manager"])

    def test_get_context_does_not_crash_and_populates_billing_period(self):
        """get_context runs without crashing and computes the current billing period.

        Pins both fixes: the controller is now importable as a normal module and
        getdate(today()) yields a real date so .replace(day=1) works (it raised
        TypeError on the raw today() string before).

        The controller emits an intentional "DuesManager Debug" log on the
        success path, and its workflow-status fetch logs under "DuesManager
        Error" / "Member Dues Status Check Failed" when the (separately-secured,
        critical-API) workflow call is unavailable to the running user -- that is
        orthogonal to the date/rename fix being pinned here and is the same
        swallow-and-fallback the dues_invoice_manager page does. Those titles are
        ignored; any OTHER error log fails.
        """
        with self.set_user(self.admin_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog(
                ignore=[
                    "DuesManager Debug",
                    "DuesManager Error",
                    "Member Dues Status Check Failed",
                ]
            ):
                dues_invoice_debugger.get_context(context)

        self.assertEqual(context.title, "Dues Invoice Manager")

        # Billing period start is a real date equal to the first of the current month.
        start = context.current_period_start
        self.assertIsInstance(start, datetime.date)
        self.assertEqual(start, getdate(today()).replace(day=1))
        self.assertEqual(start.day, 1, "period start must be the first of the month")

        # Period end is a real date on/after the start (last day of the month).
        end = context.current_period_end
        self.assertIsInstance(end, datetime.date)
        self.assertGreaterEqual(end, start)

        # Role flags are populated for the System Manager.
        self.assertIn("System Manager", context.user_roles)
        self.assertTrue(context.can_approve)
        self.assertTrue(context.can_generate_invoices)
