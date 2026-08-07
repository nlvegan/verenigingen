"""
Real integration coverage for the POST-FETCH half of
``e_boekhouden_migration.import_single_mutation`` -- the single largest
uncovered region in the repo (e_boekhouden_migration.py, ~417 missed lines).

WHY THIS MODULE EXISTS
----------------------
``test_migration_controller_guards_coverage.TestImportSingleMutationCascade``
deliberately stops at the ``EBoekhoudenAPI(settings)`` constructor and states
that everything after ``api.make_request()`` is out of scope "because reaching
it would require mocking the HTTP boundary". The eBoekhouden REST API is a
genuine EXTERNAL boundary, so stubbing exactly one method --
``EBoekhoudenAPI.make_request`` -- is legitimate and is the ONLY thing mocked
here. Everything downstream is real: the TransactionCoordinator, the
JournalProcessor, real Accounts / Cost Centers / Ledger Mappings, and a real
submitted Journal Entry whose debits and credits are asserted.

Behaviours covered (all previously unexecuted):
    * transport failure  -> structured error, nothing written to the ledger
    * malformed JSON body-> structured error, no crash
    * happy path         -> a REAL balanced Journal Entry, correct legs,
                            correct result payload
    * duplicate guard    -> overwrite_existing=False REFUSES *and preserves*
                            the existing document (a regression here would
                            silently destroy posted accounting documents)
    * overwrite path     -> exactly one document survives per mutation id
                            (no duplicate ledger postings)

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_single_mutation_dispatch
"""

import json
from unittest.mock import patch

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    import_single_mutation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

COMPANY = "TEST-EB-Dispatch-Company"
ABBR = "EBDS"

# Globally unique ledger ids/codes. "E-Boekhouden Ledger Mapping" has NO company
# column, so a low/shared code would be hijacked by whichever module's
# setUpClass runs first on a shared CI shard and would then resolve to another
# company's account (-> "Account does not belong to Company" on submit).
EXPENSE_LEDGER = "7300004"
BANK_LEDGER = "7300001"
KRUISPOSTEN_LEDGER = "7300099"

API_PATH = "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI.make_request"


def _api_ok(mutation: dict):
    """A successful eBoekhouden REST envelope carrying ``mutation`` as its body."""
    return {"success": True, "status_code": 200, "data": json.dumps(mutation)}


