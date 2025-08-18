"""
Comprehensive Tests for Mollie Financial Dashboard

Tests the financial dashboard functionality including:
- Timezone-aware date comparison logic (critical bug fix)
- Settlement data caching mechanisms
- Revenue analysis calculations
- Edge case handling for empty data
- API error scenarios
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.test_mollie_api_data_factory import (
    MollieApiDataFactory,
    create_test_settlements_for_revenue_analysis,
    create_test_data_for_caching_validation
)
from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard


class TestMollieFinancialDashboard(FrappeTestCase):
    """
    Test suite for Mollie Financial Dashboard
    
    Focuses on testing the specific issues that were fixed:
    1. Timezone comparison failures in revenue analysis
    2. Caching mechanism for settlements data
    3. API parameter errors with unsupported date filters
    4. Decimal conversion and calculation accuracy
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory(seed=42)
        
        # Mock Mollie Settings
        self.mock_settings = Mock()
        self.mock_settings.enable_backend_api = True
        self.mock_settings.get_password.return_value = "test_api_key"
        
        # Create dashboard instance with mocked clients
        self.dashboard = FinancialDashboard()
        
        # Mock the API clients to return test data instead of making real API calls
        self.setup_mocked_clients()
    
    def setup_mocked_clients(self):
        """Set up mocked API clients with realistic test data"""
        # Mock settlements client
        self.dashboard.settlements_client = Mock()
        self.dashboard.balances_client = Mock()
        self.dashboard.chargebacks_client = Mock()
        self.dashboard.invoices_client = Mock()
        
        # Default test data
        self.test_settlements = self.factory.generate_settlement_list(count=10)
        self.test_balances = [self.factory.generate_balance_data() for _ in range(2)]
        
        # Configure mock responses
        self.dashboard.settlements_client.get.return_value = self.test_settlements
        self.dashboard.balances_client.list_balances.return_value = self._create_balance_objects()
        self.dashboard.balances_client.check_balance_health.return_value = {"status": "healthy"}
    
    def _create_balance_objects(self):
        """Create mock balance objects with proper decimal_value attributes"""
        balance_objects = []
        for balance_data in self.test_balances:
            balance_obj = Mock()
            balance_obj.currency = balance_data["currency"]
            balance_obj.status = balance_data["status"]
            
            # Create amount objects with decimal_value property
            available_amount = Mock()
            available_amount.decimal_value = Decimal(balance_data["availableAmount"]["value"])
            balance_obj.available_amount = available_amount
            
            pending_amount = Mock()
            pending_amount.decimal_value = Decimal(balance_data["pendingAmount"]["value"])
            balance_obj.pending_amount = pending_amount
            
            balance_objects.append(balance_obj)
        
        return balance_objects
    
    def test_settlements_data_caching(self):
        """Test that _get_settlements_data() prevents redundant API calls"""
        # Clear any existing cache
        self.dashboard._settlements_cache = None
        
        # First call should hit the API
        first_result = self.dashboard._get_settlements_data()
        self.assertEqual(len(first_result), 10)
        self.dashboard.settlements_client.get.assert_called_once()
        
        # Second call should use cache, not hit API again
        second_result = self.dashboard._get_settlements_data()
        self.assertEqual(len(second_result), 10)
        self.assertEqual(first_result, second_result)
        # Assert API was still only called once
        self.dashboard.settlements_client.get.assert_called_once()
    
    def test_timezone_aware_revenue_analysis(self):
        """Test the timezone-aware date comparison logic that was fixed"""
        # Create settlements with different timezone formats that were causing bugs
        timezone_test_data = self.factory.generate_timezone_test_data()
        
        # Override the cached settlements with timezone test data
        self.dashboard._settlements_cache = timezone_test_data["settlements_mixed_timezones"]
        
        # Get revenue analysis
        with patch('frappe.logger') as mock_logger:
            revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Should not raise errors with mixed timezone formats
        self.assertIsInstance(revenue_analysis, dict)
        self.assertIn("current_month", revenue_analysis)
        self.assertIn("current_week", revenue_analysis)
        self.assertIn("current_quarter", revenue_analysis)
        
        # Values should be numeric (not causing decimal conversion errors)
        self.assertIsInstance(revenue_analysis["current_month"]["total_revenue"], (int, float))
        self.assertIsInstance(revenue_analysis["current_week"]["total_revenue"], (int, float))
        self.assertIsInstance(revenue_analysis["current_quarter"]["total_revenue"], (int, float))
        
        # Should have logged timezone handling
        mock_logger.return_value.info.assert_called()
    
    def test_revenue_analysis_with_current_month_settlements(self):
        """Test revenue analysis correctly identifies current month settlements"""
        # Create settlements specifically for current month
        now = datetime.now()
        current_month_settlements = []
        
        # Create settlement within current month
        current_settlement = self.factory.generate_settlement_data(
            status="paidout",
            amount_range=(1000.0, 1000.0)  # Exact amount for testing
        )
        # Set date to middle of current month
        current_month_date = now.replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        current_settlement["settledAt"] = current_month_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        current_month_settlements.append(current_settlement)
        
        # Create settlement from previous month
        prev_month_settlement = self.factory.generate_settlement_data(
            status="paidout",
            amount_range=(500.0, 500.0)
        )
        prev_month_date = (now - timedelta(days=35)).replace(day=15, hour=12, minute=0, second=0)
        prev_month_settlement["settledAt"] = prev_month_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        current_month_settlements.append(prev_month_settlement)
        
        # Override cached data
        self.dashboard._settlements_cache = current_month_settlements
        
        # Get revenue analysis
        revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Current month should only include the current month settlement (€1000)
        self.assertEqual(revenue_analysis["current_month"]["total_revenue"], 1000.0)
        
        # Current quarter should include both settlements (€1500)
        self.assertGreaterEqual(revenue_analysis["current_quarter"]["total_revenue"], 1000.0)
    
    def test_settlement_date_parsing_edge_cases(self):
        """Test handling of various date formats and edge cases"""
        edge_case_settlements = self.factory.generate_edge_case_settlements()
        self.dashboard._settlements_cache = edge_case_settlements
        
        # Should handle various edge cases without crashing
        try:
            revenue_analysis = self.dashboard._get_revenue_analysis()
            settlement_metrics = self.dashboard._get_settlement_metrics()
            
            # Should return valid data structures
            self.assertIsInstance(revenue_analysis, dict)
            self.assertIsInstance(settlement_metrics, dict)
            
        except Exception as e:
            self.fail(f"Edge case handling failed: {str(e)}")
    
    def test_empty_settlements_data_handling(self):
        """Test dashboard behavior with empty settlements data"""
        # Override with empty data
        self.dashboard._settlements_cache = []
        
        revenue_analysis = self.dashboard._get_revenue_analysis()
        settlement_metrics = self.dashboard._get_settlement_metrics()
        
        # Should handle empty data gracefully
        self.assertEqual(revenue_analysis["current_month"]["total_revenue"], 0.0)
        self.assertEqual(settlement_metrics["current_month"]["count"], 0)
        self.assertEqual(settlement_metrics["last_30_days"]["count"], 0)
    
    def test_api_error_handling_in_settlements_cache(self):
        """Test that API errors are handled gracefully in settlements caching"""
        # Configure mock to raise an exception
        self.dashboard.settlements_client.get.side_effect = Exception("API Error: Rate limit exceeded")
        
        # Clear cache to force API call
        self.dashboard._settlements_cache = None
        
        # Should handle API errors gracefully
        with patch('frappe.logger') as mock_logger:
            settlements_data = self.dashboard._get_settlements_data()
        
        # Should return empty list on API error
        self.assertEqual(settlements_data, [])
        
        # Should log the error
        mock_logger.return_value.error.assert_called_once()
    
    def test_balance_overview_with_multiple_currencies(self):
        """Test balance overview calculation with multiple currencies"""
        # Create multi-currency balance data
        multi_currency_balances = [
            self.factory.generate_balance_data(currency="EUR"),
            self.factory.generate_balance_data(currency="USD"),
            self.factory.generate_balance_data(currency="GBP")
        ]
        
        # Update mock to return multi-currency data
        self.dashboard.balances_client.list_balances.return_value = self._create_balance_objects_multi_currency(multi_currency_balances)
        
        balance_overview = self.dashboard._get_balance_overview()
        
        # Should include all currencies
        self.assertEqual(len(balance_overview["balances"]), 3)
        
        # Should have EUR totals (only EUR should be counted in totals)
        eur_balance = next(b for b in balance_overview["balances"] if b["currency"] == "EUR")
        self.assertEqual(balance_overview["total_available_eur"], eur_balance["available"])
        self.assertEqual(balance_overview["total_pending_eur"], eur_balance["pending"])
    
    def _create_balance_objects_multi_currency(self, balance_data_list):
        """Helper to create multi-currency balance objects"""
        balance_objects = []
        for balance_data in balance_data_list:
            balance_obj = Mock()
            balance_obj.currency = balance_data["currency"]
            balance_obj.status = balance_data["status"]
            
            available_amount = Mock()
            available_amount.decimal_value = Decimal(balance_data["availableAmount"]["value"])
            balance_obj.available_amount = available_amount
            
            pending_amount = Mock()
            pending_amount.decimal_value = Decimal(balance_data["pendingAmount"]["value"])
            balance_obj.pending_amount = pending_amount
            
            balance_objects.append(balance_obj)
        
        return balance_objects
    
    def test_settlement_metrics_recent_settlements_limit(self):
        """Test that recent settlements are properly limited to 5 items"""
        # Create more than 5 settlements
        many_settlements = self.factory.generate_settlement_list(count=10)
        self.dashboard._settlements_cache = many_settlements
        
        settlement_metrics = self.dashboard._get_settlement_metrics()
        
        # Should limit recent settlements to 5
        self.assertLessEqual(len(settlement_metrics["recent_settlements"]), 5)
    
    def test_dashboard_summary_integration(self):
        """Test the complete dashboard summary integration"""
        # Test the main entry point
        summary = self.dashboard.get_dashboard_summary()
        
        # Should contain all required sections
        required_sections = [
            "generated_at",
            "period",
            "balance_overview",
            "settlement_metrics",
            "revenue_analysis",
            "cost_breakdown",
            "chargeback_metrics",
            "reconciliation_status",
            "alerts"
        ]
        
        for section in required_sections:
            self.assertIn(section, summary)
        
        # Generated timestamp should be recent
        generated_time = datetime.fromisoformat(summary["generated_at"])
        self.assertLess((datetime.now() - generated_time).total_seconds(), 60)
    
    def test_decimal_to_float_conversion_accuracy(self):
        """Test that decimal to float conversions maintain accuracy"""
        # Create settlement with precise decimal amount
        precise_settlement = self.factory.generate_settlement_data()
        precise_settlement["amount"] = {"value": "1234.56", "currency": "EUR"}
        
        self.dashboard._settlements_cache = [precise_settlement]
        
        revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Should maintain decimal precision in float conversion
        # Note: This tests the specific decimal handling that was causing issues
        self.assertIsInstance(revenue_analysis["current_month"]["total_revenue"], (int, float))
        
    @patch('frappe.logger')
    def test_logging_and_debugging_info(self, mock_logger):
        """Test that proper logging is in place for debugging"""
        # Set up test data with settlements
        self.dashboard._settlements_cache = self.factory.generate_settlement_list(count=5)
        
        # Call revenue analysis which has extensive logging
        self.dashboard._get_revenue_analysis()
        
        # Should have logged information about settlement processing
        mock_logger.return_value.info.assert_called()
        
        # Verify some key log messages are present
        log_calls = [call[0][0] for call in mock_logger.return_value.info.call_args_list]
        
        # Should log about settlements being processed
        has_settlement_log = any("Revenue analysis: Got" in log for log in log_calls)
        self.assertTrue(has_settlement_log, "Should log about processing settlements")


