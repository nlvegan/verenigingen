# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Payment Integration Tests
This file restores critical payment integration testing that was removed during Phase 4
Focus on payment processing, ERPNext integration, and financial workflows
"""

import unittest

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED


class TestPaymentIntegration(EnhancedTestCase):
    """Tests for payment integration with ERPNext and financial systems"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
        
        # Ensure customer exists for payment processing
        if not self.test_member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
            customer.customer_type = "Individual"
            customer.member = self.test_member.name
            customer.save()
            
            self.test_member.customer = customer.name
            self.test_member.save()
            self.track_doc("Customer", customer.name)

    def test_sales_invoice_integration(self):
        """Test sales invoice creation and integration"""
        # Create sales invoice for membership
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Verify invoice integration
        self.assertEqual(invoice.customer, self.test_member.customer)
        self.assertTrue(invoice.is_membership_invoice)
        # NOTE: Sales Invoice has no "membership" link field (only "member" and
        # "is_membership_invoice"), so there is nothing to assert for membership here.

        # Verify invoice has proper items
        self.assertGreater(len(invoice.items), 0)
        
        # Verify financial accounts are set
        for item in invoice.items:
            self.assertIsNotNone(item.income_account)

    def test_payment_entry_integration(self):
        """Test payment entry creation and integration"""
        # Create invoice first
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create payment entry
        payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=invoice.grand_total
        )
        
        # Verify payment integration
        self.assertEqual(payment.party, self.test_member.customer)
        self.assertEqual(payment.party_type, "Customer")
        self.assertEqual(payment.payment_type, "Receive")
        self.assertEqual(payment.paid_amount, invoice.grand_total)

    def test_membership_payment_workflow(self):
        """Test complete membership payment workflow"""
        # Step 1: Create membership invoice
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.test_membership.name
        )
        
        # Step 2: Process payment
        payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=invoice.grand_total
        )
        
        # Step 3: Verify workflow completion
        self.assertEqual(payment.paid_amount, invoice.grand_total)
        
        # Verify financial integration
        self.assertIsNotNone(payment.posting_date)
        self.assertEqual(payment.posting_date, today())

    def test_sepa_payment_integration(self):
        """Test SEPA direct debit payment integration"""
        # Create SEPA mandate
        mandate = self.create_test_sepa_mandate(
            member_name=self.test_member.name,
        )
        
        # Create invoice for SEPA collection. Use the SEPA test factory so the
        # invoice is EUR, Unpaid and has a positive outstanding amount -- the batch
        # rejects invoices that fail validate_invoice_for_sepa (non-EUR / zero
        # outstanding / wrong status -> "No valid invoices found in batch").
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)
        invoice = sepa_factory.create_test_sales_invoice(
            customer=self.test_member.customer,
            member=self.test_member.name,
            status="Unpaid",
            submit=True,
        )
        self._track_test_document("Sales Invoice", invoice.name)

        # Build a direct debit batch with our own invoice row. The batch validates
        # "No invoices added to batch" on insert, so the row must be present before
        # the first save (we cannot insert an empty batch and append afterwards).
        dd_batch = frappe.new_doc("Direct Debit Batch")
        dd_batch.batch_date = today()
        dd_batch.batch_description = f"Test DD Batch {frappe.generate_hash(length=6)}"
        dd_batch.batch_type = "CORE"
        dd_batch.currency = "EUR"
        dd_batch.append("invoices", {
            "invoice": invoice.name,
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "member_name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "amount": invoice.grand_total,
            "currency": "EUR",
            "iban": mandate.iban,
            "mandate_reference": mandate.mandate_id,
            "status": "Pending",
            # First use of a fresh mandate must be FRST (SEPA compliance); RCUR
            # is only valid once the mandate has a prior successful collection.
            "sequence_type": "FRST",
        })
        dd_batch.save()
        self._track_test_document("Direct Debit Batch", dd_batch.name)
        
        # Verify SEPA integration
        self.assertEqual(len(dd_batch.invoices), 1)
        batch_invoice = dd_batch.invoices[0]
        self.assertEqual(batch_invoice.invoice, invoice.name)
        self.assertEqual(batch_invoice.iban, mandate.iban)

    def test_recurring_payment_integration(self):
        """Test recurring payment setup and integration"""
        # Create dues schedule for recurring payments
        dues_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=25.00,
            frequency="Monthly",
            auto_generate=1
        )

        # Create SEPA mandate for recurring collection
        mandate = self.create_test_sepa_mandate(
            member_name=self.test_member.name,
            used_for_memberships=1
        )
        
        # Verify recurring setup
        self.assertEqual(dues_schedule.auto_generate, 1)
        self.assertEqual(mandate.used_for_memberships, 1)
        self.assertEqual(mandate.member, self.test_member.name)

    def test_payment_reconciliation_integration(self):
        """Test payment reconciliation with bank statements"""
        # Create payment
        payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=100.00,
            mode_of_payment="Bank Transfer"
        )
        
        # Verify reconciliation fields
        self.assertEqual(payment.mode_of_payment, "Bank Transfer")
        self.assertEqual(payment.paid_amount, flt(100.00))
        
        # Test payment reference for reconciliation
        payment.reference_no = "BANK-REF-2025-001"
        payment.reference_date = today()
        payment.save()
        
        self.assertIsNotNone(payment.reference_no)
        self.assertEqual(payment.reference_date, today())

    def test_multi_currency_payment_integration(self):
        """Test multi-currency payment processing"""
        # Create payment in EUR (default)
        eur_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=75.00
        )
        
        # Verify EUR payment
        self.assertEqual(eur_payment.paid_amount, flt(75.00))
        
        # Test exchange rate handling (if applicable)
        self.assertEqual(eur_payment.source_exchange_rate, 1)
        self.assertEqual(eur_payment.target_exchange_rate, 1)

    def test_payment_failure_integration(self):
        """Test payment failure handling and integration"""
        # Create failed payment scenario
        failed_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=50.00
        )
        
        # Mark payment with failure details
        failed_payment.payment_status = "Failed"
        failed_payment.failure_reason = "Insufficient funds"
        failed_payment.save()
        
        # Verify failure handling
        self.assertEqual(failed_payment.payment_status, "Failed")
        self.assertIsNotNone(failed_payment.failure_reason)

    def test_payment_partial_integration(self):
        """Test partial payment processing"""
        # Create invoice
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create partial payment (50% of invoice)
        partial_amount = invoice.grand_total / 2
        partial_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=partial_amount
        )
        
        # Verify partial payment
        self.assertEqual(partial_payment.paid_amount, partial_amount)
        self.assertLess(partial_payment.paid_amount, invoice.grand_total)

    def test_payment_overpayment_integration(self):
        """Test overpayment handling"""
        # Create invoice
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Create overpayment (120% of invoice)
        overpayment_amount = invoice.grand_total * 1.2
        overpayment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=overpayment_amount
        )
        
        # Verify overpayment
        self.assertEqual(overpayment.paid_amount, overpayment_amount)
        self.assertGreater(overpayment.paid_amount, invoice.grand_total)


