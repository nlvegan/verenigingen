"""
Mollie Payment Integration Boundary Testing
===========================================

Comprehensive testing of Mollie payment gateway integration boundaries
for the Verenigingen association management system.

Critical business processes tested:
- Subscription lifecycle management
- Webhook security and processing
- Payment reconciliation workflows
- Error handling and recovery
- Member payment history tracking

@author Verenigingen Development Team
@version 1.0.0
"""

import hashlib
import hmac
import json
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
import requests_mock
from frappe.utils import add_months, flt, now_datetime, nowdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


@unittest.skip(
    "Unimplemented feature: MolliePaymentService has no create_subscription/"
    "update_subscription_amount/cancel_subscription methods (only create_payment/"
    "get_payment/process_webhook/create_refund exist). These tests assert a "
    "subscription-management contract that does not exist in production. "
    "Re-enable when subscription lifecycle is implemented on the service."
)
class TestMollieSubscriptionLifecycle(EnhancedTestCase):
    """
    Test complete Mollie subscription lifecycle for recurring membership dues

    Priority 1: Core payment processing workflows
    """

    def setUp(self):
        """Set up Mollie integration test environment"""
        super().setUp()

        # Create test Mollie settings
        self.mollie_settings = self.create_test_mollie_settings()

        # Create test member with complete setup
        self.test_member = self.create_test_member(
            first_name="Mollie", last_name="Integration Test", email="mollie.test@verenigingen.nl"
        )

    def create_test_mollie_settings(self):
        """Create realistic Mollie settings for testing"""
        # Check if settings already exist. frappe.db.exists(dt, dt) is
        # unconditionally truthy for a Single (#889); check whether it has
        # actually been saved instead.
        existing = frappe.db.get_singles_dict("Mollie Settings")
        if existing:
            settings = frappe.get_doc("Mollie Settings", "Mollie Settings")
        else:
            settings = frappe.new_doc("Mollie Settings")
            settings.name = "Mollie Settings"

        settings.update(
            {
                "api_key": "test_mollie_api_key_12345",
                "webhook_url": "https://dev.veganisme.net/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook",
                "enabled": 1,
                "test_mode": 1,
                "default_currency": "EUR",
            }
        )

        if existing:
            settings.save()
        else:
            settings.insert()
        return settings

    def test_member_subscription_creation_complete_workflow(self):
        """
        Test Priority 1: Complete subscription creation workflow

        This is the core workflow for recurring membership payments.
        """
        with requests_mock.Mocker() as m:
            # Mock Mollie customer creation API call
            m.post(
                "https://api.mollie.com/v2/customers",
                json={
                    "id": "cst_test_member_12345",
                    "name": self.test_member.full_name,
                    "email": self.test_member.email,
                    "metadata": {"member_id": self.test_member.name},
                },
            )

            # Mock Mollie subscription creation API call
            m.post(
                "https://api.mollie.com/v2/customers/cst_test_member_12345/subscriptions",
                json={
                    "id": "sub_test_subscription_67890",
                    "status": "active",
                    "amount": {"value": "25.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": f"Membership dues for {self.test_member.full_name}",
                    "method": "directdebit",
                    "nextPaymentDate": "2024-12-01",
                    "createdAt": "2024-11-01T10:00:00+00:00",
                },
            )

            # Test subscription creation
            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

            service = MolliePaymentService()
            result = service.create_subscription(
                member=self.test_member,
                amount=25.00,
                interval="1 month",
                description="Monthly membership dues",
            )

            # Verify subscription creation success
            self.assertTrue(result["success"])
            self.assertEqual(result["mollie_customer_id"], "cst_test_member_12345")
            self.assertEqual(result["subscription_id"], "sub_test_subscription_67890")

            # Verify member record updated with Mollie information
            self.test_member.reload()
            self.assertEqual(self.test_member.mollie_customer_id, "cst_test_member_12345")
            self.assertEqual(self.test_member.mollie_subscription_id, "sub_test_subscription_67890")
            self.assertEqual(self.test_member.subscription_status, "active")
            self.assertEqual(self.test_member.next_payment_date, "2024-12-01")

    def test_subscription_modification_and_amount_changes(self):
        """
        Test subscription modification for dues changes
        """
        # Set up existing subscription
        self.test_member.mollie_customer_id = "cst_existing_customer"
        self.test_member.mollie_subscription_id = "sub_existing_subscription"
        self.test_member.save()

        with requests_mock.Mocker() as m:
            # Mock subscription update API call
            m.patch(
                "https://api.mollie.com/v2/customers/cst_existing_customer/subscriptions/sub_existing_subscription",
                json={
                    "id": "sub_existing_subscription",
                    "status": "active",
                    "amount": {"value": "30.00", "currency": "EUR"},
                    "interval": "1 month",
                },
            )

            # Update subscription amount
            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

            service = MolliePaymentService()
            result = service.update_subscription_amount(self.test_member, 30.00)

            # Verify update success
            self.assertTrue(result["success"])
            self.assertEqual(result["new_amount"], 30.00)

    def test_subscription_cancellation_workflow(self):
        """
        Test subscription cancellation when member terminates
        """
        # Set up active subscription
        self.test_member.mollie_subscription_id = "sub_to_cancel"
        self.test_member.subscription_status = "active"
        self.test_member.save()

        with requests_mock.Mocker() as m:
            # Mock subscription cancellation API call
            m.delete(
                "https://api.mollie.com/v2/customers/cst_test/subscriptions/sub_to_cancel",
                json={"id": "sub_to_cancel", "status": "canceled"},
            )

            # Cancel subscription
            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

            service = MolliePaymentService()
            result = service.cancel_subscription(self.test_member)

            # Verify cancellation
            self.assertTrue(result["success"])

            # Verify member status updated
            self.test_member.reload()
            self.assertEqual(self.test_member.subscription_status, "Canceled")


@unittest.skip(
    "Tests a non-existent webhook contract: mollie_subscription_webhook returns a "
    "{'status': 'processed'|'ignored', ...} envelope (no 'success'/'payment_id'/"
    "'payment_failed'/'already_processed' keys); and webhook_security has no "
    "verify_mollie_signature/validate_mollie_webhook helpers. Rewrite against the real "
    "mollie_subscription_webhook envelope + webhook_validator.validate_mollie_webhook "
    "if this coverage is still wanted."
)
class TestMollieWebhookProcessing(EnhancedTestCase):
    """
    Test Mollie webhook processing and security

    Priority 1: Critical for payment reconciliation
    """

    def setUp(self):
        """Set up webhook testing environment"""
        super().setUp()

        self.test_member = self.create_test_member()
        self.test_member.mollie_subscription_id = "sub_webhook_test"
        self.test_member.save()

        # Create unpaid invoice for reconciliation testing
        self.test_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer, grand_total=25.00, submit=True
        )

    def test_successful_payment_webhook_processing(self):
        """
        Test webhook processing for successful payments

        Critical workflow: Payment → Payment Entry → Invoice Reconciliation
        """
        # Prepare webhook payload
        webhook_payload = {
            "id": "tr_test_payment_success",
            "status": "paid",
            "amount": {"value": "25.00", "currency": "EUR"},
            "paidAt": "2024-11-01T14:30:00+00:00",
            "method": "directdebit",
            "subscriptionId": "sub_webhook_test",
            "metadata": {"member_id": self.test_member.name, "invoice_id": self.test_invoice.name},
            "description": f"Membership dues for {self.test_member.full_name}",
        }

        with requests_mock.Mocker() as m:
            # Mock Mollie payment verification API call
            m.get("https://api.mollie.com/v2/payments/tr_test_payment_success", json=webhook_payload)

            # Process webhook
            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

            result = mollie_subscription_webhook()

            # Verify webhook processing success
            self.assertTrue(result["success"])
            self.assertEqual(result["payment_id"], "tr_test_payment_success")

            # Verify Payment Entry created
            payment_entries = frappe.get_all(
                "Payment Entry",
                filters={"custom_mollie_payment_id": "tr_test_payment_success"},
                fields=["name", "paid_amount", "payment_type", "party"],
            )
            self.assertEqual(len(payment_entries), 1)

            payment_entry = payment_entries[0]
            self.assertEqual(float(payment_entry.paid_amount), 25.00)
            self.assertEqual(payment_entry.payment_type, "Receive")
            self.assertEqual(payment_entry.party, self.test_member.customer)

            # Verify invoice reconciliation
            self.test_invoice.reload()
            self.assertEqual(self.test_invoice.status, "Paid")
            self.assertEqual(self.test_invoice.outstanding_amount, 0)

            # Verify Member Payment History updated
            payment_history = frappe.get_all(
                "Member Payment History",
                filters={"member": self.test_member.name, "mollie_payment_id": "tr_test_payment_success"},
                fields=["status", "amount", "payment_date"],
            )
            self.assertEqual(len(payment_history), 1)
            self.assertEqual(payment_history[0].status, "Completed")

    def test_failed_payment_webhook_processing(self):
        """
        Test webhook processing for failed payments

        Critical for member notification and retry logic
        """
        webhook_payload = {
            "id": "tr_test_payment_failed",
            "status": "failed",
            "failedAt": "2024-11-01T14:30:00+00:00",
            "subscriptionId": "sub_webhook_test",
            "failureReason": "insufficient_funds",
            "amount": {"value": "25.00", "currency": "EUR"},
            "metadata": {"member_id": self.test_member.name},
        }

        with requests_mock.Mocker() as m:
            # Mock Mollie payment verification
            m.get("https://api.mollie.com/v2/payments/tr_test_payment_failed", json=webhook_payload)

            # Process failed payment webhook
            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

            result = mollie_subscription_webhook()

            # Verify failed payment handling
            self.assertTrue(result["success"])
            self.assertTrue(result["payment_failed"])
            self.assertEqual(result["failure_reason"], "insufficient_funds")

            # Verify Member Payment History updated with failure
            payment_history = frappe.get_all(
                "Member Payment History",
                filters={"member": self.test_member.name, "mollie_payment_id": "tr_test_payment_failed"},
                fields=["status", "failure_reason"],
            )
            self.assertEqual(len(payment_history), 1)
            self.assertEqual(payment_history[0].status, "Failed")
            self.assertEqual(payment_history[0].failure_reason, "insufficient_funds")

    def test_webhook_signature_verification(self):
        """
        Test webhook signature verification for security

        Critical security boundary - prevents webhook spoofing
        """
        webhook_payload = {"id": "tr_security_test", "status": "paid"}
        webhook_body = json.dumps(webhook_payload)

        # Generate valid signature
        secret = "webhook_secret_key"
        signature = hmac.new(secret.encode("utf-8"), webhook_body.encode("utf-8"), hashlib.sha256).hexdigest()

        # Test with valid signature
        with patch("verenigingen.utils.webhook_security.verify_mollie_signature") as mock_verify:
            mock_verify.return_value = True

            from verenigingen.utils.webhook_security import validate_mollie_webhook

            result = validate_mollie_webhook(webhook_body, signature)

            self.assertTrue(result["valid"])
            mock_verify.assert_called_once()

        # Test with invalid signature
        with patch("verenigingen.utils.webhook_security.verify_mollie_signature") as mock_verify:
            mock_verify.return_value = False

            result = validate_mollie_webhook(webhook_body, "invalid_signature")

            self.assertFalse(result["valid"])
            self.assertIn("signature_mismatch", result["error"])

    def test_duplicate_webhook_prevention(self):
        """
        Test prevention of duplicate webhook processing

        Prevents double-payment scenarios
        """
        webhook_payload = {"id": "tr_duplicate_test", "status": "paid", "subscriptionId": "sub_webhook_test"}

        # Process webhook first time
        with requests_mock.Mocker() as m:
            m.get("https://api.mollie.com/v2/payments/tr_duplicate_test", json=webhook_payload)

            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

            result1 = mollie_subscription_webhook()
            self.assertTrue(result1["success"])

            # Process same webhook again
            result2 = mollie_subscription_webhook()
            self.assertFalse(result2["success"])
            self.assertIn("already_processed", result2["error"])

            # Verify only one Payment Entry created
            payment_entries = frappe.get_all(
                "Payment Entry", filters={"custom_mollie_payment_id": "tr_duplicate_test"}
            )
            self.assertEqual(len(payment_entries), 1)


