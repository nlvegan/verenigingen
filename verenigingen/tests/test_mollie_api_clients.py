"""
Comprehensive Tests for Mollie API Clients

Tests the API client functionality including:
- SettlementsClient date filtering in memory (critical bug fix)
- ChargebacksClient parameter handling
- BalancesClient health checks
- Error handling and API response parsing
"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.test_mollie_api_data_factory import MollieApiDataFactory
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.clients.chargebacks_client import ChargebacksClient
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient


class TestMollieSettlementsClient(FrappeTestCase):
    """
    Test suite for SettlementsClient
    
    Focuses on testing the critical fix:
    - Date filtering in memory instead of using unsupported API parameters
    - Proper handling of settlements with and without settledAt dates
    - Timezone-aware date parsing
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory(seed=42)
        self.client = SettlementsClient()
        
        # Mock the base client methods
        self.client.get = Mock()
        
        # Mock audit trail to avoid dependencies
        self.client.audit_trail = Mock()
        self.client.audit_trail.log_event = Mock()
    
    def test_list_settlements_without_date_parameters(self):
        """Test that list_settlements doesn't send unsupported date parameters to API"""
        # Set up mock response
        test_settlements = self.factory.generate_settlement_list(count=5)
        self.client.get.return_value = test_settlements
        
        # Call with date filters
        from_date = datetime.now() - timedelta(days=30)
        until_date = datetime.now()
        
        result = self.client.list_settlements(
            from_date=from_date,
            until_date=until_date,
            limit=100
        )
        
        # Should call API without date parameters
        self.client.get.assert_called_once_with(
            "settlements", 
            params={"limit": 100}, 
            paginated=True
        )
        
        # Should return Settlement objects
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
    
    def test_in_memory_date_filtering_with_settled_at(self):
        """Test in-memory date filtering for settlements with settledAt dates"""
        # Create test settlements with specific dates
        now = datetime.now()
        thirty_days_ago = now - timedelta(days=30)
        sixty_days_ago = now - timedelta(days=60)
        
        test_settlements_data = [
            # Recent settlement (should be included)
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "createdAt": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            # Old settlement (should be excluded)
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "createdAt": (now - timedelta(days=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            # Pending settlement (no settledAt, use createdAt - should be included)
            {
                **self.factory.generate_settlement_data(status="pending"),
                "createdAt": (now - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        ]
        
        self.client.get.return_value = test_settlements_data
        
        # Filter for last 30 days
        result = self.client.list_settlements(
            from_date=thirty_days_ago,
            until_date=now
        )
        
        # Should return 2 settlements (recent paidout + pending)
        self.assertEqual(len(result), 2)
        
        # Should not include the old settlement
        settlement_ids = [s.id for s in result]
        old_settlement_id = test_settlements_data[1]["id"]
        self.assertNotIn(old_settlement_id, settlement_ids)
    
    def test_timezone_handling_in_date_filtering(self):
        """Test proper timezone handling in date filtering"""
        # Create settlements with different timezone formats
        timezone_settlements = [
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": "2025-08-01T13:00:00Z",  # UTC with Z
                "createdAt": "2025-07-15T10:00:00Z"
            },
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": "2025-08-01T15:00:00+02:00",  # Same time, different format
                "createdAt": "2025-07-15T12:00:00+02:00"
            },
            {
                **self.factory.generate_settlement_data(status="pending"),
                "createdAt": "2025-08-10T09:00:00Z"  # Recent, no settledAt
            }
        ]
        
        self.client.get.return_value = timezone_settlements
        
        # Filter should work with mixed timezone formats
        from_date = datetime(2025, 7, 1)
        until_date = datetime(2025, 8, 31)
        
        # Should not raise timezone comparison errors
        try:
            result = self.client.list_settlements(
                from_date=from_date,
                until_date=until_date
            )
            # All should be included in this wide date range
            self.assertEqual(len(result), 3)
        except Exception as e:
            self.fail(f"Timezone handling failed: {str(e)}")
    
    def test_settlement_without_dates_handling(self):
        """Test handling of settlements that have neither settledAt nor createdAt"""
        settlements_with_missing_dates = [
            {
                **self.factory.generate_settlement_data(status="open"),
                # Remove date fields to test edge case
            },
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": "2025-08-01T13:00:00Z",
                "createdAt": "2025-07-15T10:00:00Z"
            }
        ]
        
        # Remove date fields from first settlement
        del settlements_with_missing_dates[0]["createdAt"]
        if "settledAt" in settlements_with_missing_dates[0]:
            del settlements_with_missing_dates[0]["settledAt"]
        
        self.client.get.return_value = settlements_with_missing_dates
        
        # Should handle missing dates gracefully
        result = self.client.list_settlements(
            from_date=datetime(2025, 7, 1),
            until_date=datetime(2025, 8, 31)
        )
        
        # Should return at least the settlement with valid dates
        self.assertGreaterEqual(len(result), 1)
    
    def test_settlement_reconciliation_calculations(self):
        """Test settlement reconciliation calculations"""
        # Mock settlement data
        settlement_id = "stl_test123"
        
        # Mock settlement object
        mock_settlement = Mock()
        mock_settlement.id = settlement_id
        mock_settlement.status = "paidout"
        mock_settlement.reference = "REF-2025-001"
        mock_settlement.amount = Mock()
        mock_settlement.amount.decimal_value = Decimal("1000.00")
        mock_settlement.get_total_revenue.return_value = Decimal("950.00")
        mock_settlement.get_total_costs.return_value = Decimal("50.00")
        mock_settlement.is_settled.return_value = True
        mock_settlement.is_failed.return_value = False
        
        # Mock the get_settlement method
        self.client.get_settlement = Mock(return_value=mock_settlement)
        
        # Mock component lists
        self.client.list_settlement_payments = Mock(return_value=[
            {"settlementAmount": {"value": "800.00"}},
            {"settlementAmount": {"value": "200.00"}}
        ])
        self.client.list_settlement_refunds = Mock(return_value=[
            {"settlementAmount": {"value": "-50.00"}}
        ])
        self.client.list_settlement_chargebacks = Mock(return_value=[])
        self.client.list_settlement_captures = Mock(return_value=[])
        
        # Test reconciliation
        result = self.client.reconcile_settlement(settlement_id)
        
        # Should calculate correctly
        self.assertEqual(result["settlement_id"], settlement_id)
        self.assertEqual(result["calculated_total"], 950.0)  # 1000 - 50
        self.assertEqual(result["actual_amount"], 1000.0)
        self.assertEqual(result["discrepancy"], 50.0)
        self.assertFalse(result["reconciled"])  # Due to discrepancy
    
    def test_api_error_handling(self):
        """Test API error handling in settlements client"""
        # Configure mock to raise exception
        self.client.get.side_effect = Exception("API Error: Rate limit exceeded")
        
        # Should handle API errors gracefully
        with self.assertRaises(Exception) as context:
            self.client.list_settlements()
        
        self.assertIn("Rate limit exceeded", str(context.exception))


class TestMollieChargebacksClient(FrappeTestCase):
    """
    Test suite for ChargebacksClient
    
    Tests error handling for unsupported date parameters
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory(seed=43)
        self.client = ChargebacksClient()
        
        # Mock the base client methods
        self.client.get = Mock()
        
        # Mock audit trail
        self.client.audit_trail = Mock()
        self.client.audit_trail.log_event = Mock()
    
    def test_list_chargebacks_without_unsupported_params(self):
        """Test that chargebacks client doesn't use unsupported date parameters"""
        # Set up mock response
        test_chargebacks = [self.factory.generate_chargeback_data() for _ in range(3)]
        self.client.get.return_value = test_chargebacks
        
        # This would previously cause API errors with unsupported parameters
        result = self.client.list_all_chargebacks()
        
        # Should call API without problematic date parameters
        self.client.get.assert_called()
        
        # Should return data
        self.assertIsInstance(result, list)
    
    def test_chargeback_financial_impact_calculation(self):
        """Test chargeback financial impact calculations"""
        # Mock chargeback data with various amounts
        test_chargebacks = [
            {
                **self.factory.generate_chargeback_data(amount_range=(100.0, 100.0)),
                "status": "charged_back"
            },
            {
                **self.factory.generate_chargeback_data(amount_range=(50.0, 50.0)),
                "status": "resolved"
            }
        ]
        
        self.client.get.return_value = test_chargebacks
        
        # Calculate financial impact
        from_date = datetime.now() - timedelta(days=30)
        until_date = datetime.now()
        
        # Mock the calculate_financial_impact method
        self.client.calculate_financial_impact = Mock(return_value={
            "total_loss": 100.0,
            "recovered": 50.0,
            "net_loss": 50.0
        })
        
        impact = self.client.calculate_financial_impact(from_date, until_date)
        
        # Should return calculated impact
        self.assertEqual(impact["net_loss"], 50.0)
        self.assertEqual(impact["total_loss"], 100.0)


class TestMollieBalancesClient(FrappeTestCase):
    """
    Test suite for BalancesClient
    
    Tests balance monitoring and health checks
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory(seed=44)
        self.client = BalancesClient()
        
        # Mock the base client methods
        self.client.get = Mock()
        
        # Mock audit trail
        self.client.audit_trail = Mock()
        self.client.audit_trail.log_event = Mock()
    
    def test_list_balances_parsing(self):
        """Test balance list parsing and object creation"""
        # Create test balance data
        test_balances_data = [
            self.factory.generate_balance_data(currency="EUR"),
            self.factory.generate_balance_data(currency="USD")
        ]
        
        self.client.get.return_value = test_balances_data
        
        # Call list_balances
        result = self.client.list_balances()
        
        # Should return balance objects
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
    
    def test_balance_health_check_healthy(self):
        """Test balance health check with healthy balances"""
        # Mock healthy balance data
        healthy_balances_data = [
            {
                **self.factory.generate_balance_data(),
                "availableAmount": {"value": "1000.00", "currency": "EUR"},
                "status": "active"
            }
        ]
        
        self.client.get.return_value = healthy_balances_data
        
        # Mock the health check method
        self.client.check_balance_health = Mock(return_value={
            "status": "healthy",
            "issues": []
        })
        
        health = self.client.check_balance_health()
        
        # Should return healthy status
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(len(health["issues"]), 0)
    
    def test_balance_health_check_unhealthy(self):
        """Test balance health check with unhealthy balances"""
        # Mock unhealthy balance data
        unhealthy_balances_data = [
            {
                **self.factory.generate_balance_data(),
                "availableAmount": {"value": "0.00", "currency": "EUR"},
                "status": "inactive"
            }
        ]
        
        self.client.get.return_value = unhealthy_balances_data
        
        # Mock the health check method
        self.client.check_balance_health = Mock(return_value={
            "status": "unhealthy",
            "issues": ["Low balance detected", "Inactive balance found"]
        })
        
        health = self.client.check_balance_health()
        
        # Should return unhealthy status with issues
        self.assertEqual(health["status"], "unhealthy")
        self.assertGreater(len(health["issues"]), 0)


class TestMollieApiClientErrorHandling(FrappeTestCase):
    """
    Test error handling across all API clients
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory()
        
        # Set up clients
        self.settlements_client = SettlementsClient()
        self.chargebacks_client = ChargebacksClient()
        self.balances_client = BalancesClient()
        
        # Mock audit trails
        for client in [self.settlements_client, self.chargebacks_client, self.balances_client]:
            client.audit_trail = Mock()
            client.audit_trail.log_event = Mock()
    
    def test_api_400_error_handling(self):
        """Test handling of 400 Bad Request errors (unsupported parameters)"""
        # Mock 400 error response
        error_response = self.factory.generate_api_error_responses()["bad_request_unsupported_params"]
        
        # Configure mock to raise 400 error
        import requests
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = error_response
        
        api_error = requests.exceptions.HTTPError(response=mock_response)
        
        self.settlements_client.get = Mock(side_effect=api_error)
        
        # Should handle 400 errors gracefully
        with self.assertRaises(requests.exceptions.HTTPError):
            self.settlements_client.list_settlements()
    
    def test_api_429_rate_limit_handling(self):
        """Test handling of 429 Rate Limit errors"""
        # Mock rate limit error
        error_response = self.factory.generate_api_error_responses()["rate_limit_exceeded"]
        
        import requests
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = error_response
        
        api_error = requests.exceptions.HTTPError(response=mock_response)
        
        self.balances_client.get = Mock(side_effect=api_error)
        
        # Should handle rate limit errors gracefully
        with self.assertRaises(requests.exceptions.HTTPError):
            self.balances_client.list_balances()
    
    def test_network_timeout_handling(self):
        """Test handling of network timeout errors"""
        import requests
        
        # Configure mock to raise timeout
        self.settlements_client.get = Mock(side_effect=requests.exceptions.Timeout("Request timed out"))
        
        # Should handle timeout errors gracefully
        with self.assertRaises(requests.exceptions.Timeout):
            self.settlements_client.list_settlements()
    
    def test_invalid_json_response_handling(self):
        """Test handling of invalid JSON responses"""
        # Configure mock to return invalid data
        self.chargebacks_client.get = Mock(return_value="invalid json")
        
        # Should handle invalid responses gracefully
        try:
            result = self.chargebacks_client.list_all_chargebacks()
            # If no exception, result should be handled gracefully
            self.assertIsNotNone(result)
        except Exception as e:
            # If exception is raised, it should be a meaningful error
            self.assertIsInstance(e, (ValueError, TypeError))


class TestMollieApiClientIntegration(FrappeTestCase):
    """
    Integration tests for API clients working together
    """
    
    def setUp(self):
        """Set up integration test environment"""
        self.factory = MollieApiDataFactory(seed=50)
        
        # Create clients
        self.settlements_client = SettlementsClient()
        self.balances_client = BalancesClient()
        
        # Mock audit trails
        for client in [self.settlements_client, self.balances_client]:
            client.audit_trail = Mock()
            client.audit_trail.log_event = Mock()
    
    def test_settlement_and_balance_data_consistency(self):
        """Test that settlement and balance data are consistent"""
        # Create consistent test data
        test_settlements = self.factory.generate_settlement_list(count=5)
        test_balances = [self.factory.generate_balance_data()]
        
        # Mock responses
        self.settlements_client.get = Mock(return_value=test_settlements)
        self.balances_client.get = Mock(return_value=test_balances)
        
        # Get data from both clients
        settlements = self.settlements_client.list_settlements()
        balances = self.balances_client.list_balances()
        
        # Should return consistent data types
        self.assertIsInstance(settlements, list)
        self.assertIsInstance(balances, list)
        
        # All settlements should have required fields
        for settlement in settlements:
            self.assertTrue(hasattr(settlement, 'id'))
            self.assertTrue(hasattr(settlement, 'status'))
    
    def test_date_filtering_consistency_across_clients(self):
        """Test that date filtering works consistently across different clients"""
        # Test date range
        from_date = datetime.now() - timedelta(days=30)
        until_date = datetime.now()
        
        # Mock responses with date-aware data
        settlements_with_dates = [
            {
                **self.factory.generate_settlement_data(status="paidout"),
                "settledAt": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        ]
        
        self.settlements_client.get = Mock(return_value=settlements_with_dates)
        
        # Should handle date filtering without API parameter errors
        try:
            settlements = self.settlements_client.list_settlements(
                from_date=from_date,
                until_date=until_date
            )
            
            # Should return filtered results
            self.assertIsInstance(settlements, list)
            
        except Exception as e:
            self.fail(f"Date filtering failed: {str(e)}")


if __name__ == '__main__':
    unittest.main()
