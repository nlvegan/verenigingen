#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mollie Payment Integration Test Factory
======================================

Enterprise-grade test data factory specifically designed for Mollie payment integration testing.
This factory extends the EnhancedTestDataFactory with Mollie-specific test data generation,
realistic payment scenarios, and comprehensive business rule validation.

Key Features:
- Realistic Mollie payment data generation
- Test subscription and webhook scenarios
- Payment processing edge case coverage
- Financial transaction validation
- Integration with existing test infrastructure

Author: Test Engineering Team
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any
from faker import Faker

import frappe
from frappe.utils import now_datetime, add_days, add_months, getdate, random_string, flt

from .enhanced_test_factory import EnhancedTestCase, EnhancedTestDataFactory


class MollieTestDataFactory(EnhancedTestDataFactory):
    """
    Specialized test data factory for Mollie payment integration testing
    
    Provides realistic test data for:
    - Mollie customer and subscription creation
    - Payment webhook simulation
    - Financial transaction testing
    - Error scenario generation
    """
    
    def __init__(self, seed: int = 12345, use_faker: bool = True):
        super().__init__(seed, use_faker)
        
        # Mollie-specific test data patterns
        self.mollie_test_patterns = {
            "customer_ids": ["cst_test_{}", "cst_demo_{}", "cst_sandbox_{}"],
            "subscription_ids": ["sub_test_{}", "sub_demo_{}", "sub_sandbox_{}"],
            "payment_ids": ["tr_test_{}", "tr_demo_{}", "tr_sandbox_{}"],
            "webhook_ids": ["wh_test_{}", "wh_demo_{}", "wh_sandbox_{}"]
        }
        
        # Realistic payment amounts (EUR)
        self.realistic_amounts = [15.00, 25.00, 35.00, 50.00, 75.00, 100.00, 150.00]
        
        # Common payment intervals
        self.subscription_intervals = ["1 month", "3 months", "6 months", "1 year"]
        
    def generate_mollie_customer_id(self) -> str:
        """Generate realistic Mollie customer ID"""
        pattern = random.choice(self.mollie_test_patterns["customer_ids"])
        seq = self.get_next_sequence('mollie_customer')
        return pattern.format(f"{seq:08d}")
        
    def generate_mollie_subscription_id(self) -> str:
        """Generate realistic Mollie subscription ID"""
        pattern = random.choice(self.mollie_test_patterns["subscription_ids"])
        seq = self.get_next_sequence('mollie_subscription')
        return pattern.format(f"{seq:08d}")
        
    def generate_mollie_payment_id(self) -> str:
        """Generate realistic Mollie payment ID"""
        pattern = random.choice(self.mollie_test_patterns["payment_ids"])
        seq = self.get_next_sequence('mollie_payment')
        return pattern.format(f"{seq:08d}")
        
    def generate_realistic_amount(self, base_amount: Optional[float] = None) -> float:
        """Generate realistic payment amount with optional base"""
        if base_amount:
            # Add small variation to base amount (±10%)
            variation = base_amount * 0.1 * (random.random() - 0.5) * 2
            return round(base_amount + variation, 2)
        return random.choice(self.realistic_amounts)
        
    def create_mollie_test_member(self, **kwargs):
        """Create member with Mollie-specific test data"""
        # Generate Mollie-specific fields
        mollie_data = {
            "payment_method": "Mollie",
            "custom_mollie_customer_id": self.generate_mollie_customer_id(),
            "custom_subscription_status": "active",
            "custom_next_payment_date": add_months(getdate(), 1)
        }
        
        # Merge with provided kwargs
        data = {**mollie_data, **kwargs}
        
        return self.create_member(**data)
        
    def create_mollie_subscription_scenario(self, member_name: str = None, 
                                           amount: float = None) -> Dict[str, Any]:
        """Create complete Mollie subscription test scenario"""
        if not member_name:
            member = self.create_mollie_test_member()
            member_name = member.name
        else:
            member = frappe.get_doc("Member", member_name)
            
        if not amount:
            amount = self.generate_realistic_amount()
            
        scenario = {
            "member": member_name,
            "customer_id": self.generate_mollie_customer_id(),
            "subscription_id": self.generate_mollie_subscription_id(),
            "amount": amount,
            "currency": "EUR",
            "interval": random.choice(self.subscription_intervals),
            "description": f"Membership dues for {member.full_name}",
            "webhook_url": "https://example.com/webhook",
            "status": "active"
        }
        
        return scenario
        
    def create_webhook_payload(self, subscription_id: str = None, 
                              payment_id: str = None,
                              status: str = "paid") -> Dict[str, Any]:
        """Create realistic Mollie webhook payload"""
        if not subscription_id:
            subscription_id = self.generate_mollie_subscription_id()
        if not payment_id:
            payment_id = self.generate_mollie_payment_id()
            
        payload = {
            "id": subscription_id,
            "mode": "test",
            "resource": "subscription",
            "createdAt": datetime.now().isoformat(),
            "payment": {
                "id": payment_id,
                "mode": "test",
                "status": status,
                "amount": {
                    "value": f"{self.generate_realistic_amount():.2f}",
                    "currency": "EUR"
                },
                "createdAt": datetime.now().isoformat(),
                "paidAt": datetime.now().isoformat() if status == "paid" else None,
                "method": "creditcard"
            },
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/subscriptions/{subscription_id}",
                    "type": "application/hal+json"
                }
            }
        }
        
        return payload
        
    def create_payment_test_data(self, count: int = 5) -> List[Dict[str, Any]]:
        """Create multiple payment test scenarios"""
        scenarios = []
        
        for i in range(count):
            scenario = {
                "payment_id": self.generate_mollie_payment_id(),
                "amount": self.generate_realistic_amount(),
                "status": random.choice(["paid", "pending", "failed", "cancelled"]),
                "method": random.choice(["creditcard", "banktransfer", "ideal", "paypal"]),
                "description": f"Test payment scenario {i+1}",
                "webhook_payload": None
            }
            
            # Generate corresponding webhook payload
            scenario["webhook_payload"] = self.create_webhook_payload(
                payment_id=scenario["payment_id"],
                status=scenario["status"]
            )
            
            scenarios.append(scenario)
            
        return scenarios
        
    def create_edge_case_scenarios(self) -> List[Dict[str, Any]]:
        """Create edge case payment scenarios for testing"""
        scenarios = [
            {
                "name": "amount_mismatch",
                "description": "Payment amount differs from invoice amount",
                "invoice_amount": 50.00,
                "payment_amount": 45.00,
                "expected_behavior": "partial_payment"
            },
            {
                "name": "duplicate_payment",
                "description": "Same payment ID processed twice",
                "payment_id": self.generate_mollie_payment_id(),
                "expected_behavior": "idempotent_processing"
            },
            {
                "name": "orphaned_payment",
                "description": "Payment without corresponding invoice",
                "payment_amount": 25.00,
                "expected_behavior": "no_invoice_found"
            },
            {
                "name": "expired_subscription",
                "description": "Payment for expired subscription",
                "custom_subscription_status": "cancelled",
                "expected_behavior": "payment_rejected"
            },
            {
                "name": "currency_mismatch",
                "description": "Payment in different currency",
                "invoice_currency": "EUR",
                "payment_currency": "USD",
                "expected_behavior": "currency_validation_error"
            }
        ]
        
        return scenarios
        
    def create_performance_test_data(self, webhook_count: int = 25) -> List[Dict[str, Any]]:
        """Create realistic performance test data (achievable 25 webhooks/second)"""
        test_data = []
        
        # Create base members for performance testing
        base_members = []
        for i in range(min(10, webhook_count)):
            member = self.create_mollie_test_member(
                first_name=f"PerfTest{i:03d}",
                last_name="Member"
            )
            base_members.append(member)
            
        # Generate webhook scenarios
        for i in range(webhook_count):
            member = random.choice(base_members)
            
            scenario = {
                "webhook_id": f"perf_test_webhook_{i:04d}",
                "member": member.name,
                "subscription_id": self.generate_mollie_subscription_id(),
                "payment_id": self.generate_mollie_payment_id(),
                "amount": self.generate_realistic_amount(),
                "timestamp": datetime.now() + timedelta(seconds=i),
                "expected_processing_time_ms": random.randint(100, 500),  # Realistic processing time
                "payload": self.create_webhook_payload()
            }
            
            test_data.append(scenario)
            
        return test_data
        
    def create_financial_safeguards_test_data(self) -> Dict[str, Any]:
        """Create test data for financial transaction safeguards"""
        return {
            "duplicate_prevention": {
                "same_payment_id": self.generate_mollie_payment_id(),
                "scenarios": [
                    {"timestamp": datetime.now(), "amount": 50.00},
                    {"timestamp": datetime.now() + timedelta(seconds=30), "amount": 50.00}
                ]
            },
            "amount_validation": {
                "scenarios": [
                    {"invoice_amount": 50.00, "payment_amount": 50.00, "valid": True},
                    {"invoice_amount": 50.00, "payment_amount": 55.00, "valid": False},
                    {"invoice_amount": 50.00, "payment_amount": -10.00, "valid": False},
                    {"invoice_amount": 50.00, "payment_amount": 0.00, "valid": False}
                ]
            },
            "currency_validation": {
                "scenarios": [
                    {"invoice_currency": "EUR", "payment_currency": "EUR", "valid": True},
                    {"invoice_currency": "EUR", "payment_currency": "USD", "valid": False},
                    {"invoice_currency": "EUR", "payment_currency": "", "valid": False}
                ]
            },
            "temporal_validation": {
                "scenarios": [
                    {"payment_date": datetime.now(), "valid": True},
                    {"payment_date": datetime.now() - timedelta(days=30), "valid": True},
                    {"payment_date": datetime.now() + timedelta(days=1), "valid": False}
                ]
            }
        }
    
    def _ensure_test_item(self):
        """Ensure test item exists for invoice creation"""
        item_code = "TEST-Membership-Dues"
        if not frappe.db.exists("Item", item_code):
            # First ensure Item Group exists
            if not frappe.db.exists("Item Group", "Services"):
                # Create Services item group if it doesn't exist
                item_group = frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": "Services",
                    "parent_item_group": "All Item Groups"
                })
                try:
                    item_group.insert(ignore_permissions=True)
                except frappe.DuplicateEntryError:
                    pass  # Already exists
            
            # Create the test item
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": "Test Membership Dues",
                "description": "Test item for membership dues invoices",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_service_item": 1,
                "has_variants": 0,
                "is_sales_item": 1,
                "is_purchase_item": 0
            })
            try:
                item.insert(ignore_permissions=True)
                frappe.db.commit()
            except frappe.DuplicateEntryError:
                pass  # Already exists


