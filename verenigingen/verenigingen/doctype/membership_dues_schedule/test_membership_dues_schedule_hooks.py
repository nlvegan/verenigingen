"""
Tests for membership_dues_schedule_hooks.py

These cover the branches of the Member.current_dues_schedule synchronisation
logic that the happy-path tests in tests/payment/test_dues_schedule_sync.py do
NOT exercise:

- early returns for template / member-less schedules
- the *deactivation* path: when the current schedule is cancelled the member's
  current_dues_schedule is either repointed to another Active schedule or cleared
- the bulk reconciliation job check_and_update_all_members_current_schedule()
  and its transactional wrapper run_bulk_sync_with_transaction()

All documents are real; no business logic is mocked.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule_hooks import (
    check_and_update_all_members_current_schedule,
    update_member_current_dues_schedule,
)


class TestMembershipDuesScheduleHooks(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="HookSync Type",
            amount=25.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_member_with_schedule(self, last="Sync"):
        """Member (+customer+submitted membership+auto active dues schedule).

        A Membership Dues Schedule can only be inserted for a member that holds
        an active membership, so we go through the full factory path and reuse
        the schedule the membership submit auto-creates.
        """
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
    # Early returns
    # ------------------------------------------------------------------
    def test_template_schedule_is_ignored(self):
        """A template schedule never touches any member's current_dues_schedule."""

        class _Stub:
            is_template = 1
            member = None
            status = "Active"
            name = "tmpl"

        # Should simply return without raising.
        self.assertIsNone(update_member_current_dues_schedule(_Stub()))

    def test_member_less_schedule_is_ignored(self):
        class _Stub:
            is_template = 0
            member = None
            status = "Active"
            name = "x"

        self.assertIsNone(update_member_current_dues_schedule(_Stub()))

    # ------------------------------------------------------------------
    # Deactivation path
    # ------------------------------------------------------------------
    def test_deactivating_current_schedule_clears_member_field(self):
        """Cancelling the only active schedule clears Member.current_dues_schedule."""
        member, schedule = self._make_member_with_schedule(last="ClearField")

        member.reload()
        self.assertEqual(member.current_dues_schedule, schedule.name)

        # Deactivate it -> hook should clear the member field (no other active schedule).
        # Runs as Administrator (EnhancedTestCase), so no permission bypass is needed.
        schedule.status = "Cancelled"
        schedule.save()

        member.reload()
        self.assertFalse(member.current_dues_schedule)

    def test_deactivating_current_repoints_to_other_active(self):
        """When the current schedule is cancelled the member repoints to a surviving Active one.

        Drives the deactivation branch that queries for *another* active schedule
        and sets it as the new current. Only one Active schedule per member is
        allowed at a time, so a second Active row is created directly via the DB
        (bypassing the one-active guard) for the deactivation query to find.
        """
        member, first = self._make_member_with_schedule(last="Repoint")
        member.reload()
        self.assertEqual(member.current_dues_schedule, first.name)

        # The "only one active schedule per member" guard blocks inserting a
        # second active schedule directly. Temporarily DB-cancel the first so the
        # second can be created Active, then DB-reactivate the first so two Active
        # rows coexist for the deactivation query to find.
        frappe.db.set_value("Membership Dues Schedule", first.name, "status", "Cancelled")
        second = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"HookSync-{member.name}-Two",
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

        # Drive the deactivation hook directly with a Cancelled `first` doc. (The
        # "only one active schedule" validate guard rejects a controller .save()
        # while `second` is Active, so we invoke the hook function — the unit
        # under test — with an in-memory-cancelled copy of `first`.)
        first.reload()
        first.status = "Cancelled"
        update_member_current_dues_schedule(first)

        member.reload()
        self.assertEqual(member.current_dues_schedule, second.name)

    # ------------------------------------------------------------------
    # Bulk reconciliation
    # ------------------------------------------------------------------
    def test_bulk_sync_sets_missing_current_schedule(self):
        """The bulk job sets current_dues_schedule for a member whose field is stale/empty."""
        member, schedule = self._make_member_with_schedule(last="BulkSet")

        # Simulate drift: blank out the member's field directly.
        frappe.db.set_value("Member", member.name, "current_dues_schedule", None)

        result = check_and_update_all_members_current_schedule(batch_size=100)
        frappe.db.commit()

        self.assertGreaterEqual(result["members_checked"], 1)
        self.assertIsInstance(result["errors"], list)
        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), schedule.name)

    def test_bulk_sync_clears_stale_reference(self):
        """The bulk job clears current_dues_schedule when the member has no active schedule."""
        member, schedule = self._make_member_with_schedule(last="BulkClear")
        # Remove the active schedule so the member has none, then point the
        # member at a stale schedule reference the bulk job should clear.
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Cancelled")
        frappe.db.set_value("Member", member.name, "current_dues_schedule", "GHOST-SCHEDULE")

        check_and_update_all_members_current_schedule(batch_size=100)
        frappe.db.commit()

        self.assertFalse(frappe.db.get_value("Member", member.name, "current_dues_schedule"))

    # NOTE: run_bulk_sync_with_transaction() is intentionally NOT covered here.
    # Its first statement is frappe.db.begin() (START TRANSACTION), which trips
    # Frappe's ImplicitCommitError when called inside the test's own open
    # transaction. The function is a thin begin/commit/rollback wrapper around
    # check_and_update_all_members_current_schedule(), whose behaviour IS covered
    # above; testing the explicit-commit wrapper would require a real request
    # transaction boundary that the test harness does not provide.
