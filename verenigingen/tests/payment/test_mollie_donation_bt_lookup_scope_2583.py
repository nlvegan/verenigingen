"""#2583: the donation processor's Bank Transaction lookups are scoped to the Mollie account.

reference_number is unique per bank account only (#1267). An unscoped lookup returned a
row of ANOTHER bank account, or a cancelled one, and called it this payment's booking.
Rows are seeded with raw SQL (no Link validation); only the config seam is patched.

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_donation_bt_lookup_scope_2583
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.payment_processors import DonationPaymentProcessor
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator

MOLLIE_ACCOUNT_2583 = "TEST-2583-Mollie Account"
OTHER_ACCOUNT_2583 = "TEST-2583-Other Account"
COMPANY_2583 = "TEST-2583-Company"


class TestDonationBankTransactionLookupScope2583(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.processor = DonationPaymentProcessor()
        self.payment_id = f"tr_2583{frappe.generate_hash(length=8)}"
        config = {"bank_account": MOLLIE_ACCOUNT_2583, "company": COMPANY_2583}
        patcher = patch.object(BankTransactionCreator, "get_mollie_bank_account_config", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _2583_seed_bt(self, suffix, bank_account, docstatus=1, company=COMPANY_2583):
        name = f"TEST-2583-{suffix}-{self.payment_id}"
        frappe.db.sql(
            """INSERT INTO `tabBank Transaction`
               (name, creation, modified, owner, modified_by, docstatus,
                bank_account, company, reference_number)
               VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, %s, %s, %s)""",
            (name, docstatus, bank_account, company, self.payment_id),
        )
        self.addCleanup(frappe.db.sql, "DELETE FROM `tabBank Transaction` WHERE name = %s", name)
        return name

    def test_other_accounts_row_is_not_this_payments_bank_transaction(self):
        self._2583_seed_bt("OTHER", OTHER_ACCOUNT_2583)
        self.assertFalse(self._2583_status()["bank_transaction_created"])
        self.assertIsNone(self.processor._find_mollie_bank_transaction(self.payment_id))

    def test_cancelled_row_is_not_this_payments_bank_transaction(self):
        self._2583_seed_bt("CANCELLED", MOLLIE_ACCOUNT_2583, docstatus=2)
        self.assertFalse(self._2583_status()["bank_transaction_created"])
        self.assertIsNone(self.processor._find_mollie_bank_transaction(self.payment_id))

    def test_own_row_is_found_even_when_a_newer_row_exists_on_another_account(self):
        own = self._2583_seed_bt("OWN", MOLLIE_ACCOUNT_2583)
        frappe.db.sql("UPDATE `tabBank Transaction` SET creation = creation - INTERVAL 1 DAY WHERE name = %s", own)
        self._2583_seed_bt("NEWER-OTHER", OTHER_ACCOUNT_2583)
        self.assertTrue(self._2583_status()["bank_transaction_created"])
        self.assertEqual(self.processor._find_mollie_bank_transaction(self.payment_id), own)

    def test_unresolvable_mollie_account_reports_none(self):
        self._2583_seed_bt("OWN", MOLLIE_ACCOUNT_2583)
        with patch.object(
            BankTransactionCreator, "get_mollie_bank_account_config", return_value={"error": "x"}
        ):
            self.assertFalse(self._2583_status()["bank_transaction_created"])
            self.assertIsNone(self.processor._find_mollie_bank_transaction(self.payment_id))

    def _2583_status(self):
        donor = self.create_test_donor(donor_email=f"bt.{frappe.generate_hash(length=6)}.2583@example.com")
        donation = self.create_test_donation(donor=donor.name, amount=15.0, paid=0)
        context = PaymentContext("donation", "Donation", donation.name)
        return self.processor.check_idempotency(context, self.payment_id)
