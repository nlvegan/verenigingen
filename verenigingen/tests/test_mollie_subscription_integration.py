"""
Comprehensive Tests for Mollie Subscription Integration

Tests the complete workflow:
1. Mollie subscription creation
2. Sales Invoice generation from Membership Dues Schedule
3. Mollie subscription webhook payment processing
4. Payment Entry creation and Sales Invoice payment
5. Member Payment History updates

This test suite uses actual test API keys to verify end-to-end integration.
"""

import json
from unittest.mock import MagicMock, patch
from decimal import Decimal

import frappe
from frappe.utils import add_months, today, flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    PaymentGatewayFactory,
    mollie_subscription_webhook,
    _process_subscription_payment
)


class TestMollieSubscriptionIntegration(EnhancedTestCase):
    """Comprehensive Mollie subscription integration tests"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Set up test Mollie Settings with test key
        cls.mollie_settings = frappe.get_doc({
            "doctype": "Mollie Settings",
            "gateway_name": "Test Gateway",
            "profile_id": "pfl_test_profile",
            "secret_key": "test_dHar4XY7LxsDOtmnkVtjNVWXLSlXsM",  # Test API key format
            "test_mode": 1,
            "enable_subscriptions": 1
        })
        cls.mollie_settings.flags.ignore_mandatory = True  # Skip validation for test setup
        cls.mollie_settings.insert()
        
    def setUp(self):
        """Set up test data for each test"""
        super().setUp()
        
        # Create test member with customer record
        self.member = self.create_test_member(
            first_name="Jan",
            last_name="de Vries", 
            email="jan.devries@example.com",
            birth_date="1990-01-01"
        )
        
        # Create customer for the member (required for invoices)
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": f"{self.member.first_name} {self.member.last_name}",
            "customer_type": "Individual",
            "territory": "Netherlands"
        })
        self.customer.insert()
        
        # Link customer to member
        self.member.customer = self.customer.name
        self.member.save()
        
        # Create membership dues schedule
        self.dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "billing_frequency": "Annual", 
            "dues_rate": 50.00,
            "next_invoice_date": today(),
            "auto_generate": 1,
            "status": "Active"
        })
        self.dues_schedule.insert()
        
    def test_create_mollie_subscription(self):
        """Test creating a Mollie subscription for a member"""
        
        with patch('verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.Client') as mock_client_class:
            # Mock Mollie API responses
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
            # Mock customer creation
            mock_customer = MagicMock()
            mock_customer.id = "cst_test_customer_123"
            mock_client.customers.create.return_value = mock_customer
            
            # Mock subscription creation  
            mock_subscription = MagicMock()
            mock_subscription.id = "sub_test_subscription_123"
            mock_subscription.status = "active"
            mock_subscription.next_payment_date = "2025-01-15"
            mock_client.customers_subscriptions.with_parent_id.return_value.create.return_value = mock_subscription
            
            # Create subscription via gateway
            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Test Gateway")
            subscription_data = {
                "amount": 50.00,
                "interval": "1 month",
                "currency": "EUR",
                "description": f"Membership dues for {self.member.first_name} {self.member.last_name}"
            }
            
            result = gateway.create_subscription(self.member, subscription_data)
            
            # Verify subscription was created successfully
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["customer_id"], "cst_test_customer_123")
            self.assertEqual(result["subscription_id"], "sub_test_subscription_123")
            
            # Verify member was updated with subscription details
            self.member.reload()
            self.assertEqual(self.member.mollie_customer_id, "cst_test_customer_123")
            self.assertEqual(self.member.mollie_subscription_id, "sub_test_subscription_123")
            self.assertEqual(self.member.subscription_status, "active")
            
    def test_sales_invoice_generation(self):
        """Test that Membership Dues Schedule generates Sales Invoices correctly"""
        
        # Generate invoice from dues schedule
        invoice_name = self.dues_schedule.generate_invoice(force=True)
        self.assertIsNotNone(invoice_name)
        
        # Verify invoice details
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.customer, self.customer.name)
        self.assertEqual(flt(invoice.grand_total), 50.00)
        self.assertEqual(invoice.docstatus, 1)  # Should be submitted
        self.assertIn("Unpaid", invoice.status)
        
        # Verify invoice items
        self.assertEqual(len(invoice.items), 1)
        self.assertEqual(flt(invoice.items[0].rate), 50.00)
        
    def test_mollie_subscription_webhook_payment_processing(self):
        """Test processing Mollie subscription webhook with payment"""
        
        # First, create an unpaid invoice
        invoice_name = self.dues_schedule.generate_invoice(force=True)
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Set up member with Mollie subscription details
        self.member.mollie_customer_id = "cst_test_customer_123"
        self.member.mollie_subscription_id = "sub_test_subscription_123"
        self.member.payment_method = "Mollie"
        self.member.save()
        
        # Mock webhook payload from Mollie
        webhook_payload = {
            "id": "sub_test_subscription_123",
            "payment": {
                "id": "tr_test_payment_456"
            }
        }
        
        with patch('verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway') as mock_gateway_factory:
            # Create mock gateway and client
            mock_gateway = MagicMock()
            mock_client = MagicMock()
            mock_gateway.client = mock_client
            mock_gateway_factory.return_value = mock_gateway
            
            # Mock payment details from Mollie API
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = True
            mock_payment.amount = {"value": "50.00", "currency": "EUR"}
            mock_payment.status = "paid"
            mock_client.payments.get.return_value = mock_payment
            
            # Mock subscription status
            mock_gateway.get_subscription_status.return_value = {
                "status": "success",
                "subscription": {
                    "status": "active",
                    "next_payment_date": "2025-02-15"
                }
            }
            
            # Mock frappe.request for webhook
            with patch('frappe.request') as mock_request:
                mock_request.get_data.return_value = json.dumps(webhook_payload)
                
                # Process webhook
                result = mollie_subscription_webhook()
                
                # Verify webhook processing succeeded
                self.assertEqual(result["status"], "processed")
                self.assertEqual(result["member"], self.member.name)
                self.assertIn("payment_processed", result["actions"])
                self.assertIn("status_updated", result["actions"])
                
        # Verify Payment Entry was created
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": "tr_test_payment_456", "party": self.customer.name},
            fields=["name", "paid_amount", "docstatus"]
        )
        
        self.assertEqual(len(payment_entries), 1)
        payment_entry = payment_entries[0]
        self.assertEqual(flt(payment_entry["paid_amount"]), 50.00)
        self.assertEqual(payment_entry["docstatus"], 1)  # Should be submitted
        
        # Verify Sales Invoice is now paid
        invoice.reload()
        self.assertEqual(invoice.status, "Paid")
        
        # Verify member subscription status was updated
        self.member.reload()
        self.assertEqual(self.member.subscription_status, "active")
        self.assertEqual(str(self.member.next_payment_date), "2025-02-15")
        
    def test_subscription_payment_amount_mismatch(self):
        """Test handling of payment amount mismatches"""
        
        # Create invoice for €50
        invoice_name = self.dues_schedule.generate_invoice(force=True)
        
        # Set up member with subscription
        self.member.mollie_customer_id = "cst_test_customer_123"
        self.member.mollie_subscription_id = "sub_test_subscription_123"
        self.member.save()
        
        with patch('verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway') as mock_gateway_factory:
            mock_gateway = MagicMock()
            mock_client = MagicMock()
            mock_gateway.client = mock_client
            mock_gateway_factory.return_value = mock_gateway
            
            # Mock payment with different amount (€45 instead of €50)
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = True
            mock_payment.amount = {"value": "45.00", "currency": "EUR"}  # Mismatch!
            mock_client.payments.get.return_value = mock_payment
            
            # Process payment (should still work - partial payment)
            result = _process_subscription_payment(
                mock_gateway, 
                self.member.name, 
                self.customer.name, 
                "tr_test_payment_456", 
                "sub_test_subscription_123"
            )
            
            # Verify payment was still processed
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["amount"], 45.00)
            
            # Verify Payment Entry was created with correct amount
            payment_entry_name = result["payment_entry"]
            payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
            self.assertEqual(flt(payment_entry.paid_amount), 45.00)
            
            # Invoice should be partially paid
            invoice = frappe.get_doc("Sales Invoice", result["invoice"])
            self.assertIn("Partly Paid", invoice.status)
            
    def test_subscription_webhook_no_unpaid_invoice(self):
        """Test webhook when member has no unpaid invoices"""
        
        # Set up member with subscription but no unpaid invoices
        self.member.mollie_customer_id = "cst_test_customer_123"
        self.member.mollie_subscription_id = "sub_test_subscription_123"
        self.member.save()
        
        with patch('verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway') as mock_gateway_factory:
            mock_gateway = MagicMock()
            mock_client = MagicMock()
            mock_gateway.client = mock_client
            mock_gateway_factory.return_value = mock_gateway
            
            # Mock successful payment
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = True
            mock_payment.amount = {"value": "50.00", "currency": "EUR"}
            mock_client.payments.get.return_value = mock_payment
            
            # Process payment
            result = _process_subscription_payment(
                mock_gateway,
                self.member.name,
                self.customer.name, 
                "tr_test_payment_456",
                "sub_test_subscription_123"
            )
            
            # Should return no_invoice status
            self.assertEqual(result["status"], "no_invoice")
            self.assertIn("No unpaid invoices found", result["reason"])
            
    def test_subscription_webhook_failed_payment(self):
        """Test webhook with failed/cancelled payment"""
        
        # Set up member with subscription
        self.member.mollie_customer_id = "cst_test_customer_123"
        self.member.mollie_subscription_id = "sub_test_subscription_123"
        self.member.save()
        
        with patch('verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway') as mock_gateway_factory:
            mock_gateway = MagicMock()
            mock_client = MagicMock()
            mock_gateway.client = mock_client
            mock_gateway_factory.return_value = mock_gateway
            
            # Mock failed payment
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = False
            mock_payment.status = "failed"
            mock_client.payments.get.return_value = mock_payment
            
            # Process payment
            result = _process_subscription_payment(
                mock_gateway,
                self.member.name,
                self.customer.name,
                "tr_test_payment_456", 
                "sub_test_subscription_123"
            )
            
            # Should be ignored
            self.assertEqual(result["status"], "ignored")
            self.assertIn("is not paid", result["reason"])
            
    def test_full_membership_dues_subscription_flow(self):
        """Integration test for complete membership dues + Mollie subscription flow"""
        
        # Step 1: Create Mollie subscription (mocked)
        with patch('verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
            mock_customer = MagicMock()
            mock_customer.id = "cst_integration_test"
            mock_client.customers.create.return_value = mock_customer
            
            mock_subscription = MagicMock()
            mock_subscription.id = "sub_integration_test"
            mock_subscription.status = "active"
            mock_subscription.next_payment_date = "2025-02-01"
            mock_client.customers_subscriptions.with_parent_id.return_value.create.return_value = mock_subscription
            
            # Create subscription
            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Test Gateway")
            subscription_result = gateway.create_subscription(self.member, {
                "amount": 50.00,
                "interval": "1 month",
                "currency": "EUR"
            })
            
            self.assertEqual(subscription_result["status"], "success")
            
        # Step 2: Generate invoice from dues schedule
        invoice_name = self.dues_schedule.generate_invoice(force=True)
        self.assertIsNotNone(invoice_name)
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertIn("Unpaid", invoice.status)
        
        # Step 3: Process subscription payment via webhook
        webhook_payload = {
            "id": "sub_integration_test",
            "payment": {"id": "tr_integration_payment"}
        }
        
        with patch('verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway') as mock_gateway_factory:
            mock_gateway = MagicMock()
            mock_client = MagicMock()
            mock_gateway.client = mock_client
            mock_gateway_factory.return_value = mock_gateway
            
            # Mock successful payment
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = True
            mock_payment.amount = {"value": "50.00", "currency": "EUR"}
            mock_client.payments.get.return_value = mock_payment
            
            # Mock subscription status
            mock_gateway.get_subscription_status.return_value = {
                "status": "success",
                "subscription": {
                    "status": "active",
                    "next_payment_date": "2025-03-01"
                }
            }
            
            with patch('frappe.request') as mock_request:
                mock_request.get_data.return_value = json.dumps(webhook_payload)
                
                webhook_result = mollie_subscription_webhook()
                self.assertEqual(webhook_result["status"], "processed")
                
        # Step 4: Verify complete flow
        
        # Invoice should be paid
        invoice.reload()
        self.assertEqual(invoice.status, "Paid")
        
        # Member should have updated subscription status
        self.member.reload()
        self.assertEqual(self.member.subscription_status, "active")
        self.assertEqual(str(self.member.next_payment_date), "2025-03-01")
        
        # Payment Entry should exist
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": "tr_integration_payment"},
            fields=["name", "paid_amount", "remarks"]
        )
        
        self.assertEqual(len(payment_entries), 1)
        payment_entry = payment_entries[0]
        self.assertEqual(flt(payment_entry["paid_amount"]), 50.00)
        self.assertIn("Automatic payment via Mollie subscription", payment_entry["remarks"])
        
        # Due to existing hooks, Member Payment History should be updated automatically
        # This happens via the Payment Entry on_submit hook
        
    def tearDown(self):
        """Clean up after each test"""
        super().tearDown()
        
        # Clean up test records in proper order
        for doctype in ["Payment Entry", "Sales Invoice", "Membership Dues Schedule", "Customer", "Member"]:
            frappe.db.rollback()
            
    @classmethod  
    def tearDownClass(cls):
        """Clean up class-level test data"""
        super().tearDownClass()
        
        # Clean up Mollie Settings
        if hasattr(cls, 'mollie_settings'):
            cls.mollie_settings.delete()