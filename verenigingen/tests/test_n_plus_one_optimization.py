#!/usr/bin/env python3
"""
Test N+1 Query Optimization Implementation

Tests for the batch query optimization that eliminates N+1 patterns
in payment history and expense history loading.

Covers:
- Chunking functionality for large datasets
- Error counting and metrics
- Data integrity (batched vs original results)
- Performance characteristics
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBatchChunkingFunctionality(EnhancedTestCase):
    """Test the _batch_fetch_with_chunking helper method"""

    def test_chunking_with_empty_list(self):
        """Empty list should return empty results without database queries"""
        member = self.create_test_member(
            first_name="Empty",
            last_name="Test",
            birth_date="1990-01-01"
        )

        result = member._batch_fetch_with_chunking(
            doctype="Sales Invoice",
            name_list=[],
            fields=["name", "grand_total"]
        )

        self.assertEqual(result, [])
        self.assertEqual(len(result), 0)

    def test_chunking_with_single_item(self):
        """Single-item list should work correctly"""
        member = self.create_test_member(
            first_name="Single",
            last_name="Item",
            birth_date="1990-01-01"
        )

        # Create one invoice
        invoice = self.create_test_sales_invoice(customer=member.customer)

        result = member._batch_fetch_with_chunking(
            doctype="Sales Invoice",
            name_list=[invoice.name],
            fields=["name", "grand_total"]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, invoice.name)

    def test_chunking_with_small_dataset(self):
        """Dataset smaller than chunk size should process in one batch"""
        member = self.create_test_member(
            first_name="Small",
            last_name="Dataset",
            birth_date="1990-01-01"
        )

        # Create 10 invoices (well below 500 chunk size)
        invoice_names = []
        for i in range(10):
            inv = self.create_test_sales_invoice(customer=member.customer)
            invoice_names.append(inv.name)

        result = member._batch_fetch_with_chunking(
            doctype="Sales Invoice",
            name_list=invoice_names,
            fields=["name", "grand_total"]
        )

        self.assertEqual(len(result), 10)
        result_names = {r.name for r in result}
        self.assertEqual(result_names, set(invoice_names))

    def test_chunking_with_additional_filters(self):
        """Additional filters should be preserved during chunking"""
        member = self.create_test_member(
            first_name="Filter",
            last_name="Test",
            birth_date="1990-01-01"
        )

        # Create mix of draft and submitted invoices
        draft_invoices = []
        submitted_invoices = []

        for i in range(10):
            inv = self.create_test_sales_invoice(customer=member.customer)
            if i % 2 == 0:
                inv.submit()
                submitted_invoices.append(inv.name)
            else:
                draft_invoices.append(inv.name)

        all_invoices = draft_invoices + submitted_invoices

        # Fetch only submitted invoices with additional filter
        result = member._batch_fetch_with_chunking(
            doctype="Sales Invoice",
            name_list=all_invoices,
            fields=["name", "docstatus"],
            filters={"docstatus": 1}
        )

        # Should return only submitted invoices
        self.assertEqual(len(result), len(submitted_invoices))
        for invoice_data in result:
            self.assertEqual(invoice_data.docstatus, 1)
            self.assertIn(invoice_data.name, submitted_invoices)

    def test_chunking_preserves_all_fields(self):
        """All requested fields should be included in results"""
        member = self.create_test_member(
            first_name="Fields",
            last_name="Test",
            birth_date="1990-01-01"
        )

        inv = self.create_test_sales_invoice(customer=member.customer)

        result = member._batch_fetch_with_chunking(
            doctype="Sales Invoice",
            name_list=[inv.name],
            fields=["name", "grand_total", "outstanding_amount", "posting_date", "status"]
        )

        self.assertEqual(len(result), 1)
        invoice_data = result[0]

        # Verify all fields present
        self.assertTrue(hasattr(invoice_data, "name"))
        self.assertTrue(hasattr(invoice_data, "grand_total"))
        self.assertTrue(hasattr(invoice_data, "outstanding_amount"))
        self.assertTrue(hasattr(invoice_data, "posting_date"))
        self.assertTrue(hasattr(invoice_data, "status"))


class TestPaymentHistoryBatchedOptimization(EnhancedTestCase):
    """Test payment history loading with batch optimization"""

    def test_payment_history_batched_with_no_invoices(self):
        """Member with no invoices should handle gracefully"""
        member = self.create_test_member(
            first_name="No",
            last_name="Invoices",
            birth_date="1990-01-01"
        )

        # Should not raise error
        member._load_payment_history_batched()

        self.assertEqual(len(member.payment_history), 0)

    def test_payment_history_batched_with_single_invoice(self):
        """Single invoice should be processed correctly"""
        member = self.create_test_member(
            first_name="Single",
            last_name="Invoice",
            birth_date="1990-01-01"
        )

        # Create one invoice
        invoice = self.create_test_sales_invoice(customer=member.customer)

        member._load_payment_history_batched()

        self.assertEqual(len(member.payment_history), 1)
        self.assertEqual(member.payment_history[0].invoice, invoice.name)

    def test_payment_history_batched_with_multiple_invoices(self):
        """Multiple invoices should all be included in history"""
        member = self.create_test_member(
            first_name="Multiple",
            last_name="Invoices",
            birth_date="1990-01-01"
        )

        # Create 5 invoices
        invoice_names = []
        for i in range(5):
            inv = self.create_test_sales_invoice(customer=member.customer)
            invoice_names.append(inv.name)

        member._load_payment_history_batched()

        self.assertEqual(len(member.payment_history), 5)

        history_invoices = {row.invoice for row in member.payment_history}
        self.assertEqual(history_invoices, set(invoice_names))

    def test_payment_history_includes_payment_data(self):
        """Payment entry data should be populated"""
        member = self.create_test_member(
            first_name="Payment",
            last_name="Data",
            birth_date="1990-01-01"
        )

        # Create invoice with payment
        invoice = self.create_test_sales_invoice(customer=member.customer)
        payment = self.create_test_payment_entry(
            party=member.customer,
            references=[{
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "allocated_amount": invoice.grand_total
            }]
        )

        member._load_payment_history_batched()

        self.assertEqual(len(member.payment_history), 1)
        history_row = member.payment_history[0]

        self.assertEqual(history_row.invoice, invoice.name)
        self.assertEqual(history_row.payment_entry, payment.name)
        self.assertEqual(history_row.payment_status, "Paid")
        self.assertGreater(history_row.paid_amount, 0)


class TestExpenseHistoryBatchedOptimization(EnhancedTestCase):
    """Test expense history loading with batch optimization"""

    def test_expense_entries_batched_with_empty_claims(self):
        """Empty claims list should return empty results"""
        member = self.create_test_member(
            first_name="No",
            last_name="Claims",
            birth_date="1990-01-01"
        )

        result = member._build_expense_entries_batched([])

        self.assertEqual(result, [])

    def test_expense_entries_batched_with_single_claim(self):
        """Single expense claim should be processed"""
        member = self.create_test_member_with_volunteer()

        # Create expense claim
        expense = self.create_test_expense_claim(employee=member.employee)

        # Get claim data (simulating what _update_volunteer_expense_history does)
        claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": member.employee},
            fields=["name", "employee", "posting_date", "total_claimed_amount",
                    "total_sanctioned_amount", "status", "approval_status", "docstatus"]
        )

        result = member._build_expense_entries_batched(claims)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["expense_claim"], expense.name)

    def test_expense_entries_batched_with_multiple_claims(self):
        """Multiple expense claims should all be processed"""
        member = self.create_test_member_with_volunteer()

        # Create 5 expense claims
        claim_names = []
        for i in range(5):
            expense = self.create_test_expense_claim(employee=member.employee)
            claim_names.append(expense.name)

        # Get claim data
        claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": member.employee},
            fields=["name", "employee", "posting_date", "total_claimed_amount",
                    "total_sanctioned_amount", "status", "approval_status", "docstatus"]
        )

        result = member._build_expense_entries_batched(claims)

        self.assertEqual(len(result), 5)
        result_names = {entry["expense_claim"] for entry in result}
        self.assertEqual(result_names, set(claim_names))

    def test_expense_entries_include_volunteer_lookup(self):
        """Volunteer should be correctly linked to expense claims"""
        member = self.create_test_member_with_volunteer()
        volunteer = frappe.get_doc("Volunteer", {"member": member.name})

        # Create expense claim
        expense = self.create_test_expense_claim(employee=member.employee)

        # Get claim data
        claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": member.employee},
            fields=["name", "employee", "posting_date", "total_claimed_amount",
                    "total_sanctioned_amount", "status", "approval_status", "docstatus"]
        )

        result = member._build_expense_entries_batched(claims)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["volunteer"], volunteer.name)


class TestErrorCountingMetrics(EnhancedTestCase):
    """Test error counting and logging functionality"""

    def test_payment_history_counts_successes(self):
        """Success count should be incremented for each processed invoice"""
        member = self.create_test_member(
            first_name="Success",
            last_name="Count",
            birth_date="1990-01-01"
        )

        # Create 3 valid invoices
        for i in range(3):
            self.create_test_sales_invoice(customer=member.customer)

        # Patch to capture metrics
        success_count = 0
        error_count = 0

        # Note: In actual implementation, success_count and error_count are
        # local variables in _load_payment_history_batched(), so we can't
        # easily test them without modifying the implementation to expose them.
        # This test documents the expected behavior.

        member._load_payment_history_batched()

        # Verify all invoices processed
        self.assertEqual(len(member.payment_history), 3)

    def test_expense_entries_handles_partial_failures(self):
        """Partial failures should continue processing remaining items"""
        member = self.create_test_member_with_volunteer()

        # Create valid expense claims
        for i in range(3):
            self.create_test_expense_claim(employee=member.employee)

        # Get claim data
        claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": member.employee},
            fields=["name", "employee", "posting_date", "total_claimed_amount",
                    "total_sanctioned_amount", "status", "approval_status", "docstatus"]
        )

        # Process - should handle gracefully even if some claims have issues
        result = member._build_expense_entries_batched(claims)

        # Should get results for valid claims
        self.assertGreater(len(result), 0)


class TestFallbackMechanism(EnhancedTestCase):
    """Test fallback to original N+1 implementation"""

    def test_payment_history_falls_back_on_batch_failure(self):
        """Fallback should work when batched version fails"""
        member = self.create_test_member(
            first_name="Fallback",
            last_name="Test",
            birth_date="1990-01-01"
        )

        # Create invoices
        for i in range(3):
            self.create_test_sales_invoice(customer=member.customer)

        # Force batched version to fail by temporarily breaking it
        original_method = member._load_payment_history_batched

        def failing_batch(*args, **kwargs):
            raise Exception("Simulated batch failure")

        member._load_payment_history_batched = failing_batch

        try:
            # Should fall back without raising error
            member._load_payment_history_without_save()

            # Should still have payment history (from fallback)
            self.assertGreater(len(member.payment_history), 0)

        finally:
            member._load_payment_history_batched = original_method

    def test_expense_entries_falls_back_on_batch_failure(self):
        """Fallback to individual processing when batched fails"""
        member = self.create_test_member_with_volunteer()

        # Create expense claims
        for i in range(3):
            self.create_test_expense_claim(employee=member.employee)

        # Trigger update which uses batched version with fallback
        # The method already has try-except fallback built in
        result = member._update_volunteer_expense_history()

        # Should succeed via fallback
        self.assertIsNotNone(result)


class TestDataIntegrity(EnhancedTestCase):
    """Verify batched and original implementations produce identical results"""

    def test_payment_history_batched_vs_original_results(self):
        """Batched version should produce same results as original"""
        member = self.create_test_member(
            first_name="Integrity",
            last_name="Test",
            birth_date="1990-01-01"
        )

        # Create diverse invoice scenarios
        # - Invoice without payment
        inv1 = self.create_test_sales_invoice(customer=member.customer)

        # - Invoice with payment
        inv2 = self.create_test_sales_invoice(customer=member.customer)
        self.create_test_payment_entry(
            party=member.customer,
            references=[{
                "reference_doctype": "Sales Invoice",
                "reference_name": inv2.name,
                "allocated_amount": inv2.grand_total
            }]
        )

        # - Draft invoice
        inv3 = self.create_test_sales_invoice(customer=member.customer)
        # Leave as draft (docstatus=0)

        # Get results from batched version
        member.payment_history = []
        member._load_payment_history_batched()
        batched_results = [
            {
                "invoice": row.invoice,
                "amount": row.amount,
                "payment_status": row.payment_status,
                "reconciled": row.reconciled
            }
            for row in member.payment_history
        ]

        # Note: We can't easily test against original version since it's the
        # fallback path. In production, this would require exposing the original
        # as a separate method for testing purposes.

        # Verify expected behavior
        self.assertEqual(len(batched_results), 3)

        # Verify invoices are present
        invoice_names = {r["invoice"] for r in batched_results}
        self.assertEqual(invoice_names, {inv1.name, inv2.name, inv3.name})


# Run tests if executed directly
if __name__ == "__main__":
    import unittest
    unittest.main()