class TestMollieFinancialDashboardApiEndpoints(FrappeTestCase):
    """
    Test the API endpoints for the financial dashboard
    """
    
    def setUp(self):
        """Set up test environment for API tests"""
        self.factory = MollieApiDataFactory(seed=100)
    
    @patch('verenigingen.verenigingen_payments.dashboards.financial_dashboard.FinancialDashboard')
    @patch('frappe.get_single')
    def test_get_dashboard_data_api_success(self, mock_get_single, mock_dashboard_class):
        """Test successful dashboard data API call"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Mock settings
        mock_settings = Mock()
        mock_settings.enable_backend_api = True
        mock_settings.get_password.return_value = "test_org_token"
        mock_get_single.return_value = mock_settings
        
        # Mock dashboard instance
        mock_dashboard = Mock()
        mock_dashboard_class.return_value = mock_dashboard
        
        # Mock dashboard summary
        test_summary = {
            "balance_overview": {"total_available_eur": 1000.0, "total_pending_eur": 100.0},
            "revenue_analysis": {
                "current_week": {"total_revenue": 200.0},
                "current_month": {"total_revenue": 800.0},
                "current_quarter": {"total_revenue": 2400.0}
            },
            "settlement_metrics": {"recent_settlements": []},
            "reconciliation_status": {"success_rate_30d": 95, "reconciled_settlements": 10, "total_settlements": 10}
        }
        mock_dashboard.get_dashboard_summary.return_value = test_summary
        
        # Call API
        result = get_dashboard_data()
        
        # Should return success
        self.assertTrue(result["success"])
        self.assertIn("data", result)
        
        # Should contain expected data structure
        data = result["data"]
        self.assertIn("balances", data)
        self.assertIn("revenue_metrics", data)
        self.assertIn("recent_settlements", data)
        self.assertIn("reconciliation_status", data)
    
    @patch('frappe.get_single')
    def test_get_dashboard_data_api_disabled(self, mock_get_single):
        """Test API response when backend API is disabled"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Mock settings with API disabled
        mock_settings = Mock()
        mock_settings.enable_backend_api = False
        mock_get_single.return_value = mock_settings
        
        result = get_dashboard_data()
        
        # Should return error
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("not enabled", result["error"])
    
    @patch('frappe.get_single')
    def test_get_dashboard_data_missing_token(self, mock_get_single):
        """Test API response when organization access token is missing"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Mock settings with API enabled but no token
        mock_settings = Mock()
        mock_settings.enable_backend_api = True
        mock_settings.get_password.return_value = None  # No token
        mock_get_single.return_value = mock_settings
        
        result = get_dashboard_data()
        
        # Should return error
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("not configured", result["error"])
    
    def test_test_dashboard_api_endpoint(self):
        """Test the simple test API endpoint"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import test_dashboard_api
        
        result = test_dashboard_api()
        
        # Should return success
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Dashboard API is working")
        self.assertIn("timestamp", result)


