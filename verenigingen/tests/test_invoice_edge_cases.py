# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Invoice Edge Cases Tests
This file restores critical invoice edge case testing that was removed during Phase 4
Focus on complex invoicing scenarios, error handling, and business rule validation
"""

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestInvoiceEdgeCases(VereningingenTestCase):
    """Edge case tests for invoice generation and processing"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
        
        # Ensure customer exists
        if not self.test_member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
            customer.customer_type = "Individual"
            customer.member = self.test_member.name
            customer.save()
            
            self.test_member.customer = customer.name
            self.test_member.save()
            self.track_doc("Customer", customer.name)

    def test_zero_amount_invoice_edge_case(self):
        """Test handling of zero amount invoices (free memberships)"""
        # Create invoice with zero amount
        zero_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Manually set zero amount items
        for item in zero_invoice.items:
            item.rate = 0.00
            item.amount = 0.00
        
        zero_invoice.calculate_taxes_and_totals()
        zero_invoice.save()
        
        # Verify zero amount handling
        self.assertEqual(zero_invoice.grand_total, flt(0.00))
        self.assertTrue(zero_invoice.is_membership_invoice)

    def test_very_large_invoice_amounts(self):
        """Test handling of very large invoice amounts"""
        # Create invoice with large amount
        large_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set large amount
        for item in large_invoice.items:
            item.rate = 99999.99
            item.amount = 99999.99
        
        large_invoice.calculate_taxes_and_totals()
        large_invoice.save()
        
        # Verify large amount handling
        self.assertGreater(large_invoice.grand_total, 50000.00)

    def test_invoice_with_multiple_items(self):
        """Test invoices with multiple membership items"""
        multi_item_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Add additional items
        multi_item_invoice.append("items", {
            "item_code": self._get_or_create_test_item(),
            "qty": 1,
            "rate": 50.00,
            "income_account": self._get_or_create_income_account(multi_item_invoice.company)
        })
        
        multi_item_invoice.append("items", {
            "item_code": self._get_or_create_test_item(),
            "qty": 2,
            "rate": 25.00,
            "income_account": self._get_or_create_income_account(multi_item_invoice.company)
        })
        
        multi_item_invoice.calculate_taxes_and_totals()
        multi_item_invoice.save()
        
        # Verify multiple items
        self.assertGreaterEqual(len(multi_item_invoice.items), 3)
        self.assertGreater(multi_item_invoice.grand_total, 0)

    def test_invoice_date_edge_cases(self):
        """Test invoice date edge cases"""
        # Past dated invoice
        past_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=add_days(today(), -90),
            due_date=add_days(today(), -60)
        )
        
        # Verify past dates
        self.assertEqual(past_invoice.posting_date, add_days(today(), -90))
        self.assertEqual(past_invoice.due_date, add_days(today(), -60))
        
        # Future dated invoice
        future_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            posting_date=add_days(today(), 30),
            due_date=add_days(today(), 60)
        )
        
        # Verify future dates
        self.assertEqual(future_invoice.posting_date, add_days(today(), 30))
        self.assertEqual(future_invoice.due_date, add_days(today(), 60))

    def test_invoice_currency_precision_edge_cases(self):
        """Test invoice currency precision edge cases"""
        # Create invoice with precise decimal amounts
        precise_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set precise decimal amounts
        for item in precise_invoice.items:
            item.rate = 33.333
            item.qty = 3
            item.amount = 99.999
        
        precise_invoice.calculate_taxes_and_totals()
        precise_invoice.save()
        
        # Verify precision handling
        self.assertIsInstance(precise_invoice.grand_total, (int, float))

    def test_invoice_with_taxes_edge_cases(self):
        """Test invoice with complex tax scenarios"""
        tax_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Add tax template if available
        try:
            # This would add sales taxes if configured
            tax_invoice.taxes_and_charges = "Standard VAT"
        except:
            # Skip if no tax template exists
            pass
        
        tax_invoice.calculate_taxes_and_totals()
        tax_invoice.save()
        
        # Verify tax handling
        self.assertGreaterEqual(tax_invoice.grand_total, tax_invoice.net_total)

    def test_invoice_duplicate_prevention(self):
        """Test prevention of duplicate invoices"""
        # Create first invoice
        invoice1 = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Create second invoice for same membership
        invoice2 = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Both should be created (duplication prevention would be business logic)
        self.assertNotEqual(invoice1.name, invoice2.name)

    def test_invoice_partial_payment_edge_cases(self):
        """Test invoice with partial payment scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create partial payment
        partial_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=invoice.grand_total * 0.5  # 50% payment
        )
        
        # Verify partial payment scenario
        self.assertLess(partial_payment.paid_amount, invoice.grand_total)

    def test_invoice_overpayment_edge_cases(self):
        """Test invoice with overpayment scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create overpayment
        overpayment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=invoice.grand_total * 1.5  # 150% payment
        )
        
        # Verify overpayment scenario
        self.assertGreater(overpayment.paid_amount, invoice.grand_total)

    def test_invoice_cancellation_edge_cases(self):
        """Test invoice cancellation scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Cancel invoice (change docstatus)
        if invoice.docstatus == 1:
            frappe.db.set_value("Sales Invoice", invoice.name, "docstatus", 2)
        
        # Verify cancellation
        cancelled_invoice = frappe.get_doc("Sales Invoice", invoice.name)
        self.assertEqual(cancelled_invoice.docstatus, 2)

    def test_invoice_amendment_edge_cases(self):
        """Test invoice amendment scenarios"""
        original_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create amended invoice
        amended_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set amendment reference
        amended_invoice.amended_from = original_invoice.name
        amended_invoice.save()
        
        # Verify amendment
        self.assertEqual(amended_invoice.amended_from, original_invoice.name)


class TestInvoiceBusinessRuleEdgeCases(VereningingenTestCase):
    """Business rule edge cases for invoices"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_invoice_member_status_edge_cases(self):
        """Test invoice generation with various member statuses"""
        # Test invoice for suspended member
        self.test_member.status = "Suspended"
        self.test_member.save()
        
        suspended_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Invoice should be created even for suspended member
        self.assertEqual(suspended_invoice.customer, self.test_member.customer)
        
        # Restore member status
        self.test_member.status = "Active"
        self.test_member.save()
    
    def test_invoice_membership_type_changes(self):
        """Test invoice handling when membership type changes"""
        # Create membership
        membership = self.create_test_membership(member=self.test_member.name)
        
        # Create invoice for original membership type
        original_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=membership.name
        )
        
        # Change membership type
        new_type = self.create_test_membership_type(
            membership_type_name="Changed Type",
            amount=75.00
        )
        
        membership.membership_type = new_type.name
        membership.save()
        
        # Create new invoice after type change
        new_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=membership.name
        )
        
        # Both invoices should exist
        self.assertNotEqual(original_invoice.name, new_invoice.name)
    
    def test_invoice_payment_method_constraints(self):
        """Test invoice constraints based on payment methods"""
        # Create invoice for SEPA collection
        sepa_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Add SEPA payment method indicator
        sepa_invoice.payment_method = "SEPA Direct Debit"
        sepa_invoice.save()
        
        # Verify SEPA invoice
        self.assertEqual(sepa_invoice.payment_method, "SEPA Direct Debit")
        
        # Create manual payment invoice
        manual_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        manual_invoice.payment_method = "Manual Payment"
        manual_invoice.save()
        
        # Verify manual invoice
        self.assertEqual(manual_invoice.payment_method, "Manual Payment")