class MollieTestCase(EnhancedTestCase):
    """
    Enhanced test case specifically for Mollie payment integration testing
    
    Provides convenience methods and specialized assertions for Mollie testing
    """
    
    def setUp(self):
        super().setUp()
        self.mollie_factory = MollieTestDataFactory(seed=12345, use_faker=True)
        
    def create_mollie_test_member(self, **kwargs):
        """Convenience method for creating Mollie test members"""
        return self.mollie_factory.create_mollie_test_member(**kwargs)
        
    def create_mollie_subscription_scenario(self, **kwargs):
        """Convenience method for creating subscription scenarios"""
        return self.mollie_factory.create_mollie_subscription_scenario(**kwargs)
        
    def create_webhook_payload(self, **kwargs):
        """Convenience method for creating webhook payloads"""
        return self.mollie_factory.create_webhook_payload(**kwargs)
        
    def assertPaymentProcessed(self, payment_id: str, expected_amount: float):
        """Assert that a payment was processed correctly"""
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id},
            fields=["name", "paid_amount", "docstatus", "party"]
        )
        
        self.assertGreater(len(payment_entries), 0, 
                          f"No payment entry found for payment ID {payment_id}")
        
        payment_entry = payment_entries[0]
        self.assertEqual(flt(payment_entry["paid_amount"]), expected_amount,
                        f"Payment amount mismatch for {payment_id}")
        self.assertEqual(payment_entry["docstatus"], 1,
                        f"Payment entry {payment_entry['name']} should be submitted")
                        
    def assertInvoicePaid(self, invoice_name: str):
        """Assert that an invoice is marked as paid"""
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertIn(invoice.status, ["Paid", "Partly Paid"],
                     f"Invoice {invoice_name} should be paid or partly paid, got {invoice.status}")
                     
    def assertMemberSubscriptionActive(self, member_name: str):
        """Assert that member has active subscription status"""
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.custom_subscription_status, "active",
                        f"Member {member_name} should have active subscription")
        self.assertIsNotNone(member.custom_mollie_customer_id,
                           f"Member {member_name} should have Mollie customer ID")
                           
    def assertWebhookProcessingTime(self, processing_time_ms: int, max_time_ms: int = 1000):
        """Assert that webhook processing time is within acceptable limits"""
        self.assertLessEqual(processing_time_ms, max_time_ms,
                            f"Webhook processing took {processing_time_ms}ms, "
                            f"which exceeds maximum of {max_time_ms}ms")
                            
    def simulate_webhook_load(self, webhook_count: int = 25, 
                             time_window_seconds: int = 1) -> List[Dict[str, Any]]:
        """Simulate realistic webhook load (25 webhooks/second)"""
        test_data = self.mollie_factory.create_performance_test_data(webhook_count)
        
        results = []
        start_time = datetime.now()
        
        for i, scenario in enumerate(test_data):
            # Simulate realistic timing
            target_time = start_time + timedelta(seconds=i / (webhook_count / time_window_seconds))
            current_time = datetime.now()
            
            if current_time < target_time:
                time.sleep((target_time - current_time).total_seconds())
                
            # Process webhook (mocked for testing)
            processing_start = datetime.now()
            
            # Simulate processing time
            import time
            time.sleep(scenario["expected_processing_time_ms"] / 1000.0)
            
            processing_end = datetime.now()
            processing_time_ms = (processing_end - processing_start).total_seconds() * 1000
            
            result = {
                "webhook_id": scenario["webhook_id"],
                "processing_time_ms": processing_time_ms,
                "success": True,
                "timestamp": processing_end
            }
            
            results.append(result)
            
        return results


