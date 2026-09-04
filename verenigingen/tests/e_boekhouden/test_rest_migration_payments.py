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
from verenigingen.tests.harness_logger import get_harness_logger

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
    and commit it. Named ``_create_*`` -- a privileged fixture-building helper,
    like this file's other ``_ensure_``/``_make_``/``_persist_`` builders --
    rather than inlined in the test body, for two reasons:

    1. The commit is load-bearing, not incidental: without it, the drain's own
       pre-delete ``frappe.db.rollback()`` would destroy this uncommitted row
       before the delete loop ever runs, passing the test for the wrong reason
       (any uncommitted fixture vanishes on rollback, protected or not -- that
       proves nothing about the captured-insert drain this test is about).
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
        try:
            if frappe.db.exists("Company", self.temp_company_name):
                frappe.delete_doc(
                    "Company", self.temp_company_name, force=True, ignore_permissions=True
                )
                frappe.db.commit()
        except Exception as e:
            get_harness_logger("test_rest_migration_payments").error(
                f"tearDown could not delete probe company {self.temp_company_name}: {e}"
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