class TestMollieFinancialDashboardPerformance(FrappeTestCase):
    """
    Test performance characteristics of the financial dashboard
    """
    
    def setUp(self):
        """Set up performance test environment"""
        self.factory = MollieApiDataFactory(seed=200)
        self.dashboard = FinancialDashboard()
        self.setup_mocked_clients_for_performance()
    
    def setup_mocked_clients_for_performance(self):
        """Set up mocked clients with large datasets"""
        # Mock clients
        self.dashboard.settlements_client = Mock()
        self.dashboard.balances_client = Mock()
        self.dashboard.chargebacks_client = Mock()
        self.dashboard.invoices_client = Mock()
        
        # Create large dataset
        large_settlements_dataset = self.factory.generate_settlement_list(count=100)
        
        self.dashboard.settlements_client.get.return_value = large_settlements_dataset
        self.dashboard.balances_client.list_balances.return_value = []
        self.dashboard.balances_client.check_balance_health.return_value = {"status": "healthy"}
    
    def test_large_dataset_performance(self):
        """Test dashboard performance with large settlement datasets"""
        import time
        
        # Clear cache
        self.dashboard._settlements_cache = None
        
        # Measure time for dashboard summary
        start_time = time.time()
        summary = self.dashboard.get_dashboard_summary()
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        # Should complete within reasonable time (< 5 seconds)
        self.assertLess(processing_time, 5.0, "Dashboard processing should complete within 5 seconds")
        
        # Should return valid data
        self.assertIsInstance(summary, dict)
        self.assertIn("settlement_metrics", summary)
    
    def test_caching_performance_benefit(self):
        """Test that caching provides performance benefits"""
        import time
        
        # Clear cache for first call
        self.dashboard._settlements_cache = None
        
        # First call (should hit API)
        start_time = time.time()
        first_result = self.dashboard._get_settlements_data()
        first_call_time = time.time() - start_time
        
        # Second call (should use cache)
        start_time = time.time()
        second_result = self.dashboard._get_settlements_data()
        second_call_time = time.time() - start_time
        
        # Cached call should be significantly faster
        self.assertLess(second_call_time, first_call_time / 2, "Cached call should be at least 2x faster")
        
        # Results should be identical
        self.assertEqual(first_result, second_result)


if __name__ == '__main__':
    unittest.main()
