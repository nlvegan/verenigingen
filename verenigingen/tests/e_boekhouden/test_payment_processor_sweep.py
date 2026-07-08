"""
Integration coverage sweep for the BANK-TRANSACTION / MONEY-TRANSFER surface of
``e_boekhouden/utils/processors/payment_processor.py`` (:class:`PaymentProcessor`).

The sibling ``test_payment_processor_coverage.py`` already covers the pure /
cheap-DB decision functions (``can_process``, ``get_payment_type``,
``_is_payment_gateway_adjustment``, ``_adjust_payment_gateway_amount``,
``_extract_bank_name_from_account``). This module deliberately does NOT duplicate
those; it exercises the heavier, document-producing helpers that the coverage
file explicitly left OUT OF SCOPE:

* ``_process_money_transfer``                 -- end-to-end Type 5/6 -> real,
  balanced, submitted Journal Entry + real Bank Transaction.
* ``_create_bank_transaction_for_journal_entry`` -- real Bank Transaction created
  + linked; zero-amount skip; existing-BT idempotency; bank-internal party path.
* ``_link_bank_transaction_to_journal_entry`` -- reconciliation + idempotency.
* ``_link_bank_transaction_to_payment``       -- reconciliation + idempotency.
* ``_update_bank_transaction_party``          -- party backfill on an existing BT.

Everything is REAL: a dedicated EUR company with its own chart of accounts, a
real Bank + Bank Account linked to the bank GL account, real
``E-Boekhouden Ledger Mapping`` rows, and the real ``bank_transaction_creator``
service. Assertions check the concrete documents produced (account on each line,
debit/credit signs, balance, Bank Transaction amount sign / reconciliation
status / linkage) so a regression in the wiring fails the test.

Run with::

    cd /home/frappeuser/frappe-bench && bench --site veg11.veganisme.org \\
        run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_processor_sweep
"""

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ABBR = "EBPS"
COMPANY = "TEST-EB-PayProc-Sweep-Company"

# Globally-unique ledger ids (7-digit ``73xxxxx`` range reserved for this module);
# the "E-Boekhouden Ledger Mapping" doctype has no company column, so low codes
# shared with other modules would cross-resolve to the wrong company's accounts.
BANK_LEDGER = "7300001"
INCOME_LEDGER = "7300008"
EXPENSE_LEDGER = "7300004"


