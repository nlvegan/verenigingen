"""
Real-DB coverage tests for BankTransactionCreator.

Exercises the source-agnostic Bank Transaction creation paths against the real
database, focusing on the branches the existing payment/SEPA suites do not
cover:

    - create_from_dict: deposit vs withdrawal sign handling, ISO-string date
      parsing, party / bank-party / custom_* field pass-through, the
      missing-date and missing-amount guard branches, idempotency
    - create() low-level idempotency
    - create_from_settlement idempotency + creation
    - check_already_processed: Bank Transaction Draft/Submitted/Cancelled and
      the Payment Entry branch
    - link_payment_entry: real reconciliation against a Payment Entry, plus the
      already-linked idempotent short-circuit

No business-logic / frappe.db mocks: every assertion is against real documents.

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.services.test_bank_transaction_creator_coverage
"""

import frappe
from frappe.utils import flt, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
)

COMPANY = "_Test Company 2"


class _BankTxnFixtureMixin:
    def _ensure_gl_account(self, name_suffix=""):
        account_name = f"BTCreator Cov Bank{name_suffix}"
        name = frappe.get_value("Account", {"company": COMPANY, "account_name": account_name}, "name")
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        )
        acct = frappe.new_doc("Account")
        acct.account_name = account_name
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    def _ensure_bank_account(self, gl_account, name_suffix=""):
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "BTCreator Cov Bank Inst"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"BTCreator Cov{name_suffix}"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def _ref(self, prefix="ref"):
        return f"{prefix}-{frappe.generate_hash(length=12)}"

    def _insert_draft_bank_transaction(self, reference_number, bank_account, company=COMPANY, amount=12.0):
        """Simulate a Bank Transaction left in draft by an earlier caller who
        lacked submit permission -- exactly what ``_create_bank_transaction``
        produces on that branch."""
        draft = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": bank_account,
                "company": company,
                "deposit": amount,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": reference_number,
                "description": "pre-existing draft",
                "status": "Unreconciled",
                "unallocated_amount": amount,
                "allocated_amount": 0.0,
            }
        )
        draft.insert(ignore_permissions=True)
        return draft


