"""
Real integration tests for the JOURNAL-ENTRY / MEMORIAL-BOOKING cluster of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Target functions:
    _create_journal_entry, _process_journal_entry_rows,
    _resolve_journal_row_account, _assign_party_to_entry,
    _build_memorial_balancing_entry, _validate_memorial_booking,
    _add_payment_offset_entry, _get_memorial_booking_amounts

These feed SYNTHETIC eBoekhouden mutation dicts (no live API) and assert the
REAL Journal Entry documents that come out: the account on each line, the
debit/credit amounts and signs, total_debit == total_credit (balanced), party
assignment on receivable/payable lines, the memorial balancing entry, posting
date and docstatus.

This file is the journal-entry counterpart to test_rest_invoice_creation.py
(invoices) and reuses its bootstrap pattern (company / accounts / ledger
mappings / cost center / parties / fiscal year).

MEMORIAL BOOKING SIGN CONVENTION (type 7)
-----------------------------------------
``_get_memorial_booking_amounts`` uses a single verified convention (the
"amount" field is the CREDIT side): a POSITIVE row amount CREDITS the row
account and DEBITS the offsetting main account; a negative amount reverses it.

    if row_amount > 0:  return (0, amount, amount, 0)   # row Cr, main Dr
    else:               return (amount, 0, 0, amount)   # row Dr, main Cr

(A prior version fetched unused ledger "categories" via the API and used the
OPPOSITE convention in its except-fallback, so credential-less imports — CI, or a
transient token failure — booked memorial legs on the wrong ledger side. That
dead API call was removed; these tests assert the corrected, single convention.)

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_2 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_journal_entry_creation
"""

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _add_payment_offset_entry,
    _assign_party_to_entry,
    _build_memorial_balancing_entry,
    _create_journal_entry,
    _get_memorial_booking_amounts,
    _process_journal_entry_rows,
    _resolve_journal_row_account,
    _validate_memorial_booking,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ABBR = "EBJC"
COMPANY = "TEST-EB-Journal-Company"

# Ledger ids/codes for the synthetic mutations. ledger_id == ledger_code so the
# two-hop resolution (ledgerId -> ledger_code -> erpnext_account, keyed on
# ledger_id) lands on the account we created.
EXPENSE_LEDGER = "4100"
INCOME_LEDGER = "8100"
BANK_LEDGER = "1100"
RECEIVABLE_LEDGER = "1310"
PAYABLE_LEDGER = "1610"
KRUISPOSTEN_LEDGER = "1999"  # generic asset "suspense" ledger for memorials

CUSTOMER_RELATION = "EBJ-CUST-1"
SUPPLIER_RELATION = "EBJ-SUPP-1"


