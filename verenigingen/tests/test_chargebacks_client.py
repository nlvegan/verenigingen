"""
Integration tests for Mollie Chargebacks API Client
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.chargebacks_client import ChargebacksClient
from verenigingen.verenigingen_payments.core.models.chargeback import Chargeback, ChargebackReason


class TestChargebacksClient(FrappeTestCase):
    """Test suite for Chargebacks API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        
        # Create client instance
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'):
            self.client = ChargebacksClient("test_settings")
            self.client.audit_trail = self.mock_audit_trail
            self.client.settings = self.mock_settings

    def test_get_chargeback(self):
        """Test retrieving a specific chargeback"""
        payment_id = "tr_payment123"
        chargeback_id = "chb_test123"
        
        mock_response = {
            "resource": "chargeback",
            "id": chargeback_id,
            "amount": {"value": "100.00", "currency": "EUR"},
            "settlementAmount": {"value": "-105.00", "currency": "EUR"},
            "createdAt": "2024-01-15T10:00:00+00:00",
            "reversedAt": None,
            "paymentId": payment_id,
            "reason": {
                "code": "fraudulent",
                "description": "The customer claims the payment was fraudulent"
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            chargeback = self.client.get_chargeback(payment_id, chargeback_id)
            
            # Verify API call
            mock_get.assert_called_once_with(f"/payments/{payment_id}/chargebacks/{chargeback_id}")
            
            # Verify response
            self.assertIsInstance(chargeback, Chargeback)
            self.assertEqual(chargeback.id, chargeback_id)
            self.assertEqual(chargeback.payment_id, payment_id)
            self.assertEqual(chargeback.amount.decimal_value, Decimal("100.00"))
            self.assertEqual(chargeback.settlement_amount.decimal_value, Decimal("-105.00"))
            self.assertFalse(chargeback.is_reversed())
            
            # Verify audit logging with warning severity
            audit_calls = self.mock_audit_trail.log_event.call_args_list
            self.assertTrue(any(
                call[0][1].value == "WARNING" 
                for call in audit_calls
            ))

    def test_list_payment_chargebacks(self):
        """Test listing all chargebacks for a payment"""
        payment_id = "tr_payment123"
        
        mock_response = [
            {
                "resource": "chargeback",
                "id": "chb_1",
                "amount": {"value": "50.00", "currency": "EUR"},
                "paymentId": payment_id
            },
            {
                "resource": "chargeback",
                "id": "chb_2",
                "amount": {"value": "75.00", "currency": "EUR"},
                "paymentId": payment_id
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            chargebacks = self.client.list_payment_chargebacks(payment_id)
            
            mock_get.assert_called_once_with(
                f"/payments/{payment_id}/chargebacks",
                paginated=True
            )
            
            self.assertEqual(len(chargebacks), 2)
            self.assertIsInstance(chargebacks[0], Chargeback)
            self.assertEqual(chargebacks[0].id, "chb_1")

    def test_list_all_chargebacks(self):
        """Test listing all chargebacks with date filters"""
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        mock_response = [
            {
                "resource": "chargeback",
                "id": "chb_all_1",
                "amount": {"value": "100.00", "currency": "EUR"},
                "createdAt": "2024-01-10T10:00:00Z"
            },
            {
                "resource": "chargeback",
                "id": "chb_all_2",
                "amount": {"value": "200.00", "currency": "EUR"},
                "createdAt": "2024-01-20T10:00:00Z"
            }
        ]
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            chargebacks = self.client.list_all_chargebacks(
                from_date=from_date,
                until_date=until_date
            )
            
            expected_params = {
                "limit": 250,
                "from": "2024-01-01",
                "until": "2024-01-31"
            }
            mock_get.assert_called_once_with(
                "/chargebacks",
                params=expected_params,
                paginated=True
            )
            
            self.assertEqual(len(chargebacks), 2)

    def test_analyze_chargeback_trends(self):
        """Test chargeback trend analysis"""
        mock_chargebacks = [
            Chargeback({
                "resource": "chargeback",
                "id": "chb_1",
                "amount": {"value": "100.00", "currency": "EUR"},
                "settlementAmount": {"value": "-105.00", "currency": "EUR"},
                "createdAt": datetime.now().isoformat(),
                "reason": {"code": "fraudulent"},
                "reversedAt": None
            }),
            Chargeback({
                "resource": "chargeback",
                "id": "chb_2",
                "amount": {"value": "200.00", "currency": "EUR"},
                "settlementAmount": {"value": "-210.00", "currency": "EUR"},
                "createdAt": (datetime.now() - timedelta(days=5)).isoformat(),
                "reason": {"code": "unrecognized"},
                "reversedAt": None
            }),
            Chargeback({
                "resource": "chargeback",
                "id": "chb_3",
                "amount": {"value": "50.00", "currency": "EUR"},
                "settlementAmount": {"value": "-52.50", "currency": "EUR"},
                "createdAt": (datetime.now() - timedelta(days=10)).isoformat(),
                "reason": {"code": "fraudulent"},
                "reversedAt": "2024-01-20T10:00:00Z"  # Reversed
            })
        ]
        
        with patch.object(self.client, 'list_all_chargebacks', return_value=mock_chargebacks):
            with patch('frappe.publish_realtime') as mock_publish:
                analysis = self.client.analyze_chargeback_trends(period_days=30)
                
                # Verify analysis results
                self.assertEqual(analysis["total_chargebacks"], 3)
                self.assertEqual(analysis["total_amount"], 350.0)
                self.assertEqual(analysis["by_status"]["reversed"], 1)
                self.assertEqual(analysis["by_status"]["active"], 2)
                
                # Verify reason grouping
                self.assertIn("fraudulent", analysis["by_reason"])
                self.assertIn("unrecognized", analysis["by_reason"])
                self.assertEqual(analysis["by_reason"]["fraudulent"]["count"], 2)
                self.assertEqual(analysis["by_reason"]["unrecognized"]["count"], 1)
                
                # Check if high fraud rate alert triggered
                if len(analysis["high_risk_indicators"]) > 0:
                    mock_publish.assert_called()

    def test_high_risk_chargeback_detection(self):
        """Test detection of high-risk chargeback patterns"""
        # Create many fraud chargebacks to trigger high-risk alert
        mock_chargebacks = [
            Chargeback({
                "resource": "chargeback",
                "id": f"chb_fraud_{i}",
                "amount": {"value": "100.00", "currency": "EUR"},
                "settlementAmount": {"value": "-105.00", "currency": "EUR"},
                "createdAt": (datetime.now() - timedelta(days=i)).isoformat(),
                "reason": {"code": ChargebackReason.FRAUDULENT.value},
                "reversedAt": None
            })
            for i in range(10)  # 10 fraud chargebacks
        ]
        
        with patch.object(self.client, 'list_all_chargebacks', return_value=mock_chargebacks):
            with patch('frappe.publish_realtime') as mock_publish:
                analysis = self.client.analyze_chargeback_trends(period_days=30)
                
                # Should detect high fraud rate (100% fraud)
                self.assertIn("High fraud rate", analysis["high_risk_indicators"])
                
                # Should send alert
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "chargeback_alert")
                self.assertIn("High chargeback risk detected", call_args[0][1]["message"])

    def test_calculate_financial_impact(self):
        """Test calculating financial impact of chargebacks"""
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        mock_chargebacks = [
            Chargeback({
                "resource": "chargeback",
                "id": "chb_1",
                "paymentId": "tr_1",
                "amount": {"value": "100.00", "currency": "EUR"},
                "settlementAmount": {"value": "-110.00", "currency": "EUR"},  # Includes 10 fee
                "reason": {"code": "fraudulent"},
                "reversedAt": None
            }),
            Chargeback({
                "resource": "chargeback",
                "id": "chb_2",
                "paymentId": "tr_2",
                "amount": {"value": "200.00", "currency": "EUR"},
                "settlementAmount": {"value": "-215.00", "currency": "EUR"},  # Includes 15 fee
                "reason": {"code": "unrecognized"},
                "reversedAt": "2024-01-20T10:00:00Z"  # Reversed
            })
        ]
        
        with patch.object(self.client, 'list_all_chargebacks', return_value=mock_chargebacks):
            impact = self.client.calculate_financial_impact(from_date, until_date)
            
            # Verify financial calculations
            self.assertEqual(impact["chargeback_count"], 2)
            self.assertEqual(impact["direct_loss"], 300.0)  # 100 + 200
            self.assertEqual(impact["fees_and_penalties"], 25.0)  # 10 + 15
            self.assertEqual(impact["total_impact"], 335.0)  # Total including fees
            self.assertEqual(impact["reversed_amount"], 200.0)  # One reversed
            self.assertEqual(impact["net_loss"], 135.0)  # Total impact - reversed
            
            # Verify individual chargeback tracking
            self.assertEqual(len(impact["chargebacks"]), 2)
            self.assertTrue(impact["chargebacks"][1]["reversed"])

    def test_get_chargeback_prevention_insights(self):
        """Test getting chargeback prevention insights"""
        mock_analysis = {
            "average_per_day": 0.3,
            "total_chargebacks": 9,
            "total_impact": 1000.0,
            "by_reason": {
                ChargebackReason.FRAUDULENT.value: {
                    "count": 5,
                    "amount": 500.0,
                    "description": "Fraudulent transaction"
                },
                ChargebackReason.UNRECOGNIZED.value: {
                    "count": 3,
                    "amount": 300.0,
                    "description": "Customer doesn't recognize"
                },
                ChargebackReason.DUPLICATE.value: {
                    "count": 1,
                    "amount": 200.0,
                    "description": "Duplicate charge"
                }
            }
        }
        
        with patch.object(self.client, 'analyze_chargeback_trends', return_value=mock_analysis):
            insights = self.client.get_chargeback_prevention_insights()
            
            # Verify risk level assessment
            self.assertEqual(insights["risk_level"], "medium")  # 0.3 per day
            
            # Verify top reasons
            self.assertEqual(len(insights["top_reasons"]), 3)
            self.assertEqual(insights["top_reasons"][0]["reason"], ChargebackReason.FRAUDULENT.value)
            self.assertEqual(insights["top_reasons"][0]["count"], 5)
            
            # Verify recommendations
            self.assertTrue(any(
                "fraud detection" in rec["action"].lower()
                for rec in insights["recommendations"]
            ))
            self.assertTrue(any(
                "transaction descriptors" in rec["action"].lower()
                for rec in insights["recommendations"]
            ))

    def test_handle_new_chargeback(self):
        """Test handling new chargeback notification"""
        payment_id = "tr_payment123"
        chargeback_id = "chb_new"
        
        mock_chargeback = {
            "resource": "chargeback",
            "id": chargeback_id,
            "paymentId": payment_id,
            "amount": {"value": "150.00", "currency": "EUR"},
            "createdAt": datetime.now().isoformat(),
            "reason": {
                "code": "fraudulent",
                "description": "Customer claims fraud"
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_chargeback):
            with patch('frappe.publish_realtime') as mock_publish:
                result = self.client.handle_new_chargeback(payment_id, chargeback_id)
                
                # Verify handling result
                self.assertEqual(result["chargeback_id"], chargeback_id)
                self.assertEqual(result["payment_id"], payment_id)
                self.assertEqual(result["amount"], 150.0)
                self.assertEqual(result["reason"], "fraudulent")
                self.assertIn("Logged in audit trail", result["actions_taken"])
                self.assertIn("Notification sent", result["actions_taken"])
                
                # Verify realtime notification
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "new_chargeback")
                self.assertIn(payment_id, call_args[0][1]["message"])

    def test_chargeback_reason_mapping(self):
        """Test proper mapping of chargeback reasons"""
        reasons = [
            ("fraudulent", ChargebackReason.FRAUDULENT),
            ("unrecognized", ChargebackReason.UNRECOGNIZED),
            ("duplicate", ChargebackReason.DUPLICATE),
            ("subscription_canceled", ChargebackReason.SUBSCRIPTION_CANCELED),
            ("product_not_received", ChargebackReason.PRODUCT_NOT_RECEIVED),
            ("product_unacceptable", ChargebackReason.PRODUCT_UNACCEPTABLE),
            ("credit_not_processed", ChargebackReason.CREDIT_NOT_PROCESSED),
            ("general", ChargebackReason.GENERAL),
            ("unknown_code", None)  # Unknown reason
        ]
        
        for code, expected_enum in reasons:
            mock_chargeback = Chargeback({
                "resource": "chargeback",
                "id": f"chb_{code}",
                "reason": {"code": code}
            })
            
            reason_code = mock_chargeback.get_reason_code()
            if expected_enum:
                self.assertEqual(reason_code, expected_enum.value)
            else:
                self.assertEqual(reason_code, code)  # Returns raw code if unknown

    def test_empty_chargeback_list(self):
        """Test handling empty chargeback list"""
        with patch.object(self.client, 'list_all_chargebacks', return_value=[]):
            # Test trend analysis with no chargebacks
            analysis = self.client.analyze_chargeback_trends()
            self.assertEqual(analysis["total_chargebacks"], 0)
            self.assertEqual(analysis["total_amount"], 0.0)
            self.assertEqual(analysis["average_per_day"], 0)
            self.assertEqual(len(analysis["high_risk_indicators"]), 0)
            
            # Test financial impact with no chargebacks
            impact = self.client.calculate_financial_impact(
                datetime.now() - timedelta(days=30),
                datetime.now()
            )
            self.assertEqual(impact["chargeback_count"], 0)
            self.assertEqual(impact["net_loss"], 0.0)

    def test_chargeback_month_grouping(self):
        """Test chargebacks grouped by month"""
        mock_chargebacks = [
            Chargeback({
                "resource": "chargeback",
                "id": "chb_jan_1",
                "amount": {"value": "100.00", "currency": "EUR"},
                "createdAt": "2024-01-15T10:00:00Z"
            }),
            Chargeback({
                "resource": "chargeback",
                "id": "chb_jan_2",
                "amount": {"value": "150.00", "currency": "EUR"},
                "createdAt": "2024-01-20T10:00:00Z"
            }),
            Chargeback({
                "resource": "chargeback",
                "id": "chb_feb_1",
                "amount": {"value": "200.00", "currency": "EUR"},
                "createdAt": "2024-02-10T10:00:00Z"
            })
        ]
        
        with patch.object(self.client, 'list_all_chargebacks', return_value=mock_chargebacks):
            analysis = self.client.analyze_chargeback_trends(period_days=60)
            
            # Verify month grouping
            self.assertIn("2024-01", analysis["by_month"])
            self.assertIn("2024-02", analysis["by_month"])
            self.assertEqual(analysis["by_month"]["2024-01"]["count"], 2)
            self.assertEqual(analysis["by_month"]["2024-01"]["amount"], 250.0)
            self.assertEqual(analysis["by_month"]["2024-02"]["count"], 1)
            self.assertEqual(analysis["by_month"]["2024-02"]["amount"], 200.0)

    def test_risk_level_calculation(self):
        """Test different risk level calculations"""
        test_cases = [
            (0.1, "low"),      # Low risk
            (0.3, "medium"),   # Medium risk
            (0.6, "high"),     # High risk
        ]
        
        for avg_per_day, expected_risk in test_cases:
            mock_analysis = {
                "average_per_day": avg_per_day,
                "total_chargebacks": int(avg_per_day * 30),
                "total_impact": 1000.0,
                "by_reason": {}
            }
            
            with patch.object(self.client, 'analyze_chargeback_trends', return_value=mock_analysis):
                insights = self.client.get_chargeback_prevention_insights()
                self.assertEqual(insights["risk_level"], expected_risk)


if __name__ == "__main__":
    unittest.main()