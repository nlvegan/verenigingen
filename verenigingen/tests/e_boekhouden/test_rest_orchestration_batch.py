"""Real integration tests for the batch orchestration entry point
``_import_rest_mutations_batch_enhanced`` of
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py.

This function loops over a list of eBoekhouden mutation dicts, processes each
inside its own savepoint (via _process_mutation_with_coordinator -> new
processors with legacy fallback), and returns a tally dict
``{"imported", "failed", "skipped", "errors"}``.

These tests exercise every branch of that tally against the REAL database and a
REAL TransactionCoordinator (no business logic mocked):

  1. empty mutations            -> {0,0,0,[]} early return
  2. mutation missing "id"      -> failed += 1, "Mutation missing ID" logged
  3. already-imported           -> skipped += 1 (existing submitted JE matched
                                    on eboekhouden_mutation_nr)
  4. should_skip_mutation        -> skipped += 1 (invoice flagged system import)
  5. SUCCESS                     -> imported == 1, real Journal Entry created
                                    (Type-7 memorial; iterator API boundary faked)
  6. error path (non-stock)     -> failed += 1, errors non-empty (no iterator
                                    patch => EBoekhoudenRESTIterator() construction
                                    fails for lack of an api_token)
  7. no cost center             -> {imported:0, failed:len(mutations)} with
                                    "No cost center found"

``settings`` is a function parameter and the function only reads
``settings.default_company`` from it. We point the REAL E-Boekhouden Settings
single's default_company at our isolated test company for the duration of the
class, restoring the original in tearDownClass, and pass that single as
``settings``.

The ONLY patched seam is EBoekhoudenRESTIterator (and, for the no-cost-center
case, a tiny throwaway company object that only carries .default_company) --
both are at established precedent (test_rest_party_dispatch.py). No process_*/
validate_*/business_rule target, no frappe.get_doc/get_all/new_doc/db.* is
patched.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_2 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_orchestration_batch
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, nowdate

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _import_rest_mutations_batch_enhanced,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import deadlock

ABBR = "EBBA"
COMPANY = "TEST-EB-Batch-Company"

# "E-Boekhouden Ledger Mapping" is keyed by ledger_id GLOBALLY and persists across
# suites on the shared test site. Sibling suites map the canonical eBoekhouden ids
# (1310/1610/8100/4100) to their OWN companies' accounts; reusing them here would let
# the resolver (which ignores company) return a foreign company's account, so the
# Type-7 memorial JE-building path would fail ("Account ... does not belong to
# Company"). Use ids PRIVATE to this suite so resolution points at our accounts.
INCOME_LEDGER = "9708100"
EXPENSE_LEDGER = "9704100"
RECEIVABLE_LEDGER = "9701310"
PAYABLE_LEDGER = "9701610"


class _FakeIterator:
    """Stub for EBoekhoudenRESTIterator.

    _process_single_mutation does
    ``EBoekhoudenRESTIterator().fetch_mutation_detail(id)`` to load full detail.
    Patched in via ``new=_FakeIterator(mutation)`` so the instance replaces the
    class: calling it (the ``EBoekhoudenRESTIterator()`` construction) returns
    self, and fetch_mutation_detail returns the canned mutation -- no live API.
    """

    def __init__(self, mutation):
        self._mutation = mutation

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        return self._mutation


class _RaisingIterator:
    """Stub for EBoekhoudenRESTIterator that constructs cleanly but raises a
    uniquely-tagged error from ``fetch_mutation_detail``, so the legacy
    detail-fetch path errors deterministically -- the tag lets the test assert
    WHICH error fired instead of leaning on the incidental missing-token ctor
    failure (which is coupled to ambient site/token state)."""

    TAG = "INDUCED-NONSTOCK-ERR-BATCH"

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        raise RuntimeError(self.TAG)


class _PartialFailureIterator:
    """Stub for EBoekhoudenRESTIterator returning REAL detail for every mutation
    except one, for which it raises a given (non-resumable) error -- simulating a
    1213/1205 surfacing from a live API call partway through a batch.

    ``ok_mutations`` supplies detail for every id that is not the failing one; the
    failing id need not be in there (a bare ``{"id": ..., "type": ...}`` is enough
    since fetch_mutation_detail never returns for it).
    """

    def __init__(self, ok_mutations, failing_id, error_factory):
        self._ok = {m["id"]: m for m in ok_mutations}
        self._failing_id = failing_id
        self._error_factory = error_factory

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        if mutation_id == self._failing_id:
            raise self._error_factory()
        return self._ok[mutation_id]


class _SettingsStub:
    """Minimal stand-in carrying ONLY ``default_company`` -- the single field the
    batch function reads from its ``settings`` parameter. Used only for the
    no-cost-center branch so we can aim at a bare company without a cost center
    without disturbing the real E-Boekhouden Settings single."""

    def __init__(self, default_company):
        self.default_company = default_company


# ---------------------------------------------------------------------------
# Shared bootstrap (mirrors _PartyClusterBase from test_rest_party_dispatch.py)
# ---------------------------------------------------------------------------


class _BatchClusterBase(EnhancedTestCase):
    """Company, accounts, ledger mappings, cost center, fiscal year, and the
    E-Boekhouden Settings default_company redirection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_fiscal_year()
        cls._point_settings_at_test_company()
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls._restore_settings()
        frappe.db.commit()
        super().tearDownClass()

    # ---- E-Boekhouden Settings redirection ----

    @classmethod
    def _point_settings_at_test_company(cls):
        # The E-Boekhouden Settings single has a mandatory api_token that is
        # empty in tests, so a full doc.save() raises MandatoryError. The batch
        # function only reads settings.default_company, so we persist that one
        # field directly with set_value (no hook/validation), then re-read the
        # single so the test passes the REAL single object as `settings`.
        cls._orig_default_company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", COMPANY)
        frappe.db.commit()
        cls.settings = frappe.get_single("E-Boekhouden Settings")

    @classmethod
    def _restore_settings(cls):
        frappe.db.set_single_value(
            "E-Boekhouden Settings",
            "default_company",
            getattr(cls, "_orig_default_company", None),
        )
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
        r.account_name = f"EBB {root_type} Root"
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
        cls.receivable = cls._make_account("EBB Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBB Creditors", "Payable", "Liability")
        cls.income = cls._make_account("EBB Sales Income", "Income Account", "Income")
        cls.expense = cls._make_account("EBB Expenses", "Expense Account", "Expense")
        cls.bank = cls._make_account("EBB Bank", "Bank", "Asset")

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
        cls._make_ledger_map(INCOME_LEDGER, cls.income, "EBB Sales Income")
        cls._make_ledger_map(EXPENSE_LEDGER, cls.expense, "EBB Expenses")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBB Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBB Creditors")

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
            fy_name = f"EBB-FY-{year}"
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

    def _make_submitted_je(self, mutation_nr):
        """Create a REAL submitted Journal Entry carrying the given
        eboekhouden_mutation_nr (so the batch sees it as already imported)."""
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

    @staticmethod
    def _memorial_mutation(mutation_id):
        """A self-contained, balanced Type-7 memorial mutation referencing the
        mapped income/expense ledgers (modeled on
        test_rest_party_dispatch.test_dispatch_type7_creates_journal_entry)."""
        return {
            "id": mutation_id,
            "type": 7,
            "date": nowdate(),
            "description": "Batch memorial reclassification",
            "ledgerId": INCOME_LEDGER,
            "Regels": [
                {"ledgerId": INCOME_LEDGER, "amount": 25.00, "description": "to income"},
                {"ledgerId": EXPENSE_LEDGER, "amount": -25.00, "description": "from expense"},
            ],
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportRestMutationsBatchEnhanced(_BatchClusterBase):
    def test_empty_mutations_returns_zero_tally(self):
        """No mutations => early return with an all-zero tally and empty errors."""
        result = _import_rest_mutations_batch_enhanced("MIG-EMPTY", [], self.settings, mutation_type=7)
        self.assertEqual(result, {"imported": 0, "failed": 0, "skipped": 0, "errors": []})

    def test_mutation_missing_id_counts_as_failed(self):
        """A mutation lacking an 'id' is counted as failed (not skipped/imported)."""
        result = _import_rest_mutations_batch_enhanced(
            "MIG-NOID", [{"type": 7}], self.settings, mutation_type=7
        )
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 0)

    def test_already_imported_mutation_is_skipped(self):
        """An existing submitted JE with the mutation's nr => the mutation is
        skipped, nothing re-imported."""
        mutation_id = 970001
        je = self._make_submitted_je(mutation_id)
        self.assertEqual(
            frappe.db.get_value("Journal Entry", je.name, "eboekhouden_mutation_nr"), str(mutation_id)
        )

        result = _import_rest_mutations_batch_enhanced(
            "MIG-DUP", [{"id": mutation_id, "type": 7}], self.settings, mutation_type=7
        )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["failed"], 0)

    def test_should_skip_mutation_is_skipped(self):
        """An invoice mutation flagged as a system import is skipped by
        should_skip_mutation before any processing."""
        mutation = {
            "id": 970010,
            "type": 1,  # Sales Invoice
            "amount": 100,
            "description": "System Notification of order status",
        }
        result = _import_rest_mutations_batch_enhanced("MIG-SKIP", [mutation], self.settings, mutation_type=1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["failed"], 0)

    def test_success_creates_journal_entry(self):
        """A balanced Type-7 memorial mutation is imported, producing a real
        submitted Journal Entry carrying its mutation nr."""
        mutation_id = 970100
        mutation = self._memorial_mutation(mutation_id)
        self.assertFalse(frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}))

        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator",
            new=_FakeIterator(mutation),
        ):
            result = _import_rest_mutations_batch_enhanced(
                "MIG-OK", [mutation], self.settings, mutation_type=7
            )

        self.assertEqual(result["imported"], 1, msg=f"errors: {result['errors']}")
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)
        je_name = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}, "name")
        self.assertIsNotNone(je_name, "A Journal Entry with the mutation nr must now exist")
        self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 1)
        # The JE must carry the RIGHT economic content, not just exist & balance:
        # the ±25.00 memorial posts 25.00 on each side across the mapped ledgers.
        self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "total_debit"), 25.0)
        # Ledger ids are PRIVATE to this suite, so they map to THIS company's own
        # income/expense accounts. Assert the JE used exactly those accounts -- a
        # regression posting to a wrong or default account would fail this.
        accounts = set(frappe.get_all("Journal Entry Account", filters={"parent": je_name}, pluck="account"))
        expected_accounts = {self.income, self.expense}
        self.assertEqual(accounts, expected_accounts)

    def test_processing_error_counts_as_failed(self):
        """The legacy detail-fetch error path: failed += 1, errors non-empty.

        With the new-processor coordinator DISABLED (the function's own
        ``eboekhouden_use_new_processors`` config gate), a Type-7 mutation falls
        straight to legacy ``_process_single_mutation``, which constructs the
        iterator and calls ``fetch_mutation_detail``. We patch the iterator so
        that call raises a uniquely-tagged error => action 'error' (non-stock) =>
        the mutation is counted as failed and the tagged error string is recorded.

        The tag makes the failure deterministic and decoupled from ambient
        site/token state; the config flag toggle is the function's own gate (not
        business-logic mocking).
        """
        mutation_id = 970200
        mutation = self._memorial_mutation(mutation_id)
        self.assertFalse(frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}))

        orig_flag = frappe.conf.get("eboekhouden_use_new_processors")
        frappe.conf["eboekhouden_use_new_processors"] = False
        try:
            with patch(
                "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator",
                new=_RaisingIterator(),
            ):
                result = _import_rest_mutations_batch_enhanced(
                    "MIG-ERR", [mutation], self.settings, mutation_type=7
                )
        finally:
            if orig_flag is None:
                frappe.conf.pop("eboekhouden_use_new_processors", None)
            else:
                frappe.conf["eboekhouden_use_new_processors"] = orig_flag

        self.assertGreaterEqual(result["failed"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertTrue(result["errors"], "errors list must be non-empty on a processing error")
        # The recorded error must be the one WE induced, not a stray failure.
        self.assertTrue(
            any(_RaisingIterator.TAG in e for e in result["errors"]),
            f"expected the induced tag in errors, got: {result['errors']}",
        )
        # The partial writes (if any) must have been rolled back: no JE persisted.
        self.assertFalse(frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}))

    def _ensure_company_without_cost_center(self):
        """Create (idempotently) a bare company and strip every cost center so
        get_default_cost_center() returns None. Factory helper -- permission
        bypass + force-delete live here, never in a test body."""
        bare_company = "TEST-EB-Batch-NoCC"
        if not frappe.db.exists("Company", bare_company):
            c = frappe.new_doc("Company")
            c.company_name = bare_company
            c.abbr = "EBBN"
            c.default_currency = "EUR"
            c.country = "Netherlands"
            c.insert(ignore_permissions=True)
        # get_default_cost_center checks the company's cost_center field, then
        # ANY non-group cost center for the company. To force a None result we
        # must clear the company's cost-center links AND remove every leaf cost
        # center ERPNext auto-created. Clear the company links first (they block
        # cost-center deletion), then delete the leaf cost centers.
        for fld in ("cost_center", "round_off_cost_center", "depreciation_cost_center"):
            if frappe.db.has_column("Company", fld):
                frappe.db.set_value("Company", bare_company, fld, None)
        frappe.db.commit()
        for cc in frappe.get_all(
            "Cost Center", filters={"company": bare_company, "is_group": 0}, pluck="name"
        ):
            frappe.delete_doc("Cost Center", cc, force=True, ignore_permissions=True)
        frappe.db.commit()
        return bare_company

    def test_no_cost_center_fails_all_mutations(self):
        """A company with no cost center => early return marking every mutation
        failed with a 'No cost center found' error."""
        bare_company = self._ensure_company_without_cost_center()
        self.assertFalse(
            frappe.db.get_value("Cost Center", {"company": bare_company, "is_group": 0}, "name"),
            "test precondition: bare company must have no non-group cost center",
        )

        stub = _SettingsStub(bare_company)
        mutations = [{"id": 970300, "type": 7}, {"id": 970301, "type": 7}]
        result = _import_rest_mutations_batch_enhanced("MIG-NOCC", mutations, stub, mutation_type=7)

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["failed"], len(mutations))
        self.assertEqual(result["skipped"], 0)
        self.assertIn("No cost center found", result["errors"])