class TestBankTransactionCreatorFromDict(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    # ---------------------------------------------------- deposit / withdrawal
    def test_positive_amount_creates_deposit(self):
        ref = self._ref("dep")
        bt_name = self.creator.create_from_dict(
            {"date": "2025-06-01", "amount": 75.50, "currency": "EUR", "reference_number": ref,
             "description": "Monthly donation"},
            bank_account=self.bank_account, company=COMPANY, source_type="Donation Import",
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(flt(bt.deposit), 75.50)
        self.assertEqual(flt(bt.withdrawal), 0.0)
        self.assertEqual(getdate(bt.date), getdate("2025-06-01"))
        self.assertEqual(bt.reference_number, ref)
        self.assertEqual(bt.description, "Monthly donation")
        self.assertEqual(flt(bt.unallocated_amount), 75.50)

    def test_negative_amount_creates_withdrawal(self):
        ref = self._ref("wd")
        bt_name = self.creator.create_from_dict(
            {"date": today(), "amount": -40.00, "reference_number": ref},
            bank_account=self.bank_account, company=COMPANY, source_type="Refund Import",
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(flt(bt.deposit), 0.0)
        self.assertEqual(flt(bt.withdrawal), 40.00)
        self.assertEqual(flt(bt.unallocated_amount), 40.00)
        # Default description derived from source_type.
        self.assertEqual(bt.description, "Refund Import transaction")

    def test_party_and_bank_party_and_custom_fields_pass_through(self):
        ref = self._ref("party")
        customer = frappe.get_value("Customer", {}, "name")
        bt_name = self.creator.create_from_dict(
            {
                "date": today(),
                "amount": 12.34,
                "reference_number": ref,
                "party_type": "Customer",
                "party": customer,
                "bank_party_name": "Jane Donor",
                "bank_party_iban": "NL91ABNA0417164300",
                "bank_party_account_number": "0417164300",
                "custom_member": None,  # None must be dropped, not written
            },
            bank_account=self.bank_account, company=COMPANY,
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.party_type, "Customer")
        self.assertEqual(bt.party, customer)
        self.assertEqual(bt.bank_party_name, "Jane Donor")
        self.assertEqual(bt.bank_party_iban, "NL91ABNA0417164300")
        self.assertEqual(bt.bank_party_account_number, "0417164300")

    def test_string_date_is_parsed(self):
        ref = self._ref("strdate")
        bt_name = self.creator.create_from_dict(
            {"date": "2026-01-15", "amount": 5.0, "reference_number": ref},
            bank_account=self.bank_account, company=COMPANY,
        )
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(getdate(bt.date), getdate("2026-01-15"))

    # ----------------------------------------------------------- guard branches
    def test_missing_date_returns_none(self):
        result = self.creator.create_from_dict(
            {"amount": 10.0, "reference_number": self._ref("nodate")},
            bank_account=self.bank_account, company=COMPANY,
        )
        self.assertIsNone(result)

    def test_missing_amount_returns_none(self):
        result = self.creator.create_from_dict(
            {"date": today(), "reference_number": self._ref("noamt")},
            bank_account=self.bank_account, company=COMPANY,
        )
        self.assertIsNone(result)

    def test_zero_amount_is_allowed_as_zero_deposit(self):
        """amount==0 is not None, so it is created (deposit=0, withdrawal=0)."""
        ref = self._ref("zero")
        bt_name = self.creator.create_from_dict(
            {"date": today(), "amount": 0, "reference_number": ref},
            bank_account=self.bank_account, company=COMPANY,
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(flt(bt.deposit), 0.0)
        self.assertEqual(flt(bt.withdrawal), 0.0)

    # ------------------------------------------------------------- idempotency
    def test_create_from_dict_idempotent(self):
        ref = self._ref("idem")
        payload = {"date": today(), "amount": 9.0, "reference_number": ref}
        first = self.creator.create_from_dict(payload, self.bank_account, COMPANY)
        second = self.creator.create_from_dict(payload, self.bank_account, COMPANY)
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)

    def test_create_low_level_idempotent(self):
        ref = self._ref("low")
        first = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=11.0, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="low-level create",
        )
        second = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=11.0, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="low-level create",
        )
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)

    # ---------------------------------------------- draft never gets resubmitted (#383)
    def test_create_from_dict_submits_existing_draft(self):
        ref = self._ref("draft-dict")
        draft = self._insert_draft_bank_transaction(ref, self.bank_account)

        payload = {"date": today(), "amount": 12.0, "reference_number": ref}
        result = self.creator.create_from_dict(payload, self.bank_account, COMPANY)

        self.assertEqual(result, draft.name)
        self.assertEqual(frappe.db.get_value("Bank Transaction", draft.name, "docstatus"), 1)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)

    def test_create_low_level_submits_existing_draft(self):
        ref = self._ref("draft-low")
        draft = self._insert_draft_bank_transaction(ref, self.bank_account)

        result = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=12.0, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="low-level create",
        )

        self.assertEqual(result, draft.name)
        self.assertEqual(frappe.db.get_value("Bank Transaction", draft.name, "docstatus"), 1)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)

    def test_create_from_dict_does_not_submit_draft_for_a_different_bank_account(self):
        """reference_number alone is not unique -- a draft that shares this
        reference but belongs to a DIFFERENT bank account must not be submitted
        by this caller. It is still reported as "already exists" (unchanged
        idempotency behaviour for the collision case), but left untouched."""
        other_gl_account = self._ensure_gl_account(name_suffix=" Other")
        other_bank_account = self._ensure_bank_account(other_gl_account, name_suffix=" Other")

        ref = self._ref("draft-other-account")
        draft = self._insert_draft_bank_transaction(ref, other_bank_account)

        payload = {"date": today(), "amount": 12.0, "reference_number": ref}
        result = self.creator.create_from_dict(payload, self.bank_account, COMPANY)

        self.assertEqual(result, draft.name)
        self.assertEqual(
            frappe.db.get_value("Bank Transaction", draft.name, "docstatus"),
            0,
            "a draft belonging to a different bank account must not be submitted",
        )


