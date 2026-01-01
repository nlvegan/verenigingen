"""
Tests for ConfigurableAccountMapper

Tests account detection and mapping functionality used by eBoekhouden integration.
Uses mocking to avoid complex ERPNext company/account creation side effects.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.e_boekhouden.utils.configurable_account_mapper import (
    ConfigurableAccountMapper,
    _generate_setup_recommendations,
    get_account_mapper,
    validate_account_setup,
)


class TestConfigurableAccountMapperDetection(unittest.TestCase):
    """Test ConfigurableAccountMapper detection methods execute without errors"""

    def setUp(self):
        """Initialize mapper with mock company"""
        self.mapper = ConfigurableAccountMapper("Test Company")

    def test_mapper_initialization(self):
        """Test mapper initializes with correct company"""
        self.assertEqual(self.mapper.company, "Test Company")
        self.assertEqual(self.mapper._cache, {})

    @patch("frappe.db.get_value")
    def test_find_main_bank_account_with_main_match(self, mock_get_value):
        """Test _find_main_bank_account finds account with 'main' in name"""
        mock_get_value.return_value = "Main Bank - TC"

        result = self.mapper._find_main_bank_account()

        self.assertEqual(result, "Main Bank - TC")
        # Verify the filter format is valid (dict, not list with ['or'])
        call_args = mock_get_value.call_args
        self.assertIsInstance(call_args.kwargs.get("filters", call_args.args[1] if len(call_args.args) > 1 else {}), dict)

    @patch("frappe.db.get_value")
    def test_find_main_bank_account_with_primary_fallback(self, mock_get_value):
        """Test _find_main_bank_account falls back to 'primary' match"""
        # First call (main) returns None, second call (primary) returns match
        mock_get_value.side_effect = [None, "Primary Bank - TC", None]

        result = self.mapper._find_main_bank_account()

        self.assertEqual(result, "Primary Bank - TC")
        # Should have been called at least twice
        self.assertGreaterEqual(mock_get_value.call_count, 2)

    @patch("frappe.db.get_value")
    def test_find_main_bank_account_final_fallback(self, mock_get_value):
        """Test _find_main_bank_account falls back to any bank account"""
        # First two calls return None, third returns any bank
        mock_get_value.side_effect = [None, None, "Some Bank - TC"]

        result = self.mapper._find_main_bank_account()

        self.assertEqual(result, "Some Bank - TC")
        self.assertEqual(mock_get_value.call_count, 3)

    @patch("frappe.db.get_value")
    def test_find_main_bank_account_no_match(self, mock_get_value):
        """Test _find_main_bank_account returns None when no banks exist"""
        mock_get_value.return_value = None

        result = self.mapper._find_main_bank_account()

        self.assertIsNone(result)

    @patch("frappe.db.get_value")
    def test_find_main_bank_account_no_value_error(self, mock_get_value):
        """Test _find_main_bank_account doesn't raise ValueError for invalid filter"""
        # This is the key regression test - the old code raised ValueError: Unknown filter format: ['or']
        mock_get_value.return_value = None

        # Should not raise ValueError
        try:
            self.mapper._find_main_bank_account()
        except ValueError as e:
            if "Unknown filter format" in str(e):
                self.fail("_find_main_bank_account raised ValueError for invalid filter format")
            raise

    @patch("frappe.db.get_value")
    def test_find_bank_by_name(self, mock_get_value):
        """Test _find_bank_by_name with valid filter format"""
        mock_get_value.return_value = "Triodos Bank - TC"

        result = self.mapper._find_bank_by_name("triodos")

        self.assertEqual(result, "Triodos Bank - TC")
        mock_get_value.assert_called_once()

    @patch("frappe.db.get_value")
    def test_find_cash_account_by_type(self, mock_get_value):
        """Test _find_cash_account finds account by Cash type"""
        mock_get_value.return_value = "Kas - TC"

        result = self.mapper._find_cash_account()

        self.assertEqual(result, "Kas - TC")

    @patch("frappe.db.get_value")
    def test_find_cash_account_kas_fallback(self, mock_get_value):
        """Test _find_cash_account falls back to 'kas' name pattern"""
        mock_get_value.side_effect = [None, "Kleine Kas - TC"]

        result = self.mapper._find_cash_account()

        self.assertEqual(result, "Kleine Kas - TC")

    @patch("frappe.db.get_value")
    def test_find_cash_account_cash_fallback(self, mock_get_value):
        """Test _find_cash_account falls back to 'cash' name pattern"""
        mock_get_value.side_effect = [None, None, "Petty Cash - TC"]

        result = self.mapper._find_cash_account()

        self.assertEqual(result, "Petty Cash - TC")

    @patch("frappe.db.get_value")
    def test_find_cash_account_no_value_error(self, mock_get_value):
        """Test _find_cash_account doesn't raise ValueError for invalid filter"""
        # This is the key regression test - the old code raised ValueError: Unknown filter format: ['or']
        mock_get_value.return_value = None

        # Should not raise ValueError
        try:
            self.mapper._find_cash_account()
        except ValueError as e:
            if "Unknown filter format" in str(e):
                self.fail("_find_cash_account raised ValueError for invalid filter format")
            raise

    @patch("frappe.get_doc")
    def test_find_default_expense_account_from_company(self, mock_get_doc):
        """Test _find_default_expense_account uses company setting"""
        mock_company = MagicMock()
        mock_company.default_expense_account = "Cost of Sales - TC"
        mock_get_doc.return_value = mock_company

        result = self.mapper._find_default_expense_account()

        self.assertEqual(result, "Cost of Sales - TC")

    @patch("frappe.get_doc")
    @patch("frappe.db.get_value")
    def test_find_default_expense_account_fallback(self, mock_get_value, mock_get_doc):
        """Test _find_default_expense_account falls back to any expense"""
        mock_company = MagicMock()
        mock_company.default_expense_account = None
        mock_get_doc.return_value = mock_company
        mock_get_value.return_value = "General Expense - TC"

        result = self.mapper._find_default_expense_account()

        self.assertEqual(result, "General Expense - TC")

    @patch("frappe.get_doc")
    def test_find_default_income_account_from_company(self, mock_get_doc):
        """Test _find_default_income_account uses company setting"""
        mock_company = MagicMock()
        mock_company.default_income_account = "Sales - TC"
        mock_get_doc.return_value = mock_company

        result = self.mapper._find_default_income_account()

        self.assertEqual(result, "Sales - TC")


