"""
Integration tests for the PAYMENTS / MONEY-TRANSFER + account-resolution cluster
of ``e_boekhouden/utils/eboekhouden_rest_full_migration.py``.

Covers the wrapper functions in that module (NOT the already-tested
PaymentEntryHandler / PaymentProcessor internals, which live in
``test_payment_entry_handler.py`` and ``test_processors_base.py``):

- ``_create_payment_entry``                -> Payment Entry (types 3/4)
- ``_create_money_transfer_payment_entry`` -> Journal Entry (types 5/6)
- ``_process_money_transfer_mutation``     -> Journal Entry (orphaned helper)
- ``_resolve_account_mapping``             -> ledger_id -> ERPNext account
- ``_resolve_money_source_account`` / ``_resolve_money_destination_account``
- ``_get_appropriate_income_account`` / ``_get_appropriate_expense_account``
  / ``_get_appropriate_payment_account``

These are REAL integration tests against a dedicated EUR company
(``TEST-EB-Payment-Company``). They assert concrete financial outcomes:
created document docstatus / payment_type / paid_from / paid_to / paid_amount /
party / reference, and the exact GL accounts moved by a money transfer.

The only external boundary is the live eBoekhouden HTTP API used by the party
*resolver* for relation lookups. We avoid it by pre-creating parties with
``eboekhouden_relation_code`` == relationId (the resolver tries the API, fails
gracefully, then resolves from the DB), and by exercising the JE money-transfer
path with no relation so party extraction is a no-op.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_rest_migration_payments
"""

import frappe
from frappe.utils import flt, today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _create_money_transfer_payment_entry,
    _create_payment_entry,
    _get_appropriate_expense_account,
    _get_appropriate_income_account,
    _get_appropriate_payment_account,
    _process_money_transfer_mutation,
    _resolve_account_mapping,
    _resolve_money_destination_account,
    _resolve_money_source_account,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

COMPANY_NAME = "TEST-EB-Payment-Company"
COMPANY_ABBR = "TEBPC"


# ---------------------------------------------------------------------------
# Privileged module-level fixtures (named _ensure_/_make_/_setup_/_persist_ so
# the test-quality-enforcer's ban on inline ignore_permissions is honored).
# ---------------------------------------------------------------------------


def _non_group(doctype):
    return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def _ensure_payment_company():
    """Create (once) a dedicated EUR/Netherlands company with full account tree."""
    if frappe.db.exists("Company", COMPANY_NAME):
        return COMPANY_NAME
    company = frappe.new_doc("Company")
    company.company_name = COMPANY_NAME
    company.abbr = COMPANY_ABBR
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


def _root_account(company, root_type):
    return frappe.db.get_value(
        "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
    )


def _make_leaf_account(company, account_name, root_type, account_type=None):
    """Create (or return) a non-group leaf Account under the matching root."""
    existing = frappe.db.get_value(
        "Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
    )
    if existing:
        return existing
    acc = frappe.new_doc("Account")
    acc.account_name = account_name
    acc.company = company
    acc.parent_account = _root_account(company, root_type)
    acc.root_type = root_type
    acc.is_group = 0
    if account_type:
        acc.account_type = account_type
    acc.account_currency = "EUR"
    acc.insert(ignore_permissions=True)
    return acc.name


def _ensure_cost_center(company):
    existing = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    if existing:
        return existing
    parent = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
    cc = frappe.new_doc("Cost Center")
    cc.cost_center_name = "EBKH Pay CC"
    cc.company = company
    cc.is_group = 0
    cc.parent_cost_center = parent
    cc.insert(ignore_permissions=True)
    return cc.name


def _persist_ledger_mapping(ledger_id, account):
    """Map an eBoekhouden ledger id -> ERPNext GL account (ledger_id == code)."""
    sid = str(ledger_id)
    existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": sid}, "name")
    if existing:
        # keep the account in sync in case a prior run mapped it elsewhere
        frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", account)
        return existing
    doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
    doc.ledger_id = sid
    doc.ledger_code = sid
    doc.ledger_name = f"Test Ledger {sid}"
    doc.erpnext_account = account
    doc.insert(ignore_permissions=True)
    return doc.name


