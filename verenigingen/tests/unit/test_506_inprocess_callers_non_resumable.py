"""#506: in-process callers of ``@handle_api_error`` endpoints must not swallow the
non-resumable DB errors (MariaDB 1213/1205) that #504 makes the endpoint re-raise.

Census (re-run on develop 13138a404, import-resolved): only two production callers of such an
endpoint still swallow -- ``bulk_assign_members_to_chapters`` and
``volunteer_application._create_membership_application``. The issue's other callers either no
longer exist or call ``ChapterMembershipManager.assign_member_to_chapter`` (not the endpoint).

Faults are injected BELOW every layer of the callee that swallows on the real path
(README rule 17): ``parse_application_data`` sits inside ``submit_application``'s body past its
own guard, and ``frappe.get_roles`` is a DB read in the endpoint body that no ``try`` in
``can_assign_member_to_chapter`` covers on the admin path. Only the exception CLASS is injected,
no real contention is produced.
"""

import sys
from unittest.mock import patch

import frappe

from verenigingen.tests.support.non_resumable_errors import deadlock as _deadlock
from verenigingen.tests.support.non_resumable_errors import lock_wait_timeout as _timeout
from verenigingen.tests.utils.base import VereningingenTestCase


def _506_called_from_member_management():
    """True when ``frappe.get_roles`` is being called from the module under test (the
    permission read in ``can_assign_member_to_chapter``, inside a generator expression)."""
    return sys._getframe(2).f_globals.get("__name__") == "verenigingen.api.member_management"


class TestBulkAssignMembersToChaptersNonResumable(VereningingenTestCase):
    ASSIGNMENTS = [
        {"member_name": "_506-NO-SUCH-MEMBER-A", "chapter_name": "_506-NO-SUCH-CHAPTER"},
        {"member_name": "_506-NO-SUCH-MEMBER-B", "chapter_name": "_506-NO-SUCH-CHAPTER"},
        {"member_name": "_506-NO-SUCH-MEMBER-C", "chapter_name": "_506-NO-SUCH-CHAPTER"},
    ]

    def setUp(self):
        super().setUp()
        self.expectErrorLog(
            "QueryDeadlockError", "QueryTimeoutError", "Bulk Assignment", "ordinary failure", "RuntimeError"
        )

    def _run(self, side_effect):
        from verenigingen.api import member_management

        original = member_management.can_assign_member_to_chapter
        calls = []

        def recording(member_name, chapter_name):
            calls.append(member_name)
            return original(member_name, chapter_name)

        with self.as_user("Administrator"), patch.object(
            member_management, "can_assign_member_to_chapter", side_effect=recording
        ), patch.object(frappe, "get_roles", new=side_effect):
            try:
                return member_management.bulk_assign_members_to_chapters(self.ASSIGNMENTS), calls, None
            except Exception as e:  # noqa: BLE001 - the test inspects the class
                return None, calls, e

    def _fail_on_second(self, error):
        real = frappe.get_roles
        seen = {"n": 0}

        def _get_roles(*args, **kwargs):
            if _506_called_from_member_management():
                seen["n"] += 1
                if seen["n"] == 2:
                    raise error
            return real(*args, **kwargs)

        return _get_roles

    def test_a_deadlock_stops_the_loop_and_escapes_with_its_class(self):
        with patch.object(frappe.db, "rollback") as rollback:
            result, calls, raised = self._run(self._fail_on_second(_deadlock()))
        # This frame owns the unit of work (bulk_suspend_members, #475): it rolls back.
        rollback.assert_called()
        self.assertIsInstance(raised, frappe.QueryDeadlockError, f"result={result}")
        self.assertEqual(calls, ["_506-NO-SUCH-MEMBER-A", "_506-NO-SUCH-MEMBER-B"], "loop must stop")

    def test_a_lock_wait_timeout_escapes_with_its_class(self):
        result, calls, raised = self._run(self._fail_on_second(_timeout()))
        self.assertIsInstance(raised, frappe.QueryTimeoutError, f"result={result}")
        self.assertEqual(len(calls), 2)

    def test_an_ordinary_exception_keeps_todays_handling(self):
        """CONTROL: each member is an ordinary failure and the loop carries on."""
        result, calls, raised = self._run(self._fail_on_second(RuntimeError("ordinary failure")))
        self.assertIsNone(raised)
        self.assertEqual(len(calls), 3)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["error_count"], 3)


class TestVolunteerMembershipApplicationNonResumable(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._uniq = frappe.generate_hash(length=8).lower()
        self.expectErrorLog(
            "QueryDeadlockError",
            "QueryTimeoutError",
            "Volunteer Application",
            "ordinary failure",
            "RuntimeError",
            "Application Submission Error",
            "submit_application",
        )

    def _payload(self):
        return {
            "first_name": "Ria",
            "last_name": "Vermeer",
            "email": f"ria.506.{self._uniq}@example.com",
            "birth_date": "1990-05-01",
            "motivation": "I care about animals.",
            "time_commitment": "6-10",
            "become_member": 1,
        }

    def _submit(self, error):
        from verenigingen.api import membership_application
        from verenigingen.api.volunteer_application import submit_volunteer_application

        with self.as_user("Guest"), patch.object(
            membership_application, "parse_application_data", side_effect=error
        ):
            result = submit_volunteer_application(**self._payload())
        name = (result.get("data") or {}).get("volunteer_name")
        if name and frappe.db.exists("Volunteer", name):
            self.track_doc("Volunteer", name)
        return result

    def test_a_deadlock_in_the_membership_step_does_not_report_the_application_received(self):
        result = self._submit(_deadlock())
        self.assertFalse(result["success"], f"reported success after a 1213: {result}")

    def test_a_lock_wait_timeout_does_not_report_the_application_received(self):
        result = self._submit(_timeout())
        self.assertFalse(result["success"], f"reported success after a 1205: {result}")

    def test_an_ordinary_membership_failure_still_keeps_the_volunteer_application(self):
        """CONTROL: today's handling -- the membership error is surfaced and the call still answers."""
        result = self._submit(RuntimeError("ordinary failure"))
        self.assertTrue(result["success"], result)
        self.assertTrue((result["data"] or {}).get("membership_application_error"))

    def test_the_helper_lets_the_class_escape(self):
        from verenigingen.api import membership_application
        from verenigingen.api.volunteer_application import _create_membership_application

        data = self._payload()
        with patch.object(membership_application, "parse_application_data", side_effect=_deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                _create_membership_application(data, "VOL-506")
