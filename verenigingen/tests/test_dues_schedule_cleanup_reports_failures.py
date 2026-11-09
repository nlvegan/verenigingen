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
from verenigingen.tests.services.event_application.test_related_records_orchestrator import (
    _cleanup_dues_schedule,
)

SCHEDULE = "Membership Dues Schedule"


def _refuse_schedule_delete(real_delete):
    def delete_doc(doctype, *args, **kwargs):
        if doctype == SCHEDULE:
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

    def test_membership_application_cleanup_logs_a_refused_delete(self):
        member, schedule = self._real_schedule_name()
        fake = SimpleNamespace()
        self._assert_logs_failure(
            lambda: application_tests.TestMembershipApplicationLoad._cleanup_member_completely(fake, member.name), schedule
        )

    def test_control_a_cleanup_that_succeeds_logs_nothing(self):
        _member, schedule = self._real_schedule_name()
        with self.assertNoLogs(LOGGER_NAME, level="ERROR"):
            _cleanup_dues_schedule(schedule)
        self.assertFalse(frappe.db.exists(SCHEDULE, schedule))
