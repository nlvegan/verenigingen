"""
Real integration tests for the ORCHESTRATION dispatcher
``_process_mutation_with_coordinator`` in
``verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py``.

This function routes a single eBoekhouden mutation through a "coordinator" (the
new processors) and falls back to the legacy ``_process_single_mutation`` path
when the coordinator returns nothing / raises / is absent. Its return value is a
dict with key ``action`` in {'success','failed','skip','error'}, plus
``method`` ('new_processors'|'legacy') on success, and
``is_stock_error``+``error_msg`` on error.

The ``coordinator`` is a plain FUNCTION PARAMETER, so we exercise each branch by
passing a small local test-double class instance directly as the argument. That
is NOT mocking/patching -- it is a legitimate collaborator double.

Branches covered:
  1. coordinator returns a doc            -> success / new_processors
  2. coordinator returns None + skip hint -> skip
  3. coordinator returns None, no hint    -> legacy fallback succeeds (legacy)
  4. coordinator.process_mutation RAISES  -> legacy fallback succeeds (legacy)
  5. coordinator is None (param)          -> legacy succeeds (legacy)
  6. coordinator None + not-imported id   -> error (real iterator ctor raises,
                                             no api_token in tests) -> action=error

For the legacy-success branches (3-5) we pre-create a REAL submitted Journal
Entry whose ``eboekhouden_mutation_nr`` equals the mutation id, so the legacy
``_process_single_mutation`` hits its already-imported early-return and returns
that JE BEFORE any API call.

The 'failed' action (legacy returns None without raising) is effectively
unreachable honestly, and the stock-error classification branch cannot be
triggered without a live stock-account error, so both are intentionally skipped.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_orchestration_dispatch
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _process_mutation_with_coordinator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import connection_lost

ITERATOR_TARGET = "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"

ABBR = "EBCO"
COMPANY = "TEST-EB-Coord-Company"

# Prefixed with a suite-specific "96" so these ledger IDs cannot collide with
# any other e_boekhouden test suite's own company -- see the matching note in
# test_rest_orchestration_start.py (#894): this file and that one were sharing
# the bare "8100"/"4100"/"1310"/"1610" literals against the global (no
# company field) E-Boekhouden Ledger Mapping doctype, so whichever suite's
# setUpClass ran first in a shard silently won the mapping for the other.
INCOME_LEDGER = "9608100"
EXPENSE_LEDGER = "9604100"
RECEIVABLE_LEDGER = "9601310"
PAYABLE_LEDGER = "9601610"


class _FakeDoc:
    """Minimal stand-in for a created document.

    ``_process_mutation_with_coordinator`` only reads ``.doctype`` and ``.name``
    off the returned doc (to build a debug string), so this is sufficient.
    """

    def __init__(self, doctype="Journal Entry", name="FAKE-DOC-0001"):
        self.doctype = doctype
        self.name = name


class _FakeCoordinator:
    """Test-double for the new-processors coordinator.

    Passed directly as the ``coordinator`` argument (a plain function param), so
    no patching is involved. Configurable to return a doc, return None, or raise.
    """

    def __init__(self, *, returns=None, raises=None, debug_info=None):
        self._returns = returns
        self._raises = raises
        self.last_processor_debug_info = debug_info if debug_info is not None else []

    def process_mutation(self, mutation):
        if self._raises is not None:
            raise self._raises
        return self._returns


class _RaisingIterator:
    """Stub for EBoekhoudenRESTIterator that CONSTRUCTS cleanly but raises a
    uniquely-tagged error from ``fetch_mutation_detail``.

    Used to drive the legacy path into its outer ``except`` deterministically:
    the tagged message lets the test assert WHICH error fired, instead of relying
    on the incidental ``EBoekhoudenRESTIterator()`` missing-token ctor failure
    (which is coupled to ambient site/token state and would classify any stray
    exception identically).
    """

    TAG = "INDUCED-NONSTOCK-ERR-DISPATCH"

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        raise RuntimeError(self.TAG)


class _ConnectionLostIterator:
    """Stub for EBoekhoudenRESTIterator that constructs cleanly but raises a
    connection-lost error (2006) from ``fetch_mutation_detail``, simulating a
    real driver-level connection loss surfacing from the legacy detail-fetch
    call (#731)."""

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        raise connection_lost()


class _CoordClusterBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, ledger mappings, cost center, FY.

    Mirrors _PartyClusterBase from test_rest_party_dispatch but is self-contained
    under a distinct company so the suites do not collide.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
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
        r.account_name = f"EBC {root_type} Root"
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
        cls.receivable = cls._make_account("EBC Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBC Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EBC Sales Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBC Expenses", "Expense Account", "Expense")
        cls.bank = cls._make_account("EBC Bank", "Bank", "Asset")

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
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBC Sales Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBC Expenses")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBC Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBC Creditors")

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
            fy_name = f"EBC-FY-{year}"
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

    # ---- per-test data helpers ----

    def _make_imported_je(self, mutation_nr):
        """Create a REAL submitted JE tagged with the mutation nr so the legacy
        path's already-imported early-return returns it before any API call."""
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


