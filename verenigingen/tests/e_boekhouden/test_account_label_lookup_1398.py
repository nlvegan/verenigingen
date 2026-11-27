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

    def _group(self, account_name, parent_account_name, root_type, is_group=1, disabled=0, company=None):
        company = company or self.company
        parent = frappe.db.get_value(
            "Account", {"company": company, "account_name": parent_account_name, "is_group": 1}, "name"
        )
        self.assertTrue(parent, f"fixture chart lacks {parent_account_name}")
        acc = frappe.new_doc("Account")
        acc.account_name = account_name
        acc.company = company
        acc.parent_account = parent
        acc.root_type = root_type
        acc.is_group = is_group
        acc.disabled = disabled
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
        # pin WHICH parent: after refusing "Cash" the existing account_type fallback decides.
        # (That fallback is pre-existing pick-first, deliberately unchanged here.)
        fallback = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Cash", "is_group": 1}, "name"
        )
        self.assertTrue(fallback, "fixture chart must carry a Cash-typed group for this pin")
        self.assertEqual(parent, fallback)

    def test_ambiguity_is_logged_once_per_label_and_company(self):
        self._group("Zz1398 Cash Holding A", "Current Assets", "Asset")
        self._group("Zz1398 Cash Holding B", "Current Assets", "Asset")
        svc = AccountMigrationService(self.company)
        before = frappe.db.count("Error Log", {"method": "E-Boekhouden ambiguous parent account label"})
        for _ in range(3):
            svc.get_parent_account("Cash", "Asset", self.company)
        after = frappe.db.count("Error Log", {"method": "E-Boekhouden ambiguous parent account label"})
        self.assertEqual(after - before, 1)

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
    # (method, label, root_type, parent group the fixtures hang under)
    _ORG_GROUPS = (
        ("_ensure_financial_accounts_group", "Financiële rekeningen", "Asset", "Current Assets"),
        ("_ensure_overlopende_activa_group", "Overlopende activa", "Asset", "Current Assets"),
        ("_ensure_schulden_group", "Schulden", "Liability", "Current Liabilities"),
        ("_ensure_tax_payable_group", "Belastingen", "Liability", "Current Liabilities"),
        ("_ensure_tax_receivable_group", "Belastingen", "Asset", "Current Assets"),
    )

    def _org_service(self):
        return AccountOrganizationService(self.company, settings=frappe.new_doc("E-Boekhouden Settings"))

    def test_every_org_group_lookup_refuses_ambiguous_label(self):
        for method, label, root_type, parent in self._ORG_GROUPS:
            with self.subTest(method=method):
                self._group(f"Zz1398 {label} 1", parent, root_type)
                self._group(f"Zz1398 {label} 2", parent, root_type)
                with self.assertRaises(AmbiguousAccountLabel):
                    getattr(self._org_service(), method)()
                frappe.db.rollback()

    def test_every_org_group_lookup_prefers_exact_name(self):
        for method, label, root_type, parent in self._ORG_GROUPS:
            with self.subTest(method=method):
                exact = self._group(label, parent, root_type)
                self._group(f"Zz1398 {label} Overig", parent, root_type)
                self.assertEqual(getattr(self._org_service(), method)(), exact)
                frappe.db.rollback()

    def test_org_group_lookup_finds_full_configured_name(self):
        # a group created by an earlier run carries the full configured name
        svc = self._org_service()
        full = self._group(svc.tax_payable_name, "Current Liabilities", "Liability")
        self._group("Zz1398 Belastingen Overig", "Current Liabilities", "Liability")
        self.assertEqual(svc._ensure_tax_payable_group(), full)

    def test_non_group_account_containing_label_is_ignored(self):
        group = self._group("Zz1398 Schulden Groep", "Current Liabilities", "Liability")
        self._group("Zz1398 Schulden Leaf", "Current Liabilities", "Liability", is_group=0)
        self.assertEqual(self._org_service()._ensure_schulden_group(), group)

    def test_disabled_stale_group_does_not_cause_refusal(self):
        live = self._group("Zz1398 Belastingen Live", "Current Liabilities", "Liability")
        self._group("Zz1398 Belastingen Old", "Current Liabilities", "Liability", disabled=1)
        self.assertEqual(self._org_service()._ensure_tax_payable_group(), live)

    def test_other_company_exact_match_is_not_used(self):
        other = self._other_company()
        self._group("Belastingen", "Current Liabilities", "Liability", company=other)
        mine = self._group("Zz1398 Belastingen Mine", "Current Liabilities", "Liability")
        self.assertEqual(self._org_service()._ensure_tax_payable_group(), mine)

    def test_label_lookup_false_refuses_a_filter_without_a_name_match(self):
        # structural guard: a caller that forgets label_lookup=True must not match ANY group
        svc = self._org_service()
        with self.assertRaises(ValueError):
            svc._ensure_account_group(
                svc._name_filter("Belastingen - Taxes Payable", "Liability"),
                "Belastingen - Taxes Payable",
                "Liability",
                svc._get_passiva_root,
            )

    @classmethod
    def _other_company(cls):
        name = "TEST 1398 Other Co"
        if not frappe.db.exists("Company", name):
            doc = frappe.new_doc("Company")
            doc.company_name = name
            doc.abbr = "T98O"
            doc.default_currency = "EUR"
            doc.country = "Netherlands"
            doc.insert()
        return name