class _PayProcBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, Bank + Bank Account, ledger mappings."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_bank_account()
        cls._ensure_ledger_mappings()
        cls._ensure_fiscal_year()
        frappe.db.commit()

    # ---- bootstrap ----

    @classmethod
    def _ensure_company(cls):
        if frappe.db.exists("Company", COMPANY):
            cls.company = COMPANY
            return
        c = frappe.new_doc("Company")
        c.company_name = COMPANY
        c.abbr = ABBR
        c.default_currency = "EUR"
        c.country = "Netherlands"
        c.insert(ignore_permissions=True)
        cls.company = COMPANY

    @classmethod
    def _make_root(cls, root_type):
        existing = frappe.db.get_value(
            "Account", {"company": COMPANY, "root_type": root_type, "is_group": 1}, "name"
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"EBPS {root_type} Root"
        r.company = COMPANY
        r.root_type = root_type
        r.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        r.is_group = 1
        r.insert(ignore_permissions=True)
        return r.name

    @classmethod
    def _make_account(cls, account_name, account_type, root_type):
        expected = f"{account_name} - {ABBR}"
        if frappe.db.exists("Account", expected):
            return expected
        a = frappe.new_doc("Account")
        a.account_name = account_name
        a.company = COMPANY
        a.account_type = account_type
        a.root_type = root_type
        a.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        a.is_group = 0
        a.parent_account = cls._make_root(root_type)
        a.insert(ignore_permissions=True)
        return a.name

    @classmethod
    def _ensure_accounts(cls):
        cls.bank = cls._make_account("EBPS Bank", "Bank", "Asset")
        cls.bank2 = cls._make_account("EBPS Bank Two", "Bank", "Asset")
        cls.income = cls._make_account("EBPS Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBPS Expense", "Expense Account", "Expense")

    @classmethod
    def _ensure_cost_center(cls):
        cls.cost_center = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 0}, "name")
        if cls.cost_center:
            return
        root_cc = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1}, "name")
        if not root_cc:
            rc = frappe.new_doc("Cost Center")
            rc.cost_center_name = COMPANY
            rc.company = COMPANY
            rc.is_group = 1
            rc.insert(ignore_permissions=True)
            root_cc = rc.name
        leaf = frappe.new_doc("Cost Center")
        leaf.cost_center_name = "EBPS Main"
        leaf.company = COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root_cc
        leaf.insert(ignore_permissions=True)
        cls.cost_center = leaf.name

    @classmethod
    def _ensure_bank_account(cls):
        bank_name = "EBPS Test Bank"
        if not frappe.db.exists("Bank", bank_name):
            b = frappe.new_doc("Bank")
            b.bank_name = bank_name
            b.insert(ignore_permissions=True)
        cls.bank_doc = bank_name

        # Bank Account linked to the bank GL account; convert_gl_account_to_bank_account
        # resolves this from {account, company}.
        existing = frappe.db.get_value("Bank Account", {"account": cls.bank, "company": COMPANY}, "name")
        if existing:
            cls.bank_account = existing
            return
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "EBPS Main"
        ba.bank = bank_name
        ba.account = cls.bank
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        cls.bank_account = ba.name

    @classmethod
    def _make_ledger_map(cls, ledger_id, account, name):
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "name")
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", account)
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = str(ledger_id)
        m.ledger_name = name
        m.erpnext_account = account
        m.insert(ignore_permissions=True)

    @classmethod
    def _ensure_ledger_mappings(cls):
        cls._make_ledger_map(BANK_LEDGER, cls.bank, "EBPS Bank")
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBPS Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBPS Expense")

    @classmethod
    def _ensure_fiscal_year(cls):
        year = getdate().year
        fy_name = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()]},
            "name",
            order_by="creation desc",
        )
        if not fy_name:
            fy_name = f"EBPS-FY-{year}"
            if not frappe.db.exists("Fiscal Year", fy_name):
                fy = frappe.new_doc("Fiscal Year")
                fy.year = fy_name
                fy.year_start_date = f"{year}-01-01"
                fy.year_end_date = f"{year}-12-31"
                fy.insert(ignore_permissions=True)
        fy = frappe.get_doc("Fiscal Year", fy_name)
        if not any(c.company == COMPANY for c in fy.companies):
            fy.append("companies", {"company": COMPANY})
            fy.save(ignore_permissions=True)

    # ---- helpers ----

    def _processor(self):
        return PaymentProcessor(self.company, cost_center=self.cost_center)

    @staticmethod
    def _balanced(je):
        return (
            sum(flt(a.debit_in_account_currency) for a in je.accounts),
            sum(flt(a.credit_in_account_currency) for a in je.accounts),
        )

    def _money_mutation(self, mtype, amount, row_ledger, mut_id, description="Sweep transfer", rows=None):
        m = {
            "id": mut_id,
            "type": mtype,
            "amount": amount,
            "ledgerId": BANK_LEDGER,
            "date": nowdate(),
            "description": description,
        }
        if rows is None:
            rows = [{"amount": abs(amount), "ledgerId": row_ledger}]
        m["rows"] = rows
        return m


