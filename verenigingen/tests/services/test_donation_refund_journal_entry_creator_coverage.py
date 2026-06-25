"""
Real-DB coverage tests for DonationRefundJournalEntryCreator (priority target,
previously 28% covered).

Drives the actual refund money-path against the real database. A donation
refund is the REVERSE of the original donation income entry:

    Debit:  Donation Income Account  (reduce recognised income)
    Credit: Mollie Clearing Account  (money leaves the clearing account)

This direction is the load-bearing correctness property: getting it backwards
would re-recognise income on a refund. Each test asserts the real Journal
Entry's debit/credit legs and amounts, plus the refund-specific reference
number, withdrawal-based Bank Transaction reconciliation, idempotency and the
error branches.

No business-logic / frappe.db mocks. Real accounts are supplied to the service
via its ``_config`` attribute (configuration injection, not a behaviour stub).

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage
"""

import frappe
from frappe.utils import flt, getdate, nowdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.donation_refund_journal_entry_creator import (
    DonationRefundJournalEntryCreator,
)

COMPANY = "_Test Company 2"


class _RefundFixtureMixin:
    def _ensure_clearing_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing Refund Cov"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        )
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing Refund Cov"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _ensure_income_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income Refund Cov"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
        )
        acct = frappe.new_doc("Account")
        acct.account_name = "Donation Income Refund Cov"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Income Account"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _ensure_bank_account(self, gl_account):
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "Refund Cov Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "Mollie Refund Cov"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def _make_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Refund Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"refund.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _make_donation(self, donor_name, amount):
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = today()
        donation.amount = amount
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.paid = 1
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        # Donation has no persisted ``company`` field; attach it in-memory the
        # way a production caller hands it to the creator.
        doc = frappe.get_doc("Donation", donation.name)
        doc.company = COMPANY
        return doc

    def _make_withdrawal_bank_transaction(self, withdrawal, reference_number, bank_account):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = today()
        bt.bank_account = bank_account
        bt.company = COMPANY
        bt.deposit = 0
        bt.withdrawal = withdrawal
        bt.currency = "EUR"
        bt.reference_number = reference_number
        bt.description = "Refund cov bank txn"
        bt.status = "Unreconciled"
        bt.insert(ignore_permissions=True)
        bt.submit()
        self.track_test_record("Bank Transaction", bt.name)
        return bt.name

    def _build_creator(self):
        creator = DonationRefundJournalEntryCreator()
        creator._config = {
            "company": COMPANY,
            "clearing_account": self.clearing_account,
            "income_account": self.income_account,
            "cost_center": frappe.get_value("Company", COMPANY, "cost_center"),
        }
        return creator


