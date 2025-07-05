# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Payment Processing API functions
Tests the whitelisted API functions for payment operations
"""


from frappe.utils import add_days, today

from verenigingen.verenigingen.api import payment_processing
from verenigingen.verenigingen.tests.utils.assertions import AssertionHelpers
from verenigingen.verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestPaymentProcessingAPI(VereningingenUnitTestCase):
    """Test Payment Processing API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = TestEnvironmentSetup.create_standard_test_environment()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()
        self.assertions = AssertionHelpers()

    def tearDown(self):
        """Clean up after each test"""
        self.builder.cleanup()
        super().tearDown()

    def test_process_membership_payment(self):
        """Test processing a membership payment"""
        # Create member with active membership
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name, status="Active")
            .build()
        )

        member = test_data["member"]
        test_data["membership"]

        # Process payment
        payment_data = {
            "amount": 100.00,
            "payment_method": "Bank Transfer",
            "transaction_reference": "TEST-PAY-001",
            "payment_date": today(),
        }

        result = payment_processing.process_membership_payment(member.name, payment_data)

        # Verify payment processed
        self.assertEqual(result["status"], "success")
        self.assertIn("invoice_name", result)
        self.assertIn("payment_entry", result)

    def test_create_sepa_mandate(self):
        """Test creating a SEPA mandate for a member"""
        # Create member
        test_data = self.builder.with_member(payment_method="SEPA Direct Debit").build()

        member = test_data["member"]

        # Create SEPA mandate
        mandate_data = {
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "account_holder_name": "Test Member",
            "mandate_type": "CORE",
            "sign_date": today(),
        }

        result = payment_processing.create_sepa_mandate(member.name, mandate_data)

        # Verify mandate created
        self.assertEqual(result["status"], "success")
        self.assertIn("mandate_id", result)

        # Verify member updated
        member.reload()
        self.assertEqual(member.iban, "NL91 ABNA 0417 1643 00")  # Formatted
        self.assertEqual(member.bank_account_name, "Test Member")

    def test_process_direct_debit_batch(self):
        """Test processing a batch of direct debit payments"""
        # Create multiple members with SEPA mandates
        members_with_payments = []

        for i in range(3):
            test_data = (
                self.builder.with_member(
                    payment_method="SEPA Direct Debit",
                    iban=f"NL{91 + i}ABNA0417164300",
                    bank_account_name=f"Test Member {i}",
                )
                .with_membership(
                    membership_type=self.test_env["membership_types"][2].name, status="Active"  # Monthly
                )
                .build()
            )

            members_with_payments.append(
                {"member": test_data["member"], "membership": test_data["membership"], "amount": 10.00}
            )

            self.builder.cleanup()

        # Create direct debit batch
        batch_data = {
            "collection_date": add_days(today(), 5),  # 5 days ahead
            "batch_reference": "TEST-BATCH-001",
            "member_payments": [
                {"member": mp["member"].name, "amount": mp["amount"]} for mp in members_with_payments
            ],
        }

        result = payment_processing.process_direct_debit_batch(batch_data)

        # Verify batch created
        self.assertEqual(result["status"], "success")
        self.assertIn("batch_name", result)
        self.assertEqual(result["total_amount"], 30.00)
        self.assertEqual(result["transaction_count"], 3)

    def test_handle_payment_failure(self):
        """Test handling payment failures"""
        # Create member with payment
        test_data = (
            self.builder.with_member(payment_method="SEPA Direct Debit")
            .with_membership(membership_type=self.test_env["membership_types"][0].name, status="Active")
            .build()
        )

        member = test_data["member"]

        # Handle payment failure
        failure_data = {
            "reason": "Insufficient funds",
            "failure_date": today(),
            "amount": 100.00,
            "retry_scheduled": add_days(today(), 7),
        }

        result = payment_processing.handle_payment_failure(member.name, failure_data)

        # Verify failure recorded
        member.reload()
        self.assertGreater(member.payment_failure_count, 0)
        self.assertEqual(member.last_payment_failure_date, today())

        # Verify notification scheduled
        self.assertIn("notification_sent", result)

    def test_retry_failed_payment(self):
        """Test retrying a failed payment"""
        # Create member with failed payment
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit",
            payment_failure_count=1,
            last_payment_failure_date=add_days(today(), -7),
        ).build()

        member = test_data["member"]

        # Retry payment
        retry_data = {"amount": 100.00, "retry_method": "SEPA Direct Debit"}

        result = payment_processing.retry_failed_payment(member.name, retry_data)

        # Verify retry attempted
        self.assertIn("status", result)

    def test_payment_reconciliation(self):
        """Test reconciling payments with invoices"""
        # Create member with unpaid invoice
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        member = test_data["member"]

        # Simulate unreconciled payment
        if hasattr(payment_processing, "reconcile_payment"):
            reconciliation_data = {
                "bank_transaction_id": "BANK-001",
                "amount": 100.00,
                "transaction_date": today(),
                "description": f"Payment from {member.full_name}",
            }

            result = payment_processing.reconcile_payment(reconciliation_data)

            # Verify reconciliation attempted
            self.assertIn("status", result)

    def test_generate_payment_reminder(self):
        """Test generating payment reminders"""
        # Create member with overdue payment
        test_data = (
            self.builder.with_member(email="reminder@test.com")
            .with_membership(membership_type=self.test_env["membership_types"][0].name, status="Active")
            .build()
        )

        member = test_data["member"]

        # Generate reminder
        if hasattr(payment_processing, "generate_payment_reminder"):
            reminder_data = {
                "reminder_type": "First Reminder",
                "due_amount": 100.00,
                "due_date": add_days(today(), -7),
            }

            result = payment_processing.generate_payment_reminder(member.name, reminder_data)

            # Verify reminder sent
            self.assertEqual(result["status"], "success")
            self.assertions.assert_email_sent(member.email, subject_contains="Payment Reminder")

    def test_bulk_payment_processing(self):
        """Test processing payments in bulk"""
        # Create multiple payments
        payment_entries = []

        for i in range(5):
            test_data = self.builder.with_member().build()
            payment_entries.append(
                {
                    "member": test_data["member"].name,
                    "amount": 50.00 + (i * 10),
                    "payment_method": "Bank Transfer",
                    "reference": f"BULK-{i}",
                }
            )
            self.builder.cleanup()

        # Process bulk payments
        if hasattr(payment_processing, "process_bulk_payments"):
            result = payment_processing.process_bulk_payments(payment_entries)

            self.assertEqual(result["total_processed"], 5)
            self.assertEqual(result["status"], "success")

    def test_payment_method_update(self):
        """Test updating member payment method"""
        # Create member with bank transfer
        test_data = self.builder.with_member(payment_method="Bank Transfer").build()

        member = test_data["member"]

        # Update to SEPA
        update_data = {
            "new_payment_method": "SEPA Direct Debit",
            "iban": "NL18RABO0123456789",
            "bic": "RABONL2U",
            "account_holder_name": "Updated Name",
        }

        payment_processing.update_payment_method(member.name, update_data)

        # Verify update
        member.reload()
        self.assertEqual(member.payment_method, "SEPA Direct Debit")
        self.assertEqual(member.iban, "NL18 RABO 0123 4567 89")  # Formatted

    def test_payment_history_retrieval(self):
        """Test retrieving payment history for a member"""
        # Create member with payments
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        member = test_data["member"]

        # Get payment history
        if hasattr(payment_processing, "get_payment_history"):
            history = payment_processing.get_payment_history(
                member.name, from_date=add_days(today(), -365), to_date=today()
            )

            self.assertIsInstance(history, list)
            # Verify history structure
            if history:
                self.assertIn("date", history[0])
                self.assertIn("amount", history[0])
                self.assertIn("status", history[0])

    def test_payment_export(self):
        """Test exporting payment data for accounting"""
        # Get export data
        if hasattr(payment_processing, "export_payments"):
            export_data = payment_processing.export_payments(
                from_date=add_days(today(), -30), to_date=today(), format="csv"
            )

            self.assertIn("data", export_data)
            self.assertIn("filename", export_data)
            self.assertIn("record_count", export_data)

    def test_payment_permissions(self):
        """Test payment operation permissions"""
        # Create member
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create finance user
        finance_user = self.create_test_user(email="finance@test.com", roles=["Accounts User"])

        # Test as finance user
        with self.as_user(finance_user.name):
            # Should be able to process payments
            payment_data = {
                "amount": 50.00,
                "payment_method": "Bank Transfer",
                "transaction_reference": "FIN-001",
            }

            result = payment_processing.process_membership_payment(member.name, payment_data)

            self.assertEqual(result["status"], "success")
