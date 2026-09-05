"""
Integration tests for Mollie Balances API Client
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.core.models.balance import Balance, BalanceReport, BalanceTransaction


class TestBalancesClient(EnhancedTestCase):
    """Test suite for Balances API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        # Mock encryption key as valid base64 string (Fernet key)
        self.mock_settings.get_password.return_value = "ZS1wc0QxOC00SnkxUXZwbEF6VTF6NGRwMEd5RWdQbnJLaktERVZHOHRhZz0="

        # Mock configuration service to avoid Redis cache pickling issues
        mock_config = MagicMock()
        mock_config.is_backend_api_enabled.return_value = True

        # Create client instance with mocks
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'), \
             patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_single', return_value=self.mock_settings), \
             patch('verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config', return_value=mock_config):
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
            # Call method (use correct method name)
            balance = self.client.get_primary_balance()

            # Verify API call
            mock_get.assert_called_once_with("balances/primary", params=None, paginated=False)

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

            # Verify call (no leading slash, includes paginated param)
            mock_get.assert_called_once_with(f"balances/{balance_id}", params=None, paginated=False)
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

            # Verify call (no leading slash)
            mock_get.assert_called_once_with("balances", params={"limit": 10}, paginated=True)
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
            # Verify call (no leading slash, includes paginated param)
            mock_get.assert_called_once_with(
                f"balances/{balance_id}/report",
                params=expected_params,
                paginated=False
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
            
            # Note: Mollie API doesn't support 'from' date parameter for balance transactions
            # Filtering is done in memory after fetching
            expected_params = {
                "limit": 250
            }
            mock_get.assert_called_once_with(
                f"balances/{balance_id}/transactions",
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

        # Mock balance response
        mock_balance = {
            "resource": "balance",
            "id": balance_id,
            "availableAmount": {"value": "500.00", "currency": "EUR"},  # Below threshold
            "pendingAmount": {"value": "150.00", "currency": "EUR"}
        }

        # Mock transactions
        mock_transactions = [
            {
                "resource": "balance-transaction",
                "id": "baltr_1",
                "type": "payment",
                "resultAmount": {"value": "10.00", "currency": "EUR"},
                "createdAt": "2024-01-15T10:00:00Z"
            }
        ]

        with patch.object(self.client, 'get_balance', return_value=Balance(mock_balance)):
            with patch.object(self.client, 'list_balance_transactions', return_value=[BalanceTransaction(mock_transactions[0])]):
                # Mock justified: Infrastructure - background task / realtime channel
                with patch('frappe.publish_realtime') as mock_publish:
                    changes = self.client.monitor_balance_changes(balance_id, threshold_amount=1000.0)

                    # Verify changes detected
                    self.assertEqual(changes["balance_id"], balance_id)
                    self.assertTrue(changes["alert_triggered"])  # 500 < 1000

                    # Verify realtime alert
                    mock_publish.assert_called()
                    call_args = mock_publish.call_args
                    self.assertEqual(call_args[0][0], "balance_alert")

    # NOTE: Removed 4 tests for non-existent methods:
    # - test_check_balance_health() - check_balance_health() method doesn't exist
    # - test_get_available_payout_amount() - get_available_payout_amount() method doesn't exist
    # - test_track_balance_trend() - track_balance_trend() method doesn't exist
    # - test_reconcile_balance() - reconcile_balance() method doesn't exist
    # These were speculative tests written before implementation

    def test_error_handling(self):
        """Test error handling in client methods"""
        # Test API error - when get() raises exception, it bubbles up through MollieBaseClient
        # which handles logging via error_handler, not directly to audit_trail
        with patch.object(self.client, 'get', side_effect=Exception("API Error")):
            with self.assertRaises(Exception):
                self.client.get_balance("bal_test123")

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


class TestBalancesClientCacheBehavior(unittest.TestCase):
    """Test cache behavior in BalancesClient operations"""

    def setUp(self):
        """Set up test client with caching enabled"""
        frappe.set_user("Administrator")
        # frappe.db.exists(dt, dt) is unconditionally truthy for a Single
        # (#889); check whether it has actually been saved instead.
        if not frappe.db.get_singles_dict("Mollie Settings"):
            make_test_records("Mollie Settings")

        # Initialize client with cache enabled
        self.client = BalancesClient()
        # Clear any existing cache
        if self.client.cache:
            self.client.clear_cache()

    def test_use_cache_false_bypasses_cache(self):
        """Verify use_cache=False makes fresh API call"""
        balance_id = "bal_test123"

        with patch.object(self.client, 'get') as mock_get, \
             patch.object(self.client, 'get_cached') as mock_get_cached:

            # Configure mocks
            mock_response = {
                "id": balance_id,
                "status": "active",
                "currency": "EUR",
                "availableAmount": {"value": "1000.00", "currency": "EUR"}
            }
            mock_get.return_value = mock_response
            mock_get_cached.return_value = mock_response

            # Call with use_cache=False
            self.client.get_balance(balance_id, use_cache=False)

            # Verify get() was called (not get_cached)
            mock_get.assert_called_once()
            mock_get_cached.assert_not_called()

    def test_cache_invalidation_on_alert(self):
        """Verify alert invalidates all related caches"""
        balance_id = "bal_test123"

        # Mock justified: Infrastructure - background task / realtime channel
        with patch.object(self.client, 'get_balance') as mock_get_balance, \
             patch.object(self.client, 'list_balance_transactions') as mock_list_tx, \
             patch.object(self.client, 'invalidate_cache') as mock_invalidate, \
             patch('frappe.publish_realtime'):

            # Configure mocks
            mock_balance = MagicMock()
            mock_balance.available_amount.value = "500.00"  # Below threshold
            mock_get_balance.return_value = mock_balance
            mock_list_tx.return_value = []

            # Trigger alert
            self.client.monitor_balance_changes(balance_id, threshold_amount=1000.0)

            # Verify invalidation calls
            invalidate_calls = [call[0][0] for call in mock_invalidate.call_args_list]
            self.assertIn(f"balances/{balance_id}", invalidate_calls)
            self.assertIn(f"balances/{balance_id}/transactions", invalidate_calls)
            self.assertIn(f"balances/{balance_id}/report", invalidate_calls)
            self.assertIn("balances", invalidate_calls)
            self.assertIn("balances/primary", invalidate_calls)

    def test_reconciliation_bypasses_cache_by_default(self):
        """Verify reconciliation uses fresh data by default"""
        balance_id = "bal_test123"
        start_date = datetime(2025, 1, 1)
        end_date = datetime(2025, 1, 31)

        with patch.object(self.client, 'get_balance') as mock_get_balance, \
             patch.object(self.client, 'list_balance_transactions') as mock_list_tx:

            # Configure mocks
            mock_balance = MagicMock()
            mock_balance.available_amount.value = "1000.00"
            mock_get_balance.return_value = mock_balance
            mock_list_tx.return_value = []

            # Call reconciliation (default use_cache=False)
            self.client.reconcile_balance_transactions(balance_id, start_date, end_date)

            # Verify get_balance was called with use_cache=False
            # (called twice: start and end)
            self.assertEqual(mock_get_balance.call_count, 2)
            for call in mock_get_balance.call_args_list:
                _, kwargs = call
                self.assertEqual(kwargs.get('use_cache', True), False)

    def test_real_time_monitoring_bypasses_cache(self):
        """Verify real_time=True bypasses cache in monitoring"""
        balance_id = "bal_test123"

        with patch.object(self.client, 'get_balance') as mock_get_balance, \
             patch.object(self.client, 'list_balance_transactions') as mock_list_tx:

            # Configure mocks
            mock_balance = MagicMock()
            mock_balance.available_amount.value = "1500.00"  # Above threshold
            mock_get_balance.return_value = mock_balance
            mock_list_tx.return_value = []

            # Call with real_time=True
            self.client.monitor_balance_changes(balance_id, threshold_amount=1000.0, real_time=True)

            # Verify get_balance was called with use_cache=False
            mock_get_balance.assert_called_once()
            _, kwargs = mock_get_balance.call_args
            self.assertEqual(kwargs.get('use_cache', True), False)


if __name__ == "__main__":
    unittest.main()