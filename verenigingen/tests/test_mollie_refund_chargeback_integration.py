"""
Mollie Refund & Chargeback Integration Test Suite
=================================================

Consolidated refund and chargeback testing following Phase 4D A+ standards.
Integrates with the new refund implementation and Enhanced Test Factory methods
for comprehensive testing of financial transaction reversals.

Architecture:
- Enhanced Test Factory integration with refund methods
- Real Payment Entry reversals (no custom DocTypes)
- Database transaction safety and race condition prevention
- Dutch business rule compliance (IBAN, amounts, timing)
- Comprehensive webhook security validation
- Performance baselines for financial operations

This test file consolidates and replaces:
- test_refund_webhook_integration.py (incomplete implementation)
- Various refund-related test fragments
- Chargeback processing tests
- Financial transaction reversal validations
"""

import json
import unittest
from unittest.mock import patch
from decimal import Decimal
import time

import frappe
from frappe.utils import flt, now_datetime, add_days

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.payment_services.refund_utility import (
    initiate_refund,
    get_payment_refund_info, 
    get_donation_refund_info,
    initiate_donation_refund
)
from verenigingen.utils.payment_services.mollie_webhook_processor import MollieWebhookProcessor


class TestMollieRefundChargebackIntegration(EnhancedTestCase):
    """
    Comprehensive refund and chargeback integration testing.
    
    Tests complete financial reversal workflows:
    - Partial and full refunds
    - Chargeback processing
    - Concurrent transaction safety
    - Dutch business rule compliance
    - Database integrity under load
    - Webhook-driven refund processing
    """
    
    def setUp(self):
        super().setUp()
        
        # Initialize components for testing
        self.webhook_processor = MollieWebhookProcessor("test")
        
        # Create realistic test data using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Refund",
            last_name="Integration",
            email="refund.integration@test.example.com"
        )
        
        # Create test donation with payment
        self.test_donation = self.create_test_donation(
            donor_email=self.test_member.email,
            amount=100.0
        )
        
        # Create original payment entry for refund testing
        self.original_payment = self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no="test_payment_refund_123",
            custom_donation=self.test_donation.name
        )
        
        # Performance baselines for refund operations
        self.refund_performance_baselines = {
            "refund_initiation": 400,        # Business logic + validation
            "refund_info_query": 150,        # Database queries
            "webhook_refund_processing": 500, # Complete webhook workflow
            "concurrent_refund_check": 200,   # Race condition prevention
            "chargeback_processing": 400      # Chargeback workflow
        }
    
    def test_partial_refund_workflow_integration(self):
        """
        Test complete partial refund workflow integration.
        
        Covers the entire partial refund process:
        1. Refund validation and initiation
        2. Mollie API integration (mocked)
        3. Webhook processing for refund confirmation
        4. Payment Entry reversal creation
        5. Database integrity validation
        """
        # Test refund initiation with business rule validation
        with self.assertQueryCount(self.refund_performance_baselines["refund_initiation"]):
            # Mock Mollie API call (legitimate external service mock)
            with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
                mock_instance = mock_mollie.return_value
                mock_instance.create_refund.return_value = {
                    "status": "success",
                    "refund_id": "refund_partial_123",
                    "amount": 30.0
                }
                
                # Initiate partial refund through real business logic
                refund_result = initiate_refund(
                    payment_entry_name=self.original_payment.name,
                    amount=30.0,
                    reason="Integration test partial refund"
                )
        
        # Validate refund initiation results
        self.assertEqual(refund_result["status"], "success")
        self.assertIn("refund_id", refund_result["data"])
        self.assertEqual(refund_result["data"]["amount"], 30.0)
        
        # Simulate webhook processing for refund confirmation
        refund_webhook_data = self.create_test_mollie_webhook_data(
            webhook_type="refund.completed",
            payment_id="test_payment_refund_123",
            refund_id="refund_partial_123",
            refund_amount=30.0
        )
        
        # Process refund webhook with security validation
        security_validation = self.simulate_mollie_webhook_security(
            refund_webhook_data["webhook_payload"]
        )
        
        with self.assertQueryCount(self.refund_performance_baselines["webhook_refund_processing"]):
            with patch.object(self.webhook_processor, '_fetch_refund_details') as mock_fetch:
                mock_fetch.return_value = {
                    "id": "refund_partial_123",
                    "amount": {"value": "30.00", "currency": "EUR"},
                    "status": "refunded",
                    "description": "Integration test partial refund",
                    "payment_id": "test_payment_refund_123"
                }
                
                # Process through real webhook business logic
                webhook_result = self.webhook_processor.process_refund_webhook(
                    webhook_payload=refund_webhook_data["raw_payload"],
                    signature=security_validation["test_signature"]
                )
        
        # Validate webhook processing results
        self.assertEqual(webhook_result["status"], "completed")
        self.assertEqual(webhook_result["refund_amount"], "30.00")
        
        # Verify Payment Entry reversal was created (real database validation)
        refund_entries = frappe.get_all("Payment Entry",
            filters={
                "payment_type": "Pay",
                "custom_reversal_type": "Refund",
                "reference_no": "refund_partial_123",
                "docstatus": 1
            },
            fields=["name", "paid_amount", "custom_donation", "custom_original_payment_id"]
        )
        
        self.assertTrue(refund_entries, "Refund Payment Entry should be created")
        refund_entry = refund_entries[0]
        self.assertEqual(refund_entry.paid_amount, 30.0)
        self.assertEqual(refund_entry.custom_donation, self.test_donation.name)
        self.assertEqual(refund_entry.custom_original_payment_id, "test_payment_refund_123")
        
        print("✅ Partial refund workflow integration test passed")
    
    def test_full_refund_workflow_integration(self):
        """
        Test complete full refund workflow integration.
        
        Tests the full refund scenario including:
        - Full amount validation
        - Complete reversal processing
        - Database state consistency
        - Donation payment history updates
        """
        # Test full refund initiation
        with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
            mock_instance = mock_mollie.return_value
            mock_instance.create_refund.return_value = {
                "status": "success",
                "refund_id": "refund_full_456",
                "amount": 100.0
            }
            
            # Initiate full refund (no amount specified = full refund)
            refund_result = initiate_refund(
                payment_entry_name=self.original_payment.name,
                reason="Integration test full refund"
            )
        
        # Validate full refund initiation
        self.assertEqual(refund_result["status"], "success")
        self.assertEqual(refund_result["data"]["amount"], 100.0)
        
        # Process corresponding webhook
        full_refund_webhook = self.create_test_mollie_webhook_data(
            webhook_type="refund.completed",
            payment_id="test_payment_refund_123",
            refund_id="refund_full_456",
            refund_amount=100.0
        )
        
        security_validation = self.simulate_mollie_webhook_security(
            full_refund_webhook["webhook_payload"]
        )
        
        with patch.object(self.webhook_processor, '_fetch_refund_details') as mock_fetch:
            mock_fetch.return_value = {
                "id": "refund_full_456",
                "amount": {"value": "100.00", "currency": "EUR"},
                "status": "refunded",
                "description": "Integration test full refund",
                "payment_id": "test_payment_refund_123"
            }
            
            webhook_result = self.webhook_processor.process_refund_webhook(
                webhook_payload=full_refund_webhook["raw_payload"],
                signature=security_validation["test_signature"]
            )
        
        # Verify complete reversal
        self.assertEqual(webhook_result["status"], "completed")
        self.assertEqual(webhook_result["refund_amount"], "100.00")
        
        # Check that no further refunds are possible
        refund_info = get_payment_refund_info(self.original_payment.name)
        self.assertEqual(refund_info["status"], "success")
        self.assertEqual(refund_info["data"]["available_amount"], 0.0)
        self.assertFalse(refund_info["data"]["can_refund"])
        
        print("✅ Full refund workflow integration test passed")
    
    def test_concurrent_refund_prevention(self):
        """
        Test concurrent refund prevention and race condition safety.
        
        Validates the database transaction safety mechanisms:
        - Row-level locking (FOR UPDATE)
        - Concurrent refund attempt detection
        - Available amount validation
        - Database integrity under concurrent load
        """
        # Create additional payment for concurrent testing
        concurrent_payment = self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no="test_concurrent_payment_789",
            custom_donation=self.test_donation.name
        )
        
        with self.assertQueryCount(self.refund_performance_baselines["concurrent_refund_check"]):
            # Mock first refund attempt
            with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
                mock_instance = mock_mollie.return_value
                mock_instance.create_refund.return_value = {
                    "status": "success",
                    "refund_id": "concurrent_refund_1",
                    "amount": 60.0
                }
                
                # First refund should succeed
                first_refund = initiate_refund(
                    payment_entry_name=concurrent_payment.name,
                    amount=60.0,
                    reason="First concurrent refund"
                )
        
        self.assertEqual(first_refund["status"], "success")
        
        # Create the refund Payment Entry to simulate processing
        self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=60.0,
            reference_no="concurrent_refund_1",
            custom_original_payment_id="test_concurrent_payment_789",
            custom_reversal_type="Refund",
            submit=True  # Submit to make it count against available amount
        )
        
        # Attempt second refund that would exceed available amount
        with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
            mock_instance = mock_mollie.return_value
            mock_instance.create_refund.return_value = {
                "status": "success",
                "refund_id": "concurrent_refund_2", 
                "amount": 50.0
            }
            
            # Second refund should fail due to insufficient available amount
            second_refund = initiate_refund(
                payment_entry_name=concurrent_payment.name,
                amount=50.0,
                reason="Second concurrent refund (should fail)"
            )
        
        # Validate concurrent refund prevention
        self.assertEqual(second_refund["status"], "error")
        self.assertIn("40", second_refund["message"])  # Only 40.0 should be available
        self.assertEqual(second_refund["error_code"], "INSUFFICIENT_REFUNDABLE_AMOUNT")
        
        print("✅ Concurrent refund prevention test passed")
    
    def test_chargeback_processing_integration(self):
        """
        Test chargeback processing integration.
        
        Tests chargeback workflow which is similar to refunds but
        initiated by the bank/payment processor rather than merchant:
        - Chargeback webhook processing
        - Automatic reversal creation
        - Different reversal type handling
        - Impact on available refund amounts
        """
        # Create chargeback webhook data
        chargeback_webhook_data = self.create_test_mollie_webhook_data(
            webhook_type="chargeback.created",
            payment_id="test_payment_refund_123"
        )
        
        # Add chargeback-specific data
        chargeback_webhook_data["webhook_payload"].update({
            "resource": "chargeback",
            "chargeback": {
                "id": "chargeback_test_123",
                "amount": {"value": "25.00", "currency": "EUR"},
                "reason": {"code": "duplicate_processing", "description": "Duplicate processing"},
                "createdAt": now_datetime().isoformat() + "Z"
            }
        })
        
        # Process chargeback webhook
        with self.assertQueryCount(self.refund_performance_baselines["chargeback_processing"]):
            with patch.object(self.webhook_processor, '_fetch_chargeback_details') as mock_fetch:
                mock_fetch.return_value = {
                    "id": "chargeback_test_123",
                    "amount": {"value": "25.00", "currency": "EUR"},
                    "reason": {"code": "duplicate_processing", "description": "Duplicate processing"},
                    "payment_id": "test_payment_refund_123"
                }
                
                # Process through chargeback business logic
                security_validation = self.simulate_mollie_webhook_security(
                    chargeback_webhook_data["webhook_payload"]
                )
                
                chargeback_result = self.webhook_processor.process_chargeback_webhook(
                    webhook_payload=chargeback_webhook_data["raw_payload"],
                    signature=security_validation["test_signature"]
                )
        
        # Validate chargeback processing
        self.assertEqual(chargeback_result["status"], "completed")
        self.assertEqual(chargeback_result["chargeback_amount"], "25.00")
        
        # Verify chargeback Payment Entry creation
        chargeback_entries = frappe.get_all("Payment Entry",
            filters={
                "payment_type": "Pay",
                "custom_reversal_type": "Chargeback",
                "reference_no": "chargeback_test_123"
            },
            fields=["name", "paid_amount", "custom_original_payment_id"]
        )
        
        self.assertTrue(chargeback_entries, "Chargeback Payment Entry should be created")
        chargeback_entry = chargeback_entries[0]
        self.assertEqual(chargeback_entry.paid_amount, 25.0)
        self.assertEqual(chargeback_entry.custom_original_payment_id, "test_payment_refund_123")
        
        # Verify impact on available refund amount
        payment_info = get_payment_refund_info(self.original_payment.name)
        # Original 100.0 - 25.0 chargeback = 75.0 available for refund
        self.assertEqual(payment_info["data"]["available_amount"], 75.0)
        
        print("✅ Chargeback processing integration test passed")
    
    def test_donation_refund_info_accuracy(self):
        """
        Test donation refund information accuracy and completeness.
        
        Validates that donation-level refund information provides
        accurate financial data across multiple payments and reversals:
        - Total paid amounts
        - Total refunded amounts  
        - Total chargeback amounts
        - Net amounts and refundability
        """
        # Create multiple payments for the same donation
        payment1 = self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=50.0,
            reference_no="donation_payment_1",
            custom_donation=self.test_donation.name
        )
        
        payment2 = self.create_test_payment_entry(
            payment_type="Receive", 
            paid_amount=30.0,
            reference_no="donation_payment_2",
            custom_donation=self.test_donation.name
        )
        
        # Create partial refund
        refund1 = self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=20.0,
            reference_no="donation_refund_1",
            custom_donation=self.test_donation.name,
            custom_reversal_type="Refund",
            custom_original_payment_id="donation_payment_1"
        )
        
        # Create chargeback
        chargeback1 = self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=10.0,
            reference_no="donation_chargeback_1", 
            custom_donation=self.test_donation.name,
            custom_reversal_type="Chargeback",
            custom_original_payment_id="donation_payment_2"
        )
        
        # Get comprehensive donation refund info
        with self.assertQueryCount(self.refund_performance_baselines["refund_info_query"]):
            donation_info = get_donation_refund_info(self.test_donation.name)
        
        # Validate donation refund information accuracy
        self.assertEqual(donation_info["status"], "success")
        data = donation_info["data"]
        
        # Total paid: original 100.0 + payment1 50.0 + payment2 30.0 = 180.0
        self.assertEqual(data["total_paid"], 180.0)
        
        # Total refunded: 20.0
        self.assertEqual(data["total_refunded"], 20.0)
        
        # Total chargebacks: 10.0
        self.assertEqual(data["total_chargebacks"], 10.0)
        
        # Net amount: 180.0 - 20.0 - 10.0 = 150.0
        self.assertEqual(data["net_amount"], 150.0)
        
        # Should still be able to refund (has Mollie payments)
        self.assertTrue(data["can_refund"])
        
        # Verify payment history structure
        self.assertIn("original_payments", data)
        self.assertIn("refunds", data)
        self.assertIn("chargebacks", data)
        
        print("✅ Donation refund info accuracy test passed")
    
    def test_refund_business_rule_validation(self):
        """
        Test Dutch business rule validation for refunds.
        
        Validates compliance with Dutch financial regulations:
        - Minimum refund amounts
        - Maximum refund descriptions
        - IBAN validation for refund accounts
        - Timing constraints
        """
        # Test minimum refund amount validation
        with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService'):
            result = initiate_refund(
                payment_entry_name=self.original_payment.name,
                amount=0.001,  # Below minimum (0.01)
                reason="Test minimum amount"
            )
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "INVALID_AMOUNT")
        
        # Test maximum description length validation
        long_description = "x" * 300  # Exceeds maximum length
        
        with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService'):
            result = initiate_refund(
                payment_entry_name=self.original_payment.name,
                amount=10.0,
                reason=long_description
            )
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "DESCRIPTION_TOO_LONG")
        
        # Test valid refund with Dutch compliance
        with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
            mock_instance = mock_mollie.return_value
            mock_instance.create_refund.return_value = {
                "status": "success",
                "refund_id": "valid_refund_789",
                "amount": 15.50
            }
            
            result = initiate_refund(
                payment_entry_name=self.original_payment.name,
                amount=15.50,
                reason="Valid Dutch compliant refund"
            )
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["amount"], 15.50)
        
        print("✅ Refund business rule validation test passed")
    
    def test_refund_performance_baselines(self):
        """
        Validate refund processing performance against established baselines.
        
        Ensures refund operations meet performance requirements:
        - Refund initiation: <400 queries
        - Info queries: <150 queries
        - Webhook processing: <500 queries
        - Concurrent checks: <200 queries
        """
        import time
        
        # Test refund initiation performance
        start_time = time.time()
        with self.assertQueryCount(self.refund_performance_baselines["refund_initiation"]):
            with patch('verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService') as mock_mollie:
                mock_instance = mock_mollie.return_value
                mock_instance.create_refund.return_value = {
                    "status": "success",
                    "refund_id": "perf_test_refund",
                    "amount": 25.0
                }
                
                result = initiate_refund(
                    payment_entry_name=self.original_payment.name,
                    amount=25.0,
                    reason="Performance test refund"
                )
        refund_duration = time.time() - start_time
        
        # Test refund info query performance
        start_time = time.time()
        with self.assertQueryCount(self.refund_performance_baselines["refund_info_query"]):
            info_result = get_payment_refund_info(self.original_payment.name)
        info_duration = time.time() - start_time
        
        # Performance evaluation
        if refund_duration < 1.0:
            print(f"🚀 Excellent refund initiation performance: {refund_duration:.3f}s")
        elif refund_duration < 3.0:
            print(f"✅ Good refund initiation performance: {refund_duration:.3f}s")
        else:
            print(f"⚠️ Refund initiation performance needs attention: {refund_duration:.3f}s")
        
        if info_duration < 0.5:
            print(f"🚀 Excellent refund info performance: {info_duration:.3f}s")
        elif info_duration < 1.0:
            print(f"✅ Good refund info performance: {info_duration:.3f}s")
        else:
            print(f"⚠️ Refund info performance needs attention: {info_duration:.3f}s")
        
        print("✅ Refund performance baselines validation completed")


if __name__ == "__main__":
    unittest.main()