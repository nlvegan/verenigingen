"""The Mollie donation webhook's Member payment-history row (#465, #713).

#465 made `UnifiedWebhookWrapperService._update_member_payment_history`'s row
well-formed (a real `invoice_doctype`, no fields that do not exist on `Member
Payment History`). #465 explicitly deferred the modelling question its own fix
raised: `PaymentHistoryService.load_payment_history_batched` clears and rebuilds
`payment_history` from Sales Invoices only, so a donation row placed there does
not survive the next full refresh. That is #713.

The decision (#713) is option 2: the donation writer stops writing to
`payment_history` at all, rather than teaching the rebuild about donations.
Full reasoning, verified per code path rather than assumed, lives on
`_update_member_payment_history`'s docstring in
`webhook_wrapper_service_unified.py` -- summarised:

1. `Member Payment History` is documented, by its own writers, as an
   invoice-derived cache (`_step_rebuild_payment_history`'s "matching the
   invoice-only model the other writers already enforce",
   `clear_stale_membership_payment_history_links.py`'s "derived cache").
2. Whether a stray donation-shaped row gets cleaned up varies by path and is
   NOT a reliable sweep -- one path wipes the whole table but only for a
   member with a `customer` set; another reports a removal but never
   persists it; a third does persist a removal, but through an unrelated
   branch, and only when a different history type also changed. That
   inconsistency is itself part of the case for not writing the row: relying
   on any of it to clean up after a bad write would be worse than not
   writing at all.
3. Nothing is lost by not writing the row. A donation only reaches
   `_update_member_payment_history` through `donation.donor` (`Donation.donor`
   is `reqd` unless anonymous, and the member lookup runs only through
   `Donor.member` -- `Donation` has no `member` field of its own), and that
   same donation is already recorded -- unconditionally of any member link --
   on `Donor.donor_history` (Donation's own `after_insert`/`on_update` hooks,
   `hooks/doc_events.py`) and on `Donation.payments`
   (`_update_donation_payment_history_atomic`, same webhook call, same
   values, including the Mollie payment id and Journal Entry this method
   never carried). The idempotency manager reads `Donation.payments`, never
   this table, so removing this write cannot affect webhook re-delivery.
4. No repair patch for rows a pre-#713 build already wrote: not because they
   self-heal (they may not -- see point 2), but because the precondition for
   this method to have ever written one -- a Donor linked to a Member -- has
   never occurred in production. Measured on veg11: 431 `Member Payment
   History` rows, all `invoice_doctype = "Sales Invoice"`, zero Donors with a
   linked Member.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services import (
    webhook_wrapper_service_unified as wws,
)

HISTORY_DOCTYPE = "Member Payment History"


class TestMollieDonationMemberHistoryRow(EnhancedTestCase):
    """A member-linked donation writes no `Member Payment History` row -- and
    loses no information by not writing one."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

        # The wrapper is built without __init__ so no live Mollie client or
        # idempotency manager is needed: this suite exercises one method, and
        # every collaborator it touches (the history manager, the payment-data
        # extractor) is real.
        from unittest.mock import MagicMock

        self.svc = object.__new__(wws.UnifiedWebhookWrapperService)
        self.svc.logger = wws.MollieLogger("test_i713_member_history_row")
        self.svc._debug_mode = False
        self.svc.idempotency_manager = MagicMock()

        self.member = self.create_test_member(first_name="MollieDonationHistory")
        self.donor = self.create_test_donor(donor_name="I713 Donor", member=self.member.name)
        self.donation = self.create_test_donation(donor=self.donor.name, amount=25.0)

        self.payment_data = {
            "id": f"tr_i713_{frappe.generate_hash(length=8)}",
            "amount": {"value": "25.00", "currency": "EUR"},
            # snake_case: PaymentDataExtractor.extract_payment_date reads
            # `paid_at`/`created_at`, not Mollie's raw camelCase.
            "paid_at": "2025-04-10T12:00:00+00:00",
            "method": "ideal",
        }

    # ------------------------------------------------------------------
    def test_a_member_linked_donation_writes_no_payment_history_row(self):
        """The core decision: the writer reports success but appends nothing.

        Before #713's fix this method built a row via
        `MemberFinancialHistoryManager` -- this is the RED assertion that
        distinguishes "no row, ever" (option 2) from "the rebuild forgot about
        it" (option 1): the row must never exist in the first place, not merely
        survive a rebuild.
        """
        self.assertTrue(
            self.svc._update_member_payment_history(self.donation, self.payment_data),
            "a no-op is not a failure",
        )
        member = frappe.get_doc("Member", self.member.name)
        rows = [r for r in member.payment_history if r.invoice == self.donation.name]
        self.assertEqual(
            rows,
            [],
            "Member Payment History is invoice-only (#713); a donation must not appear",
        )

    def test_an_unlinked_donor_also_writes_no_row(self):
        """Same outcome whether or not a member is linked -- the method no
        longer branches on it at all."""
        frappe.db.set_value("Donor", self.donor.name, "member", None, update_modified=False)
        self.donation.reload()
        self.assertTrue(self.svc._update_member_payment_history(self.donation, self.payment_data))
        self.assertEqual(frappe.get_doc("Member", self.member.name).payment_history, [])

    def test_the_donation_is_already_recorded_without_any_member_row(self):
        """Control for "nothing is lost": `Donor.donor_history` already carries
        this donation from the Donation's own `after_insert` hook -- written in
        `setUp`, before `_update_member_payment_history` ever runs -- so the
        member-side row this test suite used to require was always redundant
        with data that exists unconditionally of any member link.
        """
        donor = frappe.get_doc("Donor", self.donor.name)
        matches = [e for e in donor.donor_history if e.donation_reference == self.donation.name]
        self.assertEqual(len(matches), 1, "Donation.after_insert must record it on donor_history")
        self.assertEqual(matches[0].donation_amount, 25.0)

        # Calling the (now no-op) member writer changes nothing about that record.
        self.svc._update_member_payment_history(self.donation, self.payment_data)
        donor.reload()
        matches = [e for e in donor.donor_history if e.donation_reference == self.donation.name]
        self.assertEqual(len(matches), 1)

    def test_a_stale_donation_shaped_row_is_swept_by_a_full_rebuild_when_reachable(self):
        """Confirms the rebuild path DOES discard a stale donation row -- for the
        one population it can reach: a member with `customer` set.

        Simulates a pre-#713 row by appending one shaped exactly like the old
        builder's output directly to `payment_history`, then runs the SAME full
        rebuild `PaymentHistoryService.load_payment_history_batched` that #713's
        issue named -- unmodified by this fix, because the fix is in the writer,
        not the rebuild.

        This is NOT the reason a repair patch is skipped (see the module
        docstring and the sibling test below) -- `load_payment_history_batched`
        returns before touching `payment_history` at all when `member.customer`
        is unset, so this path is not a general-purpose sweep. It is recorded
        here so a future change to the rebuild cannot silently start preserving
        orphaned donation rows instead of the two real homes, for the members it
        does reach.
        """
        from verenigingen.services.member.payment.payment_history_service import (
            get_payment_history_service,
        )

        customer = self.factory.create_test_customer()
        member = frappe.get_doc("Member", self.member.name)
        member.customer = customer.name
        member.append(
            "payment_history",
            {
                "invoice": self.donation.name,
                "invoice_doctype": "Donation",
                "transaction_type": "Donation",
                "amount": 25.0,
                "payment_method": "Mollie",
                "status": "Completed",
            },
        )
        member.save()
        member.reload()
        self.assertEqual(len(member.payment_history), 1, "the stale row must be present before the rebuild")

        result = get_payment_history_service().load_payment_history_batched(member)
        self.assertTrue(result.success)

        # load_payment_history_batched only mutates the in-memory doc; the
        # production orchestrator (_step_save_history_changes) is what persists
        # it. Do the same here rather than asserting on an unsaved document.
        member.flags.ignore_version = True
        member.flags.ignore_links = True
        member.save()
        member.reload()
        self.assertEqual(
            [r.invoice for r in member.payment_history],
            [],
            "a full rebuild pulls Sales Invoices only, so the stale donation row must be gone",
        )

        # The donation's real homes are untouched by a Member-side rebuild.
        donor = frappe.get_doc("Donor", self.donor.name)
        matches = [e for e in donor.donor_history if e.donation_reference == self.donation.name]
        self.assertEqual(len(matches), 1)

    def test_a_stale_donation_shaped_row_survives_indefinitely_without_a_customer(self):
        """Pins the known limit of the rebuild-based sweep: it is unreachable for
        a member with no `customer`, so a stale row there is NOT cleaned up by
        `load_payment_history_batched` at all.

        This is exactly why "no repair patch is needed" (#713's decision) rests
        on the precondition never having occurred in production (veg11: zero
        Donors linked to a Member), not on any sweep being reliable. If that
        precondition ever stops holding, this test is where "the rebuild will
        quietly fix it" would be caught as false.
        """
        from verenigingen.services.member.payment.payment_history_service import (
            get_payment_history_service,
        )

        # create_test_member auto-creates and links a Customer; null it out so
        # this test exercises the no-customer branch it is named for.
        frappe.db.set_value("Member", self.member.name, "customer", None, update_modified=False)
        member = frappe.get_doc("Member", self.member.name)
        self.assertFalse(member.customer, "the precondition of this test: no customer linked")
        member.append(
            "payment_history",
            {
                "invoice": self.donation.name,
                "invoice_doctype": "Donation",
                "transaction_type": "Donation",
                "amount": 25.0,
                "payment_method": "Mollie",
                "status": "Completed",
            },
        )
        member.save()
        member.reload()
        self.assertEqual(len(member.payment_history), 1)

        result = get_payment_history_service().load_payment_history_batched(member)
        self.assertTrue(result.success)
        self.assertTrue(result.data.get("skipped"), "no customer -> the rebuild must skip, not clear")

        member.reload()
        self.assertEqual(
            [r.invoice for r in member.payment_history],
            [self.donation.name],
            "without a customer, the stale row is NOT swept -- it survives indefinitely",
        )