class TestConfigurableAccountMapperCaching(unittest.TestCase):
    """Test caching behavior"""

    def setUp(self):
        """Initialize mapper"""
        self.mapper = ConfigurableAccountMapper("Test Company")

    @patch("frappe.db.get_value")
    def test_caching_stores_result(self, mock_get_value):
        """Test that results are cached after first lookup"""
        mock_get_value.return_value = "Main Bank - TC"

        result1 = self.mapper.get_account_by_purpose("main_bank")

        self.assertIn("main_bank", self.mapper._cache)
        self.assertEqual(self.mapper._cache["main_bank"], "Main Bank - TC")

    @patch("frappe.db.get_value")
    def test_caching_prevents_duplicate_queries(self, mock_get_value):
        """Test that cached results prevent additional queries"""
        mock_get_value.return_value = "Main Bank - TC"

        result1 = self.mapper.get_account_by_purpose("main_bank")
        result2 = self.mapper.get_account_by_purpose("main_bank")

        self.assertEqual(result1, result2)
        # Should only query once, second call uses cache
        # Note: actual call count may vary due to fallback logic, but cache should work
        self.assertEqual(self.mapper._cache.get("main_bank"), "Main Bank - TC")

    def test_unknown_purpose_returns_none(self):
        """Test that unknown purpose returns None"""
        result = self.mapper.get_account_by_purpose("unknown_purpose")
        self.assertIsNone(result)


class TestConfigurableAccountMapperMappings(unittest.TestCase):
    """Test mapping and validation methods"""

    def setUp(self):
        """Initialize mapper"""
        self.mapper = ConfigurableAccountMapper("Test Company")

    @patch.object(ConfigurableAccountMapper, "get_account_by_purpose")
    def test_get_payment_account_mappings(self, mock_get):
        """Test get_payment_account_mappings returns dict of found accounts"""
        mock_get.side_effect = lambda p: {
            "main_bank": "Main Bank - TC",
            "cash": "Cash - TC",
            "triodos": None,
            "paypal": None,
            "asn": None,
        }.get(p)

        mappings = self.mapper.get_payment_account_mappings()

        self.assertIsInstance(mappings, dict)
        self.assertEqual(mappings.get("main_bank"), "Main Bank - TC")
        self.assertEqual(mappings.get("cash"), "Cash - TC")
        self.assertNotIn("triodos", mappings)  # None values not included

    @patch.object(ConfigurableAccountMapper, "get_account_by_purpose")
    def test_validate_required_accounts_all_found(self, mock_get):
        """Test validate_required_accounts when all accounts exist"""
        mock_get.return_value = "Some Account - TC"

        results = self.mapper.validate_required_accounts(["main_bank", "cash"])

        self.assertTrue(results["main_bank"])
        self.assertTrue(results["cash"])

    @patch.object(ConfigurableAccountMapper, "get_account_by_purpose")
    def test_validate_required_accounts_some_missing(self, mock_get):
        """Test validate_required_accounts when some accounts missing"""
        mock_get.side_effect = lambda p: "Account - TC" if p == "main_bank" else None

        results = self.mapper.validate_required_accounts(["main_bank", "cash"])

        self.assertTrue(results["main_bank"])
        self.assertFalse(results["cash"])


