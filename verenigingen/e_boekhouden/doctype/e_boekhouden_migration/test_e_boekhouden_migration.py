"""
E-Boekhouden Migration controller tests
========================================

Integration tests for the EBoekhoudenMigration DocType controller and its
module-level @frappe.whitelist endpoints.

Design notes
------------
- Base class is EnhancedTestCase (dominant convention in this app).
- A dedicated, isolated Company ("EBH Migration Test Co") is created with an
  EMPTY Chart of Accounts (ignore_chart_of_accounts) so account-type and
  recommendation assertions are deterministic and don't depend on ERPNext's
  auto-generated default CoA.
- NO business logic is mocked. The only true external boundary is the
  eBoekhouden REST/SOAP HTTP API; the endpoints exercised below either never
  reach the API (they fail the Draft-status / parameter guards first) or operate
  purely on real ERPNext DB state (Account documents). The status-guard endpoints
  return BEFORE enqueuing the background job, so no HTTP call is made.
- Endpoints whose only meaningful path is "configure + frappe.enqueue the real
  REST import" are exercised only up to the point where they would enqueue, by
  driving the Draft-status guard and the parameter-validation guards. We do NOT
  run a full live migration (that requires the external API + a populated
  eBoekhouden account).
"""

import json
import unittest

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    _migration_phase_failed,
    _resolve_migration_status,
    cleanup_chart_of_accounts,
    get_account_type_recommendations,
    start_migration_api,
    start_transaction_import,
    update_account_type_mapping,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestEBoekhoudenMigration(EnhancedTestCase):
    """Controller + endpoint tests for E-Boekhouden Migration."""

    COMPANY_NAME = "EBH Migration Test Co"
    COMPANY_ABBR = "EBHMT"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Company", cls.COMPANY_NAME):
            frappe.local.flags.ignore_chart_of_accounts = True
            try:
                company = frappe.get_doc(
                    {
                        "doctype": "Company",
                        "company_name": cls.COMPANY_NAME,
                        "abbr": cls.COMPANY_ABBR,
                        "default_currency": "EUR",
                        "country": "Netherlands",
                    }
                )
                company.flags.ignore_permissions = True
                company.insert(ignore_permissions=True)
                frappe.db.commit()
            finally:
                frappe.local.flags.ignore_chart_of_accounts = False
        cls.company = cls.COMPANY_NAME

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._created_accounts = []
        self._parent_groups = {}

    def _make_root_group(self, root_type):
        """Get-or-create a group (root) Account of the given root_type to parent leaves under.

        ERPNext requires non-group accounts to have a group parent; a leaf with no
        parent is treated as a root account and must itself be a group. We create a
        single group per root_type for this company.
        """
        if root_type in self._parent_groups:
            return self._parent_groups[root_type]
        name = f"EBHMT {root_type} Group"
        existing = frappe.db.get_value("Account", {"company": self.company, "account_name": name}, "name")
        if existing:
            self._parent_groups[root_type] = existing
            return existing
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": name,
                "company": self.company,
                "root_type": root_type,
                "is_group": 1,
            }
        )
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        self._created_accounts.append(doc.name)
        self._parent_groups[root_type] = doc.name
        return doc.name

    def tearDown(self):
        # update_account_type_mapping uses frappe.db.set_value (no commit) but
        # other endpoints commit; roll back then wipe any accounts this test made.
        frappe.db.rollback()
        for name in reversed(self._created_accounts):
            try:
                if frappe.db.exists("Account", name):
                    frappe.delete_doc("Account", name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    # -- helpers ---------------------------------------------------------------

    def _make_migration(self, **kwargs):
        """Create a real E-Boekhouden Migration document (Draft)."""
        doc = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": kwargs.pop("migration_name", "Test Migration"),
                "company": kwargs.pop("company", self.company),
                "migration_status": "Draft",
                **kwargs,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _make_account(self, account_name, root_type="Asset", account_type=None, eb_number=None):
        doc = {
            "doctype": "Account",
            "account_name": account_name,
            "company": self.company,
            "root_type": root_type,
            "is_group": 0,
            "parent_account": self._make_root_group(root_type),
        }
        if account_type:
            doc["account_type"] = account_type
        if eb_number:
            doc["eboekhouden_grootboek_nummer"] = eb_number
        account = frappe.get_doc(doc)
        account.flags.ignore_mandatory = True
        account.insert(ignore_permissions=True)
        self._created_accounts.append(account.name)
        return account

    # ======================================================================
    # validate()  --  date-range business rules
    # ======================================================================

    def test_validate_rejects_partial_date_range_when_migrating_transactions(self):
        """Specifying only one of date_from/date_to with transactions must throw."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._make_migration(
                migration_name="Partial Date Range",
                migrate_transactions=1,
                date_from="2024-01-01",
                # date_to deliberately omitted
            )
        self.assertIn("both Date From and Date To are required", str(ctx.exception))

    def test_validate_rejects_inverted_date_range(self):
        """date_from after date_to must throw regardless of transactions flag."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._make_migration(
                migration_name="Inverted Dates",
                date_from="2024-12-31",
                date_to="2024-01-01",
            )
        self.assertIn("Date From cannot be after Date To", str(ctx.exception))

    def test_validate_allows_empty_dates_for_import_all(self):
        """Empty dates mean 'import everything' and must be accepted."""
        doc = self._make_migration(migration_name="Import All", migrate_transactions=1)
        self.assertEqual(doc.migration_status, "Draft")
        self.assertFalse(doc.date_from)
        self.assertFalse(doc.date_to)

    def test_validate_allows_full_valid_date_range(self):
        doc = self._make_migration(
            migration_name="Valid Range",
            migrate_transactions=1,
            date_from="2024-01-01",
            date_to="2024-12-31",
        )
        self.assertEqual(str(doc.date_from), "2024-01-01")
        self.assertEqual(str(doc.date_to), "2024-12-31")

    # ======================================================================
    # Pure helpers: _migration_phase_failed / _resolve_migration_status
    # ======================================================================

    def test_phase_failed_on_success_dict(self):
        self.assertFalse(_migration_phase_failed({"success": True, "message": "ok"}))

    def test_phase_failed_on_failure_dict(self):
        self.assertTrue(_migration_phase_failed({"success": False, "message": "boom"}))

    def test_phase_failed_treats_non_dict_as_failure(self):
        # "fail loud rather than silently record a broken phase as Completed"
        self.assertTrue(_migration_phase_failed(None))
        self.assertTrue(_migration_phase_failed("not a dict"))
        self.assertTrue(_migration_phase_failed({"message": "missing success key"}))

    def test_resolve_status_completed_when_no_failures(self):
        status, operation = _resolve_migration_status([])
        self.assertEqual(status, "Completed")
        self.assertEqual(operation, "Migration completed successfully")

    def test_resolve_status_failed_lists_failed_phases(self):
        status, operation = _resolve_migration_status(["Chart of Accounts", "Transactions"])
        self.assertEqual(status, "Failed")
        self.assertIn("Chart of Accounts", operation)
        self.assertIn("Transactions", operation)
        self.assertTrue(operation.startswith("Migration finished with errors in:"))

    # ======================================================================
    # parse_account_group_mappings()
    # ======================================================================

    def test_parse_group_mappings_prefers_structured_table(self):
        """When group_type_mappings table is present, it wins and includes root_type."""
        doc = self._make_migration(migration_name="Group Mappings Structured")
        settings = frappe._dict(
            {
                "group_type_mappings": [
                    frappe._dict(
                        {
                            "group_code": "001",
                            "group_name": "Vaste activa",
                            "root_type": "Asset",
                            "account_type": "Fixed Asset",
                        }
                    ),
                    # Incomplete row (missing root_type) must be skipped
                    frappe._dict({"group_code": "002", "group_name": "Incomplete", "root_type": None}),
                ],
                "balance_sheet_group_mappings": "999 Should Be Ignored",
            }
        )
        mappings = doc.parse_account_group_mappings(settings)
        self.assertIn("001", mappings)
        self.assertEqual(mappings["001"]["group_name"], "Vaste activa")
        self.assertEqual(mappings["001"]["root_type"], "Asset")
        self.assertEqual(mappings["001"]["account_type"], "Fixed Asset")
        # Incomplete row skipped, and the legacy text field is NOT consulted.
        self.assertNotIn("002", mappings)
        self.assertNotIn("999", mappings)

    def test_parse_group_mappings_legacy_text_fields(self):
        """With no structured table, legacy text fields are parsed (code/name only)."""
        doc = self._make_migration(migration_name="Group Mappings Legacy")
        settings = frappe._dict(
            {
                "group_type_mappings": [],
                "balance_sheet_group_mappings": "001 Vaste activa\n002 Vlottende activa",
                "pl_group_mappings": "800 Opbrengsten",
            }
        )
        mappings = doc.parse_account_group_mappings(settings)
        self.assertEqual(mappings["001"], "Vaste activa")
        self.assertEqual(mappings["002"], "Vlottende activa")
        self.assertEqual(mappings["800"], "Opbrengsten")

    # ======================================================================
    # update_account_type_mapping()  --  rich validation + DB side-effect
    # ======================================================================

    def test_update_account_type_missing_parameters(self):
        result = update_account_type_mapping("", "Bank", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "MISSING_PARAMETERS")

    def test_update_account_type_invalid_type(self):
        account = self._make_account("UpdateType Invalid", root_type="Asset")
        result = update_account_type_mapping(account.name, "Totally Bogus Type", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INVALID_ACCOUNT_TYPE")
        self.assertIn("Totally Bogus Type", result["error"])

    def test_update_account_type_account_not_found(self):
        result = update_account_type_mapping("Definitely Nonexistent Account XYZ", "Bank", self.company)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "ACCOUNT_NOT_FOUND")

    def test_update_account_type_company_mismatch(self):
        """Account resolved by primary key but belonging to another company is rejected."""
        account = self._make_account("UpdateType CompanyCheck", root_type="Asset")
        result = update_account_type_mapping(account.name, "Bank", "Some Other Company")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "COMPANY_MISMATCH")
        self.assertIn(self.company, result["error"])

    def test_update_account_type_no_change_short_circuits(self):
        account = self._make_account("UpdateType NoChange", root_type="Asset", account_type="Bank")
        result = update_account_type_mapping(account.name, "Bank", self.company)
        self.assertTrue(result["success"])
        self.assertTrue(result.get("no_change"))

    def test_update_account_type_success_persists_change(self):
        """Happy path: account_type is changed in the DB via set_value."""
        account = self._make_account("UpdateType Success", root_type="Asset", account_type="Current Asset")
        result = update_account_type_mapping(account.name, "Bank", self.company)
        self.assertTrue(result["success"], msg=result)
        self.assertIn("Bank", result["message"])
        # Real DB side-effect verification
        self.assertEqual(frappe.db.get_value("Account", account.name, "account_type"), "Bank")

    def test_update_account_type_lookup_by_display_name(self):
        """account_name (display field) resolution path."""
        account = self._make_account(
            "UpdateType ByDisplayName", root_type="Asset", account_type="Current Asset"
        )
        # account.account_name is the display value (e.g. "UpdateType ByDisplayName - EBHMT")
        result = update_account_type_mapping(account.account_name, "Bank", self.company)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(frappe.db.get_value("Account", account.name, "account_type"), "Bank")

    # ======================================================================
    # start_migration_api()  --  Draft-status guard (no API/enqueue reached)
    # ======================================================================

    def test_start_migration_api_rejects_non_draft(self):
        doc = self._make_migration(migration_name="Already Running")
        frappe.db.set_value("E-Boekhouden Migration", doc.name, "migration_status", "In Progress")
        result = start_migration_api(doc.name, dry_run=1)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Migration must be in Draft status to start")

    # ======================================================================
    # start_transaction_import()  --  missing-doc & status guards
    # ======================================================================

    def test_start_transaction_import_missing_document(self):
        result = start_transaction_import("EBMIG-NONEXISTENT-9999")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])
        self.assertIn("recent_migrations", result.get("debug_info", {}))

    def test_start_transaction_import_rejects_non_draft(self):
        doc = self._make_migration(migration_name="TxnImport NonDraft")
        frappe.db.set_value("E-Boekhouden Migration", doc.name, "migration_status", "Completed")
        result = start_transaction_import(doc.name)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Migration must be in Draft status to start")

    # ======================================================================
    # cleanup_chart_of_accounts()  --  delegation to cleanup_utils
    # ======================================================================

    def test_cleanup_chart_of_accounts_delegates_and_returns_dict(self):
        """With no imported accounts in the isolated company, cleanup is a safe no-op."""
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts=False)
        self.assertIsInstance(result, dict)
        # cleanup_impl reports success and should not have deleted anything in our
        # empty isolated company.
        self.assertIn("success", result)

    # ======================================================================
    # check_migration_data_quality()  --  delegation + db_set side-effect
    # ======================================================================

    def test_check_migration_data_quality_writes_report(self):
        from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            check_migration_data_quality,
        )

        doc = self._make_migration(migration_name="DataQuality Check")
        result = check_migration_data_quality(doc.name)
        self.assertTrue(result["success"], msg=result)
        self.assertIn("report", result)
        # Side-effect: the quality report is serialized into migration_summary.
        stored = frappe.db.get_value("E-Boekhouden Migration", doc.name, "migration_summary")
        self.assertIsNotNone(stored)
        parsed = json.loads(stored)
        self.assertEqual(parsed, result["report"])

    # ======================================================================
    # get_account_type_recommendations()  --  real SQL + classification
    # ======================================================================

    def test_account_type_recommendations_only_untyped_by_default(self):
        """Default (show_all=False) returns only accounts lacking a type."""
        typed = self._make_account(
            "Recommend Typed", root_type="Asset", account_type="Bank", eb_number="10001"
        )
        untyped = self._make_account("Recommend Untyped", root_type="Income", eb_number="80001")
        frappe.db.commit()

        result = get_account_type_recommendations(self.company, show_all=False)
        self.assertTrue(result["success"], msg=result)
        accounts = {r["account"] for r in result["recommendations"]}
        self.assertIn(untyped.name, accounts)
        self.assertNotIn(typed.name, accounts)
        # Each recommendation must carry a recommended_type from the classifier.
        for rec in result["recommendations"]:
            if rec["account"] == untyped.name:
                self.assertIn("recommended_type", rec)
                self.assertEqual(rec["account_code"], "80001")
                self.assertEqual(rec["current_type"], "Not Set")

    def test_account_type_recommendations_show_all_includes_typed(self):
        typed = self._make_account(
            "Recommend All Typed", root_type="Asset", account_type="Bank", eb_number="10002"
        )
        frappe.db.commit()
        result = get_account_type_recommendations(self.company, show_all=True)
        self.assertTrue(result["success"], msg=result)
        accounts = {r["account"]: r for r in result["recommendations"]}
        self.assertIn(typed.name, accounts)
        self.assertEqual(accounts[typed.name]["current_type"], "Bank")

    def test_account_type_recommendations_ignores_accounts_without_eb_number(self):
        """Accounts without eboekhouden_grootboek_nummer are excluded by the SQL filter."""
        no_eb = self._make_account("Recommend NoEB", root_type="Asset")  # no eb_number
        frappe.db.commit()
        result = get_account_type_recommendations(self.company, show_all=True)
        self.assertTrue(result["success"], msg=result)
        accounts = {r["account"] for r in result["recommendations"]}
        self.assertNotIn(no_eb.name, accounts)


if __name__ == "__main__":
    unittest.main()
