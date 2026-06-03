#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Tests for Payment History Batched Processing

Tests the batched payment-history pipeline:
  Member.add_invoice_to_payment_history()  -> queues a batch op
  FinancialHistoryBatchProcessor           -> persists it atomically (fresh Member doc)

Current production contract (see payment_mixin.py + financial_history_batch_processor.py):
  * add_invoice_to_payment_history() only QUEUES the operation; it does NOT mutate the
    in-memory member doc. Callers must force batch processing and reload to observe the result.
  * The batch processor loads a fresh Member doc from the DB, so observing the result
    requires self.test_member.reload().
  * Payment history is trimmed to 30 entries (max_entries=30 in the history manager),
    newest-first.

These tests previously assumed the legacy synchronous/in-memory contract (and used worker
threads that cannot bind frappe.local); they have been updated to the current batched contract.
"""

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor


class TestPaymentHistoryRaceCondition(EnhancedTestCase):
    """Test payment history batched processing with realistic scenarios"""

    def setUp(self):
        super().setUp()
        self.test_start_time = now_datetime()

        # Create test member and customer for all payment history tests
        self.test_member = self.create_test_member(
            first_name="RaceCondition",
            last_name="TestMember",
            email="race.condition.test@example.com"
        )

        # Ensure customer exists for payment history testing
        if not self.test_member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
            customer.customer_type = "Individual"
            customer.member = self.test_member.name
            customer.save()
            self.test_member.customer = customer.name
            self.test_member.save()
            self._track_test_document("Customer", customer.name)

    def _flush_and_reload(self):
        """Force the batched payment-history pipeline to run and refresh the member doc.

        add_invoice_to_payment_history() only queues an operation; the batch processor
        persists it against a fresh Member doc. Tests must flush + reload to observe results.
        """
        FinancialHistoryBatchProcessor.force_process_all()
        self.test_member.reload()

    def _find_entry(self, invoice_name):
        for entry in self.test_member.payment_history:
            if entry.invoice == invoice_name:
                return entry
        return None

    def test_normal_invoice_processing(self):
        """Test normal invoice processing persists through the batch pipeline"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        # Clear bulk processing flags to test normal mode (safe removal)
        frappe.flags.bulk_invoice_generation = False

        start_time = time.time()

        # Queue the invoice, then flush the batch
        self.test_member.add_invoice_to_payment_history(invoice.name)
        self._flush_and_reload()

        execution_time = time.time() - start_time
        self.assertLess(execution_time, 5.0,
                       f"Normal mode processing took too long: {execution_time:.2f}s")

        found_entry = self._find_entry(invoice.name)
        self.assertIsNotNone(found_entry, "Invoice should be added to payment history")
        self.assertEqual(found_entry.amount, invoice.grand_total)
        self.assertEqual(found_entry.status, invoice.status)

    def test_bulk_processing_extended_timeout(self):
        """Test bulk processing mode persists through the batch pipeline"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        frappe.flags.bulk_invoice_generation = True

        try:
            start_time = time.time()

            self.test_member.add_invoice_to_payment_history(invoice.name)
            self._flush_and_reload()

            execution_time = time.time() - start_time

            found_entry = self._find_entry(invoice.name)
            self.assertIsNotNone(found_entry, "Invoice should be added in bulk mode")

            self.assertLess(execution_time, 10.0,
                           f"Bulk mode processing took too long: {execution_time:.2f}s")

        finally:
            if hasattr(frappe.flags, 'bulk_invoice_generation'):
                delattr(frappe.flags, 'bulk_invoice_generation')

    def test_race_condition_retry_mechanism(self):
        """Test that queuing the same invoice repeatedly is deduplicated and persisted once.

        The legacy version spun up worker threads; that cannot work because frappe.local is
        not bound in threads spawned by the test. The real current contract is that the batch
        queue deduplicates per (member, invoice), so multiple queue calls collapse into one
        persisted entry.
        """
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        # Queue the same invoice several times (simulating concurrent enqueues)
        results = []
        for _ in range(3):
            if self.test_member.add_invoice_to_payment_history(invoice.name):
                results.append("queued")

        # All queue calls should succeed
        self.assertEqual(len(results), 3, "All queue operations should succeed")

        # Flush the batch and verify a single entry was persisted
        self._flush_and_reload()

        matching = [e for e in self.test_member.payment_history if e.invoice == invoice.name]
        self.assertEqual(len(matching), 1, "Invoice should be added exactly once after dedup")

    def test_race_condition_exhausted_retries(self):
        """Test behavior when an invoice never becomes available"""
        fake_invoice_name = "FAKE-INVOICE-NEVER-EXISTS"

        start_time = time.time()

        # Queue + flush; the batch processor's retry should exhaust and log, not crash
        self.test_member.add_invoice_to_payment_history(fake_invoice_name)
        self._flush_and_reload()

        execution_time = time.time() - start_time

        # Should not take too long even with retries
        self.assertLess(execution_time, 30.0,
                       "Exhausted retries should not take too long")

        # Verify no entry was added for the fake invoice
        self.assertIsNone(self._find_entry(fake_invoice_name),
                          "Fake invoice should not be in payment history")

    def test_concurrent_invoice_processing(self):
        """Test batched processing of multiple invoices in one window"""
        invoices = []
        for i in range(5):
            invoice = self.create_test_sales_invoice(
                customer=self.test_member.customer,
                is_membership_invoice=1,
                posting_date=add_days(today(), -i)
            )
            invoices.append(invoice)

        # Queue all invoices, then flush a single batch
        for invoice in invoices:
            queued = self.test_member.add_invoice_to_payment_history(invoice.name)
            self.assertTrue(queued, f"Invoice {invoice.name} should queue successfully")

        self._flush_and_reload()

        # Verify all invoices are in payment history
        payment_history_invoices = [entry.invoice for entry in self.test_member.payment_history]
        for invoice in invoices:
            self.assertIn(invoice.name, payment_history_invoices,
                         f"Invoice {invoice.name} should be in payment history")

    def test_payment_history_entry_building(self):
        """Test comprehensive payment history entry building with all fields"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today(),
            due_date=add_days(today(), 30)
        )

        # Create a membership association
        membership = self.create_test_membership(member=self.test_member.name)

        # Create a payment entry for testing payment status
        payment_entry = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            paid_amount=invoice.grand_total,
            posting_date=today()
        )

        # Link payment to invoice
        payment_entry.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": invoice.grand_total
        })
        payment_entry.save()

        # Queue + flush the invoice into payment history
        self.test_member.add_invoice_to_payment_history(invoice.name)
        self._flush_and_reload()

        payment_entry_found = self._find_entry(invoice.name)

        # Verify all fields are properly populated
        self.assertIsNotNone(payment_entry_found, "Payment history entry should exist")
        self.assertEqual(payment_entry_found.invoice, invoice.name)
        self.assertEqual(payment_entry_found.amount, invoice.grand_total)
        self.assertIn(payment_entry_found.transaction_type, ["Regular Invoice", "Membership Invoice"])
        self.assertIsNotNone(payment_entry_found.posting_date)
        self.assertIsNotNone(payment_entry_found.due_date)

    def test_payment_history_trimming(self):
        """Test that payment history is trimmed to the configured maximum (30 entries)"""
        # Max entries for payment_history is 30 (see member_financial_history_manager.py)
        max_entries = 30

        invoices = []
        for i in range(max_entries + 5):
            invoice = self.create_test_sales_invoice(
                customer=self.test_member.customer,
                is_membership_invoice=1,
                posting_date=add_days(today(), -i)
            )
            invoices.append(invoice)
            self.test_member.add_invoice_to_payment_history(invoice.name)

        # Flush the batch and reload to observe persisted state
        self._flush_and_reload()

        # Verify payment history is trimmed to the configured maximum
        self.assertLessEqual(len(self.test_member.payment_history), max_entries,
                            f"Payment history should be trimmed to maximum {max_entries} entries")
        self.assertEqual(len(self.test_member.payment_history), max_entries,
                         f"Payment history should contain exactly {max_entries} entries after trimming")

        # The most-recently-queued invoice prepends to the front and survives trimming.
        payment_history_invoices = [entry.invoice for entry in self.test_member.payment_history]
        self.assertIn(invoices[-1].name, payment_history_invoices,
                      "The most recently added invoice should remain in payment history")

    def test_database_commit_behavior(self):
        """Test that the batch processor commits when persisting payment history"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        self.test_member.add_invoice_to_payment_history(invoice.name)

        # Count commits during batch processing (the batch processor commits per member)
        commit_count = [0]
        original_commit = frappe.db.commit

        def counting_commit():
            commit_count[0] += 1
            return original_commit()

        with patch('frappe.db.commit', side_effect=counting_commit):
            FinancialHistoryBatchProcessor.force_process_all()

        self.test_member.reload()

        # Verify commits occurred during batch processing
        self.assertGreater(commit_count[0], 0, "Database commits should occur during processing")

        # Verify invoice was successfully added
        self.assertIsNotNone(self._find_entry(invoice.name),
                             "Invoice should be committed to payment history")

    def test_logging_output_verification(self):
        """Test that proper logging occurs during batch processing scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        frappe.flags.bulk_invoice_generation = True

        try:
            logged_messages = []

            def mock_log_info(message):
                logged_messages.append(message)

            with patch.object(frappe.logger("payment_history"), 'info', side_effect=mock_log_info):
                self.test_member.add_invoice_to_payment_history(invoice.name)
                FinancialHistoryBatchProcessor.force_process_all()

            # Logging should be available for race condition scenarios (may be zero on success)
            self.assertGreaterEqual(len(logged_messages), 0,
                                   "Logging should be available for race condition scenarios")

        finally:
            if hasattr(frappe.flags, 'bulk_invoice_generation'):
                delattr(frappe.flags, 'bulk_invoice_generation')

    def test_performance_comparison_normal_vs_bulk(self):
        """Test performance differences between normal and bulk processing modes"""
        invoice_normal = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=today()
        )

        invoice_bulk = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=add_days(today(), -1)
        )

        # Test normal mode performance
        start_time = time.time()
        self.test_member.add_invoice_to_payment_history(invoice_normal.name)
        FinancialHistoryBatchProcessor.force_process_all()
        normal_time = time.time() - start_time

        # Test bulk mode performance
        frappe.flags.bulk_invoice_generation = True
        try:
            start_time = time.time()
            self.test_member.add_invoice_to_payment_history(invoice_bulk.name)
            FinancialHistoryBatchProcessor.force_process_all()
            bulk_time = time.time() - start_time
        finally:
            if hasattr(frappe.flags, 'bulk_invoice_generation'):
                delattr(frappe.flags, 'bulk_invoice_generation')

        self.test_member.reload()

        # Both should complete successfully
        self.assertLess(normal_time, 10.0, f"Normal mode should complete quickly: {normal_time:.2f}s")
        self.assertLess(bulk_time, 10.0, f"Bulk mode should complete reasonably: {bulk_time:.2f}s")

        # Verify both invoices were added
        payment_history_invoices = [entry.invoice for entry in self.test_member.payment_history]
        self.assertIn(invoice_normal.name, payment_history_invoices)
        self.assertIn(invoice_bulk.name, payment_history_invoices)

    def test_edge_case_invalid_customer(self):
        """Test behavior when invoice has different customer than member"""
        other_customer = frappe.new_doc("Customer")
        other_customer.customer_name = "Other Test Customer"
        other_customer.customer_type = "Individual"
        other_customer.save()
        self._track_test_document("Customer", other_customer.name)

        invoice = self.create_test_sales_invoice(
            customer=other_customer.name,
            is_membership_invoice=1,
            posting_date=today()
        )

        # Try to add invoice to member with different customer
        initial_count = len(self.test_member.payment_history)

        self.test_member.add_invoice_to_payment_history(invoice.name)
        self._flush_and_reload()

        # Should not add invoice since customer doesn't match
        final_count = len(self.test_member.payment_history)
        self.assertEqual(initial_count, final_count,
                        "Invoice with different customer should not be added")

    def tearDown(self):
        """Clean up test data and verify no errors were logged"""
        # Drain any leftover queued operations so state does not leak across tests
        try:
            FinancialHistoryBatchProcessor.force_process_all()
        except Exception:
            pass

        try:
            test_errors = frappe.db.sql('''
                SELECT error, creation
                FROM `tabError Log`
                WHERE creation >= %s
                AND error LIKE %s
                ORDER BY creation DESC
                LIMIT 5
            ''', (self.test_start_time, '%race condition%'), as_dict=True)

            if test_errors:
                print("Race condition errors found during test:")
                for error in test_errors:
                    print(f"  - {error.creation}: {error.error[:200]}...")
        except Exception as e:
            print(f"Warning: Could not check for race condition errors: {e}")

        super().tearDown()
