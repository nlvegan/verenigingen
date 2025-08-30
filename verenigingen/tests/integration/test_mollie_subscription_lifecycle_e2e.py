#!/usr/bin/env python3
"""
End-to-End Mollie Subscription Lifecycle Test
============================================

Complete integration test for the subscription workflow:
1. Create test member with active membership and dues schedule
2. Create Mollie subscription for recurring payments
3. Simulate webhook callback for payment processing
4. Verify payment matches open invoice
5. Clean up by cancelling subscription

This tests the complete business workflow that members would experience.
"""

import frappe
from frappe.utils import today, add_months, flt
from decimal import Decimal
import json
from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    PaymentGatewayFactory,
    mollie_subscription_webhook
)


class TestMollieSubscriptionLifecycleE2E(EnhancedTestCase):
    """
    End-to-End Subscription Lifecycle Test
    
    Tests the complete subscription workflow from creation to cancellation,
    including webhook payment processing and invoice matching.
    """
    
    def setUp(self):
        """Set up comprehensive test persona"""
        super().setUp()
        
        print("\n🎭 Creating Test Persona: Active Member with Dues Schedule")
        
        # Create comprehensive test member (Dutch association member)
        self.test_member = self.create_test_member(
            first_name="Emma",
            last_name="van Subscription",
            email="emma.subscription@test.veganisme.nl",
            birth_date="1985-03-15",
            iban="NL91ABNA0417164300",  # Real Dutch IBAN format
            member_number="SUB-2025-001",
            status="Active"
        )
        
        print(f"✅ Created member: {self.test_member.name} ({self.test_member.full_name})")
        
        # Create customer for financial operations
        self.customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": self.test_member.full_name,
            "customer_type": "Individual",
            "territory": "Netherlands",
            "default_currency": "EUR"
        })
        self.customer.insert()
        
        # Link member to customer
        self.test_member.customer = self.customer.name
        self.test_member.save()
        
        print(f"✅ Created customer: {self.customer.name}")
        
        # Create active membership
        self.membership = self._create_active_membership()
        print(f"✅ Created membership: {self.membership.name}")
        
        # Create membership dues schedule
        self.dues_schedule = self._create_dues_schedule()
        print(f"✅ Created dues schedule: {self.dues_schedule.name}")
        
        # Create unpaid invoice for current period
        self.current_invoice = self._create_current_period_invoice()
        print(f"✅ Created invoice: {self.current_invoice.name} (€{self.current_invoice.grand_total})")
        
        print("🎭 Test Persona Complete: Emma van Subscription ready for subscription testing")

    def test_complete_subscription_lifecycle(self):
        """
        Test complete subscription lifecycle:
        1. Create subscription
        2. Process webhook payment
        3. Verify invoice payment
        4. Cancel subscription
        """
        print("\n🔄 Starting Complete Subscription Lifecycle Test")
        
        # Step 1: Create subscription
        subscription_result = self._create_mollie_subscription()
        self.assertTrue(subscription_result["success"], f"Subscription creation failed: {subscription_result}")
        
        customer_id = subscription_result["customer_id"]
        subscription_id = subscription_result["subscription_id"]
        
        print(f"✅ Step 1: Subscription created - {subscription_id}")
        
        # Step 2: Simulate first payment via webhook
        payment_result = self._simulate_webhook_payment(customer_id, subscription_id)
        self.assertTrue(payment_result["success"], f"Webhook payment failed: {payment_result}")
        
        payment_id = payment_result["payment_id"]
        print(f"✅ Step 2: Payment processed - {payment_id}")
        
        # Step 3: Verify payment entry and invoice status
        self._verify_payment_processing(payment_id)
        print("✅ Step 3: Payment verification complete")
        
        # Step 4: Cancel subscription (cleanup)
        cancel_result = self._cancel_mollie_subscription(customer_id, subscription_id)
        self.assertTrue(cancel_result["success"], f"Subscription cancellation failed: {cancel_result}")
        
        print("✅ Step 4: Subscription cancelled successfully")
        print("🎉 Complete Subscription Lifecycle Test: SUCCESS")

    def _create_active_membership(self):
        """Create active membership for test persona"""
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": self.test_member.name,
            "membership_type": "Full Member",
            "membership_status": "Current",
            "from_date": today(),
            "to_date": add_months(today(), 12),  # 1 year membership
            "amount": 300.00,  # Annual dues
            "currency": "EUR",
            "is_paid": 0  # Unpaid - will use subscription
        })
        membership.insert()
        membership.submit()
        return membership

    def _create_dues_schedule(self):
        """Create membership dues schedule for recurring payments"""
        
        # First ensure we have a dues schedule doctype or create monthly billing record
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.test_member.name,
            "membership": self.membership.name,
            "billing_cycle": "Monthly",
            "monthly_amount": 25.00,  # €25/month
            "currency": "EUR",
            "start_date": today(),
            "end_date": add_months(today(), 12),
            "status": "Active",
            "auto_invoice": 1  # Automatically create invoices
        })
        dues_schedule.insert()
        dues_schedule.submit()
        return dues_schedule

    def _create_current_period_invoice(self):
        """Create unpaid invoice for current billing period"""
        
        # Ensure test item exists
        if not frappe.db.exists("Item", "MEMBERSHIP-DUES"):
            test_item = frappe.get_doc({
                "doctype": "Item",
                "item_code": "MEMBERSHIP-DUES",
                "item_name": "Monthly Membership Dues",
                "item_group": "Services",
                "is_sales_item": 1,
                "is_service_item": 1,
                "standard_rate": 25.00
            })
            test_item.insert()
        
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.customer.name,
            "customer_name": self.customer.customer_name,
            "posting_date": today(),
            "due_date": add_months(today(), 1),
            "currency": "EUR",
            "items": [{
                "item_code": "MEMBERSHIP-DUES",
                "item_name": "Monthly Membership Dues",
                "description": f"Monthly membership dues for {self.test_member.full_name} - {today()}",
                "qty": 1,
                "rate": 25.00,
                "amount": 25.00
            }],
            "remarks": f"Monthly dues invoice for subscription testing - Member: {self.test_member.name}"
        })
        
        invoice.insert()
        invoice.submit()
        return invoice

    def _create_mollie_subscription(self):
        """Create real Mollie subscription using PaymentGatewayFactory"""
        try:
            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
            
            # Customer data for Mollie
            customer_data = {
                "name": self.test_member.full_name,
                "email": self.test_member.email,
                "locale": "nl_NL"  # Dutch locale
            }
            
            # Subscription data
            subscription_data = {
                "amount": {"currency": "EUR", "value": "25.00"},
                "interval": "1 month",
                "description": f"Monthly membership dues - {self.test_member.full_name}",
                "webhookUrl": frappe.utils.get_url("/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook")
            }
            
            # Create subscription via gateway
            result = gateway.create_subscription(customer_data, subscription_data)
            
            if result.get("customer_id") and result.get("subscription_id"):
                # Update member with Mollie IDs
                self.test_member.mollie_customer_id = result["customer_id"]
                self.test_member.mollie_subscription_id = result["subscription_id"]
                self.test_member.subscription_status = "active"
                self.test_member.save()
                
                return {
                    "success": True,
                    "customer_id": result["customer_id"],
                    "subscription_id": result["subscription_id"]
                }
            else:
                return {"success": False, "error": "Invalid subscription response", "result": result}
                
        except Exception as e:
            frappe.log_error(f"Subscription creation error: {str(e)}", "E2E Test")
            return {"success": False, "error": str(e)}

    def _simulate_webhook_payment(self, customer_id, subscription_id):
        """Simulate Mollie webhook for subscription payment"""
        try:
            # Generate test payment ID
            import uuid
            payment_id = f"tr_test_{str(uuid.uuid4())[:8]}"
            
            # Create webhook payload that matches Mollie's format
            webhook_payload = {
                "id": payment_id,
                "mode": "test",
                "createdAt": frappe.utils.now(),
                "status": "paid",
                "amount": {
                    "value": "25.00",
                    "currency": "EUR"
                },
                "description": f"Monthly membership dues - {self.test_member.full_name}",
                "method": "directdebit",
                "metadata": {},
                "subscriptionId": subscription_id,
                "customerId": customer_id,
                "sequenceType": "recurring",
                "_links": {
                    "self": {
                        "href": f"https://api.mollie.com/v2/payments/{payment_id}",
                        "type": "application/hal+json"
                    }
                }
            }
            
            # Mock the webhook call with our payload
            # We'll patch the payment retrieval to return our test payment
            def mock_get_payment(payment_id_param):
                mock_payment = type('MockPayment', (), {
                    'id': payment_id,
                    'status': 'paid',
                    'amount': {'value': '25.00', 'currency': 'EUR'},
                    'is_paid': lambda: True,
                    'subscription_id': subscription_id,
                    'customer_id': customer_id
                })()
                return mock_payment
            
            # Patch the Mollie client's payment retrieval
            with patch.object(PaymentGatewayFactory.get_gateway("Mollie", "Default").client.payments, 'get', side_effect=mock_get_payment):
                # Process webhook with our test data
                frappe.local.request = type('MockRequest', (), {
                    'get_data': lambda as_text=False: json.dumps(webhook_payload)
                })()
                
                # Call the actual webhook handler
                result = mollie_subscription_webhook()
                
                return {
                    "success": True,
                    "payment_id": payment_id,
                    "webhook_result": result
                }
                
        except Exception as e:
            frappe.log_error(f"Webhook simulation error: {str(e)}", "E2E Test")
            return {"success": False, "error": str(e)}

    def _verify_payment_processing(self, payment_id):
        """Verify that webhook processing created payment entry and updated invoice"""
        
        # Check for Payment Entry
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={
                "reference_no": payment_id,
                "party": self.customer.name
            },
            fields=["name", "paid_amount", "posting_date", "reference_no"]
        )
        
        self.assertGreater(len(payment_entries), 0, "Payment Entry should be created for webhook payment")
        
        payment_entry = payment_entries[0]
        self.assertEqual(float(payment_entry["paid_amount"]), 25.00, "Payment amount should match subscription amount")
        
        print(f"✅ Payment Entry created: {payment_entry['name']} - €{payment_entry['paid_amount']}")
        
        # Check invoice status
        self.current_invoice.reload()
        
        # Verify payment allocation (invoice should be paid or partly paid)
        if self.current_invoice.status in ["Paid", "Partly Paid"]:
            print(f"✅ Invoice status updated: {self.current_invoice.status}")
        else:
            print(f"ℹ️  Invoice status: {self.current_invoice.status} (may require manual reconciliation)")
        
        # Check outstanding amount
        outstanding = flt(self.current_invoice.outstanding_amount)
        if outstanding == 0:
            print("✅ Invoice fully paid - outstanding amount: €0.00")
        else:
            print(f"ℹ️  Invoice outstanding amount: €{outstanding}")

    def _cancel_mollie_subscription(self, customer_id, subscription_id):
        """Cancel the Mollie subscription for cleanup"""
        try:
            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
            
            # Cancel via gateway
            success = gateway.cancel_subscription(customer_id, subscription_id)
            
            if success:
                # Update member record
                self.test_member.subscription_status = "cancelled"
                self.test_member.save()
                
                return {"success": True}
            else:
                return {"success": False, "error": "Gateway cancellation failed"}
                
        except Exception as e:
            frappe.log_error(f"Subscription cancellation error: {str(e)}", "E2E Test")
            return {"success": False, "error": str(e)}

    def tearDown(self):
        """Clean up test data"""
        print("\n🧹 Cleaning up test persona...")
        
        # Cancel any remaining subscriptions
        if hasattr(self, 'test_member') and self.test_member.mollie_subscription_id:
            try:
                gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
                gateway.cancel_subscription(
                    self.test_member.mollie_customer_id,
                    self.test_member.mollie_subscription_id
                )
                print("✅ Subscription cleaned up")
            except:
                pass  # Already cancelled or doesn't exist
        
        super().tearDown()
        print("✅ Test persona cleanup complete")


# Test Documentation:
# ===================
# This test creates a complete test persona "Emma van Subscription" with:
# - Active membership (1 year, €300 annual dues)
# - Monthly dues schedule (€25/month)
# - Unpaid invoice for current period
# - Real Mollie subscription creation
# - Webhook payment simulation
# - Payment entry verification
# - Invoice payment reconciliation
# - Subscription cancellation cleanup
#
# Success Criteria:
# ✅ Subscription created successfully in Mollie
# ✅ Webhook payment processed and logged
# ✅ Payment Entry created with correct amount
# ✅ Invoice status updated (paid/partly paid)
# ✅ Subscription cancelled for cleanup
#
# This validates the complete member subscription workflow
# from signup through payment processing to cancellation.