# ---------------------------------------------------------------------------
# _process_money_transfer  (end-to-end, real JE + real Bank Transaction)
# ---------------------------------------------------------------------------
class TestProcessMoneyTransfer(_PayProcBase):
    def _bt_for(self, mutation_id):
        return frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": f"EB-{mutation_id}"},
            ["name", "deposit", "withdrawal", "status", "allocated_amount"],
            as_dict=True,
        )

    def test_type5_money_received_debits_bank_credits_income(self):
        """Type 5 (Money Received) -> bank DEBITED, income CREDITED, balanced & submitted."""
        p = self._processor()
        mut = self._money_mutation(5, 120.00, INCOME_LEDGER, 7310001)
        je = p.process(mut)

        self.assertIsNotNone(je, f"JE was None. debug={p.get_debug_info()}")
        self.assertEqual(je.doctype, "Journal Entry")
        self.assertEqual(je.docstatus, 1, "money-transfer JE should be submitted")
        self.assertEqual(je.eboekhouden_mutation_nr, "7310001")

        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2)
        self.assertAlmostEqual(td, 120.00, places=2)

        bank_line = next(a for a in je.accounts if a.account == self.bank)
        income_line = next(a for a in je.accounts if a.account == self.income)
        self.assertEqual(flt(bank_line.debit_in_account_currency), 120.00)
        self.assertEqual(flt(bank_line.credit_in_account_currency), 0.0)
        self.assertEqual(flt(income_line.credit_in_account_currency), 120.00)

        # Real Bank Transaction created (deposit, positive) and reconciled to the JE.
        bt = self._bt_for(7310001)
        self.assertIsNotNone(bt, "Bank Transaction must be created for money received")
        self.assertEqual(flt(bt.deposit), 120.00)
        self.assertEqual(flt(bt.withdrawal), 0.0)
        self.assertEqual(bt.status, "Reconciled")
        self.assertEqual(flt(bt.allocated_amount), 120.00)
        self.assertTrue(
            frappe.db.exists(
                "Bank Transaction Payments",
                {"parent": bt.name, "payment_entry": je.name, "payment_document": "Journal Entry"},
            ),
            "Bank Transaction must be linked to the Journal Entry",
        )

    def test_type6_money_paid_credits_bank_debits_expense(self):
        """Type 6 (Money Paid) -> bank CREDITED, expense DEBITED; BT is a withdrawal."""
        p = self._processor()
        mut = self._money_mutation(6, 75.00, EXPENSE_LEDGER, 7310002)
        je = p.process(mut)

        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        self.assertEqual(je.docstatus, 1)
        bank_line = next(a for a in je.accounts if a.account == self.bank)
        expense_line = next(a for a in je.accounts if a.account == self.expense)
        self.assertEqual(flt(bank_line.credit_in_account_currency), 75.00)
        self.assertEqual(flt(bank_line.debit_in_account_currency), 0.0)
        self.assertEqual(flt(expense_line.debit_in_account_currency), 75.00)

        bt = self._bt_for(7310002)
        self.assertIsNotNone(bt)
        # Money out -> negative signed amount -> withdrawal.
        self.assertEqual(flt(bt.withdrawal), 75.00)
        self.assertEqual(flt(bt.deposit), 0.0)
        self.assertEqual(bt.status, "Reconciled")

    def test_amount_zero_calculated_from_rows(self):
        """Main amount 0 with rows -> amount summed from rows; JE still balances."""
        p = self._processor()
        mut = self._money_mutation(
            5, 0, INCOME_LEDGER, 7310003, rows=[{"amount": 90.00, "ledgerId": INCOME_LEDGER}]
        )
        je = p.process(mut)
        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        self.assertEqual(je.docstatus, 1)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, 90.00, places=2)
        self.assertAlmostEqual(td, tc, places=2)  # JE must balance
        self.assertTrue(any("Main amount was 0" in m for m in p.get_debug_info()))

    def test_multi_row_creates_one_line_per_row(self):
        """Multi-row Type 5 -> one bank leg + one income leg per row."""
        p = self._processor()
        rows = [
            {"amount": 40.00, "ledgerId": INCOME_LEDGER},
            {"amount": 60.00, "ledgerId": INCOME_LEDGER},
        ]
        mut = self._money_mutation(5, 100.00, INCOME_LEDGER, 7310004, rows=rows)
        je = p.process(mut)
        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        # 1 bank + 2 income lines.
        self.assertEqual(len(je.accounts), 3)
        bank_line = next(a for a in je.accounts if a.account == self.bank)
        self.assertEqual(flt(bank_line.debit_in_account_currency), 100.00)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2)

    def test_bank_internal_description_no_party_on_bank_transaction(self):
        """A bank-internal (BANKKOSTEN) Type 6 still books; BT gets no party (bank not a Supplier)."""
        p = self._processor()
        mut = self._money_mutation(6, 12.50, EXPENSE_LEDGER, 7310006, description="BANKKOSTEN")
        je = p.process(mut)
        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        self.assertEqual(je.docstatus, 1)
        bt = frappe.db.get_value(
            "Bank Transaction", {"reference_number": "EB-7310006"}, ["name", "party"], as_dict=True
        )
        self.assertIsNotNone(bt)
        # Bank Account name "EBPS Main" has no ' - ' separator -> no bank name -> no party.
        self.assertFalse(bt.party, "bank-internal txn should not invent a party here")

    def test_unmapped_ledger_raises_validation_error(self):
        """An unmapped, non-auto-creatable bank ledger fails fast with a clear message."""
        p = self._processor()
        mut = {
            "id": 7310007,
            "type": 5,
            "amount": 10.0,
            "ledgerId": "739999999",  # no mapping, auto-create has no API in test env
            "date": nowdate(),
            "description": "unmapped",
            "rows": [{"amount": 10.0, "ledgerId": INCOME_LEDGER}],
        }
        with self.assertRaises(Exception) as ctx:
            p.process(mut)
        self.assertIn("No ERPNext account mapped", str(ctx.exception))