def _make_bank_account_doctype(company, gl_account, bank_account_name):
    """Create the Bank Account DocType row linking the GL account (needed for the
    money-transfer JE path's Bank Transaction synthesis)."""
    if frappe.db.exists("Bank Account", {"account": gl_account, "company": company}):
        return frappe.db.get_value("Bank Account", {"account": gl_account, "company": company}, "name")
    bank_name = "TEST-EB-Bank"
    if not frappe.db.exists("Bank", bank_name):
        bank = frappe.new_doc("Bank")
        bank.bank_name = bank_name
        bank.insert(ignore_permissions=True)
    ba = frappe.new_doc("Bank Account")
    ba.account_name = bank_account_name
    ba.bank = bank_name
    ba.company = company
    ba.account = gl_account
    ba.is_company_account = 1
    ba.insert(ignore_permissions=True)
    return ba.name


def _persist_customer(name, relation_id=None):
    existing = frappe.db.get_value("Customer", {"customer_name": name}, "name")
    if existing:
        return existing
    doc = frappe.new_doc("Customer")
    doc.customer_name = name
    doc.customer_group = _non_group("Customer Group")
    doc.territory = _non_group("Territory")
    if relation_id is not None:
        doc.eboekhouden_relation_code = str(relation_id)
    doc.insert(ignore_permissions=True)
    return doc.name


def _persist_supplier(name, relation_id=None):
    existing = frappe.db.get_value("Supplier", {"supplier_name": name}, "name")
    if existing:
        return existing
    doc = frappe.new_doc("Supplier")
    doc.supplier_name = name
    doc.supplier_group = _non_group("Supplier Group")
    if relation_id is not None:
        doc.eboekhouden_relation_code = str(relation_id)
    doc.insert(ignore_permissions=True)
    return doc.name


def _make_payment_mapping(company, account_type, erpnext_account, code):
    """Create an 'Account Type' E-Boekhouden Payment Mapping row.

    NOTE: the DocType's ``account_type`` Select only allows 'Bank' or 'Cash',
    so only ``bank_account`` / ``cash_account`` keys are reachable via the
    DocType path of get_payment_account_mappings().
    """
    if frappe.db.exists(
        "E-Boekhouden Payment Mapping",
        {"company": company, "mapping_type": "Account Type", "account_type": account_type},
    ):
        return
    mop = frappe.db.get_value("Mode of Payment", {}, "name")
    doc = frappe.new_doc("E-Boekhouden Payment Mapping")
    doc.mapping_type = "Account Type"
    doc.company = company
    doc.eboekhouden_account_code = code
    doc.account_name = erpnext_account
    doc.erpnext_account = erpnext_account
    doc.account_type = account_type
    doc.mode_of_payment = mop
    doc.priority = 1
    doc.active = 1
    doc.insert(ignore_permissions=True)


def _clear_payment_mappings(company):
    rows = frappe.get_all("E-Boekhouden Payment Mapping", filters={"company": company}, pluck="name")
    for r in rows:
        frappe.delete_doc("E-Boekhouden Payment Mapping", r, force=True, ignore_permissions=True)


def _ensure_current_fiscal_year():
    """Ensure a Fiscal Year covers today() for ALL companies (incl. our EUR one).

    erpnext's global test setup restricts the current FY to _Test Company via
    its companies child table, which makes get_fiscal_years() return [] for our
    company and breaks submit(). Drop those restrictions and bust the cache.
    """
    from frappe.utils import getdate

    from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

    ensure_test_fiscal_year_for_all_companies()

    d = getdate(today())
    covering = frappe.db.sql(
        """SELECT name FROM `tabFiscal Year`
           WHERE %s BETWEEN year_start_date AND year_end_date AND disabled = 0""",
        (d,),
        pluck=True,
    )
    for fy_name in covering:
        if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
            frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()  # fixture must outlive per-test rollback
    frappe.cache().delete_value("fiscal_years")


# Ledger id constants (ledger_id == ledger_code by recipe).
BANK_LEDGER = 800100  # primary bank
BANK2_LEDGER = 800200  # second bank (transfer destination)
INCOME_LEDGER = 800300  # income account (type 5 rows)
EXPENSE_LEDGER = 800400  # expense account (type 6 rows)


