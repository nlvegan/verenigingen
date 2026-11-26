"""#1398: e-Boekhouden parent/group lookups must not take a silent first LIKE match.

Real flow: AccountMigrationService.get_parent_account / find_or_create_parent_group and
AccountOrganizationService._ensure_*_group against the shared EUR test company's real chart
(which already carries "Tax Assets", "Cash In Hand", "Current Assets"). Competing accounts are
real inserted Account rows, no mocks and no direct field writes.
"""

import frappe

from verenigingen.e_boekhouden.services.account_migration_service import AccountMigrationService
from verenigingen.e_boekhouden.services.account_organization_service import AccountOrganizationService
from verenigingen.e_boekhouden.utils.account_label_lookup import (
    AmbiguousAccountLabel,
    find_account_by_label,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestAccountLabelLookup1398(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _group(self, account_name, parent_account_name, root_type):
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "account_name": parent_account_name, "is_group": 1}, "name"
        )
        self.assertTrue(parent, f"fixture chart lacks {parent_account_name}")
        acc = frappe.new_doc("Account")
        acc.account_name = account_name
        acc.company = self.company
        acc.parent_account = parent
        acc.root_type = root_type
        acc.is_group = 1
        acc.insert()
        return acc.name

    def _named(self, account_name):
        return frappe.db.get_value("Account", {"company": self.company, "account_name": account_name}, "name")

    # ---- migration service -------------------------------------------------
    def test_exact_label_wins_over_newer_superstring_account(self):
        tax_assets = self._named("Tax Assets")
        # inserted AFTER the real one: develop's get_value orders creation DESC and picks this.
        self._group("Deferred Tax Assets", "Current Assets", "Asset")
        parent = AccountMigrationService(self.company).get_parent_account("Tax", "Asset", self.company)
        self.assertEqual(parent, tax_assets)

    def test_ambiguous_substring_label_is_not_picked(self):
        extra_a = self._group("Zz1398 Cash Holding A", "Current Assets", "Asset")
        extra_b = self._group("Zz1398 Cash Holding B", "Current Assets", "Asset")
        # "Cash" has no exact account_name here ("Cash In Hand" is not "Cash"): three groups
        # contain it, so the label must be refused rather than any one of them picked.
        parent = AccountMigrationService(self.company).get_parent_account("Cash", "Asset", self.company)
        self.assertNotIn(parent, (extra_a, extra_b))
        self.assertTrue(parent, "refusal must fall through to the existing fallbacks, not return nothing")

    def test_unique_substring_label_still_resolves(self):
        # control: "Kas en Bank"/"Bank" - exactly one asset group contains "Bank" (Bank Accounts).
        bank_accounts = self._named("Bank Accounts")
        parent = AccountMigrationService(self.company).get_parent_account("Bank", "Asset", self.company)
        self.assertEqual(parent, bank_accounts)

    def test_find_or_create_parent_group_does_not_pick_among_ambiguous(self):
        # Asset labels: "Current Assets" exact exists; a newer "Zz Current Assets Old" must not steal it.
        current_assets = self._named("Current Assets")
        self._group("Zz1398 Current Assets Old", "Application of Funds (Assets)", "Asset")
        parent = AccountMigrationService(self.company).find_or_create_parent_group("Asset", self.company)
        self.assertEqual(parent, current_assets)

    # ---- helper -------------------------------------------------------------
    def test_helper_refuses_ambiguity_with_both_rows_named(self):
        a = self._group("Zz1398 Alpha Fund", "Current Assets", "Asset")
        b = self._group("Zz1398 Beta Fund", "Current Assets", "Asset")
        with self.assertRaises(AmbiguousAccountLabel) as ctx:
            find_account_by_label("Zz1398", {"company": self.company, "is_group": 1})
        self.assertIn(a, str(ctx.exception))
        self.assertIn(b, str(ctx.exception))

    def test_helper_does_not_treat_underscore_or_percent_as_wildcard(self):
        self.assertTrue(self._named("Tax Assets"))
        self.assertIsNone(find_account_by_label("Tax_Assets", {"company": self.company}))
        self.assertIsNone(find_account_by_label("Tax%ssets", {"company": self.company}))
        self.assertTrue(find_account_by_label("Tax Assets", {"company": self.company}))

    # ---- organization service ----------------------------------------------
    def _org_service(self):
        return AccountOrganizationService(self.company, settings=frappe.new_doc("E-Boekhouden Settings"))

    def test_org_group_lookup_refuses_ambiguous_label(self):
        self._group("Zz1398 Belastingen 2025", "Current Liabilities", "Liability")
        self._group("Zz1398 Belastingen Overig", "Current Liabilities", "Liability")
        before = frappe.db.count("Account", {"company": self.company})
        # label is "Belastingen" (suffix after " - " dropped): two candidates, no exact.
        with self.assertRaises(AmbiguousAccountLabel):
            self._org_service()._ensure_tax_payable_group()
        # and it did not fall through to creating a third duplicate group
        self.assertEqual(frappe.db.count("Account", {"company": self.company}), before)

    def test_org_group_lookup_prefers_exact_name(self):
        exact = self._group("Belastingen", "Current Liabilities", "Liability")
        self._group("Zz1398 Belastingen Overig", "Current Liabilities", "Liability")
        self.assertEqual(self._org_service()._ensure_tax_payable_group(), exact)

    def test_org_group_lookup_finds_full_configured_name(self):
        # a group created by an earlier run carries the full configured name
        svc = self._org_service()
        full = self._group(svc.tax_payable_name, "Current Liabilities", "Liability")
        self._group("Zz1398 Belastingen Overig", "Current Liabilities", "Liability")
        self.assertEqual(svc._ensure_tax_payable_group(), full)
