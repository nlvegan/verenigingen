"""#2654: the non-resumable-error branch of suspend_member / unsuspend_member logged an
f-string with doubled braces, so the Error Log recorded the literal text
``{member_name}`` / ``{traceback.format_exc()}`` instead of the member and the traceback.

The fault is injected at ``suspend_member_safe`` / ``unsuspend_member_safe``, the layer that
re-raises a 1213/1205 in production (#470), and the assertions read the Error Log ROW that
the handler wrote.
"""

from unittest.mock import patch

import frappe

from verenigingen.api import suspension_api
from verenigingen.tests.support.non_resumable_errors import deadlock as _deadlock
from verenigingen.tests.utils.base import VereningingenTestCase

TITLE = "Suspension API Exception"


class TestSuspensionNonResumableLog2654(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Brace", last_name="Log2654", status="Active")
        self.expectErrorLog("QueryDeadlockError", TITLE)

    def _drive(self, endpoint, safe_name):
        """Call the endpoint with the deadlock injected; return the Error Log row written."""
        from verenigingen.utils import termination_integration

        before = {r.name for r in frappe.get_all("Error Log", filters={"method": TITLE})}
        with self.as_user("Administrator"), patch.object(
            termination_integration, safe_name, side_effect=_deadlock()
        ):
            with self.assertErrorLog(TITLE), self.assertRaises(frappe.QueryDeadlockError):
                endpoint(self.member.name, "reason 2654")
        rows = [
            r
            for r in frappe.get_all("Error Log", filters={"method": TITLE}, fields=["name", "error"])
            if r.name not in before
        ]
        self.assertEqual(len(rows), 1, rows)
        return rows[0].error

    def _assert_recorded(self, error, endpoint_name):
        self.assertIn(f"Non-resumable DB error in {endpoint_name} for {self.member.name}", error)
        self.assertNotIn("{member_name}", error)
        self.assertNotIn("{traceback.format_exc()}", error)
        # A real traceback names the raising exception class and a frame of the endpoint.
        self.assertIn("Traceback (most recent call last)", error)
        self.assertIn("QueryDeadlockError", error)
        self.assertIn("suspension_api.py", error)

    def test_suspend_member_row_records_member_and_traceback(self):
        error = self._drive(suspension_api.suspend_member, "suspend_member_safe")
        self._assert_recorded(error, "suspend_member")

    def test_unsuspend_member_row_records_member_and_traceback(self):
        error = self._drive(suspension_api.unsuspend_member, "unsuspend_member_safe")
        self._assert_recorded(error, "unsuspend_member")