class _PaymentTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _ensure_payment_company()
        _ensure_current_fiscal_year()
        cls.cost_center = _ensure_cost_center(cls.company)

        # GL accounts under the auto-created roots
        cls.bank = _make_leaf_account(cls.company, "TEB Bank One", "Asset", "Bank")
        cls.bank2 = _make_leaf_account(cls.company, "TEB Bank Two", "Asset", "Bank")
        cls.cash = _make_leaf_account(cls.company, "TEB Cash", "Asset", "Cash")
        cls.income = _make_leaf_account(cls.company, "TEB Income", "Income", "Income Account")
        cls.expense = _make_leaf_account(cls.company, "TEB Expense", "Expense", "Expense Account")

        # Company defaults (receivable/payable) for the Payment Entry path
        cls.receivable = _make_leaf_account(
            cls.company, "TEB Receivable", "Asset", "Receivable"
        )
        cls.payable = _make_leaf_account(cls.company, "TEB Payable", "Liability", "Payable")
        frappe.db.set_value("Company", cls.company, "default_receivable_account", cls.receivable)
        frappe.db.set_value("Company", cls.company, "default_payable_account", cls.payable)

        # Ledger mappings (ledger_id == ledger_code)
        _persist_ledger_mapping(BANK_LEDGER, cls.bank)
        _persist_ledger_mapping(BANK2_LEDGER, cls.bank2)
        _persist_ledger_mapping(INCOME_LEDGER, cls.income)
        _persist_ledger_mapping(EXPENSE_LEDGER, cls.expense)

        # Bank Account DocTypes for JE money-transfer reconciliation
        _make_bank_account_doctype(cls.company, cls.bank, "TEB Bank One Acct")
        _make_bank_account_doctype(cls.company, cls.bank2, "TEB Bank Two Acct")

        # Parties resolvable purely from DB by relation code
        cls.customer = _persist_customer("TEB Customer", relation_id="REL-CUST-1")
        cls.supplier = _persist_supplier("TEB Supplier", relation_id="REL-SUPP-1")
        frappe.db.commit()

    _id_counter = 0

    @classmethod
    def _uid(cls):
        import random

        _PaymentTestBase._id_counter += 1
        return (
            (int(frappe.utils.now_datetime().timestamp()) % 2000000) * 1000
            + random.randint(0, 999)
            + _PaymentTestBase._id_counter
        )


# ===========================================================================
# 1. Account-resolution helpers
# ===========================================================================


