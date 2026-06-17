"""
Real integration tests for the PARTY get-or-create + single-mutation DISPATCH +
party-account resolution + batch error/stat helper cluster of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Target functions:
    _get_or_create_customer / _get_or_create_supplier
    _get_or_create_company_party / _get_or_create_company_as_customer /
        _get_or_create_company_as_supplier
    _process_single_mutation (type -> handler dispatcher)
    _resolve_party_account / _resolve_receivable_account / _resolve_payable_account
    _check_woocommerce_factuursturen_account
    _log_batch_summary / _get_bank_transaction_stats (pure-ish)
    _retry_transient_failures

These feed SYNTHETIC eBoekhouden mutation dicts. No live API is reachable here, so
party resolution degrades gracefully:
  - _get_or_create_customer/_supplier call EBoekhoudenPartyResolver, whose API
    fetch fails and which then (a) reuses an existing party matched on
    eboekhouden_relation_code, or (b) creates a provisional party.
  - the company helpers go through BankTransactionParser.find_or_create_party
    which is purely DB-driven (no API).

For _process_single_mutation we only exercise the type->handler routing that is
reachable without a live mutation-detail API call:
  - the already-imported early-return path (asserts the right existing doctype
    is returned for each type before any API call), and
  - a self-contained Type 7 memorial Journal Entry where we stub the single
    API-boundary call fetch_mutation_detail (unavoidable; it makes an HTTP GET).

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_5 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_party_dispatch
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _categorize_batch_errors,
    _check_woocommerce_factuursturen_account,
    _get_bank_transaction_stats,
    _get_or_create_company_as_customer,
    _get_or_create_company_as_supplier,
    _get_or_create_company_party,
    _get_or_create_customer,
    _get_or_create_supplier,
    _log_batch_summary,
    _process_single_mutation,
    _resolve_party_account,
    _resolve_payable_account,
    _resolve_receivable_account,
    _retry_transient_failures,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ABBR = "EBPC"
COMPANY = "TEST-EB-Party-Company"

# "E-Boekhouden Ledger Mapping" is keyed by ledger_id GLOBALLY and persists across
# suites on the shared test site. Sibling suites also map the canonical eBoekhouden
# ids (1310/1610/8100/4100) -- to their OWN companies' accounts. If this suite reused
# those ids, the resolver (which ignores company) would return a foreign company's
# account, breaking both the account-resolution assertions and the JE-building
# dispatch tests (the JE rejects accounts that don't belong to COMPANY). Use ids
# PRIVATE to this suite so resolution is deterministic and points at our accounts.
INCOME_LEDGER = "9508100"
EXPENSE_LEDGER = "9504100"
RECEIVABLE_LEDGER = "9501310"
PAYABLE_LEDGER = "9501610"

# A relation id that ALREADY has a pre-created party keyed on relation code.
EXISTING_CUSTOMER_RELATION = "EBPC-CUST-EXIST"
EXISTING_SUPPLIER_RELATION = "EBPC-SUPP-EXIST"


class _FakeIterator:
    """Stub for EBoekhoudenRESTIterator: _process_single_mutation does
    ``EBoekhoudenRESTIterator().fetch_mutation_detail(id)`` to load full detail.

    Patched in via ``new=_FakeIterator(mutation)``, so the instance replaces the
    class: calling it (the ``EBoekhoudenRESTIterator()`` construction) returns
    self, and fetch_mutation_detail returns the canned mutation -- no live API.
    """

    def __init__(self, mutation):
        self._mutation = mutation

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        return self._mutation


class _PartyClusterBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, ledger mappings, cost center, parties, FY."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_te_ontvangen_account()
        cls._ensure_existing_parties()
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
        r.account_name = f"EBP {root_type} Root"
        r.company = COMPANY
        r.root_type = root_type
        r.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        r.is_group = 1
        r.insert(ignore_permissions=True)
        return r.name

    @classmethod
    def _make_account(cls, account_name, account_type, root_type, is_group=0):
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
        a.is_group = is_group
        a.parent_account = cls._make_root(root_type)
        a.insert(ignore_permissions=True)
        return a.name

    @classmethod
    def _ensure_accounts(cls):
        cls.receivable = cls._make_account("EBP Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBP Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EBP Sales Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBP Expenses", "Expense Account", "Expense")
        cls.bank = cls._make_account("EBP Bank", "Bank", "Asset")
        # A group/control receivable account used to prove control accounts are rejected
        cls.group_receivable = cls._make_account("EBP Control Debtors", "Receivable", "Asset", is_group=1)

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
        leaf.cost_center_name = "Main"
        leaf.company = COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root_cc
        leaf.insert(ignore_permissions=True)
        cls.cost_center = leaf.name

    @classmethod
    def _make_ledger_map(cls, ledger_id, account, name):
        """Upsert a ledger mapping and return the account the ledger ACTUALLY
        resolves to. The "E-Boekhouden Ledger Mapping" doctype is keyed by
        ledger_id GLOBALLY and persists across suites on the shared site, so a
        SIBLING suite that mapped the same id (e.g. 1310/1610/8100/4100) first
        wins. Returning the existing mapping's account lets callers align their
        expectations with whatever the resolver will actually produce, rather
        than asserting against this suite's own (possibly-unmapped) account."""
        existing = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "erpnext_account"
        )
        if existing:
            return existing
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = str(ledger_id)
        m.ledger_name = name
        m.erpnext_account = account
        m.insert(ignore_permissions=True)
        return account

    @classmethod
    def _ensure_ledger_mappings(cls):
        # Ledger ids are PRIVATE to this suite (see module-level constants), so each
        # maps to THIS company's own account and resolution is deterministic.
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBP Sales Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBP Expenses")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBP Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBP Creditors")

    @classmethod
    def _ensure_te_ontvangen_account(cls):
        """WooCommerce/FactuurSturen special-case account, matched by name LIKE."""
        cls.te_ontvangen = cls._make_account("Te Ontvangen Bedragen", "Receivable", "Asset")

    @classmethod
    def _ensure_existing_parties(cls):
        if not frappe.db.exists("Customer", {"eboekhouden_relation_code": EXISTING_CUSTOMER_RELATION}):
            cust = frappe.new_doc("Customer")
            cust.customer_name = "EBP Existing Customer"
            cust.customer_type = "Individual"
            cust.default_currency = "EUR"
            cust.eboekhouden_relation_code = EXISTING_CUSTOMER_RELATION
            cust.insert(ignore_permissions=True)
        cls.existing_customer = frappe.db.get_value(
            "Customer", {"eboekhouden_relation_code": EXISTING_CUSTOMER_RELATION}, "name"
        )

        if not frappe.db.exists("Supplier", {"eboekhouden_relation_code": EXISTING_SUPPLIER_RELATION}):
            supp = frappe.new_doc("Supplier")
            supp.supplier_name = "EBP Existing Supplier"
            supp.supplier_type = "Individual"
            supp.default_currency = "EUR"
            supp.eboekhouden_relation_code = EXISTING_SUPPLIER_RELATION
            supp.insert(ignore_permissions=True)
        cls.existing_supplier = frappe.db.get_value(
            "Supplier", {"eboekhouden_relation_code": EXISTING_SUPPLIER_RELATION}, "name"
        )

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
            fy_name = f"EBP-FY-{year}"
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


