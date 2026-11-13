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
from verenigingen.tests.fixtures.mollie_account_fixtures import (
    ensure_bank_account_record,
    provisioned_mollie_settings,
)
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.payment_processors import DonationPaymentProcessor
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    customer_for_member,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
    get_bank_transaction_creator,
)

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
        # A row with NO bank account is what a `.get("bank_account")` on the error dict
        # would match (IS NULL), so dropping the error guard reddens this test.
        self._2583_seed_bt("OWN", MOLLIE_ACCOUNT_2583)
        self._2583_seed_bt("NOACCOUNT", None)
        with patch.object(
            BankTransactionCreator, "get_mollie_bank_account_config", return_value={"error": "x"}
        ), patch.object(BankTransactionCreator, "_find_matching_bank_transaction") as lookup:
            self.assertFalse(self._2583_status()["bank_transaction_created"])
            self.assertIsNone(self.processor._find_mollie_bank_transaction(self.payment_id))
        lookup.assert_not_called()

    def _2583_status(self):
        donor = self.create_test_donor(donor_email=f"bt.{frappe.generate_hash(length=6)}.2583@example.com")
        donation = self.create_test_donation(donor=donor.name, amount=15.0, paid=0)
        context = PaymentContext("donation", "Donation", donation.name)
        return self.processor.check_idempotency(context, self.payment_id)


class TestDonationEndToEndBookingScope2583(EnhancedTestCase):
    """process_successful_payment with the REAL creator, two real Bank Accounts."""

    def test_other_accounts_bank_transaction_is_not_the_booking(self):
        with provisioned_mollie_settings() as accounts:
            company = accounts["company"]
            mollie_ba = ensure_bank_account_record(company, accounts["clearing_account"])
            other_ba = ensure_bank_account_record(company, accounts["bank_account"])
            self.assertNotEqual(mollie_ba, other_ba)
            currency = frappe.db.get_value("Bank Account", mollie_ba, "account")
            currency = frappe.db.get_value("Account", currency, "account_currency")
            payment_id = f"tr_2583e{frappe.generate_hash(length=8)}"
            amount = 25.0

            creator = get_bank_transaction_creator()
            other_bt = creator.create(
                date=frappe.utils.getdate(),
                bank_account=other_ba,
                company=company,
                deposit=amount,
                withdrawal=0.0,
                currency=currency,
                reference_number=payment_id,
                transaction_id=payment_id,
                description="2583 other-account row",
            )
            self.assertTrue(other_bt, "premise: the other-account Bank Transaction must exist")
            self.assertEqual(frappe.db.get_value("Bank Transaction", other_bt, "bank_account"), other_ba)

            member = self.create_test_member(
                first_name="Scope",
                last_name="E2E2583",
                email=f"scope.{frappe.generate_hash(length=6)}.2583@example.com",
            )
            customer = customer_for_member(member)
            donor = self.create_test_donor(donor_email=f"scope.donor.{frappe.generate_hash(length=6)}@example.com")
            frappe.db.set_value("Donor", donor.name, "customer", customer)
            # Not submitted, like the real pre-webhook record: the processor later sets paid=1.
            donation = frappe.new_doc("Donation")
            donation.update(
                {
                    "donor": donor.name,
                    "donation_date": frappe.utils.today(),
                    "amount": amount,
                    "mode_of_payment": "Mollie",
                    "status": "One-time",
                    "company": company,
                    "payment_id": payment_id,
                    "paid": 0,
                }
            )
            donation.flags.ignore_validate = True
            donation.insert()
            self.track_test_record("Donation", donation.name)

            context = PaymentContext("donation", "Donation", donation.name)
            mollie_data = {
                "payment_id": payment_id,
                "amount": amount,
                "currency": currency,
                "paid_at": "2026-03-04T10:00:00+00:00",
                "method": "Mollie",
            }
            result = DonationPaymentProcessor().process_successful_payment(context, None, mollie_data)

            booked = (result.data or {}).get("bank_transaction")
            self.assertTrue(booked, f"a Bank Transaction must be booked on the Mollie account: {result.message}")
            self.assertNotEqual(booked, other_bt, "the other account's row was returned as the booking")
            self.assertEqual(frappe.db.get_value("Bank Transaction", booked, "bank_account"), mollie_ba)
