"""
Unit / integration tests for the account-organization and account-hierarchy
services used by the eBoekhouden Chart-of-Accounts importer.

Targets:
- verenigingen/e_boekhouden/services/account_hierarchy_service.py
    derive_group_code, _get_keywords_for_group, match_account_to_group,
    get_group_type_mappings_dict
- verenigingen/e_boekhouden/services/account_organization_service.py
    range-parsing helpers + _is_in_ranges (pure, settings-driven)

These exercise pure keyword/range logic plus settings parsing. No live
eBoekhouden HTTP connection is required.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_account_services
"""

import unittest

import frappe

from verenigingen.e_boekhouden.services.account_hierarchy_service import (
    EXCLUDE_PATTERNS,
    GROUP_KEYWORDS,
    INCOME_SIGNALS,
    _get_keywords_for_group,
    derive_group_code,
    get_group_type_mappings_dict,
    match_account_to_group,
)
from verenigingen.e_boekhouden.services.account_organization_service import AccountOrganizationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# account_hierarchy_service - pure functions
# ---------------------------------------------------------------------------
class TestDeriveGroupCode(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(derive_group_code(None))

    def test_empty(self):
        self.assertIsNone(derive_group_code(""))

    def test_non_numeric(self):
        self.assertIsNone(derive_group_code("ABC"))

    def test_short_padded(self):
        self.assertEqual(derive_group_code("42"), "042")

    def test_single_digit(self):
        self.assertEqual(derive_group_code("7"), "007")

    def test_long_takes_first_three(self):
        self.assertEqual(derive_group_code("80001"), "800")

    def test_strips_non_digits(self):
        self.assertEqual(derive_group_code("13.05"), "130")

    def test_whitespace(self):
        self.assertEqual(derive_group_code("  4220  "), "422")


class TestGetKeywordsForGroup(unittest.TestCase):
    def test_explicit_keywords(self):
        kws = _get_keywords_for_group("Liquide middelen")
        self.assertEqual(kws, GROUP_KEYWORDS["Liquide middelen"])

    def test_derived_from_name(self):
        # Not in GROUP_KEYWORDS -> derive from the name words >= 4 chars, non-filler
        kws = _get_keywords_for_group("Programma Educatie")
        self.assertIn("educatie", kws)
        # filler word "programma" excluded
        self.assertNotIn("programma", kws)

    def test_filler_words_excluded(self):
        kws = _get_keywords_for_group("Overige Kosten Algemene")
        self.assertEqual(kws, [])  # all words are filler

    def test_programma_suffix_added(self):
        kws = _get_keywords_for_group("Programma Dierenrechten")
        self.assertIn("dierenrechten", kws)

    def test_short_words_excluded(self):
        kws = _get_keywords_for_group("ICT en de IT")
        # "ict" (3), "en"/"de" filler, "it" (2) -> nothing qualifies
        self.assertEqual(kws, [])


class TestMatchAccountToGroup(unittest.TestCase):
    def setUp(self):
        # Minimal mapping dict mimicking settings.group_type_mappings
        self.mappings = {
            "001": {"group_name": "Liquide middelen", "root_type": "Asset", "account_type": "Bank"},
            "002": {"group_name": "Vorderingen", "root_type": "Asset", "account_type": "Receivable"},
            "010": {
                "group_name": "Personeelskosten",
                "root_type": "Expense",
                "account_type": "Expense Account",
            },
            "020": {"group_name": "Opbrengsten", "root_type": "Income", "account_type": "Income Account"},
            "030": {
                "group_name": "Promotiekosten",
                "root_type": "Expense",
                "account_type": "Expense Account",
            },
        }

    def test_empty_name(self):
        self.assertEqual(match_account_to_group("", self.mappings), (None, None, None))

    def test_bank_matches_liquide(self):
        code, name, reason = match_account_to_group("Triodos Bank Algemeen", self.mappings)
        self.assertEqual(code, "001")
        self.assertEqual(name, "Liquide middelen")
        self.assertIn("Matched keyword", reason)

    def test_debiteuren_matches_vorderingen(self):
        code, name, _ = match_account_to_group("Debiteuren binnenland", self.mappings)
        self.assertEqual(name, "Vorderingen")

    def test_salaris_matches_personeel(self):
        code, name, _ = match_account_to_group("Lonen en salaris medewerkers", self.mappings)
        self.assertEqual(name, "Personeelskosten")

    def test_income_signal_blocks_expense_group(self):
        # "Promotie: inkomsten" has an income signal -> must NOT match Promotiekosten (Expense)
        code, name, _ = match_account_to_group("Promotie: inkomsten festival", self.mappings)
        self.assertNotEqual(name, "Promotiekosten")

    def test_exclude_pattern_applied(self):
        # Opbrengsten excludes "kosten"; "Opbrengst kosten" should not match Opbrengsten
        code, name, _ = match_account_to_group("Opbrengst kosten dubieus", self.mappings)
        self.assertNotEqual(name, "Opbrengsten")

    def test_longer_keyword_wins(self):
        # "spaarrekening" (13) beats "bank"; both under Liquide, so still 001 but
        # verifies scoring path runs without error and returns the group.
        code, name, _ = match_account_to_group("Triodos spaarrekening", self.mappings)
        self.assertEqual(name, "Liquide middelen")

    def test_no_match_returns_none(self):
        code, name, reason = match_account_to_group("Zomaar iets onbekends xyz", self.mappings)
        self.assertIsNone(code)
        self.assertIsNone(name)

    def test_skips_mapping_without_group_name(self):
        mappings = {"099": {"group_name": "", "root_type": "Asset"}}
        self.assertEqual(match_account_to_group("Triodos Bank", mappings), (None, None, None))

    def test_income_signals_constant_used(self):
        # sanity: an income signal we test with is actually in the constant
        self.assertIn("inkomsten", INCOME_SIGNALS)


# ---------------------------------------------------------------------------
# account_hierarchy_service - get_group_type_mappings_dict (DB/doc-backed)
# ---------------------------------------------------------------------------
class TestGetGroupTypeMappingsDict(EnhancedTestCase):
    def test_builds_dict_from_doc_rows(self):
        # Construct an in-memory E-Boekhouden Settings-like doc using a real
        # new_doc so child-table rows behave correctly (no DB write needed).
        settings = frappe.get_single("E-Boekhouden Settings")
        # Snapshot existing rows; we only read via get(), so build a transient doc.
        transient = frappe.new_doc("E-Boekhouden Settings")
        transient.append(
            "group_type_mappings",
            {
                "group_code": "001",
                "group_name": "Liquide middelen",
                "root_type": "Asset",
                "account_type": "Bank",
            },
        )
        transient.append(
            "group_type_mappings",
            {"group_code": "010", "group_name": "Personeelskosten", "root_type": "Expense"},
        )
        # Row missing root_type must be skipped
        transient.append(
            "group_type_mappings",
            {"group_code": "099", "group_name": "Incomplete", "root_type": ""},
        )
        result = get_group_type_mappings_dict(transient)
        self.assertIn("001", result)
        self.assertEqual(result["001"]["account_type"], "Bank")
        self.assertIn("010", result)
        self.assertEqual(result["010"]["account_type"], "")  # default empty
        self.assertNotIn("099", result)
        # ensure we didn't depend on the live single
        del settings


# ---------------------------------------------------------------------------
# account_organization_service - range parsing + _is_in_ranges
# ---------------------------------------------------------------------------
class TestAccountOrganizationRanges(EnhancedTestCase):
    """Range parsing is settings-driven; we feed a transient settings doc."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST AcctOrg Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TAOC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _make_settings(self, asset_ranges="", liability_ranges=""):
        """Build a transient settings doc carrying just the range fields."""
        s = frappe.new_doc("E-Boekhouden Settings")
        s.bal_asset_ranges = asset_ranges
        s.bal_liability_ranges = liability_ranges
        return s

    def test_defaults_when_no_config(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        # Falls back to hardcoded defaults
        self.assertEqual(svc.receivable_ranges, [("1300", "1399")])
        self.assertEqual(svc.financial_account_ranges, [("1000", "1299")])
        self.assertIn(("1600", "1699"), svc.creditor_ranges)

    def test_extract_receivable_ranges(self):
        asset = "1300-1899 Receivables / Vorderingen\n1000-1099 Bank accounts"
        svc = AccountOrganizationService(self.company, settings=self._make_settings(asset_ranges=asset))
        self.assertIn(("1300", "1899"), svc.receivable_ranges)

    def test_extract_financial_ranges(self):
        asset = "1000-1099 Bank en kas\n1300-1399 Vorderingen receivable"
        svc = AccountOrganizationService(self.company, settings=self._make_settings(asset_ranges=asset))
        self.assertIn(("1000", "1099"), svc.financial_account_ranges)

    def test_extract_creditor_ranges(self):
        liab = "1600-1699 Crediteuren / payable\n3000-3999 Equity"
        svc = AccountOrganizationService(self.company, settings=self._make_settings(liability_ranges=liab))
        self.assertIn(("1600", "1699"), svc.creditor_ranges)

    def test_line_without_keyword_ignored(self):
        asset = "2000-2999 Just some assets"  # no receivable/bank keyword
        svc = AccountOrganizationService(self.company, settings=self._make_settings(asset_ranges=asset))
        # Falls back to defaults since nothing matched
        self.assertEqual(svc.receivable_ranges, [("1300", "1399")])

    def test_is_in_ranges_true(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        self.assertTrue(svc._is_in_ranges("1350", [("1300", "1399")]))

    def test_is_in_ranges_boundaries(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        self.assertTrue(svc._is_in_ranges("1300", [("1300", "1399")]))
        self.assertTrue(svc._is_in_ranges("1399", [("1300", "1399")]))

    def test_is_in_ranges_outside(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        self.assertFalse(svc._is_in_ranges("1400", [("1300", "1399")]))

    def test_is_in_ranges_padding(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        # short codes are zfilled to 4: "13" -> "0013" which is inside 0010-0020
        self.assertTrue(svc._is_in_ranges("13", [("0010", "0020")]))
        self.assertTrue(svc._is_in_ranges("15", [("0010", "0020")]))
        # "30" -> "0030" is outside 0010-0020
        self.assertFalse(svc._is_in_ranges("30", [("0010", "0020")]))

    def test_is_in_ranges_empty(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        self.assertFalse(svc._is_in_ranges("1300", []))
        self.assertFalse(svc._is_in_ranges(None, [("1300", "1399")]))

    def test_configurable_group_names_defaults(self):
        svc = AccountOrganizationService(self.company, settings=self._make_settings())
        self.assertEqual(svc.vorderingen_name, "Vorderingen - Receivables")
        self.assertEqual(svc.schulden_name, "Schulden - Liabilities")
        self.assertEqual(svc.tax_receivable_account, "1530")


if __name__ == "__main__":
    unittest.main()