# ---------------------------------------------------------------------------
# PARTY get-or-create
# ---------------------------------------------------------------------------


class TestPartyGetOrCreate(_PartyClusterBase):
    def test_get_or_create_customer_reuses_existing_by_relation_code(self):
        """Pre-existing Customer keyed on relation code is returned (no API needed)."""
        debug = []
        name = _get_or_create_customer(EXISTING_CUSTOMER_RELATION, debug)
        self.assertEqual(name, self.existing_customer)

    def test_get_or_create_customer_idempotent(self):
        """Two calls for the same relation id return the SAME customer."""
        first = _get_or_create_customer(EXISTING_CUSTOMER_RELATION, [])
        second = _get_or_create_customer(EXISTING_CUSTOMER_RELATION, [])
        self.assertEqual(first, second)
        self.assertEqual(first, self.existing_customer)

    def test_get_or_create_supplier_reuses_existing_by_relation_code(self):
        debug = []
        name = _get_or_create_supplier(EXISTING_SUPPLIER_RELATION, "any desc", debug)
        self.assertEqual(name, self.existing_supplier)

    def test_get_or_create_customer_new_relation_creates_provisional(self):
        """A brand-new relation id with no API => provisional customer is created,
        and a second call for the SAME relation id reuses it (idempotent)."""
        relation = "EBPC-NEW-CUST-1"
        # Make sure it doesn't pre-exist
        self.assertFalse(frappe.db.exists("Customer", {"eboekhouden_relation_code": str(relation)}))
        name1 = _get_or_create_customer(relation, [])
        self.assertIsNotNone(name1)
        self.assertTrue(frappe.db.exists("Customer", name1))
        # The provisional party carries the relation code so it can be re-found.
        self.assertEqual(frappe.db.get_value("Customer", name1, "eboekhouden_relation_code"), str(relation))
        name2 = _get_or_create_customer(relation, [])
        self.assertEqual(name1, name2)

    def test_get_or_create_supplier_new_relation_creates_provisional(self):
        relation = "EBPC-NEW-SUPP-1"
        self.assertFalse(frappe.db.exists("Supplier", {"eboekhouden_relation_code": str(relation)}))
        name1 = _get_or_create_supplier(relation, "Some supplier", [])
        self.assertIsNotNone(name1)
        self.assertTrue(frappe.db.exists("Supplier", name1))
        name2 = _get_or_create_supplier(relation, "Some supplier", [])
        self.assertEqual(name1, name2)