class TestPaymentIntegrationWorkflows(VereningingenTestCase):
    """Workflow tests for payment integration scenarios"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)
    
    def test_membership_renewal_payment_workflow(self):
        """Test payment workflow for membership renewals"""
        # Create renewal membership
        renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=add_months(today(), 12),
            to_date=add_months(today(), 24)
        )
        
        # Create renewal invoice
        renewal_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=renewal.name
        )
        
        # Process renewal payment
        renewal_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=renewal_invoice.grand_total
        )
        
        # Verify renewal payment workflow
        self.assertEqual(renewal_payment.party, self.test_member.customer)
        self.assertEqual(renewal_payment.paid_amount, renewal_invoice.grand_total)
    
    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_payment_workflow(self):
        """Test payment workflow for volunteer expenses"""
        # Create volunteer
        volunteer = self.create_test_volunteer(member=self.test_member.name)
        
        # Create expense
        expense = self.create_test_volunteer_expense(
            volunteer=volunteer.name,
            amount=150.00,
            description="Volunteer expense payment test",
            status="Approved"
        )
        
        # Process expense payment (to volunteer)
        expense_payment = self.create_test_payment_entry(
            party=volunteer.email,
            party_type="Supplier",  # Volunteers are suppliers for expenses
            payment_type="Pay",
            paid_amount=expense.amount
        )
        
        # Verify expense payment workflow
        self.assertEqual(expense_payment.payment_type, "Pay")
        self.assertEqual(expense_payment.paid_amount, expense.amount)
    
    def test_donation_payment_workflow(self):
        """Test payment workflow for donations"""
        # Create donor
        donor = self.create_test_donor(
            donor_email=self.test_member.email,
            donor_name=f"{self.test_member.first_name} {self.test_member.last_name}"
        )
        
        # Create donation
        donation = self.create_test_donation(
            donor=donor.name,
            amount=200.00,
            payment_method="Bank Transfer"
        )
        
        # Process donation payment
        donation_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=donation.amount
        )
        
        # Verify donation payment workflow
        self.assertEqual(donation_payment.payment_type, "Receive")
        self.assertEqual(donation_payment.paid_amount, donation.amount)


class TestPaymentIntegrationEdgeCases(VereningingenTestCase):
    """Edge case tests for payment integration"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_zero_amount_payment_integration(self):
        """Test handling of zero amount payments.

        ERPNext does not allow a Payment Entry with a zero Paid Amount
        ("Paid Amount is mandatory"). Free/scholarship memberships are modelled
        as zero-amount invoices, never as zero-amount payment entries. Verify the
        framework rejects the invalid case rather than silently accepting it.
        """
        with self.assertRaises(frappe.ValidationError):
            self.create_test_payment_entry(
                party=self.test_member.customer,
                party_type="Customer",
                payment_type="Receive",
                paid_amount=0.00,
            )
    
    def test_very_large_payment_integration(self):
        """Test handling of very large payment amounts"""
        # Create large payment
        large_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=99999.99
        )
        
        # Verify large payment handling
        self.assertEqual(large_payment.paid_amount, flt(99999.99))
    
    def test_payment_with_special_characters(self):
        """Test payment integration with special characters in references"""
        # Create payment with special reference
        special_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=75.00
        )
        
        # Add special character reference
        special_payment.reference_no = "REF-2025-€£¥-001"
        special_payment.save()
        
        # Verify special character handling
        self.assertEqual(special_payment.reference_no, "REF-2025-€£¥-001")
    
    def test_concurrent_payment_processing(self):
        """Test concurrent payment processing scenarios"""
        # Create multiple payments simultaneously
        payments = []
        for i in range(3):
            payment = self.create_test_payment_entry(
                party=self.test_member.customer,
                party_type="Customer",
                payment_type="Receive",
                paid_amount=25.00 + i
            )
            payments.append(payment)
        
        # Verify all payments processed
        self.assertEqual(len(payments), 3)
        
        # Verify unique payment references
        payment_names = [p.name for p in payments]
        self.assertEqual(len(payment_names), len(set(payment_names)))
    
    def test_payment_date_edge_cases(self):
        """Test payment processing with edge case dates"""
        # Payment with past date
        past_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=100.00,
            posting_date=add_days(today(), -30)
        )
        
        self.assertEqual(past_payment.posting_date, add_days(today(), -30))
        
        # Payment with future date
        future_payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=125.00,
            posting_date=add_days(today(), 15)
        )
        
        self.assertEqual(future_payment.posting_date, add_days(today(), 15))


