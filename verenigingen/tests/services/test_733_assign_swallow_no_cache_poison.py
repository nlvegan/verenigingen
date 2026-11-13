"""
#733: broad ``except`` handlers that ASSIGNED a fallback into a ``self._*`` cache
turned one transient lookup failure into a permanent one for the life of the
object. Each test injects the failure at the real lookup (the API client call,
``frappe.get_all`` / ``frappe.get_single`` for the one doctype, ``frappe.get_roles``),
calls twice, and requires the second call to retry and recover.

Run on test_site_9:
    bench --site test_site_9 run-tests --app verenigingen \
        --module verenigingen.tests.services.test_733_assign_swallow_no_cache_poison
"""

from unittest.mock import Mock, patch

import frappe
from frappe.model.qb_query import DatabaseQuery

from verenigingen.services.chapter.optimized_chapter_lookup import OptimizedChapterLookup
from verenigingen.tests.payment.test_mollie_reconciliation_engine import setup_mollie_backend_api
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.audit_logging import SEPAAuditLogger
from verenigingen.utils.security.types import AuditEventType
from verenigingen.verenigingen.doctype.chapter.validators.board_member_validator import (
    BoardMemberValidator,
)
from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard


class _733_RecordingLogger:
    """Stands in for the file sink; keeps the ``extra`` dict of each record."""

    def __init__(self):
        self.extras = []

    def _record(self, message, extra=None):
        self.extras.append(extra)

    info = warning = error = critical = _record


class Test733DashboardDoesNotCacheFailure(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        setup_mollie_backend_api(self)
        self.dashboard = FinancialDashboard()
        self.dashboard.settlements_client = Mock()
        self.dashboard.payments_client = Mock()

    def test_settlements_failure_is_retried(self):
        self.expectErrorLog("Financial dashboard")
        rows = [{"id": "stl_733", "status": "paidout"}]
        self.dashboard.settlements_client.get.side_effect = [RuntimeError("mollie 503"), rows]
        self.assertEqual(self.dashboard._get_settlements_data(), [])
        self.assertEqual(self.dashboard._get_settlements_data(), rows)
        self.assertEqual(self.dashboard.settlements_client.get.call_count, 2)

    def test_settlements_success_is_still_cached(self):
        """Control: the fix must not disable caching of a good fetch."""
        rows = [{"id": "stl_733", "status": "paidout"}]
        self.dashboard.settlements_client.get.side_effect = [rows, [{"id": "other"}]]
        self.assertEqual(self.dashboard._get_settlements_data(), rows)
        self.assertEqual(self.dashboard._get_settlements_data(), rows)
        self.assertEqual(self.dashboard.settlements_client.get.call_count, 1)

    def test_payments_failure_is_retried(self):
        self.expectErrorLog("Financial dashboard")
        rows = [{"id": "tr_733"}]
        self.dashboard.payments_client.get.side_effect = [RuntimeError("mollie 503"), rows]
        self.assertEqual(self.dashboard._get_payments_data(), [])
        self.assertEqual(self.dashboard._get_payments_data(), rows)
        self.assertEqual(self.dashboard.payments_client.get.call_count, 2)

    def test_payments_success_is_still_cached(self):
        rows = [{"id": "tr_733"}]
        self.dashboard.payments_client.get.side_effect = [rows, [{"id": "other"}]]
        self.assertEqual(self.dashboard._get_payments_data(), rows)
        self.assertEqual(self.dashboard._get_payments_data(), rows)
        self.assertEqual(self.dashboard.payments_client.get.call_count, 1)


class Test733UniqueRolesDoesNotCacheFailure(VereningingenTestCase):
    def _make_unique_role(self):
        name = f"R733{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": name,
                "permissions_level": "Basic",
                "is_unique": 1,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _fail_chapter_role_query(self, times):
        """Fail the Chapter Role query in DatabaseQuery.execute, below get_all/get_list
        and below the validator's handler; every other query runs for real."""
        real = DatabaseQuery.execute
        state = {"left": times}

        def _733_fail_lookup(query, *args, **kwargs):
            if query.doctype == "Chapter Role" and state["left"]:
                state["left"] -= 1
                raise RuntimeError("deadlock on Chapter Role")
            return real(query, *args, **kwargs)

        return patch.object(DatabaseQuery, "execute", _733_fail_lookup)

    def test_failed_lookup_is_retried_and_uniqueness_returns(self):
        role = self._make_unique_role()
        validator = BoardMemberValidator()
        self.expectErrorLog("Error fetching unique roles")
        with self._fail_chapter_role_query(times=1):
            self.assertEqual(validator._get_unique_roles(), set())
            self.assertIn(role, validator._get_unique_roles())

    def test_good_lookup_is_still_cached(self):
        role = self._make_unique_role()
        validator = BoardMemberValidator()
        self.assertIn(role, validator._get_unique_roles())
        with self._fail_chapter_role_query(times=99):
            self.assertIn(role, validator._get_unique_roles())


class Test733ChapterManagementFlagDoesNotCacheFailure(VereningingenTestCase):
    def test_failed_settings_lookup_is_retried(self):
        lookup = OptimizedChapterLookup()
        real = frappe.get_single
        state = {"failed": False}

        def _733_fail_lookup(doctype, *args, **kwargs):
            if doctype == "Verenigingen Settings" and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("settings read failed")
            return real(doctype, *args, **kwargs)

        enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management")
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        try:
            self.expectErrorLog("Failed to check chapter management setting")
            with patch("frappe.get_single", side_effect=_733_fail_lookup):
                self.assertFalse(lookup.is_chapter_management_enabled())
                self.assertTrue(lookup.is_chapter_management_enabled())
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", enabled or 0)


class Test733AuditLogMarksFailedRoleLookup(VereningingenTestCase):
    def _log(self, roles_side_effect):
        audit = SEPAAuditLogger()
        sink = _733_RecordingLogger()
        audit.logger = sink
        with patch("frappe.get_roles", side_effect=roles_side_effect):
            audit.log_event(AuditEventType.API_CALL_SUCCESS, user="Administrator", check_alerts=False)
        return sink.extras[-1]

    def test_failed_role_lookup_is_distinguishable_from_no_roles(self):
        self.expectErrorLog("Security Audit - Role Retrieval Failed")
        extra = self._log(RuntimeError("role table locked"))
        self.assertEqual(extra["user_roles"], [])
        self.assertIn("role table locked", extra["user_roles_error"])

    def test_successful_lookup_carries_no_error_marker(self):
        extra = self._log(lambda user: ["System Manager"])
        self.assertEqual(extra["user_roles"], ["System Manager"])
        self.assertNotIn("user_roles_error", extra)
