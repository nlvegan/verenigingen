"""
Mollie Refund & Chargeback Integration Tests (Real API)

Tests webhook processing with real Mollie test API interactions.
This focuses on testing OUR webhook processor code, not Mollie's API.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)


class TestMollieRefundChargebackWebhookProcessing(EnhancedTestCase):
    """
    Test webhook processing for refunds and chargebacks.

    This test suite focuses on validating OUR webhook processor,
    not Mollie's API behavior. We test with realistic webhook payloads.
    """

    def setUp(self):
        super().setUp()
        self.webhook_processor = UnifiedWebhookWrapperService()

        # Create test data
        self.test_member = self.create_test_member(
            first_name="Webhook", last_name="Test", email="webhook.test@example.com"
        )

        # Prepare payment ID for donation
        self.test_payment_id = "tr_webhook_test_12345"

        # Create donation with payment_id set for lookup
        self.test_donation = self.create_test_donation(
            donor_email=self.test_member.email, amount=100.0, payment_id=self.test_payment_id
        )

        # Get proper accounts for the payment entry
        company = "Test Company"

        # Get receivable account (paid_from for Receive type)
        receivable_account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
        )

        # Get or create a leaf bank account (paid_to for Receive type)
        bank_account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        )

        if not bank_account:
            # Create a test bank account if none exists
            bank_group = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
            )
            if bank_group:
                bank_acc_doc = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": "Test Bank Account",
                        "parent_account": bank_group,
                        "company": company,
                        "account_type": "Bank",
                        "is_group": 0,
                    }
                )
                bank_acc_doc.insert(ignore_permissions=True)
                bank_account = bank_acc_doc.name

        # Create an original payment entry that our webhooks will reference
        self.original_payment = self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no=self.test_payment_id,
            custom_donation=self.test_donation.name,
            paid_from=receivable_account,
            paid_to=bank_account,
            submit=True,  # Must be submitted for reversals to work
        )

        # Add original payment to donation payment history
        # (this would normally be done by the webhook processor for the original payment)
        self.test_donation.reload()
        self.test_donation.append(
            "payments",
            {
                "payment_entry": self.original_payment.name,
                "amount": 100.0,
                "payment_date": frappe.utils.today(),
                "mollie_payment_id": self.test_payment_id,
                "payment_status": "Paid",  # Must be one of: Pending, Paid, Failed, Cancelled, Refunded
                "payment_method": "Mollie",
            },
        )
        self.test_donation.flags.ignore_validate_update_after_submit = True
        self.test_donation.save()
        frappe.db.commit()

    def test_refund_webhook_processing(self):
        """
        Test that refund webhook creates proper Payment Entry.

        This tests OUR webhook processor, not Mollie's refund creation.
        """
        # Build realistic refund webhook payload
        refund_data = {
            "id": "re_test_refund_001",
            "amount": {"value": "30.00", "currency": "EUR"},
            "status": "refunded",
            "createdAt": "2025-01-15T10:30:00+00:00",
        }

        # Process the refund webhook
        result = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data
        )

        # Validate webhook processing succeeded
        self.assertEqual(result["status"], "success", f"Webhook failed: {result.get('message')}")
        self.assertIn("refund_id", result)
        self.assertEqual(result["refund_id"], "re_test_refund_001")

        # Verify Payment Entry was created correctly
        refund_pe = frappe.get_all(
            "Payment Entry",
            filters={
                "payment_type": "Pay",
                "reference_no": f"{self.test_payment_id}_refund_re_test_refund_001",
                "docstatus": 1,
            },
            fields=["name", "paid_amount", "custom_reversal_type", "custom_original_payment_id"],
        )

        self.assertTrue(refund_pe, "Refund Payment Entry should be created")
        self.assertEqual(len(refund_pe), 1)

        pe = refund_pe[0]
        self.assertEqual(pe.paid_amount, 30.0)
        self.assertEqual(pe.custom_reversal_type, "Refund")
        self.assertEqual(pe.custom_original_payment_id, self.test_payment_id)

        # Verify payment history was updated (reload from database)
        donation = frappe.get_doc("Donation", self.test_donation.name)
        donation.reload()  # Ensure we have latest data from database

        # DEBUG: Print payment history details
        print(f"\n📊 Payment History Debug:")
        print(f"  Total payments: {len(donation.payments)}")
        for idx, p in enumerate(donation.payments):
            print(f"  Payment {idx + 1}: status={p.payment_status}, amount={p.amount}, PE={p.payment_entry}")

        refund_history = [p for p in donation.payments if p.payment_status == "Refunded"]
        self.assertTrue(
            refund_history,
            f"Donation payment history should include refund. Found {len(donation.payments)} total payments",
        )

        print("✅ Refund webhook processing test passed")

    def test_chargeback_webhook_processing(self):
        """
        Test that chargeback webhook creates proper Payment Entry.

        This tests OUR webhook processor, not bank-initiated chargebacks.
        """
        # Build realistic chargeback webhook payload
        chargeback_data = {
            "id": "chb_test_chargeback_001",
            "amount": {"value": "25.00", "currency": "EUR"},
            "reason": {"code": "duplicate", "description": "Duplicate transaction"},
            "createdAt": "2025-01-16T14:20:00+00:00",
        }

        # Process the chargeback webhook
        result = self.webhook_processor.process_chargeback_webhook(
            payment_id=self.test_payment_id, chargeback_data=chargeback_data
        )

        # Validate webhook processing succeeded
        self.assertEqual(result["status"], "success", f"Webhook failed: {result.get('message')}")
        self.assertIn("chargeback_id", result)
        self.assertEqual(result["chargeback_id"], "chb_test_chargeback_001")

        # Verify Payment Entry was created correctly
        chargeback_pe = frappe.get_all(
            "Payment Entry",
            filters={
                "payment_type": "Pay",
                "reference_no": f"{self.test_payment_id}_chargeback_chb_test_chargeback_001",
                "docstatus": 1,
            },
            fields=["name", "paid_amount", "custom_reversal_type", "custom_original_payment_id"],
        )

        self.assertTrue(chargeback_pe, "Chargeback Payment Entry should be created")
        self.assertEqual(len(chargeback_pe), 1)

        pe = chargeback_pe[0]
        self.assertEqual(pe.paid_amount, 25.0)
        self.assertEqual(pe.custom_reversal_type, "Chargeback")
        self.assertEqual(pe.custom_original_payment_id, self.test_payment_id)

        # Verify payment history was updated (reload from database)
        donation = frappe.get_doc("Donation", self.test_donation.name)
        donation.reload()  # Ensure we have latest data from database
        chargeback_history = [p for p in donation.payments if p.payment_status == "Chargeback"]
        self.assertTrue(chargeback_history, "Donation payment history should include chargeback")

        print("✅ Chargeback webhook processing test passed")

    def test_idempotency_prevents_duplicate_refunds(self):
        """Test that processing the same refund webhook twice doesn't create duplicates."""
        refund_data = {
            "id": "re_idempotency_test",
            "amount": {"value": "20.00", "currency": "EUR"},
            "status": "refunded",
        }

        # Process webhook first time
        result1 = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data
        )
        self.assertEqual(result1["status"], "success")

        # Process same webhook second time
        result2 = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data
        )

        # Should return success with idempotent flag
        self.assertEqual(result2["status"], "success")
        self.assertTrue(result2.get("idempotent"), "Second processing should be idempotent")

        # Verify only ONE Payment Entry exists
        refund_entries = frappe.get_all(
            "Payment Entry",
            filters={
                "payment_type": "Pay",
                "reference_no": f"{self.test_payment_id}_refund_re_idempotency_test",
                "docstatus": 1,
            },
        )
        self.assertEqual(len(refund_entries), 1, "Should only create one Payment Entry")

        print("✅ Idempotency test passed")

    def test_payment_history_idempotency(self):
        """
        Test that payment history child table prevents duplicate entries.

        This is a regression test for the bug where duplicate refund webhooks
        would re-add old refund entries to the payment history child table.
        """
        # Create first refund
        refund_data_1 = {
            "id": "re_history_test_001",
            "amount": {"value": "15.00", "currency": "EUR"},
            "status": "refunded",
        }

        result1 = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data_1
        )
        self.assertEqual(result1["status"], "success")

        # Get donation and check payment history
        donation = frappe.get_doc("Donation", self.test_donation.name)
        initial_payment_count = len(donation.payments)

        # Find the refund entry
        refund_entries_1 = [p for p in donation.payments if p.mollie_payment_id == "re_history_test_001"]
        self.assertEqual(len(refund_entries_1), 1, "Should have exactly one entry for first refund")

        print(f"\n📊 Initial payment history count: {initial_payment_count}")

        # Create second refund
        refund_data_2 = {
            "id": "re_history_test_002",
            "amount": {"value": "10.00", "currency": "EUR"},
            "status": "refunded",
        }

        result2 = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data_2
        )
        self.assertEqual(result2["status"], "success")

        # Reload donation and check payment history again
        donation.reload()

        print(f"📊 Payment history after second refund:")
        for idx, p in enumerate(donation.payments):
            print(
                f"  Entry {idx + 1}: PE={p.payment_entry}, amount={p.amount}, mollie_id={p.mollie_payment_id}"
            )

        # Verify we have exactly 2 refund entries (not duplicates of the first one)
        refund_entries_1_after = [
            p for p in donation.payments if p.mollie_payment_id == "re_history_test_001"
        ]
        refund_entries_2 = [p for p in donation.payments if p.mollie_payment_id == "re_history_test_002"]

        self.assertEqual(
            len(refund_entries_1_after), 1, "First refund should still appear exactly once (no duplicates)"
        )
        self.assertEqual(len(refund_entries_2), 1, "Second refund should appear exactly once")

        # Process first refund webhook AGAIN (simulate duplicate webhook delivery)
        result3 = self.webhook_processor.process_refund_webhook(
            payment_id=self.test_payment_id, refund_data=refund_data_1
        )

        # Should be idempotent (no new Payment Entry created)
        self.assertEqual(result3["status"], "success")
        self.assertTrue(result3.get("idempotent"), "Should detect duplicate webhook")

        # Reload donation and verify NO duplicate entries were added
        donation.reload()
        final_payment_count = len(donation.payments)

        print(f"📊 Final payment history count: {final_payment_count}")

        # Count should be unchanged (idempotency working)
        self.assertEqual(
            final_payment_count,
            initial_payment_count + 1,
            "Payment history count should not increase when processing duplicate webhook",
        )

        # Verify still exactly one entry for first refund (no duplication)
        refund_entries_1_final = [
            p for p in donation.payments if p.mollie_payment_id == "re_history_test_001"
        ]
        self.assertEqual(
            len(refund_entries_1_final),
            1,
            "First refund should STILL appear exactly once after duplicate webhook",
        )

        # Verify refund IDs are stored correctly in mollie_payment_id field
        for entry in donation.payments:
            if entry.payment_status in ["Refunded", "Chargeback"]:
                self.assertTrue(
                    entry.mollie_payment_id.startswith(("re_", "chb_")),
                    f"Refund/chargeback entries should store reversal ID, not payment ID. Got: {entry.mollie_payment_id}",
                )

        print("✅ Payment history idempotency test passed - duplicate entries prevented")

    def test_refund_without_original_payment_fails(self):
        """Test that refund webhook fails gracefully if original payment doesn't exist."""
        refund_data = {
            "id": "re_orphan_refund",
            "amount": {"value": "10.00", "currency": "EUR"},
        }

        # Try to process refund for non-existent payment
        result = self.webhook_processor.process_refund_webhook(
            payment_id="tr_nonexistent_payment", refund_data=refund_data
        )

        # Should return error
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"].lower())

        print("✅ Orphan refund handling test passed")

    def test_input_validation_rejects_invalid_reversal_type(self):
        """Test that invalid reversal types are rejected."""
        result = self.webhook_processor.process_reversal_webhook(
            payment_id=self.test_payment_id,
            reversal_id="invalid_001",
            amount=10.0,
            reversal_type="INVALID_TYPE",  # Not in allowed set
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid reversal_type", result["message"])

        print("✅ Input validation test passed")

    def test_input_validation_rejects_negative_amount(self):
        """Test that negative amounts are rejected."""
        result = self.webhook_processor.process_reversal_webhook(
            payment_id=self.test_payment_id,
            reversal_id="negative_001",
            amount=-50.0,  # Negative amount
            reversal_type="refund",
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("must be greater than 0", result["message"])

        print("✅ Negative amount validation test passed")


if __name__ == "__main__":
    unittest.main()
