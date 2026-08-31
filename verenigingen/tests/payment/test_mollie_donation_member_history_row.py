"""The Mollie donation webhook's Member payment-history row (#465).

`UnifiedWebhookWrapperService._update_member_payment_history` builds the one row a
member gets for a donation. Measured on `test_site_2` against the unmodified file,
with the three-way control that decides the fix:

    Member Payment History has 'invoice'            -> True
    Member Payment History has 'mollie_payment_id'  -> False
    Member Payment History has 'journal_entry'      -> False
    Member Payment History has 'payment_type'       -> False
    CONTROL 'CONTROL_definitely_not_a_field'        -> False

An unknown key is dropped on the way to the table -- `append()` sets it as a plain
Python attribute, so `row.get("mollie_payment_id")` reads back in memory, but it is
absent from `get_valid_dict()` and the column does not exist. Nothing raises.

The `invoice` half is louder and is what this module is really about. `invoice` is a
Dynamic Link keyed on `invoice_doctype`, and the builder set only the first. The write
lands because `MemberFinancialHistoryManager` persists through `update_child_table()`,
which does not run `_validate_links()` -- but the NEXT full save of the parent Member
does, and `get_invalid_links()` throws on a Dynamic Link whose companion is empty:

    invoice set, invoice_doctype EMPTY -> ValidationError: Invoice DocType must be set first
    invoice set, invoice_doctype set   -> saves (CONTROL)
    invoice_doctype set, bad name      -> LinkValidationError (CONTROL)

So one donation to a member-linked donor made that Member unsavable by every
full-document path -- the shape
`patches/v2_2/clear_stale_membership_payment_history_links.py` exists to clean up,
where 430 members could not be saved at all.

Zero test coverage before this module: every donation-webhook test uses a donor with
no `Donor.member`, so `_update_member_payment_history` returns at its guard and the
builder never runs.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services import (
    webhook_wrapper_service_unified as wws,
)

HISTORY_DOCTYPE = "Member Payment History"


class TestMollieDonationMemberHistoryRow(EnhancedTestCase):
    """One donation, one member-linked donor, one payment-history row."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

        # The wrapper is built without __init__ so no live Mollie client or
        # idempotency manager is needed: this suite exercises one method, and
        # every collaborator it touches (the history manager, the payment-data
        # extractor) is real.
        from unittest.mock import MagicMock

        self.svc = object.__new__(wws.UnifiedWebhookWrapperService)
        self.svc.logger = wws.MollieLogger("test_i465_member_history_row")
        self.svc._debug_mode = False
        self.svc.idempotency_manager = MagicMock()

        self.member = self.create_test_member(first_name="MollieDonationHistory")
        self.donor = self.create_test_donor(donor_name="I465 Donor", member=self.member.name)
        self.donation = self.create_test_donation(donor=self.donor.name, amount=25.0)

        self.payment_data = {
            "id": f"tr_i465_{frappe.generate_hash(length=8)}",
            "amount": {"value": "25.00", "currency": "EUR"},
            # snake_case: PaymentDataExtractor.extract_payment_date reads
            # `paid_at`/`created_at`, not Mollie's raw camelCase.
            "paid_at": "2025-04-10T12:00:00+00:00",
            "method": "ideal",
        }

    # ------------------------------------------------------------------
    def build_the_row(self):
        """Run the production writer and return the persisted row."""
        self.assertTrue(
            self.svc._update_member_payment_history(self.donation, self.payment_data),
            "_update_member_payment_history reported failure",
        )
        member = frappe.get_doc("Member", self.member.name)
        rows = [r for r in member.payment_history if r.invoice == self.donation.name]
        self.assertEqual(len(rows), 1, "expected exactly one history row for the donation")
        return rows[0]

    # ------------------------------------------------------------------
    def test_an_unlinked_donor_produces_no_row_at_all(self):
        """Premise, asserted on the guard rather than on the fixture.

        Every existing donation-webhook test uses a donor with no `Donor.member`, so
        the writer returns True at its guard and the builder never runs -- which is
        the coverage gap that let #465 sit, and the way this module could pass
        vacuously. Re-reading `Donor.member` after setUp wrote it would prove nothing,
        so this clears the link and asserts the True-with-zero-rows contract, then
        restores it and asserts one row appears.
        """
        frappe.db.set_value("Donor", self.donor.name, "member", None, update_modified=False)
        self.donation.reload()
        self.assertTrue(
            self.svc._update_member_payment_history(self.donation, self.payment_data),
            "an unlinked donor is not a failure -- it is nothing to do",
        )
        self.assertEqual(
            frappe.get_doc("Member", self.member.name).payment_history,
            [],
            "no member is linked, so no row may be written",
        )

        # CONTROL: with the link restored, the same call writes exactly one row.
        frappe.db.set_value(
            "Donor", self.donor.name, "member", self.member.name, update_modified=False
        )
        self.build_the_row()

    def test_the_row_names_the_donation_doctype_for_its_dynamic_link(self):
        """`invoice` is a Dynamic Link; `invoice_doctype` is its companion."""
        row = self.build_the_row()
        self.assertEqual(row.invoice, self.donation.name)
        self.assertEqual(row.invoice_doctype, "Donation")

    def test_the_member_can_still_be_saved_afterwards(self):
        """The consequence, not the field: an empty companion throws on every
        later full save of the parent Member, whatever the caller was changing."""
        self.build_the_row()
        member = frappe.get_doc("Member", self.member.name)
        member.notes = "an unrelated edit"
        member.save()  # must not raise

    def test_the_row_records_that_it_is_a_donation(self):
        """`transaction_type` is this doctype's classifier and its sibling Mollie
        writers already set it ("Membership Payment"). A NULL here is
        indistinguishable from an unclassified legacy row."""
        row = self.build_the_row()
        self.assertEqual(row.transaction_type, "Donation")

    def test_every_key_the_builder_writes_is_a_real_field(self):
        """The class assertion: no key is silently dropped.

        Reads the dict the builder actually produced rather than the persisted row,
        because a dropped key leaves no trace in the row at all -- which is the whole
        defect.
        """
        from verenigingen.utils import member_financial_history_manager as mfhm

        captured = {}
        manager_factory = mfhm.get_payment_history_manager

        def capture(member_doc):
            manager = manager_factory(member_doc)
            original = manager.add_or_update_entry

            def wrapper(entry_id, entry_builder, id_field_name="invoice"):
                # Call the builder ONCE and replay the result: some builders in this
                # app hit the DB (`bulk_invoice_generation_service.build_invoice_entry`
                # does a retrying invoice read), so a capture idiom that invokes twice
                # doubles that work wherever it gets copied.
                captured.update(entry_builder())
                return original(entry_id, lambda: dict(captured), id_field_name)

            manager.add_or_update_entry = wrapper
            return manager

        # The writer imports the factory inside the method, so the patch has to
        # land on the defining module rather than on the service module.
        mfhm.get_payment_history_manager = capture
        try:
            self.build_the_row()
        finally:
            mfhm.get_payment_history_manager = manager_factory

        self.assertTrue(captured, "the entry builder never ran")
        known = {df.fieldname for df in frappe.get_meta(HISTORY_DOCTYPE).fields}
        self.assertEqual(
            sorted(k for k in captured if k not in known),
            [],
            f"builder wrote keys that are not fields of {HISTORY_DOCTYPE}",
        )

    def test_the_row_carries_no_second_dynamic_link(self):
        """Pins the decision NOT to re-home the Journal Entry into
        `payment_entry`/`payment_entry_doctype`.

        That pair is a Dynamic Link on a table whose only deletion-cleanup hook
        (`sales_invoice_hooks.on_trash`) covers Sales Invoice, so pointing it at a
        Journal Entry would re-create #465's own failure mode the first time such an
        entry were deleted. The JE is already on `Donation Payment.journal_entry`.

        A regression pin, not coverage of a live path: `_update_member_payment_history`
        no longer takes a `journal_entry_name` at all.
        """
        row = self.build_the_row()
        self.assertIsNone(row.payment_entry)
        self.assertIsNone(row.payment_entry_doctype)