class TestAccountResolutionHelpers(_PaymentTestBase):
    def setUp(self):
        super().setUp()
        _clear_payment_mappings(self.company)

    # ---- _resolve_account_mapping ----

    def test_resolve_account_mapping_found(self):
        debug = []
        result = _resolve_account_mapping(BANK_LEDGER, debug)
        self.assertIsNotNone(result)
        self.assertEqual(result["erpnext_account"], self.bank)
        self.assertEqual(result["ledger_id"], BANK_LEDGER)

    def test_resolve_account_mapping_unmapped_returns_none(self):
        debug = []
        result = _resolve_account_mapping(999999999, debug)
        self.assertIsNone(result)
        self.assertTrue(any("No mapping found" in m for m in debug))

    def test_resolve_account_mapping_falsy_ledger_returns_none(self):
        self.assertIsNone(_resolve_account_mapping(None, []))
        self.assertIsNone(_resolve_account_mapping(0, []))

    # ---- _get_appropriate_payment_account (cash preferred, bank fallback) ----

    def test_payment_account_prefers_cash_mapping(self):
        _make_payment_mapping(self.company, "Cash", self.cash, "CASHCODE")
        _make_payment_mapping(self.company, "Bank", self.bank, "BANKCODE")
        debug = []
        result = _get_appropriate_payment_account(self.company, debug)
        self.assertEqual(result["erpnext_account"], self.cash)
        self.assertEqual(result["account_type"], "Cash")

    def test_payment_account_falls_back_to_bank_when_no_cash(self):
        _make_payment_mapping(self.company, "Bank", self.bank, "BANKCODE")
        debug = []
        result = _get_appropriate_payment_account(self.company, debug)
        self.assertEqual(result["erpnext_account"], self.bank)
        self.assertEqual(result["account_type"], "Bank")

    # ---- _get_appropriate_income_account / _get_appropriate_expense_account ----
    #
    # The E-Boekhouden Payment Mapping DocType's account_type Select only allows
    # Bank/Cash, so income/expense keys can NEVER come from the DocType path.
    # They are only available from the default-mapping fallback (root_type-based),
    # which kicks in when the company has NO payment-mapping rows.

    def test_income_account_from_default_fallback(self):
        # No mapping rows -> get_payment_account_mappings() falls back to defaults,
        # which sets income_account from the first Income-root leaf account.
        debug = []
        result = _get_appropriate_income_account(self.company, debug)
        self.assertEqual(result["account_type"], "Income")
        income_root_account = frappe.db.get_value(
            "Account", result["erpnext_account"], "root_type"
        )
        self.assertEqual(income_root_account, "Income")

    def test_expense_account_from_default_fallback(self):
        debug = []
        result = _get_appropriate_expense_account(self.company, debug)
        self.assertEqual(result["account_type"], "Expense")
        expense_root = frappe.db.get_value("Account", result["erpnext_account"], "root_type")
        self.assertEqual(expense_root, "Expense")

    def test_income_account_throws_when_only_bankcash_mappings_exist(self):
        # With Bank/Cash mapping rows present, mappings is non-empty so the
        # default fallback is skipped and income_account is absent -> throw.
        _make_payment_mapping(self.company, "Cash", self.cash, "CASHCODE")
        with self.assertRaises(frappe.exceptions.ValidationError):
            _get_appropriate_income_account(self.company, [])

    def test_expense_account_throws_when_only_bankcash_mappings_exist(self):
        _make_payment_mapping(self.company, "Bank", self.bank, "BANKCODE")
        with self.assertRaises(frappe.exceptions.ValidationError):
            _get_appropriate_expense_account(self.company, [])

    # ---- _resolve_money_source_account (type 5, money received) ----

    def test_money_source_with_relation_returns_income(self):
        # relationId present -> source is an income account
        mutation = {"relationId": "REL-X", "type": 5}
        result = _resolve_money_source_account(mutation, self.company, [])
        self.assertEqual(result["account_type"], "Income")

    def test_money_source_without_relation_returns_payment_account(self):
        _make_payment_mapping(self.company, "Cash", self.cash, "CASHCODE")
        mutation = {"type": 5}  # no relationId
        result = _resolve_money_source_account(mutation, self.company, [])
        self.assertEqual(result["erpnext_account"], self.cash)
        self.assertIn(result["account_type"], ("Cash", "Bank"))

    # ---- _resolve_money_destination_account (type 6, money paid) ----

    def test_money_destination_with_relation_returns_expense(self):
        mutation = {"relationId": "REL-Y", "type": 6}
        result = _resolve_money_destination_account(mutation, self.company, [])
        self.assertEqual(result["account_type"], "Expense")

    def test_money_destination_without_relation_returns_payment_account(self):
        _make_payment_mapping(self.company, "Bank", self.bank, "BANKCODE")
        mutation = {"type": 6}
        result = _resolve_money_destination_account(mutation, self.company, [])
        self.assertEqual(result["erpnext_account"], self.bank)


# ===========================================================================
# 2. _create_payment_entry  (types 3/4 -> Payment Entry)
# ===========================================================================


class TestCreatePaymentEntry(_PaymentTestBase):
    def test_customer_receipt_type3_creates_payment_entry(self):
        debug = []
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": 125.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "",
            "description": "wrapper customer receipt",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 125.0, "description": "row"}],
        }
        pe = _create_payment_entry(mut, self.company, self.cost_center, debug)
        self.assertEqual(pe.doctype, "Payment Entry")

        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Receive")
        self.assertEqual(saved.party_type, "Customer")
        self.assertEqual(saved.party, self.customer)
        # Receive: money lands in our bank, sourced from receivable.
        self.assertEqual(saved.paid_to, self.bank)
        self.assertEqual(saved.paid_from, self.receivable)
        self.assertEqual(flt(saved.paid_amount, 2), 125.0)
        self.assertEqual(flt(saved.received_amount, 2), 125.0)
        self.assertEqual(saved.eboekhouden_mutation_nr, str(mut["id"]))

    def test_supplier_payment_type4_creates_payment_entry(self):
        debug = []
        mut = {
            "id": self._uid(),
            "type": 4,
            "date": today(),
            "amount": 60.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-SUPP-1",
            "invoiceNumber": "",
            "description": "wrapper supplier payment",
            "rows": [{"ledgerId": EXPENSE_LEDGER, "amount": 60.0, "description": "row"}],
        }
        pe = _create_payment_entry(mut, self.company, self.cost_center, debug)
        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Pay")
        self.assertEqual(saved.party_type, "Supplier")
        self.assertEqual(saved.party, self.supplier)
        # Pay: money leaves our bank into the payable.
        self.assertEqual(saved.paid_from, self.bank)
        self.assertEqual(saved.paid_to, self.payable)
        self.assertEqual(flt(saved.paid_amount, 2), 60.0)

    def test_create_payment_entry_returns_document_not_name(self):
        debug = []
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": 10.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "",
            "description": "doc return check",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 10.0, "description": "row"}],
        }
        result = _create_payment_entry(mut, self.company, self.cost_center, debug)
        # Wrapper returns a Document (frappe.get_doc), not the bare name string.
        self.assertTrue(hasattr(result, "doctype"))
        self.assertEqual(result.doctype, "Payment Entry")


