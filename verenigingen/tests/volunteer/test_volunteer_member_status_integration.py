"""
Member-status gating of volunteer creation — real integration coverage.

Replaces the self-mocked test_volunteer_member_integration.py (deleted in
f47d89ce, which reimplemented eligibility in local helpers and asserted against
that). These tests exercise the REAL BulkVolunteerCreationService against real
Member records.

The gate (bulk_volunteer_creation_service.py): a volunteer is created only when
the member's status is in VALID_VOLUNTEER_STATUSES (["Active", "Approved"]);
every other status is skipped as MEMBER_INACTIVE. Note that "Approved" is not a
valid Member.status option, so in practice only "Active" members pass the gate.
The existing test_volunteer_service_coverage.py covered only the Active happy
path and the enum classification — these add the negative (blocked) cases.
"""

import frappe

from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
    BulkVolunteerCreationService,
    VolunteerCreationOutcome,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Every Member.status option that is NOT in VALID_VOLUNTEER_STATUSES.
BLOCKED_STATUSES = ["Pending", "Rejected", "Expired", "Suspended", "Banned", "Deceased", "Quit"]


class TestVolunteerMemberStatusIntegration(EnhancedTestCase):
    """member.status → volunteer-creation eligibility, end to end."""

    def _service(self):
        return BulkVolunteerCreationService()

    def _member_with_status(self, status, birth_date="1990-01-01"):
        """Create a real member then set its status directly.

        db.set_value bypasses status-transition hooks on purpose — we are
        exercising the volunteer gate, not the status-change workflow.
        """
        member = self.create_test_member(birth_date=birth_date)
        frappe.db.set_value("Member", member.name, "status", status)
        return member

    def test_active_member_becomes_volunteer(self):
        """An Active member passes the gate and a Volunteer is created."""
        member = self._member_with_status("Active")

        summary = self._service().create_volunteers_for_members([member.name])

        self.assertEqual(summary.total_attempted, 1)
        self.assertEqual(summary.skipped_inactive, 0)
        self.assertGreaterEqual(summary.created + summary.already_existed, 1)
        self.assertTrue(frappe.db.exists("Volunteer", {"member": member.name}))

    def test_blocked_statuses_are_skipped_as_inactive(self):
        """Every non-eligible status is skipped as MEMBER_INACTIVE — no volunteer created."""
        for status in BLOCKED_STATUSES:
            with self.subTest(status=status):
                member = self._member_with_status(status)

                summary = self._service().create_volunteers_for_members([member.name])

                self.assertEqual(
                    summary.skipped_inactive, 1, f"{status} member should be skipped as inactive"
                )
                self.assertEqual(summary.created, 0)
                self.assertEqual(summary.results[0].outcome, VolunteerCreationOutcome.MEMBER_INACTIVE)
                self.assertFalse(
                    frappe.db.exists("Volunteer", {"member": member.name}),
                    f"No volunteer may exist for a {status} member",
                )

    def test_existing_volunteer_is_not_duplicated(self):
        """A second creation attempt for the same member returns ALREADY_EXISTS."""
        member = self._member_with_status("Active")
        svc = self._service()

        svc.create_volunteers_for_members([member.name])  # first pass: creates
        summary = svc.create_volunteers_for_members([member.name])  # second pass

        self.assertEqual(summary.already_existed, 1)
        self.assertEqual(summary.created, 0)
        self.assertEqual(summary.results[0].outcome, VolunteerCreationOutcome.ALREADY_EXISTS)

    def test_nonexistent_member_reports_not_found(self):
        """A member id that does not exist is reported as MEMBER_NOT_FOUND, not silently dropped."""
        summary = self._service().create_volunteers_for_members([f"NO-SUCH-MEMBER-{self.uid}"])

        self.assertEqual(summary.total_attempted, 1)
        self.assertEqual(summary.skipped_not_found, 1)
        self.assertEqual(summary.results[0].outcome, VolunteerCreationOutcome.MEMBER_NOT_FOUND)
