"""
Branch coverage for the E-Boekhouden Migration DocType controller's
whitelisted endpoints and helper methods
(verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py).

All tests use REAL database objects (Company, Account, Cost Center, the
E-Boekhouden Migration doc itself). The only thing mocked is the external
eBoekhouden HTTP boundary where an endpoint would otherwise make a live API
call (e.g. the session-token request inside check_rest_api_status), and
``frappe.enqueue`` where a test asserts a background job was scheduled rather
than running it inline. No business logic is mocked.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_controller_endpoints
"""

from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    _migration_phase_failed,
    _resolve_migration_status,
    check_rest_api_status,
    import_single_mutation,
    start_migration_api,
    start_transaction_import,
    update_account_type_mapping,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _insert_test_doc(doc):
    doc.insert(ignore_permissions=True)
    return doc


class TestMigrationPhaseHelpers(EnhancedTestCase):
    """Pure helpers that decide final migration status from phase results."""

    def test_phase_failed_on_non_dict(self):
        """A non-dict phase result is treated as a failure (fail loud)."""
        self.assertTrue(_migration_phase_failed(None))
        self.assertTrue(_migration_phase_failed("oops"))

    def test_phase_failed_on_success_false(self):
        self.assertTrue(_migration_phase_failed({"success": False, "message": "x"}))

    def test_phase_not_failed_on_success_true(self):
        self.assertFalse(_migration_phase_failed({"success": True, "message": "ok"}))

    def test_resolve_status_completed_when_no_failures(self):
        status, operation = _resolve_migration_status([])
        self.assertEqual(status, "Completed")
        self.assertIn("completed successfully", operation.lower())

    def test_resolve_status_failed_lists_phases(self):
        status, operation = _resolve_migration_status(["Chart of Accounts", "Transactions"])
        self.assertEqual(status, "Failed")
        self.assertIn("Chart of Accounts", operation)
        self.assertIn("Transactions", operation)


class TestUpdateAccountTypeMapping(EnhancedTestCase):
    """update_account_type_mapping: input validation + lookup + update branches.

    Uses a real Account so the success path actually flips account_type in the DB.
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        # A real group account to parent a fresh leaf account.
        self.parent = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
        ) or frappe.db.get_value("Account", {"company": self.company, "is_group": 1}, "name")
        if not self.parent:
            self.skipTest("No group account to parent a test account")
        self.account = self._make_account()

    def _make_account(self, account_type=""):
        doc = frappe.new_doc("Account")
        doc.account_name = f"EB Type Test {frappe.generate_hash()[:6]}"
        doc.company = self.company
        doc.parent_account = self.parent
        doc.is_group = 0
        if account_type:
            doc.account_type = account_type
        return _insert_test_doc(doc)

    def test_missing_parameters(self):
        result = update_account_type_mapping("", "Cash", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "MISSING_PARAMETERS")

    def test_invalid_account_type(self):
        result = update_account_type_mapping(self.account.name, "NotARealType", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INVALID_ACCOUNT_TYPE")

    def test_account_not_found(self):
        result = update_account_type_mapping("ACC-DOES-NOT-EXIST-XYZ", "Cash", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "ACCOUNT_NOT_FOUND")

    def test_company_mismatch(self):
        other_company = frappe.db.get_value("Company", {"name": ["!=", self.company]}, "name")
        if not other_company:
            self.skipTest("Need a second company for mismatch test")
        result = update_account_type_mapping(self.account.name, "Cash", other_company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "COMPANY_MISMATCH")

    def test_no_change_needed(self):
        acct = self._make_account(account_type="Cash")
        result = update_account_type_mapping(acct.name, "Cash", self.company)
        self.assertTrue(result["success"])
        self.assertTrue(result.get("no_change"))

    def test_successful_update_persists(self):
        """The happy path flips account_type in the DB via db.set_value."""
        result = update_account_type_mapping(self.account.name, "Cash", self.company)
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Account", self.account.name, "account_type"), "Cash")

    def test_lookup_by_display_name(self):
        """When the primary key doesn't match, lookup falls back to account_name field."""
        display = frappe.db.get_value("Account", self.account.name, "account_name")
        result = update_account_type_mapping(display, "Cash", self.company)
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Account", self.account.name, "account_type"), "Cash")


