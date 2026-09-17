"""
Integration tests for the PAYMENTS / MONEY-TRANSFER + account-resolution cluster
of ``e_boekhouden/utils/eboekhouden_rest_full_migration.py``.

Covers the wrapper functions in that module (NOT the already-tested
PaymentEntryHandler / PaymentProcessor internals, which live in
``test_payment_entry_handler.py`` and ``test_processors_base.py``):

- ``_create_payment_entry``                -> Payment Entry (types 3/4)
- ``_create_money_transfer_payment_entry`` -> Journal Entry (types 5/6)
- ``_resolve_account_mapping``             -> ledger_id -> ERPNext account

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

import unittest
from unittest import mock

import frappe
from frappe.utils import flt, today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _create_money_transfer_payment_entry,
    _create_payment_entry,
    _resolve_account_mapping,
)
from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    shared_fixture,
    suspend_insert_capture,
)
from verenigingen.tests.harness_logger import LOGGER_NAME, get_harness_logger

COMPANY_NAME = "TEST-EB-Payment-Company"
COMPANY_ABBR = "TEBPC"


# ---------------------------------------------------------------------------
# Privileged module-level fixtures (named _ensure_/_make_/_setup_/_persist_ so
# the test-quality-enforcer's ban on inline ignore_permissions is honored).
# ---------------------------------------------------------------------------


def _non_group(doctype):
    return frappe.db.get_value(doctype, {"is_group": 0}, "name")


@shared_fixture
def _ensure_payment_company():
    """Create (once) a dedicated EUR/Netherlands company with full account tree.

    ``TEST-EB-Payment-Company`` is site-owned master data shared by every test
    in this module, not a throwaway row belonging to whichever test calls
    first. It survived only by accident before this decorator: the
    captured-insert drain is installed in ``EnhancedTestCase.setUp``, not
    ``setUpClass``, and every caller here happens to run from
    ``_PaymentTestBase.setUpClass()``. That is a harness implementation
    detail, not a declared contract -- #392 found the same company built a
    second time, unprotected, in ``test_e_boekhouden_migration_integration.py``
    (fixed there under ``@shared_fixture`` by #387), and #386/#387 already
    measured what happens when the drain claims a company's whole chart of
    accounts: every later class needing it dies in ``setUpClass``.
    """
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
INCOME_LEDGER = 800300  # income account (type 5 rows)
EXPENSE_LEDGER = 800400  # expense account (type 6 rows)


class _PaymentTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Everything below is site-owned master data shared by every test in this
        # module (the company, its chart of accounts, cost center, ledger mappings,
        # bank account and the two parties) -- not a throwaway row belonging to
        # whichever test happens to run first. It survived the captured-insert
        # drain only because that hook is installed in EnhancedTestCase.setUp, not
        # setUpClass; suspending capture here makes that a declared contract
        # instead of an accident of call order (#392).
        with suspend_insert_capture():
            cls.company = _ensure_payment_company()
            _ensure_current_fiscal_year()
            cls.cost_center = _ensure_cost_center(cls.company)

            # GL accounts under the auto-created roots
            cls.bank = _make_leaf_account(cls.company, "TEB Bank One", "Asset", "Bank")
            cls.cash = _make_leaf_account(cls.company, "TEB Cash", "Asset", "Cash")
            cls.income = _make_leaf_account(cls.company, "TEB Income", "Income", "Income Account")
            cls.expense = _make_leaf_account(cls.company, "TEB Expense", "Expense", "Expense Account")

            # Company defaults (receivable/payable) for the Payment Entry path
            cls.receivable = _make_leaf_account(
                cls.company, "TEB Receivable", "Asset", "Receivable"
            )
            cls.payable = _make_leaf_account(cls.company, "TEB Payable", "Liability", "Payable")
            frappe.db.set_value(
                "Company", cls.company, "default_receivable_account", cls.receivable
            )
            frappe.db.set_value("Company", cls.company, "default_payable_account", cls.payable)

            # Ledger mappings (ledger_id == ledger_code)
            _persist_ledger_mapping(BANK_LEDGER, cls.bank)
            _persist_ledger_mapping(INCOME_LEDGER, cls.income)
            _persist_ledger_mapping(EXPENSE_LEDGER, cls.expense)

            # Bank Account DocType for JE money-transfer reconciliation
            _make_bank_account_doctype(cls.company, cls.bank, "TEB Bank One Acct")

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
# 3. _create_money_transfer_payment_entry  (types 5/6 -> Journal Entry)
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


def _create_probe_company(module_name, temp_name, temp_abbr):
    """Build a throwaway company through the real ``_ensure_payment_company()``
    and commit it. Named ``_create_*`` -- a privileged fixture-building prefix
    recognised across this codebase (``scripts/validation/test_quality_enforcer.py``
    lists it alongside ``_ensure_``/``_make_``/``_setup_``/``_persist_``), though
    it is the first ``_create_*`` helper in THIS file -- rather than inlined in
    the test body, for two reasons:

    1. The commit is load-bearing, but NOT for the reason first written here. The
       original claim was that the drain's own pre-delete
       ``frappe.db.rollback()`` would otherwise destroy the uncommitted row. That
       is true only on the UNPROTECTED branch, which is not the one a passing run
       exercises: with ``@shared_fixture`` in place the insert never enters
       ``_captured_inserts``, so ``_drain_captured_inserts()`` returns on its
       first line (``if not captured: return``) and that rollback is never
       reached at all. Measured three ways on test_site_2 with the drain
       instrumented, including a second pymysql connection confirming the row
       was never committed.

       The real reason is durability against any LATER rollback in the same
       process. Without the commit the company sits in the connection's still-open
       transaction after the test method returns, and the next test class's own
       drain calls ``frappe.db.rollback()`` -- observed doing so, in the same run.
       That would wipe the row and make this an order-dependent flake, which is a
       particularly bad failure mode for a regression test about order dependence.
    2. ``scripts/testing/scan_order_dependence.py``'s order-dependence scanner
       exempts ``_cleanup_*``/``_create_*``/``tearDown`` helpers from its COMMIT
       check on the same reasoning it exempts every other privileged fixture
       helper in this codebase -- a bare ``frappe.db.commit()`` inline in a
       ``test_*`` method is what the ratchet is watching for, not one inside a
       named, reviewed fixture builder.
    """
    with mock.patch(f"{module_name}.COMPANY_NAME", temp_name), mock.patch(
        f"{module_name}.COMPANY_ABBR", temp_abbr
    ):
        _ensure_payment_company()
    frappe.db.commit()


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards so an abbr containing `_` or `%` cannot over-match.

    This repo has already shipped one unescaped-LIKE defect (a Mollie payment id
    containing `%`). Today's only caller passes a hex-derived abbr that cannot
    contain either character, but the helper takes `abbr` as a free parameter and
    must not depend on its caller staying that way.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _report_teardown_exception(company_name: str) -> None:
    """Log the FULL traceback for a teardown that raised.

    Extracted so it can be pinned by a test without mocking the database or
    `frappe.delete_doc` -- this is a Tier 2 path where database mocks are a hard
    gate. `str(e)` was what this replaced, and it cannot say WHERE the delete
    failed, which is the question #1150 poses.
    """
    get_harness_logger("test_rest_migration_payments").error(
        f"PROBE-TEARDOWN-RAISED {company_name}\n{frappe.get_traceback()}"
    )


def _probe_residue(company_name: str, abbr: str) -> dict:
    """Rows that must NOT survive this probe's tearDown, keyed by doctype.

    #1150: the teardown deletes the probe Company with ``force=True``, which
    SKIPS link validation. So the delete can report success and still strand an
    Account that another Company's default-account row points at -- and the next
    ``Company`` insert in the same shard then dies with
    ``LinkValidationError: Could not find Row #N: ... Default Account:
    Expense Claims - <abbr>``, erroring four ``setUpClass`` calls that never
    touched this module. Checking the Company row alone would not see that, so
    this also looks for Accounts carrying the probe's abbr.
    """
    residue = {
        "Company": [company_name] if frappe.db.exists("Company", company_name) else [],
        # Account is matched by NAME because its rows are named `<Name> - <ABBR>`
        # and the stranded row in #1150 was identified that way. `_` and `%` are
        # LIKE wildcards, so the abbr is escaped -- ERPNext's own `_Test Company`
        # has abbr `_TC`, and unescaped that pattern also matches `Debtors - XTC`.
        "Account": frappe.get_all(
            "Account", filters={"name": ("like", f"%- {_like_escape(abbr)}")}, pluck="name"
        ),
    }
    # `Company.on_trash` removes these in the same sweep, scoped by `company`, and
    # Account happens to go FIRST -- so an on_trash interrupted anywhere later
    # strands one of these instead, with the same dangling-link consequence.
    for doctype in ("Cost Center", "Warehouse", "Mode of Payment Account"):
        residue[doctype] = frappe.get_all(
            doctype, filters={"company": company_name}, pluck="name"
        )
    return residue


def _report_probe_residue(company_name: str, abbr: str, when: str) -> dict:
    """Log any surviving probe rows LOUDLY, and return them.

    Loud means the harness logger (stderr, reaches the CI job log) rather than
    ``frappe.logger()``, which writes to a file CI never uploads -- see
    CLAUDE.md's "known traps". The tag is greppable on purpose: a shard log is
    1.4MB and this needs to be findable without reading it.
    """
    residue = {dt: rows for dt, rows in _probe_residue(company_name, abbr).items() if rows}
    if residue:
        detail = "; ".join(f"{dt}={rows}" for dt, rows in residue.items())
        get_harness_logger("test_rest_migration_payments").error(
            f"PROBE-RESIDUE ({when}) {company_name} abbr={abbr}: {detail}"
        )
    return residue


class TestEbPaymentCompanySurvivesCapture(unittest.TestCase):
    """#392: ``_ensure_payment_company`` is protected from the captured-insert
    drain only by accident -- it happens to be called from
    ``_PaymentTestBase.setUpClass()``, and the drain's insert-capture hook is
    installed in ``EnhancedTestCase.setUp``, not ``setUpClass``
    (``enhanced_test_factory.py``'s ``_install_insert_capture``). That is a
    harness implementation detail, not a declared contract: #386/#387 already
    showed the same unprotected-builder shape losing a sibling company's whole
    chart of accounts the moment something forced it through the drain.

    This proves the claim empirically instead of trusting call-site ordering:
    install the REAL capture hook, call the REAL builder against a throwaway
    company name, run the REAL drain, and check whether the company survives.
    """

    def setUp(self):
        suffix = frappe.generate_hash(length=6)
        self.temp_company_name = f"TEST-EB-Payment-Shared-Probe-{suffix}"
        self.temp_company_abbr = f"TPP{suffix[:5]}"

    def tearDown(self):
        # Committed, not just deleted: this class is plain unittest.TestCase (no
        # framework rollback of its own), but sibling classes in this module ARE
        # EnhancedTestCase and roll back per test. Measured: an uncommitted delete
        # here is undone whole by the next such rollback -- the Company, its 96
        # Accounts, 2 Cost Centers and 5 Warehouses all reappeared in a probe run
        # against test_site_2 -- reproducing exactly the leak this test exists to
        # prevent, just one call later and silently.
        #
        # A failed delete must be visible, not swallowed: frappe.logger() writes
        # to a file CI never surfaces (see CLAUDE.md's "known traps"), so use the
        # harness logger, which reaches stderr and the CI job log.
        #
        # #1150: `str(e)` alone cannot answer the question this failure poses --
        # whether the delete RAISES or silently half-succeeds -- so log the full
        # traceback, and then check for residue REGARDLESS of whether we raised.
        # A `force=True` delete that reports success while stranding an Account
        # is precisely the case the old `except` could not see, because it never
        # ran on the success path at all.
        try:
            if frappe.db.exists("Company", self.temp_company_name):
                frappe.delete_doc(
                    "Company", self.temp_company_name, force=True, ignore_permissions=True
                )
                frappe.db.commit()
        except Exception:
            _report_teardown_exception(self.temp_company_name)
        # Guarded in its own right: this runs OUTSIDE the try above, and a
        # diagnostic must never convert a previously-silent teardown into a new
        # test ERROR. It is read-only, but "unlikely to raise" is not "cannot".
        try:
            _report_probe_residue(
                self.temp_company_name, self.temp_company_abbr, "after tearDown"
            )
        except Exception:
            get_harness_logger("test_rest_migration_payments").error(
                f"PROBE-RESIDUE-CHECK-FAILED {self.temp_company_name}\n{frappe.get_traceback()}"
            )

    def test_ensure_payment_company_survives_capture(self):
        module_name = "verenigingen.tests.e_boekhouden.test_rest_migration_payments"

        class _Probe(EnhancedTestCase):
            # Function-local, so unittest's TestCase-subclass discovery can never
            # collect it regardless of test_* methods (see
            # test_harness_leak_attribution.py's _DrainProbe for the same trick).
            pass

        probe = _Probe("runTest")
        probe._captured_inserts = []
        probe._install_insert_capture()
        try:
            _create_probe_company(module_name, self.temp_company_name, self.temp_company_abbr)
        finally:
            probe._uninstall_insert_capture()

        self.assertTrue(
            frappe.db.exists("Company", self.temp_company_name),
            "sanity check: the builder must actually have created the company",
        )

        probe._drain_captured_inserts()

        self.assertTrue(
            frappe.db.exists("Company", self.temp_company_name),
            "_ensure_payment_company must be @shared_fixture (or build under "
            "suspend_insert_capture()), or the captured-insert drain claims the "
            "company the moment this helper is ever called from outside "
            "setUpClass (#392)",
        )


class TestProbeResidueDetector(unittest.TestCase):
    """#1150: the probe teardown force-deletes its Company, and ``force=True``
    skips link validation -- so the delete can report success while stranding an
    Account that another Company's default-account row still points at. That is
    what erroring four ``setUpClass`` calls on shard 12 looks like from the
    outside, and the swallowed ``except`` meant nothing recorded it.

    These pin the detector that makes the residue visible. They query REAL rows
    (no database mocks -- this is a Tier 2 path) and never create any, so they
    cannot themselves leak what they exist to detect.
    """

    def test_reports_a_company_that_still_exists(self):
        existing = frappe.get_all("Company", pluck="name", limit=1)
        if not existing:
            self.skipTest("no Company on this site to probe against")
        residue = _probe_residue(existing[0], "NOSUCHABBRZZZ")
        self.assertEqual(residue["Company"], [existing[0]])
        # control: a bogus abbr must find nothing, or the Account filter is
        # matching everything and the positive case below proves nothing.
        self.assertEqual(residue["Account"], [])

    def test_is_silent_for_a_company_that_is_really_gone(self):
        residue = _probe_residue("TEST-EB-Probe-Does-Not-Exist-zzzzzz", "NOSUCHABBRZZZ")
        self.assertEqual(residue["Company"], [])
        self.assertEqual(residue["Account"], [])

    def test_finds_accounts_by_the_company_abbr_suffix(self):
        """The stranded row in #1150 was `Expense Claims - TPPf171c` -- an Account
        carrying the probe's abbr. Pin that the suffix filter actually matches
        that shape, against a real account name from this site."""
        named = [n for n in frappe.get_all("Account", pluck="name", limit=50) if "- " in n]
        if not named:
            self.skipTest("no abbr-suffixed Account on this site to probe against")
        abbr = named[0].rsplit("- ", 1)[-1]
        residue = _probe_residue("TEST-EB-Probe-Does-Not-Exist-zzzzzz", abbr)
        self.assertIn(named[0], residue["Account"])

    def test_reporter_returns_residue_when_rows_survive(self):
        """Control for the tearDown wiring. A clean CI run logging nothing only
        means something if this path is known to fire when there IS residue --
        otherwise silence is equally consistent with a broken detector, which is
        how #1150 went unrecorded in the first place."""
        existing = frappe.get_all("Company", pluck="name", limit=1)
        if not existing:
            self.skipTest("no Company on this site to probe against")
        residue = _report_probe_residue(existing[0], "NOSUCHABBRZZZ", "control")
        self.assertEqual(residue.get("Company"), [existing[0]])
        # control: the bogus abbr must yield no Account key at all -- the reporter
        # drops empty doctypes, so its presence would mean the abbr filter is
        # matching rows it should not, and the positive cases prove nothing.
        self.assertNotIn("Account", residue)

    def test_reporter_is_empty_when_nothing_survives(self):
        residue = _report_probe_residue(
            "TEST-EB-Probe-Does-Not-Exist-zzzzzz", "NOSUCHABBRZZZ", "control"
        )
        self.assertEqual(residue, {})

    def test_reporter_actually_EMITS_the_residue_line(self):
        """The one thing this whole diagnostic exists to do.

        The return-value assertions above all still passed when the logging call
        was deleted outright -- nothing in production consumes that return value,
        so they pinned a contract disconnected from the purpose. This pins the
        emission itself.
        """
        existing = frappe.get_all("Company", pluck="name", limit=1)
        if not existing:
            self.skipTest("no Company on this site to probe against")
        with self.assertLogs(LOGGER_NAME, level="ERROR") as captured:
            _report_probe_residue(existing[0], "NOSUCHABBRZZZ", "control")
        joined = "\n".join(captured.output)
        self.assertIn("PROBE-RESIDUE", joined)
        self.assertIn(existing[0], joined)

    def test_teardown_exception_reporter_EMITS_a_full_traceback(self):
        """`PROBE-TEARDOWN-RAISED` is the branch that fires when the interesting
        failure happens, so it must not be the untested one. Raised for real
        rather than mocked -- database mocks are a hard gate on this Tier 2 path.
        """
        with self.assertLogs(LOGGER_NAME, level="ERROR") as captured:
            try:
                raise RuntimeError("probe delete failed")
            except RuntimeError:
                _report_teardown_exception("TEST-EB-Probe-Does-Not-Exist-zzzzzz")
        joined = "\n".join(captured.output)
        self.assertIn("PROBE-TEARDOWN-RAISED", joined)
        # the point of the change: a TRACEBACK, not `str(e)`. Both the exception
        # type and the raising frame must be present, or we are back to a bare
        # message that cannot say where the delete failed.
        self.assertIn("RuntimeError", joined)
        self.assertIn("probe delete failed", joined)
        self.assertIn("test_rest_migration_payments.py", joined)

    def test_like_escape_neutralises_wildcards(self):
        """`_` and `%` are LIKE wildcards. ERPNext's own `_Test Company` has abbr
        `_TC`, and unescaped `%- _TC` also matches `Debtors - XTC`."""
        self.assertEqual(_like_escape("_TC"), "\\_TC")
        self.assertEqual(_like_escape("50%"), "50\\%")
        self.assertEqual(_like_escape("a\\b"), "a\\\\b")

    def test_escaped_abbr_still_matches_its_own_accounts(self):
        """Control for the escaping: neutralising the wildcard must not break the
        legitimate literal match."""
        rows = _probe_residue("TEST-EB-Probe-Does-Not-Exist-zzzzzz", "_TC")["Account"]
        if not rows:
            self.skipTest("no `- _TC` account on this site")
        for name in rows:
            self.assertTrue(name.endswith("- _TC"), f"{name} matched but does not end in '- _TC'")