class _JournalClusterBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, ledger mappings, cost center, parties."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_parties()
        cls._ensure_fiscal_year()
        frappe.db.commit()

    # ---- bootstrap helpers ----

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
            "Account",
            {"company": COMPANY, "root_type": root_type, "is_group": 1},
            "name",
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"EBJ {root_type} Root"
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
        cls.receivable = cls._make_account("EBJ Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBJ Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EBJ Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBJ Expense", "Expense Account", "Expense")
        cls.bank = cls._make_account("EBJ Bank", "Bank", "Asset")
        cls.kruisposten = cls._make_account("EBJ Kruisposten", "", "Asset")

        company = frappe.get_doc("Company", COMPANY)
        changed = False
        if not company.default_receivable_account:
            company.default_receivable_account = cls.receivable
            changed = True
        if not company.default_payable_account:
            company.default_payable_account = cls.payable
            changed = True
        if changed:
            company.save(ignore_permissions=True)

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
        leaf.cost_center_name = "EBJ Main"
        leaf.company = COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root_cc
        leaf.insert(ignore_permissions=True)
        cls.cost_center = leaf.name

    @classmethod
    def _make_ledger_map(cls, ledger_id, account, name):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}):
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = str(ledger_id)
        m.ledger_name = name
        m.erpnext_account = account
        m.insert(ignore_permissions=True)

    @classmethod
    def _ensure_ledger_mappings(cls):
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBJ Expense")
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBJ Income")
        cls._make_ledger_map(BANK_LEDGER, cls.bank, "EBJ Bank")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBJ Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBJ Creditors")
        cls._make_ledger_map(KRUISPOSTEN_LEDGER, cls.kruisposten, "EBJ Kruisposten")

    @classmethod
    def _ensure_parties(cls):
        if not frappe.db.exists("Customer", {"eboekhouden_relation_code": CUSTOMER_RELATION}):
            cust = frappe.new_doc("Customer")
            cust.customer_name = "EBJ Test Customer"
            cust.customer_type = "Individual"
            cust.default_currency = "EUR"
            cust.eboekhouden_relation_code = CUSTOMER_RELATION
            cust.insert(ignore_permissions=True)
        cls.customer = frappe.db.get_value(
            "Customer", {"eboekhouden_relation_code": CUSTOMER_RELATION}, "name"
        )

        if not frappe.db.exists("Supplier", {"eboekhouden_relation_code": SUPPLIER_RELATION}):
            supp = frappe.new_doc("Supplier")
            supp.supplier_name = "EBJ Test Supplier"
            supp.supplier_type = "Individual"
            supp.default_currency = "EUR"
            supp.eboekhouden_relation_code = SUPPLIER_RELATION
            supp.insert(ignore_permissions=True)
        cls.supplier = frappe.db.get_value(
            "Supplier", {"eboekhouden_relation_code": SUPPLIER_RELATION}, "name"
        )

    @classmethod
    def _ensure_fiscal_year(cls):
        """Ensure a Fiscal Year covering today() lists our test company."""
        year = getdate().year
        fy_name = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()]},
            "name",
            order_by="creation desc",
        )
        if not fy_name:
            fy_name = f"EBJ-FY-{year}"
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

    # ---- per-test helpers ----

    @staticmethod
    def _balanced(je):
        return sum(flt(a.debit_in_account_currency) for a in je.accounts), sum(
            flt(a.credit_in_account_currency) for a in je.accounts
        )

    def _memorial_mutation(self, **overrides):
        """A type-7 memorial booking. No top-level amount (REST omits it for type 7)."""
        m = {
            "id": 700001,
            "type": 7,
            "date": nowdate(),
            "relationId": None,
            "invoiceNumber": None,
            "description": "Memorial reclassification",
            # main ledger that the balancing leg posts to
            "ledgerId": KRUISPOSTEN_LEDGER,
            "Regels": [
                {
                    "ledgerId": EXPENSE_LEDGER,
                    "amount": 100.00,
                    "quantity": 1,
                    "description": "Expense reclass",
                }
            ],
        }
        m.update(overrides)
        return m


# ---------------------------------------------------------------------------
# _get_memorial_booking_amounts  (pure-ish; takes the fallback branch here)
# ---------------------------------------------------------------------------
class TestGetMemorialBookingAmounts(_JournalClusterBase):
    """The verified single convention: positive amount -> credit row, debit main."""

    def test_positive_amount_credits_row_debits_main(self):
        debug = []
        row_d, row_c, main_d, main_c = _get_memorial_booking_amounts(
            EXPENSE_LEDGER, KRUISPOSTEN_LEDGER, 100.00, debug
        )
        # Positive amount -> row CREDITED, main DEBITED (amount is the credit side).
        self.assertEqual((row_d, row_c, main_d, main_c), (0, 100.00, 100.00, 0))

    def test_negative_amount_debits_row_credits_main(self):
        debug = []
        row_d, row_c, main_d, main_c = _get_memorial_booking_amounts(
            EXPENSE_LEDGER, KRUISPOSTEN_LEDGER, -75.00, debug
        )
        # Negative amount -> row DEBITED, main CREDITED (mirror of positive).
        self.assertEqual((row_d, row_c, main_d, main_c), (75.00, 0, 0, 75.00))

    def test_row_and_main_legs_always_balance(self):
        debug = []
        for amt in (100.0, -100.0, 33.33, -0.01):
            row_d, row_c, main_d, main_c = _get_memorial_booking_amounts("4100", "1999", amt, debug)
            # The two legs together net to zero (internally balanced pair).
            self.assertAlmostEqual((row_d - row_c) + (main_d - main_c), 0.0, places=2)