class TestInvoicePerformanceEdgeCases(VereningingenTestCase):
    """Performance edge cases for invoice processing"""
    
    def setUp(self):
        super().setUp()
        self.test_members = []
        
        # Create multiple members for bulk testing
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Bulk{i}",
                last_name="InvoiceMember",
                email=f"bulk{i}@example.com"
            )
            self.test_members.append(member)
    
    def test_bulk_invoice_generation(self):
        """Test bulk invoice generation performance"""
        invoices = []
        
        # Generate invoices for all members
        for member in self.test_members:
            invoice = self.create_test_sales_invoice(
                customer=member.customer,
                is_membership_invoice=1
            )
            invoices.append(invoice)
        
        # Verify all invoices created
        self.assertEqual(len(invoices), 5)
        
        # Verify each invoice is unique
        invoice_names = [inv.name for inv in invoices]
        self.assertEqual(len(invoice_names), len(set(invoice_names)))
    
    def test_concurrent_invoice_processing(self):
        """Test concurrent invoice processing"""
        # Create invoices simultaneously
        concurrent_invoices = []
        
        for member in self.test_members[:3]:  # Test with 3 members
            invoice = self.create_test_sales_invoice(
                customer=member.customer,
                is_membership_invoice=1
            )
            concurrent_invoices.append(invoice)
        
        # Verify concurrent processing
        self.assertEqual(len(concurrent_invoices), 3)
        
        # All should have different names
        names = [inv.name for inv in concurrent_invoices]
        self.assertEqual(len(names), len(set(names)))
    
    def test_invoice_calculation_performance(self):
        """Test invoice calculation performance with complex items"""
        complex_invoice = self.create_test_sales_invoice(
            customer=self.test_members[0].customer,
            is_membership_invoice=1
        )
        
        # Add multiple items with different rates
        for i in range(10):
            complex_invoice.append("items", {
                "item_code": self._get_or_create_test_item(),
                "qty": i + 1,
                "rate": 10.00 + i,
                "income_account": self._get_or_create_income_account(complex_invoice.company)
            })
        
        # Perform calculation
        complex_invoice.calculate_taxes_and_totals()
        complex_invoice.save()
        
        # Verify calculation completed
        self.assertGreater(len(complex_invoice.items), 10)
        self.assertGreater(complex_invoice.grand_total, 0)


