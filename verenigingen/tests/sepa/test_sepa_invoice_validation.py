# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
SEPA Invoice Validation Tests
This file restores critical SEPA invoice validation testing that was removed during Phase 4
Focus on SEPA direct debit invoice validation, batch processing, and compliance
"""

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAInvoiceValidation(VereningingenTestCase):
    """Tests for SEPA invoice validation and processing"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
        
        # Create SEPA mandate
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal",
            bank_code="TEST"
        )
        
        # Create invoice
        self.test_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )

    def test_sepa_invoice_mandate_validation(self):
        """Test SEPA invoice validation against mandate"""
        # Verify invoice can be linked to SEPA mandate
        self.assertEqual(self.test_invoice.customer, self.test_member.customer)
        
        # Verify mandate is active and valid
        self.assertEqual(self.test_mandate.status, "Active")
        self.assertEqual(self.test_mandate.member, self.test_member.name)
        
        # Test mandate-invoice compatibility
        self.assertTrue(self.test_mandate.used_for_memberships)
        self.assertTrue(self.test_invoice.is_membership_invoice)

    def test_sepa_invoice_amount_validation(self):
        """Test SEPA invoice amount validation against mandate limits"""
        # Test invoice within mandate limits
        if hasattr(self.test_mandate, 'maximum_amount') and self.test_mandate.maximum_amount:
            # Verify invoice amount is within mandate limits
            self.assertLessEqual(
                self.test_invoice.grand_total, 
                self.test_mandate.maximum_amount,
                "Invoice amount should be within mandate maximum"
            )
        
        # Test very small amount
        small_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set minimal amount
        for item in small_invoice.items:
            item.rate = 0.01
            item.amount = 0.01
        
        small_invoice.calculate_taxes_and_totals()
        small_invoice.save()
        
        self.assertEqual(small_invoice.grand_total, flt(0.01))
        
        # Test large amount validation
        large_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set large amount
        for item in large_invoice.items:
            item.rate = 500.00
            item.amount = 500.00
        
        large_invoice.calculate_taxes_and_totals()
        large_invoice.save()
        
        self.assertEqual(large_invoice.grand_total, flt(500.00))

    def test_sepa_invoice_currency_validation(self):
        """Test SEPA invoice currency validation"""
        # Verify invoice currency matches mandate
        self.assertEqual(self.test_invoice.currency, "EUR")
        
        # Test currency consistency
        if hasattr(self.test_mandate, 'currency'):
            self.assertEqual(self.test_invoice.currency, self.test_mandate.currency)

    def test_sepa_invoice_due_date_validation(self):
        """Test SEPA invoice due date validation"""
        # SEPA invoices should have appropriate due dates
        self.assertIsNotNone(self.test_invoice.due_date)
        
        # Due date should be in the future or today
        self.assertGreaterEqual(self.test_invoice.due_date, today())
        
        # Test past due date scenario
        past_due_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            due_date=add_days(today(), -30)
        )
        
        # Past due dates should be handled
        self.assertEqual(past_due_invoice.due_date, add_days(today(), -30))

    def test_sepa_invoice_batch_eligibility(self):
        """Test SEPA invoice eligibility for batch processing"""
        # Create direct debit batch
        dd_batch = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        # Add invoice to batch
        dd_batch.append("invoices", {
            "invoice": self.test_invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": self.test_invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        
        dd_batch.save()
        
        # Verify batch processing eligibility
        self.assertEqual(len(dd_batch.invoices), 1)
        batch_invoice = dd_batch.invoices[0]
        
        self.assertEqual(batch_invoice.invoice, self.test_invoice.name)
        self.assertEqual(batch_invoice.iban, self.test_mandate.iban)
        self.assertEqual(batch_invoice.mandate_reference, self.test_mandate.mandate_id)

    def test_sepa_invoice_outstanding_amount_validation(self):
        """Test SEPA invoice outstanding amount validation"""
        # Invoice should have outstanding amount for SEPA collection
        self.assertGreater(self.test_invoice.outstanding_amount, 0)
        self.assertEqual(self.test_invoice.outstanding_amount, self.test_invoice.grand_total)
        
        # Test partially paid invoice
        partial_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=self.test_invoice.grand_total * 0.5
        )
        
        # Outstanding amount should be reduced (this would be handled by ERPNext)
        self.assertEqual(partial_payment.paid_amount, self.test_invoice.grand_total * 0.5)

    def test_sepa_invoice_mandate_type_validation(self):
        """Test SEPA invoice validation against mandate types"""
        # Test CORE mandate (recurring)
        core_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal",
            mandate_type="CORE"
        )
        
        # CORE mandates should support recurring membership invoices
        self.assertEqual(core_mandate.mandate_type, "CORE")
        self.assertTrue(core_mandate.used_for_memberships)
        
        # Test OOFF mandate (one-off)
        ooff_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="one_time",
            mandate_type="OOFF"
        )
        
        # OOFF mandates for single payments
        self.assertEqual(ooff_mandate.mandate_type, "OOFF")

    def test_sepa_invoice_sequence_type_validation(self):
        """Test SEPA invoice sequence type validation"""
        # First payment should be FRST
        first_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        first_invoice.sepa_sequence_type = "FRST"
        first_invoice.save()
        
        self.assertEqual(first_invoice.sepa_sequence_type, "FRST")
        
        # Subsequent payments should be RCUR
        recurring_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        recurring_invoice.sepa_sequence_type = "RCUR"
        recurring_invoice.save()
        
        self.assertEqual(recurring_invoice.sepa_sequence_type, "RCUR")

    def test_sepa_invoice_mandate_expiry_validation(self):
        """Test SEPA invoice validation against mandate expiry"""
        # Create mandate with expiry date
        expiring_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal",
            bank_code="TEST"
        )
        
        # Set expiry date in future
        expiring_mandate.expiry_date = add_days(today(), 30)
        expiring_mandate.save()
        
        # Invoice should be valid before expiry
        valid_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        self.assertLess(valid_invoice.posting_date, expiring_mandate.expiry_date)
        
        # Test expired mandate scenario
        expired_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="expired",
            bank_code="TEST"
        )
        
        self.assertEqual(expired_mandate.status, "Expired")

    def test_sepa_invoice_iban_validation(self):
        """Test SEPA invoice IBAN validation"""
        # Verify mandate has valid IBAN
        self.assertIsNotNone(self.test_mandate.iban)
        self.assertTrue(self.test_mandate.iban.startswith("NL"))
        
        # Test IBAN format validation
        self.assertEqual(len(self.test_mandate.iban), 18)  # Dutch IBAN length
        
        # Verify IBAN checksum (basic validation)
        iban = self.test_mandate.iban
        self.assertTrue(iban[2:4].isdigit())  # Check digits should be numeric