class TestBankTransactionCreatorSettlement(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def test_create_from_settlement_creates_deposit(self):
        from types import SimpleNamespace

        settlement_id = self._ref("stl")
        settlement = SimpleNamespace(id=settlement_id)
        bt_name = self.creator.create_from_settlement(
            settlement=settlement, bank_account=self.bank_account, company=COMPANY,
            settlement_amount=250.00, settlement_date=today(), currency="EUR",
            description="Mollie settlement payout",
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(flt(bt.deposit), 250.00)
        self.assertEqual(bt.reference_number, settlement_id)
        # Second identical settlement is idempotent.
        again = self.creator.create_from_settlement(
            settlement=settlement, bank_account=self.bank_account, company=COMPANY,
            settlement_amount=250.00, settlement_date=today(), currency="EUR",
            description="Mollie settlement payout",
        )
        self.assertEqual(again, bt_name)

    def test_create_from_settlement_submits_existing_draft(self):
        """A settlement draft left behind by a caller lacking submit permission
        must be resubmitted, not adopted as "already processed" forever (#383)."""
        from types import SimpleNamespace

        settlement_id = self._ref("stl-draft")
        draft = self._insert_draft_bank_transaction(settlement_id, self.bank_account, amount=250.00)

        settlement = SimpleNamespace(id=settlement_id)
        bt_name = self.creator.create_from_settlement(
            settlement=settlement, bank_account=self.bank_account, company=COMPANY,
            settlement_amount=250.00, settlement_date=today(), currency="EUR",
            description="Mollie settlement payout",
        )

        self.assertEqual(bt_name, draft.name)
        self.assertEqual(frappe.db.get_value("Bank Transaction", draft.name, "docstatus"), 1)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": settlement_id}), 1)


class TestBankTransactionCreatorMolliePayment(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def test_create_from_mollie_payment_submits_existing_draft(self):
        """A Mollie-payment draft left behind by a caller lacking submit
        permission must be resubmitted, not adopted as "already processed"
        forever (#383). The idempotency check runs before any Mollie-specific
        field extraction, so a bare object exposing only ``id`` reaches it --
        the same pattern used for create_from_settlement's SDK stand-in."""
        from types import SimpleNamespace

        payment_id = self._ref("tr-draft")
        draft = self._insert_draft_bank_transaction(payment_id, self.bank_account, amount=75.00)

        payment = SimpleNamespace(id=payment_id)
        bt_name = self.creator.create_from_mollie_payment(
            payment=payment, bank_account=self.bank_account, company=COMPANY,
        )

        self.assertEqual(bt_name, draft.name)
        self.assertEqual(frappe.db.get_value("Bank Transaction", draft.name, "docstatus"), 1)
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": payment_id}), 1)


class TestBankTransactionCreatorAlreadyProcessed(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def test_not_processed_when_no_document(self):
        result = self.creator.check_already_processed(self._ref("none"))
        self.assertFalse(result["already_processed"])
        self.assertIsNone(result["bank_transaction"])
        self.assertEqual(result["details"], "Not yet processed")

    def test_submitted_bank_transaction_is_already_processed(self):
        ref = self._ref("sub")
        bt_name = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=10.0, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="submitted bt",
        )
        self.assertTrue(bt_name)
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "docstatus"), 1)

        result = self.creator.check_already_processed(ref)
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["bank_transaction"], bt_name)
        self.assertEqual(result["document_type"], "Bank Transaction")
        self.assertEqual(result["docstatus"], 1)

    def test_cancelled_bank_transaction_allows_reprocessing(self):
        ref = self._ref("cancel")
        bt_name = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=10.0, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="to cancel",
        )
        bt = frappe.get_doc("Bank Transaction", bt_name)
        bt.cancel()
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "docstatus"), 2)

        result = self.creator.check_already_processed(ref)
        self.assertFalse(result["already_processed"], "Cancelled BT must allow reprocessing")

    def test_payment_entry_branch_detects_submitted_pe(self):
        ref = self._ref("pe")
        pe_name = self._make_internal_transfer_pe(ref)
        result = self.creator.check_already_processed(ref, check_payment_entry=True)
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["payment_entry"], pe_name)
        self.assertEqual(result["document_type"], "Payment Entry")

    def _make_internal_transfer_pe(self, reference_no):
        """A minimal submitted Payment Entry carrying reference_no, used only to
        exercise check_already_processed's Payment Entry branch."""
        paid_from = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 0}, "name"
        ) or self.gl_account
        paid_to = self.gl_account
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = COMPANY
        pe.posting_date = today()
        pe.paid_from = paid_from
        pe.paid_to = paid_to
        pe.paid_amount = 5.0
        pe.received_amount = 5.0
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.flags.ignore_permissions = True
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.track_test_record("Payment Entry", pe.name)
        return pe.name


class TestBankTransactionLinkPaymentEntry(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def test_link_payment_entry_reconciles_and_is_idempotent(self):
        amount = 30.0
        ref = self._ref("link")
        # A deposit Bank Transaction against the Mollie GL account.
        bt_name = self.creator.create(
            date=today(), bank_account=self.bank_account, company=COMPANY,
            deposit=amount, withdrawal=0.0, currency="EUR", reference_number=ref,
            description="bt to link",
        )
        self.assertTrue(bt_name)
        # A submitted Payment Entry depositing into the same GL account.
        pe_name = self._make_received_pe(amount)

        ok = self.creator.link_payment_entry(bt_name, pe_name)
        self.assertTrue(ok, "Linking BT to PE should succeed")

        bt = frappe.get_doc("Bank Transaction", bt_name)
        links = [pe for pe in bt.payment_entries if pe.payment_entry == pe_name]
        self.assertTrue(links, "BT must reference the linked PE")
        self.assertEqual(links[0].payment_document, "Payment Entry")

        # Idempotent: a second link call short-circuits and stays True.
        ok2 = self.creator.link_payment_entry(bt_name, pe_name)
        self.assertTrue(ok2)
        bt.reload()
        again = [pe for pe in bt.payment_entries if pe.payment_entry == pe_name]
        self.assertEqual(len(again), 1, "PE link must not be duplicated")

    def _make_received_pe(self, amount):
        """Submitted 'Receive' Payment Entry crediting a customer into the Mollie
        GL account, matched against the deposit Bank Transaction."""
        customer = frappe.get_value("Customer", {}, "name")
        receivable = frappe.get_value(
            "Account",
            {"company": COMPANY, "account_type": "Receivable", "is_group": 0},
            "name",
        )
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = COMPANY
        pe.posting_date = today()
        pe.party_type = "Customer"
        pe.party = customer
        pe.paid_to = self.gl_account
        pe.paid_from = receivable
        pe.paid_amount = amount
        pe.received_amount = amount
        pe.reference_no = self._ref("pe-ref")
        pe.reference_date = today()
        pe.flags.ignore_permissions = True
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.track_test_record("Payment Entry", pe.name)
        return pe.name
