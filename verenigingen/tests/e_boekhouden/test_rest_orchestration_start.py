"""
Real integration tests for the top-level REST migration ORCHESTRATOR
``start_full_rest_import(migration_name, mutation_types=None)`` of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py.

This function is the entrypoint that the E-Boekhouden Migration form calls. It:
  - loads the E-Boekhouden Migration doc + E-Boekhouden Settings single,
  - errors out when no api_token / company is configured,
  - normalizes the ``mutation_types`` argument (None -> [1..7]; non-list ->
    default; custom list -> filtered to 0..10, de-duped, sorted),
  - constructs an EBoekhoudenRESTIterator and, per type, fetches mutations,
    optionally date-filters them (type 0 is exempt), routes type 0 to
    ``_import_opening_balances`` and everything else to
    ``_import_rest_mutations_batch_enhanced``,
  - aggregates totals, writes progress fields on the migration doc, and returns
    ``{"success": True, "stats": {...}}`` (or ``{"success": False, "error": ...}``).

The ONLY seam is the REST iterator: its real ``__init__`` performs a live API
auth/fetch which is unreachable in tests. We patch the iterator CLASS with a
fake whose ``fetch_mutations_by_type`` returns per-type canned lists WE control
and which RECORDS the types it was asked for (so we can assert which types ran).
Everything downstream (mutation processing, JE creation, the migration doc
writes) is REAL DB. No ``process_``/``validate_``/``business_rule`` target is
patched, nor any frappe.get_doc/get_all/new_doc/db.* call.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_3 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_orchestration_start
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    start_full_rest_import,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ABBR = "EBST"
COMPANY = "TEST-EB-Start-Company"

INCOME_LEDGER = "8100"
EXPENSE_LEDGER = "4100"
RECEIVABLE_LEDGER = "1310"
PAYABLE_LEDGER = "1610"

ITERATOR_TARGET = "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"


class _FakeIterator:
    """Stand-in for EBoekhoudenRESTIterator.

    ``start_full_rest_import`` does ``EBoekhoudenRESTIterator()`` then calls
    ``fetch_mutations_by_type(mutation_type=..., limit=...)`` for each type, and
    legacy detail processing may call ``fetch_mutation_detail(id)``. We patch the
    class with ``new=_FakeIterator(...)`` so the instance replaces the class:
    calling it (the construction) returns self.

    ``per_type`` maps a mutation-type int -> the list it should return.
    ``raise_for`` is an optional set of types for which fetch should RAISE (to
    exercise the per-type exception capture path). ``requested_types`` records
    every type the orchestrator asked for, in order.
    """

    def __init__(self, per_type=None, raise_for=None):
        self._per_type = per_type or {}
        self._raise_for = set(raise_for or ())
        self.requested_types = []

    def __call__(self):
        return self

    def fetch_mutations_by_type(self, mutation_type, limit=500):
        self.requested_types.append(mutation_type)
        if mutation_type in self._raise_for:
            raise RuntimeError(f"boom fetching type {mutation_type}")
        return list(self._per_type.get(mutation_type, []))

    def fetch_mutation_detail(self, mutation_id):
        # Legacy processing path may load full detail; return the matching inline
        # mutation from whatever per-type list contains this id.
        for muts in self._per_type.values():
            for m in muts:
                if str(m.get("id")) == str(mutation_id):
                    return m
        return None


class _StartImportBase(EnhancedTestCase):
    """Shared bootstrap: company, accounts, ledger mappings, cost center, FY, and a
    real E-Boekhouden Migration doc. Also sets a real api_token + default_company on
    the E-Boekhouden Settings single (restored in tearDownClass)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_fiscal_year()
        cls._setup_settings()
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls._restore_settings()
        frappe.db.commit()
        super().tearDownClass()

    # ---- settings seam ----

    @classmethod
    def _setup_settings(cls):
        from frappe.utils.password import set_encrypted_password

        settings = frappe.get_single("E-Boekhouden Settings")
        cls._orig_company = settings.default_company
        # Preserve the original token so we can restore the live single afterwards.
        try:
            cls._orig_token = settings.get_password("api_token", raise_exception=False)
        except Exception:
            cls._orig_token = None
        settings.default_company = COMPANY
        settings.save(ignore_permissions=True)
        # Write the token directly to the Auth store (Password field; see _set_token).
        set_encrypted_password(
            "E-Boekhouden Settings", "E-Boekhouden Settings", "test-token-dummy", "api_token"
        )
        frappe.db.commit()

    @classmethod
    def _restore_settings(cls):
        from frappe.utils.password import set_encrypted_password

        settings = frappe.get_single("E-Boekhouden Settings")
        settings.default_company = cls._orig_company
        settings.save(ignore_permissions=True)
        set_encrypted_password(
            "E-Boekhouden Settings",
            "E-Boekhouden Settings",
            cls._orig_token or "",
            "api_token",
        )
        frappe.db.commit()

    def _set_token(self, value):
        """Flip the stored api_token password on the live single.

        ``api_token`` is a mandatory Password field, so we cannot ``save`` the
        single with an empty docfield (MandatoryError). Instead we write the
        encrypted password directly into the Auth store; ``get_single`` always
        loads the docfield as the dummy ``****`` placeholder, so ``get_password``
        falls through to the decrypted Auth value. An empty stored value makes
        the gate's ``get_password(...)`` return a falsy string WITHOUT raising
        (which a removed row would do), so the "REST API token not configured"
        branch is exercised exactly.
        """
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password("E-Boekhouden Settings", "E-Boekhouden Settings", value, "api_token")
        frappe.db.commit()

    # ---- migration doc ----

    def _make_migration(self, date_from=None, date_to=None, migrate_transactions=1):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = f"Start Import Test {frappe.generate_hash(length=6)}"
        doc.migration_status = "Draft"
        doc.company = COMPANY
        doc.migrate_transactions = migrate_transactions
        if date_from:
            doc.date_from = date_from
        if date_to:
            doc.date_to = date_to
        doc.insert(ignore_permissions=True)
        return doc

    # ---- company / accounts / mappings / FY bootstrap ----

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
        r.account_name = f"EBST {root_type} Root"
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
        cls.receivable = cls._make_account("EBST Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBST Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EBST Sales Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBST Expenses", "Expense Account", "Expense")
        cls.bank = cls._make_account("EBST Bank", "Bank", "Asset")

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
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBST Sales Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBST Expenses")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBST Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBST Creditors")

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
            fy_name = f"EBST-FY-{year}"
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

    # ---- shared mutation builder ----

    def _unique_mutation_id(self):
        """A mutation nr not yet present as a Journal Entry on this (persistent) site."""
        import random

        for _ in range(50):
            candidate = random.randint(970000, 9_999_999)
            if not frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(candidate)}):
                return candidate
        raise RuntimeError("could not find a free mutation id")

    def _type7_memorial(self, mutation_id, date=None):
        """A self-contained, balanced Type-7 memorial mutation that produces a JE."""
        return {
            "id": mutation_id,
            "type": 7,
            "date": date or nowdate(),
            "description": f"Memorial reclassification {mutation_id}",
            "ledgerId": INCOME_LEDGER,
            "Regels": [
                {"ledgerId": INCOME_LEDGER, "amount": 25.00, "description": "to income"},
                {"ledgerId": EXPENSE_LEDGER, "amount": -25.00, "description": "from expense"},
            ],
        }