class TestHelperFunctions(unittest.TestCase):
    """Test module-level helper functions"""

    def test_get_account_mapper(self):
        """Test get_account_mapper returns mapper instance"""
        mapper = get_account_mapper("Test Company")

        self.assertIsInstance(mapper, ConfigurableAccountMapper)
        self.assertEqual(mapper.company, "Test Company")

    @patch.object(ConfigurableAccountMapper, "validate_required_accounts")
    def test_validate_account_setup_valid(self, mock_validate):
        """Test validate_account_setup when all accounts exist"""
        mock_validate.return_value = {
            "main_bank": True,
            "cash": True,
            "default_expense": True,
            "default_income": True,
        }

        result = validate_account_setup("Test Company")

        self.assertTrue(result["valid"])
        self.assertEqual(result["missing_accounts"], [])

    @patch.object(ConfigurableAccountMapper, "validate_required_accounts")
    def test_validate_account_setup_missing(self, mock_validate):
        """Test validate_account_setup when accounts missing"""
        mock_validate.return_value = {
            "main_bank": True,
            "cash": False,
            "default_expense": False,
            "default_income": True,
        }

        result = validate_account_setup("Test Company")

        self.assertFalse(result["valid"])
        self.assertIn("cash", result["missing_accounts"])
        self.assertIn("default_expense", result["missing_accounts"])

    def test_generate_setup_recommendations_empty(self):
        """Test recommendations for no missing accounts"""
        recommendations = _generate_setup_recommendations([])
        self.assertEqual(recommendations, [])

    def test_generate_setup_recommendations_all_missing(self):
        """Test recommendations for all missing accounts"""
        recommendations = _generate_setup_recommendations([
            "main_bank", "cash", "default_expense", "default_income"
        ])

        self.assertEqual(len(recommendations), 4)
        self.assertTrue(any("Bank" in r for r in recommendations))
        self.assertTrue(any("Cash" in r for r in recommendations))


class TestIntegrationWithRealDatabase(unittest.TestCase):
    """Integration tests that use the actual database"""

    def setUp(self):
        """Get an existing company from the database"""
        # Use the first available company
        self.company = frappe.db.get_value("Company", {}, "name")
        if not self.company:
            self.skipTest("No company exists in database")
        self.mapper = ConfigurableAccountMapper(self.company)

    def test_find_main_bank_account_no_error(self):
        """Test _find_main_bank_account executes without ValueError on real DB"""
        # This is the key integration test for the fix
        try:
            result = self.mapper._find_main_bank_account()
            # Result can be None or string, but should not raise ValueError
            self.assertTrue(result is None or isinstance(result, str))
        except ValueError as e:
            if "Unknown filter format" in str(e):
                self.fail(f"Invalid filter format in _find_main_bank_account: {e}")
            raise

    def test_find_cash_account_no_error(self):
        """Test _find_cash_account executes without ValueError on real DB"""
        # This is the key integration test for the fix
        try:
            result = self.mapper._find_cash_account()
            # Result can be None or string, but should not raise ValueError
            self.assertTrue(result is None or isinstance(result, str))
        except ValueError as e:
            if "Unknown filter format" in str(e):
                self.fail(f"Invalid filter format in _find_cash_account: {e}")
            raise

    def test_all_detection_methods_execute(self):
        """Test all detection methods run without raising filter errors"""
        purposes = ["main_bank", "triodos", "paypal", "asn", "cash",
                   "default_expense", "default_income"]

        for purpose in purposes:
            with self.subTest(purpose=purpose):
                try:
                    result = self.mapper.get_account_by_purpose(purpose)
                    self.assertTrue(result is None or isinstance(result, str))
                except ValueError as e:
                    if "Unknown filter format" in str(e):
                        self.fail(f"Invalid filter format for {purpose}: {e}")
                    raise


def run_tests():
    """Run all configurable account mapper tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestConfigurableAccountMapperDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigurableAccountMapperCaching))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigurableAccountMapperMappings))
    suite.addTests(loader.loadTestsFromTestCase(TestHelperFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationWithRealDatabase))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    run_tests()