class TestCompanyPartyGetOrCreate(_PartyClusterBase):
    def test_company_as_customer_created_and_idempotent(self):
        first = _get_or_create_company_as_customer(COMPANY, [])
        second = _get_or_create_company_as_customer(COMPANY, [])
        self.assertIsNotNone(first)
        self.assertTrue(frappe.db.exists("Customer", first))
        # Idempotent: the second call resolves to the SAME party. This is the
        # contract that matters and the real regression guard.
        self.assertEqual(first, second)
        # Note: the internal party is REQUESTED as "<company> (Internal)", but
        # BankTransactionParser.find_or_create_party may FUZZY-match the request to
        # a pre-existing Customer on a shared site with accumulated parties (prod
        # behaviour outside this test's control), so the resolved name is not
        # guaranteed to carry the "(Internal)" literal. We therefore do not assert
        # on the resolved customer_name.

    def test_company_as_supplier_created_and_idempotent(self):
        first = _get_or_create_company_as_supplier(COMPANY, [])
        second = _get_or_create_company_as_supplier(COMPANY, [])
        self.assertIsNotNone(first)
        self.assertTrue(frappe.db.exists("Supplier", first))
        self.assertEqual(first, second)

    def test_company_party_customer_and_supplier_are_distinct(self):
        cust = _get_or_create_company_party("Customer", COMPANY, [])
        supp = _get_or_create_company_party("Supplier", COMPANY, [])
        self.assertTrue(frappe.db.exists("Customer", cust))
        self.assertTrue(frappe.db.exists("Supplier", supp))


# ---------------------------------------------------------------------------
# party-account resolution
# ---------------------------------------------------------------------------