# ---------------------------------------------------------------------------
# _create_bank_transaction_for_journal_entry  (direct, edge branches)
# ---------------------------------------------------------------------------
class TestCreateBankTransactionForJE(_PayProcBase):
    def _make_je_with_legs(self, mut_id, amount=33.00):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = str(mut_id)
        je.cheque_no = f"EB-{mut_id}"
        je.cheque_date = nowdate()
        je.append(
            "accounts",
            {
                "account": self.bank,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
                "cost_center": self.cost_center,
            },
        )
        je.append(
            "accounts",
            {
                "account": self.income,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
                "cost_center": self.cost_center,
            },
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def test_zero_amount_skips_creation(self):
        """A JE whose bank leg nets to zero produces no Bank Transaction."""
        p = self._processor()
        je = frappe._dict(
            name="FAKE-JE-ZERO",
            posting_date=nowdate(),
            accounts=[
                frappe._dict(account=self.bank, debit_in_account_currency=0, credit_in_account_currency=0)
            ],
        )
        result = p._create_bank_transaction_for_journal_entry(
            {"id": 7320001, "type": 5, "description": "zero"}, je, self.bank, self.bank_account
        )
        self.assertIsNone(result)
        self.assertTrue(any("zero/near-zero amount" in m for m in p.get_debug_info()))

    def test_creates_and_links_bank_transaction(self):
        """Direct call against a real JE creates a reconciled Bank Transaction (deposit)."""
        p = self._processor()
        je = self._make_je_with_legs(7320002, amount=44.00)
        bt_name = p._create_bank_transaction_for_journal_entry(
            {"id": 7320002, "type": 5, "description": "direct create"},
            je,
            self.bank,
            self.bank_account,
        )
        self.assertTrue(bt_name)
        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(flt(bt.deposit), 44.00)
        self.assertEqual(bt.status, "Reconciled")
        self.assertTrue(any(p.payment_entry == je.name for p in bt.payment_entries))

    def test_existing_bank_transaction_is_reused_and_linked(self):
        """When a BT already exists for EB-<id>, it is reused (not duplicated) and linked to the JE."""
        p = self._processor()
        je = self._make_je_with_legs(7320003, amount=20.00)

        # Pre-create an unreconciled Bank Transaction with the same reference.
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        creator = get_bank_transaction_creator()
        pre_bt = creator.create_from_dict(
            transaction_data={
                "date": nowdate(),
                "amount": 20.00,
                "currency": "EUR",
                "description": "pre-existing",
                "reference_number": "EB-7320003",
            },
            bank_account=self.bank_account,
            company=self.company,
            source_type="Coverage Pre-Seed",
        )
        self.assertTrue(pre_bt)

        result = p._create_bank_transaction_for_journal_entry(
            {"id": 7320003, "type": 5, "description": "reuse"}, je, self.bank, self.bank_account
        )
        self.assertEqual(result, pre_bt, "should reuse the existing Bank Transaction")
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": "EB-7320003"}), 1)
        bt = frappe.get_doc("Bank Transaction", pre_bt)
        self.assertEqual(bt.status, "Reconciled")


# ---------------------------------------------------------------------------
# _link_bank_transaction_to_journal_entry
# ---------------------------------------------------------------------------
class TestLinkBankTransactionToJE(_PayProcBase):
    def _make_draft_bt(self, ref, amount=50.0):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = nowdate()
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.deposit = amount
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = ref
        bt.description = "link test"
        bt.status = "Unreconciled"
        bt.unallocated_amount = amount
        bt.allocated_amount = 0
        bt.insert(ignore_permissions=True)
        return bt

    def _make_simple_je(self, mut_id, amount=50.0):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        je.eboekhouden_mutation_nr = str(mut_id)
        je.cheque_no = f"EB-{mut_id}"
        je.cheque_date = nowdate()
        je.append(
            "accounts",
            {"account": self.bank, "debit_in_account_currency": amount, "cost_center": self.cost_center},
        )
        je.append(
            "accounts",
            {"account": self.income, "credit_in_account_currency": amount, "cost_center": self.cost_center},
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def test_links_and_reconciles(self):
        p = self._processor()
        bt = self._make_draft_bt("EB-LNK-7330001", 50.0)
        je = self._make_simple_je(7330001, 50.0)
        p._link_bank_transaction_to_journal_entry(bt.name, je.name, 50.0)

        bt.reload()
        self.assertEqual(bt.status, "Reconciled")
        self.assertEqual(flt(bt.allocated_amount), 50.0)
        self.assertEqual(flt(bt.unallocated_amount), 0.0)
        self.assertEqual(len(bt.payment_entries), 1)
        self.assertEqual(bt.payment_entries[0].payment_entry, je.name)
        self.assertEqual(bt.payment_entries[0].payment_document, "Journal Entry")

    def test_idempotent_when_already_linked(self):
        p = self._processor()
        bt = self._make_draft_bt("EB-LNK-7330002", 30.0)
        je = self._make_simple_je(7330002, 30.0)
        p._link_bank_transaction_to_journal_entry(bt.name, je.name, 30.0)
        # Second call must be a no-op, not a duplicate row or an error.
        p._link_bank_transaction_to_journal_entry(bt.name, je.name, 30.0)
        bt.reload()
        self.assertEqual(len(bt.payment_entries), 1)
        self.assertTrue(any("already linked to JE" in m for m in p.get_debug_info()))


# ---------------------------------------------------------------------------
# _link_bank_transaction_to_payment  (NOTE: dead code -- no production caller;
# tested to pin documented behaviour and guard against accidental reuse)
#
# KEEP-WITH-NOTE (2026-07-08 false-confidence remediation, report 25c): confirmed
# still dead (re-grepped callers) during the remediation pass. Left in place as a
# dead-code tripwire rather than deleted -- the methods do assert real link/
# reconcile + idempotency effects, so if this path is ever wired back up (a real
# caller added), these tests already cover it correctly.
# ---------------------------------------------------------------------------
class TestLinkBankTransactionToPayment(_PayProcBase):
    def _make_draft_bt(self, ref, amount=25.0):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = nowdate()
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.deposit = amount
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = ref
        bt.description = "pe link test"
        bt.status = "Unreconciled"
        bt.unallocated_amount = amount
        bt.allocated_amount = 0
        bt.insert(ignore_permissions=True)
        return bt

    def _make_internal_transfer_pe(self, amount=25.0):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = self.company
        pe.posting_date = nowdate()
        pe.paid_from = self.bank
        pe.paid_to = self.bank2
        pe.paid_amount = amount
        pe.received_amount = amount
        pe.source_exchange_rate = 1
        pe.target_exchange_rate = 1
        # Bank-to-bank transfers require a transaction reference.
        pe.reference_no = "EBPS-XFER"
        pe.reference_date = nowdate()
        pe.insert(ignore_permissions=True)
        return pe

    def test_links_payment_entry_and_reconciles(self):
        p = self._processor()
        bt = self._make_draft_bt("EB-PE-7340001", 25.0)
        pe = self._make_internal_transfer_pe(25.0)
        p._link_bank_transaction_to_payment(bt.name, pe.name)

        bt.reload()
        self.assertEqual(bt.status, "Reconciled")
        self.assertEqual(flt(bt.allocated_amount), 25.0)
        self.assertEqual(len(bt.payment_entries), 1)
        self.assertEqual(bt.payment_entries[0].payment_entry, pe.name)
        self.assertEqual(bt.payment_entries[0].payment_document, "Payment Entry")

    def test_idempotent_when_already_linked(self):
        p = self._processor()
        bt = self._make_draft_bt("EB-PE-7340002", 15.0)
        pe = self._make_internal_transfer_pe(15.0)
        p._link_bank_transaction_to_payment(bt.name, pe.name)
        p._link_bank_transaction_to_payment(bt.name, pe.name)
        bt.reload()
        self.assertEqual(len(bt.payment_entries), 1)
        self.assertTrue(any("already linked" in m for m in p.get_debug_info()))


# ---------------------------------------------------------------------------
# _update_bank_transaction_party
# ---------------------------------------------------------------------------
class TestUpdateBankTransactionParty(_PayProcBase):
    def setUp(self):
        super().setUp()
        self._saved_auto = frappe.db.get_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions"
        )
        frappe.db.set_single_value("E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", 0)

    def tearDown(self):
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", self._saved_auto
        )
        super().tearDown()

    def _make_draft_bt(self, ref):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = nowdate()
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.deposit = 10.0
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = ref
        bt.description = "party update test"
        bt.status = "Unreconciled"
        bt.unallocated_amount = 10.0
        bt.allocated_amount = 0
        bt.insert(ignore_permissions=True)
        return bt

    def _make_supplier(self, name):
        if frappe.db.exists("Supplier", name):
            return name
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = name
        sup.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name")
        sup.insert(ignore_permissions=True)
        return sup.name

    def test_backfills_matching_supplier_when_auto_create_disabled(self):
        """With auto-create off, an existing matching Supplier is written onto the BT."""
        supplier = self._make_supplier("EBPS Party Update Supplier")
        bt = self._make_draft_bt("EB-PARTY-7350001")
        p = self._processor()
        p._update_bank_transaction_party(bt.name, {"party_type": "Supplier", "party_name": supplier})
        bt.reload()
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, supplier)

    def test_no_party_name_is_noop(self):
        """Missing party_name returns early without touching the Bank Transaction."""
        bt = self._make_draft_bt("EB-PARTY-7350002")
        p = self._processor()
        p._update_bank_transaction_party(bt.name, {"party_type": "Supplier", "party_name": ""})
        bt.reload()
        self.assertFalse(bt.party)

    def test_unmatched_party_leaves_bt_without_party(self):
        """A party name with no matching Supplier (auto-create off) leaves the BT party empty."""
        bt = self._make_draft_bt("EB-PARTY-7350003")
        p = self._processor()
        p._update_bank_transaction_party(
            bt.name, {"party_type": "Supplier", "party_name": "ZZZ No Such Supplier 9931"}
        )
        bt.reload()
        self.assertFalse(bt.party)


if __name__ == "__main__":
    import unittest

    unittest.main()
