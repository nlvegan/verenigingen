"""
Integration tests for Mollie Settlements API Client
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.core.models.settlement import (
    Settlement,
    SettlementCapture,
    SettlementPeriod,
    SettlementStatus,
)


class TestSettlementsClient(FrappeTestCase):
    """Test suite for Settlements API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        
        # Create client instance
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'):
            self.client = SettlementsClient("test_settings")
            self.client.audit_trail = self.mock_audit_trail
            self.client.settings = self.mock_settings

    def test_get_settlement(self):
        """Test retrieving a specific settlement"""
        settlement_id = "stl_test123"
        mock_response = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": "1234567.2024.01",
            "createdAt": "2024-01-15T10:00:00+00:00",
            "settledAt": "2024-01-16T10:00:00+00:00",
            "status": "paidout",
            "amount": {
                "value": "1000.00",
                "currency": "EUR"
            },
            "periods": {
                "2024-01": {
                    "revenue": [
                        {"amountNet": {"value": "1100.00", "currency": "EUR"}}
                    ],
                    "costs": [
                        {"amountNet": {"value": "100.00", "currency": "EUR"}}
                    ]
                }
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            settlement = self.client.get_settlement(settlement_id)
            
            # Verify API call
            mock_get.assert_called_once_with(f"/settlements/{settlement_id}")
            
            # Verify response
            self.assertIsInstance(settlement, Settlement)
            self.assertEqual(settlement.id, settlement_id)
            self.assertEqual(settlement.reference, "1234567.2024.01")
            self.assertEqual(settlement.status, "paidout")
            self.assertTrue(settlement.is_settled())
            
            # Verify audit logging
            self.mock_audit_trail.log_event.assert_called()

    def test_list_settlements(self):
        """Test listing settlements with filters"""
        mock_response = [
            {
                "resource": "settlement",
                "id": "stl_1",
                "reference": "ref_1",
                "status": "paidout",
                "amount": {"value": "500.00", "currency": "EUR"}
            },
            {
                "resource": "settlement",
                "id": "stl_2",
                "reference": "ref_2",
                "status": "pending",
                "amount": {"value": "750.00", "currency": "EUR"}
            }
        ]
        
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            settlements = self.client.list_settlements(
                reference="ref_1",
                from_date=from_date,
                until_date=until_date
            )
            
            expected_params = {
                "limit": 250,
                "reference": "ref_1",
                "from": "2024-01-01",
                "until": "2024-01-31"
            }
            mock_get.assert_called_once_with("/settlements", params=expected_params, paginated=True)
            
            self.assertEqual(len(settlements), 2)
            self.assertIsInstance(settlements[0], Settlement)

    def test_get_next_settlement(self):
        """Test getting next scheduled settlement"""
        mock_response = {
            "resource": "settlement",
            "id": "stl_next",
            "status": "pending",
            "amount": {"value": "2000.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            settlement = self.client.get_next_settlement()
            
            mock_get.assert_called_once_with("/settlements/next")
            self.assertIsInstance(settlement, Settlement)
            self.assertEqual(settlement.id, "stl_next")

    def test_get_open_settlement(self):
        """Test getting open settlement"""
        mock_response = {
            "resource": "settlement",
            "id": "stl_open",
            "status": "open",
            "amount": {"value": "0.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            settlement = self.client.get_open_settlement()
            
            mock_get.assert_called_once_with("/settlements/open")
            self.assertIsInstance(settlement, Settlement)
            self.assertEqual(settlement.status, "open")

    def test_list_settlement_payments(self):
        """Test listing payments in a settlement"""
        settlement_id = "stl_test123"
        mock_response = [
            {
                "id": "tr_payment1",
                "amount": {"value": "100.00", "currency": "EUR"},
                "settlementAmount": {"value": "98.00", "currency": "EUR"}
            },
            {
                "id": "tr_payment2",
                "amount": {"value": "200.00", "currency": "EUR"},
                "settlementAmount": {"value": "196.00", "currency": "EUR"}
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            payments = self.client.list_settlement_payments(settlement_id)
            
            expected_params = {"limit": 250}
            mock_get.assert_called_once_with(
                f"/settlements/{settlement_id}/payments",
                params=expected_params,
                paginated=True
            )
            
            self.assertEqual(len(payments), 2)
            self.assertEqual(payments[0]["id"], "tr_payment1")

    def test_list_settlement_refunds(self):
        """Test listing refunds in a settlement"""
        settlement_id = "stl_test123"
        mock_response = [
            {
                "id": "re_refund1",
                "amount": {"value": "50.00", "currency": "EUR"},
                "settlementAmount": {"value": "-50.00", "currency": "EUR"}
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            refunds = self.client.list_settlement_refunds(settlement_id)
            
            mock_get.assert_called_once_with(
                f"/settlements/{settlement_id}/refunds",
                params={"limit": 250},
                paginated=True
            )
            
            self.assertEqual(len(refunds), 1)

    def test_list_settlement_chargebacks(self):
        """Test listing chargebacks in a settlement"""
        settlement_id = "stl_test123"
        mock_response = [
            {
                "id": "chb_1",
                "amount": {"value": "75.00", "currency": "EUR"},
                "settlementAmount": {"value": "-75.00", "currency": "EUR"}
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            chargebacks = self.client.list_settlement_chargebacks(settlement_id)
            
            mock_get.assert_called_once_with(
                f"/settlements/{settlement_id}/chargebacks",
                params={"limit": 250},
                paginated=True
            )
            
            self.assertEqual(len(chargebacks), 1)

    def test_reconcile_settlement(self):
        """Test settlement reconciliation"""
        settlement_id = "stl_test123"
        
        # Mock settlement
        mock_settlement = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": "ref_123",
            "status": "paidout",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "periods": {
                "2024-01": {
                    "revenue": [{"amountNet": {"value": "1100.00"}}],
                    "costs": [{"amountNet": {"value": "100.00"}}]
                }
            }
        }
        
        # Mock components
        mock_payments = [
            {"settlementAmount": {"value": "500.00"}},
            {"settlementAmount": {"value": "600.00"}}
        ]
        mock_refunds = [
            {"settlementAmount": {"value": "50.00"}}
        ]
        mock_chargebacks = [
            {"settlementAmount": {"value": "50.00"}}
        ]
        mock_captures = []
        
        with patch.object(self.client, 'get', side_effect=[
            mock_settlement,  # get_settlement
            mock_payments,    # list_settlement_payments
            mock_refunds,     # list_settlement_refunds
            mock_chargebacks, # list_settlement_chargebacks
            mock_captures     # list_settlement_captures
        ]):
            with patch('frappe.publish_realtime') as mock_publish:
                result = self.client.reconcile_settlement(settlement_id)
                
                # Verify reconciliation
                self.assertEqual(result["settlement_id"], settlement_id)
                self.assertEqual(result["calculated_total"], 1000.0)  # 1100 - 50 - 50
                self.assertEqual(result["actual_amount"], 1000.0)
                self.assertTrue(result["reconciled"])
                
                # No alert for reconciled settlement
                mock_publish.assert_not_called()

    def test_reconcile_settlement_with_discrepancy(self):
        """Test settlement reconciliation with discrepancy"""
        settlement_id = "stl_test123"
        
        mock_settlement = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": "ref_123",
            "status": "paidout",
            "amount": {"value": "900.00", "currency": "EUR"},  # Actual is 900
            "periods": {}
        }
        
        mock_payments = [{"settlementAmount": {"value": "1000.00"}}]  # Expected 1000
        mock_refunds = []
        mock_chargebacks = []
        mock_captures = []
        
        with patch.object(self.client, 'get', side_effect=[
            mock_settlement,
            mock_payments,
            mock_refunds,
            mock_chargebacks,
            mock_captures
        ]):
            with patch('frappe.publish_realtime') as mock_publish:
                result = self.client.reconcile_settlement(settlement_id)
                
                # Verify discrepancy detected
                self.assertFalse(result["reconciled"])
                self.assertEqual(result["discrepancy"], -100.0)
                
                # Verify alert sent
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "settlement_discrepancy")

    def test_get_settlement_summary(self):
        """Test getting settlement summary for a period"""
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        mock_settlements = [
            {
                "resource": "settlement",
                "id": "stl_1",
                "reference": "ref_1",
                "status": "paidout",
                "amount": {"value": "1000.00", "currency": "EUR"},
                "createdAt": "2024-01-15T10:00:00Z",
                "settledAt": "2024-01-16T10:00:00Z",
                "periods": {
                    "2024-01": {
                        "revenue": [{"amountNet": {"value": "1100.00"}}],
                        "costs": [{"amountNet": {"value": "100.00"}}]
                    }
                }
            },
            {
                "resource": "settlement",
                "id": "stl_2",
                "reference": "ref_2",
                "status": "pending",
                "amount": {"value": "500.00", "currency": "EUR"},
                "createdAt": "2024-01-20T10:00:00Z",
                "periods": {}
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_settlements):
            summary = self.client.get_settlement_summary(from_date, until_date)
            
            # Verify summary
            self.assertEqual(summary["total_settlements"], 2)
            self.assertEqual(summary["by_status"]["paidout"], 1)
            self.assertEqual(summary["by_status"]["pending"], 1)
            self.assertEqual(summary["total_amount"], 1500.0)
            self.assertEqual(len(summary["settlements"]), 2)

    def test_track_settlement_status(self):
        """Test tracking settlement status"""
        settlement_id = "stl_test123"
        
        # Test failed settlement
        mock_response = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": "ref_failed",
            "status": "failed",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "createdAt": "2024-01-15T10:00:00Z"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            with patch('frappe.publish_realtime') as mock_publish:
                status = self.client.track_settlement_status(settlement_id)
                
                # Verify failed status detected
                self.assertEqual(status["current_status"], "failed")
                self.assertTrue(status["is_failed"])
                self.assertEqual(status["alert"], "Settlement failed")
                self.assertEqual(status["alert_severity"], "high")
                
                # Verify alert sent
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "settlement_failed")

    def test_track_pending_settlement(self):
        """Test tracking long-pending settlement"""
        settlement_id = "stl_pending"
        
        # Create date 10 days ago
        created_date = (datetime.now() - timedelta(days=10)).isoformat()
        
        mock_response = {
            "resource": "settlement",
            "id": settlement_id,
            "status": "pending",
            "createdAt": created_date,
            "amount": {"value": "500.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            status = self.client.track_settlement_status(settlement_id)
            
            # Verify pending alert
            self.assertEqual(status["current_status"], "pending")
            self.assertEqual(status["days_pending"], 10)
            self.assertIn("pending for 10 days", status["alert"])
            self.assertEqual(status["alert_severity"], "medium")

    def test_export_settlement_report(self):
        """Test exporting settlement report"""
        settlement_id = "stl_test123"
        
        # Mock reconciliation data
        mock_reconciliation = {
            "settlement_id": settlement_id,
            "actual_amount": 1000.0,
            "calculated_total": 1000.0,
            "reconciled": True,
            "components": {
                "payments": {"count": 10, "total": 1100.0},
                "refunds": {"count": 2, "total": 100.0}
            }
        }
        
        mock_settlement = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": "ref_123",
            "status": "paidout",
            "createdAt": "2024-01-15T10:00:00Z",
            "settledAt": "2024-01-16T10:00:00Z",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "periods": {
                "2024-01": {
                    "revenue": [{"amountNet": {"value": "1100.00"}}],
                    "costs": [{"amountNet": {"value": "100.00"}}],
                    "invoiceId": "inv_123"
                }
            }
        }
        
        with patch.object(self.client, 'reconcile_settlement', return_value=mock_reconciliation):
            with patch.object(self.client, 'get_settlement') as mock_get:
                mock_get.return_value = Settlement(mock_settlement)
                
                report = self.client.export_settlement_report(settlement_id)
                
                # Verify report structure
                self.assertIn("settlement", report)
                self.assertIn("reconciliation", report)
                self.assertIn("periods", report)
                self.assertIn("generated_at", report)
                
                # Verify audit logging
                audit_calls = self.mock_audit_trail.log_event.call_args_list
                report_logged = any(
                    "report" in str(call).lower() 
                    for call in audit_calls
                )
                self.assertTrue(report_logged)

    def test_settlement_period_calculations(self):
        """Test settlement period revenue/cost calculations"""
        mock_response = {
            "resource": "settlement",
            "id": "stl_test",
            "periods": {
                "2024-01": {
                    "revenue": [
                        {"amountNet": {"value": "500.00"}},
                        {"amountNet": {"value": "600.00"}}
                    ],
                    "costs": [
                        {"amountNet": {"value": "50.00"}},
                        {"amountNet": {"value": "60.00"}}
                    ]
                }
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            settlement = self.client.get_settlement("stl_test")
            
            # Verify period calculations
            total_revenue = settlement.get_total_revenue()
            total_costs = settlement.get_total_costs()
            
            self.assertEqual(total_revenue, Decimal("1100.00"))
            self.assertEqual(total_costs, Decimal("110.00"))


if __name__ == "__main__":
    unittest.main()