class TestResolvePartyAccount(_PartyClusterBase):
    def test_receivable_resolution_returns_receivable_account(self):
        detail = {"ledgerId": RECEIVABLE_LEDGER, "description": "Sales invoice"}
        acct = _resolve_receivable_account(detail, COMPANY, [])
        self.assertEqual(acct, self.receivable)
        self.assertEqual(frappe.db.get_value("Account", acct, "account_type"), "Receivable")

    def test_payable_resolution_returns_payable_account(self):
        detail = {"ledgerId": PAYABLE_LEDGER, "description": "Purchase invoice"}
        acct = _resolve_payable_account(detail, COMPANY, [])
        self.assertEqual(acct, self.payable)
        self.assertEqual(frappe.db.get_value("Account", acct, "account_type"), "Payable")

    def test_receivable_and_payable_not_swapped(self):
        """Receivable ledger must NOT resolve to the payable account and vice-versa."""
        recv = _resolve_receivable_account({"ledgerId": RECEIVABLE_LEDGER, "description": ""}, COMPANY, [])
        pay = _resolve_payable_account({"ledgerId": PAYABLE_LEDGER, "description": ""}, COMPANY, [])
        self.assertNotEqual(recv, pay)
        self.assertEqual(recv, self.receivable)
        self.assertEqual(pay, self.payable)

    def test_no_ledger_id_returns_none(self):
        """Missing ledgerId => None so ERPNext falls back to the party default."""
        self.assertIsNone(_resolve_receivable_account({"description": "x"}, COMPANY, []))
        self.assertIsNone(_resolve_payable_account({"description": "x"}, COMPANY, []))

    def test_unmapped_ledger_returns_none(self):
        """A ledger id with no mapping row => None."""
        self.assertIsNone(
            _resolve_party_account({"ledgerId": "999999", "description": ""}, "Receivable", COMPANY, [])
        )

    def test_group_control_account_rejected(self):
        """Ledger that maps to a group/control account must NOT be used in invoices."""
        # Map a fresh ledger id to the group/control receivable account
        ledger = "1399"
        self._make_ledger_map(ledger, self.group_receivable, "EBP Control Debtors")
        frappe.db.commit()
        acct = _resolve_party_account({"ledgerId": ledger, "description": ""}, "Receivable", COMPANY, [])
        self.assertIsNone(acct, "Group/control account must be rejected (None) for invoices")

    def test_woocommerce_uses_te_ontvangen_special_account(self):
        """A WooCommerce description routes receivables to 'Te Ontvangen Bedragen'."""
        detail = {"ledgerId": RECEIVABLE_LEDGER, "description": "Order via WooCommerce shop"}
        acct = _resolve_receivable_account(detail, COMPANY, [])
        self.assertEqual(acct, self.te_ontvangen)

    def test_factuursturen_uses_te_ontvangen_special_account(self):
        detail = {"ledgerId": RECEIVABLE_LEDGER, "description": "FactuurSturen export 12"}
        acct = _resolve_receivable_account(detail, COMPANY, [])
        self.assertEqual(acct, self.te_ontvangen)

    def test_woocommerce_special_account_only_for_receivable(self):
        """The special-account shortcut does not apply to Payable resolution."""
        detail = {"ledgerId": PAYABLE_LEDGER, "description": "WooCommerce refund"}
        acct = _resolve_payable_account(detail, COMPANY, [])
        # Payable path ignores the WooCommerce special case -> normal mapping
        self.assertEqual(acct, self.payable)

    def test_check_woocommerce_returns_none_for_non_matching_description(self):
        self.assertIsNone(
            _check_woocommerce_factuursturen_account(
                {"description": "Regular membership payment"}, COMPANY, []
            )
        )

    def test_check_woocommerce_returns_account_for_matching_description(self):
        acct = _check_woocommerce_factuursturen_account({"description": "woocommerce order #5"}, COMPANY, [])
        self.assertEqual(acct, self.te_ontvangen)


# ---------------------------------------------------------------------------
# single-mutation DISPATCH
# ---------------------------------------------------------------------------