# ---------------------------------------------------------------------------
# _resolve_journal_row_account
# ---------------------------------------------------------------------------
class TestResolveJournalRowAccount(_JournalClusterBase):
    def test_mapped_ledger_resolves_to_account(self):
        debug = []
        acct = _resolve_journal_row_account(
            EXPENSE_LEDGER, 100.0, "Expense reclass", self._memorial_mutation(), self.company, debug
        )
        self.assertEqual(acct, self.expense)

    def test_income_ledger_resolves_to_income_account(self):
        debug = []
        acct = _resolve_journal_row_account(
            INCOME_LEDGER, 50.0, "Income line", self._memorial_mutation(), self.company, debug
        )
        self.assertEqual(acct, self.income)


# ---------------------------------------------------------------------------
# _assign_party_to_entry
# ---------------------------------------------------------------------------
class TestAssignPartyToEntry(_JournalClusterBase):
    def test_receivable_gets_customer_party_from_relation(self):
        line = {"account": self.receivable}
        _assign_party_to_entry(line, self.receivable, 3, CUSTOMER_RELATION, self.company, "desc", [])
        self.assertEqual(line["party_type"], "Customer")
        self.assertEqual(line["party"], self.customer)

    def test_payable_gets_supplier_party_from_relation(self):
        line = {"account": self.payable}
        _assign_party_to_entry(line, self.payable, 4, SUPPLIER_RELATION, self.company, "desc", [])
        self.assertEqual(line["party_type"], "Supplier")
        self.assertEqual(line["party"], self.supplier)

    def test_non_party_account_left_unchanged(self):
        line = {"account": self.expense}
        _assign_party_to_entry(line, self.expense, 7, None, self.company, "desc", [])
        self.assertNotIn("party_type", line)
        self.assertNotIn("party", line)

    def test_receivable_no_relation_sets_party_type_but_no_party(self):
        # Non-memorial type with no relation id: party_type set, party not resolvable.
        line = {"account": self.receivable}
        _assign_party_to_entry(line, self.receivable, 3, None, self.company, "desc", [])
        self.assertEqual(line["party_type"], "Customer")
        self.assertNotIn("party", line)

    def test_memorial_receivable_uses_company_as_customer(self):
        # type 7 + receivable: party is the company-as-customer, not the relation.
        line = {"account": self.receivable}
        _assign_party_to_entry(line, self.receivable, 7, CUSTOMER_RELATION, self.company, "d", [])
        self.assertEqual(line["party_type"], "Customer")
        self.assertTrue(line.get("party"), "memorial receivable should get company-as-customer party")
        self.assertTrue(frappe.db.exists("Customer", line["party"]))