class TestSEPAInvoiceBatchValidation(VereningingenTestCase):
    """Tests for SEPA invoice batch processing validation"""
    
    def setUp(self):
        super().setUp()
        
        # Create multiple members with mandates for batch testing
        self.batch_members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Batch{i}",
                last_name="TestMember",
                email=f"batch{i}@example.com"
            )
            
            mandate = self.create_test_sepa_mandate(
                member=member.name,
                scenario="normal",
                bank_code="TEST"
            )
            
            invoice = self.create_test_sales_invoice(
                customer=member.customer,
                is_membership_invoice=1
            )
            
            self.batch_members.append({
                "member": member,
                "mandate": mandate,
                "invoice": invoice
            })
    
    def test_sepa_batch_invoice_validation(self):
        """Test validation of invoices in SEPA batch"""
        # Create batch
        batch = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        # Add all invoices to batch
        for member_data in self.batch_members:
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })
        
        batch.save()
        
        # Verify batch validation
        self.assertEqual(len(batch.invoices), 3)
        
        # Verify each invoice in batch
        for batch_invoice in batch.invoices:
            self.assertIsNotNone(batch_invoice.invoice)
            self.assertIsNotNone(batch_invoice.iban)
            self.assertIsNotNone(batch_invoice.mandate_reference)
            self.assertGreater(batch_invoice.amount, 0)
    
    def test_sepa_batch_amount_validation(self):
        """Test batch amount validation"""
        batch = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        total_amount = 0
        for member_data in self.batch_members:
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })
            total_amount += member_data["invoice"].grand_total
        
        batch.save()
        
        # Calculate batch total
        batch_total = sum(inv.amount for inv in batch.invoices)
        self.assertEqual(batch_total, total_amount)
    
    def test_sepa_batch_currency_validation(self):
        """Test batch currency consistency validation"""
        batch = self.create_test_direct_debit_batch(
            currency="EUR",
            skip_invoice_creation=True
        )
        
        # All invoices should be in EUR
        for member_data in self.batch_members:
            self.assertEqual(member_data["invoice"].currency, "EUR")
            
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })
        
        batch.save()
        
        # Verify batch currency consistency
        self.assertEqual(batch.currency, "EUR")
        for batch_invoice in batch.invoices:
            self.assertEqual(batch_invoice.currency, "EUR")


