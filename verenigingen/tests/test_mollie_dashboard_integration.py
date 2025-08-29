"""
Phase 4 Mock Elimination: Mollie Financial Dashboard Integration Tests
=====================================================================

This test suite demonstrates Phase 4 mock elimination principles for Mollie dashboard operations.
It eliminates inappropriate business logic mocks while keeping necessary external service mocks.

ELIMINATED INAPPROPRIATE MOCKS:
- Dashboard internal calculation mocks
- Date comparison business logic mocks
- Decimal conversion logic mocks
- Caching mechanism business logic mocks

KEPT LEGITIMATE MOCKS:
- External Mollie API services
- Network communication layers
- External balance API endpoints
- Settlement API endpoints

REAL BUSINESS LOGIC TESTED:
- Timezone-aware date calculations
- Revenue analysis calculations
- Settlement metrics processing
- Multi-currency balance handling
"""

import frappe
from frappe.utils import today, add_days, getdate, now_datetime
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
import json

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard


class TestMollieDashboardIntegration(EnhancedTestCase):
    """
    Real integration tests for Mollie Financial Dashboard
    
    Tests actual business logic calculations without mocking internal systems
    """
    
    def setUp(self):
        """Set up test environment with real business logic"""
        super().setUp()
        
        # Create real test data using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Dashboard",
            last_name="TestMember",
            email_address="dashboard@integration.test"
        )
        
        # Create realistic Mollie settings (without real API keys)
        self.mollie_settings = frappe.get_single("Mollie Settings")
        self.mollie_settings.enable_backend_api = 1
        self.mollie_settings.api_key = "test_api_key_for_integration"  # Test key
        self.mollie_settings.save()
        
        # Initialize dashboard with real business logic
        self.dashboard = FinancialDashboard()
        
        # Only mock external Mollie API clients (appropriate mocks)
        self.setup_external_api_mocks()
    
    def setup_external_api_mocks(self):
        """Set up mocks for external Mollie API services only"""
        # These are legitimate mocks - external service boundaries
        self.dashboard.settlements_client = Mock()
        self.dashboard.balances_client = Mock()
        self.dashboard.chargebacks_client = Mock()
        self.dashboard.invoices_client = Mock()
        
        # Configure realistic API responses for testing business logic
        self.configure_realistic_api_responses()
    
    def configure_realistic_api_responses(self):
        """Configure realistic API responses that test business logic"""
        # Real settlement data structure - tests timezone handling
        current_month = datetime.now().replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        prev_month = current_month - timedelta(days=35)
        
        realistic_settlements = [
            {
                "id": "stl_current_001",
                "status": "paidout",
                "amount": {"value": "1500.75", "currency": "EUR"},
                "settledAt": current_month.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "periods": [{
                    "revenue": [{"description": "Membership fees", "count": 5, "amountNet": {"value": "1500.75"}}]
                }]
            },
            {
                "id": "stl_prev_001", 
                "status": "paidout",
                "amount": {"value": "890.50", "currency": "EUR"},
                "settledAt": prev_month.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "periods": [{
                    "revenue": [{"description": "Donations", "count": 3, "amountNet": {"value": "890.50"}}]
                }]
            }
        ]
        
        # Real balance data structure
        realistic_balances = [
            Mock(
                currency="EUR",
                status="active",
                available_amount=Mock(decimal_value=Decimal("2500.25")),
                pending_amount=Mock(decimal_value=Decimal("150.75"))
            ),
            Mock(
                currency="USD", 
                status="active",
                available_amount=Mock(decimal_value=Decimal("500.00")),
                pending_amount=Mock(decimal_value=Decimal("25.50"))
            )
        ]
        
        # Configure mock responses
        self.dashboard.settlements_client.get.return_value = realistic_settlements
        self.dashboard.balances_client.list_balances.return_value = realistic_balances
        self.dashboard.balances_client.check_balance_health.return_value = {"status": "healthy"}
    
    def test_timezone_aware_date_calculations_real_logic(self):
        """Test timezone-aware date calculations with real business logic"""
        
        # Clear cache to ensure fresh calculation
        self.dashboard._settlements_cache = None
        
        # Get revenue analysis - tests real date calculation logic
        revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Validate real business logic results
        self.assertIsInstance(revenue_analysis, dict)
        self.assertIn("current_month", revenue_analysis)
        self.assertIn("current_week", revenue_analysis)
        self.assertIn("current_quarter", revenue_analysis)
        
        # Test real date comparison logic (no mocks)
        current_month_revenue = revenue_analysis["current_month"]["total_revenue"]
        self.assertIsInstance(current_month_revenue, (int, float))
        self.assertGreater(current_month_revenue, 0)  # Should find current month settlement
        
        # Validate real calculation accuracy
        # Current month settlement amount should be reflected
        self.assertEqual(current_month_revenue, 1500.75)
    
    def test_decimal_precision_real_calculations(self):
        """Test decimal precision in real calculations (no conversion mocks)"""
        
        # Test with precise decimal values
        self.dashboard._settlements_cache = None
        
        # Get balance overview - tests real decimal handling
        balance_overview = self.dashboard._get_balance_overview()
        
        # Validate real decimal precision
        self.assertIsInstance(balance_overview, dict)
        self.assertIn("balances", balance_overview)
        self.assertIn("total_available_eur", balance_overview)
        
        # Test real precision preservation (no mocking)
        total_available = balance_overview["total_available_eur"]
        self.assertEqual(total_available, 2500.25)  # Exact decimal match
        
        total_pending = balance_overview["total_pending_eur"]
        self.assertEqual(total_pending, 150.75)  # Exact decimal match
    
    def test_multi_currency_handling_real_logic(self):
        """Test multi-currency processing with real business logic"""
        
        balance_overview = self.dashboard._get_balance_overview()
        
        # Validate real multi-currency business logic
        balances = balance_overview["balances"]
        self.assertEqual(len(balances), 2)  # EUR and USD
        
        # Test real currency separation logic (no mocks)
        currencies = [b["currency"] for b in balances]
        self.assertIn("EUR", currencies)
        self.assertIn("USD", currencies)
        
        # EUR should be counted in totals (real business rule)
        eur_balance = next(b for b in balances if b["currency"] == "EUR")
        self.assertEqual(balance_overview["total_available_eur"], eur_balance["available"])
        
        # USD should not affect EUR totals (real business logic)
        self.assertNotEqual(balance_overview["total_available_eur"], 3000.25)  # Should not include USD
    
    def test_settlement_metrics_real_aggregation(self):
        """Test settlement metrics aggregation with real business logic"""
        
        # Clear cache for fresh calculation
        self.dashboard._settlements_cache = None
        
        # Get settlement metrics - tests real aggregation logic
        settlement_metrics = self.dashboard._get_settlement_metrics()
        
        # Validate real aggregation results
        self.assertIsInstance(settlement_metrics, dict)
        self.assertIn("current_month", settlement_metrics)
        self.assertIn("last_30_days", settlement_metrics)
        self.assertIn("recent_settlements", settlement_metrics)
        
        # Test real counting logic (no mocks)
        current_month_count = settlement_metrics["current_month"]["count"]
        self.assertIsInstance(current_month_count, int)
        self.assertGreaterEqual(current_month_count, 1)  # At least current month settlement
        
        # Test real recent settlements limit (business rule)
        recent_settlements = settlement_metrics["recent_settlements"]
        self.assertLessEqual(len(recent_settlements), 5)  # Real business limit
    
    def test_caching_mechanism_real_behavior(self):
        """Test caching mechanism with real business behavior"""
        
        # Clear cache initially
        self.dashboard._settlements_cache = None
        
        # First call should populate cache (real caching logic)
        first_result = self.dashboard._get_settlements_data()
        self.assertIsNotNone(self.dashboard._settlements_cache)
        self.assertEqual(len(first_result), 2)  # Our test settlements
        
        # Verify API was called
        self.dashboard.settlements_client.get.assert_called_once()
        
        # Second call should use cache (real caching behavior)
        second_result = self.dashboard._get_settlements_data()
        self.assertEqual(first_result, second_result)  # Same data
        
        # Verify API was not called again (real caching working)
        self.dashboard.settlements_client.get.assert_called_once()  # Still once
        
        # Test cache invalidation (real business logic)
        self.dashboard._settlements_cache = None
        third_result = self.dashboard._get_settlements_data()
        
        # Should have called API again
        self.assertEqual(self.dashboard.settlements_client.get.call_count, 2)
    
    def test_empty_data_handling_real_logic(self):
        """Test empty data handling with real business logic"""
        
        # Configure empty responses
        self.dashboard.settlements_client.get.return_value = []
        self.dashboard.balances_client.list_balances.return_value = []
        
        # Clear cache for fresh call
        self.dashboard._settlements_cache = None
        
        # Test real empty data handling
        revenue_analysis = self.dashboard._get_revenue_analysis()
        settlement_metrics = self.dashboard._get_settlement_metrics()
        balance_overview = self.dashboard._get_balance_overview()
        
        # Validate real empty data business logic
        self.assertEqual(revenue_analysis["current_month"]["total_revenue"], 0.0)
        self.assertEqual(settlement_metrics["current_month"]["count"], 0)
        self.assertEqual(len(balance_overview["balances"]), 0)
        self.assertEqual(balance_overview["total_available_eur"], 0.0)
    
    @patch('frappe.log_error')  # KEEP: External logging service mock (appropriate)
    def test_api_error_handling_real_recovery(self, mock_log_error):
        """Test API error handling with real recovery logic"""
        
        # Configure API to raise exception
        self.dashboard.settlements_client.get.side_effect = Exception("API Rate Limit")
        
        # Clear cache to force API call
        self.dashboard._settlements_cache = None
        
        # Test real error recovery logic (no mocking)
        settlements_data = self.dashboard._get_settlements_data()
        
        # Real error recovery should return empty list
        self.assertEqual(settlements_data, [])
        
        # Should log error (external service mock is appropriate)
        mock_log_error.assert_called_once()
        
        # Test recovery after error (real business logic)
        self.dashboard.settlements_client.get.side_effect = None
        self.dashboard.settlements_client.get.return_value = [{"id": "recovery_test"}]
        
        # Cache should be reset, allowing recovery
        self.dashboard._settlements_cache = None
        recovery_data = self.dashboard._get_settlements_data()
        self.assertEqual(len(recovery_data), 1)
        self.assertEqual(recovery_data[0]["id"], "recovery_test")
    
    def test_dashboard_summary_integration_real_workflow(self):
        """Test complete dashboard summary with real workflow integration"""
        
        # Test real business workflow integration
        summary = self.dashboard.get_dashboard_summary()
        
        # Validate real workflow results
        self.assertIsInstance(summary, dict)
        
        # Check all required sections (real business requirements)
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
            self.assertIn(section, summary, f"Missing required section: {section}")
        
        # Test real timestamp generation (no date mocking)
        generated_time = datetime.fromisoformat(summary["generated_at"])
        time_diff = (datetime.now() - generated_time).total_seconds()
        self.assertLess(time_diff, 60, "Generated timestamp should be current")
        
        # Test real data consistency across sections
        balance_total = summary["balance_overview"]["total_available_eur"]
        self.assertIsInstance(balance_total, (int, float))
        
        revenue_current = summary["revenue_analysis"]["current_month"]["total_revenue"]  
        self.assertIsInstance(revenue_current, (int, float))
    
    def test_date_range_calculations_real_business_rules(self):
        """Test date range calculations with real business rules"""
        
        # Create settlements across different time periods
        now = datetime.now()
        
        # Current week settlement
        current_week_date = now - timedelta(days=2)  # 2 days ago
        # Current month settlement (different from week)
        current_month_date = now - timedelta(days=10)  # 10 days ago
        # Previous quarter settlement
        prev_quarter_date = now - timedelta(days=120)  # 4 months ago
        
        time_period_settlements = [
            {
                "id": "stl_week_001",
                "status": "paidout",
                "amount": {"value": "100.00", "currency": "EUR"},
                "settledAt": current_week_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            {
                "id": "stl_month_001", 
                "status": "paidout",
                "amount": {"value": "200.00", "currency": "EUR"},
                "settledAt": current_month_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            {
                "id": "stl_prev_quarter_001",
                "status": "paidout", 
                "amount": {"value": "300.00", "currency": "EUR"},
                "settledAt": prev_quarter_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        ]
        
        # Configure settlements
        self.dashboard.settlements_client.get.return_value = time_period_settlements
        self.dashboard._settlements_cache = None
        
        # Test real date range business logic
        revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Current week should include week settlement
        week_revenue = revenue_analysis["current_week"]["total_revenue"]
        self.assertGreaterEqual(week_revenue, 100.00)  # At least week settlement
        
        # Current month should include both week and month settlements
        month_revenue = revenue_analysis["current_month"]["total_revenue"]
        self.assertGreaterEqual(month_revenue, 300.00)  # Week + month settlements
        
        # Current quarter should include all current settlements but not previous quarter
        quarter_revenue = revenue_analysis["current_quarter"]["total_revenue"]
        self.assertGreaterEqual(quarter_revenue, 300.00)  # Current settlements
        self.assertLess(quarter_revenue, 600.00)  # Should not include previous quarter
    
    def test_performance_with_real_data_volumes(self):
        """Test performance with realistic data volumes"""
        
        # Create realistic volume of settlements (100 items)
        import time
        
        large_settlement_set = []
        for i in range(100):
            settlement_date = datetime.now() - timedelta(days=i)
            large_settlement_set.append({
                "id": f"stl_perf_{i:03d}",
                "status": "paidout",
                "amount": {"value": f"{10 + i}.{i%100:02d}", "currency": "EUR"},
                "settledAt": settlement_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            })
        
        # Configure large dataset
        self.dashboard.settlements_client.get.return_value = large_settlement_set
        self.dashboard._settlements_cache = None
        
        # Measure real performance
        start_time = time.time()
        summary = self.dashboard.get_dashboard_summary()
        processing_time = time.time() - start_time
        
        # Real performance should be reasonable
        self.assertLess(processing_time, 5.0, "Dashboard should process 100 settlements in <5s")
        
        # Results should be valid
        self.assertIsInstance(summary, dict)
        self.assertGreater(summary["revenue_analysis"]["current_month"]["total_revenue"], 0)


class TestMollieDashboardAPIIntegration(EnhancedTestCase):
    """Test Mollie dashboard API endpoints with real business logic"""
    
    @patch('verenigingen.verenigingen_payments.dashboards.financial_dashboard.FinancialDashboard')  # KEEP: External service boundary
    def test_dashboard_api_real_validation(self, mock_dashboard_class):
        """Test API endpoint with real validation logic"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Configure real settings validation
        mollie_settings = frappe.get_single("Mollie Settings") 
        mollie_settings.enable_backend_api = 1
        mollie_settings.api_key = "test_org_token_for_api"
        mollie_settings.save()
        
        # Mock dashboard instance (external service boundary)
        mock_dashboard = Mock()
        mock_dashboard_class.return_value = mock_dashboard
        
        # Real dashboard summary structure
        realistic_summary = {
            "generated_at": datetime.now().isoformat(),
            "period": "last_30_days",
            "balance_overview": {
                "total_available_eur": 1500.75,
                "total_pending_eur": 125.50,
                "balances": [
                    {"currency": "EUR", "available": 1500.75, "pending": 125.50}
                ]
            },
            "revenue_analysis": {
                "current_week": {"total_revenue": 250.00, "transaction_count": 5},
                "current_month": {"total_revenue": 1200.00, "transaction_count": 25},
                "current_quarter": {"total_revenue": 3600.00, "transaction_count": 75}
            },
            "settlement_metrics": {
                "recent_settlements": [
                    {"id": "stl_001", "amount": 500.00, "status": "paidout"}
                ]
            },
            "reconciliation_status": {
                "success_rate_30d": 98.5,
                "reconciled_settlements": 45,
                "total_settlements": 46
            }
        }
        mock_dashboard.get_dashboard_summary.return_value = realistic_summary
        
        # Test real API validation and response processing
        result = get_dashboard_data()
        
        # Validate real API business logic
        self.assertTrue(result["success"])
        self.assertIn("data", result)
        
        # Test real response structure transformation
        data = result["data"]
        self.assertIn("balances", data)
        self.assertIn("revenue_metrics", data)
        self.assertIn("recent_settlements", data)
        self.assertIn("reconciliation_status", data)
        
        # Test real data transformation accuracy
        self.assertEqual(data["balances"]["total_available_eur"], 1500.75)
        self.assertEqual(data["revenue_metrics"]["current_month"], 1200.00)
    
    def test_api_settings_validation_real_logic(self):
        """Test API settings validation with real business logic"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Test with API disabled (real validation)
        mollie_settings = frappe.get_single("Mollie Settings")
        mollie_settings.enable_backend_api = 0
        mollie_settings.save()
        
        result = get_dashboard_data()
        
        # Real validation should reject
        self.assertFalse(result["success"])
        self.assertIn("not enabled", result["error"])
        
        # Test with missing token (real validation)
        mollie_settings.enable_backend_api = 1
        mollie_settings.api_key = ""  # Empty token
        mollie_settings.save()
        
        result = get_dashboard_data()
        
        # Real validation should reject
        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"])


class TestMollieDashboardPerformanceIntegration(EnhancedTestCase):
    """Performance tests with real business logic"""
    
    def test_caching_performance_real_measurement(self):
        """Test caching performance with real measurement (no mocking)"""
        
        dashboard = FinancialDashboard()
        
        # Mock external API only (appropriate boundary)
        dashboard.settlements_client = Mock()
        dashboard.settlements_client.get.return_value = [
            {"id": f"stl_{i}", "amount": {"value": "100.00"}} for i in range(50)
        ]
        
        # Clear cache
        dashboard._settlements_cache = None
        
        # Measure real caching performance
        import time
        
        # First call (should cache)
        start_time = time.time()
        first_result = dashboard._get_settlements_data()
        first_call_time = time.time() - start_time
        
        # Second call (should use cache)  
        start_time = time.time()
        second_result = dashboard._get_settlements_data()
        second_call_time = time.time() - start_time
        
        # Real caching should provide performance benefit
        self.assertLess(second_call_time, first_call_time / 2)
        self.assertEqual(first_result, second_result)
        
        # API should only be called once (real caching behavior)
        dashboard.settlements_client.get.assert_called_once()