@unittest.skip(
    "Unimplemented feature: chargeback webhook handling does not exist. No "
    "mollie_chargeback_webhook in payment_gateways, no "
    "verenigingen.utils.chargeback_notifications module, and no Member.chargeback_count "
    "column. Re-enable when chargeback processing is implemented."
)
class TestMollieChargebackHandling(EnhancedTestCase):
    """
    Test Mollie chargeback webhook processing and recovery

    Priority 1: Critical for financial protection and dispute management
    """

    def setUp(self):
        """Set up chargeback testing environment"""
        super().setUp()

        # Create member with successful payment history
        self.test_member = self.create_test_member(
            first_name="Chargeback", last_name="Test Member", email="chargeback.test@verenigingen.nl"
        )

        # Create paid invoice that will be subject to chargeback
        self.paid_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer, grand_total=50.00, submit=True
        )

        # Create payment entry for the invoice. The invoice link lives in the
        # Payment Entry "references" child table (reference_doctype/reference_name
        # are not top-level Payment Entry fields).
        self.payment_entry = self.create_test_payment_entry(
            payment_type="Receive",
            party=self.test_member.customer,
            paid_amount=50.00,
            references=[
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": self.paid_invoice.name,
                    "allocated_amount": 50.00,
                }
            ],
        )

        # Mark invoice as paid
        self.paid_invoice.reload()
        self.paid_invoice.db_set("status", "Paid")
        self.paid_invoice.db_set("outstanding_amount", 0)

    def test_chargeback_webhook_processing_and_reversal(self):
        """
        Test chargeback webhook processing with payment reversal

        Critical workflow: Chargeback → Payment Reversal → Invoice Status Update → Member Notification
        """
        chargeback_payload = {
            "id": "chb_test_chargeback_12345",
            "paymentId": "tr_original_payment_67890",
            "amount": {"value": "50.00", "currency": "EUR"},
            "reason": "duplicate",
            "reasonCode": "duplicate",
            "reversedAt": "2024-11-02T10:30:00+00:00",
            "createdAt": "2024-11-02T10:00:00+00:00",
            "metadata": {"member_id": self.test_member.name, "invoice_id": self.paid_invoice.name},
        }

        with requests_mock.Mocker() as m:
            # Mock Mollie chargeback verification API
            m.get(
                "https://api.mollie.com/v2/payments/tr_original_payment_67890/chargebacks/chb_test_chargeback_12345",
                json=chargeback_payload,
            )

            # Process chargeback webhook
            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_chargeback_webhook

            result = mollie_chargeback_webhook(chargeback_payload)

            # Verify chargeback processing success
            self.assertTrue(result["success"])
            self.assertEqual(result["chargeback_id"], "chb_test_chargeback_12345")
            self.assertEqual(result["action"], "payment_reversed")

            # Verify Payment Entry reversal created
            reversal_entries = frappe.get_all(
                "Payment Entry",
                filters={
                    "custom_mollie_chargeback_id": "chb_test_chargeback_12345",
                    "payment_type": "Pay",  # Reversal entry
                },
                fields=["name", "paid_amount", "party"],
            )
            self.assertEqual(len(reversal_entries), 1)
            reversal = reversal_entries[0]
            self.assertEqual(float(reversal.paid_amount), 50.00)
            self.assertEqual(reversal.party, self.test_member.customer)

            # Verify invoice status reverted to unpaid
            self.paid_invoice.reload()
            self.assertEqual(self.paid_invoice.status, "Unpaid")
            self.assertEqual(self.paid_invoice.outstanding_amount, 50.00)

            # Verify Member Payment History updated with chargeback
            payment_history = frappe.get_all(
                "Member Payment History",
                filters={
                    "member": self.test_member.name,
                    "mollie_chargeback_id": "chb_test_chargeback_12345",
                },
                fields=["status", "chargeback_reason", "amount"],
            )
            self.assertEqual(len(payment_history), 1)
            history = payment_history[0]
            self.assertEqual(history.status, "Chargeback")
            self.assertEqual(history.chargeback_reason, "duplicate")

    def test_chargeback_reason_categorization_and_response(self):
        """
        Test different chargeback reasons and appropriate responses

        Different chargeback reasons require different handling strategies
        """
        chargeback_scenarios = [
            {
                "reason": "fraud",
                "reasonCode": "fraud",
                "expected_action": "fraud_protection",
                "member_action": "suspend_account",
            },
            {
                "reason": "duplicate",
                "reasonCode": "duplicate",
                "expected_action": "investigate_duplicate",
                "member_action": "review_billing",
            },
            {
                "reason": "unrecognized",
                "reasonCode": "unrecognized",
                "expected_action": "member_contact",
                "member_action": "send_notification",
            },
            {
                "reason": "subscription",
                "reasonCode": "subscription",
                "expected_action": "cancel_subscription",
                "member_action": "update_subscription_status",
            },
        ]

        for scenario in chargeback_scenarios:
            with self.subTest(reason=scenario["reason"]):
                chargeback_payload = {
                    "id": f"chb_{scenario['reason']}_test",
                    "paymentId": "tr_test_payment",
                    "amount": {"value": "25.00", "currency": "EUR"},
                    "reason": scenario["reason"],
                    "reasonCode": scenario["reasonCode"],
                    "metadata": {"member_id": self.test_member.name},
                }

                with requests_mock.Mocker() as m:
                    m.get(
                        f"https://api.mollie.com/v2/payments/tr_test_payment/chargebacks/chb_{scenario['reason']}_test",
                        json=chargeback_payload,
                    )

                    # Process chargeback
                    from verenigingen.verenigingen_payments.utils.payment_gateways import (
                        mollie_chargeback_webhook,
                    )

                    result = mollie_chargeback_webhook(chargeback_payload)

                    # Verify appropriate action taken
                    self.assertTrue(result["success"])
                    self.assertEqual(result["chargeback_action"], scenario["expected_action"])
                    self.assertEqual(result["member_action"], scenario["member_action"])

    def test_chargeback_dispute_workflow_initiation(self):
        """
        Test initiation of dispute workflow for contestable chargebacks

        Some chargebacks can be disputed with evidence
        """
        contestable_chargeback = {
            "id": "chb_contestable_12345",
            "paymentId": "tr_dispute_payment",
            "amount": {"value": "75.00", "currency": "EUR"},
            "reason": "unrecognized",
            "reasonCode": "unrecognized",
            "isEligibleForDispute": True,
            "disputeDeadline": "2024-11-16T23:59:59+00:00",
            "metadata": {
                "member_id": self.test_member.name,
                "service_provided": True,
                "has_member_confirmation": True,
            },
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.mollie.com/v2/payments/tr_dispute_payment/chargebacks/chb_contestable_12345",
                json=contestable_chargeback,
            )

            # Process contestable chargeback
            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_chargeback_webhook

            result = mollie_chargeback_webhook(contestable_chargeback)

            # Verify dispute workflow initiated
            self.assertTrue(result["success"])
            self.assertTrue(result["dispute_eligible"])
            self.assertIsNotNone(result["dispute_deadline"])

            # Verify Chargeback Dispute record created
            dispute_records = frappe.get_all(
                "Chargeback Dispute",
                filters={"mollie_chargeback_id": "chb_contestable_12345"},
                fields=["status", "dispute_deadline", "evidence_required"],
            )
            self.assertEqual(len(dispute_records), 1)
            dispute = dispute_records[0]
            self.assertEqual(dispute.status, "Evidence Collection")
            self.assertIsNotNone(dispute.dispute_deadline)

    def test_chargeback_notification_and_escalation(self):
        """
        Test chargeback notification system and escalation procedures

        Critical for timely response to chargebacks
        """
        high_value_chargeback = {
            "id": "chb_high_value_999",
            "paymentId": "tr_high_value_payment",
            "amount": {"value": "500.00", "currency": "EUR"},
            "reason": "fraud",
            "reasonCode": "fraud",
            "metadata": {"member_id": self.test_member.name},
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.mollie.com/v2/payments/tr_high_value_payment/chargebacks/chb_high_value_999",
                json=high_value_chargeback,
            )

            # Mock email notification system
            with patch("verenigingen.utils.chargeback_notifications.send_chargeback_alert") as mock_email:
                mock_email.return_value = {"success": True, "notification_sent": True}

                # Process high-value chargeback
                from verenigingen.verenigingen_payments.utils.payment_gateways import (
                    mollie_chargeback_webhook,
                )

                result = mollie_chargeback_webhook(high_value_chargeback)

                # Verify escalation triggered
                self.assertTrue(result["success"])
                self.assertTrue(result["escalated"])
                self.assertEqual(result["escalation_reason"], "high_value_fraud")

                # Verify notification sent
                mock_email.assert_called_once()
                call_args = mock_email.call_args[0]
                self.assertIn("high_value", call_args[0])  # Alert type
                self.assertEqual(call_args[1], 500.00)  # Amount

    def test_chargeback_prevention_member_flagging(self):
        """
        Test member flagging system for chargeback prevention

        Members with multiple chargebacks need special handling
        """
        # Simulate member with previous chargeback history
        self.test_member.db_set("chargeback_count", 2)
        self.test_member.db_set("chargeback_risk_level", "Medium")

        repeat_chargeback = {
            "id": "chb_repeat_offender_123",
            "paymentId": "tr_repeat_payment",
            "amount": {"value": "30.00", "currency": "EUR"},
            "reason": "fraud",
            "reasonCode": "fraud",
            "metadata": {"member_id": self.test_member.name},
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.mollie.com/v2/payments/tr_repeat_payment/chargebacks/chb_repeat_offender_123",
                json=repeat_chargeback,
            )

            # Process repeat chargeback
            from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_chargeback_webhook

            result = mollie_chargeback_webhook(repeat_chargeback)

            # Verify member risk level updated
            self.assertTrue(result["success"])
            self.assertTrue(result["member_flagged"])
            self.assertEqual(result["new_risk_level"], "High")

            # Verify member record updated
            self.test_member.reload()
            self.assertEqual(self.test_member.chargeback_count, 3)
            self.assertEqual(self.test_member.chargeback_risk_level, "High")
            self.assertTrue(self.test_member.payment_review_required)


