"""#2283: fail-closed authorization helpers must RECORD their errors, not only deny.

`frappe.logger()` output is not captured anywhere readable (see bench CLAUDE.md), so the helpers
below denied correctly but invisibly. Each error is injected at the boundary the helper calls
(pytz / client-IP resolver / frappe.db.get_value / frappe.get_doc). Asserted per helper:
(a) the SAME deny outcome as before, (b) an Error Log row whose body carries the traceback and the
injected message, (c) where the handler reaches a caller (role profiles, volunteer lookup), a deadlock is re-raised.
The business-hours / IP helpers do no DB work, so they carry no deadlock re-raise.

Mock justified: infrastructure failures (DB driver, deadlock) cannot be produced
for real from one session; the logic under test (the helpers' except handlers) is not mocked.
"""

from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.authorization import SEPAAuthorizationManager
from verenigingen.utils.security.authorization_engine import get_authorization_engine
from verenigingen.utils.security.self_service_access_controller import SelfServiceAccessController

BH_TITLE = "SEPA business-hours check failed (denying)"
IP_TITLE = "SEPA IP restriction check failed (denying)"
RP_TITLE = "Authorization engine: role profile lookup failed"
VOL_TITLE = "Self-service volunteer member lookup failed"


class TestSecurityHelperErrorLogging2283(EnhancedTestCase):
    def _error_log_rows_2283(self, title):
        return frappe.get_all(
            "Error Log", filters={"method": title}, fields=["name", "error"], order_by="creation asc"
        )

    def _new_row(self, title, before):
        rows = self._error_log_rows_2283(title)
        self.assertEqual(len(rows), len(before) + 1, f"expected exactly one new Error Log row: {title}")
        return rows[-1]

    def _manager_2283(self):
        mgr = SEPAAuthorizationManager()
        mgr.business_hours = {"enabled": True, "weekdays_only": False, "start_hour": 0, "end_hour": 24}
        mgr.allowed_ips = ["10.0.0.1"]
        return mgr

    # ---- business hours ------------------------------------------------------------------

    def test_control_business_hours_allows_when_evaluable(self):
        self.assertTrue(self._manager_2283()._check_business_hours())

    def test_business_hours_error_denies_and_is_recorded(self):
        """A REAL failure: an unknown timezone name makes pytz raise inside the helper."""
        self.expectErrorLog(BH_TITLE)
        mgr = self._manager_2283()
        mgr.business_hours["timezone"] = "Not/AZone-2283"
        before = self._error_log_rows_2283(BH_TITLE)
        self.assertFalse(mgr._check_business_hours())
        row = self._new_row(BH_TITLE, before)
        self.assertIn("Not/AZone-2283", row.error)
        self.assertIn("Traceback", row.error)

    # ---- IP allowlist --------------------------------------------------------------------

    def _with_request(self, remote_addr="10.0.0.1"):
        """A real request-shaped object: get_client_ip reads only request.environ."""
        # Mock justified: frappe runtime context (request); get_client_ip and the helper stay real.
        patcher = mock.patch.object(
            frappe.local, "request", SimpleNamespace(environ={"REMOTE_ADDR": remote_addr}), create=True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_control_ip_allowlist_allows_listed_ip(self):
        self._with_request()
        self.assertTrue(self._manager_2283()._check_ip_restrictions())

    def test_control_ip_allowlist_denies_unlisted_ip(self):
        self._with_request("192.0.2.9")
        before = self._error_log_rows_2283(IP_TITLE)
        self.assertFalse(self._manager_2283()._check_ip_restrictions())
        self.assertEqual(len(self._error_log_rows_2283(IP_TITLE)), len(before))

    def test_ip_check_error_denies_and_is_recorded(self):
        self.expectErrorLog(IP_TITLE)
        self._with_request()
        mgr = self._manager_2283()

        class BrokenAllowlist(list):
            def __contains__(self, item):
                raise RuntimeError("ip-boom-2283")

        mgr.allowed_ips = BrokenAllowlist(["10.0.0.1"])
        before = self._error_log_rows_2283(IP_TITLE)
        self.assertFalse(mgr._check_ip_restrictions())
        row = self._new_row(IP_TITLE, before)
        self.assertIn("ip-boom-2283", row.error)

    # ---- role profiles -------------------------------------------------------------------

    def _fail_user_lookup(self, exc):
        real = frappe.db.get_value

        def flaky(doctype, *args, **kwargs):
            if doctype == "User":
                raise exc
            return real(doctype, *args, **kwargs)

        # Mock justified: infrastructure failure (tz database / DB / client-IP resolver) cannot be produced for real
        patcher = mock.patch.object(frappe.db, "get_value", flaky)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fresh_user(self):
        return f"rp2283-{frappe.generate_hash(length=10)}@example.com"

    def test_control_role_profiles_empty_for_unknown_user_without_error(self):
        self.assertEqual(get_authorization_engine().get_user_role_profiles(self._fresh_user()), [])
        self.assertEqual(self._error_log_rows_2283(RP_TITLE), [])

    def test_role_profile_error_returns_empty_and_is_recorded(self):
        self.expectErrorLog(RP_TITLE)
        user = self._fresh_user()
        before = self._error_log_rows_2283(RP_TITLE)
        self._fail_user_lookup(frappe.ValidationError("rp-boom-2283"))
        self.assertEqual(get_authorization_engine().get_user_role_profiles(user), [])
        row = self._new_row(RP_TITLE, before)
        self.assertIn("rp-boom-2283", row.error)
        self.assertIn(user, row.error)

    def test_role_profile_deadlock_propagates(self):
        self._fail_user_lookup(QueryDeadlockError("1213"))
        with self.assertRaises(QueryDeadlockError):
            get_authorization_engine().get_user_role_profiles(self._fresh_user())

    # ---- volunteer -> member -------------------------------------------------------------

    def _get_doc_failing_for_volunteer(self, exc):
        """frappe.get_doc raising for Volunteer only: log_error itself needs get_doc("Error Log")."""
        real = frappe.get_doc

        def flaky(*args, **kwargs):
            if args and args[0] == "Volunteer":
                raise exc
            return real(*args, **kwargs)

        # Mock justified: infrastructure failure (tz database / DB / client-IP resolver) cannot be produced for real
        return mock.patch("frappe.get_doc", flaky)

    def test_volunteer_lookup_error_returns_none_and_is_recorded(self):
        self.expectErrorLog(VOL_TITLE)
        before = self._error_log_rows_2283(VOL_TITLE)
        with self._get_doc_failing_for_volunteer(frappe.ValidationError("vol-boom-2283")):
            self.assertIsNone(SelfServiceAccessController().get_volunteer_member("VOL-X"))
        row = self._new_row(VOL_TITLE, before)
        self.assertIn("vol-boom-2283", row.error)
        self.assertIn("VOL-X", row.error)

    def test_volunteer_lookup_deadlock_propagates(self):
        with self._get_doc_failing_for_volunteer(QueryDeadlockError("1213")):
            with self.assertRaises(QueryDeadlockError):
                SelfServiceAccessController().get_volunteer_member("VOL-X")

    def test_non_string_volunteer_name_is_refused_without_an_error_row(self):
        """A dict-valued name from a request must not let a caller write Error Log rows."""
        before = self._error_log_rows_2283(VOL_TITLE)
        self.assertIsNone(SelfServiceAccessController().get_volunteer_member({"a": 1}))
        self.assertEqual(len(self._error_log_rows_2283(VOL_TITLE)), len(before))

    def test_logged_volunteer_name_is_bounded(self):
        self.expectErrorLog(VOL_TITLE)
        before = self._error_log_rows_2283(VOL_TITLE)
        with self._get_doc_failing_for_volunteer(frappe.ValidationError("vol-boom-2283")):
            SelfServiceAccessController().get_volunteer_member("V" * 5000)
        row = self._new_row(VOL_TITLE, before)
        self.assertNotIn("V" * 200, row.error)

    def test_control_missing_volunteer_is_not_an_error_row(self):
        before = self._error_log_rows_2283(VOL_TITLE)
        self.assertIsNone(SelfServiceAccessController().get_volunteer_member("NO-SUCH-VOL-2283"))
        self.assertEqual(len(self._error_log_rows_2283(VOL_TITLE)), len(before))