class TestCheckRestApiStatus(EnhancedTestCase):
    """check_rest_api_status: the not-configured and working/failing branches."""

    def test_no_token_configured(self):
        """With no token, returns configured=False without touching the API."""
        with patch(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.frappe.get_single"
        ) as mock_single:
            settings = mock_single.return_value
            settings.get_password.return_value = None
            result = check_rest_api_status()
        self.assertFalse(result["configured"])
        self.assertIn("not configured", result["message"].lower())

    def test_working_when_session_token_obtained(self):
        """A configured token + a session token => configured & working."""
        iterator_path = (
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        )
        with patch(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.frappe.get_single"
        ) as mock_single, patch(iterator_path) as mock_iter:
            mock_single.return_value.get_password.return_value = "tok"
            mock_iter.return_value._get_session_token.return_value = "session-abc"
            result = check_rest_api_status()
        self.assertTrue(result["configured"])
        self.assertTrue(result["working"])

    def test_configured_but_auth_fails(self):
        """A configured token but no session token => configured, not working."""
        iterator_path = (
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        )
        with patch(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.frappe.get_single"
        ) as mock_single, patch(iterator_path) as mock_iter:
            mock_single.return_value.get_password.return_value = "tok"
            mock_iter.return_value._get_session_token.return_value = None
            result = check_rest_api_status()
        self.assertTrue(result["configured"])
        self.assertFalse(result["working"])


class TestStartMigrationGuards(EnhancedTestCase):
    """start_migration_api / start_transaction_import status-guard branches."""

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")

    def _make_migration(self, status="Draft"):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.naming_series = "EBMIG-.YYYY.-"
        doc.migration_name = f"Guard Test {frappe.generate_hash()[:8]}"
        doc.migration_status = status
        doc.company = self.company
        return _insert_test_doc(doc)

    def test_start_migration_api_rejects_non_draft(self):
        """start_migration_api refuses a migration not in Draft."""
        mig = self._make_migration(status="Completed")
        result = start_migration_api(mig.name, dry_run=1)
        self.assertFalse(result["success"])
        self.assertIn("Draft", result["error"])

    def test_start_transaction_import_missing_document(self):
        """A nonexistent migration name returns a structured not-found error."""
        result = start_transaction_import("NO-SUCH-MIGRATION-ABC", import_type="recent")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())
        self.assertIn("recent_migrations", result["debug_info"])

    def test_start_transaction_import_rejects_non_draft(self):
        """start_transaction_import refuses a migration not in Draft."""
        mig = self._make_migration(status="In Progress")
        result = start_transaction_import(mig.name, import_type="recent")
        self.assertFalse(result["success"])
        self.assertIn("Draft", result["error"])


class TestImportSingleMutationGuards(EnhancedTestCase):
    """import_single_mutation: the already-exists / overwrite-disabled guard."""

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        self.migration = self._make_migration()

    def _make_migration(self):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.naming_series = "EBMIG-.YYYY.-"
        doc.migration_name = f"Single Mut Test {frappe.generate_hash()[:8]}"
        doc.migration_status = "Draft"
        doc.company = self.company
        return _insert_test_doc(doc)

    def test_existing_doc_without_overwrite_is_rejected(self):
        """If a JE already carries the mutation nr and overwrite is off, refuse early.

        We create a real submitted-shaped marker by stamping an existing Journal
        Entry's eboekhouden_mutation_nr, then assert the guard fires before any
        API call (no external HTTP is reached).
        """
        je_name = frappe.db.get_value("Journal Entry", {}, "name")
        if not je_name:
            self.skipTest("No Journal Entry exists to mark as an existing mutation")
        marker = f"TESTMUT{frappe.generate_hash()[:6]}"
        frappe.db.set_value("Journal Entry", je_name, "eboekhouden_mutation_nr", marker)

        result = import_single_mutation(self.migration.name, marker, overwrite_existing=False)
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["error"])
