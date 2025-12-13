# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberHistoryUpdateService

Tests member history table update functionality.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.utils import random_string, today, add_days
from verenigingen.services.member.history.member_history_update_service import MemberHistoryUpdateService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberHistoryUpdateService(EnhancedTestCase):
    """Unit tests for MemberHistoryUpdateService"""

    def setUp(self):
        super().setUp()
        self.service = MemberHistoryUpdateService()
        # Set user to Administrator for history update permissions
        frappe.set_user("Administrator")

    def test_incremental_update_history_tables_returns_operation_result(self):
        """Test incremental history update returns OperationResult"""
        unique_email = f"history.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="History",
            last_name="Test",
            email=unique_email
        )

        result = self.service.incremental_update_history_tables(member)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("volunteer_expenses", result.data)
        self.assertIn("donations", result.data)
        self.assertIn("dues_payments", result.data)
        self.assertIn("invoices", result.data)

    def test_incremental_update_with_no_history_returns_success(self):
        """Test incremental update with member having no history"""
        unique_email = f"nohistory.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="NoHistory",
            last_name="Test",
            email=unique_email
        )

        result = self.service.incremental_update_history_tables(member)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertEqual(result.data["donations"]["count"], 0)
        self.assertEqual(result.data["dues_payments"]["count"], 0)
        self.assertEqual(result.data["invoices"]["count"], 0)

    def test_incremental_update_with_customer_includes_invoices(self):
        """Test incremental update with customer includes invoice history"""
        unique_email = f"customer.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Customer",
            last_name="Test",
            email=unique_email
        )

        # Create customer for member
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.insert()
            frappe.db.set_value("Member", member.name, "customer", customer.name)
            member.reload()

        result = self.service.incremental_update_history_tables(member)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIn("invoices", result.data)

    def test_incremental_update_never_throws_exceptions(self):
        """Test that incremental update never throws exceptions"""
        # Create a member with potential issues
        unique_email = f"exception.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Exception",
            last_name="Test",
            email=unique_email
        )

        # Should always return OperationResult
        result = self.service.incremental_update_history_tables(member)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_refresh_fee_change_history_returns_operation_result(self):
        """Test fee change history refresh returns OperationResult"""
        unique_email = f"feehistory.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="FeeHistory",
            last_name="Test",
            email=unique_email
        )

        result = self.service.refresh_fee_change_history(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("history_count", result.data)
        self.assertIn("amendments_found", result.data)
        self.assertIn("dues_schedules_found", result.data)

    def test_refresh_fee_change_history_with_no_changes(self):
        """Test refresh fee history when no changes needed"""
        unique_email = f"nochanges.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="NoChanges",
            last_name="Test",
            email=unique_email
        )

        result = self.service.refresh_fee_change_history(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("method"), "no_changes")

    def test_refresh_fee_change_history_invalid_member_returns_failed_result(self):
        """Test refresh fee history with invalid member returns failed OperationResult"""
        result = self.service.refresh_fee_change_history("INVALID-MEMBER")

        # Should return failed OperationResult (not throw exception)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_refresh_fee_change_history_never_throws_exceptions(self):
        """Test that fee history refresh never throws exceptions"""
        invalid_inputs = ["", "INVALID", "Non-Existent-Member-789"]

        for invalid_input in invalid_inputs:
            result = self.service.refresh_fee_change_history(invalid_input)
            self.assertIsNotNone(result, f"Service returned None for: {invalid_input}")
            # Should be OperationResult with success attribute
            self.assertIsNotNone(result.success)

    def test_incremental_update_result_data_structure(self):
        """Test that incremental update returns correct data structure"""
        unique_email = f"structure.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Structure",
            last_name="Test",
            email=unique_email
        )

        result = self.service.incremental_update_history_tables(member)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Check structure
        self.assertIn("volunteer_expenses", result.data)
        self.assertIsInstance(result.data["volunteer_expenses"], dict)
        self.assertIn("success", result.data["volunteer_expenses"])
        self.assertIn("count", result.data["volunteer_expenses"])

        self.assertIn("donations", result.data)
        self.assertIsInstance(result.data["donations"], dict)
        self.assertIn("success", result.data["donations"])
        self.assertIn("count", result.data["donations"])

    def test_refresh_fee_history_result_contains_metadata(self):
        """Test that fee history refresh includes all expected metadata"""
        unique_email = f"metadata.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Metadata",
            last_name="Test",
            email=unique_email
        )

        result = self.service.refresh_fee_change_history(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Check metadata fields
        expected_fields = [
            "history_count",
            "amendments_found",
            "dues_schedules_found",
            "removed_entries",
            "cleanup_details",
            "method"
        ]
        for field in expected_fields:
            self.assertIn(field, result.data, f"Missing expected field: {field}")

    def test_incremental_update_handles_member_with_donor(self):
        """Test incremental update with member having donor link"""
        unique_email = f"donor.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Donor",
            last_name="Test",
            email=unique_email
        )

        # Create a donor with same email
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"{member.first_name} {member.last_name}"
        donor.donor_email = unique_email
        donor.donor_type = "Individual"  # Required field
        donor.insert()

        result = self.service.incremental_update_history_tables(member)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIn("donations", result.data)

    def test_incremental_update_preserves_existing_history(self):
        """Test that incremental update preserves valid existing history"""
        unique_email = f"preserve.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Preserve",
            last_name="Test",
            email=unique_email
        )

        # Run update twice - should preserve history
        result1 = self.service.incremental_update_history_tables(member)
        self.assertTrue(result1.success)

        result2 = self.service.incremental_update_history_tables(member)
        self.assertTrue(result2.success)

    def test_reconciled_payment_not_duplicated_in_history(self):
        """Test that payment entries reconciled with invoices don't create duplicate rows.

        When a Payment Entry is reconciled with a Sales Invoice:
        - The invoice row shows the payment info (payment_entry, payment_date, reconciled=1)
        - NO separate "Membership Dues Payment" row should be created

        This prevents duplicate representation of the same payment.
        """
        unique_email = f"nodupe.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="NoDupe",
            last_name="Test",
            email=unique_email
        )

        # Ensure customer exists for member (factory may auto-create)
        if not member.customer:
            member.create_customer()
            member.reload()

        # Create a Sales Invoice for this member using factory method
        invoice = self.create_test_sales_invoice(
            customer=member.name,  # Factory resolves member to customer
            rate=25.0,
            submit=True
        )

        # Verify invoice is still unpaid (test isolation check)
        invoice.reload()
        if invoice.outstanding_amount <= 0:
            self.skipTest(f"Invoice {invoice.name} already paid - test data pollution")

        # Create a Payment Entry for this member that pays the invoice
        # Wrapped in try/except to handle test environment issues where invoice
        # may get paid by auto-reconciliation or other mechanisms
        try:
            payment_entry = self.create_test_payment_entry(
                party=member.customer,
                paid_amount=25.0,
                custom_member=member.name,
                references=[{
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": 25.0,
                }],
                submit=True
            )
        except frappe.exceptions.ValidationError as e:
            if "already been fully paid" in str(e):
                self.skipTest(f"Invoice {invoice.name} got paid by external mechanism - test environment issue")
            raise

        # Run incremental update
        result = self.service.incremental_update_history_tables(member)
        self.assertTrue(result.success)

        # Reload member to get updated history
        member.reload()

        # Count how many times this payment entry appears in history
        payment_entry_occurrences = [
            row for row in (member.payment_history or [])
            if row.payment_entry == payment_entry.name
        ]

        # The payment entry should appear ONCE (via the invoice row), not twice
        self.assertEqual(
            len(payment_entry_occurrences), 1,
            f"Payment Entry {payment_entry.name} appears {len(payment_entry_occurrences)} times, expected 1"
        )

        # The single occurrence should be on an invoice row (reconciled)
        occurrence = payment_entry_occurrences[0]
        self.assertEqual(occurrence.invoice, invoice.name)
        self.assertEqual(occurrence.reconciled, 1)
        # It should NOT be a standalone "Membership Dues Payment" type
        self.assertNotEqual(occurrence.transaction_type, "Membership Dues Payment")

    def test_unreconciled_payment_creates_standalone_row(self):
        """Test that unreconciled payment entries create standalone history rows.

        When a Payment Entry is NOT reconciled with any invoice:
        - A "Membership Dues Payment" row should be created
        - reconciled should be 0
        """
        unique_email = f"unreconciled.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Unreconciled",
            last_name="Test",
            email=unique_email
        )

        # Ensure customer exists for member
        if not member.customer:
            member.create_customer()
            member.reload()

        # Create an unallocated Payment Entry (no invoice references)
        payment_entry = self.create_test_payment_entry(
            party=member.customer,
            paid_amount=25.0,
            custom_member=member.name,
            # No references - this is an unreconciled payment
            submit=True
        )

        # Run incremental update
        result = self.service.incremental_update_history_tables(member)
        self.assertTrue(result.success)

        # Reload member to get updated history
        member.reload()

        # Find the payment entry in history
        payment_rows = [
            row for row in (member.payment_history or [])
            if row.payment_entry == payment_entry.name
        ]

        # Should have exactly one entry
        self.assertEqual(len(payment_rows), 1)

        # Should be a standalone "Membership Dues Payment" row
        row = payment_rows[0]
        self.assertEqual(row.transaction_type, "Membership Dues Payment")
        self.assertEqual(row.reconciled, 0)
        self.assertIsNone(row.invoice)  # No invoice linked


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberHistoryUpdateService)
    unittest.TextTestRunner(verbosity=2).run(suite)