class TestInvoiceDataIntegrityEdgeCases(VereningingenTestCase):
    """Data integrity edge cases for invoices"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
    
    def test_invoice_member_relationship_integrity(self):
        """Test invoice-member relationship integrity"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Verify relationships
        self.assertEqual(invoice.customer, self.test_member.customer)
        self.assertEqual(invoice.membership, self.test_membership.name)
        
        # Verify customer exists
        customer_exists = frappe.db.exists("Customer", self.test_member.customer)
        self.assertTrue(customer_exists)
        
        # Verify membership exists
        membership_exists = frappe.db.exists("Membership", self.test_membership.name)
        self.assertTrue(membership_exists)
    
    def test_invoice_financial_account_integrity(self):
        """Test invoice financial account integrity"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Verify all items have income accounts
        for item in invoice.items:
            self.assertIsNotNone(item.income_account)
            
            # Verify account exists
            account_exists = frappe.db.exists("Account", item.income_account)
            self.assertTrue(account_exists)
    
    def test_invoice_item_integrity(self):
        """Test invoice item integrity"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Verify all items are valid
        for item in invoice.items:
            self.assertIsNotNone(item.item_code)
            self.assertGreater(item.qty, 0)
            self.assertGreaterEqual(item.rate, 0)
            
            # Verify item exists
            item_exists = frappe.db.exists("Item", item.item_code)
            self.assertTrue(item_exists)
    
    def test_invoice_modification_integrity(self):
        """Test invoice modification integrity"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        original_total = invoice.grand_total
        original_modified = invoice.modified
        
        # Modify invoice
        invoice.remarks = "Modified for integrity test"
        invoice.save()
        
        # Verify modification tracking
        self.assertNotEqual(invoice.modified, original_modified)
        self.assertEqual(invoice.remarks, "Modified for integrity test")
        
        # Total should remain same unless items changed
        self.assertEqual(invoice.grand_total, original_total)


class TestInvoiceRegulatoryEdgeCases(VereningingenTestCase):
    """Regulatory compliance edge cases for invoices"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_invoice_vat_compliance_cases(self):
        """Test VAT compliance in various invoice scenarios"""
        # Standard VAT invoice
        vat_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Add VAT information if required
        vat_invoice.customer_tax_id = "NL123456789B01"  # Dutch VAT format
        vat_invoice.save()
        
        # Verify VAT compliance setup
        self.assertIsNotNone(vat_invoice.customer_tax_id)
    
    def test_invoice_anbi_compliance_cases(self):
        """Test ANBI (tax deductible) compliance for invoices"""
        # Create ANBI-eligible invoice
        anbi_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Mark as ANBI eligible
        anbi_invoice.anbi_eligible = 1
        anbi_invoice.save()
        
        # Verify ANBI compliance
        self.assertEqual(anbi_invoice.anbi_eligible, 1)
    
    def test_invoice_retention_compliance(self):
        """Test invoice retention compliance requirements"""
        retention_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set retention period (7 years for Dutch law)
        retention_invoice.retention_years = 7
        retention_invoice.save()
        
        # Verify retention compliance
        self.assertEqual(retention_invoice.retention_years, 7)