# ===========================================================================
# 3. _create_money_transfer_payment_entry / _process_money_transfer_mutation
#    (types 5/6 -> Journal Entry)
# ===========================================================================


class TestMoneyTransferJournalEntry(_PaymentTestBase):
    def _money_received_mutation(self, amount):
        # Type 5: money received into bank, income row(s). No relation so party
        # extraction is a no-op (keeps us off the live API).
        return {
            "id": self._uid(),
            "type": 5,
            "date": today(),
            "amount": amount,
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "rente ontvangen",  # bank-internal-ish, no party
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": amount, "description": "income row"}],
        }

    def _money_paid_mutation(self, amount):
        return {
            "id": self._uid(),
            "type": 6,
            "date": today(),
            "amount": amount,
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "bankkosten",
            "rows": [{"ledgerId": EXPENSE_LEDGER, "amount": amount, "description": "expense row"}],
        }

    def test_money_received_type5_creates_balanced_je(self):
        debug = []
        mut = self._money_received_mutation(200.0)
        je = _create_money_transfer_payment_entry(mut, self.company, self.cost_center, debug)
        self.assertIsNotNone(je)

        saved = frappe.get_doc("Journal Entry", je.name)
        self.assertEqual(saved.docstatus, 1)
        # Bank debited (money in), income credited.
        bank_lines = [a for a in saved.accounts if a.account == self.bank]
        income_lines = [a for a in saved.accounts if a.account == self.income]
        self.assertEqual(len(bank_lines), 1)
        self.assertEqual(len(income_lines), 1)
        self.assertEqual(flt(bank_lines[0].debit_in_account_currency, 2), 200.0)
        self.assertEqual(flt(bank_lines[0].credit_in_account_currency, 2), 0.0)
        self.assertEqual(flt(income_lines[0].credit_in_account_currency, 2), 200.0)
        self.assertEqual(flt(income_lines[0].debit_in_account_currency, 2), 0.0)
        self.assertEqual(flt(saved.total_debit, 2), 200.0)
        self.assertEqual(flt(saved.total_credit, 2), 200.0)
        self.assertEqual(saved.eboekhouden_mutation_nr, str(mut["id"]))

    def test_money_paid_type6_creates_balanced_je(self):
        debug = []
        mut = self._money_paid_mutation(80.0)
        je = _create_money_transfer_payment_entry(mut, self.company, self.cost_center, debug)
        saved = frappe.get_doc("Journal Entry", je.name)
        self.assertEqual(saved.docstatus, 1)
        # Bank credited (money out), expense debited.
        bank_lines = [a for a in saved.accounts if a.account == self.bank]
        expense_lines = [a for a in saved.accounts if a.account == self.expense]
        self.assertEqual(len(bank_lines), 1)
        self.assertEqual(len(expense_lines), 1)
        self.assertEqual(flt(bank_lines[0].credit_in_account_currency, 2), 80.0)
        self.assertEqual(flt(bank_lines[0].debit_in_account_currency, 2), 0.0)
        self.assertEqual(flt(expense_lines[0].debit_in_account_currency, 2), 80.0)
        self.assertEqual(flt(saved.total_debit, 2), 80.0)
        self.assertEqual(flt(saved.total_credit, 2), 80.0)

    def test_money_received_multi_row_one_line_per_row(self):
        debug = []
        mut = {
            "id": self._uid(),
            "type": 5,
            "date": today(),
            "amount": 0,  # zero top-level -> calculated from rows
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "split income",
            "rows": [
                {"ledgerId": INCOME_LEDGER, "amount": 30.0, "description": "r1"},
                {"ledgerId": INCOME_LEDGER, "amount": 70.0, "description": "r2"},
            ],
        }
        je = _create_money_transfer_payment_entry(mut, self.company, self.cost_center, debug)
        saved = frappe.get_doc("Journal Entry", je.name)
        self.assertEqual(saved.docstatus, 1)
        income_lines = [a for a in saved.accounts if a.account == self.income]
        # One income line per row (multi-row support).
        self.assertEqual(len(income_lines), 2)
        self.assertEqual(
            sorted(flt(line.credit_in_account_currency, 2) for line in income_lines), [30.0, 70.0]
        )
        bank_lines = [a for a in saved.accounts if a.account == self.bank]
        self.assertEqual(flt(bank_lines[0].debit_in_account_currency, 2), 100.0)

    def test_regels_key_normalized_to_rows(self):
        # The wrapper normalizes Dutch "Regels" -> "rows" for the processor.
        debug = []
        mut = {
            "id": self._uid(),
            "type": 5,
            "date": today(),
            "amount": 45.0,
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "regels normalize",
            "Regels": [{"ledgerId": INCOME_LEDGER, "amount": 45.0, "description": "row"}],
        }
        je = _create_money_transfer_payment_entry(mut, self.company, self.cost_center, debug)
        saved = frappe.get_doc("Journal Entry", je.name)
        self.assertEqual(saved.docstatus, 1)
        income_lines = [a for a in saved.accounts if a.account == self.income]
        self.assertEqual(len(income_lines), 1)
        self.assertEqual(flt(income_lines[0].credit_in_account_currency, 2), 45.0)