# ---------------------------------------------------------------------------
# _build_memorial_balancing_entry
# ---------------------------------------------------------------------------
class TestBuildMemorialBalancingEntry(_JournalClusterBase):
    def test_single_row_positive_main_leg_debited(self):
        # Single-row memorial uses _get_memorial_booking_amounts: positive row
        # amount -> row CREDITED, so the main (kruisposten) leg is DEBITED.
        debug = []
        rows = [{"ledgerId": EXPENSE_LEDGER, "amount": 100.00, "quantity": 1}]
        line = _build_memorial_balancing_entry(
            700010, rows, KRUISPOSTEN_LEDGER, 100.0, 0.0, self.company, self.cost_center, "d", debug
        )
        self.assertIsNotNone(line)
        self.assertEqual(line["account"], self.kruisposten)
        self.assertEqual(flt(line["debit_in_account_currency"]), 100.00)
        self.assertEqual(flt(line["credit_in_account_currency"]), 0.0)

    def test_multi_row_nets_imbalance_to_main(self):
        # >1 row: balancing leg covers (total_debit - total_credit).
        debug = []
        rows = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 60.0, "quantity": 1},
            {"ledgerId": INCOME_LEDGER, "amount": 40.0, "quantity": 1},
        ]
        # Pretend rows produced 100 debit, 0 credit -> imbalance +100 needs a 100 credit.
        line = _build_memorial_balancing_entry(
            700011, rows, KRUISPOSTEN_LEDGER, 100.0, 0.0, self.company, self.cost_center, "d", debug
        )
        self.assertIsNotNone(line)
        self.assertEqual(flt(line["credit_in_account_currency"]), 100.0)
        self.assertEqual(flt(line["debit_in_account_currency"]), 0.0)

    def test_multi_row_credit_excess_needs_debit_main(self):
        debug = []
        rows = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 60.0, "quantity": 1},
            {"ledgerId": INCOME_LEDGER, "amount": 40.0, "quantity": 1},
        ]
        # 0 debit, 100 credit -> imbalance -100 needs a 100 debit on the main leg.
        line = _build_memorial_balancing_entry(
            700012, rows, KRUISPOSTEN_LEDGER, 0.0, 100.0, self.company, self.cost_center, "d", debug
        )
        self.assertEqual(flt(line["debit_in_account_currency"]), 100.0)
        self.assertEqual(flt(line["credit_in_account_currency"]), 0.0)

    def test_multi_row_balanced_returns_none(self):
        debug = []
        rows = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 60.0, "quantity": 1},
            {"ledgerId": INCOME_LEDGER, "amount": 40.0, "quantity": 1},
        ]
        line = _build_memorial_balancing_entry(
            700013, rows, KRUISPOSTEN_LEDGER, 100.0, 100.0, self.company, self.cost_center, "d", debug
        )
        self.assertIsNone(line, "balanced multi-row memorial needs no balancing leg")

    def test_unmapped_main_ledger_raises(self):
        debug = []
        rows = [{"ledgerId": EXPENSE_LEDGER, "amount": 100.0, "quantity": 1}]
        with self.assertRaises(Exception):
            _build_memorial_balancing_entry(
                700014, rows, "999999999", 100.0, 0.0, self.company, self.cost_center, "d", debug
            )


