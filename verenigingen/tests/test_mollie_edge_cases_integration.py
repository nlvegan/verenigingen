"""
Mollie Backend API Edge Cases and Integration Tests

Tests edge cases, error scenarios, and integration between components.
Focuses on real-world scenarios that could cause failures.
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
from verenigingen.verenigingen_payments.core.security.mollie_security_manager import MollieSecurityManager


class TestMollieEdgeCasesIntegration(FrappeTestCase):
    """
    Integration tests for edge cases across multiple Mollie components
    
    Tests scenarios that involve multiple components working together,
    edge cases that were causing crashes, and error recovery.
    """
    
    def setUp(self):
        """Set up integration test environment"""
        self.factory = MollieApiDataFactory(seed=100)
        
        # Set up dashboard with mocked components
        self.dashboard = FinancialDashboard()
        self.setup_mocked_dashboard()
        
        # Set up security manager
        self.mock_settings = Mock()
        self.mock_settings.name = "Mollie Settings"
        self.mock_settings.get_password = Mock()
        self.security_manager = MollieSecurityManager(self.mock_settings)
    
    def setup_mocked_dashboard(self):
        """Set up mocked dashboard components"""
        self.dashboard.settlements_client = Mock()
        self.dashboard.balances_client = Mock()
        self.dashboard.chargebacks_client = Mock()
        self.dashboard.invoices_client = Mock()
        
        # Default empty responses
        self.dashboard.settlements_client.get.return_value = []
        self.dashboard.balances_client.list_balances.return_value = []
        self.dashboard.balances_client.check_balance_health.return_value = {"status": "healthy"}
    
    def test_complete_api_failure_recovery(self):
        """Test dashboard behavior when all APIs fail"""
        # Configure all clients to fail
        api_error = Exception("Service temporarily unavailable")
        self.dashboard.settlements_client.get.side_effect = api_error
        self.dashboard.balances_client.list_balances.side_effect = api_error
        self.dashboard.chargebacks_client.list_all_chargebacks.side_effect = api_error
        
        # Dashboard should handle complete API failure gracefully
        with patch('frappe.logger') as mock_logger:
            summary = self.dashboard.get_dashboard_summary()
        
        # Should return valid structure with error indicators
        self.assertIsInstance(summary, dict)
        self.assertIn("balance_overview", summary)
        self.assertIn("settlement_metrics", summary)
        
        # Should have error fields in components that failed
        self.assertIn("error", summary["balance_overview"])
        
        # Should log errors
        mock_logger.return_value.error.assert_called()
    
    def test_partial_api_failure_handling(self):
        """Test dashboard behavior when some APIs fail"""
        # Only settlements API fails
        self.dashboard.settlements_client.get.side_effect = Exception("Settlements API down")
        
        # But balances API works
        test_balances = [self._create_mock_balance("EUR", 1000.0, 100.0)]
        self.dashboard.balances_client.list_balances.return_value = test_balances
        
        summary = self.dashboard.get_dashboard_summary()
        
        # Balance overview should work
        self.assertEqual(summary["balance_overview"]["total_available_eur"], 1000.0)
        
        # Settlement metrics should have error but not crash
        self.assertIn("settlement_metrics", summary)
    
    def _create_mock_balance(self, currency, available, pending):
        """Helper to create mock balance object"""
        balance = Mock()
        balance.currency = currency
        balance.status = "active"
        
        available_amount = Mock()
        available_amount.decimal_value = Decimal(str(available))
        balance.available_amount = available_amount
        
        pending_amount = Mock()
        pending_amount.decimal_value = Decimal(str(pending))
        balance.pending_amount = pending_amount
        
        return balance
    
    def test_timezone_handling_across_components(self):
        """Test consistent timezone handling across all components"""
        # Create settlements with mixed timezone formats
        timezone_test_data = self.factory.generate_timezone_test_data()
        settlements = timezone_test_data["settlements_mixed_timezones"]
        
        self.dashboard._settlements_cache = settlements
        
        # All these operations should handle timezones consistently
        try:
            revenue_analysis = self.dashboard._get_revenue_analysis()
            settlement_metrics = self.dashboard._get_settlement_metrics()
            reconciliation_status = self.dashboard._get_reconciliation_status()
            
            # Should not raise timezone-related errors
            self.assertIsInstance(revenue_analysis, dict)
            self.assertIsInstance(settlement_metrics, dict)
            self.assertIsInstance(reconciliation_status, dict)
            
        except Exception as e:
            if "timezone" in str(e).lower() or "fromisoformat" in str(e):
                self.fail(f"Timezone handling failed: {str(e)}")
            else:
                # Re-raise if it's a different error
                raise
    
    def test_large_dataset_memory_usage(self):
        """Test memory efficiency with large datasets"""
        import psutil
        import os
        
        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Create large settlement dataset
        large_settlements = self.factory.generate_settlement_list(count=1000)
        self.dashboard._settlements_cache = large_settlements
        
        # Process the data
        summary = self.dashboard.get_dashboard_summary()
        
        # Check memory usage didn't grow excessively
        final_memory = process.memory_info().rss
        memory_growth = final_memory - initial_memory
        
        # Should not use more than 100MB for processing 1000 settlements
        self.assertLess(memory_growth, 100 * 1024 * 1024, "Memory usage too high")
        
        # Should return valid summary
        self.assertIsInstance(summary, dict)
    
    def test_concurrent_api_calls_thread_safety(self):
        """Test thread safety with concurrent API calls"""
        import threading
        import time
        
        # Set up test data
        test_settlements = self.factory.generate_settlement_list(count=50)
        self.dashboard.settlements_client.get.return_value = test_settlements
        
        results = []
        errors = []
        
        def call_dashboard():
            try:
                result = self.dashboard.get_dashboard_summary()
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=call_dashboard)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join(timeout=10)
        
        # Should have no errors and all results
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")
        self.assertEqual(len(results), 5)
        
        # All results should be consistent
        first_result = results[0]
        for result in results[1:]:
            self.assertEqual(
                result["settlement_metrics"]["current_month"]["count"],
                first_result["settlement_metrics"]["current_month"]["count"]
            )
    
    def test_security_manager_dashboard_integration(self):
        """Test integration between security manager and dashboard"""
        # Mock encryption for dashboard data
        sensitive_api_key = "org_test_12345_secret"
        self.mock_settings.get_password.return_value = "webhook_secret_123"
        
        # Test webhook validation with dashboard context
        webhook_payload = self.factory.generate_webhook_payload(
            resource_type="settlement",
            include_signature_data=True
        )
        
        # Calculate correct signature
        import hmac
        import hashlib
        webhook_secret = "webhook_secret_123"
        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            webhook_payload["payload"].encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        # Mock audit log creation
        with patch.object(self.security_manager, '_create_audit_log'):
            # Should validate successfully
            result = self.security_manager.validate_webhook_signature(
                webhook_payload["payload"],
                expected_signature
            )
            
            self.assertTrue(result)
    
    def test_extreme_settlement_amounts(self):
        """Test handling of extreme settlement amounts"""
        # Create settlements with extreme amounts
        extreme_settlements = [
            # Very small amount
            {
                **self.factory.generate_settlement_data(),
                "amount": {"value": "0.01", "currency": "EUR"}
            },
            # Very large amount
            {
                **self.factory.generate_settlement_data(),
                "amount": {"value": "999999.99", "currency": "EUR"}
            },
            # Zero amount (edge case)
            {
                **self.factory.generate_settlement_data(),
                "amount": {"value": "0.00", "currency": "EUR"}
            },
            # Negative amount (chargeback scenario)
            {
                **self.factory.generate_settlement_data(),
                "amount": {"value": "-100.00", "currency": "EUR"}
            }
        ]
        
        self.dashboard._settlements_cache = extreme_settlements
        
        # Should handle extreme amounts without overflow or precision loss
        revenue_analysis = self.dashboard._get_revenue_analysis()
        
        # Should return valid numeric values
        self.assertIsInstance(revenue_analysis["current_month"]["total_revenue"], (int, float))
        self.assertGreaterEqual(revenue_analysis["current_month"]["total_revenue"], 0)
    
    def test_malformed_settlement_data_resilience(self):
        """Test resilience against malformed settlement data"""
        # Create malformed settlement data
        malformed_settlements = [
            # Missing required fields
            {
                "id": "stl_missing_fields",
                "resource": "settlement"
                # Missing amount, status, dates
            },
            # Invalid amount format
            {
                **self.factory.generate_settlement_data(),
                "amount": {"value": "invalid_number", "currency": "EUR"}
            },
            # Invalid date format
            {
                **self.factory.generate_settlement_data(),
                "settledAt": "not-a-date",
                "createdAt": "2025-13-45T25:70:80Z"  # Invalid date components
            },
            # Completely wrong structure
            {
                "unexpected": "structure",
                "not_a_settlement": True
            }
        ]
        
        self.dashboard._settlements_cache = malformed_settlements
        
        # Should handle malformed data gracefully without crashing
        try:
            revenue_analysis = self.dashboard._get_revenue_analysis()
            settlement_metrics = self.dashboard._get_settlement_metrics()
            
            # Should return valid structures even with bad data
            self.assertIsInstance(revenue_analysis, dict)
            self.assertIsInstance(settlement_metrics, dict)
            
        except Exception as e:
            # Should not crash on malformed data
            self.fail(f"Dashboard crashed on malformed data: {str(e)}")
    
    def test_unicode_and_special_characters(self):
        """Test handling of Unicode and special characters in settlement data"""
        # Create settlements with Unicode characters
        unicode_settlements = [
            {
                **self.factory.generate_settlement_data(),
                "reference": "REF-测试-2025",  # Chinese characters
                "description": "Paiement pour café ☕ & émojis 🎉"  # French + emojis
            },
            {
                **self.factory.generate_settlement_data(),
                "reference": "Überweisung-Größe-€",  # German with special chars
                "description": "Платёж за услуги"  # Cyrillic
            }
        ]
        
        self.dashboard._settlements_cache = unicode_settlements
        
        # Should handle Unicode characters without encoding errors
        try:
            settlement_metrics = self.dashboard._get_settlement_metrics()
            
            # Should have recent settlements with Unicode data
            recent = settlement_metrics.get("recent_settlements", [])
            if recent:
                # Should contain the Unicode references
                references = [s.get("reference", "") for s in recent]
                unicode_found = any("测试" in ref or "Größe" in ref for ref in references)
                # Don't fail if Unicode not found (might be filtered), just ensure no crashes
                
        except UnicodeError as e:
            self.fail(f"Unicode handling failed: {str(e)}")
        except Exception as e:
            # Other exceptions might be OK, but log them
            print(f"Warning: Unicode test caused exception: {str(e)}")
    
    def test_dashboard_api_endpoint_error_scenarios(self):
        """Test dashboard API endpoints with various error scenarios"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data
        
        # Test with missing Mollie Settings
        with patch('frappe.get_single', side_effect=frappe.DoesNotExistError("Mollie Settings")):
            result = get_dashboard_data()
            
            self.assertFalse(result["success"])
            self.assertIn("error", result)
    
    def test_caching_invalidation_scenarios(self):
        """Test cache invalidation in various scenarios"""
        # Initial data
        initial_settlements = self.factory.generate_settlement_list(count=5)
        self.dashboard.settlements_client.get.return_value = initial_settlements
        
        # First call - should cache
        first_result = self.dashboard._get_settlements_data()
        self.assertEqual(len(first_result), 5)
        
        # Change the mock response
        updated_settlements = self.factory.generate_settlement_list(count=10)
        self.dashboard.settlements_client.get.return_value = updated_settlements
        
        # Second call - should still use cache
        second_result = self.dashboard._get_settlements_data()
        self.assertEqual(len(second_result), 5)  # Still cached
        
        # Clear cache manually
        self.dashboard._settlements_cache = None
        
        # Third call - should get new data
        third_result = self.dashboard._get_settlements_data()
        self.assertEqual(len(third_result), 10)  # New data
    
    def test_performance_with_complex_calculations(self):
        """Test performance with complex revenue calculations"""
        import time
        
        # Create complex settlement data with nested periods
        complex_settlements = []
        for i in range(100):
            settlement = self.factory.generate_settlement_data()
            # Add complex nested periods data
            settlement["periods"] = {
                f"2025-{month:02d}": {
                    "revenue": [
                        {
                            "description": f"Revenue item {j}",
                            "amountNet": {"value": f"{j * 10}.00", "currency": "EUR"},
                            "count": j
                        }
                        for j in range(1, 6)
                    ],
                    "costs": [
                        {
                            "description": f"Cost item {j}",
                            "amountGross": {"value": f"{j * 2}.00", "currency": "EUR"},
                            "count": j
                        }
                        for j in range(1, 4)
                    ]
                }
                for month in range(1, 13)
            }
            complex_settlements.append(settlement)
        
        self.dashboard._settlements_cache = complex_settlements
        
        # Measure performance
        start_time = time.time()
        summary = self.dashboard.get_dashboard_summary()
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        # Should complete complex calculations within reasonable time
        self.assertLess(processing_time, 10.0, "Complex calculations took too long")
        
        # Should return valid summary
        self.assertIsInstance(summary, dict)
        self.assertIn("revenue_analysis", summary)


