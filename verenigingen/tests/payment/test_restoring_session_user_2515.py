"""#2515: ``restores_session_user`` puts back the caller's user, sid AND session data.

The WSGI test (test_gateway_session_user_restored_wsgi) always starts as Guest, so it cannot see
a restore that forgets sid/data; this one starts as a logged-in caller with a non-trivial
session. ``set_user`` resets ``session.sid`` to the username and empties ``session.data``.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_user import restores_session_user, restoring_session_user


class TestRestoringSessionUser(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        session = frappe.local.session
        self._saved = (session.user, session.sid, session.data)
        self.addCleanup(self._put_back)
        frappe.set_user("Administrator")
        session.sid = "sid-2515-caller"
        session.data = frappe._dict(marker="caller-data")

    def _put_back(self):
        frappe.set_user(self._saved[0])
        frappe.local.session.sid, frappe.local.session.data = self._saved[1], self._saved[2]

    def _assert_callers_session(self):
        session = frappe.local.session
        self.assertEqual(session.user, "Administrator")
        self.assertEqual(session.sid, "sid-2515-caller")
        self.assertEqual(session.data.marker, "caller-data")

    def test_a_returning_function_gets_user_sid_and_data_back(self):
        @restores_session_user
        def switches():
            frappe.set_user("Guest")
            return frappe.session.user

        self.assertEqual(switches(), "Guest")
        self._assert_callers_session()

    def test_a_raising_function_gets_user_sid_and_data_back(self):
        @restores_session_user
        def switches_then_fails():
            frappe.set_user("Guest")
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            switches_then_fails()
        self._assert_callers_session()

    def test_a_block_that_never_switched_does_not_call_set_user(self):
        """set_user wipes form_dict; a handler that never switched must not pay for it."""
        frappe.local.form_dict = frappe._dict(keep="me")
        with restoring_session_user():
            pass
        self.assertEqual(frappe.local.form_dict.keep, "me")
        self._assert_callers_session()
