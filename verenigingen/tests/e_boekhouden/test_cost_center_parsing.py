"""
Unit and Integration Tests for Cost Center Parsing

Tests the parse_groups_and_suggest_cost_centers function including:
- Tab vs space handling
- Balance sheet vs P&L filtering
- Cost center suggestion logic
"""

import frappe
import unittest
from verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings import (
    parse_groups_and_suggest_cost_centers,
    should_suggest_cost_center,
    clean_cost_center_name,
)


class TestCostCenterParsing(unittest.TestCase):
    """Test suite for cost center parsing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_company = frappe.get_value("Company", {"company_name": "Test Company"}, "name")
        if not self.test_company:
            # Create test company if it doesn't exist
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": "Test Company",
                "abbr": "TC",
                "default_currency": "EUR",
                "country": "Netherlands"
            })
            company.insert(ignore_permissions=True)
            self.test_company = company.name

    def test_parsing_with_spaces(self):
        """Test that parsing works correctly with space-separated values"""
        input_text = """007 Personeelskosten
008 Promotiekosten
009 Algemene kosten"""

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 3)

        # Verify first entry
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_with_tabs(self):
        """Test that parsing works correctly with tab-separated values"""
        input_text = "007\tPersoneelskosten\n008\tPromotiekosten\n009\tAlgemene kosten"

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 3)

        # Verify parsing correctly handles tabs
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_with_multiple_spaces(self):
        """Test that parsing works with multiple spaces between code and name"""
        input_text = """007    Personeelskosten
008     Promotiekosten"""

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_multi_word_names(self):
        """Test that parsing correctly handles multi-word group names"""
        input_text = "033\tInterne evenementen"

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 1)

        # Should NOT split the name on internal spaces
        self.assertEqual(result["suggestions"][0]["group_code"], "033")
        self.assertEqual(result["suggestions"][0]["group_name"], "Interne evenementen")

    def test_empty_input(self):
        """Test that empty input is handled gracefully"""
        result = parse_groups_and_suggest_cost_centers("", self.test_company)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_expense_group_suggestion(self):
        """Test that expense groups are suggested for cost center creation"""
        # Expense codes start with "5" (personnel) or "6" (other expenses)
        should_create, reason = should_suggest_cost_center("507", "Personeelskosten")

        self.assertTrue(should_create)
        self.assertIn("Expense", reason)

    def test_balance_sheet_not_suggested(self):
        """Test that balance sheet accounts are NOT suggested for cost centers"""
        # Balance sheet codes start with "1" (assets) or "2" (liabilities)
        should_create, reason = should_suggest_cost_center("101", "Materiële vaste activa")

        self.assertFalse(should_create)
        self.assertIn("Balance sheet", reason)

    def test_income_group_suggestion(self):
        """Test that income groups can be suggested for cost centers"""
        should_create, reason = should_suggest_cost_center("055", "Opbrengsten dienstverlening")

        # Income groups with specific keywords should be suggested
        self.assertTrue(should_create)

    def test_cost_center_name_cleaning(self):
        """Test that cost center names are properly cleaned"""
        cleaned = clean_cost_center_name("Personeelskosten rekeningen")

        self.assertEqual(cleaned, "Personeelskosten")

        cleaned2 = clean_cost_center_name("grootboek kosten")
        self.assertEqual(cleaned2, "Kosten")

    def test_operational_keywords_detection(self):
        """Test that operational keywords trigger cost center suggestions"""
        should_create, reason = should_suggest_cost_center("025", "Project Marketing")

        self.assertTrue(should_create)
        self.assertIn("departmental", reason.lower())

    def tearDown(self):
        """Clean up test data"""
        # Note: We don't delete the test company as it might be used by other tests
        pass


class TestCostCenterIntegration(unittest.TestCase):
    """Integration tests for cost center functionality with settings"""

    def setUp(self):
        """Set up test settings"""
        self.settings = frappe.get_single("E-Boekhouden Settings")

        # Backup original values
        self.original_pl_mappings = self.settings.get("pl_group_mappings")

    def test_settings_pl_mapping_parsing(self):
        """Test that settings correctly parse P&L mappings"""
        # Parser splits on space, not tab
        test_mappings = "007 Personeelskosten\n008 Promotiekosten"

        self.settings.pl_group_mappings = test_mappings

        # Parse using settings method
        parsed = self.settings._parse_pl_group_mappings()

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed["007"], "Personeelskosten")
        self.assertEqual(parsed["008"], "Promotiekosten")

    def test_balance_sheet_separate_from_pl(self):
        """Test that balance sheet and P&L mappings are kept separate"""
        # Parser splits on space, not tab
        self.settings.balance_sheet_group_mappings = "001 Vaste activa"
        self.settings.pl_group_mappings = "055 Opbrengsten"

        bal_parsed = self.settings._parse_balance_sheet_group_mappings()
        pl_parsed = self.settings._parse_pl_group_mappings()

        self.assertEqual(len(bal_parsed), 1)
        self.assertEqual(len(pl_parsed), 1)
        self.assertIn("001", bal_parsed)
        self.assertIn("055", pl_parsed)

    def tearDown(self):
        """Restore original settings"""
        if self.original_pl_mappings:
            self.settings.pl_group_mappings = self.original_pl_mappings
            self.settings.save(ignore_permissions=True)