class TestDonationRefundJournalEntryCreator(_RefundFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # "Mollie" Mode of Payment is not an app fixture; seed it via the factory
        # so the hard-coded donation.mode_of_payment = "Mollie" works in isolation.
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        self.creator = self._build_creator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    # ---------------------------------------------------------- correctness
    def test_refund_je_reverses_donation_with_correct_accounts(self):
        """The load-bearing test: refund debits income, credits clearing."""
        amount = 35.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)

        with self.assertNoErrorLog():
            je_name = self.creator.create_refund_journal_entry(
                refund_id=refund_id,
                refund_amount=amount,
                refund_date="2025-05-12T08:00:00+00:00",
                donation_doc=donation,
                original_payment_id=payment_id,
            )

        self.assertTrue(je_name, "Expected a refund Journal Entry")
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1, "Refund JE should be submitted")
        self.assertEqual(je.company, COMPANY)
        # Reference number combines original payment + refund id.
        self.assertEqual(je.cheque_no, f"{payment_id}_refund_{refund_id}")
        # Posting date parsed from the ISO refund_date.
        self.assertEqual(getdate(je.posting_date), getdate("2025-05-12"))

        income_rows = [a for a in je.accounts if a.account == self.income_account]
        clearing_rows = [a for a in je.accounts if a.account == self.clearing_account]
        self.assertTrue(income_rows and clearing_rows)
        # REVERSED vs a donation: income is DEBITED, clearing is CREDITED.
        self.assertEqual(flt(income_rows[0].debit_in_account_currency), amount)
        self.assertEqual(flt(income_rows[0].credit_in_account_currency), 0)
        self.assertEqual(flt(clearing_rows[0].credit_in_account_currency), amount)
        self.assertEqual(flt(clearing_rows[0].debit_in_account_currency), 0)
        # Balanced.
        self.assertEqual(
            sum(flt(a.debit_in_account_currency) for a in je.accounts),
            sum(flt(a.credit_in_account_currency) for a in je.accounts),
        )

    def test_refund_date_none_falls_back_to_today(self):
        amount = 10.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)

        je_name = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        self.assertTrue(je_name)
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(getdate(je.posting_date), getdate(nowdate()))

    def test_refund_date_unparseable_falls_back_to_today(self):
        """A garbage date string must not crash; it falls back to today."""
        amount = 8.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)

        je_name = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date="not-a-date",
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        self.assertTrue(je_name)
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(getdate(je.posting_date), getdate(nowdate()))

    # ------------------------------------------------------- reconciliation
    def test_refund_reconciles_withdrawal_bank_transaction(self):
        amount = 20.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)
        bt_name = self._make_withdrawal_bank_transaction(
            amount, f"{payment_id}_refund_{refund_id}", self.bank_account
        )

        je_name = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
            bank_transaction_name=bt_name,
        )
        self.assertTrue(je_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertTrue(links, "Withdrawal Bank Transaction must link to the refund JE")
        self.assertEqual(flt(links[0].allocated_amount), amount)
        self.assertEqual(links[0].payment_document, "Journal Entry")
        # Fully allocated against the withdrawal -> Reconciled.
        self.assertEqual(bt.status, "Reconciled")

    # -------------------------------------------------------- idempotency
    def test_refund_je_is_idempotent(self):
        amount = 15.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)
        reference = f"{payment_id}_refund_{refund_id}"

        first = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        second = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        self.assertEqual(first, second, "Duplicate refund must return the existing JE")
        self.assertEqual(
            frappe.db.count("Journal Entry", {"cheque_no": reference, "docstatus": ["!=", 2]}),
            1,
            "No duplicate refund Journal Entry may be created",
        )

    def test_idempotent_refund_reconciles_existing_bank_transaction(self):
        """Second call on an existing refund JE still reconciles a BT."""
        amount = 22.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)
        reference = f"{payment_id}_refund_{refund_id}"

        # First create the JE (no BT yet).
        je_name = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        self.assertTrue(je_name)

        # Now a withdrawal BT shows up; the idempotent re-call must reconcile it.
        bt_name = self._make_withdrawal_bank_transaction(amount, reference, self.bank_account)
        again = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
            bank_transaction_name=bt_name,
        )
        self.assertEqual(again, je_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertTrue(links, "Idempotent re-call must reconcile the late-arriving BT")

    # -------------------------------------------------------- error paths
    def test_missing_company_returns_none(self):
        amount = 10.00
        donation = self._make_donation(self._make_donor(), amount)
        donation.company = None
        creator = DonationRefundJournalEntryCreator()  # no injected config
        orig = frappe.db.get_single_value("Verenigingen Settings", "company")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "company", "")
            result = creator.create_refund_journal_entry(
                refund_id=f"re_{frappe.generate_hash(length=8)}",
                refund_amount=amount,
                refund_date=None,
                donation_doc=donation,
                original_payment_id=f"tr_{frappe.generate_hash(length=8)}",
            )
            self.assertIsNone(result)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "company", orig)

    def test_config_error_returns_none(self):
        amount = 10.00
        donation = self._make_donation(self._make_donor(), amount)
        creator = DonationRefundJournalEntryCreator()
        creator._config = {"company": COMPANY, "error": "Mollie clearing account not configured"}
        result = creator.create_refund_journal_entry(
            refund_id=f"re_{frappe.generate_hash(length=8)}",
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=f"tr_{frappe.generate_hash(length=8)}",
        )
        self.assertIsNone(result)

    def test_reconcile_is_idempotent_no_duplicate_link(self):
        amount = 18.00
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)
        reference = f"{payment_id}_refund_{refund_id}"
        bt_name = self._make_withdrawal_bank_transaction(amount, reference, self.bank_account)
        je_name = self.creator.create_refund_journal_entry(
            refund_id=refund_id,
            refund_amount=amount,
            refund_date=None,
            donation_doc=donation,
            original_payment_id=payment_id,
        )
        self.assertTrue(je_name)

        self.creator._reconcile_bank_transaction(bt_name, je_name, amount)
        self.creator._reconcile_bank_transaction(bt_name, je_name, amount)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertEqual(len(links), 1, "Reconciliation must be idempotent")