# ---------------------------------------------------------------------------
# 1. no api_token -> structured error
# ---------------------------------------------------------------------------


class TestStartImportTokenGate(_StartImportBase):
    def test_missing_api_token_returns_error(self):
        """No REST token configured => structured error, no processing."""
        doc = self._make_migration()
        # Use a fake iterator so that, even if the gate failed to trigger, we would
        # NOT hit a live API. requested_types staying empty proves we short-circuited.
        fake = _FakeIterator(per_type={})
        try:
            self._set_token("")
            with patch(ITERATOR_TARGET, new=fake):
                result = start_full_rest_import(doc.name, mutation_types=[7])
        finally:
            # Restore so the other tests in the class still have a token.
            self._set_token("test-token-dummy")

        self.assertFalse(result["success"])
        self.assertIn("REST API token not configured", result["error"])
        # Gate is BEFORE the iterator loop -> nothing was fetched.
        self.assertEqual(fake.requested_types, [])


# ---------------------------------------------------------------------------
# 2. happy path: real type-7 processing creates a Journal Entry
# ---------------------------------------------------------------------------


class TestStartImportHappyPath(_StartImportBase):
    def test_type7_memorial_creates_journal_entry_and_updates_doc(self):
        """One balanced Type-7 memorial => a real submitted JE, stats reflect the
        import, and the migration doc's progress fields are persisted to 100%."""
        doc = self._make_migration()
        # The test site persists data across runs; a fixed mutation nr would be
        # skipped as "already imported". Use a unique nr that does not pre-exist.
        mutation_id = self._unique_mutation_id()
        fake = _FakeIterator(per_type={7: [self._type7_memorial(mutation_id)]})

        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=[7])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        # Exactly one mutation was fed -> exactly one import (==, not >=, so a
        # double-count regression cannot hide).
        self.assertEqual(result["stats"]["invoices_created"], 1)
        self.assertEqual(fake.requested_types, [7])

        # A REAL Journal Entry was created carrying the mutation nr.
        je_name = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}, "name")
        self.assertIsNotNone(je_name, "expected a Journal Entry for the type-7 mutation")
        self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 1)
        # Right economic content: the ±25.00 memorial posts 25.00 across the
        # mapped income/expense ledgers.
        self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "total_debit"), 25.0)
        # E-Boekhouden Ledger Mapping is keyed by ledger_id GLOBALLY and persists
        # across suites on the shared site, so the resolved accounts belong to
        # whichever suite first mapped 8100/4100. Assert the JE used exactly the
        # accounts those ledgers resolve to -- a regression posting to a wrong or
        # default account would fail this.
        accounts = set(frappe.get_all("Journal Entry Account", filters={"parent": je_name}, pluck="account"))
        expected_accounts = {
            frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": "8100"}, "erpnext_account"),
            frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": "4100"}, "erpnext_account"),
        }
        self.assertEqual(accounts, expected_accounts)

        # Migration doc progress persisted (db_set + commit inside the function).
        doc.reload()
        self.assertEqual(doc.progress_percentage, 100)
        self.assertEqual(doc.imported_records, 1)


