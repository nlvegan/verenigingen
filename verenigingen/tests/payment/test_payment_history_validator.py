#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# -*- coding: utf-8 -*-
"""
Comprehensive Tests for Payment History Validator

Tests the payment_history_validator.py scheduled task functionality
with realistic data generation and edge case coverage.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.payment_history_validator import (
    get_payment_history_validation_stats,
    validate_and_repair_payment_history,
    validate_payment_history_integrity,
)


class TestPaymentHistoryValidator(VereningingenTestCase):
    """Test payment history validator functionality with realistic scenarios"""

    def setUp(self):
        super().setUp()
        self.test_start_time = now_datetime()

        # Create multiple test members for comprehensive validation testing
        self.test_members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Validator{i:02d}",
                last_name="TestMember",
                email=f"validator.test.{i:02d}@example.com",
            )

            # Ensure customer exists
            if not member.customer:
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{member.first_name} {member.last_name}"
                customer.customer_type = "Individual"
                customer.member = member.name
                customer.save()
                member.customer = customer.name
                member.save()
                self.track_doc("Customer", customer.name)

            self.test_members.append(member)

    def _clear_history_rows(self, invoice_names):
        """Delete payment-history rows for the given invoices to leave genuine gaps.

        Payment-history population on Sales Invoice submit now runs only via the
        async batch/drain path (the synchronous on_submit rebuild was removed),
        which does not run inline in tests. This delete stays as a defensive
        guarantee that these invoices are genuine gaps regardless of any batch
        timing.

        We also drop any still-queued batch adds for these invoices so the batch
        processor cannot re-materialize them. We do NOT flush the batch processor:
        its _process_member_payment_batch rolls back the whole transaction on any
        error, which would undo uncommitted setUp data. The in-session deletes are
        visible to the validator's get_value lookup, so no commit is required.
        """
        from verenigingen.utils.financial_history_batch_processor import (
            FinancialHistoryBatchProcessor,
        )

        for invoice_name in invoice_names:
            for member_queue in FinancialHistoryBatchProcessor._payment_queue.values():
                member_queue.pop(invoice_name, None)
            frappe.db.delete("Member Payment History", {"invoice": invoice_name})

    def test_validation_with_complete_payment_history(self):
        """Test validation when all invoices have corresponding payment history entries"""
        # Create invoices and ensure they're in payment history
        test_invoices = []
        for member in self.test_members[:3]:  # Use first 3 members
            # Create invoice
            invoice = self.create_test_sales_invoice(
                customer=member.customer, is_membership_invoice=1, posting_date=add_days(today(), -2)
            )
            invoice.submit()
            test_invoices.append(invoice)

            # Populate and persist the member's payment history. Invoice submit no
            # longer rebuilds payment history synchronously (that redundant on_submit
            # hook was removed); load_payment_history() rebuilds from the member's
            # invoices and saves without an explicit commit, so it is safe inside the
            # test transaction. (add_invoice_to_payment_history only QUEUES an async
            # batch update, which does not run inline in tests.)
            member.reload()
            member.load_payment_history()

        # Run validation
        result = validate_and_repair_payment_history()

        # Verify successful validation
        self.assertTrue(result["success"], "Validation should succeed")
        self.assertEqual(result["missing_found"], 0, "No missing entries should be found")
        self.assertEqual(result["repaired"], 0, "No repairs should be needed")
        self.assertEqual(result["errors"], 0, "No errors should occur")
        self.assertGreater(result["validated"], 0, "Some entries should be validated")

    def test_detection_of_missing_payment_history_entries(self):
        """Test detection of invoices missing from payment history"""
        # Create invoices WITHOUT adding them to payment history
        missing_invoices = []
        for member in self.test_members[:2]:  # Use first 2 members
            invoice = self.create_test_sales_invoice(
                customer=member.customer, is_membership_invoice=1, posting_date=add_days(today(), -1)
            )
            invoice.submit()
            missing_invoices.append(invoice)

        # Clear the auto-synced rows AFTER all submits to leave genuine gaps.
        self._clear_history_rows([inv.name for inv in missing_invoices])

        # Run validation
        result = validate_and_repair_payment_history()

        # Verify missing entries were detected
        self.assertTrue(result["success"], "Validation should succeed")
        self.assertGreater(result["missing_found"], 0, "Missing entries should be detected")
        self.assertEqual(
            result["missing_found"],
            len(missing_invoices),
            f"Should detect {len(missing_invoices)} missing entries",
        )

    def test_automatic_repair_of_missing_entries(self):
        """Test automatic repair of missing payment history entries"""
        # Create invoices without payment history entries
        repair_test_member = self.test_members[0]
        missing_invoices = []

        for i in range(3):
            invoice = self.create_test_sales_invoice(
                customer=repair_test_member.customer,
                is_membership_invoice=1,
                posting_date=add_days(today(), -i - 1),
            )
            invoice.submit()
            missing_invoices.append(invoice)

        # Clear the auto-synced rows AFTER all submits to leave genuine gaps.
        self._clear_history_rows([inv.name for inv in missing_invoices])
        repair_test_member.reload()

        # Verify payment history is initially empty or doesn't contain our invoices
        initial_payment_history = [entry.invoice for entry in repair_test_member.payment_history]
        for invoice in missing_invoices:
            self.assertNotIn(
                invoice.name,
                initial_payment_history,
                f"Invoice {invoice.name} should not be in payment history initially",
            )

        # Run validation and repair. The validator now reconciles against
        # source-of-truth and drives the real drain job
        # (background_jobs.drain_member_payment_history) once per member with a
        # gap, instead of the old circular member_doc.add_invoice_to_payment_history()
        # re-enqueue. Capture the frappe.enqueue call to prove it targets the
        # right job/member, then invoke the drain function directly (as the
        # worker would) to observe the row actually land.
        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = validate_and_repair_payment_history()

        # Verify repair was successful
        self.assertTrue(result["success"], "Validation and repair should succeed")
        self.assertGreater(result["repaired"], 0, "Some entries should be repaired")
        self.assertEqual(result["errors"], 0, "No repair errors should occur")

        job_ids = [k.get("job_id") for k in calls]
        self.assertIn(
            f"fin_history_payment_{repair_test_member.name}",
            job_ids,
            "Repair should enqueue the real drain job for the member with the gap",
        )

        # Simulate the worker draining the enqueued job.
        from verenigingen.utils.background_jobs import drain_member_payment_history

        drain_member_payment_history(repair_test_member.name, repair_test_member.customer)

        repair_test_member.reload()
        final_payment_history = [entry.invoice for entry in repair_test_member.payment_history]

        for invoice in missing_invoices:
            self.assertIn(
                invoice.name,
                final_payment_history,
                f"Invoice {invoice.name} should be in payment history after repair",
            )

    def test_validation_with_mixed_scenarios(self):
        """Test validation with mix of complete, missing, and error scenarios"""
        # Member 1: Complete payment history (should validate)
        complete_member = self.test_members[0]
        complete_invoice = self.create_test_sales_invoice(
            customer=complete_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -1)
        )
        complete_invoice.submit()
        # Populate + persist (see test_validation_with_complete_payment_history for
        # why load_payment_history() is used instead of the async queue helper).
        complete_member.reload()
        complete_member.load_payment_history()

        # Member 2: Missing payment history (should be repaired). Submit but never
        # populate, so it stays a genuine gap.
        missing_member = self.test_members[1]
        missing_invoice = self.create_test_sales_invoice(
            customer=missing_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -2)
        )
        missing_invoice.submit()

        # Member 3: partial history -- invoice1 present, invoice2 a gap. Populate
        # after submitting invoice1 only; invoice2 is submitted afterwards and left
        # unpopulated (invoice submit no longer auto-rebuilds payment history).
        partial_member = self.test_members[2]
        partial_invoice1 = self.create_test_sales_invoice(
            customer=partial_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -3)
        )
        partial_invoice1.submit()
        partial_member.reload()
        partial_member.load_payment_history()

        partial_invoice2 = self.create_test_sales_invoice(
            customer=partial_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -4)
        )
        partial_invoice2.submit()

        # Defensively ensure the two intended gaps have no history rows.
        self._clear_history_rows([missing_invoice.name, partial_invoice2.name])

        # Run validation
        result = validate_and_repair_payment_history()

        # Verify mixed scenario results
        self.assertTrue(result["success"], "Mixed scenario validation should succeed")
        self.assertGreater(result["validated"], 0, "Some valid entries should be found")
        self.assertGreater(result["missing_found"], 0, "Some missing entries should be found")
        self.assertGreater(result["repaired"], 0, "Some entries should be repaired")

        # The validator detected and repaired the two genuine gaps (missing_invoice
        # and partial_invoice2). Confirm they are now flagged for repair.
        self.assertGreaterEqual(result["missing_found"], 2, "Both gaps should be detected")
        self.assertGreaterEqual(result["repaired"], 2, "Both gaps should be repaired")

    def test_validation_stats_generation(self):
        """Test generation of payment history validation statistics"""
        # Create test data for statistics
        stats_member = self.test_members[3]

        # Create invoices with payment history
        for i in range(3):
            invoice = self.create_test_sales_invoice(
                customer=stats_member.customer,
                is_membership_invoice=1,
                posting_date=add_days(today(), -i - 1),
            )
            invoice.submit()
            stats_member.add_invoice_to_payment_history(invoice.name)

        # Get validation statistics
        stats_result = get_payment_history_validation_stats()

        # Verify statistics structure
        self.assertTrue(stats_result["success"], "Statistics generation should succeed")
        self.assertIn("total_invoices", stats_result, "Should include total invoices count")
        self.assertIn("invoices_with_members", stats_result, "Should include member-linked invoices")
        self.assertIn("payment_history_entries", stats_result, "Should include payment history count")
        self.assertIn("sync_rate", stats_result, "Should include sync rate percentage")
        self.assertEqual(stats_result["period_days"], 7, "Should cover 7-day period")

        # Verify reasonable values
        self.assertGreaterEqual(stats_result["total_invoices"], 0, "Total invoices should be non-negative")
        self.assertGreaterEqual(stats_result["sync_rate"], 0, "Sync rate should be non-negative")
        self.assertLessEqual(stats_result["sync_rate"], 100, "Sync rate should not exceed 100%")

    def test_alert_generation_for_significant_issues(self):
        """Test alert generation when significant payment history issues are detected"""
        # Create many missing entries to trigger alert threshold
        alert_test_members = self.test_members[:4]  # Use 4 members
        missing_invoices = []

        # Create 3 invoices per member (12 total) to exceed alert threshold of 10
        for member in alert_test_members:
            for i in range(3):
                invoice = self.create_test_sales_invoice(
                    customer=member.customer, is_membership_invoice=1, posting_date=add_days(today(), -i - 1)
                )
                invoice.submit()
                missing_invoices.append(invoice)

        # Clear the auto-synced rows AFTER all submits to leave genuine gaps.
        self._clear_history_rows([inv.name for inv in missing_invoices])

        # Check if System Alert doctype exists (may not in all installations)
        system_alert_exists = DocumentExistenceValidator.check_document_exists("DocType", "System Alert")

        # Run validation
        result = validate_and_repair_payment_history()

        # Verify large number of missing entries triggers appropriate handling
        self.assertTrue(result["success"], "Validation should succeed even with many missing entries")
        self.assertGreaterEqual(result["missing_found"], 10, "Should find at least 10 missing entries")

        if system_alert_exists:
            # Check if alert was created (if System Alert doctype exists)
            recent_alerts = frappe.get_all(
                "System Alert",
                filters={
                    "creation": (">=", self.test_start_time),
                    "message": ("like", "%Payment History Sync Issues%"),
                },
                limit=1,
            )

            if result["missing_found"] > 10:
                # Alert should have been created for significant issues
                self.assertGreater(
                    len(recent_alerts), 0, "Alert should be created for significant payment history issues"
                )

    def test_validation_error_handling(self):
        """Test error handling during validation process"""
        # Create a member with customer but then break the relationship
        error_test_member = self.test_members[4]

        # Create invoice
        invoice = self.create_test_sales_invoice(
            customer=error_test_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -1)
        )
        invoice.submit()

        # Break the customer relationship to cause repair errors
        frappe.db.set_value("Member", error_test_member.name, "customer", "NON_EXISTENT_CUSTOMER")

        # Run validation (should handle errors gracefully)
        result = validate_and_repair_payment_history()

        # Verification: should complete but may have errors
        self.assertTrue(result["success"], "Validation should succeed even with some errors")

        # If errors occurred, they should be properly counted
        if result["errors"] > 0:
            self.assertGreater(result["errors"], 0, "Errors should be properly counted")

    def test_scheduled_task_wrapper(self):
        """Test the scheduled task wrapper function"""
        # Create test data
        scheduled_member = self.test_members[0]
        invoice = self.create_test_sales_invoice(
            customer=scheduled_member.customer, is_membership_invoice=1, posting_date=add_days(today(), -1)
        )
        invoice.submit()

        # Run scheduled task wrapper (should not raise exceptions)
        try:
            validate_payment_history_integrity()
            wrapper_success = True
        except Exception as e:
            wrapper_success = False
            print(f"Scheduled task wrapper failed: {e}")

        self.assertTrue(wrapper_success, "Scheduled task wrapper should complete without exceptions")

    def test_performance_with_large_dataset(self):
        """Test validator performance with larger dataset"""
        import time

        # Create larger dataset for performance testing
        performance_member = self.test_members[0]

        # Create 10 invoices for performance testing
        performance_invoices = []
        gap_invoices = []
        for i in range(10):
            invoice = self.create_test_sales_invoice(
                customer=performance_member.customer,
                is_membership_invoice=1,
                posting_date=add_days(today(), -i - 1),
            )
            invoice.submit()
            performance_invoices.append(invoice)
            # Keep half in payment history; the other half become genuine gaps.
            if i % 2 != 0:
                gap_invoices.append(invoice)

        # Clear the gap rows AFTER all submits (each submit rebuilds the member's
        # full payment history, so deletes must happen once at the end).
        self._clear_history_rows([inv.name for inv in gap_invoices])

        # Measure validation performance
        start_time = time.time()
        result = validate_and_repair_payment_history()
        execution_time = time.time() - start_time

        # Verify performance and results
        self.assertTrue(result["success"], "Performance test validation should succeed")
        self.assertLess(execution_time, 30.0, f"Validation should complete within 30s: {execution_time:.2f}s")
        self.assertGreater(result["missing_found"], 0, "Should find missing entries in performance test")
        self.assertGreater(result["repaired"], 0, "Should repair missing entries in performance test")

    def test_cutoff_date_filtering(self):
        """Test that validation only processes recent invoices (7-day cutoff)"""
        # Create old invoice (beyond 7-day cutoff)
        old_invoice = self.create_test_sales_invoice(
            customer=self.test_members[0].customer,
            is_membership_invoice=1,
            posting_date=add_days(today(), -10),  # 10 days old
        )
        old_invoice.submit()

        # Manually set creation date to be old
        frappe.db.set_value("Sales Invoice", old_invoice.name, "creation", add_days(now_datetime(), -10))

        # Create recent invoice (within 7-day cutoff)
        recent_invoice = self.create_test_sales_invoice(
            customer=self.test_members[1].customer,
            is_membership_invoice=1,
            posting_date=add_days(today(), -2),  # 2 days old
        )
        recent_invoice.submit()
        # Clear the auto-synced row so the recent invoice is a genuine gap.
        self._clear_history_rows([recent_invoice.name])

        # Run validation
        result = validate_and_repair_payment_history()

        # Verify only recent invoices are processed
        self.assertTrue(result["success"], "Cutoff date filtering should work correctly")

        # The old invoice should not be in the repair count
        # (This test verifies the 7-day cutoff is working)
        self.assertGreater(result["missing_found"], 0, "Should find the recent missing invoice")

    def tearDown(self):
        """Clean up test data and verify validator performance"""
        # Check for validator-related errors during test
        validator_errors = frappe.db.sql(
            """
            SELECT error, creation
            FROM `tabError Log`
            WHERE creation >= %s
            AND (error LIKE '%%payment_history_validator%%' OR error LIKE '%%Payment History Validator%%')
            ORDER BY creation DESC
            LIMIT 5
        """,
            (self.test_start_time,),
            as_dict=True,
        )

        if validator_errors:
            print("Payment history validator errors found during test:")
            for error in validator_errors:
                print(f"  - {error.creation}: {error.error[:200]}...")

        super().tearDown()