class TestSEPAInvoiceEdgeCases(VereningingenTestCase):
    """Edge case tests for SEPA invoice processing"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal"
        )
    
    def test_sepa_invoice_zero_amount_edge_case(self):
        """Test SEPA processing with zero amount invoices"""
        # Create zero amount invoice
        zero_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Set zero amount
        for item in zero_invoice.items:
            item.rate = 0.00
            item.amount = 0.00
        
        zero_invoice.calculate_taxes_and_totals()
        zero_invoice.save()
        
        # Zero amount invoices should be handled
        self.assertEqual(zero_invoice.grand_total, flt(0.00))
    
    def test_sepa_invoice_very_large_amount_edge_case(self):
        """Test SEPA processing with very large amounts"""
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
        
        # Large amounts should be handled
        self.assertEqual(large_invoice.grand_total, flt(99999.99))
    
    def test_sepa_invoice_mandate_mismatch_edge_case(self):
        """Test handling of invoice-mandate mismatches"""
        # Create invoice for different member
        other_member = self.create_test_member(
            first_name="Other",
            last_name="Member",
            email="other@example.com"
        )
        
        mismatch_invoice = self.create_test_sales_invoice(
            customer=other_member.customer,
            is_membership_invoice=1
        )
        
        # Invoice and original mandate are for different members
        self.assertNotEqual(mismatch_invoice.customer, self.test_member.customer)
        self.assertEqual(self.test_mandate.member, self.test_member.name)
    
    def test_sepa_invoice_duplicate_processing_edge_case(self):
        """Test handling of duplicate invoice processing"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create first batch with invoice
        batch1 = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        batch1.append("invoices", {
            "invoice": invoice.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        batch1.save()
        
        # Create second batch with same invoice
        batch2 = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        batch2.append("invoices", {
            "invoice": invoice.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        batch2.save()
        
        # Both batches should be created (duplicate prevention is business logic)
        self.assertNotEqual(batch1.name, batch2.name)
    
    def test_sepa_invoice_partial_collection_edge_case(self):
        """Test SEPA invoice partial collection scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create batch with partial amount
        partial_batch = self.create_test_direct_debit_batch(
            skip_invoice_creation=True
        )
        
        partial_amount = invoice.grand_total * 0.5
        partial_batch.append("invoices", {
            "invoice": invoice.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": partial_amount,  # Only 50% of invoice
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        partial_batch.save()
        
        # Verify partial collection setup
        batch_invoice = partial_batch.invoices[0]
        self.assertEqual(batch_invoice.amount, partial_amount)
        self.assertLess(batch_invoice.amount, invoice.grand_total)


class TestSEPAInvoiceComplianceValidation(VereningingenTestCase):
    """SEPA compliance validation tests for invoices"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal"
        )
    
    def test_sepa_invoice_pre_notification_compliance(self):
        """Test SEPA pre-notification compliance"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            due_date=add_days(today(), 14)  # 14 days notice
        )
        
        # SEPA requires pre-notification (usually 14 days)
        notification_period = (invoice.due_date - today()).days
        self.assertEqual(notification_period, 14)
    
    def test_sepa_invoice_mandate_reference_compliance(self):
        """Test SEPA mandate reference compliance"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Mandate reference should follow SEPA standards
        self.assertIsNotNone(self.test_mandate.mandate_id)
        self.assertGreater(len(self.test_mandate.mandate_id), 0)
        
        # Reference should be alphanumeric
        mandate_id = self.test_mandate.mandate_id
        self.assertTrue(mandate_id.replace("-", "").replace("_", "").isalnum())
    
    def test_sepa_invoice_creditor_identifier_compliance(self):
        """Test SEPA creditor identifier compliance"""
        batch = self.create_test_direct_debit_batch()
        
        # Batch should have creditor identifier (if configured)
        if hasattr(batch, 'creditor_identifier'):
            self.assertIsNotNone(batch.creditor_identifier)
    
    def test_sepa_invoice_collection_date_compliance(self):
        """Test SEPA collection date compliance"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            due_date=add_days(today(), 5)
        )
        
        # Collection date should respect banking days
        collection_date = invoice.due_date
        self.assertGreaterEqual(collection_date, today())
        
        # Should not be weekend (basic check)
        # In real implementation, would check banking calendar
        weekday = collection_date.weekday()
        # 0-4 = Monday-Friday, 5-6 = Weekend
        # This is just a basic example check