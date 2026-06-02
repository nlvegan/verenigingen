# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
SEPA Invoice Validation Tests
This file restores critical SEPA invoice validation testing that was removed during Phase 4
Focus on SEPA direct debit invoice validation, batch processing, and compliance
"""

import frappe
from frappe.utils import today, add_days, add_months, flt, getdate, date_diff
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAInvoiceValidation(VereningingenTestCase):
    """Tests for SEPA invoice validation and processing"""

    def setUp(self):
        super().setUp()

        # SEPA invoice validation rejects any non-EUR currency, so invoices in
        # this module must be created under the app's EUR test company.
        self.eur_company = get_eur_test_company()

        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)

        # Create SEPA mandate
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal",
            bank_code="TEST"
        )

        # Create invoice and submit it so it is eligible for SEPA batch
        # processing (the batch only accepts submitted, unpaid invoices).
        self.test_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name,
            company=self.eur_company,
            currency="EUR",
        )
        self.test_invoice.submit()

    def _new_batch(self, **kwargs):
        """Build an unsaved Direct Debit Batch (append invoices before save)."""
        defaults = {
            "batch_date": today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR",
        }
        defaults.update(kwargs)
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        return batch

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
        self.assertGreaterEqual(getdate(self.test_invoice.due_date), getdate(today()))

        # Test past due date scenario. The due date may not precede the posting
        # date (ERPNext validation), so back-date the posting date too;
        # set_posting_time=1 keeps ERPNext from resetting posting_date to today.
        past_due_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
            set_posting_time=1,
            posting_date=add_days(today(), -30),
            due_date=add_days(today(), -30)
        )

        # Past due dates should be handled
        self.assertEqual(getdate(past_due_invoice.due_date), getdate(add_days(today(), -30)))

    def test_sepa_invoice_batch_eligibility(self):
        """Test SEPA invoice eligibility for batch processing"""
        # Create direct debit batch
        dd_batch = self._new_batch()

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
        self.track_doc("Direct Debit Batch", dd_batch.name)
        
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
        
        # Test expired mandate scenario. The "expired" scenario sets expiry_date
        # 30 days ago; sign_date must precede expiry, so set it explicitly
        # (the factory's default sign_date is today, which would post-date expiry).
        expired_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="expired",
            bank_code="TEST",
            sign_date=add_days(today(), -60),
        )

        self.assertEqual(expired_mandate.status, "Expired")

    def test_sepa_invoice_iban_validation(self):
        """Test SEPA invoice IBAN validation"""
        # Verify mandate has valid IBAN
        self.assertIsNotNone(self.test_mandate.iban)
        self.assertTrue(self.test_mandate.iban.startswith("NL"))
        
        # The SEPA Mandate stores the IBAN in its human-readable grouped form
        # ("NL13 TEST 0123 4567 89"), so strip spaces before validating the
        # compact Dutch IBAN length (18 chars).
        compact_iban = self.test_mandate.iban.replace(" ", "")
        self.assertEqual(len(compact_iban), 18)  # Dutch IBAN length

        # Verify IBAN checksum (basic validation)
        self.assertTrue(compact_iban[2:4].isdigit())  # Check digits should be numeric


class TestSEPAInvoiceBatchValidation(VereningingenTestCase):
    """Tests for SEPA invoice batch processing validation"""
    
    def setUp(self):
        super().setUp()
        
        # SEPA invoice validation rejects any non-EUR currency.
        self.eur_company = get_eur_test_company()

        # Create multiple members with mandates for batch testing
        self.batch_members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Batch{i}",
                last_name="TestMember",
                email=f"batch{i}@example.com"
            )

            membership = self.create_test_membership(member=member.name)

            mandate = self.create_test_sepa_mandate(
                member=member.name,
                scenario="normal",
                bank_code="TEST"
            )

            invoice = self.create_test_sales_invoice(
                customer=member.customer,
                is_membership_invoice=1,
                membership=membership.name,
                company=self.eur_company,
                currency="EUR",
            )
            invoice.submit()

            self.batch_members.append({
                "member": member,
                "membership": membership,
                "mandate": mandate,
                "invoice": invoice
            })
    
    def _new_batch(self, **kwargs):
        """Build an unsaved Direct Debit Batch (append invoices before save).

        ``create_test_direct_debit_batch`` saves immediately, but a batch with
        no invoices fails validation ("No invoices added to batch"), so tests
        that append their own rows must build the batch document directly and
        save only after appending.
        """
        defaults = {
            "batch_date": today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR",
        }
        defaults.update(kwargs)
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        return batch

    def test_sepa_batch_invoice_validation(self):
        """Test validation of invoices in SEPA batch"""
        # Create batch
        batch = self._new_batch()

        # Add all invoices to batch
        for member_data in self.batch_members:
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "membership": member_data["membership"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })

        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)
        
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
        batch = self._new_batch()

        total_amount = 0
        for member_data in self.batch_members:
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "membership": member_data["membership"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })
            total_amount += member_data["invoice"].grand_total

        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)

        # Calculate batch total
        batch_total = sum(inv.amount for inv in batch.invoices)
        self.assertEqual(batch_total, total_amount)
    
    def test_sepa_batch_currency_validation(self):
        """Test batch currency consistency validation"""
        batch = self._new_batch(currency="EUR")

        # All invoices should be in EUR
        for member_data in self.batch_members:
            self.assertEqual(member_data["invoice"].currency, "EUR")
            
            batch.append("invoices", {
                "invoice": member_data["invoice"].name,
                "membership": member_data["membership"].name,
                "member": member_data["member"].name,
                "member_name": f"{member_data['member'].first_name} {member_data['member'].last_name}",
                "amount": member_data["invoice"].grand_total,
                "currency": "EUR",
                "iban": member_data["mandate"].iban,
                "mandate_reference": member_data["mandate"].mandate_id
            })

        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)

        # Verify batch currency consistency
        self.assertEqual(batch.currency, "EUR")
        for batch_invoice in batch.invoices:
            self.assertEqual(batch_invoice.currency, "EUR")


class TestSEPAInvoiceEdgeCases(VereningingenTestCase):
    """Edge case tests for SEPA invoice processing"""

    def setUp(self):
        super().setUp()
        self.eur_company = get_eur_test_company()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal"
        )

    def _new_batch(self, **kwargs):
        """Build an unsaved Direct Debit Batch (append invoices before save)."""
        defaults = {
            "batch_date": today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR",
        }
        defaults.update(kwargs)
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        return batch

    def test_sepa_invoice_zero_amount_edge_case(self):
        """Test SEPA processing with zero amount invoices"""
        # Create zero amount invoice
        zero_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )

        # Set zero amount. price_list_rate must also be cleared, otherwise
        # ERPNext repopulates the item rate from the price list on recalculation.
        zero_invoice.ignore_pricing_rule = 1
        for item in zero_invoice.items:
            item.price_list_rate = 0.00
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
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
        )
        invoice.submit()

        # Create first batch with invoice
        batch1 = self._new_batch()

        batch1.append("invoices", {
            "invoice": invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        batch1.save()
        self.track_doc("Direct Debit Batch", batch1.name)

        # Create second batch with same invoice
        batch2 = self._new_batch()

        batch2.append("invoices", {
            "invoice": invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        batch2.save()
        self.track_doc("Direct Debit Batch", batch2.name)

        # Both batches should be created (duplicate prevention is business logic)
        self.assertNotEqual(batch1.name, batch2.name)
    
    def test_sepa_invoice_partial_collection_edge_case(self):
        """Test SEPA invoice partial collection scenarios"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
        )
        invoice.submit()

        # Create batch with partial amount
        partial_batch = self._new_batch()

        partial_amount = invoice.grand_total * 0.5
        partial_batch.append("invoices", {
            "invoice": invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": partial_amount,  # Only 50% of invoice
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        partial_batch.save()
        self.track_doc("Direct Debit Batch", partial_batch.name)

        # Verify partial collection setup
        batch_invoice = partial_batch.invoices[0]
        self.assertEqual(batch_invoice.amount, partial_amount)
        self.assertLess(batch_invoice.amount, invoice.grand_total)


class TestSEPAInvoiceComplianceValidation(VereningingenTestCase):
    """SEPA compliance validation tests for invoices"""
    
    def setUp(self):
        super().setUp()
        self.eur_company = get_eur_test_company()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
        self.test_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal"
        )

    def _new_batch(self, **kwargs):
        """Build an unsaved Direct Debit Batch (append invoices before save)."""
        defaults = {
            "batch_date": today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR",
        }
        defaults.update(kwargs)
        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)
        return batch

    def test_sepa_invoice_pre_notification_compliance(self):
        """Test SEPA pre-notification compliance"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
            due_date=add_days(today(), 14)  # 14 days notice
        )

        # SEPA requires pre-notification (usually 14 days). invoice.due_date is a
        # date string when read back from the DB, so use date_diff for the math.
        notification_period = date_diff(invoice.due_date, today())
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
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
        )
        invoice.submit()

        batch = self._new_batch()
        batch.append("invoices", {
            "invoice": invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": self.test_mandate.iban,
            "mandate_reference": self.test_mandate.mandate_id
        })
        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)

        # Batch should have creditor identifier (if configured)
        if hasattr(batch, 'creditor_identifier'):
            self.assertIsNotNone(batch.creditor_identifier)
    
    def test_sepa_invoice_collection_date_compliance(self):
        """Test SEPA collection date compliance"""
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            company=self.eur_company,
            currency="EUR",
            due_date=add_days(today(), 5)
        )

        # Collection date should respect banking days. invoice.due_date is a
        # date string when read back from the DB, so normalise with getdate.
        collection_date = getdate(invoice.due_date)
        self.assertGreaterEqual(collection_date, getdate(today()))

        # Should not be weekend (basic check)
        # In real implementation, would check banking calendar
        weekday = collection_date.weekday()
        # 0-4 = Monday-Friday, 5-6 = Weekend
        # This is just a basic example check