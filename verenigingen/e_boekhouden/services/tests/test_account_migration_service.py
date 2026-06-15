"""
Account Migration Service Tests
===============================

Integration tests for AccountMigrationService using real ERPNext documents.

These tests exercise the eBoekhouden chart-of-accounts migration service end to
end against a dedicated, isolated test Company so that:

- Root account creation (Dutch COA structure) is verified against real DB state
- Account hierarchy / parent resolution is driven through real Account records
- Group account creation and bank-account creation paths run with real documents

No business logic is mocked. The only external boundary touched here is internal
Frappe document creation (the service does not call the eBoekhouden REST API for
any of the account-creation paths exercised below), so everything is directly
integration-testable.
"""

import frappe

from verenigingen.e_boekhouden.services.account_migration_service import AccountMigrationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountMigrationService(EnhancedTestCase):
    """Integration tests for AccountMigrationService with real ERPNext accounts."""

    COMPANY_NAME = "EBH Account Migration Test Co"
    COMPANY_ABBR = "EBHAMT"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create a dedicated, isolated company with an EMPTY Chart of Accounts.
        # We deliberately do NOT reuse the shared _get_test_company(): we need full
        # control over which group/root accounts exist so parent resolution and
        # ensure_root_accounts() assertions are deterministic. ERPNext otherwise
        # auto-creates a full default CoA (Bank Accounts, Tax Assets, Current
        # Assets, ...) which would make parent resolution non-deterministic, so we
        # suppress it with ignore_chart_of_accounts.
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
        self.service = AccountMigrationService(company=self.company)
        self._created_accounts = []

    def tearDown(self):
        # Several service methods (ensure_root_accounts, create_account via
        # validate_and_insert) call frappe.db.commit(), so the accounts they create
        # escape FrappeTestCase's per-test rollback and would pollute later tests in
        # this class. Because the company is dedicated to this test class, wipe ALL
        # of its accounts (and any linked Bank Accounts) here, children first.
        frappe.db.rollback()
        self._wipe_company_accounts()
        super().tearDown()

    def _wipe_company_accounts(self):
        for ba in frappe.get_all("Bank Account", filters={"company": self.company}, pluck="name"):
            try:
                frappe.delete_doc("Bank Account", ba, force=True, ignore_permissions=True)
            except Exception:
                pass
        # Delete leaf-first using rgt descending so children precede parents.
        accounts = frappe.get_all(
            "Account", filters={"company": self.company}, pluck="name", order_by="rgt desc"
        )
        for name in accounts:
            try:
                if frappe.db.exists("Account", name):
                    frappe.delete_doc("Account", name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    # -- helpers ---------------------------------------------------------------

    def _track(self, name):
        if name:
            self._created_accounts.append(name)

    def _make_account(
        self, account_name, root_type, is_group=1, parent=None, account_type=None, account_number=None
    ):
        """Create a real Account directly (test fixture, not via the service)."""
        doc = {
            "doctype": "Account",
            "account_name": account_name,
            "company": self.company,
            "root_type": root_type,
            "is_group": is_group,
        }
        if parent:
            doc["parent_account"] = parent
        if account_type:
            doc["account_type"] = account_type
        if account_number:
            doc["account_number"] = account_number
        account = frappe.get_doc(doc)
        account.flags.ignore_mandatory = True
        account.insert(ignore_permissions=True)
        self._track(account.name)
        return account.name

    def _ensure_dutch_roots(self):
        """Seed the Dutch root accounts via the service and track them."""
        result = self.service.ensure_root_accounts()
        # Track any roots that exist so tearDown can clean up.
        for acc in frappe.get_all(
            "Account",
            filters={"company": self.company, "parent_account": ["in", ["", None]], "is_group": 1},
            pluck="name",
        ):
            self._track(acc)
        return result

    # =========================================================================
    # settings property
    # =========================================================================

    def test_settings_property_uses_injected_settings(self):
        """Injected settings are returned without a DB fetch."""
        sentinel = object()
        service = AccountMigrationService(company=self.company, settings=sentinel)
        self.assertIs(service.settings, sentinel)

    def test_settings_property_lazy_loads_single(self):
        """When no settings injected, the single doctype is lazily loaded and cached."""
        service = AccountMigrationService(company=self.company)
        self.assertIsNone(service._settings)
        loaded = service.settings
        self.assertEqual(loaded.doctype, "E-Boekhouden Settings")
        # Cached: second access returns the same object.
        self.assertIs(service.settings, loaded)

    # =========================================================================
    # log_error
    # =========================================================================

    def test_log_error_uses_callback_when_provided(self):
        """log_error routes through the provided error callback."""
        captured = []

        def cb(message, record_type=None, record_data=None):
            captured.append((message, record_type, record_data))

        service = AccountMigrationService(company=self.company, error_callback=cb)
        service.log_error("boom", "account", {"code": "1"})
        self.assertEqual(captured, [("boom", "account", {"code": "1"})])

    def test_log_error_falls_back_to_frappe_log(self):
        """Without a callback, log_error writes a frappe Error Log (no crash)."""
        self.service.log_error("standalone error message", "account")
        frappe.db.commit()
        # Assert the specific Error Log row was written (not just "count did not shrink").
        # frappe.log_error(message, title) stores the message arg in the Error Log's
        # `method` field on this version, so match the message text there.
        logged = frappe.db.exists("Error Log", {"method": ["like", "%standalone error message%"]})
        self.assertTrue(logged, "log_error should write a frappe Error Log when no callback is set")

    # =========================================================================
    # ensure_root_accounts
    # =========================================================================

    def test_ensure_root_accounts_no_company(self):
        """Service with no company returns a failure dict."""
        service = AccountMigrationService(company=None)
        result = service.ensure_root_accounts()
        self.assertFalse(result["success"])
        self.assertIn("No company", result["error"])

    def test_ensure_root_accounts_creates_dutch_roots(self):
        """ensure_root_accounts creates the five Dutch root accounts."""
        result = self._ensure_dutch_roots()
        self.assertTrue(result["success"], msg=result)

        # Verify one root group account exists for each root_type.
        for root_type in ["Asset", "Liability", "Equity", "Income", "Expense"]:
            root = frappe.db.get_value(
                "Account",
                {
                    "company": self.company,
                    "root_type": root_type,
                    "is_group": 1,
                    "parent_account": ["in", ["", None]],
                },
                "name",
            )
            self.assertIsNotNone(root, f"No root account for {root_type}")

    def test_ensure_root_accounts_idempotent(self):
        """Running twice reports the second run as 'existing', not duplicated."""
        self._ensure_dutch_roots()
        result2 = self.service.ensure_root_accounts()
        self.assertTrue(result2["success"], msg=result2)
        self.assertEqual(len(result2["created"]), 0)
        self.assertGreaterEqual(len(result2["existing"]), 5)

    # =========================================================================
    # find_or_create_parent_group
    # =========================================================================

    def test_find_or_create_parent_group_finds_dutch_named_group(self):
        """A group whose name matches the Dutch mapping is found by root_type."""
        root = self._make_account("Activa", "Asset")
        group = self._make_account("Vlottende activa", "Asset", parent=root)
        found = self.service.find_or_create_parent_group("Asset", self.company)
        self.assertEqual(found, group)

    def test_find_or_create_parent_group_returns_non_root_group(self):
        """With no name match, the first non-root group under the root_type is used."""
        root = self._make_account("Opbrengsten", "Income")
        child_group = self._make_account("Verkoopopbrengsten XYZ", "Income", parent=root)
        found = self.service.find_or_create_parent_group("Income", self.company)
        # Should prefer a non-root (has parent) group.
        self.assertEqual(found, child_group)

    def test_find_or_create_parent_group_returns_root_when_only_root(self):
        """When only a root group exists, it is returned as a last resort."""
        root = self._make_account("Eigen Vermogen Test", "Equity")
        found = self.service.find_or_create_parent_group("Equity", self.company)
        self.assertEqual(found, root)

    def test_find_or_create_parent_group_none_when_empty(self):
        """No groups for the root_type -> None."""
        found = self.service.find_or_create_parent_group("Liability", self.company)
        self.assertIsNone(found)

    # =========================================================================
    # get_parent_account
    # =========================================================================

    def test_get_parent_account_bank_prefers_liquide_middelen(self):
        """A Bank account resolves to a 'Liquide middelen' asset group when present."""
        root = self._make_account("Activa", "Asset")
        liquide = self._make_account("Liquide middelen", "Asset", parent=root)
        parent = self.service.get_parent_account("Bank", "Asset", self.company)
        self.assertEqual(parent, liquide)

    def test_get_parent_account_income_prefers_named_group(self):
        """Income accounts resolve to an Opbrengsten/Inkomsten group."""
        root = self._make_account("Opbrengsten", "Income")
        inkomsten = self._make_account("Inkomsten Contributies", "Income", parent=root)
        parent = self.service.get_parent_account("Income Account", "Income", self.company)
        self.assertEqual(parent, inkomsten)

    def test_get_parent_account_expense_prefers_kosten(self):
        """Expense accounts resolve to a Kosten group."""
        root = self._make_account("Kosten Root", "Expense")
        kosten = self._make_account("Kosten Algemeen", "Expense", parent=root)
        parent = self.service.get_parent_account("Expense Account", "Expense", self.company)
        self.assertEqual(parent, kosten)

    def test_get_parent_account_falls_back_to_root(self):
        """With no matching group, the root account for the root_type is returned."""
        root = self._make_account("Activa", "Asset")
        parent = self.service.get_parent_account("Bank", "Asset", self.company)
        # No 'Liquide middelen' / 'Bank' group, falls back to the asset root.
        self.assertEqual(parent, root)

    def test_get_parent_account_tax_finds_liability_group(self):
        """Tax accounts resolve to a Belastingen / Duties-and-Taxes style group."""
        root = self._make_account("Passiva", "Liability")
        belastingen = self._make_account("Belastingen", "Liability", parent=root)
        parent = self.service.get_parent_account("Tax", "Liability", self.company)
        self.assertEqual(parent, belastingen)

    # =========================================================================
    # get_or_create_group_account
    # =========================================================================

    def test_get_or_create_group_account_no_mapping(self):
        """No mapping for the group code -> None."""
        result = self.service.get_or_create_group_account("999", "Asset", self.company)
        self.assertIsNone(result)

    def test_get_or_create_group_account_creates_new_group_dict_mapping(self):
        """New-format dict mapping creates a group under the matching root."""
        root = self._make_account("Activa", "Asset")
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"001": {"group_name": "Vaste activa", "root_type": "Asset"}},
        )
        name = service.get_or_create_group_account("001", root_type="Asset", company=self.company)
        self.assertIsNotNone(name)
        self._track(name)
        group = frappe.get_doc("Account", name)
        self.assertEqual(group.account_name, "Vaste activa")
        self.assertEqual(group.is_group, 1)
        self.assertEqual(group.parent_account, root)

    def test_get_or_create_group_account_legacy_string_mapping(self):
        """Legacy string mapping (group_name only) creates the group when root given."""
        self._make_account("Kosten Root", "Expense")  # seed the Expense root
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"055": "Personeelskosten"},
        )
        name = service.get_or_create_group_account("055", root_type="Expense", company=self.company)
        self.assertIsNotNone(name)
        self._track(name)
        self.assertEqual(frappe.get_doc("Account", name).account_name, "Personeelskosten")

    def test_get_or_create_group_account_returns_existing(self):
        """An existing group with the mapped name/root is returned, not duplicated."""
        root = self._make_account("Activa", "Asset")
        existing = self._make_account("Vaste activa", "Asset", parent=root)
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"001": {"group_name": "Vaste activa", "root_type": "Asset"}},
        )
        name = service.get_or_create_group_account("001", root_type="Asset", company=self.company)
        self.assertEqual(name, existing)

    def test_get_or_create_group_account_root_type_from_mapping(self):
        """root_type is read from the dict mapping when not passed as an argument."""
        root = self._make_account("Opbrengsten", "Income")
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"080": {"group_name": "Netto-omzet", "root_type": "Income"}},
        )
        name = service.get_or_create_group_account("080", company=self.company)
        self.assertIsNotNone(name)
        self._track(name)
        self.assertEqual(frappe.get_doc("Account", name).root_type, "Income")
        self.assertEqual(frappe.get_doc("Account", name).parent_account, root)

    def test_get_or_create_group_account_no_root_returns_none(self):
        """Dict mapping but no root account of that root_type -> None (cannot parent)."""
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"001": {"group_name": "Vaste activa", "root_type": "Asset"}},
        )
        # No Asset root seeded.
        name = service.get_or_create_group_account("001", root_type="Asset", company=self.company)
        self.assertIsNone(name)

    # =========================================================================
    # create_account
    # =========================================================================

    def test_create_account_invalid_data(self):
        """Missing code or name -> False, no account created."""
        self.assertFalse(self.service.create_account({"code": "", "description": ""}))
        self.assertFalse(self.service.create_account({"code": "1", "description": ""}))

    def test_create_account_income_under_dutch_root(self):
        """An income account is created as a child of the Dutch Income root."""
        self._ensure_dutch_roots()
        ok = self.service.create_account(
            {"code": "8000", "description": "Contributies", "category": "VW", "group": ""}
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "8000", "company": self.company}, "name")
        self.assertIsNotNone(name)
        self._track(name)
        acc = frappe.get_doc("Account", name)
        self.assertEqual(acc.root_type, "Income")
        self.assertEqual(acc.eboekhouden_grootboek_nummer, "8000")
        self.assertEqual(acc.is_group, 0)
        self.assertIsNotNone(acc.parent_account)

    def test_create_account_expense_under_dutch_root(self):
        """An expense account is created as a child of the Dutch Expense root."""
        self._ensure_dutch_roots()
        ok = self.service.create_account(
            {"code": "4000", "description": "Kantoorkosten", "category": "", "group": ""}
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "4000", "company": self.company}, "name")
        self.assertIsNotNone(name)
        self._track(name)
        self.assertEqual(frappe.get_doc("Account", name).root_type, "Expense")

    def test_create_account_strips_duplicated_code_prefix(self):
        """A description prefixed with 'code - ' has the code stripped from the name."""
        self._ensure_dutch_roots()
        ok = self.service.create_account(
            {"code": "8210", "description": "8210 - Advertenties", "category": "VW", "group": ""}
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "8210", "company": self.company}, "name")
        self._track(name)
        self.assertEqual(frappe.get_doc("Account", name).account_name, "Advertenties")

    def test_create_account_duplicate_by_number_skipped(self):
        """Re-creating the same account code is skipped (returns False)."""
        self._ensure_dutch_roots()
        data = {"code": "8001", "description": "Donaties", "category": "VW", "group": ""}
        self.assertTrue(self.service.create_account(data))
        name = frappe.db.get_value("Account", {"account_number": "8001", "company": self.company}, "name")
        self._track(name)
        # Second attempt is a no-op skip.
        self.assertFalse(self.service.create_account(data))

    def test_create_account_as_group_when_in_group_accounts(self):
        """Account codes listed in group_accounts are created as group accounts."""
        self._ensure_dutch_roots()
        service = AccountMigrationService(company=self.company, group_accounts={"8500"})
        ok = service.create_account(
            {"code": "8500", "description": "Omzetgroep", "category": "VW", "group": ""}
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "8500", "company": self.company}, "name")
        self._track(name)
        self.assertEqual(frappe.get_doc("Account", name).is_group, 1)

    def test_create_account_uses_group_mapping_parent(self):
        """When a group code maps to a group, the new account parents under it."""
        root = self._make_account("Activa", "Asset")
        service = AccountMigrationService(
            company=self.company,
            account_group_mappings={"001": {"group_name": "Vaste activa", "root_type": "Asset"}},
        )
        ok = service.create_account(
            {"code": "0100", "description": "Inventaris", "category": "BAL", "group": "001"}
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "0100", "company": self.company}, "name")
        self._track(name)
        # Track the created group too.
        group_name = frappe.db.get_value(
            "Account", {"account_name": "Vaste activa", "company": self.company}, "name"
        )
        self._track(group_name)
        acc = frappe.get_doc("Account", name)
        self.assertEqual(acc.parent_account, group_name)
        self.assertEqual(group_name and frappe.get_doc("Account", group_name).parent_account, root)

    def test_create_account_unclassified_pl_routed_to_expense(self):
        """A P&L (VW) account the classifier cannot type is routed to Expense, not dropped.

        A VW account the classifier cannot map returns an empty account_type and
        None root_type. Rather than skipping it (silent data loss during migration),
        the no-root_type guard routes P&L accounts to Expense. We use code '3500'
        precisely because its leading digit ('3') would land it under *Asset* via the
        generic code heuristic — getting Expense proves the VW-specific branch ran,
        not the digit fallback (a P&L account under Asset would corrupt reporting).
        """
        from verenigingen.e_boekhouden.services.account_classification_service import (
            AccountClassificationService,
        )

        self._ensure_dutch_roots()
        account_data = {"code": "3500", "description": "Onverdeelde kosten", "category": "VW", "group": ""}

        # Precondition: confirm the classifier genuinely returns no root_type for this
        # input on this site, so create_account is exercising the no-root_type guard
        # (and not coincidentally classifying it via a configured range). If a future
        # config change makes this classify normally, this assert fails loudly to flag
        # that the test no longer covers the guard.
        classification = AccountClassificationService(settings=self.service.settings).classify_account(
            account_data
        )
        self.assertIsNone(
            classification.root_type,
            "Precondition: classifier must return no root_type to exercise the guard",
        )

        ok = self.service.create_account(account_data)
        self.assertTrue(ok, "Unclassifiable P&L account should still be created, not dropped")
        name = frappe.db.get_value("Account", {"account_number": "3500", "company": self.company}, "name")
        self.assertIsNotNone(name)
        self._track(name)
        self.assertEqual(
            frappe.get_doc("Account", name).root_type,
            "Expense",
            "VW (P&L) account must land under Expense, not Asset",
        )

    def test_create_account_no_root_no_parent_skipped(self):
        """With no Dutch roots and no resolvable parent, creation is skipped."""
        # No roots seeded for this company in this test.
        ok = self.service.create_account(
            {"code": "8099", "description": "Orphan income", "category": "VW", "group": ""}
        )
        self.assertFalse(ok)
        self.assertFalse(frappe.db.exists("Account", {"account_number": "8099", "company": self.company}))

    def test_create_account_bank_creates_bank_account(self):
        """A bank-type account also creates a linked Bank Account record."""
        self._ensure_dutch_roots()
        # Seed an asset group so the bank account has a sensible parent.
        asset_root = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Asset", "parent_account": ["in", ["", None]]},
            "name",
        )
        self._make_account("Liquide middelen", "Asset", parent=asset_root)

        ok = self.service.create_account(
            {
                "code": "1200",
                "description": "Triodos - 19.83.96.716 - Algemeen",
                "category": "FIN",
                "group": "",
            }
        )
        self.assertTrue(ok)
        name = frappe.db.get_value("Account", {"account_number": "1200", "company": self.company}, "name")
        self._track(name)
        acc = frappe.get_doc("Account", name)
        self.assertEqual(acc.account_type, "Bank")
        # A Bank Account linked to this account should exist.
        bank_acc = frappe.db.exists("Bank Account", {"account": name})
        self.assertTrue(bank_acc, "Bank Account record should be created for bank COA account")
        if bank_acc:
            ba_name = frappe.db.get_value("Bank Account", {"account": name}, "name")
            try:
                frappe.delete_doc("Bank Account", ba_name, force=True, ignore_permissions=True)
            except Exception:
                pass

    # =========================================================================
    # create_bank_account_for_coa_account
    # =========================================================================

    def test_create_bank_account_non_bank_returns_none(self):
        """A non-bank-looking account does not produce a Bank Account."""
        root = self._make_account("Activa", "Asset")
        name = self._make_account(
            "Vooruitbetaalde kosten", "Asset", is_group=0, parent=root, account_number="1400"
        )
        account_doc = frappe.get_doc("Account", name)
        result = self.service.create_bank_account_for_coa_account(account_doc, "Vooruitbetaalde kosten")
        self.assertIsNone(result)

    def test_create_bank_account_for_bank_account(self):
        """A recognisable bank account produces a Bank Account record."""
        root = self._make_account("Activa", "Asset")
        name = self._make_account(
            "Triodos - 19.83.96.716 - Zakelijk",
            "Asset",
            is_group=0,
            parent=root,
            account_type="Bank",
            account_number="1210",
        )
        account_doc = frappe.get_doc("Account", name)
        result = self.service.create_bank_account_for_coa_account(
            account_doc, "Triodos - 19.83.96.716 - Zakelijk"
        )
        self.assertIsNotNone(result)
        self.assertTrue(frappe.db.exists("Bank Account", result))
        try:
            frappe.delete_doc("Bank Account", result, force=True, ignore_permissions=True)
        except Exception:
            pass