class _DispatchBase(EnhancedTestCase):
    """Company / accounts / cost center / ledger mappings / fiscal year."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Restore the session user on class teardown: _restore_ctx_locals restores
        # frappe.local.flags but NOT the session user, so without this the
        # Administrator session leaks into whatever module runs next in-process.
        _prior_user = frappe.session.user
        cls.addClassCleanup(frappe.set_user, _prior_user)
        frappe.set_user("Administrator")
        cls._ensure_company()
        cls._ensure_accounts()
        cls._ensure_cost_center()
        cls._ensure_ledger_mappings()
        cls._ensure_fiscal_year()
        cls._ensure_api_token()
        frappe.db.commit()

    # ---- bootstrap ----

    @classmethod
    def _ensure_api_token(cls):
        """Give E-Boekhouden Settings a placeholder token.

        ``import_single_mutation`` constructs a real ``EBoekhoudenAPI`` before it
        calls ``make_request``; that constructor reads the api_token password and
        raises when it is unset (a sibling module deliberately blanks it). The
        token value is never used -- ``make_request`` is stubbed in every test --
        but it must exist for the client to be constructible.

        NOT restored afterwards: api_token is a MANDATORY field, so it cannot be
        saved back to "". Nothing depends on it being empty either -- the sibling
        module that needs a blank token
        (test_migration_controller_guards_coverage) blanks it itself in setUp.
        """
        settings = frappe.get_single("E-Boekhouden Settings")
        try:
            if settings.get_password("api_token", raise_exception=False):
                return
        except Exception:
            pass
        settings.api_token = "EBDS-PLACEHOLDER-TOKEN"
        # default_company is reqd on this Single, so save() throws
        # "[E-Boekhouden Settings]: default_company" whenever it is still empty.
        # It only ever looked optional because some other module in the same shard
        # happened to seed it first; rebalancing the shards removed that accident.
        if not settings.default_company:
            settings.default_company = COMPANY
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    @classmethod
    def _ensure_company(cls):
        if not frappe.db.exists("Company", COMPANY):
            c = frappe.new_doc("Company")
            c.company_name = COMPANY
            c.abbr = ABBR
            c.default_currency = "EUR"
            c.country = "Netherlands"
            c.insert()
        cls.company = COMPANY

    @classmethod
    def _root(cls, root_type):
        existing = frappe.db.get_value(
            "Account", {"company": COMPANY, "root_type": root_type, "is_group": 1}, "name"
        )
        if existing:
            return existing
        r = frappe.new_doc("Account")
        r.account_name = f"{ABBR} {root_type} Root"
        r.company = COMPANY
        r.root_type = root_type
        r.report_type = (
            "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        )
        r.is_group = 1
        r.insert()
        return r.name

    @classmethod
    def _account(cls, account_name, account_type, root_type):
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
        a.parent_account = cls._root(root_type)
        a.insert()
        return a.name

    @classmethod
    def _ensure_accounts(cls):
        cls.expense = cls._account("EBDS Expense", "Expense Account", "Expense")
        cls.bank = cls._account("EBDS Bank", "Bank", "Asset")
        cls.kruisposten = cls._account("EBDS Kruisposten", "", "Asset")
        cls.receivable = cls._account("EBDS Debtors", "Receivable", "Asset")
        cls.payable = cls._account("EBDS Creditors", "Payable", "Liability")
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
            rc.insert()
            root_cc = rc.name
        leaf = frappe.new_doc("Cost Center")
        leaf.cost_center_name = "EBDS Main"
        leaf.company = COMPANY
        leaf.is_group = 0
        leaf.parent_cost_center = root_cc
        leaf.insert()
        cls.cost_center = leaf.name

    @classmethod
    def _map_ledger(cls, ledger_id, account, label):
        # Repoint rather than skip: the mapping is a GLOBAL singleton keyed on
        # ledger_id, so a stale row from an earlier run must be corrected to
        # THIS company's account.
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "name")
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", account)
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = str(ledger_id)
        m.ledger_code = str(ledger_id)
        m.ledger_name = label
        m.erpnext_account = account
        m.insert()

    @classmethod
    def _ensure_ledger_mappings(cls):
        cls._map_ledger(EXPENSE_LEDGER, cls.expense, "EBDS Expense")
        cls._map_ledger(BANK_LEDGER, cls.bank, "EBDS Bank")
        cls._map_ledger(KRUISPOSTEN_LEDGER, cls.kruisposten, "EBDS Kruisposten")

    @classmethod
    def _ensure_fiscal_year(cls):
        """A Fiscal Year covering today() that lists THIS company.

        Scoped per test company (never appended to a shared FY-<year> row) so
        sibling modules cannot be affected.
        """
        year = getdate().year
        fy_name = f"FY-{ABBR}-{year}"

        # ALWAYS use the scoped row. An earlier version looked up any Fiscal Year
        # covering today() and only fell back to a scoped one if none existed —
        # so on any real site it appended this test company to the shared FY-<year>,
        # the exact opposite of the docstring above and a violation of the repo's
        # no-shared-FY rule. Verified: FY-2026 had picked up the test company.
        if not frappe.db.exists("Fiscal Year", fy_name):
            fy = frappe.new_doc("Fiscal Year")
            fy.year = fy_name
            fy.year_start_date = f"{year}-01-01"
            fy.year_end_date = f"{year}-12-31"
            # The company MUST be set before insert. ERPNext's validate_overlap()
            # rejects a Fiscal Year whose dates overlap an existing one unless it is
            # company-scoped ("To avoid please set company"), and a scoped row by
            # definition overlaps the shared FY-<year>.
            fy.append("companies", {"company": COMPANY})
            fy.insert()
            return

        fy = frappe.get_doc("Fiscal Year", fy_name)
        if not any(c.company == COMPANY for c in fy.companies):
            fy.append("companies", {"company": COMPANY})
            fy.save(ignore_permissions=True)

    # ---- per-test helpers ----

    def _migration(self):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = f"EBDS Dispatch {frappe.generate_hash()[:8]}"
        doc.company = COMPANY
        doc.migration_status = "Draft"
        doc.insert()
        self.addCleanup(self._safe_delete, "E-Boekhouden Migration", doc.name)
        return doc

    @staticmethod
    def _safe_delete(doctype, name):
        """import_single_mutation COMMITS on success, so rows survive the test
        rollback and must be removed explicitly."""
        if not frappe.db.exists(doctype, name):
            return
        try:
            doc = frappe.get_doc(doctype, name)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()

    def _cleanup_mutation_docs(self, mutation_id):
        """Delete whatever ledger document a committed import left behind."""

        def _drop():
            for doctype in ("Journal Entry", "Sales Invoice", "Purchase Invoice", "Payment Entry"):
                for name in frappe.get_all(
                    doctype,
                    filters={"eboekhouden_mutation_nr": str(mutation_id)},
                    pluck="name",
                ):
                    self._safe_delete(doctype, name)

        self.addCleanup(_drop)

    def _memorial_mutation(self, mutation_id, amount=100.00, **overrides):
        """A type-7 memorial booking: one expense row offset against Kruisposten.

        The REST payload omits a top-level ``amount`` for type 7; the row amount
        drives both legs.
        """
        m = {
            "id": mutation_id,
            "type": 7,
            "date": nowdate(),
            "relationId": None,
            "invoiceNumber": None,
            "description": f"EBDS memorial {mutation_id}",
            "ledgerId": KRUISPOSTEN_LEDGER,
            "rows": [
                {
                    "ledgerId": EXPENSE_LEDGER,
                    "amount": amount,
                    "quantity": 1,
                    "description": "EBDS expense reclass",
                }
            ],
        }
        m.update(overrides)
        return m


# ---------------------------------------------------------------------------
# Transport / payload failures: the ledger must stay untouched.
# ---------------------------------------------------------------------------
class TestImportSingleMutationTransportFailures(_DispatchBase):
    def test_api_reports_failure_returns_structured_error_and_writes_nothing(self):
        """A non-200 API envelope must abort BEFORE any document is written.

        Regression risk: if the guard at e_boekhouden_migration.py:~1378 were
        dropped, ``json.loads(result.get("data", "{}"))`` would yield ``{}`` and
        the coordinator would be handed an empty mutation.
        """
        migration = self._migration()
        mutation_id = 730101
        self._cleanup_mutation_docs(mutation_id)

        with patch(API_PATH, return_value={"success": False, "status_code": 500, "error": "boom"}):
            result = import_single_mutation(migration.name, str(mutation_id), overwrite_existing=True)

        self.assertFalse(result["success"])
        self.assertIn(str(mutation_id), result["error"])
        self.assertIn("Failed to fetch", result["error"])
        self.assertEqual(
            frappe.get_all("Journal Entry", filters={"eboekhouden_mutation_nr": str(mutation_id)}),
            [],
            "a failed fetch must not create a ledger document",
        )

    def test_http_200_with_success_false_is_still_rejected(self):
        """status_code 200 alone is not enough -- ``success`` must also be true."""
        migration = self._migration()
        mutation_id = 730102
        self._cleanup_mutation_docs(mutation_id)

        with patch(API_PATH, return_value={"success": False, "status_code": 200, "data": "{}"}):
            result = import_single_mutation(migration.name, str(mutation_id), overwrite_existing=True)

        self.assertFalse(result["success"])
        self.assertIn("Failed to fetch", result["error"])

    def test_malformed_json_body_is_reported_not_crashed(self):
        """A 200 response whose body is not JSON must surface as a structured
        error, not propagate a JSONDecodeError to the caller."""
        migration = self._migration()
        mutation_id = 730103
        self._cleanup_mutation_docs(mutation_id)
        # The endpoint logs the parse failure before returning it -- that IS the
        # asserted behaviour (an operator needs the Error Log row to diagnose a
        # bad gateway response), so the guard is told to expect it.
        self.expectErrorLog(f"Import Error - Mutation {mutation_id}")

        with patch(API_PATH, return_value={"success": True, "status_code": 200, "data": "<html>502</html>"}):
            result = import_single_mutation(migration.name, str(mutation_id), overwrite_existing=True)

        self.assertFalse(result["success"])
        self.assertIn("Unexpected error", result["error"])
        self.assertEqual(
            frappe.get_all("Journal Entry", filters={"eboekhouden_mutation_nr": str(mutation_id)}), []
        )


# ---------------------------------------------------------------------------
# The happy path: a real, balanced, submitted Journal Entry.
# ---------------------------------------------------------------------------
class TestImportSingleMutationHappyPath(_DispatchBase):
    def test_memorial_mutation_creates_balanced_journal_entry(self):
        """End-to-end: envelope -> TransactionCoordinator -> JournalProcessor ->
        a real Journal Entry.

        Asserts the accounting outcome, not just ``success``: the expense ledger
        and the offsetting Kruisposten ledger each carry exactly 100.00 on
        opposite sides, and the entry balances.
        """
        migration = self._migration()
        mutation_id = 730201
        self._cleanup_mutation_docs(mutation_id)

        with patch(API_PATH, return_value=_api_ok(self._memorial_mutation(mutation_id, amount=100.00))):
            result = import_single_mutation(migration.name, str(mutation_id), overwrite_existing=True)

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["document_type"], "Journal Entry")
        self.assertIn(result["processing_method"], ("new_processors", "legacy"))

        je = frappe.get_doc("Journal Entry", result["document_name"])
        self.assertEqual(str(je.eboekhouden_mutation_nr), str(mutation_id))
        self.assertEqual(je.company, COMPANY)

        total_debit = sum(flt(a.debit_in_account_currency) for a in je.accounts)
        total_credit = sum(flt(a.credit_in_account_currency) for a in je.accounts)
        self.assertAlmostEqual(total_debit, total_credit, places=2, msg="journal entry must balance")
        self.assertAlmostEqual(total_debit, 100.00, places=2)

        by_account = {
            a.account: (flt(a.debit_in_account_currency), flt(a.credit_in_account_currency))
            for a in je.accounts
        }
        self.assertIn(self.expense, by_account, f"expense ledger leg missing; got {list(by_account)}")
        self.assertIn(self.kruisposten, by_account, f"offset ledger leg missing; got {list(by_account)}")
        # Memorial convention: a POSITIVE row amount CREDITS the row account and
        # DEBITS the main (offset) account.
        self.assertEqual(by_account[self.expense], (0.0, 100.00))
        self.assertEqual(by_account[self.kruisposten], (100.00, 0.0))

    def test_result_payload_carries_debug_info(self):
        """The endpoint's debug trail is what the Desk UI shows an operator when
        an import misbehaves; an empty trail makes migrations undiagnosable."""
        migration = self._migration()
        mutation_id = 730202
        self._cleanup_mutation_docs(mutation_id)

        with patch(API_PATH, return_value=_api_ok(self._memorial_mutation(mutation_id, amount=55.00))):
            result = import_single_mutation(migration.name, str(mutation_id), overwrite_existing=True)

        self.assertTrue(result["success"], result.get("error"))
        self.assertIsInstance(result["debug_info"], list)
        self.assertTrue(result["debug_info"], "debug_info must not be empty on a successful import")


# ---------------------------------------------------------------------------
# Duplicate detection -- the branch that protects posted accounting documents.
# ---------------------------------------------------------------------------
class TestImportSingleMutationDuplicateGuard(_DispatchBase):
    def _import(self, migration, mutation_id, amount, overwrite):
        with patch(API_PATH, return_value=_api_ok(self._memorial_mutation(mutation_id, amount=amount))):
            return import_single_mutation(migration.name, str(mutation_id), overwrite_existing=overwrite)

    def test_reimport_without_overwrite_refuses_and_preserves_existing_document(self):
        """overwrite_existing=False must refuse AND leave the posted document
        intact.

        This is the highest-consequence branch in the endpoint: a regression that
        let the delete-cascade run before the guard would destroy a submitted
        Journal Entry that the caller explicitly asked NOT to replace.
        """
        migration = self._migration()
        mutation_id = 730301
        self._cleanup_mutation_docs(mutation_id)

        first = self._import(migration, mutation_id, 100.00, overwrite=True)
        self.assertTrue(first["success"], first.get("error"))
        original_name = first["document_name"]

        second = self._import(migration, mutation_id, 999.00, overwrite=False)

        self.assertFalse(second["success"])
        self.assertIn("already exists", second["error"])
        self.assertIn(original_name, second["error"])
        self.assertTrue(
            frappe.db.exists("Journal Entry", original_name),
            "the refused re-import must not delete the existing Journal Entry",
        )
        # ...and its amounts are untouched by the refused import.
        je = frappe.get_doc("Journal Entry", original_name)
        self.assertAlmostEqual(flt(je.total_debit), 100.00, places=2)

    def test_reimport_with_overwrite_leaves_exactly_one_document(self):
        """The overwrite path must REPLACE, never duplicate.

        Two documents carrying the same eboekhouden_mutation_nr would double-post
        the mutation to the general ledger.
        """
        migration = self._migration()
        mutation_id = 730302
        self._cleanup_mutation_docs(mutation_id)

        first = self._import(migration, mutation_id, 100.00, overwrite=True)
        self.assertTrue(first["success"], first.get("error"))

        second = self._import(migration, mutation_id, 250.00, overwrite=True)
        self.assertTrue(second["success"], second.get("error"))

        surviving = frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": str(mutation_id), "docstatus": ["<", 2]},
            pluck="name",
        )
        self.assertEqual(
            len(surviving), 1, f"overwrite must leave exactly one live document, got {surviving}"
        )
        self.assertEqual(surviving[0], second["document_name"])
        # The surviving document reflects the SECOND import's amount.
        je = frappe.get_doc("Journal Entry", second["document_name"])
        self.assertAlmostEqual(flt(je.total_debit), 250.00, places=2)
