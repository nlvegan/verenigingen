"""The Mollie booking guard as a database constraint, not a check-then-act (#809, #746).

`unified_payment_entry_creator.py:74-79` reads "does a Payment Entry already exist for
this (payment_type, reference_no, party)" and books one if not. Two concurrent webhook
deliveries both read "no" and both book -- the read does not hold a lock. These tests
assert the backstop: a second row carrying the same key is refused by the database.

They fail loudly rather than skip when the field is missing. A skip here would be the
#746 failure again in test form -- the guard silently absent, with a green run over it.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.mollie_idempotency_key import (
    FIELDNAME,
    build_idempotency_key,
)


class TestMollieIdempotencyConstraint(EnhancedTestCase):
    def test_the_field_and_its_unique_index_are_installed(self):
        self.assertTrue(
            frappe.get_meta("Payment Entry").has_field(FIELDNAME),
            f"Payment Entry.{FIELDNAME} is not installed - the guard cannot be active",
        )
        index = frappe.db.sql(
            f"SHOW INDEX FROM `tabPayment Entry` WHERE Column_name = '{FIELDNAME}' AND Non_unique = 0"
        )
        self.assertTrue(index, f"no UNIQUE index on Payment Entry.{FIELDNAME}")

    def test_a_second_booking_of_one_mollie_reference_is_refused(self):
        reference_no = f"tr_{frappe.generate_hash()[:10]}"
        first = self.create_test_payment_entry(reference_no=reference_no)
        self.assertIsNotNone(
            first.get(FIELDNAME), "the before_save hook did not derive a key for a Mollie reference"
        )

        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            self.create_test_payment_entry(
                reference_no=reference_no, party_type=first.party_type, party=first.party
            )

    def test_a_refund_of_a_booked_payment_is_still_allowed(self):
        # The refund shares the payment id and differs only by suffix and payment_type.
        # If this ever fails, the key has been narrowed to the bare payment id and is
        # rejecting legitimate data.
        payment_id = f"tr_{frappe.generate_hash()[:10]}"
        original = self.create_test_payment_entry(reference_no=payment_id)
        refund = self.create_test_payment_entry(
            reference_no=f"{payment_id}_refund_re_{frappe.generate_hash()[:8]}",
            payment_type="Pay",
            party_type=original.party_type,
            party=original.party,
        )
        self.assertNotEqual(original.get(FIELDNAME), refund.get(FIELDNAME))

    def test_non_mollie_references_may_repeat_freely(self):
        # The whole reason the index is scoped: this app reuses invoice numbers and
        # payroll batch references across many Payment Entries by design.
        reference_no = f"nlvf-standfacturen-{frappe.generate_hash()[:6]}"
        first = self.create_test_payment_entry(reference_no=reference_no)
        second = self.create_test_payment_entry(
            reference_no=reference_no, party_type=first.party_type, party=first.party
        )
        self.assertIsNone(first.get(FIELDNAME))
        self.assertIsNone(second.get(FIELDNAME))

    def test_editing_a_draft_reference_moves_the_key(self):
        # before_save, not before_insert: a key frozen at insert time would guard the
        # tuple the row used to have.
        payment = self.create_test_payment_entry(reference_no=f"tr_{frappe.generate_hash()[:10]}")
        moved_to = f"tr_{frappe.generate_hash()[:10]}"
        payment.reference_no = moved_to
        payment.save()
        self.assertEqual(
            payment.get(FIELDNAME), build_idempotency_key(moved_to, payment.payment_type, payment.party)
        )