class TestImportRestMutationsBatchEnhancedAbortsOnNonResumableError(_BatchClusterBase):
    """#572: a 1213/1205 raised mid-batch must ABORT the batch and report how far it
    got, instead of being folded into an ordinary per-mutation failure (the pre-#572
    behaviour) and continuing to feed mutations into a transaction the server has
    already discarded.

    New processors disabled (``eboekhouden_use_new_processors=False``, the function's
    own config gate -- the same seam ``test_processing_error_counts_as_failed`` uses,
    not business-logic mocking) so the error is raised deterministically from
    ``EBoekhoudenRESTIterator.fetch_mutation_detail`` inside the LEGACY path, driven by
    a REAL Type-7 memorial mutation exactly like this file's SUCCESS case.
    """

    def test_deadlock_mid_batch_aborts_and_reports_last_imported_mutation(self):
        ok_id, deadlock_id, unreached_id = 970400, 970401, 970402
        ok_mutation = self._memorial_mutation(ok_id)
        unreached_mutation = self._memorial_mutation(unreached_id)
        mutations = [ok_mutation, {"id": deadlock_id, "type": 7}, unreached_mutation]

        for mutation_id in (ok_id, deadlock_id, unreached_id):
            self.assertFalse(
                frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)})
            )

        self.expectErrorLog("ABORTED")

        orig_flag = frappe.conf.get("eboekhouden_use_new_processors")
        frappe.conf["eboekhouden_use_new_processors"] = False
        try:
            with patch(
                "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator",
                new=_PartialFailureIterator([ok_mutation, unreached_mutation], deadlock_id, deadlock),
            ):
                with self.assertRaises(frappe.QueryDeadlockError):
                    _import_rest_mutations_batch_enhanced(
                        "MIG-ABORT", mutations, self.settings, mutation_type=7
                    )
        finally:
            if orig_flag is None:
                frappe.conf.pop("eboekhouden_use_new_processors", None)
            else:
                frappe.conf["eboekhouden_use_new_processors"] = orig_flag

        # The mutation imported BEFORE the deadlock must still be persisted -- its
        # own savepoint was released before the batch ever saw the error.
        self.assertTrue(
            frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(ok_id)}),
            "the mutation imported before the deadlock must still be persisted",
        )
        # The mutation AFTER the abort point must never have been attempted --
        # the batch stopped instead of continuing past the non-resumable error.
        self.assertFalse(
            frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": str(unreached_id)}),
            "a mutation after the abort point must never be attempted",
        )

        # And an operator-visible report exists, naming how far the batch got --
        # NOT `debug_info`, which never reaches an operator on this path.
        abort_logs = frappe.get_all(
            "Error Log",
            filters={"method": ["like", "%ABORTED%"]},
            fields=["name", "method", "error"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(abort_logs, "expected an ABORTED Error Log entry to be written")
        self.assertIn("Memorial Bookings", abort_logs[0].method)
        self.assertIn(
            str(ok_id),
            abort_logs[0].error,
            "the report must name the last successfully imported mutation",
        )