class TestMollieErrorHandlingAndRecovery(EnhancedTestCase):
    """
    Test Mollie error scenarios and recovery mechanisms

    Priority 2: Error resilience and business continuity
    """

    @unittest.skip(
        "Unimplemented feature: MolliePaymentService.create_subscription does not "
        "exist, and the asserted error envelope (error_type/retry_recommended) is not "
        "produced anywhere. Re-enable when subscription creation + structured retry "
        "handling are implemented."
    )
    def test_mollie_api_timeout_handling(self):
        """
        Test handling of Mollie API timeouts
        """
        with requests_mock.Mocker() as m:
            # Mock API timeout
            from requests.exceptions import Timeout

            m.post("https://api.mollie.com/v2/customers", exc=Timeout)

            member = self.create_test_member()

            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

            service = MolliePaymentService()
            result = service.create_subscription(member, 25.00, "1 month")

            # Verify timeout handled gracefully
            self.assertFalse(result["success"])
            self.assertEqual(result["error_type"], "timeout")
            self.assertTrue(result["retry_recommended"])

    @unittest.skip(
        "Unimplemented feature: MolliePaymentService.create_subscription does not "
        "exist, and the asserted error envelope (error_type/retry_after) is not "
        "produced anywhere. Re-enable when subscription creation + structured retry "
        "handling are implemented."
    )
    def test_mollie_api_rate_limiting(self):
        """
        Test handling of Mollie API rate limiting
        """
        with requests_mock.Mocker() as m:
            # Mock rate limit response
            m.post("https://api.mollie.com/v2/customers", status_code=429, headers={"Retry-After": "60"})

            member = self.create_test_member()

            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

            service = MolliePaymentService()
            result = service.create_subscription(member, 25.00, "1 month")

            # Verify rate limiting handled
            self.assertFalse(result["success"])
            self.assertEqual(result["error_type"], "rate_limited")
            self.assertEqual(result["retry_after"], 60)

    def test_invalid_webhook_payload_handling(self):
        """
        Test handling of malformed webhook payloads
        """
        malformed_payloads = [
            {},  # Empty payload
            {"id": ""},  # Missing required fields
            {"id": "tr_test", "amount": "invalid"},  # Invalid amount format
            {"id": "tr_test", "status": "unknown_status"},  # Invalid status
        ]

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                from verenigingen.verenigingen_payments.utils.payment_gateways import (
                    mollie_subscription_webhook,
                )

                result = mollie_subscription_webhook()

                # The webhook returns a standardized {"status", "message"/"reason"}
                # envelope (no "success"/"error" keys). A malformed/unauthenticated
                # payload must not be processed successfully.
                self.assertNotEqual(result.get("status"), "processed")
                self.assertIn(result.get("status"), {"error", "ignored", "already_processed"})

    # Helper methods for Mollie integration tests
    def create_test_payment_entry(self, payment_type="Receive", **kwargs):
        """Create test payment entry for chargeback testing"""
        payment_entry = frappe.new_doc("Payment Entry")

        defaults = {
            "payment_type": payment_type,
            "posting_date": today(),
            "company": "Ned Ver Vegan",
            "mode_of_payment": "Bank Transfer",
            "paid_amount": 25.00,
            "received_amount": 25.00,
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
        }
        defaults.update(kwargs)

        payment_entry.update(defaults)

        # Add reference if provided
        if defaults.get("reference_doctype") and defaults.get("reference_name"):
            payment_entry.append(
                "references",
                {
                    "reference_doctype": defaults["reference_doctype"],
                    "reference_name": defaults["reference_name"],
                    "allocated_amount": defaults.get("paid_amount", 25.00),
                },
            )

        payment_entry.insert()
        payment_entry.submit()
        return payment_entry

    def create_test_mollie_payment_data(self, status="paid", amount="25.00"):
        """Create standardized Mollie payment test data"""
        return {
            "id": f"tr_test_{status}_{frappe.utils.random_string(8)}",
            "status": status,
            "amount": {"value": amount, "currency": "EUR"},
            "method": "directdebit",
            "paidAt": now_datetime().isoformat() if status == "paid" else None,
            "failedAt": now_datetime().isoformat() if status == "failed" else None,
            "subscriptionId": "sub_test_subscription",
            "metadata": {"member_id": self.test_member.name},
        }
