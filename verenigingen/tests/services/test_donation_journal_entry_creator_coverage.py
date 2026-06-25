"""
Real-DB coverage tests for DonationJournalEntryCreator.

Complements the existing (mock-based) ``test_donation_journal_entry_creator``
by driving the actual money-path logic against the real database:

    - ``create_from_mollie_payment`` / ``create_from_dict`` SUCCESS paths
      (a real, submitted Journal Entry with the correct
      Debit: Mollie Clearing / Credit: Donation Income legs and amount)
    - the Donation.journal_entry write-back
    - Bank Transaction reconciliation (deposit) + Reconciled status flip
    - idempotency (second identical call creates no duplicate JE)
    - error branches: missing company, zero amount, missing income account
    - date handling (paid_at parsing, dict date string, donation_date fallback)

No mocks of business logic / frappe.db are used; the service is given real
accounts via its ``_config`` attribute (legitimate configuration injection,
not a stub of behaviour) so the tests are deterministic and isolated from the
global Mollie / Verenigingen Settings singles.

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.services.test_donation_journal_entry_creator_coverage
"""

import frappe
from frappe.utils import flt, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.donation_journal_entry_creator import (
    DonationJournalEntryCreator,
)

# EUR company so the single-currency donation Journal Entry (Debit clearing /
# Credit income) does not trip ERPNext's multi-currency validation.
COMPANY = "_Test Company 2"


class _DonationJEFixtureMixin:
    """Builds the real accounting + donor/donation fixtures money-path tests need."""

    def _ensure_clearing_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing JE Cov"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        )
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing JE Cov"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _ensure_income_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income JE Cov"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
        )
        acct = frappe.new_doc("Account")
        acct.account_name = "Donation Income JE Cov"
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
            bank.bank_name = "JE Cov Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "Mollie JE Cov"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def _make_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"JE Cov Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"jecov.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _make_donation(self, donor_name, amount, payment_id=None, donation_date=None):
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = donation_date or today()
        donation.amount = amount
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.company = COMPANY
        if payment_id:
            donation.payment_id = payment_id
        donation.paid = 0
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        # The Donation doctype has no persisted ``company`` field; production
        # callers attach it in-memory on the doc they hand the creator, which is
        # how _resolve_company reads it (getattr fallback to Settings otherwise).
        doc = frappe.get_doc("Donation", donation.name)
        doc.company = COMPANY
        return doc

    def _make_bank_transaction(self, deposit, reference_number, bank_account):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = today()
        bt.bank_account = bank_account
        bt.company = COMPANY
        bt.deposit = deposit
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = reference_number
        bt.description = "JE cov bank txn"
        bt.status = "Unreconciled"
        bt.insert(ignore_permissions=True)
        bt.submit()
        self.track_test_record("Bank Transaction", bt.name)
        return bt.name

    def _build_creator(self):
        """Creator with real accounts injected so _get_config is deterministic."""
        creator = DonationJournalEntryCreator()
        creator._config = {
            "company": COMPANY,
            "clearing_account": self.clearing_account,
            "income_account": self.income_account,
            "cost_center": frappe.get_value("Company", COMPANY, "cost_center"),
        }
        return creator


