"""Real-DB coverage for EBoekhoudenMigration account/CoA helper methods (Cluster A).

Covers the pure / DB-only account helpers of the migration controller
(``verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py``):

* ``do_clear_existing_accounts`` (no-company / empty / dry-run / real-delete-with-GL / delete-failure)
* ``get_account_type_recommendations`` (show_all branches / classification / code-less skip / empty)
* ``cleanup_chart_of_accounts`` (module-level delegate, default safe path)
* ``get_suspense_account`` (the ``%suspense%`` and ``%temporary%`` name-match branches
  not already exercised in test_eboekhouden_doctype_coverage.py)
* ``test_group_mappings`` (settings -> parse_account_group_mappings count)

No business logic is mocked: every method is exercised against real DB rows.
A dedicated company is used wherever accounts are deleted/created so the shared
chart of accounts is never disturbed.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_controller_accounts_coverage
"""

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    cleanup_chart_of_accounts,
    get_account_type_recommendations,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMigrationControllerAccounts(EnhancedTestCase):
    """Account/CoA helpers of the E-Boekhouden Migration controller."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Dedicated company so account create/delete never touches the shared CoA.
        cls.company = cls._persist_company("TEST EBkh MigCtrl Co", "TEMC")
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_company(cls, name, abbr):
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = abbr
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert()
        frappe.db.commit()
        return name

    def setUp(self):
        super().setUp()
        self.has_grootboek_field = frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer")

    # ------------------------------------------------------------------ helpers
    def _make_migration(self, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop("migration_name", f"Test Migration {frappe.generate_hash()[:8]}")
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        return doc

    def _leaf_parent(self, root_type="Expense", company=None):
        company = company or self.company
        return frappe.db.get_value(
            "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
        )

    def _make_account(
        self, account_name, *, company=None, account_number="", grootboek=None, root_type="Expense"
    ):
        company = company or self.company
        abbr = frappe.db.get_value("Company", company, "abbr")
        full = f"{account_name} - {abbr}"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = account_name
        doc.company = company
        doc.parent_account = self._leaf_parent(root_type, company)
        doc.root_type = root_type
        doc.is_group = 0
        if account_number:
            doc.account_number = account_number
        if grootboek is not None and self.has_grootboek_field:
            doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert()
        self._track_test_document("Account", doc.name)
        return doc.name

    def _purge_company_imported_accounts(self):
        """Remove any account_number-flagged accounts on the dedicated company.

        Keeps do_clear_existing_accounts tests deterministic regardless of
        sibling-test ordering within this dedicated company.
        """
        rows = frappe.get_all(
            "Account",
            filters={"company": self.company, "account_number": ["!=", ""]},
            pluck="name",
            order_by="lft desc",
        )
        for name in rows:
            frappe.db.delete("GL Entry", {"account": name})
            frappe.delete_doc("Account", name, force=True)
        frappe.db.commit()

    # ------------------------------------------------- do_clear_existing_accounts
    def test_clear_existing_accounts_no_company(self):
        """No default_company on settings -> error result, no work done."""
        doc = self._make_migration()
        result = doc.do_clear_existing_accounts(frappe._dict(default_company=None))
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No default company set")

    def test_clear_existing_accounts_none_to_clear(self):
        """A company with zero account_number-flagged accounts -> deleted_count 0."""
        self._purge_company_imported_accounts()
        doc = self._make_migration()
        result = doc.do_clear_existing_accounts(frappe._dict(default_company=self.company))
        self.assertTrue(result["success"])
        self.assertEqual(result["deleted_count"], 0)
        self.assertIn("No existing imported accounts", result["message"])

    def test_clear_existing_accounts_dry_run_does_not_delete(self):
        """dry_run=True reports the count but deletes nothing."""
        self._purge_company_imported_accounts()
        acct = self._make_account("EBkh DryRun Acct", account_number="80001")
        doc = self._make_migration()
        doc.dry_run = 1
        result = doc.do_clear_existing_accounts(frappe._dict(default_company=self.company))
        self.assertTrue(result["success"])
        # Dry run reports zero deleted (the field is the count actually removed).
        self.assertEqual(result["deleted_count"], 0)
        self.assertIn("Would delete 1", result["message"])
        # The account must still exist - nothing was actually deleted.
        self.assertTrue(frappe.db.exists("Account", acct))

    def test_clear_existing_accounts_real_delete_with_gl_entries(self):
        """Real delete of an account_number account, including its GL-entry purge."""
        self._purge_company_imported_accounts()
        acct = self._make_account("EBkh Clear Acct", account_number="80002")

        # Seed an orphan GL Entry so the has_gl_entries purge branch (lines ~238-240) runs.
        cost_center = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")
        ge = frappe.new_doc("GL Entry")
        ge.posting_date = frappe.utils.today()
        ge.account = acct
        ge.company = self.company
        ge.debit = 5
        ge.credit = 0
        ge.cost_center = cost_center
        ge.voucher_type = "Journal Entry"
        ge.voucher_no = "EBKH-NONEXISTENT-VOUCHER"
        ge.db_insert()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("GL Entry", {"account": acct}))

        doc = self._make_migration()
        doc.dry_run = 0
        result = doc.do_clear_existing_accounts(frappe._dict(default_company=self.company))

        self.assertTrue(result["success"])
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result.get("errors"), [])
        # Both the account and its GL entries are gone.
        self.assertFalse(frappe.db.exists("Account", acct))
        self.assertFalse(frappe.db.exists("GL Entry", {"account": acct}))

    def test_clear_existing_accounts_delete_failure_records_error(self):
        """An account that cannot be deleted is recorded in errors, others still deleted.

        Targeted failure: a FLAGGED group account (account_number set, so it is in
        scope) that still contains an UNFLAGGED child. The unflagged child is never
        in the deletion set (the filter requires account_number != ""), so when the
        method force-deletes the group its NestedSet on_trash raises
        NestedSetChildExistsError - it lands in ``errors`` while a sibling flagged
        leaf deletes successfully.
        """
        # This test deliberately drives the delete-failure path, which writes an
        # Error Log via self.log_error(...); mark it expected so the guard ignores it.
        self.expectErrorLog("account_deletion", "Failed to delete account")

        self._purge_company_imported_accounts()
        parent_root = self._leaf_parent("Expense")

        # Flagged GROUP account (in scope) ...
        gdoc = frappe.new_doc("Account")
        gdoc.account_name = "EBkh Clear Group"
        gdoc.company = self.company
        gdoc.parent_account = parent_root
        gdoc.root_type = "Expense"
        gdoc.is_group = 1
        gdoc.account_number = "80010"
        gdoc.insert()
        self._track_test_document("Account", gdoc.name)
        group_full = gdoc.name

        # ... containing an UNFLAGGED child (no account_number -> never in scope,
        # so it survives and keeps the group non-empty -> group delete must fail).
        cdoc = frappe.new_doc("Account")
        cdoc.account_name = "EBkh Clear Unflagged Child"
        cdoc.company = self.company
        cdoc.parent_account = group_full
        cdoc.root_type = "Expense"
        cdoc.is_group = 0
        cdoc.insert()
        self._track_test_document("Account", cdoc.name)
        child_full = cdoc.name

        # A separate flagged leaf that SHOULD delete cleanly.
        ok_leaf = self._make_account("EBkh Clear OK Leaf", account_number="80012")

        frappe.db.commit()

        doc = self._make_migration()
        doc.dry_run = 0
        result = doc.do_clear_existing_accounts(frappe._dict(default_company=self.company))

        self.assertTrue(result["success"])
        # The standalone flagged leaf deleted; the non-empty group failed.
        self.assertFalse(frappe.db.exists("Account", ok_leaf))
        self.assertTrue(frappe.db.exists("Account", group_full))
        self.assertTrue(frappe.db.exists("Account", child_full))
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("80010", result["errors"][0])

    # ------------------------------------------ get_account_type_recommendations
    def test_account_type_recommendations_empty_when_no_grootboek(self):
        """A company with no grootboek-flagged accounts yields an empty list."""
        # Use a throwaway company that has no eboekhouden accounts.
        empty_company = self._persist_company("TEST EBkh MigCtrl Empty Co", "TEME")
        result = get_account_type_recommendations(empty_company, show_all=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["recommendations"], [])

    def test_account_type_recommendations_classifies_flagged_account(self):
        """show_all=True returns a recommendation per grootboek-flagged account.

        The recommended_type must match what AccountClassificationService returns
        for the same code/description - derived live, not hard-coded.
        """
        if not self.has_grootboek_field:
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")

        rec_company = self._persist_company("TEST EBkh MigCtrl Rec Co", "TEMR")
        acct = self._make_account("EBkh Rec Bank", company=rec_company, grootboek="10100", root_type="Asset")

        from verenigingen.e_boekhouden.services.account_classification_service import (
            AccountClassificationService,
        )

        expected = (
            AccountClassificationService()
            .classify_account({"code": "10100", "description": "EBkh Rec Bank", "category": "", "group": ""})
            .account_type
        )

        result = get_account_type_recommendations(rec_company, show_all=True)
        self.assertTrue(result["success"])
        match = [r for r in result["recommendations"] if r["account"] == acct]
        self.assertEqual(len(match), 1, "flagged account must appear exactly once")
        self.assertEqual(match[0]["account_code"], "10100")
        self.assertEqual(match[0]["recommended_type"], expected)

    def test_account_type_recommendations_show_all_vs_untyped(self):
        """show_all=False excludes accounts that already have an account_type set."""
        if not self.has_grootboek_field:
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")

        rec_company = self._persist_company("TEST EBkh MigCtrl ShowAll Co", "TEMS")
        # Typed account: has account_type -> excluded from the untyped query.
        typed = self._make_account(
            "EBkh Typed Bank", company=rec_company, grootboek="10200", root_type="Asset"
        )
        frappe.db.set_value("Account", typed, "account_type", "Bank")
        frappe.db.commit()

        all_result = get_account_type_recommendations(rec_company, show_all=True)
        untyped_result = get_account_type_recommendations(rec_company, show_all=False)
        self.assertTrue(all_result["success"])
        self.assertTrue(untyped_result["success"])

        all_accounts = {r["account"] for r in all_result["recommendations"]}
        untyped_accounts = {r["account"] for r in untyped_result["recommendations"]}
        # show_all sees the typed account; the untyped-only query does not.
        self.assertIn(typed, all_accounts)
        self.assertNotIn(typed, untyped_accounts)

    # --------------------------------------------- cleanup_chart_of_accounts (fn)
    def test_cleanup_chart_of_accounts_safe_default(self):
        """Module-level delegate runs the safe (delete_all=False) path sensibly."""
        clean_company = self._persist_company("TEST EBkh MigCtrl Clean Co", "TEMK")
        result = cleanup_chart_of_accounts(clean_company, delete_all_accounts=False)
        self.assertTrue(result["success"])
        self.assertIn("results", result)
        # Fresh company, no eBoekhouden accounts -> nothing deleted (proves
        # delete_all=False scoped to flagged accounts, not the whole CoA).
        self.assertEqual(result["results"]["accounts_deleted"], 0)

    # ------------------------------------------------------ get_suspense_account
    def test_get_suspense_account_matches_suspense_named_account(self):
        """A %suspense%-named account is returned by the first lookup branch."""
        susp_company = self._persist_company("TEST EBkh MigCtrl Susp Co", "TEMP")
        susp = self._make_account("EBkh Suspense Holding", company=susp_company, root_type="Liability")
        doc = self._make_migration()
        self.assertEqual(doc.get_suspense_account(susp_company), susp)

    def test_get_suspense_account_falls_back_to_temporary(self):
        """With no %suspense% account, a %temporary%-named account is returned."""
        temp_company = self._persist_company("TEST EBkh MigCtrl Temp Co", "TEMT")
        # Guard: ensure no suspense account exists so the temporary branch is hit.
        self.assertIsNone(
            frappe.db.get_value(
                "Account",
                {"company": temp_company, "account_name": ["like", "%suspense%"]},
                "name",
            )
        )
        temp = self._make_account("EBkh Temporary Holding", company=temp_company, root_type="Liability")
        doc = self._make_migration()
        self.assertEqual(doc.get_suspense_account(temp_company), temp)

    # ------------------------------------------------------- test_group_mappings
    def test_group_mappings_counts_structured_table(self):
        """test_group_mappings returns the count of configured group mappings.

        Configures group_type_mappings on the E-Boekhouden Settings Single (via
        db writes, never .save() - api_token is mandatory) and asserts the count
        and field-exists flags returned by the whitelisted method.
        """
        settings_name = "E-Boekhouden Settings"
        meta = frappe.get_meta(settings_name)
        if not meta.has_field("group_type_mappings"):
            self.skipTest("group_type_mappings field not present on settings")

        # Snapshot existing rows so we restore them after the test.
        existing = frappe.get_all(
            "E-Boekhouden Group Type Mapping",
            filters={"parent": settings_name, "parenttype": settings_name},
            fields=["group_code", "group_name", "root_type", "account_type"],
            order_by="idx",
        )

        def _set_rows(rows):
            frappe.db.delete(
                "E-Boekhouden Group Type Mapping",
                {"parent": settings_name, "parenttype": settings_name},
            )
            for idx, r in enumerate(rows, start=1):
                child = frappe.new_doc("E-Boekhouden Group Type Mapping")
                child.parent = settings_name
                child.parenttype = settings_name
                child.parentfield = "group_type_mappings"
                child.idx = idx
                child.group_code = r["group_code"]
                child.group_name = r["group_name"]
                child.root_type = r["root_type"]
                if r.get("account_type"):
                    child.account_type = r["account_type"]
                child.insert()
            frappe.db.commit()
            frappe.clear_document_cache(settings_name, settings_name)

        try:
            rows = [
                {"group_code": "TST001", "group_name": "Test Vaste activa", "root_type": "Asset"},
                {"group_code": "TST002", "group_name": "Test Schulden", "root_type": "Liability"},
                {"group_code": "TST003", "group_name": "Test Omzet", "root_type": "Income"},
            ]
            _set_rows(rows)

            doc = self._make_migration()
            result = doc.test_group_mappings()

            self.assertTrue(result["success"])
            self.assertEqual(result["mappings_count"], len(rows))
            self.assertTrue(result["balance_sheet_field_exists"])
            self.assertTrue(result["pl_field_exists"])
            # The parsed mapping carries the structured root_type per group code.
            self.assertEqual(result["mappings"]["TST001"]["root_type"], "Asset")
        finally:
            _set_rows(existing)