# Convenience factory instance for direct usage
mollie_factory = MollieTestDataFactory()


if __name__ == "__main__":
    # Example usage and testing
    print("Testing MollieTestDataFactory...")
    
    try:
        factory = MollieTestDataFactory(seed=12345, use_faker=True)
        
        # Test basic ID generation
        customer_id = factory.generate_mollie_customer_id()
        subscription_id = factory.generate_mollie_subscription_id()
        payment_id = factory.generate_mollie_payment_id()
        
        print(f"✅ Generated Mollie IDs:")
        print(f"  Customer: {customer_id}")
        print(f"  Subscription: {subscription_id}")
        print(f"  Payment: {payment_id}")
        
        # Test webhook payload generation
        webhook_payload = factory.create_webhook_payload()
        print(f"✅ Generated webhook payload with payment ID: {webhook_payload['payment']['id']}")
        
        # Test edge case scenarios
        edge_cases = factory.create_edge_case_scenarios()
        print(f"✅ Generated {len(edge_cases)} edge case scenarios")
        
        # Test performance data
        perf_data = factory.create_performance_test_data(25)
        print(f"✅ Generated {len(perf_data)} performance test scenarios")
        
        # Test financial safeguards
        safeguards = factory.create_financial_safeguards_test_data()
        print(f"✅ Generated financial safeguards test data with {len(safeguards)} categories")
        
        print("✅ MollieTestDataFactory validation completed successfully")
        
    except Exception as e:
        print(f"❌ MollieTestDataFactory test failed: {e}")
        raise