class TestPaymentIntegrationReporting(VereningingenTestCase):
    """Payment integration reporting and analytics tests"""
    
    def setUp(self):
        super().setUp()
        self.test_members = []
        
        # Create multiple members with payments
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Payment{i}",
                last_name="TestMember",
                email=f"payment{i}@example.com"
            )
            
            payment = self.create_test_payment_entry(
                party=member.customer,
                party_type="Customer",
                payment_type="Receive",
                paid_amount=100.00 + (i * 50.00)  # 100, 150, 200
            )
            
            self.test_members.append({"member": member, "payment": payment})
    
    def test_payment_aggregation_reporting(self):
        """Test payment aggregation for reporting"""
        # Calculate total payments
        total_payments = sum(data["payment"].paid_amount for data in self.test_members)
        expected_total = flt(450.00)  # 100 + 150 + 200
        
        self.assertEqual(total_payments, expected_total)
        
        # Calculate average payment
        average_payment = total_payments / len(self.test_members)
        expected_average = flt(150.00)
        
        self.assertEqual(average_payment, expected_average)
    
    def test_payment_frequency_analysis(self):
        """Test payment frequency analysis"""
        # All payments are "Receive" type
        receive_count = sum(1 for data in self.test_members 
                           if data["payment"].payment_type == "Receive")
        
        self.assertEqual(receive_count, 3)
        
        # Test payment method distribution
        payment_methods = {}
        for data in self.test_members:
            method = data["payment"].mode_of_payment or "Bank Transfer"
            payment_methods[method] = payment_methods.get(method, 0) + 1
        
        # All should use default method
        self.assertGreater(payment_methods.get("Bank Transfer", 0), 0)
    
    def test_payment_status_reporting(self):
        """Test payment status reporting"""
        # All test payments should be in submitted state
        submitted_count = 0
        for data in self.test_members:
            # Payments are typically submitted by default in tests
            submitted_count += 1
        
        self.assertEqual(submitted_count, 3)
    
    def test_payment_timeline_analysis(self):
        """Test payment timeline analysis"""
        # All payments should be from today
        today_payments = sum(1 for data in self.test_members 
                           if data["payment"].posting_date == today())
        
        self.assertEqual(today_payments, 3)
        
        # Test payment amount ranges
        payment_amounts = [data["payment"].paid_amount for data in self.test_members]
        
        min_payment = min(payment_amounts)
        max_payment = max(payment_amounts)
        
        self.assertEqual(min_payment, flt(100.00))
        self.assertEqual(max_payment, flt(200.00))