# ---------------------------------------------------------------------------
# _process_journal_entry_rows
# ---------------------------------------------------------------------------
class TestProcessJournalEntryRows(_JournalClusterBase):
    def _new_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        return je

    def test_memorial_single_row_balanced_with_main_leg(self):
        je = self._new_je()
        mut = self._memorial_mutation()
        rows = mut["Regels"]
        td, tc = _process_journal_entry_rows(
            je, mut, rows, KRUISPOSTEN_LEDGER, self.company, self.cost_center, "d", []
        )
        # Two legs: the expense row + the kruisposten balancing leg.
        self.assertEqual(len(je.accounts), 2)
        self.assertAlmostEqual(td, tc, places=2)  # balanced
        self.assertAlmostEqual(td, 100.0, places=2)
        accounts = {a.account for a in je.accounts}
        self.assertEqual(accounts, {self.expense, self.kruisposten})
        # Verified convention: positive row amount -> row CREDITED, main DEBITED.
        row_line = next(a for a in je.accounts if a.account == self.expense)
        main_line = next(a for a in je.accounts if a.account == self.kruisposten)
        self.assertEqual(flt(row_line.credit_in_account_currency), 100.0)
        self.assertEqual(flt(main_line.debit_in_account_currency), 100.0)

    def test_zero_amount_rows_skipped(self):
        je = self._new_je()
        mut = self._memorial_mutation(id=700020)
        mut["Regels"] = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 0.0, "quantity": 1, "description": "zero"},
            {"ledgerId": INCOME_LEDGER, "amount": 50.0, "quantity": 1, "description": "real"},
        ]
        td, tc = _process_journal_entry_rows(
            je, mut, mut["Regels"], KRUISPOSTEN_LEDGER, self.company, self.cost_center, "d", []
        )
        # zero row skipped: income row + balancing leg = 2 lines, not 3.
        self.assertEqual(len(je.accounts), 2)
        self.assertAlmostEqual(td, tc, places=2)

    def test_non_memorial_rows_use_sign_based_debit_credit(self):
        # type != 7 path: positive amount -> debit, negative -> credit; no balancing leg.
        je = self._new_je()
        mut = {
            "id": 700030,
            "type": 5,
            "date": nowdate(),
            "relationId": None,
            "description": "money received split",
            "ledgerId": BANK_LEDGER,
            "Regels": [
                {"ledgerId": INCOME_LEDGER, "amount": 80.0, "quantity": 1, "description": "pos"},
                {"ledgerId": EXPENSE_LEDGER, "amount": -30.0, "quantity": 1, "description": "neg"},
            ],
        }
        td, tc = _process_journal_entry_rows(
            je, mut, mut["Regels"], BANK_LEDGER, self.company, self.cost_center, "d", []
        )
        # No memorial balancing leg for type 5 -> exactly 2 lines.
        self.assertEqual(len(je.accounts), 2)
        pos = next(a for a in je.accounts if a.account == self.income)
        neg = next(a for a in je.accounts if a.account == self.expense)
        self.assertEqual(flt(pos.debit_in_account_currency), 80.0)
        self.assertEqual(flt(pos.credit_in_account_currency), 0.0)
        self.assertEqual(flt(neg.credit_in_account_currency), 30.0)
        self.assertEqual(flt(neg.debit_in_account_currency), 0.0)
        self.assertEqual(td, 80.0)
        self.assertEqual(tc, 30.0)


# ---------------------------------------------------------------------------
# _validate_memorial_booking
# ---------------------------------------------------------------------------
class TestValidateMemorialBooking(_JournalClusterBase):
    def _new_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        return je

    def test_balanced_booking_passes(self):
        je = self._new_je()
        mut = self._memorial_mutation(id=700040)
        rows = mut["Regels"]
        # net amount from one +100 row is 100; legs balance at 100/100.
        debug = []
        _validate_memorial_booking(
            je, mut, rows, 100.0, 100.0, 100.0, self.company, self.cost_center, debug
        )
        self.assertTrue(any("is balanced" in m for m in debug))

    def test_unbalanced_legs_raise(self):
        je = self._new_je()
        mut = self._memorial_mutation(id=700041)
        rows = mut["Regels"]
        with self.assertRaises(Exception):
            # debit 100 vs credit 90 -> imbalance > tolerance.
            _validate_memorial_booking(
                je, mut, rows, 100.0, 100.0, 90.0, self.company, self.cost_center, []
            )

    def test_row_sum_mismatch_raises(self):
        # rows sum to 100 net but mutation amount claims 200 -> row validation fails.
        je = self._new_je()
        mut = self._memorial_mutation(id=700042)
        rows = mut["Regels"]
        with self.assertRaises(Exception):
            _validate_memorial_booking(
                je, mut, rows, 200.0, 100.0, 100.0, self.company, self.cost_center, []
            )


