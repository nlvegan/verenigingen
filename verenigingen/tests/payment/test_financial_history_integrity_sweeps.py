"""Integrity sweeps for fee_change_history and donor_history (#425).

Before this, financial history writes rode whatever transaction the caller
happened to have open (the commit that used to make each write durable was
removed by #411), and only two of the four history tables had a periodic
sweep re-checking for a write that got lost that way:

    payment_history       hourly  (payment_history_validator.py)
    volunteer_expenses     daily / weekly (expense_history_batch_processor.py)
    fee_change_history     NONE (until this file)
    donor_history          NONE (until this file)

Each test below manufactures the exact inconsistency its sweep exists to
catch -- a history child-table row that a real write would have produced, but
that isn't there -- and confirms the sweep both notices AND repairs it. Each
also carries a control: run the same sweep over data that is already
consistent, and confirm it makes no changes and reports no repairs. A sweep
that reports nothing on a broken table would be the exact failure #425
describes; a sweep that "repairs" consistent data -- or silently rewrites it
-- would be a different bug.

Both sweeps accept an optional scoping parameter (``donor_names=`` /
``member_names=``) precisely so these tests can scope to their own fixture:
test_site_5 is a shared, disposable site that accumulates members and donors
from unrelated prior test runs (documented leaked-test-data behavior; see
MEMORY.md), some of them genuinely broken. An unscoped sweep run in these
tests would legitimately report errors for records this test never touched.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import (
    validate_donor_history_integrity,
    validate_fee_change_history_integrity,
)


class TestDonorHistoryIntegritySweep(EnhancedTestCase):
    """validate_donor_history_integrity() -- the donor_history sweep."""

    def test_sweep_repairs_a_donation_missing_from_donor_history(self):
        """A donation exists, but its donor_history row was lost.

        This is the shape #425 describes: the Donation write committed (it is
        the source of truth here), but the donor_history child-table write
        that should have accompanied it never became durable. Simulate that by
        deleting the donor_history row directly rather than going through
        DonationHistoryManager, so nothing about the deletion path could
        accidentally re-create it.
        """
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, amount=250)

        # Confirm the live hook path did write it, then destroy that row to
        # simulate the write being lost to a rolled-back transaction.
        donor.reload()
        self.assertTrue(
            any(e.donation_reference == donation.name for e in donor.donor_history),
            "setUp assumption failed: the live Donation hook did not write a donor_history row",
        )
        frappe.db.delete(
            "Donation History", {"parent": donor.name, "donation_reference": donation.name}
        )
        donor.reload()
        self.assertFalse(
            any(e.donation_reference == donation.name for e in donor.donor_history),
            "the manufactured gap did not take -- donor_history still carries this donation",
        )

        result = validate_donor_history_integrity(donor_names=[donor.name])

        self.assertEqual(result.get("errors"), 0, f"sweep reported an error for our own donor: {result}")
        self.assertEqual(result.get("resynced"), 1)

        donor.reload()
        matches = [e for e in donor.donor_history if e.donation_reference == donation.name]
        self.assertEqual(
            len(matches),
            1,
            "the sweep must repair a donation missing from donor_history, not just report it",
        )
        self.assertEqual(float(matches[0].donation_amount), 250.0)

    def test_sweep_is_quiet_on_consistent_donor_history(self):
        """Control: a donor whose donor_history already matches its donations.

        The underlying rebuild (DonationHistoryManager.sync_donation_history)
        unconditionally deletes and re-inserts every child row, so this
        cannot assert the ROW is untouched (its own ``name``/``creation``
        legitimately change every run -- a known tradeoff documented on the
        sweep itself). What it CAN and must assert is that the resulting data
        is still correct and not duplicated: same donation, same amount, one
        row.
        """
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, amount=75)

        result = validate_donor_history_integrity(donor_names=[donor.name])
        self.assertEqual(result.get("errors"), 0, f"sweep reported an error for our own donor: {result}")

        donor.reload()
        matches = [e for e in donor.donor_history if e.donation_reference == donation.name]
        self.assertEqual(len(matches), 1, "consistent data must not be duplicated by the sweep")
        self.assertEqual(float(matches[0].donation_amount), 75.0)


class TestFeeChangeHistoryIntegritySweep(EnhancedTestCase):
    """validate_fee_change_history_integrity() -- the fee_change_history sweep."""

    def test_sweep_repairs_a_schedule_missing_from_fee_change_history(self):
        """A dues schedule exists, but its fee_change_history row was lost.

        Creating a (non-template) Membership Dues Schedule fires
        MembershipDuesSchedule.after_insert -> FeeChangeTrackingService.handle_new_schedule(),
        which records exactly one fee_change_history entry. Delete that entry
        directly to simulate the write being lost to a rolled-back transaction,
        leaving the schedule (the source of truth) as the only trace the change
        ever happened.
        """
        member = self.create_test_member()
        # create_test_membership's own after_insert hook already auto-creates
        # one active dues schedule for the member; create_test_dues_schedule
        # (see sepa_test_factory.py) detects that and reuses it rather than
        # creating a second one (production allows only one active schedule
        # per member), so the requested dues_rate kwarg has no effect here --
        # assert against the schedule's ACTUAL rate, not the one requested.
        self.create_test_membership(member=member.name)
        schedule = self.create_test_dues_schedule(member=member.name, dues_rate=42)
        expected_rate = float(schedule.dues_rate)

        member.reload()
        self.assertTrue(
            any(e.dues_schedule == schedule.name for e in member.fee_change_history),
            "setUp assumption failed: after_insert did not write a fee_change_history row",
        )
        frappe.db.delete("Member Fee Change History", {"dues_schedule": schedule.name})
        member.reload()
        self.assertFalse(
            any(e.dues_schedule == schedule.name for e in member.fee_change_history),
            "the manufactured gap did not take -- fee_change_history still carries this schedule",
        )

        result = validate_fee_change_history_integrity(member_names=[member.name])
        self.assertEqual(result.get("errors"), 0, f"sweep reported an error for our own member: {result}")
        self.assertEqual(result.get("repaired"), 1)

        member.reload()
        matches = [e for e in member.fee_change_history if e.dues_schedule == schedule.name]
        self.assertEqual(
            len(matches),
            1,
            "the sweep must repair a schedule missing from fee_change_history, not just report it",
        )
        self.assertEqual(float(matches[0].new_dues_rate), expected_rate)

    def test_sweep_repairs_an_applied_amendment_missing_from_fee_change_history(self):
        """An Applied Contribution Amendment Request has no fee_change_history row.

        This is the gap a schedule-only sweep cannot see: an amendment can be
        the ONLY source of truth for a fee change (e.g. one applied without
        going through the schedule-update hook path). Insert one directly --
        bypassing the approval service entirely -- with status "Applied" from
        the start, so no code path ever gets a chance to record it. The sweep
        must still find and repair it via the amendment_request-keyed query,
        independent of the schedule-keyed one.
        """
        member = self.create_test_member()
        self.create_test_membership(member=member.name)
        schedule = self.create_test_dues_schedule(member=member.name)

        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "member": member.name,
                "membership": frappe.db.get_value("Membership", {"member": member.name}, "name"),
                "amendment_type": "Fee Change",
                "status": "Applied",
                "requested_date": frappe.utils.today(),
                "effective_date": frappe.utils.today(),
                "current_amount": schedule.dues_rate,
                "requested_amount": float(schedule.dues_rate) + 5,
                "reason": "Test amendment for #425 coverage",
            }
        )
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        # before_insert()'s set_auto_approval_status() unconditionally sets
        # status to "Approved"/"Pending Approval" during insert, overriding
        # whatever the caller requested -- so force it to "Applied" afterwards
        # with a direct db write (bypassing hooks entirely, on purpose: the
        # sweep only reads this table via raw SQL, so no application side
        # effect needs to have run for this test).
        frappe.db.set_value("Contribution Amendment Request", amendment.name, "status", "Applied")
        amendment.reload()

        member.reload()
        self.assertFalse(
            any(e.amendment_request == amendment.name for e in member.fee_change_history),
            "setUp assumption failed: inserting the amendment directly must not itself "
            "record a fee_change_history entry",
        )

        result = validate_fee_change_history_integrity(member_names=[member.name])
        self.assertEqual(result.get("errors"), 0, f"sweep reported an error for our own member: {result}")
        self.assertEqual(result.get("repaired"), 1)

        member.reload()
        matches = [e for e in member.fee_change_history if e.amendment_request == amendment.name]
        self.assertEqual(
            len(matches),
            1,
            "the sweep must repair an Applied amendment missing from fee_change_history",
        )
        self.assertEqual(float(matches[0].new_dues_rate), float(amendment.requested_amount))

    def test_sweep_is_quiet_on_consistent_fee_change_history(self):
        """Control: a member whose fee_change_history already matches their schedule.

        Unlike the donor sweep, this one must leave an already-correct row
        completely untouched -- not just non-duplicated. It is built
        specifically to never call the reconciliation path that would
        otherwise silently rewrite reason/change_type/change_date on every
        run (see the sweep's own docstring); this asserts that guarantee.
        """
        member = self.create_test_member()
        self.create_test_membership(member=member.name)
        schedule = self.create_test_dues_schedule(member=member.name)
        member.reload()
        before = [e for e in member.fee_change_history if e.dues_schedule == schedule.name]
        self.assertEqual(len(before), 1)
        before_snapshot = (
            before[0].reason,
            before[0].change_type,
            before[0].change_date,
            before[0].new_dues_rate,
        )

        result = validate_fee_change_history_integrity(member_names=[member.name])
        self.assertEqual(result.get("errors"), 0, f"sweep reported an error for our own member: {result}")
        self.assertEqual(result.get("repaired"), 0, "nothing was missing -- the sweep must not touch it")

        member.reload()
        after = [e for e in member.fee_change_history if e.dues_schedule == schedule.name]
        self.assertEqual(len(after), 1, "consistent data must not be duplicated by the sweep")
        after_snapshot = (
            after[0].reason,
            after[0].change_type,
            after[0].change_date,
            after[0].new_dues_rate,
        )
        self.assertEqual(
            before_snapshot,
            after_snapshot,
            "the sweep must never rewrite an existing fee_change_history row",
        )