class TestDonationJournalEntryCreatorMoneyPath(_DonationJEFixtureMixin, EnhancedTestCase):
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

    # ------------------------------------------------------------- success
    def test_create_from_mollie_payment_creates_correct_je(self):
        amount = 42.50
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        donation = self._make_donation(self._make_donor(), amount, payment_id=payment_id)

        with self.assertNoErrorLog():
            je_name = self.creator.create_from_mollie_payment(
                {
                    "id": payment_id,
                    "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
                    "paid_at": "2025-01-15T10:00:00+00:00",
                },
                donation,
            )

        self.assertTrue(je_name, "Expected a Journal Entry to be created")
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1, "JE should be submitted")
        self.assertEqual(je.cheque_no, payment_id)
        self.assertEqual(je.company, COMPANY)
        # Posting date parsed from paid_at, not today.
        self.assertEqual(getdate(je.posting_date), getdate("2025-01-15"))

        # Debit clearing, credit income, balanced at amount.
        clearing = [a for a in je.accounts if a.account == self.clearing_account]
        income = [a for a in je.accounts if a.account == self.income_account]
        self.assertTrue(clearing and income)
        self.assertEqual(flt(clearing[0].debit_in_account_currency), amount)
        self.assertEqual(flt(clearing[0].credit_in_account_currency), 0)
        self.assertEqual(flt(income[0].credit_in_account_currency), amount)
        self.assertEqual(flt(income[0].debit_in_account_currency), 0)

        # Donation linked back to the JE.
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "journal_entry"),
            je_name,
            "Donation.journal_entry must be written back",
        )

    def test_create_from_dict_creates_correct_je(self):
        amount = 17.00
        ref = f"dict-{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), amount)

        with self.assertNoErrorLog():
            je_name = self.creator.create_from_dict(
                {"amount": amount, "date": "2025-03-20", "reference_number": ref},
                donation,
            )

        self.assertTrue(je_name)
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.cheque_no, ref)
        self.assertEqual(getdate(je.posting_date), getdate("2025-03-20"))
        income = [a for a in je.accounts if a.account == self.income_account]
        self.assertEqual(flt(income[0].credit_in_account_currency), amount)
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "journal_entry"), je_name)

    def test_create_from_dict_date_fallback_to_donation_date(self):
        """No date AND no reference_number in dict -> JE still created and submitted.

        With no reference_number, the creator must NOT set cheque_date (otherwise
        ERPNext's validate_cheque_info rejects submit and secure_document_operation
        silently swallows the failure -> no JE). assertNoErrorLog proves no swallowed
        error; docstatus==1 proves the JE was actually created and submitted.
        """
        amount = 9.00
        ddate = "2026-02-02"
        donation = self._make_donation(self._make_donor(), amount, donation_date=ddate)

        with self.assertNoErrorLog():
            je_name = self.creator.create_from_dict({"amount": amount}, donation)
        self.assertTrue(je_name, "JE must be created even without a reference_number")
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1, "JE should be submitted (no swallowed cheque-info error)")
        self.assertFalse(je.cheque_no, "No reference_number -> cheque_no must stay empty")
        self.assertFalse(je.cheque_date, "No reference_number -> cheque_date must not be set")
        self.assertEqual(getdate(je.posting_date), getdate(ddate))
        # Donation linked back to the JE proves the full success path ran.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "journal_entry"), je_name)

    # ------------------------------------------------------- reconciliation
    def test_create_from_mollie_payment_reconciles_bank_transaction(self):
        amount = 30.00
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        donation = self._make_donation(self._make_donor(), amount, payment_id=payment_id)
        bt_name = self._make_bank_transaction(amount, payment_id, self.bank_account)

        je_name = self.creator.create_from_mollie_payment(
            {"id": payment_id, "amount": {"value": f"{amount:.2f}", "currency": "EUR"}},
            donation,
            bank_transaction_name=bt_name,
        )
        self.assertTrue(je_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertTrue(links, "Bank Transaction must be linked to the JE")
        self.assertEqual(flt(links[0].allocated_amount), amount)
        self.assertEqual(links[0].payment_document, "Journal Entry")
        # Fully allocated deposit -> Reconciled.
        self.assertEqual(bt.status, "Reconciled")

    def test_reconcile_is_idempotent_no_duplicate_link(self):
        amount = 12.00
        ref = f"rec-{frappe.generate_hash(length=10)}"
        bt_name = self._make_bank_transaction(amount, ref, self.bank_account)
        donation = self._make_donation(self._make_donor(), amount)
        # Create a JE to link.
        je_name = self.creator.create_from_dict(
            {"amount": amount, "date": today(), "reference_number": ref}, donation
        )
        self.assertTrue(je_name)

        # Reconcile twice; second call must not add a duplicate row.
        self.creator._reconcile_bank_transaction(bt_name, je_name, amount)
        self.creator._reconcile_bank_transaction(bt_name, je_name, amount)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == je_name]
        self.assertEqual(len(links), 1, "Reconciliation must be idempotent")

    # -------------------------------------------------------- idempotency
    def test_create_from_mollie_payment_idempotent(self):
        amount = 21.00
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        donation = self._make_donation(self._make_donor(), amount, payment_id=payment_id)
        payload = {"id": payment_id, "amount": {"value": f"{amount:.2f}", "currency": "EUR"}}

        first = self.creator.create_from_mollie_payment(payload, donation)
        second = self.creator.create_from_mollie_payment(payload, donation)
        self.assertEqual(first, second, "Second call must return the existing JE")
        self.assertEqual(
            frappe.db.count("Journal Entry", {"cheque_no": payment_id, "docstatus": ["!=", 2]}),
            1,
            "No duplicate Journal Entry may be created",
        )

    # -------------------------------------------------------- error paths
    def test_zero_amount_mollie_payment_creates_no_je(self):
        """A zero Mollie amount must never create a Journal Entry.

        The PaymentDataExtractor raises on a zero amount (allow_zero=False),
        so create_from_mollie_payment propagates the ValueError rather than
        silently returning None -- either way, no JE may be created.
        """
        ref = f"tr_{frappe.generate_hash(length=10)}"
        donation = self._make_donation(self._make_donor(), 10.00)
        with self.assertRaises(ValueError):
            self.creator.create_from_mollie_payment(
                {"id": ref, "amount": {"value": "0.00", "currency": "EUR"}},
                donation,
            )
        self.assertEqual(
            frappe.db.count("Journal Entry", {"cheque_no": ref, "docstatus": ["!=", 2]}),
            0,
            "No Journal Entry may be created for a zero-amount payment",
        )

    def test_zero_amount_dict_returns_none(self):
        donation = self._make_donation(self._make_donor(), 10.00)
        result = self.creator.create_from_dict(
            {"amount": 0, "reference_number": f"z-{frappe.generate_hash(length=8)}"}, donation
        )
        self.assertIsNone(result)

    def test_missing_company_returns_none(self):
        """No company on donation and no settings default -> None, no JE."""
        donation = self._make_donation(self._make_donor(), 10.00)
        donation.company = None
        creator = DonationJournalEntryCreator()  # no injected config
        orig = frappe.db.get_single_value("Verenigingen Settings", "company")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "company", "")
            result = creator.create_from_dict(
                {"amount": 10.0, "reference_number": f"nc-{frappe.generate_hash(length=8)}"},
                donation,
            )
            self.assertIsNone(result)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "company", orig)

    def test_config_error_missing_income_account_returns_none(self):
        """When _get_config reports an error, creation aborts with None."""
        donation = self._make_donation(self._make_donor(), 10.00)
        creator = DonationJournalEntryCreator()
        creator._config = {"company": COMPANY, "error": "Donation income account not configured"}
        # _get_config short-circuits on cached company match and returns the error.
        result = creator.create_from_dict(
            {"amount": 10.0, "reference_number": f"ce-{frappe.generate_hash(length=8)}"},
            donation,
        )
        self.assertIsNone(result)