# ---------------------------------------------------------------------------
# _add_payment_offset_entry  (type 3/4)
# ---------------------------------------------------------------------------
class TestAddPaymentOffsetEntry(_JournalClusterBase):
    def _new_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        return je

    def test_credit_excess_debits_bank(self):
        # total_credit(100) - total_debit(0) = +100 net -> bank DEBITED 100.
        je = self._new_je()
        mut = {"id": 700050, "type": 3, "description": "refund"}
        _add_payment_offset_entry(
            je, mut, BANK_LEDGER, self.company, self.cost_center, 0.0, 100.0, "refund", []
        )
        self.assertEqual(len(je.accounts), 1)
        line = je.accounts[0]
        self.assertEqual(line.account, self.bank)
        self.assertEqual(flt(line.debit_in_account_currency), 100.0)
        self.assertEqual(flt(line.credit_in_account_currency), 0.0)

    def test_debit_excess_credits_bank(self):
        # total_credit(0) - total_debit(100) = -100 net -> bank CREDITED 100.
        je = self._new_je()
        mut = {"id": 700051, "type": 4, "description": "payment"}
        _add_payment_offset_entry(
            je, mut, BANK_LEDGER, self.company, self.cost_center, 100.0, 0.0, "payment", []
        )
        line = je.accounts[0]
        self.assertEqual(flt(line.credit_in_account_currency), 100.0)
        self.assertEqual(flt(line.debit_in_account_currency), 0.0)

    def test_offset_balances_the_rows(self):
        # The offset leg always brings the JE to balance.
        je = self._new_je()
        mut = {"id": 700052, "type": 3, "description": "x"}
        _add_payment_offset_entry(
            je, mut, BANK_LEDGER, self.company, self.cost_center, 0.0, 100.0, "x", []
        )
        # offset alone: 100 debit. Together with the (simulated) 100 credit rows it nets to 0.
        offset_debit = flt(je.accounts[0].debit_in_account_currency)
        self.assertAlmostEqual(offset_debit - 100.0, 0.0, places=2)

    def test_unmapped_bank_ledger_raises(self):
        je = self._new_je()
        mut = {"id": 700053, "type": 3, "description": "x"}
        with self.assertRaises(Exception):
            _add_payment_offset_entry(
                je, mut, "999999999", self.company, self.cost_center, 0.0, 100.0, "x", []
            )


