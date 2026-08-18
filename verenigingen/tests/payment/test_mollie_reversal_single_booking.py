"""
A Mollie reversal must book exactly ONCE, whichever route delivers it.

Two independent code paths book a donation refund, and neither can see the
other's work:

  * the payment-webhook sweep -- ``_process_pending_refunds`` -> Bank Transaction
    + **Journal Entry**, keyed ``{payment_id}_refund_{refund_id}``
  * the refund webhook -- ``handle_refund_webhook`` -> ``create_refund_payment_entry``
    -> **Payment Entry**, keyed with the *same* string

``create_unified_payment_entry`` checks only ``Payment Entry`` for that key, so a
refund already booked as a Journal Entry is booked a second time as a Payment
Entry. The two routes agree on the key and disagree on the doctype (#370).

This is NOT gated by the ``payment_entry_exists`` precondition that blocks
``process_reversal_webhook``: ``handle_refund_webhook`` never calls it.

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_reversal_single_booking
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_refund_payment_entry,
)


class TestMollieReversalBooksOnce(_RefundFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Mode of Payment", "Mollie"):
            mop = frappe.new_doc("Mode of Payment")
            mop.mode_of_payment = "Mollie"
            mop.insert(ignore_permissions=True)
        if not frappe.db.exists("Mode of Payment", "Mollie Refund"):
            mop = frappe.new_doc("Mode of Payment")
            mop.mode_of_payment = "Mollie Refund"
            mop.insert(ignore_permissions=True)

        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)

        # create_unified_payment_entry resolves its bank account by looking for an
        # Account literally named "Mollie" on the company when Mollie Settings has
        # none. Provide it rather than mutating Mollie Settings.
        self.mollie_account = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie"}, "name"
        )
        if not self.mollie_account:
            parent = frappe.get_value(
                "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
            )
            acct = frappe.new_doc("Account")
            acct.account_name = "Mollie"
            acct.company = COMPANY
            acct.parent_account = parent
            acct.account_type = "Bank"
            acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
            acct.insert(ignore_permissions=True)
            self.mollie_account = acct.name

        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )

        # Verenigingen Settings is a Single shared with every co-tenant test in the
        # shard, so save and restore it via addCleanup (a tearDown restore is
        # discarded by the base cleanup).
        self._restore_settings = {}
        for field, value in (("company", COMPANY), ("donation_receivable_account", self.receivable)):
            self._restore_settings[field] = frappe.db.get_single_value("Verenigingen Settings", field)
            frappe.db.set_single_value("Verenigingen Settings", field, value)
        self.addCleanup(self._restore_vs)

        self.donor = self._make_donor()
        donor_doc = frappe.get_doc("Donor", self.donor)
        donor_doc.get_or_create_customer()

        self.payment_id = f"tr_dbl_{frappe.generate_hash(length=8)}"
        self.refund_id = f"re_dbl_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id

    def _restore_vs(self):
        for field, value in self._restore_settings.items():
            frappe.db.set_single_value("Verenigingen Settings", field, value)
        frappe.db.commit()

    def _artefacts_for(self, key):
        """Every submitted-or-draft ledger artefact booked under this reversal key."""
        jes = frappe.get_all(
            "Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        pes = frappe.get_all(
            "Payment Entry", filters={"reference_no": key, "docstatus": ["!=", 2]}, pluck="name"
        )
        return jes, pes

    def test_refund_delivered_to_both_routes_books_exactly_once(self):
        """The sweep books a JE; the refund webhook must not then book a PE."""
        key = f"{self.payment_id}_refund_{self.refund_id}"

        # --- route 1: the payment-webhook sweep books Bank Transaction + Journal Entry
        bt = self._make_withdrawal_bank_transaction(100.0, key, self.bank_account)
        je_name = self._build_creator().create_refund_journal_entry(
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
            donation_doc=self.donation,
            original_payment_id=self.payment_id,
            bank_transaction_name=bt,
        )
        self.assertTrue(
            je_name, "sweep route did not book its Journal Entry - fixture problem, not the defect"
        )

        jes, pes = self._artefacts_for(key)
        self.assertEqual(len(jes), 1, "expected exactly one JE from the sweep route")
        self.assertEqual(len(pes), 0, "sweep route should not create a Payment Entry")

        # --- route 2: the same refund arrives at handle_refund_webhook, which calls this
        create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )

        jes, pes = self._artefacts_for(key)
        total = len(jes) + len(pes)
        self.assertEqual(
            total,
            1,
            "the same refund was booked twice under one key "
            f"{key!r}: Journal Entries={jes}, Payment Entries={pes}. "
            "The Payment-Entry route's idempotency check looks only at Payment Entry, "
            "so it cannot see the Journal Entry the sweep already wrote (#370).",
        )
