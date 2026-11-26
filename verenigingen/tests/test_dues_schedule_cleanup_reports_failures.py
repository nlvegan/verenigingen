"""A cleanup that cannot delete a Membership Dues Schedule must say so (#2271).

Seven cleanup paths wrapped the delete in `except Exception: pass`, so a schedule that survived (and
with it a link to its Membership Type) leaked into later modules with nothing in any log. They now
write to the harness logger. The failure is forced by making `frappe.delete_doc` raise for that
doctype only; the control asserts a cleanup that succeeds logs nothing.

The sibling test classes are imported as MODULES so their tests are not collected a second time here.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.backend.components import test_membership_application as application_tests
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.harness_logger import LOGGER_NAME
from verenigingen.tests.member import test_member_utils as member_utils_tests
from verenigingen.verenigingen.doctype.contribution_amendment_request import (
    test_contribution_amendment_request_coverage as amendment_tests,
)
from verenigingen.tests.services.event_application.test_related_records_orchestrator import (
    _cleanup_dues_schedule,
)

SCHEDULE = "Membership Dues Schedule"


def _refuse_schedule_delete(real_delete, refused=(SCHEDULE,)):
    def delete_doc(doctype, *args, **kwargs):
        if doctype in refused:
            raise frappe.ValidationError("refused by test")
        return real_delete(doctype, *args, **kwargs)

    return delete_doc


class TestDuesScheduleCleanupReportsFailures(EnhancedTestCase):
    def _assert_logs_failure(self, run, schedule_name):
        # Mock justified: forces the delete failure the swallowed handlers hide; no real row refuses a force delete
        with patch("frappe.delete_doc", side_effect=_refuse_schedule_delete(frappe.delete_doc)):
            with self.assertLogs(LOGGER_NAME, level="ERROR") as logged:
                run()
        self.assertTrue(
            any(schedule_name in line and SCHEDULE in line for line in logged.output), logged.output
        )

    def _real_schedule_name(self):
        member = self.create_test_member(first_name="Sched", last_name="Cleanup")
        mtype = self.create_test_membership_type()
        schedule = frappe.get_doc(
            {
                "doctype": SCHEDULE,
                "schedule_name": f"CLEANUP-LOG-{frappe.generate_hash(length=6)}",
                "member": member.name,
                "membership_type": mtype.name,
                "status": "Active",
                "billing_frequency": "Annual",
                "currency": "EUR",
                "dues_rate": 25,
            }
        )
        schedule.flags.ignore_validate = True
        schedule.insert(ignore_mandatory=True)
        self.track_doc(SCHEDULE, schedule.name)
        return member, schedule.name

    def test_orchestrator_cleanup_logs_a_refused_delete(self):
        _member, schedule = self._real_schedule_name()
        self._assert_logs_failure(lambda: _cleanup_dues_schedule(schedule), schedule)

    def test_member_utils_cleanups_log_a_refused_delete(self):
        member, schedule = self._real_schedule_name()
        fake = SimpleNamespace(member=member, membership=SimpleNamespace(name="no-such"))
        self._assert_logs_failure(lambda: member_utils_tests.TestDuesScheduleUtilities._cleanup_member_schedules(fake), schedule)
        frappe.db.set_value(SCHEDULE, schedule, "membership", None)

    def test_member_utils_membership_schedule_cleanup_logs_a_refused_delete(self):
        member, schedule = self._real_schedule_name()
        membership = self.create_test_membership(member_name=member.name)
        frappe.db.set_value(SCHEDULE, schedule, "membership", membership.name)
        fake = SimpleNamespace(member=member, membership=membership)
        self._assert_logs_failure(
            lambda: member_utils_tests.TestDuesScheduleUtilities._cleanup_membership_schedules(fake),
            schedule,
        )

    def test_membership_application_cleanup_logs_a_refused_delete(self):
        member, schedule = self._real_schedule_name()
        fake = SimpleNamespace()
        self._assert_logs_failure(
            lambda: application_tests.TestMembershipApplicationLoad._cleanup_member_completely(fake, member.name), schedule
        )

    def _run_chapter_selection_flow(self, refused):
        """Run the real TestChapterSelection test whose body ends in the inline cleanup, with
        `frappe.delete_doc` refusing `refused`; return the ERROR lines logged."""
        case_class = application_tests.TestChapterSelection
        name = "test_chapter_data_persistence_through_approval_flow"
        case_class.setUpClass()
        case = case_class(name)
        try:
            case.setUp()
            try:
                # Mock justified: forces the delete failure the inline cleanup swallowed. Patched only
                # around the test body, so the case's own tearDown drain can still delete.
                with patch("frappe.delete_doc", side_effect=_refuse_schedule_delete(frappe.delete_doc, refused)):
                    with self.assertLogs(LOGGER_NAME, level="ERROR") as logged:
                        getattr(case, name)()
            finally:
                case.tearDown()
                case.doCleanups()
        finally:
            case_class.tearDownClass()
        return logged.output

    def test_chapter_selection_inline_cleanup_logs_a_refused_schedule_delete(self):
        output = self._run_chapter_selection_flow((SCHEDULE,))
        self.assertTrue(any("could not delete " + SCHEDULE in line for line in output), output)

    def test_chapter_selection_inline_cleanup_logs_a_failed_member_delete(self):
        output = self._run_chapter_selection_flow(("Member",))
        self.assertTrue(any("cleanup of member" in line for line in output), output)

    def test_contribution_amendment_teardown_class_logs_a_refused_delete(self):
        case_class = amendment_tests.TestContributionAmendmentRequestCoverage
        case_class.setUpClass()
        try:
            schedules = frappe.get_all(SCHEDULE, {"member": case_class.member.name}, pluck="name")
            if not schedules:
                self.skipTest("class fixtures created no Dues Schedule, nothing for teardown to refuse")
            # Mock justified: forces the delete failure the swallowed handler hid
            with patch("frappe.delete_doc", side_effect=_refuse_schedule_delete(frappe.delete_doc)):
                with self.assertLogs(LOGGER_NAME, level="ERROR") as logged:
                    case_class.tearDownClass()
            self.assertTrue(any(schedules[0] in line for line in logged.output), logged.output)
        finally:
            case_class.tearDownClass()

    def test_control_a_cleanup_that_succeeds_logs_nothing(self):
        _member, schedule = self._real_schedule_name()
        with self.assertNoLogs(LOGGER_NAME, level="ERROR"):
            _cleanup_dues_schedule(schedule)
        self.assertFalse(frappe.db.exists(SCHEDULE, schedule))
