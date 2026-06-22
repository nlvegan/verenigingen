"""
Additional coverage for membership_dues_schedule_hooks.py.

test_membership_dues_schedule_hooks.py already covers the early returns, the
deactivation path and two bulk-reconciliation cases. These tests target the
*Active-schedule* branch of update_member_current_dues_schedule (the
FOR-UPDATE query and its three "should become current" cases) plus the bulk
metrics shape:

- Case 1: member has no current schedule -> the active schedule becomes current.
- Case 2: member's current schedule is no longer Active -> repointed.
- Case 3: a newer active schedule (later creation) supersedes the current one.
- bulk sync leaves an already-correct member untouched (members_updated count).
- bulk sync metrics dict shape (members_checked / execution_time / batch_size).

All documents are real; no business logic is mocked.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule_hooks import (
    check_and_update_all_members_current_schedule,
    update_member_current_dues_schedule,
)


class TestMembershipDuesScheduleHooksCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="HookCov Type",
            amount=25.0,
            contribution_mode="Fixed Amount",
        )

    def _member_with_schedule(self, last="Cov"):
        member, schedule = self.create_test_member_with_schedule(
            first_name="Hook",
            last_name=last,
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        if member.status != "Active":
            frappe.db.set_value("Member", member.name, "status", "Active")
            member.reload()
        return member, schedule

    # ------------------------------------------------------------------
    # Active-schedule path: Case 1 (no current set)
    # ------------------------------------------------------------------
    def test_active_schedule_sets_current_when_none(self):
        """An active schedule becomes current when the member has none set."""
        member, schedule = self._member_with_schedule(last="NoCurrent")
        # Clear the field so Case 1 (no current) is the path taken.
        frappe.db.set_value("Member", member.name, "current_dues_schedule", None)

        update_member_current_dues_schedule(schedule)

        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), schedule.name)

    # ------------------------------------------------------------------
    # Active-schedule path: Case 2 (current is not Active)
    # ------------------------------------------------------------------
    def test_active_schedule_replaces_inactive_current(self):
        """When the current schedule is no longer Active, an active one replaces it."""
        member, schedule = self._member_with_schedule(last="StaleCurrent")
        # Point the member at a stale (non-existent) current schedule. The
        # LEFT JOIN yields current_status = NULL (!= "Active") -> Case 2.
        frappe.db.set_value("Member", member.name, "current_dues_schedule", "GHOST-STALE")

        update_member_current_dues_schedule(schedule)

        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), schedule.name)

    # ------------------------------------------------------------------
    # Active-schedule path: Case 3 (newer active schedule supersedes)
    # ------------------------------------------------------------------
    def test_newer_active_schedule_supersedes_current(self):
        """A newer (later-created) active schedule becomes current over an older one."""
        member, first = self._member_with_schedule(last="Newer")
        member.reload()
        self.assertEqual(member.current_dues_schedule, first.name)

        # Make a second, later-created Active schedule. The one-active-per-member
        # guard blocks a direct insert while `first` is Active, so DB-cancel
        # `first`, insert `second`, then DB-reactivate `first`.
        frappe.db.set_value("Membership Dues Schedule", first.name, "status", "Cancelled")
        second = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"HookCov-{member.name}-Two",
                "member": member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 25.0,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
                "is_template": 0,
            }
        ).insert()
        frappe.db.set_value("Membership Dues Schedule", first.name, "status", "Active")

        # current_dues_schedule still points at `first`; driving the hook with the
        # newer `second` should repoint it (Case 3: newer creation date).
        second.reload()
        update_member_current_dues_schedule(second)

        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), second.name)

    def test_older_active_schedule_does_not_supersede(self):
        """An OLDER active schedule does NOT replace a newer current schedule.

        Inverse of Case 3: when `first` (older) runs the hook while `second`
        (newer) is already current, none of the three "should be current"
        conditions hold, so the current pointer is left unchanged.
        """
        member, first = self._member_with_schedule(last="Older")

        frappe.db.set_value("Membership Dues Schedule", first.name, "status", "Cancelled")
        second = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"HookCov-{member.name}-Newer",
                "member": member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 25.0,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
                "is_template": 0,
            }
        ).insert()
        frappe.db.set_value("Membership Dues Schedule", first.name, "status", "Active")
        # Make `second` the current pointer.
        frappe.db.set_value("Member", member.name, "current_dues_schedule", second.name)

        # Driving the OLDER `first` must not steal current away from `second`.
        first.reload()
        update_member_current_dues_schedule(first)

        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), second.name)

    # ------------------------------------------------------------------
    # Bulk reconciliation: already-correct member untouched + metrics shape
    # ------------------------------------------------------------------
    def test_bulk_sync_leaves_correct_member_untouched(self):
        """A member already pointing at its newest active schedule is not re-updated."""
        member, schedule = self._member_with_schedule(last="Correct")
        member.reload()
        # Precondition: member already correct.
        self.assertEqual(member.current_dues_schedule, schedule.name)

        result = check_and_update_all_members_current_schedule(batch_size=100)
        frappe.db.commit()

        # Still correct, and the metrics dict has the documented shape.
        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), schedule.name)
        self.assertIn("members_checked", result)
        self.assertIn("members_updated", result)
        self.assertIn("execution_time", result)
        self.assertIn("avg_time_per_member", result)
        self.assertEqual(result["batch_size"], 100)
        self.assertIsInstance(result["members_updated"], int)
        self.assertGreaterEqual(result["members_checked"], 1)