# ---------------------------------------------------------------------------
# 3 & 4. mutation_types normalization
# ---------------------------------------------------------------------------


class TestStartImportTypeNormalization(_StartImportBase):
    def test_non_list_falls_back_to_default_types(self):
        """A non-list mutation_types argument => default [1..7].

        We set migrate_transactions=0 so the type-0 opening-balance auto-add
        (gated on is_full_import) does NOT fire; that keeps this assertion focused
        on the non-list normalization branch rather than the type-0 inclusion.
        """
        doc = self._make_migration(migrate_transactions=0)
        fake = _FakeIterator(per_type={})  # every type returns [] -> cheap
        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types="not-a-list")

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(fake.requested_types, [1, 2, 3, 4, 5, 6, 7])

    def test_custom_list_filtered_to_valid_range(self):
        """[7, 99, -1] => only the in-range type 7 is fetched (99 and -1 dropped)."""
        doc = self._make_migration()
        fake = _FakeIterator(per_type={})
        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=[7, 99, -1])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(fake.requested_types, [7])


# ---------------------------------------------------------------------------
# 5. date filtering excludes out-of-window mutations
# ---------------------------------------------------------------------------


class TestStartImportDateFiltering(_StartImportBase):
    def test_date_window_filters_out_of_window_keeps_in_window(self):
        """Of two type-7 mutations, only the one INSIDE [date_from, date_to] is
        processed; the out-of-window one is dropped before processing. The
        positive control (an in-window mutation that DOES import) proves the
        filter keeps the right rows, not that it drops everything."""
        doc = self._make_migration(date_from="2024-01-01", date_to="2024-01-31")
        out_id = self._unique_mutation_id()
        in_id = self._unique_mutation_id()
        out_of_window = self._type7_memorial(out_id, date="2023-06-15")  # before window
        in_window = self._type7_memorial(in_id, date="2024-01-15")  # inside window
        fake = _FakeIterator(per_type={7: [out_of_window, in_window]})

        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=[7])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        # Exactly the single in-window mutation imported.
        self.assertEqual(result["stats"]["invoices_created"], 1)
        self.assertEqual(fake.requested_types, [7])
        # The out-of-window mutation was dropped: no JE for it.
        self.assertFalse(frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(out_id)}))
        # The in-window mutation WAS imported: a submitted JE exists for it.
        in_je = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": str(in_id)}, "name")
        self.assertIsNotNone(in_je, "the in-window mutation should have produced a JE")
        self.assertEqual(frappe.db.get_value("Journal Entry", in_je, "docstatus"), 1)
        doc.reload()
        self.assertEqual(doc.imported_records, 1)