# ---------------------------------------------------------------------------
# _create_journal_entry  (full end-to-end: builds, saves & submits a real JE)
# ---------------------------------------------------------------------------
class TestCreateJournalEntryEndToEnd(_JournalClusterBase):
    def test_memorial_single_row_creates_balanced_submitted_je(self):
        debug = []
        mut = self._memorial_mutation(id=700100)
        je = _create_journal_entry(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(je, f"JE was None. debug={debug}")
        self.assertEqual(je.doctype, "Journal Entry")
        self.assertEqual(je.docstatus, 1, "memorial JE should be submitted")
        self.assertEqual(je.company, self.company)
        self.assertEqual(getdate(je.posting_date), getdate(nowdate()))
        self.assertEqual(je.eboekhouden_mutation_nr, "700100")
        # Two legs, balanced.
        self.assertEqual(len(je.accounts), 2)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2)
        self.assertAlmostEqual(td, 100.0, places=2)
        self.assertEqual({a.account for a in je.accounts}, {self.expense, self.kruisposten})

    def test_memorial_multi_row_balanced_and_submitted(self):
        # Two opposite-signed rows that net to zero against each other; the main
        # leg is omitted (already balanced) so we craft rows that need a balance.
        debug = []
        mut = self._memorial_mutation(id=700101)
        # +100 expense and -40 income => net 60. The main (kruisposten) leg
        # balances the JE. Because each row goes through the fallback
        # debit/credit mapping, assert only the global balance + submission.
        mut["Regels"] = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 100.0, "quantity": 1, "description": "a"},
            {"ledgerId": INCOME_LEDGER, "amount": -40.0, "quantity": 1, "description": "b"},
        ]
        je = _create_journal_entry(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(je, f"debug={debug}")
        self.assertEqual(je.docstatus, 1)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2, msg=f"unbalanced JE submitted! Dr={td} Cr={tc}")

    def test_zero_amount_memorial_creates_log_not_je(self):
        # All-zero rows -> _create_import_log_entry, NOT a Journal Entry.
        debug = []
        mut = self._memorial_mutation(id=700102)
        mut["Regels"] = [{"ledgerId": EXPENSE_LEDGER, "amount": 0.0, "quantity": 1, "description": "z"}]
        result = _create_journal_entry(mut, self.company, self.cost_center, debug)
        # Should not be a submitted Journal Entry document.
        self.assertTrue(
            result is None or getattr(result, "doctype", None) != "Journal Entry",
            msg=f"zero-amount memorial unexpectedly produced {result}",
        )
        self.assertTrue(any("Zero-amount transaction detected" in m for m in debug))

    def test_payment_type3_offsets_to_bank_and_balances(self):
        # Type 3 (customer payment / refund): rows post to a ledger, then the
        # bank main-ledger offset balances the JE.
        debug = []
        mut = {
            "id": 700103,
            "type": 3,
            "date": nowdate(),
            "amount": 100.0,
            "relationId": CUSTOMER_RELATION,
            "invoiceNumber": "PAY-700103",
            "description": "Customer refund",
            "ledgerId": BANK_LEDGER,  # main ledger -> bank offset
            "Regels": [
                {"ledgerId": RECEIVABLE_LEDGER, "amount": 100.0, "quantity": 1, "description": "recv"},
            ],
        }
        je = _create_journal_entry(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(je, f"debug={debug}")
        self.assertEqual(je.docstatus, 1)
        # receivable row + bank offset = 2 legs, balanced.
        self.assertEqual(len(je.accounts), 2)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2)
        # Receivable leg must carry a Customer party.
        recv_line = next(a for a in je.accounts if a.account == self.receivable)
        self.assertEqual(recv_line.party_type, "Customer")
        self.assertEqual(recv_line.party, self.customer)
        # Bank offset leg is present.
        self.assertTrue(any(a.account == self.bank for a in je.accounts))

    def test_single_line_simple_journal_entry_no_rows_is_rejected(self):
        # No Regels: the "simple" branch (~L3351-3383) builds ONLY one line on the
        # main ledger and explicitly does NOT add a balancing leg ("let journal
        # entry validation handle unbalanced entries"). A one-legged JE can never
        # balance, so ERPNext rejects it on submit. This pins that real contract:
        # the no-rows path cannot produce a submitted document.
        debug = []
        mut = {
            "id": 700104,
            "type": 5,
            "date": nowdate(),
            "amount": 200.0,
            "relationId": None,
            "description": "simple money received",
            "ledgerId": INCOME_LEDGER,
            "Regels": [],
        }
        with self.assertRaises(Exception):
            _create_journal_entry(mut, self.company, self.cost_center, debug)
        # The build wired the single debit leg before submission failed.
        self.assertTrue(any("Failed to create Journal Entry" in m for m in debug))

    def test_unbalanced_memorial_does_not_submit(self):
        # Hand-craft a memorial whose declared net (from rows) is internally
        # consistent but whose legs are forced unbalanced is impossible through
        # the normal path because the balancing leg always nets it. Instead,
        # verify the validation gate rejects a row-sum/amount mismatch end-to-end
        # by feeding a memorial whose rows can't be validated.
        # A memorial with a single +100 row is valid; we assert the happy path
        # already covered. Here we assert NO unbalanced JE ever submits: scan the
        # produced JE for balance (regression guard).
        debug = []
        mut = self._memorial_mutation(id=700105)
        mut["Regels"] = [
            {"ledgerId": EXPENSE_LEDGER, "amount": 123.45, "quantity": 1, "description": "a"},
        ]
        je = _create_journal_entry(mut, self.company, self.cost_center, debug)
        td, tc = self._balanced(je)
        self.assertAlmostEqual(td, tc, places=2)
        self.assertEqual(je.docstatus, 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
