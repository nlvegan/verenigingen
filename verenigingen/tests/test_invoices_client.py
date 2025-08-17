"""
Integration tests for Mollie Invoices API Client
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.invoices_client import InvoicesClient
from verenigingen.verenigingen_payments.core.models.invoice import Invoice, InvoiceStatus


class TestInvoicesClient(FrappeTestCase):
    """Test suite for Invoices API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        
        # Create client instance
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'):
            self.client = InvoicesClient("test_settings")
            self.client.audit_trail = self.mock_audit_trail
            self.client.settings = self.mock_settings

    def test_get_invoice(self):
        """Test retrieving a specific invoice"""
        invoice_id = "inv_test123"
        mock_response = {
            "resource": "invoice",
            "id": invoice_id,
            "reference": "2024-001",
            "vatNumber": "NL123456789B01",
            "status": "paid",
            "issuedAt": "2024-01-15T10:00:00+00:00",
            "paidAt": "2024-01-20T10:00:00+00:00",
            "dueAt": "2024-01-30T10:00:00+00:00",
            "netAmount": {"value": "100.00", "currency": "EUR"},
            "vatAmount": {"value": "21.00", "currency": "EUR"},
            "grossAmount": {"value": "121.00", "currency": "EUR"},
            "lines": [
                {
                    "period": "2024-01",
                    "description": "Transaction costs",
                    "count": 10,
                    "vatPercentage": 21.0,
                    "amount": {"value": "10.00", "currency": "EUR"}
                }
            ]
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            invoice = self.client.get_invoice(invoice_id)
            
            # Verify API call
            mock_get.assert_called_once_with(f"/invoices/{invoice_id}")
            
            # Verify response
            self.assertIsInstance(invoice, Invoice)
            self.assertEqual(invoice.id, invoice_id)
            self.assertEqual(invoice.reference, "2024-001")
            self.assertEqual(invoice.status, "paid")
            self.assertTrue(invoice.is_paid())
            self.assertFalse(invoice.is_overdue())
            
            # Verify amounts
            self.assertEqual(invoice.net_amount.decimal_value, Decimal("100.00"))
            self.assertEqual(invoice.vat_amount.decimal_value, Decimal("21.00"))
            self.assertEqual(invoice.gross_amount.decimal_value, Decimal("121.00"))
            
            # Verify audit logging
            self.mock_audit_trail.log_event.assert_called()

    def test_list_invoices(self):
        """Test listing invoices with filters"""
        mock_response = [
            {
                "resource": "invoice",
                "id": "inv_1",
                "reference": "2024-001",
                "status": "paid",
                "grossAmount": {"value": "121.00", "currency": "EUR"}
            },
            {
                "resource": "invoice",
                "id": "inv_2",
                "reference": "2024-002",
                "status": "open",
                "grossAmount": {"value": "242.00", "currency": "EUR"}
            }
        ]
        
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            invoices = self.client.list_invoices(
                reference="2024",
                year=2024,
                from_date=from_date,
                until_date=until_date
            )
            
            expected_params = {
                "limit": 250,
                "reference": "2024",
                "year": 2024,
                "from": "2024-01-01",
                "until": "2024-01-31"
            }
            mock_get.assert_called_once_with("/invoices", params=expected_params, paginated=True)
            
            self.assertEqual(len(invoices), 2)
            self.assertIsInstance(invoices[0], Invoice)

    def test_get_overdue_invoices(self):
        """Test getting overdue invoices"""
        past_due_date = (datetime.now() - timedelta(days=10)).isoformat()
        future_due_date = (datetime.now() + timedelta(days=10)).isoformat()
        
        mock_response = [
            {
                "resource": "invoice",
                "id": "inv_overdue",
                "status": "open",
                "dueAt": past_due_date,
                "grossAmount": {"value": "100.00", "currency": "EUR"}
            },
            {
                "resource": "invoice",
                "id": "inv_current",
                "status": "open",
                "dueAt": future_due_date,
                "grossAmount": {"value": "200.00", "currency": "EUR"}
            },
            {
                "resource": "invoice",
                "id": "inv_paid",
                "status": "paid",
                "dueAt": past_due_date,
                "grossAmount": {"value": "150.00", "currency": "EUR"}
            }
        ]
        
        with patch.object(self.client, 'list_invoices', return_value=[Invoice(inv) for inv in mock_response]):
            overdue = self.client.get_overdue_invoices()
            
            # Only open invoice with past due date should be overdue
            self.assertEqual(len(overdue), 1)
            self.assertEqual(overdue[0].id, "inv_overdue")
            
            # Verify warning logged for overdue invoices
            audit_calls = self.mock_audit_trail.log_event.call_args_list
            warning_logged = any(
                call[0][1].value == "WARNING" 
                for call in audit_calls
            )
            self.assertTrue(warning_logged)

    def test_calculate_vat_summary(self):
        """Test VAT summary calculation"""
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        mock_invoices = [
            Invoice({
                "resource": "invoice",
                "status": "paid",
                "netAmount": {"value": "100.00", "currency": "EUR"},
                "vatAmount": {"value": "21.00", "currency": "EUR"},
                "grossAmount": {"value": "121.00", "currency": "EUR"}
            }),
            Invoice({
                "resource": "invoice",
                "status": "open",
                "dueAt": (datetime.now() - timedelta(days=5)).isoformat(),
                "netAmount": {"value": "200.00", "currency": "EUR"},
                "vatAmount": {"value": "18.00", "currency": "EUR"},
                "grossAmount": {"value": "218.00", "currency": "EUR"}
            })
        ]
        
        with patch.object(self.client, 'list_invoices', return_value=mock_invoices):
            summary = self.client.calculate_vat_summary(from_date, until_date)
            
            # Verify summary totals
            self.assertEqual(summary["total_invoices"], 2)
            self.assertEqual(summary["total_net"], 300.0)
            self.assertEqual(summary["total_vat"], 39.0)
            self.assertEqual(summary["total_gross"], 339.0)
            
            # Verify status counts
            self.assertEqual(summary["by_status"]["paid"], 1)
            self.assertEqual(summary["by_status"]["overdue"], 1)
            self.assertEqual(summary["by_status"]["open"], 0)
            
            # Verify VAT rate grouping
            self.assertIn("21.0%", summary["by_rate"])
            self.assertIn("9.0%", summary["by_rate"])  # 18/200 = 9%

    def test_reconcile_invoice_with_settlements(self):
        """Test invoice reconciliation with settlements"""
        invoice_id = "inv_test123"
        
        mock_invoice = {
            "resource": "invoice",
            "id": invoice_id,
            "reference": "2024-001",
            "status": "paid",
            "grossAmount": {"value": "121.00", "currency": "EUR"},
            "settlements": ["stl_1", "stl_2"]
        }
        
        with patch.object(self.client, 'get', return_value=mock_invoice):
            result = self.client.reconcile_invoice_with_settlements(invoice_id)
            
            # Verify reconciliation structure
            self.assertEqual(result["invoice_id"], invoice_id)
            self.assertEqual(result["reference"], "2024-001")
            self.assertEqual(result["gross_amount"], 121.0)
            self.assertEqual(len(result["settlements"]), 2)
            self.assertTrue(result["reconciled"])

    def test_track_payment_status(self):
        """Test tracking invoice payment status"""
        invoice_id = "inv_test123"
        due_date = (datetime.now() - timedelta(days=5)).isoformat()
        
        mock_invoice = {
            "resource": "invoice",
            "id": invoice_id,
            "reference": "2024-001",
            "status": "open",
            "issuedAt": "2024-01-01T10:00:00Z",
            "dueAt": due_date,
            "netAmount": {"value": "100.00", "currency": "EUR"},
            "vatAmount": {"value": "21.00", "currency": "EUR"},
            "grossAmount": {"value": "121.00", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_invoice):
            with patch('frappe.publish_realtime') as mock_publish:
                status = self.client.track_payment_status(invoice_id)
                
                # Verify status tracking
                self.assertEqual(status["invoice_id"], invoice_id)
                self.assertEqual(status["status"], "open")
                self.assertFalse(status["is_paid"])
                self.assertTrue(status["is_overdue"])
                self.assertEqual(status["days_overdue"], 5)
                
                # Verify overdue alert sent
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                self.assertEqual(call_args[0][0], "invoice_overdue")
                self.assertIn("days_overdue", call_args[0][1])

    def test_export_invoices_for_accounting(self):
        """Test exporting invoices for accounting systems"""
        from_date = datetime(2024, 1, 1)
        until_date = datetime(2024, 1, 31)
        
        mock_invoices = [
            Invoice({
                "resource": "invoice",
                "reference": "2024-001",
                "issuedAt": "2024-01-15T10:00:00Z",
                "dueAt": "2024-01-30T10:00:00Z",
                "paidAt": "2024-01-20T10:00:00Z",
                "status": "paid",
                "vatNumber": "NL123456789B01",
                "netAmount": {"value": "100.00", "currency": "EUR"},
                "vatAmount": {"value": "21.00", "currency": "EUR"},
                "grossAmount": {"value": "121.00", "currency": "EUR"},
                "lines": [
                    {
                        "description": "Transaction fees",
                        "period": "2024-01",
                        "count": 10,
                        "vatPercentage": 21.0,
                        "amount": {"value": "10.00", "currency": "EUR"}
                    }
                ]
            })
        ]
        
        with patch.object(self.client, 'list_invoices', return_value=mock_invoices):
            export_data = self.client.export_invoices_for_accounting(from_date, until_date)
            
            # Verify export structure
            self.assertEqual(len(export_data), 1)
            invoice_data = export_data[0]
            
            self.assertEqual(invoice_data["invoice_number"], "2024-001")
            self.assertEqual(invoice_data["status"], "paid")
            self.assertEqual(invoice_data["net_amount"], 100.0)
            self.assertEqual(invoice_data["vat_amount"], 21.0)
            self.assertEqual(invoice_data["gross_amount"], 121.0)
            self.assertEqual(invoice_data["vat_rate"], 21.0)
            
            # Verify line items
            self.assertEqual(len(invoice_data["lines"]), 1)
            line = invoice_data["lines"][0]
            self.assertEqual(line["description"], "Transaction fees")
            self.assertEqual(line["quantity"], 10)
            
            # Verify audit logging
            audit_calls = self.mock_audit_trail.log_event.call_args_list
            export_logged = any(
                "export" in str(call).lower() 
                for call in audit_calls
            )
            self.assertTrue(export_logged)

    def test_invoice_vat_rate_calculation(self):
        """Test VAT rate calculation from invoice amounts"""
        mock_invoice = Invoice({
            "resource": "invoice",
            "netAmount": {"value": "100.00", "currency": "EUR"},
            "vatAmount": {"value": "21.00", "currency": "EUR"},
            "grossAmount": {"value": "121.00", "currency": "EUR"}
        })
        
        vat_rate = mock_invoice.get_vat_rate()
        self.assertEqual(vat_rate, 21.0)

    def test_invoice_with_multiple_vat_rates(self):
        """Test handling invoices with multiple VAT rates"""
        mock_response = {
            "resource": "invoice",
            "id": "inv_multi_vat",
            "lines": [
                {
                    "description": "High VAT items",
                    "vatPercentage": 21.0,
                    "amount": {"value": "100.00", "currency": "EUR"}
                },
                {
                    "description": "Low VAT items",
                    "vatPercentage": 9.0,
                    "amount": {"value": "50.00", "currency": "EUR"}
                },
                {
                    "description": "Zero VAT items",
                    "vatPercentage": 0.0,
                    "amount": {"value": "25.00", "currency": "EUR"}
                }
            ],
            "netAmount": {"value": "175.00", "currency": "EUR"},
            "vatAmount": {"value": "25.50", "currency": "EUR"},
            "grossAmount": {"value": "200.50", "currency": "EUR"}
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            invoice = self.client.get_invoice("inv_multi_vat")
            
            # Verify invoice has multiple line items with different VAT rates
            self.assertEqual(len(invoice.lines), 3)
            vat_rates = [line.vat_percentage for line in invoice.lines]
            self.assertIn(21.0, vat_rates)
            self.assertIn(9.0, vat_rates)
            self.assertIn(0.0, vat_rates)

    def test_empty_invoice_list(self):
        """Test handling empty invoice list"""
        with patch.object(self.client, 'get', return_value=[]):
            invoices = self.client.list_invoices()
            self.assertEqual(len(invoices), 0)
            
            # Test overdue with no invoices
            overdue = self.client.get_overdue_invoices()
            self.assertEqual(len(overdue), 0)

    def test_invoice_date_parsing(self):
        """Test proper date parsing in invoices"""
        mock_response = {
            "resource": "invoice",
            "id": "inv_dates",
            "issuedAt": "2024-01-15T10:30:45+00:00",
            "dueAt": "2024-01-30T23:59:59+00:00",
            "paidAt": "2024-01-20T14:22:33+00:00"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            invoice = self.client.get_invoice("inv_dates")
            
            # Verify dates are properly stored
            self.assertEqual(invoice.issued_at, "2024-01-15T10:30:45+00:00")
            self.assertEqual(invoice.due_at, "2024-01-30T23:59:59+00:00")
            self.assertEqual(invoice.paid_at, "2024-01-20T14:22:33+00:00")


if __name__ == "__main__":
    unittest.main()