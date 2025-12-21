"""
Payment Processors Test Suite
============================

Comprehensive tests for the new payment-agnostic processor architecture.
Tests the DonationPaymentProcessor and MembershipPaymentProcessor to ensure
proper payment handling without donation-specific hardcoding.

Key Test Areas:
- Payment processing workflows (Payment Entry creation, status updates)
- Recurring vs one-time payment detection
- Idempotency checking and duplicate prevention
- PaymentEntryFactory integration
- Error handling and edge cases
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.utils import flt, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.payment_processors import (
    DonationPaymentProcessor,
    MembershipPaymentProcessor,
    PaymentProcessingResult,
    PaymentProcessorFactory,
)


class TestDonationPaymentProcessor(EnhancedTestCase):
    """
    Test DonationPaymentProcessor to prevent regressions and validate
    the complete donation payment workflow.
    """

    def reset_donation_to_draft(self, donation):
        """Reset donation to draft state for testing (factory force-submits in tests)"""
        donation.reload()
        if donation.docstatus == 1:
            donation.cancel()
            frappe.db.set_value("Donation", donation.name, "docstatus", 0)
            frappe.db.set_value("Donation", donation.name, "payment_id", None)
            donation.reload()
        return donation

    def setUp(self):
        super().setUp()
        self.processor = DonationPaymentProcessor()

        # Create test data using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Donation", last_name="Test", email="donation.test@example.com"
        )

        self.test_donation = self.create_test_donation(
            donor_email=self.test_member.email, amount=100.0, payment_id="test_donation_payment_123", paid=0
        )
        self.test_donation = self.reset_donation_to_draft(self.test_donation)

        self.payment_context = PaymentContext(
            payment_type="donation", target_doctype="Donation", target_name=self.test_donation.name
        )

    def test_supports_context(self):
        """Test that processor correctly identifies donation contexts"""
        # Should support donation context
        self.assertTrue(self.processor.supports_context(self.payment_context))

        # Should not support membership context
        membership_context = PaymentContext("membership", "Member", "test-member")
        self.assertFalse(self.processor.supports_context(membership_context))

    def test_determine_recurring_status_explicit_override(self):
        """Test Priority 1: Explicit metadata override"""
        # Test explicit false override
        mollie_data = {
            "payment_id": "test_123",
            "amount": "100.00",
            "metadata": {"subscription_setup": "false"},
        }

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertFalse(result, "Explicit subscription_setup=false should return False")

        # Test explicit true override
        mollie_data["metadata"]["subscription_setup"] = "true"
        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "Explicit subscription_setup=true should return True")

    def test_determine_recurring_status_subscription_id(self):
        """Test Priority 2: Mollie subscription ID"""
        mollie_data = {"payment_id": "test_123", "amount": "100.00", "subscription_id": "sub_abc123"}

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "Presence of subscription_id should indicate recurring")

    def test_determine_recurring_status_sepa_mandate(self):
        """Test Priority 3: SEPA mandate + customer"""
        mollie_data = {
            "payment_id": "test_123",
            "amount": "100.00",
            "mandate_id": "mdt_abc123",
            "customer_id": "cst_xyz789",
        }

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "SEPA mandate + customer should indicate recurring")

        # Should be false with only mandate (no customer)
        mollie_data.pop("customer_id")
        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertFalse(result, "Mandate without customer should not indicate recurring")

    def test_determine_recurring_status_metadata_indicators(self):
        """Test Priority 4: Other metadata indicators"""
        # Test subscription interval
        mollie_data = {
            "payment_id": "test_123",
            "amount": "100.00",
            "metadata": {"subscription_interval": "1 month"},
        }

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "subscription_interval metadata should indicate recurring")

        # Test subscription amount
        mollie_data["metadata"] = {"subscription_amount": "25.00"}
        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "subscription_amount metadata should indicate recurring")

    def test_determine_recurring_status_legacy_json(self):
        """Test Priority 5: Legacy JSON description parsing"""
        mollie_data = {
            "payment_id": "test_123",
            "amount": "100.00",
            "description": '{"type": "recurring", "donor": "test-donor"}',
        }

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "Legacy JSON description with type=recurring should indicate recurring")

        # Test malformed JSON (should not crash)
        mollie_data["description"] = '{"type": "recurring"'  # Invalid JSON
        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertFalse(result, "Malformed JSON should default to one-time")

    def test_determine_recurring_status_existing_status(self):
        """Test Priority 6: Existing donation status preservation"""
        # Set donation to recurring status
        self.test_donation.status = "Recurring"

        mollie_data = {"payment_id": "test_123", "amount": "100.00"}

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertTrue(result, "Existing Recurring status should be preserved")

    def test_determine_recurring_status_default_one_time(self):
        """Test default behavior: one-time when no indicators found"""
        mollie_data = {"payment_id": "test_123", "amount": "100.00"}

        result = self.processor._determine_recurring_status(self.test_donation, mollie_data)
        self.assertFalse(result, "Should default to one-time when no recurring indicators found")

    def test_process_successful_payment_one_time(self):
        """Test complete one-time donation payment processing"""
        mollie_data = {
            "payment_id": "test_donation_one_time",
            "amount": "50.00",
            "method": "Bank Transfer",  # Use a standard ERPNext payment method
            "metadata": {"subscription_setup": "false"},
            "paid_at": "2025-01-15T10:30:00+00:00",
            "currency": "EUR",
        }

        # Mock Bank Transaction creation (returns None since test donor has no customer)
        with patch.object(
            self.processor, "_create_bank_transaction_for_donation", return_value=None
        ) as mock_bt_creator:
            # Create real Payment Entry instead of mocking
            with patch.object(self.processor.payment_factory, "create_payment_entry") as mock_factory:
                # Create a real Payment Entry using Enhanced Test Factory
                payment_entry = self.create_test_payment_entry(
                    paid_amount=50.0,
                    reference_no="test_donation_one_time",
                    party=self.test_member.customer
                    if hasattr(self.test_member, "customer") and self.test_member.customer
                    else None,
                )
                mock_factory.return_value = payment_entry

                result = self.processor.process_successful_payment(self.payment_context, Mock(), mollie_data)

                # Verify result
                self.assertTrue(result.success)
                # Message should indicate processing occurred
                self.assertTrue(
                    "successfully" in result.message.lower() or "processed" in result.message.lower(),
                    f"Expected success message, got: {result.message}",
                )
                self.assertEqual(result.data["amount"], "50.00")

                # Verify donation was updated correctly
                updated_donation = frappe.get_doc("Donation", self.test_donation.name)
                self.assertEqual(updated_donation.paid, 1)
                self.assertEqual(updated_donation.status, "One-time")
                self.assertEqual(updated_donation.payment_id, "test_donation_one_time")

                # Verify payment history was added
                self.assertTrue(len(updated_donation.payments) > 0)
                payment_record = updated_donation.payments[-1]
                self.assertEqual(payment_record.mollie_payment_id, "test_donation_one_time")
                self.assertEqual(payment_record.payment_status, "Paid")

    def test_process_successful_payment_recurring(self):
        """Test complete recurring donation payment processing"""
        # Create a fresh donation for this test
        recurring_donation = self.create_test_donation(
            donor_email="recurring.test@example.com", amount=25.0, paid=0
        )
        recurring_donation = self.reset_donation_to_draft(recurring_donation)

        recurring_context = PaymentContext(
            payment_type="donation", target_doctype="Donation", target_name=recurring_donation.name
        )

        mollie_data = {
            "payment_id": "test_donation_recurring",
            "amount": "25.00",
            "method": "Bank Transfer",  # Use a standard ERPNext payment method
            "subscription_id": "sub_recurring_test",
            "paid_at": "2025-01-15T10:30:00+00:00",
            "currency": "EUR",
        }

        # Mock Bank Transaction creation
        with patch.object(
            self.processor, "_create_bank_transaction_for_donation", return_value=None
        ) as mock_bt_creator:
            # Create real Payment Entry
            with patch.object(self.processor.payment_factory, "create_payment_entry") as mock_factory:
                payment_entry = self.create_test_payment_entry(
                    paid_amount=25.0,
                    reference_no="test_donation_recurring",
                    party=self.test_member.customer
                    if hasattr(self.test_member, "customer") and self.test_member.customer
                    else None,
                )
                mock_factory.return_value = payment_entry

                result = self.processor.process_successful_payment(recurring_context, Mock(), mollie_data)

                # Verify result
                self.assertTrue(result.success)

                # Verify donation was marked as recurring
                updated_donation = frappe.get_doc("Donation", recurring_donation.name)
                self.assertEqual(updated_donation.paid, 1)
                self.assertEqual(updated_donation.status, "Recurring")

    def test_idempotency_checking(self):
        """Test idempotency prevents duplicate processing"""
        # Create a fresh donation for this test (without payment_id, and unpaid)
        fresh_donation = self.create_test_donation(
            donor_email="idempotency.test@example.com", amount=75.0, paid=0
        )
        fresh_donation = self.reset_donation_to_draft(fresh_donation)

        fresh_context = PaymentContext(
            payment_type="donation", target_doctype="Donation", target_name=fresh_donation.name
        )

        payment_id = "test_idempotency_123"

        # First processing - should go through
        mollie_data = {
            "payment_id": payment_id,
            "amount": "75.00",
            "metadata": {"subscription_setup": "false"},
            "paid_at": "2025-01-15T10:30:00+00:00",
            "currency": "EUR",
        }

        # Mock Bank Transaction creation
        with patch.object(
            self.processor, "_create_bank_transaction_for_donation", return_value=None
        ) as mock_bt_creator:
            # Create real Payment Entry
            with patch.object(self.processor.payment_factory, "create_payment_entry") as mock_factory:
                payment_entry = self.create_test_payment_entry(
                    paid_amount=75.0,
                    reference_no="test_idempotency_123",
                )
                mock_factory.return_value = payment_entry

                # First call
                result1 = self.processor.process_successful_payment(fresh_context, Mock(), mollie_data)
                self.assertTrue(result1.success)

                # Second call - should be idempotent
                result2 = self.processor.process_successful_payment(fresh_context, Mock(), mollie_data)

                # Should indicate already processed
                self.assertTrue(result2.success)
                self.assertIn("already processed", result2.message)

    def test_process_failed_payment(self):
        """Test failed payment processing"""
        mollie_data = {
            "payment_id": "test_failed_payment",
            "amount": "100.00",
            "method": "Bank Transfer",
            "paid_at": "2025-01-15T10:30:00+00:00",
            "currency": "EUR",
        }

        mock_payment_data = Mock()
        mock_payment_data.status = "failed"

        # No mocking needed - failed payments don't create Payment Entry or Bank Transaction
        result = self.processor.process_failed_payment(self.payment_context, mock_payment_data, mollie_data)

        # Verify result
        self.assertTrue(result.success)
        self.assertIn("Failed donation payment recorded", result.message)

        # Verify payment history was added
        updated_donation = frappe.get_doc("Donation", self.test_donation.name)
        self.assertTrue(len(updated_donation.payments) > 0)
        payment_record = updated_donation.payments[-1]
        self.assertEqual(payment_record.payment_status, "Cancelled")


class TestMembershipPaymentProcessor(EnhancedTestCase):
    """
    Test MembershipPaymentProcessor for membership-specific payment handling.
    """

    def setUp(self):
        super().setUp()
        self.processor = MembershipPaymentProcessor()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Membership", last_name="Test", email="membership.test@example.com"
        )

        self.payment_context = PaymentContext(
            payment_type="membership", target_doctype="Member", target_name=self.test_member.name
        )

    def test_supports_context(self):
        """Test that processor correctly identifies membership contexts"""
        self.assertTrue(self.processor.supports_context(self.payment_context))

        # Should not support donation context
        donation_context = PaymentContext("donation", "Donation", "test-donation")
        self.assertFalse(self.processor.supports_context(donation_context))

    def test_process_successful_payment(self):
        """Test membership payment processing"""
        mollie_data = {"payment_id": "test_membership_payment", "amount": "25.00", "method": "directdebit"}

        with patch.object(self.processor.payment_factory, "create_payment_entry") as mock_factory:
            mock_payment_entry = Mock()
            mock_payment_entry.name = "PE-MEMBER-001"
            mock_factory.return_value = mock_payment_entry

            result = self.processor.process_successful_payment(self.payment_context, Mock(), mollie_data)

            # Verify result
            self.assertTrue(result.success)
            self.assertIn("successfully", result.message)

            # Verify member payment history was updated
            updated_member = frappe.get_doc("Member", self.test_member.name)
            self.assertTrue(hasattr(updated_member, "payment_history"))


class TestPaymentProcessorFactory(EnhancedTestCase):
    """
    Test PaymentProcessorFactory for correct processor selection.
    """

    def setUp(self):
        super().setUp()
        self.factory = PaymentProcessorFactory()

    def test_get_processor_donation(self):
        """Test factory returns DonationPaymentProcessor for donations"""
        context = PaymentContext("donation", "Donation", "test-donation")
        processor = self.factory.get_processor(context)

        self.assertIsInstance(processor, DonationPaymentProcessor)

    def test_get_processor_membership(self):
        """Test factory returns MembershipPaymentProcessor for memberships"""
        context = PaymentContext("membership", "Member", "test-member")
        processor = self.factory.get_processor(context)

        self.assertIsInstance(processor, MembershipPaymentProcessor)

    def test_get_processor_unsupported(self):
        """Test factory returns None for unsupported payment types"""
        context = PaymentContext("unsupported", "Unknown", "test-unknown")
        processor = self.factory.get_processor(context)

        self.assertIsNone(processor)

    def test_register_processor(self):
        """Test custom processor registration"""

        # Create a mock custom processor
        class CustomProcessor:
            def supports_context(self, context):
                return context.payment_type == "custom"

        custom_processor = CustomProcessor()
        self.factory.register_processor(custom_processor)

        # Test that custom processor is found
        context = PaymentContext("custom", "Custom", "test-custom")
        processor = self.factory.get_processor(context)

        self.assertEqual(processor, custom_processor)


if __name__ == "__main__":
    unittest.main()
