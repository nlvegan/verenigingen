"""
Cluster C branch coverage for the E-Boekhouden Migration controller
(verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py).

This module targets the whitelisted-endpoint GUARD branches and the
``import_single_mutation`` delete-cascade that run WITHOUT a live eBoekhouden
REST API. It complements (does not duplicate) test_migration_controller_endpoints.py.

Everything uses REAL database objects: a submitted Journal Entry for the
delete-cascade, real Account rows for the ambiguous-account lookup, and the
real E-Boekhouden Migration / E-Boekhouden Settings documents.

The eBoekhouden HTTP boundary is NEVER mocked. Branches that are only
reachable past the API fetch (e.g. the no-cost-center error) are documented as
OUT OF SCOPE. The "not configured" branches are reached by emptying the
api_token via Frappe's own password-storage API (framework infra), which the
per-test transaction rolls back. ``frappe.enqueue`` is patched in exactly one
test (on_submit happy path) to observe that a background job was scheduled
rather than running it inline -- it is framework infra, not business logic.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_3 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_controller_guards_coverage
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, today
from frappe.utils.password import set_encrypted_password

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    import_single_mutation,
    run_migration_background,
    start_migration,
    start_migration_api,
    start_transaction_import,
    update_account_type_mapping,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SETTINGS = "E-Boekhouden Settings"


def _ensure_fiscal_year_for_all_companies():
    """A Fiscal Year must cover today() for the (non-_Test) default company so
    Journal Entry.submit() works. erpnext's global setup restricts the current
    FY to _Test Company via its child table; drop that restriction + bust cache.

    Committed so it outlives the per-test rollback (mirrors the payments suite).
    """
    from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

    ensure_test_fiscal_year_for_all_companies()
    covering = frappe.db.sql(
        """SELECT name FROM `tabFiscal Year`
           WHERE %s BETWEEN year_start_date AND year_end_date AND disabled = 0""",
        (getdate(today()),),
        pluck=True,
    )
    for fy_name in covering:
        if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
            frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()
    frappe.cache().delete_value("fiscal_years")


class _MigrationGuardBase(EnhancedTestCase):
    """Base with explicit cleanup.

    Several controller paths under test call ``frappe.db.commit()`` (e.g.
    start_migration sets status In Progress then commits; on_submit commits via
    start_migration_background). That commit also persists this test's own
    setup writes -- the api_token blanking and the inserted migration docs --
    PAST FrappeTestCase's per-test rollback. So we cannot rely on rollback: we
    snapshot the raw api_token value in setUp and restore it in tearDown, and we
    track + force-delete every migration we create.
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        # Raw stored value of the Password field (NULL/masked-or-empty); restored
        # verbatim in tearDown so emptying it here never leaks to other suites.
        self._orig_api_token = frappe.db.get_value(SETTINGS, SETTINGS, "api_token")
        # Snapshot the REAL decrypted secrets too. On CI the site is unconfigured
        # (these are None), but on a configured site (e.g. veg11) tearDown must
        # restore the encrypted __Auth rows it deletes -- otherwise running this
        # suite would WIPE the live eBoekhouden credential.
        settings_doc = frappe.get_doc(SETTINGS)
        self._orig_pw = {
            field: settings_doc.get_password(field, raise_exception=False)
            for field in ("api_token", "rest_api_token")
        }
        self._created_migrations = []

    def tearDown(self):
        # Roll back any uncommitted work first, then repair committed leakage.
        frappe.db.rollback()
        for name in self._created_migrations:
            if frappe.db.exists("E-Boekhouden Migration", name):
                doc = frappe.get_doc("E-Boekhouden Migration", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc(
                    "E-Boekhouden Migration", name, force=True, delete_permanently=True
                )
        # Restore the api_token Password field exactly as we found it and drop
        # any empty encrypted password rows we may have written.
        frappe.db.delete(
            "__Auth",
            {"doctype": SETTINGS, "name": SETTINGS, "fieldname": "api_token"},
        )
        frappe.db.delete(
            "__Auth",
            {"doctype": SETTINGS, "name": SETTINGS, "fieldname": "rest_api_token"},
        )
        frappe.db.set_value(
            SETTINGS, SETTINGS, "api_token", self._orig_api_token, update_modified=False
        )
        # Re-store any real secrets we snapshotted (no-op on an unconfigured site).
        for field, secret in self._orig_pw.items():
            if secret:
                set_encrypted_password(SETTINGS, SETTINGS, secret, field)
        frappe.db.commit()
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        super().tearDown()

    def _make_migration(self, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop(
            "migration_name", f"Test Migration {frappe.generate_hash()[:8]}"
        )
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        doc.insert()
        self._created_migrations.append(doc.name)
        return doc

    def _empty_api_token_value(self):
        """Make ``E-Boekhouden Settings.get_password("api_token")`` return ''
        (falsy, no raise).

        ``BaseDocument.get_password`` returns the stored field value verbatim
        when it is truthy and not a dummy (all-'*') placeholder, and only falls
        back to the __Auth row otherwise. So we must BOTH blank the tabSingles
        field AND store an empty encrypted password row: the blank field forces
        the __Auth fallback, and the empty encrypted row decrypts to '' instead
        of raising "Password not found". tearDown restores the field.
        """
        frappe.db.set_value(SETTINGS, SETTINGS, "api_token", "", update_modified=False)
        set_encrypted_password(SETTINGS, SETTINGS, "", "api_token")
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    def _blank_api_token_field(self):
        """Make the *document field* ``settings.api_token`` itself falsy ('').

        A Password field renders as a masked dummy ('***') whenever a value is
        stored, so the instance ``start_migration``'s ``if not settings.api_token``
        check only fires when the field is empty AND the stored password row is
        removed (otherwise get_password's __Auth fallback re-populates a mask).
        tearDown restores both.
        """
        frappe.db.delete(
            "__Auth",
            {"doctype": SETTINGS, "name": SETTINGS, "fieldname": "api_token"},
        )
        frappe.db.set_value(SETTINGS, SETTINGS, "api_token", "", update_modified=False)
        frappe.clear_document_cache(SETTINGS, SETTINGS)


class TestImportSingleMutationCascade(_MigrationGuardBase):
    """import_single_mutation: the overwrite delete-cascade and the
    API-configuration ValueError branch, both reached without a live API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_fiscal_year_for_all_companies()

    def _make_submitted_journal_entry(self, mutation_nr):
        """A real submitted Journal Entry stamped with eboekhouden_mutation_nr.

        Cash (debit) vs an Income account (credit) avoids the party
        requirement that Receivable/Payable accounts impose.
        """
        company = self.company
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        cash = frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "account_type": "Cash"}, "name"
        )
        income = frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "root_type": "Income"}, "name"
        )
        if not (cost_center and cash and income):
            self.skipTest("Company lacks the Cash/Income/cost-center accounts the JE needs")

        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = today()
        je.voucher_type = "Journal Entry"
        je.append("accounts", {"account": cash, "debit_in_account_currency": 10, "cost_center": cost_center})
        je.append("accounts", {"account": income, "credit_in_account_currency": 10, "cost_center": cost_center})
        je.insert()
        je.submit()
        frappe.db.set_value("Journal Entry", je.name, "eboekhouden_mutation_nr", str(mutation_nr))
        return je

    def test_overwrite_cascade_deletes_existing_then_reports_api_error(self):
        """overwrite_existing=True deletes the existing submitted doc (the
        cascade), THEN -- because credentials are absent -- returns the
        API-configuration error from EBoekhoudenAPI(settings).

        Both side-effects are observable WITHOUT mocking the HTTP boundary:
        the JE is gone (cascade ran) and the result carries the config error.
        """
        migration = self._make_migration()
        mutation_nr = f"CASC{frappe.generate_hash()[:6]}"
        je = self._make_submitted_journal_entry(mutation_nr)
        self.assertEqual(frappe.db.get_value("Journal Entry", je.name, "docstatus"), 1)

        # Force the API client constructor (EBoekhoudenAPI -> _init_http_client)
        # to raise ValueError("API token is required ...") instead of doing a
        # live request. The cascade runs BEFORE this point.
        self._empty_api_token_value()

        result = import_single_mutation(migration.name, mutation_nr, overwrite_existing=True)

        # Cascade side-effect: the existing submitted JE was cancelled + deleted.
        self.assertFalse(
            frappe.db.exists("Journal Entry", je.name),
            "overwrite cascade should have deleted the existing Journal Entry",
        )
        # And the method then surfaced the API-config error (no HTTP happened).
        self.assertFalse(result["success"])
        self.assertIn("API configuration error", result["error"])

    def test_api_config_error_when_no_existing_doc(self):
        """With no existing doc to cascade, an unconfigured token still yields
        the EBoekhoudenAPI ValueError branch (success=False, config error)."""
        migration = self._make_migration()
        self._empty_api_token_value()

        result = import_single_mutation(
            migration.name, f"NOEXIST{frappe.generate_hash()[:6]}", overwrite_existing=True
        )
        self.assertFalse(result["success"])
        self.assertIn("API configuration error", result["error"])

    # NOTE: the no-cost-center branch (~1503-1504) and the success/skip paths
    # are OUT OF SCOPE here: they live AFTER api.make_request(), which requires
    # a live eBoekhouden REST call. Reaching them would require mocking the HTTP
    # boundary, which the test-quality enforcer forbids.


class TestStartTransactionImportNoToken(_MigrationGuardBase):
    """start_transaction_import: the REST-token-not-configured guard."""

    def test_no_api_token_returns_not_configured(self):
        """A Draft migration with no REST token returns the structured
        API_NOT_CONFIGURED result before any connection attempt.

        Both api_token AND rest_api_token must resolve to '' (falsy, no raise)
        -- the endpoint reads ``get_password("api_token") or
        get_password("rest_api_token")`` and an unset password raises.
        """
        set_encrypted_password(SETTINGS, SETTINGS, "", "api_token")
        set_encrypted_password(SETTINGS, SETTINGS, "", "rest_api_token")
        frappe.clear_document_cache(SETTINGS, SETTINGS)

        migration = self._make_migration(migration_status="Draft")
        result = start_transaction_import(migration.name, import_type="recent")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "API_NOT_CONFIGURED")


class TestStartMigrationGuards(_MigrationGuardBase):
    """start_migration (module fn) and start_migration_api status/exception
    guards reachable without the API."""

    def test_start_migration_rejects_non_draft(self):
        """The module start_migration refuses a migration not in Draft and
        returns before any API connection check."""
        migration = self._make_migration(migration_status="Completed")
        result = start_migration(migration.name)
        self.assertFalse(result["success"])
        self.assertIn("Draft", result["error"])

    def test_start_migration_api_exception_path_marks_failed(self):
        """start_migration_api saves the doc then calls the instance
        start_migration, which throws "not configured" when api_token is blank.
        The except (line ~1198) returns the structured failure, and the
        instance method has already flipped migration_status to Failed.
        """
        self._blank_api_token_field()
        # The controller intentionally frappe.log_error()s the not-configured
        # failure on this path; the ErrorLogGuardMixin would otherwise flag it.
        self.expectErrorLog("Error starting migration", "E-Boekhouden migration failed")
        migration = self._make_migration(migration_status="Draft")

        result = start_migration_api(migration.name, dry_run=0)

        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"].lower())
        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "migration_status"),
            "Failed",
        )


class TestRunMigrationBackgroundFailure(_MigrationGuardBase):
    """run_migration_background failure handling."""

    def test_failure_path_marks_failed_and_returns_structured_error(self):
        """When the instance start_migration throws (blank api_token),
        run_migration_background's except handler must cleanly record the failure
        and return the structured {"success": False, "error": ...} result.

        Regression guard: the handler previously wrote a phantom ``error_message``
        field (the doctype only has ``error_log``), so the recovery db_set ITSELF
        raised OperationalError 1054 instead of marking the run Failed. The fix
        writes ``error_log``; this asserts the clean failure path.
        """
        self._blank_api_token_field()
        # The instance start_migration log_error()s the not-configured failure,
        # and run_migration_background log_error()s its own background failure.
        self.expectErrorLog(
            "Error in background migration",
            "E-Boekhouden migration failed",
        )
        migration = self._make_migration(migration_status="Draft")

        result = run_migration_background(migration.name)

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        # The recovery write succeeded: status Failed + error captured in error_log.
        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "migration_status"),
            "Failed",
        )
        self.assertTrue(
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "error_log"),
            "failure detail must be persisted to the real error_log field",
        )


class TestOnSubmit(_MigrationGuardBase):
    """EBoekhoudenMigration.on_submit Draft vs non-Draft behavior."""

    def test_draft_submit_enqueues_background_migration(self):
        """Submitting a Draft migration flips status to In Progress and
        schedules run_migration_background. frappe.enqueue (framework infra)
        is patched so the job is observed, not executed inline."""
        migration = self._make_migration(migration_status="Draft")

        with patch("frappe.enqueue") as enqueue:
            migration.submit()

        self.assertTrue(enqueue.called)
        target = enqueue.call_args[0][0] if enqueue.call_args.args else enqueue.call_args.kwargs.get("method")
        self.assertIn("run_migration_background", target)
        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "migration_status"),
            "In Progress",
        )

    def test_non_draft_on_submit_is_noop(self):
        """on_submit only starts a background run for Draft status; for any
        other status it must NOT enqueue anything."""
        migration = self._make_migration(migration_status="Completed")

        with patch("frappe.enqueue") as enqueue:
            migration.on_submit()

        self.assertFalse(enqueue.called)


class TestUpdateAccountTypeAmbiguous(_MigrationGuardBase):
    """update_account_type_mapping: ONLY the ambiguous-account branch
    (other branches are covered in test_migration_controller_endpoints.py)."""

    def _parent_account(self):
        return frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
        ) or frappe.db.get_value("Account", {"company": self.company, "is_group": 1}, "name")

    def test_ambiguous_account_name_rejected(self):
        """Two leaf accounts share the same account_name in one company (their
        doc-names differ by account_number). A lookup by the shared display
        name finds >1 match -> AMBIGUOUS_ACCOUNT."""
        parent = self._parent_account()
        if not parent:
            self.skipTest("No group account to parent the duplicate-name accounts")

        shared_name = f"EB Ambiguous {frappe.generate_hash()[:6]}"
        for i in range(2):
            acct = frappe.new_doc("Account")
            acct.account_name = shared_name
            acct.company = self.company
            acct.parent_account = parent
            acct.is_group = 0
            acct.account_number = f"99{i}{frappe.generate_hash()[:4]}"
            acct.insert()

        # Sanity: the display-name lookup really is ambiguous.
        matches = frappe.get_all(
            "Account", filters={"account_name": shared_name, "company": self.company}, limit=2
        )
        self.assertEqual(len(matches), 2)

        result = update_account_type_mapping(shared_name, "Cash", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "AMBIGUOUS_ACCOUNT")