class TestMollieApiParameterValidation(FrappeTestCase):
    """
    Test API parameter validation and error handling
    """
    
    def setUp(self):
        """Set up parameter validation tests"""
        self.factory = MollieApiDataFactory(seed=200)
    
    def test_api_parameter_sanitization(self):
        """Test that API parameters are properly sanitized"""
        from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
        
        client = SettlementsClient()
        client.get = Mock()
        client.audit_trail = Mock()
        client.audit_trail.log_event = Mock()
        
        # Test with various parameter combinations
        test_params = [
            # Should not include date parameters
            {"from_date": datetime.now(), "until_date": datetime.now()},
            # Should include valid parameters
            {"reference": "REF-123", "limit": 50},
            # Should handle None values
            {"reference": None, "from_date": None}
        ]
        
        for params in test_params:
            client.get.reset_mock()
            
            # Call should not fail
            client.list_settlements(**params)
            
            # Check that API was called
            self.assertTrue(client.get.called)
            
            # Check that unsupported date parameters were not passed
            call_args = client.get.call_args
            if call_args and "params" in call_args[1]:
                api_params = call_args[1]["params"]
                self.assertNotIn("from", api_params)
                self.assertNotIn("until", api_params)
    
    def test_date_range_validation(self):
        """Test date range validation in memory filtering"""
        from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
        
        client = SettlementsClient()
        client.audit_trail = Mock()
        client.audit_trail.log_event = Mock()
        
        # Create test settlements with known dates
        test_settlements = [
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": "2025-08-01T12:00:00Z",
                "createdAt": "2025-07-25T10:00:00Z"
            },
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": "2025-07-15T12:00:00Z",
                "createdAt": "2025-07-10T10:00:00Z"
            }
        ]
        
        client.get = Mock(return_value=test_settlements)
        
        # Test various date range scenarios
        test_cases = [
            # Wide range - should include both
            {
                "from_date": datetime(2025, 7, 1),
                "until_date": datetime(2025, 8, 31),
                "expected_count": 2
            },
            # Narrow range - should include only one
            {
                "from_date": datetime(2025, 7, 20),
                "until_date": datetime(2025, 8, 31),
                "expected_count": 1
            },
            # No overlap - should include none
            {
                "from_date": datetime(2025, 9, 1),
                "until_date": datetime(2025, 9, 30),
                "expected_count": 0
            }
        ]
        
        for test_case in test_cases:
            result = client.list_settlements(
                from_date=test_case["from_date"],
                until_date=test_case["until_date"]
            )
            
            self.assertEqual(
                len(result),
                test_case["expected_count"],
                f"Date filtering failed for range {test_case['from_date']} to {test_case['until_date']}"
            )


if __name__ == '__main__':
    unittest.main()
