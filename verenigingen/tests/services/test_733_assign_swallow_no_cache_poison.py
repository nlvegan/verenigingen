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

import json
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


def _733_error_log_count(title):
    return frappe.db.count("Error Log", {"method": title})


class Test733DashboardDoesNotCacheFailure(VereningingenTestCase):
    SETTLEMENTS_TITLE = "Financial dashboard: settlements fetch failed"
    PAYMENTS_TITLE = "Financial dashboard: payments fetch failed"

    def setUp(self):
        super().setUp()
        setup_mollie_backend_api(self)
        self.dashboard = FinancialDashboard()
        self.dashboard.settlements_client = Mock()
        self.dashboard.payments_client = Mock()
        # the other clients would otherwise make real Mollie calls
        for name in ("balances_client", "invoices_client", "chargebacks_client"):
            setattr(self.dashboard, name, Mock())

    def test_failure_is_not_stored_as_cached_data_and_a_new_object_recovers(self):
        self.expectErrorLog("Financial dashboard")
        rows = [{"id": "stl_733", "status": "paidout"}]
        self.dashboard.settlements_client.get.side_effect = RuntimeError("mollie 503")
        self.assertEqual(self.dashboard._get_settlements_data(), [])
        self.assertIsNone(self.dashboard._settlements_cache)

        fresh = FinancialDashboard()
        fresh.settlements_client = Mock()
        fresh.settlements_client.get.return_value = rows
        self.assertEqual(fresh._get_settlements_data(), rows)

    def test_payments_failure_is_not_stored_as_cached_data(self):
        self.expectErrorLog("Financial dashboard")
        self.dashboard.payments_client.get.side_effect = RuntimeError("mollie 503")
        self.assertEqual(self.dashboard._get_payments_data(), [])
        self.assertIsNone(self.dashboard._payments_cache)

    def test_one_request_costs_one_call_and_one_error_log_row_per_client(self):
        """get_dashboard_summary() reads each getter several times; a failing API must
        be hit once and logged once per client, not once per read (#733 review)."""
        self.dashboard.settlements_client.get.side_effect = RuntimeError("mollie 503")
        self.dashboard.payments_client.get.side_effect = RuntimeError("mollie 503")
        settlements_before = _733_error_log_count(self.SETTLEMENTS_TITLE)
        payments_before = _733_error_log_count(self.PAYMENTS_TITLE)
        self.expectErrorLog("Financial dashboard")

        self.dashboard.get_dashboard_summary()

        self.assertEqual(self.dashboard.settlements_client.get.call_count, 1)
        self.assertEqual(self.dashboard.payments_client.get.call_count, 1)
        self.assertEqual(_733_error_log_count(self.SETTLEMENTS_TITLE) - settlements_before, 1)
        self.assertEqual(_733_error_log_count(self.PAYMENTS_TITLE) - payments_before, 1)

    def test_settlements_success_is_still_cached(self):
        """Control: the fix must not disable caching of a good fetch."""
        rows = [{"id": "stl_733", "status": "paidout"}]
        self.dashboard.settlements_client.get.side_effect = [rows, [{"id": "other"}]]
        self.assertEqual(self.dashboard._get_settlements_data(), rows)
        self.assertEqual(self.dashboard._get_settlements_data(), rows)
        self.assertEqual(self.dashboard.settlements_client.get.call_count, 1)

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
    def setUp(self):
        super().setUp()
        self._flag = frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management")
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Settings", "enable_chapter_management", self._flag or 0
        )

    def _fail_settings_once(self):
        real = frappe.get_single
        state = {"failed": False}

        def _733_fail_lookup(doctype, *args, **kwargs):
            if doctype == "Verenigingen Settings" and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("settings read failed")
            return real(doctype, *args, **kwargs)

        return patch("frappe.get_single", side_effect=_733_fail_lookup)

    def test_failed_settings_lookup_is_retried(self):
        lookup = OptimizedChapterLookup()
        self.expectErrorLog("Failed to check chapter management setting")
        with self._fail_settings_once():
            self.assertFalse(lookup.is_chapter_management_enabled())
            self.assertTrue(lookup.is_chapter_management_enabled())

    def test_failed_flag_does_not_cache_the_empty_postal_mapping(self):
        """get_lookup_instance() is a process singleton: an empty mapping built while
        the flag lookup failed must not be served for the 300 s TTL."""
        lookup = OptimizedChapterLookup()
        self.expectErrorLog("Failed to check chapter management setting")
        with self._fail_settings_once():
            self.assertEqual(lookup.get_chapter_postal_mapping(), {})
            self.assertIsNone(lookup._chapter_postal_mapping)
        with patch.object(lookup, "_build_postal_mapping", return_value={"1000": []}) as build:
            self.assertEqual(lookup.get_chapter_postal_mapping(), {"1000": []})
            build.assert_called_once()

    def test_good_flag_lookup_and_mapping_are_still_cached(self):
        lookup = OptimizedChapterLookup()
        self.assertTrue(lookup.is_chapter_management_enabled())
        lookup.get_chapter_postal_mapping()
        with patch("frappe.get_single", side_effect=AssertionError("flag must be cached")):
            self.assertTrue(lookup.is_chapter_management_enabled())
        with patch.object(lookup, "_build_postal_mapping", side_effect=AssertionError("cached")):
            lookup.get_chapter_postal_mapping()


class Test733AuditLogMarksFailedRoleLookup(VereningingenTestCase):
    """Asserted on the STORED API Audit Log row: `extra=` is never rendered or persisted."""

    def _stored_details(self, roles_side_effect):
        audit = SEPAAuditLogger()
        with patch("frappe.get_roles", side_effect=roles_side_effect):
            event_id = audit.log_event(
                AuditEventType.API_CALL_SUCCESS, user="Administrator", check_alerts=False
            )
        row = frappe.db.get_value("API Audit Log", {"event_id": event_id}, "details")
        self.assertIsNotNone(row, "audit row was not stored")
        return json.loads(row)

    def test_failed_role_lookup_is_recorded_in_the_stored_row(self):
        self.expectErrorLog("Security Audit - Role Retrieval Failed")
        details = self._stored_details(RuntimeError("role table locked"))
        self.assertIn("role table locked", details["user_roles_error"])

    def test_successful_lookup_stores_no_error_marker(self):
        details = self._stored_details(lambda user: ["System Manager"])
        self.assertNotIn("user_roles_error", details)