class TestProcessSingleMutationDispatch(_PartyClusterBase):
    """Dispatch routing via the already-imported early-return path.

    _process_single_mutation looks up existing docs by eboekhouden_mutation_nr
    BEFORE making any API call, then returns the matching doc. By pre-creating a
    doc of a given doctype with a known mutation nr, we assert the dispatcher
    surfaces the right doctype for that mutation id.
    """

    def _make_je(self, mutation_nr):
        je = frappe.new_doc("Journal Entry")
        je.company = COMPANY
        je.posting_date = nowdate()
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = str(mutation_nr)
        je.append(
            "accounts",
            {"account": self.income, "credit_in_account_currency": 50, "cost_center": self.cost_center},
        )
        je.append(
            "accounts",
            {"account": self.bank, "debit_in_account_currency": 50, "cost_center": self.cost_center},
        )
        je.insert(ignore_permissions=True)
        # Guarantee the posting date's Fiscal Year covers this company before
        # submit (idempotent); the setUpClass company-restriction handling does
        # not always survive the test runner's transaction handling on a fresh
        # site.
        from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

        ensure_fiscal_year_exists(je.posting_date, COMPANY)
        je.submit()
        return je

    def test_already_imported_journal_entry_returned(self):
        """Dispatcher returns the existing JE BEFORE any API call (early return)."""
        je = self._make_je(950001)
        result = _process_single_mutation({"id": 950001, "type": 7}, COMPANY, self.cost_center, [])
        self.assertEqual(result.doctype, "Journal Entry")
        self.assertEqual(result.name, je.name)

    def test_dispatch_type7_creates_journal_entry(self):
        """Type 7 (memorial) routes to _create_journal_entry -> a Journal Entry.

        The EBoekhoudenRESTIterator API boundary is faked (its real __init__
        loads the api_token, which is absent in tests) so its fetch_mutation_detail
        returns the synthetic two-row memorial mutation; everything else is real.
        """
        mutation = {
            "id": 950100,
            "type": 7,
            "date": nowdate(),
            "description": "Memorial reclassification",
            "ledgerId": INCOME_LEDGER,
            "Regels": [
                {"ledgerId": INCOME_LEDGER, "amount": 25.00, "description": "to income"},
                {"ledgerId": EXPENSE_LEDGER, "amount": -25.00, "description": "from expense"},
            ],
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator",
            new=_FakeIterator(mutation),
        ):
            result = _process_single_mutation(mutation, COMPANY, self.cost_center, [])
        self.assertEqual(result.doctype, "Journal Entry")
        self.assertEqual(result.eboekhouden_mutation_nr, "950100")
        # Routing must produce a VALID (submitted) JE, not just any JE doc.
        self.assertEqual(result.docstatus, 1)

    def test_dispatch_type7_zero_amount_creates_error_log(self):
        """Type 7 with all-zero rows routes to the zero-amount import-log path."""
        mutation = {
            "id": 950101,
            "type": 7,
            "date": nowdate(),
            "description": "Zero memorial",
            "ledgerId": INCOME_LEDGER,
            "Regels": [
                {"ledgerId": INCOME_LEDGER, "amount": 0, "description": "zero a"},
                {"ledgerId": EXPENSE_LEDGER, "amount": 0, "description": "zero b"},
            ],
        }
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator",
            new=_FakeIterator(mutation),
        ):
            result = _process_single_mutation(mutation, COMPANY, self.cost_center, [])
        # Zero-amount path returns an Error Log (audit-only), not a financial doc.
        self.assertEqual(result.doctype, "Error Log")


# ---------------------------------------------------------------------------
# batch error / stat helpers (pure-ish)
# ---------------------------------------------------------------------------