# ---------------------------------------------------------------------------
# 6. per-type fetch exception is captured; the loop continues
# ---------------------------------------------------------------------------


class TestStartImportPerTypeExceptionCaptured(_StartImportBase):
    def test_fetch_exception_for_one_type_does_not_abort_run(self):
        """If fetch_mutations_by_type RAISES for one type, that error is captured
        in stats['errors'] and the loop continues to the next type. Overall run
        still reports success."""
        doc = self._make_migration()
        # Type 2 raises; type 7 returns [] cleanly.
        fake = _FakeIterator(per_type={7: []}, raise_for={2})

        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=[2, 7])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        # Both types were attempted (loop continued past the raising one).
        self.assertEqual(sorted(fake.requested_types), [2, 7])
        joined = "\n".join(result["stats"]["errors"])
        self.assertIn("Error importing mutation type 2", joined)


# ---------------------------------------------------------------------------
# 7. type-0 opening-balance branch
# ---------------------------------------------------------------------------


class TestStartImportType0OpeningBalances(_StartImportBase):
    """The type-0 branch routes to _import_opening_balances (which fetches via
    EBoekhoudenAPI, NOT the iterator) and converts its result into the batch
    tally: success + journal_entry -> imported 1; success + no JE -> 0; failure
    -> failed len(iterator mutations). Type 0 is exempt from date filtering and
    is auto-prepended for a full import.

    The iterator's type-0 list only gates entry into the branch (and supplies
    len(mutations) for the failure count); the actual OB data comes from the
    EBoekhoudenAPI boundary, which we stub exactly like test_opening_balance_import.
    """

    OB_API_TARGET = "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI"

    def setUp(self):
        super().setUp()
        # start_full_rest_import COMMITS, so an OPENING_BALANCE JE created in one
        # test leaks into the next on the shared site. Force a clean slate.
        self._delete_opening_balance_jes()

    def tearDown(self):
        self._delete_opening_balance_jes()
        super().tearDown()

    def _delete_opening_balance_jes(self):
        # eboekhouden_mutation_nr="OPENING_BALANCE" is GLOBALLY unique, so a leftover
        # OB JE for ANY company blocks creating ours. Purge by the marker alone.
        # Cancelling a submitted OB JE can trip an on_cancel hook in the test env;
        # force-delete works regardless of docstatus, so swallow a failed cancel and
        # delete anyway (this is test-only cleanup, not a business operation).
        for je in frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": "OPENING_BALANCE"},
            pluck="name",
        ):
            try:
                doc = frappe.get_doc("Journal Entry", je)
                if doc.docstatus == 1:
                    doc.cancel()
            except Exception:
                frappe.db.rollback()
            frappe.delete_doc("Journal Entry", je, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _make_opening_balance_je(self):
        """Pre-create a balanced draft Opening Entry JE tagged OPENING_BALANCE so
        _import_opening_balances' already-imported early-return fires (success +
        journal_entry) with no API call. Two plain asset lines => balanced, no
        party required."""
        offset = self._make_account("EBST OB Offset", "", "Asset")
        je = frappe.new_doc("Journal Entry")
        je.company = COMPANY
        je.posting_date = nowdate()
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.append(
            "accounts",
            {"account": self.bank, "debit_in_account_currency": 100, "cost_center": self.cost_center},
        )
        je.append(
            "accounts",
            {"account": offset, "credit_in_account_currency": 100, "cost_center": self.cost_center},
        )
        je.insert(ignore_permissions=True)
        return je

    @staticmethod
    def _ob_api(*, data=None, success=True, status_code=200, error=None):
        api = MagicMock()
        payload = {"success": success, "status_code": status_code}
        if data is not None:
            payload["data"] = data
        if error is not None:
            payload["error"] = error
        api.make_request.return_value = payload
        return api

    def test_type0_existing_ob_counts_one_imported(self):
        """An already-imported OPENING_BALANCE => _import_opening_balances returns
        success + journal_entry => the type-0 branch tallies imported == 1 with no
        API fetch."""
        self._make_opening_balance_je()
        doc = self._make_migration(migrate_transactions=0)
        fake = _FakeIterator(per_type={0: [{"id": 1, "type": 0}]})

        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=[0])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(result["stats"]["invoices_created"], 1)
        self.assertEqual(fake.requested_types, [0])

    def test_type0_empty_opening_balances_imports_zero(self):
        """OB API returns an empty list => success + journal_entry None => the
        branch tallies imported == 0, run still succeeds."""
        doc = self._make_migration(migrate_transactions=0)
        fake = _FakeIterator(per_type={0: [{"id": 1, "type": 0}]})
        api = self._ob_api(data="[]")

        with patch(ITERATOR_TARGET, new=fake), patch(self.OB_API_TARGET, return_value=api):
            result = start_full_rest_import(doc.name, mutation_types=[0])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(result["stats"]["invoices_created"], 0)
        api.make_request.assert_called_once()
        # Nothing persisted under the OPENING_BALANCE marker.
        self.assertFalse(
            frappe.db.exists(
                "Journal Entry", {"company": COMPANY, "eboekhouden_mutation_nr": "OPENING_BALANCE"}
            )
        )

    def test_type0_api_failure_counts_all_as_failed(self):
        """An OB fetch failure => _import_opening_balances returns success False =>
        the branch tallies failed == len(iterator mutations) and surfaces the OB
        error in stats; the overall run is NOT aborted."""
        doc = self._make_migration(migrate_transactions=0)
        ob_muts = [{"id": 1, "type": 0}, {"id": 2, "type": 0}]
        fake = _FakeIterator(per_type={0: ob_muts})
        api = self._ob_api(success=False, status_code=500, error="boom")

        with patch(ITERATOR_TARGET, new=fake), patch(self.OB_API_TARGET, return_value=api):
            result = start_full_rest_import(doc.name, mutation_types=[0])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(result["stats"]["invoices_created"], 0)
        self.assertEqual(result["stats"]["total_mutations"], len(ob_muts))
        joined = "\n".join(result["stats"]["errors"])
        self.assertIn("Failed to fetch opening balances", joined)

    def test_type0_is_exempt_from_date_filtering(self):
        """Type 0 is NOT date-filtered: an OB mutation dated OUTSIDE the window
        still routes to the OB import (a non-zero type would be filtered out)."""
        doc = self._make_migration(date_from="2024-01-01", date_to="2024-01-31", migrate_transactions=0)
        fake = _FakeIterator(per_type={0: [{"id": 1, "type": 0, "date": "2023-06-15"}]})
        api = self._ob_api(data="[]")

        with patch(ITERATOR_TARGET, new=fake), patch(self.OB_API_TARGET, return_value=api):
            result = start_full_rest_import(doc.name, mutation_types=[0])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        # The OB import was still attempted despite the out-of-window date.
        api.make_request.assert_called_once()

    def test_type0_auto_added_first_for_full_import(self):
        """A full import (migrate_transactions=1, no date_from) with the DEFAULT
        type set prepends type 0 so opening balances are fetched FIRST."""
        doc = self._make_migration(migrate_transactions=1)  # no date_from => is_full_import
        fake = _FakeIterator(per_type={})  # every type empty => cheap

        with patch(ITERATOR_TARGET, new=fake):
            result = start_full_rest_import(doc.name, mutation_types=None)

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(fake.requested_types, [0, 1, 2, 3, 4, 5, 6, 7])

    # A ledger id PRIVATE to this test. Ledger mappings are keyed by ledger_id
    # GLOBALLY and persist across suites, so reusing a shared id (1310/1610/...)
    # risks resolving to a SIBLING suite's company account -> an OB JE whose lines
    # "do not belong to" COMPANY. A private id mapped to OUR own bank account keeps
    # the JE valid no matter what other suites mapped first.
    OB_PRIVATE_LEDGER = 8_800_777

    def _ensure_private_ob_mapping(self):
        """Point OB_PRIVATE_LEDGER at THIS company's bank account (upsert), so the
        opening-balance build resolves to an account that belongs to COMPANY."""
        existing = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": str(self.OB_PRIVATE_LEDGER)}, "name"
        )
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", self.bank)
        else:
            m = frappe.new_doc("E-Boekhouden Ledger Mapping")
            m.ledger_id = self.OB_PRIVATE_LEDGER
            m.ledger_code = str(self.OB_PRIVATE_LEDGER)
            m.ledger_name = "EBST OB Private Bank"
            m.erpnext_account = self.bank
            m.insert(ignore_permissions=True)
        frappe.db.commit()

    def test_type0_real_opening_balances_create_submitted_je(self):
        """Deep path: type-0 with REAL opening-balance data routes through
        _import_opening_balances, which BUILDS, SAVES and SUBMITS a real
        OPENING_BALANCE Journal Entry. The orchestrator converts that into
        imported == 1. The earlier type-0 tests only exercise the empty / failure /
        already-imported tallies; this one drives the full JE-creation path end to
        end through the orchestrator.

        A single bank (Asset) line of +1000 posts a 1000 debit; the builder adds a
        1000 temp-diff credit so the entry balances and submits — no party needed.
        """
        self._ensure_private_ob_mapping()
        doc = self._make_migration(migrate_transactions=0)
        fake = _FakeIterator(per_type={0: [{"id": 1, "type": 0}]})
        ob_payload = [
            {"id": 101, "ledgerId": self.OB_PRIVATE_LEDGER, "amount": 1000.0, "date": nowdate()},
        ]
        api = self._ob_api(data=frappe.as_json(ob_payload))

        with patch(ITERATOR_TARGET, new=fake), patch(self.OB_API_TARGET, return_value=api):
            result = start_full_rest_import(doc.name, mutation_types=[0])

        self.assertTrue(result["success"], msg=f"unexpected failure: {result}")
        self.assertEqual(result["stats"]["invoices_created"], 1)
        api.make_request.assert_called_once()

        # A REAL submitted OPENING_BALANCE JE was produced by the deep path.
        je_name = frappe.db.exists(
            "Journal Entry",
            {
                "company": COMPANY,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            },
        )
        self.assertTrue(je_name, "expected a real OPENING_BALANCE JE from the type-0 deep path")
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1)
        self.assertAlmostEqual(je.total_debit, je.total_credit, places=2)
        self.assertEqual(je.total_debit, 1000.0)
        # The bank line carries the +1000 as a debit; a balancing temp-diff credit
        # makes the Opening Entry balance.
        bank_line = next(r for r in je.accounts if r.account == self.bank)
        self.assertEqual(bank_line.debit_in_account_currency, 1000.0)
        self.assertGreater(len(je.accounts), 1, "expected a balancing line beyond the bank line")