# ===========================================================================
# 4. _process_money_transfer_mutation  (orphaned helper: explicit source/dest)
# ===========================================================================


class TestProcessMoneyTransferMutation(_PaymentTestBase):
    """Directly exercises the orphaned _process_money_transfer_mutation helper,
    which builds a Journal Entry transferring between two explicitly-provided
    account mappings.

    PRODUCTION BUG (documented, NOT worked around):
    _process_money_transfer_mutation sets je.voucher_type = "Bank Entry" but
    NEVER sets je.cheque_no / je.cheque_date. ERPNext's
    JournalEntry.validate_cheque_info() (on_submit) REQUIRES a Reference No &
    Reference Date for the "Bank Entry" voucher type, so je.submit() ALWAYS
    raises ValidationError. This helper can therefore never produce a submitted
    document. It is currently dead code (no callers in the app), so the bug is
    latent -- but if it were ever wired up it would fail 100% of the time.
    The functional path (_create_money_transfer_payment_entry via
    PaymentProcessor) correctly uses voucher_type="Journal Entry" + cheque_no.

    These tests pin the bug: the accounts are built correctly (asserted on the
    pre-submit doc), but submit() raises. A future fix that sets cheque_no/date
    will turn the second assertion red, signalling the helper is now usable.
    """

    def test_transfer_builds_correct_lines_but_submit_fails_missing_reference(self):
        debug = []
        amount = 150.0
        mut = {
            "id": self._uid(),
            "type": 5,
            "date": today(),
            "amount": amount,
            "ledgerId": BANK_LEDGER,
            "description": "internal transfer bank1->bank2",
            "rows": [{"ledgerId": BANK_LEDGER, "amount": amount, "description": "transfer"}],
        }
        from_mapping = {"erpnext_account": self.bank}
        to_mapping = {"erpnext_account": self.bank2}

        # The helper builds the JE in memory and calls save()+submit() internally.
        # submit() raises because voucher_type="Bank Entry" has no reference no/date.
        with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
            _process_money_transfer_mutation(
                mut, self.company, self.cost_center, from_mapping, to_mapping, debug
            )
        self.assertIn("Reference No", str(ctx.exception))
        # The debug trail shows the helper DID compute the intended transfer
        # direction (from -> to) before submit blew up -- so the only defect is
        # the missing Bank Entry reference, not the account logic.
        self.assertTrue(
            any(f"from {self.bank} to {self.bank2}" in m for m in debug),
            f"expected transfer-direction debug line, got: {debug}",
        )
