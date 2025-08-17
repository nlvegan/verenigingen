"""
Integration tests for Mollie Balances API Client
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.core.models.balance import Balance, BalanceReport, BalanceTransaction


class TestBalancesClient(FrappeTestCase):
    """Test suite for Balances API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        
        # Create client instance with mocks
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'):
            self.client = BalancesClient("test_settings")
            self.client.audit_trail = self.mock_audit_trail
            self.client.settings = self.mock_settings

    def test_get_balance_primary(self):
        """Test retrieving primary balance"""
        # Mock response
        mock_response = {
            "resource": "balance",
            "id": "bal_test123",
            "mode": "test",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "currency": "EUR",
            "status": "active",
            "availableAmount": {
                "value": "1000.00",
                "currency": "EUR"
            },
            "pendingAmount": {
                "value": "250.00",
                "currency": "EUR"
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            # Call method
            balance = self.client.get_balance()
            
            # Verify API call
            mock_get.assert_called_once_with("/balances/primary")
            
            # Verify response
            self.assertIsInstance(balance, Balance)
            self.assertEqual(balance.id, "bal_test123")
            self.assertEqual(balance.currency, "EUR")
            self.assertEqual(balance.available_amount.decimal_value, Decimal("1000.00"))
            self.assertEqual(balance.pending_amount.decimal_value, Decimal("250.00"))
            
            # Verify audit logging
            self.mock_audit_trail.log_event.assert_called()

    def test_get_balance_by_id(self):
        """Test retrieving specific balance by ID"""
        balance_id = "bal_specific123"
        mock_response = {
            "resource": "balance",
            "id": balance_id,
            "currency": "USD",
            "status": "active",
            "availableAmount": {"value": "500.00", "currency": "USD"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            balance = self.client.get_balance(balance_id)
            
            mock_get.assert_called_once_with(f"/balances/{balance_id}")
            self.assertEqual(balance.id, balance_id)
            self.assertEqual(balance.currency, "USD")

    def test_list_balances(self):
        """Test listing all balances"""
        mock_response = [
            {
                "resource": "balance",
                "id": "bal_eur",
                "currency": "EUR",
                "status": "active"
            },
            {
                "resource": "balance",
                "id": "bal_usd",
                "currency": "USD",
                "status": "active"
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            balances = self.client.list_balances()
            
            mock_get.assert_called_once_with("/balances", params={"limit": 10}, paginated=True)
            self.assertEqual(len(balances), 2)
            self.assertIsInstance(balances[0], Balance)
            self.assertEqual(balances[0].currency, "EUR")
            self.assertEqual(balances[1].currency, "USD")

    def test_get_balance_report(self):
        """Test retrieving balance report"""
        balance_id = "bal_test123"
        mock_response = {
            "resource": "balance-report",
            "balanceId": balance_id,
            "timeZone": "Europe/Amsterdam",
            "from": "2024-01-01",
            "until": "2024-01-31",
            "grouping": "transaction-categories"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            report = self.client.get_balance_report(
                balance_id,
                from_date=datetime(2024, 1, 1),
                until_date=datetime(2024, 1, 31)
            )
            
            expected_params = {
                "from": "2024-01-01",
                "until": "2024-01-31",
                "grouping": "transaction-categories"
            }
            mock_get.assert_called_once_with(
                f"/balances/{balance_id}/report",
                params=expected_params
            )
            
            self.assertIsInstance(report, BalanceReport)
            self.assertEqual(report.balance_id, balance_id)

    def test_list_balance_transactions(self):
        """Test listing balance transactions"""
        balance_id = "bal_test123"
        mock_response = [
            {
                "resource": "balance-transaction",
                "id": "baltr_1",
                "type": "payment",
                "resultAmount": {"value": "10.00", "currency": "EUR"},
                "createdAt": "2024-01-15T10:00:00Z"
            },
            {
                "resource": "balance-transaction",
                "id": "baltr_2",
                "type": "refund",
                "resultAmount": {"value": "-5.00", "currency": "EUR"},
                "createdAt": "2024-01-15T11:00:00Z"
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            transactions = self.client.list_balance_transactions(
                balance_id,
                from_date=datetime(2024, 1, 15)
            )
            
            expected_params = {
                "from": "2024-01-15",
                "limit": 250
            }
            mock_get.assert_called_once_with(
                f"/balances/{balance_id}/transactions",
                params=expected_params,
                paginated=True
            )
            
            self.assertEqual(len(transactions), 2)
            self.assertIsInstance(transactions[0], BalanceTransaction)
            self.assertEqual(transactions[0].type, "payment")
            self.assertEqual(transactions[1].type, "refund")

    def test_monitor_balance_changes(self):
        """Test balance monitoring with alerts"""
        balance_id = "bal_test123"
        
        # Mock two different balance states
        initial_balance = {
            "resource": "balance",
            "id": balance_id,
            "availableAmount": {"value": "1000.00", "currency": "EUR"},
            "pendingAmount": {"value": "100.00", "currency": "EUR"}
        }
        
        updated_balance = {
            "resource": "balance",
            "id": balance_id,
            "availableAmount": {"value": "500.00", "currency": "EUR"},
            "pendingAmount": {"value": "150.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', side_effect=[initial_balance, updated_balance]):
            with patch('frappe.publish_realtime') as mock_publish:
                changes = self.client.monitor_balance_changes(balance_id)
                
                # Verify changes detected
                self.assertEqual(changes["balance_id"], balance_id)
                self.assertEqual(changes["available_change"], -500.0)
                self.assertEqual(changes["pending_change"], 50.0)
                self.assertTrue(changes["alert_triggered"])
                
                # Verify realtime alert
                mock_publish.assert_called()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "balance_alert")

    def test_reconcile_balance(self):
        """Test balance reconciliation"""
        balance_id = "bal_test123"
        
        # Mock balance and transactions
        mock_balance = {
            "resource": "balance",
            "id": balance_id,
            "availableAmount": {"value": "1000.00", "currency": "EUR"},
            "pendingAmount": {"value": "200.00", "currency": "EUR"}
        }
        
        mock_transactions = [
            {
                "resource": "balance-transaction",
                "type": "payment",
                "resultAmount": {"value": "1500.00", "currency": "EUR"},
                "status": "completed"
            },
            {
                "resource": "balance-transaction",
                "type": "refund",
                "resultAmount": {"value": "-300.00", "currency": "EUR"},
                "status": "completed"
            }
        ]
        
        with patch.object(self.client, 'get', side_effect=[mock_balance, mock_transactions]):
            result = self.client.reconcile_balance(balance_id)
            
            # Verify reconciliation results
            self.assertEqual(result["balance_id"], balance_id)
            self.assertEqual(result["current_available"], 1000.0)
            self.assertEqual(result["transaction_total"], 1200.0)
            self.assertTrue(result["reconciled"])

    def test_check_balance_health(self):
        """Test balance health check"""
        # Mock unhealthy balance (negative available)
        mock_response = {
            "resource": "balance",
            "id": "bal_test",
            "availableAmount": {"value": "-100.00", "currency": "EUR"},
            "pendingAmount": {"value": "1500.00", "currency": "EUR"},
            "currency": "EUR"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            with patch('frappe.publish_realtime') as mock_publish:
                health = self.client.check_balance_health()
                
                # Verify health issues detected
                self.assertEqual(health["status"], "unhealthy")
                self.assertIn("Negative available balance", health["issues"])
                self.assertIn("High pending amount", health["issues"])
                
                # Verify alert sent
                mock_publish.assert_called()

    def test_get_available_payout_amount(self):
        """Test calculating available payout amount"""
        mock_response = {
            "resource": "balance",
            "availableAmount": {"value": "5000.00", "currency": "EUR"},
            "pendingAmount": {"value": "500.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            amount = self.client.get_available_payout_amount()
            
            # Default reserve is 10%
            expected = 5000.0 * 0.9  # 4500.0
            self.assertEqual(amount["available_for_payout"], expected)
            self.assertEqual(amount["reserve_amount"], 500.0)
            
            # Test with custom reserve
            amount = self.client.get_available_payout_amount(reserve_percentage=20)
            expected = 5000.0 * 0.8  # 4000.0
            self.assertEqual(amount["available_for_payout"], expected)

    def test_track_balance_trend(self):
        """Test balance trend tracking"""
        balance_id = "bal_test123"
        
        # Mock balance snapshots
        mock_balance = {
            "resource": "balance",
            "id": balance_id,
            "availableAmount": {"value": "1500.00", "currency": "EUR"},
            "pendingAmount": {"value": "300.00", "currency": "EUR"},
            "currency": "EUR"
        }
        
        # Mock transactions for trend analysis
        mock_transactions = [
            {
                "resource": "balance-transaction",
                "type": "payment",
                "resultAmount": {"value": "100.00", "currency": "EUR"},
                "createdAt": datetime.now().isoformat()
            }
            for _ in range(5)  # 5 payments
        ]
        
        with patch.object(self.client, 'get', side_effect=[mock_balance, mock_transactions]):
            trend = self.client.track_balance_trend(balance_id, days=7)
            
            # Verify trend analysis
            self.assertEqual(trend["balance_id"], balance_id)
            self.assertEqual(trend["current_available"], 1500.0)
            self.assertEqual(trend["transaction_count"], 5)
            self.assertEqual(trend["total_inflow"], 500.0)

    def test_error_handling(self):
        """Test error handling in client methods"""
        # Test API error
        with patch.object(self.client, 'get', side_effect=Exception("API Error")):
            with self.assertRaises(Exception):
                self.client.get_balance()
            
            # Verify error logged
            self.mock_audit_trail.log_event.assert_called()

    def test_balance_currency_conversion(self):
        """Test multi-currency balance handling"""
        mock_balances = [
            {
                "resource": "balance",
                "currency": "EUR",
                "availableAmount": {"value": "1000.00", "currency": "EUR"}
            },
            {
                "resource": "balance",
                "currency": "USD",
                "availableAmount": {"value": "1200.00", "currency": "USD"}
            },
            {
                "resource": "balance",
                "currency": "GBP",
                "availableAmount": {"value": "800.00", "currency": "GBP"}
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_balances):
            balances = self.client.list_balances()
            
            # Verify multiple currencies handled
            currencies = [b.currency for b in balances]
            self.assertIn("EUR", currencies)
            self.assertIn("USD", currencies)
            self.assertIn("GBP", currencies)


if __name__ == "__main__":
    unittest.main()