class TestProcessMutationWithCoordinator(_CoordClusterBase):
    """Branch coverage for the orchestration dispatcher."""

    # ---- 1. coordinator returns a doc -> success / new_processors ----

    def test_coordinator_returns_doc_success_new_processors(self):
        mutation_id = 970001
        coordinator = _FakeCoordinator(
            returns=_FakeDoc(doctype="Journal Entry", name="JE-NEW-970001"),
            debug_info=["new processor handled it"],
        )
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 7, "description": "via new processors"},
            mutation_id,
            7,
            coordinator,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result, {"action": "success", "method": "new_processors"})
        # The coordinator's debug info must have been folded into the running log.
        self.assertIn("new processor handled it", debug_info)

    # ---- 2. coordinator returns None + skip hint -> skip ----

    def test_coordinator_legitimate_skip(self):
        mutation_id = 970002
        coordinator = _FakeCoordinator(
            returns=None,
            debug_info=["Skipping payment gateway adjustment for this mutation"],
        )
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 5, "description": "gateway adj"},
            mutation_id,
            5,
            coordinator,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result, {"action": "skip"})

    def test_coordinator_skip_uppercase_indicator(self):
        """The bare 'SKIPPING' token is also a legitimate-skip indicator."""
        mutation_id = 970003
        coordinator = _FakeCoordinator(
            returns=None,
            debug_info=["processor decided: SKIPPING duplicate"],
        )
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 5, "description": "dup"},
            mutation_id,
            5,
            coordinator,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result, {"action": "skip"})

    # ---- 3. coordinator returns None, no hint -> legacy fallback succeeds ----

    def test_coordinator_none_no_hint_falls_back_to_legacy(self):
        mutation_id = 970010
        self._make_imported_je(mutation_id)
        coordinator = _FakeCoordinator(
            returns=None,
            debug_info=["processor could not determine handler, deferring"],
        )
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 7, "description": "fallback to legacy"},
            mutation_id,
            7,
            coordinator,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result["action"], "success")
        self.assertEqual(result["method"], "legacy")
        # Bonus: the "returned None" diagnostic Error Log should have been created.
        error_log = frappe.db.exists(
            "Error Log",
            {"error": ["like", f"%Mutation ID: {mutation_id}%"]},
        )
        self.assertTrue(
            error_log,
            "Expected a 'New Processor Returned None' Error Log for the no-hint fallback",
        )

    # ---- 4. coordinator.process_mutation RAISES -> legacy fallback succeeds ----

    def test_coordinator_raises_falls_back_to_legacy(self):
        mutation_id = 970011
        self._make_imported_je(mutation_id)
        coordinator = _FakeCoordinator(
            raises=RuntimeError("processor blew up"),
            debug_info=["partial work before failure"],
        )
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 7, "description": "raise then legacy"},
            mutation_id,
            7,
            coordinator,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result["action"], "success")
        self.assertEqual(result["method"], "legacy")
        # The exception message must be recorded in the running debug log.
        self.assertTrue(
            any("processor blew up" in line for line in debug_info),
            "Expected the coordinator exception text in debug_info",
        )

    # ---- 5. coordinator is None (param) -> legacy succeeds ----

    def test_coordinator_none_param_uses_legacy(self):
        mutation_id = 970012
        self._make_imported_je(mutation_id)
        debug_info = []
        result = _process_mutation_with_coordinator(
            {"id": mutation_id, "type": 7, "description": "no coordinator"},
            mutation_id,
            7,
            None,
            COMPANY,
            self.cost_center,
            debug_info,
        )
        self.assertEqual(result["action"], "success")
        self.assertEqual(result["method"], "legacy")

    # ---- 6. error branch (non-stock) ----

    def test_error_branch_non_stock(self):
        """A not-yet-imported mutation with no coordinator falls to the legacy
        path; the (patched) iterator raises a uniquely-tagged error from
        fetch_mutation_detail, so the outer except returns a non-stock error
        dict. Asserting the tag pins the branch to a cause this test owns, rather
        than relying on the incidental missing-token ctor failure (decoupled from
        ambient site/token state)."""
        mutation_id = 970099  # deliberately NOT pre-imported
        debug_info = []
        with patch(ITERATOR_TARGET, new=_RaisingIterator()):
            result = _process_mutation_with_coordinator(
                {"id": mutation_id, "type": 7, "description": "legacy detail-fetch raises tagged error"},
                mutation_id,
                7,
                None,
                COMPANY,
                self.cost_center,
                debug_info,
            )
        self.assertEqual(result["action"], "error")
        self.assertIs(result["is_stock_error"], False)
        self.assertTrue(
            result["error_msg"].startswith("Error processing mutation"),
            f"Unexpected error_msg: {result['error_msg']!r}",
        )
        # The error must be the one WE induced, not a stray failure.
        self.assertIn(_RaisingIterator.TAG, result["error_msg"])

    # ---- #731: a lost connection must propagate, not fold into an "error" result ----

    def test_coordinator_raises_connection_lost_propagates(self):
        """A connection-lost error from coordinator.process_mutation() must
        propagate (aborting the mutation), not be treated as an ordinary
        "new processor failed, fall back to legacy" case: falling back would run
        the legacy path against a connection the server may have silently
        replaced mid-transaction (#731, mirrors #572's deadlock/timeout guard).

        CAVEAT: this exercises the GUARD via a test double that raises, not the
        real collaborator. The REAL TransactionCoordinator.process_mutation
        (verenigingen/e_boekhouden/utils/processors/transaction_coordinator.py,
        ~line 176) has its own bare `except Exception` that already swallows
        everything -- 1213/2006 included -- into a logged Error Log row and
        `return None`, which this module's caller then reads as "fall back to
        legacy" rather than ever seeing an exception here. That swallow is a
        separate, already-baselined finding (scripts/validation/
        error_swallow_baseline.txt) and out of scope for this fix -- this test
        only proves the guard added here works FOR AN EXCEPTION THAT REACHES
        IT, which on the current default (`eboekhouden_use_new_processors`
        True) production path it structurally cannot: the coordinator's own
        swallow intercepts it first.
        """
        mutation_id = 970098
        coordinator = _FakeCoordinator(
            raises=connection_lost(),
            debug_info=["partial work before the connection was lost"],
        )
        debug_info = []
        with self.assertRaises(Exception) as ctx:
            _process_mutation_with_coordinator(
                {"id": mutation_id, "type": 7, "description": "connection lost mid new-processor"},
                mutation_id,
                7,
                coordinator,
                COMPANY,
                self.cost_center,
                debug_info,
            )
        self.assertIn("MySQL server has gone away", str(ctx.exception))
        # And it must NOT have fallen back to legacy processing.
        self.assertFalse(
            any("using legacy" in line for line in debug_info),
            f"must not have attempted legacy fallback, debug_info={debug_info}",
        )

    def test_legacy_raises_connection_lost_propagates(self):
        """A connection-lost error raised from the LEGACY path (no coordinator)
        must propagate out of the outer catch-all instead of being folded into
        an ordinary {"action": "error", ...} result (#731)."""
        mutation_id = 970097  # deliberately NOT pre-imported
        debug_info = []
        with patch(ITERATOR_TARGET, new=_ConnectionLostIterator()):
            with self.assertRaises(Exception) as ctx:
                _process_mutation_with_coordinator(
                    {"id": mutation_id, "type": 7, "description": "legacy detail-fetch loses connection"},
                    mutation_id,
                    7,
                    None,
                    COMPANY,
                    self.cost_center,
                    debug_info,
                )
        self.assertIn("MySQL server has gone away", str(ctx.exception))