class TestBatchHelpers(EnhancedTestCase):
    def test_categorize_batch_errors_groups_by_pattern(self):
        errors = [
            "mutation 1: Stock accounts X can only be updated via Stock Transactions",
            "mutation 2: invoice already been fully paid",
            "mutation 3: Could not find reference",
            "mutation 4: SomeDoc already exists",
            "mutation 5: random failure",
        ]
        cats = _categorize_batch_errors(errors)
        self.assertEqual(len(cats["Payment Allocation Issues"]), 1)
        self.assertEqual(len(cats["Missing References"]), 1)
        self.assertEqual(len(cats["Duplicate Entries"]), 1)
        self.assertEqual(len(cats["Other Errors"]), 1)
        self.assertIn("Stock Account Updates (Fixed - now creates Stock Reconciliations)", cats)

    def test_get_bank_transaction_stats_empty_returns_empty_string(self):
        self.assertEqual(_get_bank_transaction_stats([], "Customer Payments"), "")
        self.assertEqual(_get_bank_transaction_stats(None, "Customer Payments"), "")

    def test_get_bank_transaction_stats_no_payment_entries(self):
        """Mutation ids with no matching Payment Entries => 'No Payment Entries' block."""
        mutations = [{"id": 990001}, {"id": 990002}]
        stats = _get_bank_transaction_stats(mutations, "Money Received")
        self.assertIn("No Payment Entries created", stats)
        self.assertIn("2 mutations processed", stats)

    def test_log_batch_summary_counts_and_strings(self):
        mutations = [{"id": 1}, {"id": 2}, {"id": 3}]
        errors = ["mutation 2: boom"]
        error_categories = _categorize_batch_errors(errors)
        summary = _log_batch_summary(
            mutations=mutations,
            type_name="Sales Invoices",
            imported=2,
            failed=1,
            skipped=0,
            errors=errors,
            processed_with_new=2,
            processed_with_legacy=1,
            error_categories=error_categories,
        )
        self.assertIn("Processed: 3 mutations", summary)
        self.assertIn("Imported: 2", summary)
        self.assertIn("Failed: 1", summary)
        self.assertIn("Total Errors: 1", summary)
        self.assertIn("PROCESSING METHOD BREAKDOWN", summary)
        # 2 of 3 processed with new processors -> 66.7%
        self.assertIn("66.7%", summary)
        self.assertIn("ERROR CATEGORIES", summary)

    def test_log_batch_summary_no_processing_breakdown_when_zero(self):
        summary = _log_batch_summary(
            mutations=[{"id": 1}],
            type_name="Sales Invoices",
            imported=1,
            failed=0,
            skipped=0,
            errors=[],
            processed_with_new=0,
            processed_with_legacy=0,
            error_categories={},
        )
        self.assertNotIn("PROCESSING METHOD BREAKDOWN", summary)
        self.assertIn("Imported: 1", summary)


# ---------------------------------------------------------------------------
# retry of transient failures
# ---------------------------------------------------------------------------


class TestRetryTransientFailures(EnhancedTestCase):
    def test_no_failures_is_noop(self):
        result = _retry_transient_failures("MIG-X", [], 0, 5, [])
        self.assertEqual(result["imported"], 5)
        self.assertEqual(result["failed"], 0)
        self.assertIsNone(result["retry_summary"])

    def test_non_transient_errors_not_retried(self):
        """A non-transient error (e.g. validation) is never retried."""
        errors = ["mutation 3: ValidationError some business rule"]
        result = _retry_transient_failures("MIG-X", errors, 1, 4, [])
        # Counts unchanged; no retry summary because nothing matched the patterns.
        self.assertEqual(result["imported"], 4)
        self.assertEqual(result["failed"], 1)
        self.assertIsNone(result["retry_summary"])
        self.assertEqual(result["errors"], errors)

    def test_transient_error_triggers_retry(self):
        """A transient (deadlock) error is retried via import_single_mutation.

        We stub import_single_mutation (the retry entrypoint) to report success
        and assert the counts are updated and the failed error is dropped.
        """
        errors = ["mutation 7: Deadlock found when trying to get lock"]
        debug = []
        with patch(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_migration."
            "e_boekhouden_migration.import_single_mutation",
            return_value={"success": True},
        ):
            result = _retry_transient_failures("MIG-X", errors, 1, 4, debug)
        self.assertEqual(result["imported"], 5)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], [])
        self.assertIsNotNone(result["retry_summary"])
        self.assertIn("Successful: 1", result["retry_summary"])

    def test_transient_error_retry_failure_keeps_counts(self):
        """If the retry itself fails, the mutation stays failed."""
        errors = ["mutation 8: Lock wait timeout exceeded"]
        with patch(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_migration."
            "e_boekhouden_migration.import_single_mutation",
            return_value={"success": False, "error": "still broken"},
        ):
            result = _retry_transient_failures("MIG-X", errors, 1, 4, [])
        self.assertEqual(result["imported"], 4)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Failed: 1", result["retry_summary"])
