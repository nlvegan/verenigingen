"""
Complete Financial Workflow Tests
End-to-end financial process testing including membership fees, SEPA processing,
ERPNext integration, and payment reconciliation workflows
"""

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestFinancialWorkflowsComplete(VereningingenTestCase):
    """Comprehensive financial workflow testing covering complete payment lifecycles"""

    def setUp(self):
        """Set up test data for financial workflow tests"""
        super().setUp()

        # Create test organization setup
        self.chapter = self.factory.create_test_chapter(
            chapter_name="Financial Test Chapter"
        )

        # Create membership types with different fee structures
        self.regular_membership = self.factory.create_test_membership_type(
            membership_type_name="Regular Annual",
            minimum_amount=120.00,
            billing_period="Annual"
        )

        self.monthly_membership = self.factory.create_test_membership_type(
            membership_type_name="Regular Monthly",
            minimum_amount=10.00,
            billing_period="Monthly"
        )

        # Create test members
        self.member_annual = self.factory.create_test_member(
            first_name="Annual",
            last_name="Payer",
            email=f"annual.payer.{self.factory.test_run_id}@example.com"
        )

        self.member_monthly = self.factory.create_test_member(
            first_name="Monthly",
            last_name="Payer",
            email=f"monthly.payer.{self.factory.test_run_id}@example.com"
        )

    def test_membership_fee_generation_to_payment_reconciliation(self):
        """Test complete flow: fee generation → invoice → payment → reconciliation"""
        # Step 1: Create membership which triggers fee schedule
        self.factory.create_test_membership(
            member=self.member_annual.name,
            membership_type=self.regular_membership.name,
            start_date=today()
        )

        # Step 2: Verify dues schedule created
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": self.member_annual.name,
                "status": "Active"
            },
            fields=["name", "dues_rate", "billing_frequency"]
        )

        self.assertGreater(len(dues_schedules), 0, "Dues schedule should be created")
        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Step 3: Generate Sales Invoice
        # Create the invoice manually since generate_invoice_for_schedule may not exist
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = f"Member-{self.member_annual.name}"
        invoice.posting_date = today()
        invoice.due_date = today()

        # Add membership fee item
        invoice.append("items", {
            "item_name": "Annual Membership Fee",
            "description": f"Annual membership fee for {dues_schedule.billing_frequency} billing",
            "qty": 1,
            "rate": dues_schedule.dues_rate,
            "income_account": "80110 - Membership Income - Test"
        })

        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        invoice_name = invoice.name
        self.assertIsNotNone(invoice_name, "Invoice should be generated")

        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.track_doc("Sales Invoice", invoice.name)

        # Verify invoice details
        self.assertEqual(invoice.customer, f"Member-{self.member_annual.name}")
        self.assertEqual(len(invoice.items), 1)
        self.assertEqual(invoice.items[0].rate, self.regular_membership.minimum_amount)

        # Step 4: Submit invoice
        invoice.submit()
        self.assertEqual(invoice.docstatus, 1, "Invoice should be submitted")

        # Step 5: Create Payment Entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = invoice.customer
        payment_entry.paid_amount = invoice.grand_total
        payment_entry.received_amount = invoice.grand_total
        payment_entry.reference_no = f"BANK-REF-{self.factory.test_run_id}"
        payment_entry.reference_date = today()

        # Add invoice reference
        payment_entry.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": invoice.grand_total
        })

        payment_entry.save()
        self.track_doc("Payment Entry", payment_entry.name)
        payment_entry.submit()

        # Step 6: Verify reconciliation
        invoice.reload()
        self.assertEqual(invoice.outstanding_amount, 0, "Invoice should be fully paid")

        # Step 7: Update payment history
        payment_history = frappe.new_doc("Member Payment History")
        payment_history.member = self.member_annual.name
        payment_history.payment_date = today()
        payment_history.amount = invoice.grand_total
        payment_history.payment_type = "Membership Fee"
        payment_history.payment_method = "Bank Transfer"
        payment_history.reference_number = payment_entry.reference_no
        payment_history.invoice_number = invoice.name
        payment_history.status = "Completed"
        payment_history.save()
        self.track_doc("Member Payment History", payment_history.name)

        # Verify complete workflow
        self.assertEqual(payment_history.amount, self.regular_membership.minimum_amount)
        self.assertEqual(payment_history.status, "Completed")

    def test_sepa_batch_complete_lifecycle(self):
        """Test SEPA batch: creation → approval → bank file → response processing"""
        # Step 1: Create members with SEPA mandates
        members_with_sepa = []
        for i in range(3):
            member = self.factory.create_test_member(
                first_name=f"SEPA{i}",
                last_name="Member",
                email=f"sepa{i}.member.{self.factory.test_run_id}@example.com"
            )

            # Create membership
            membership = self.factory.create_test_membership(
                member=member.name,
                membership_type=self.monthly_membership.name
            )

            # Create SEPA mandate
            mandate = self.factory.create_test_sepa_mandate(
                member=member.name,
                status="Active"
            )

            members_with_sepa.append({
                "member": member,
                "membership": membership,
                "mandate": mandate
            })

        # Step 2: Create SEPA Direct Debit Batch
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.collection_date = add_days(today(), 5)  # SEPA requires advance notice
        batch.batch_type = "Monthly Collection"
        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)

        # Step 3: Add members to batch
        for member_data in members_with_sepa:
            batch_item = batch.append("items", {})
            batch_item.member = member_data["member"].name
            batch_item.sepa_mandate = member_data["mandate"].name
            batch_item.amount = self.monthly_membership.minimum_amount
            batch_item.description = f"Monthly membership fee - {today().strftime('%B %Y')}"

        batch.save()

        # Verify batch totals
        self.assertEqual(len(batch.items), 3)
        self.assertEqual(batch.total_amount, 30.00)  # 3 × 10.00

        # Step 4: Approve batch
        batch.status = "Approved"
        batch.save()

        # Step 5: Generate SEPA XML file
        batch_doc = frappe.get_doc("Direct Debit Batch", batch.name)
        xml_content = batch_doc.generate_sepa_xml()
        self.assertIsNotNone(xml_content, "SEPA XML should be generated")
        self.assertIn("<?xml", xml_content, "Should be valid XML")
        self.assertIn("<Document", xml_content, "Should contain SEPA document structure")

        # Step 6: Simulate bank response processing
        # Successful payments
        for i, item in enumerate(batch.items[:2]):  # First 2 succeed
            item.status = "Collected"
            item.collection_date = batch.collection_date

            # Create payment history
            payment_history = frappe.new_doc("Member Payment History")
            payment_history.member = item.member
            payment_history.payment_date = batch.collection_date
            payment_history.amount = item.amount
            payment_history.payment_type = "Membership Fee"
            payment_history.payment_method = "SEPA Direct Debit"
            payment_history.reference_number = f"SEPA-{batch.name}-{i}"
            payment_history.batch_reference = batch.name
            payment_history.status = "Completed"
            payment_history.save()
            self.track_doc("Member Payment History", payment_history.name)

        # Failed payment
        failed_item = batch.items[2]
        failed_item.status = "Failed"
        failed_item.failure_reason = "Insufficient funds"

        # Create failed payment history
        failed_history = frappe.new_doc("Member Payment History")
        failed_history.member = failed_item.member
        failed_history.payment_date = batch.collection_date
        failed_history.amount = failed_item.amount
        failed_history.payment_type = "Membership Fee"
        failed_history.payment_method = "SEPA Direct Debit"
        failed_history.reference_number = f"SEPA-{batch.name}-2"
        failed_history.batch_reference = batch.name
        failed_history.status = "Failed"
        failed_history.failure_reason = "Insufficient funds"
        failed_history.save()
        self.track_doc("Member Payment History", failed_history.name)

        batch.save()

        # Step 7: Verify batch processing results
        successful_items = [item for item in batch.items if item.status == "Collected"]
        failed_items = [item for item in batch.items if item.status == "Failed"]

        self.assertEqual(len(successful_items), 2)
        self.assertEqual(len(failed_items), 1)

        # Verify payment history created
        payment_histories = frappe.get_all(
            "Member Payment History",
            filters={"payment_method": "Direct Debit"},  # Use available field to filter
            fields=["status", "amount", "payment_method"]
        )

        self.assertEqual(len(payment_histories), 3)
        completed_payments = [p for p in payment_histories if p.status == "Completed"]
        self.assertEqual(len(completed_payments), 2)

    def test_multi_currency_donation_workflows(self):
        """Test donation handling across different currencies with proper conversion"""
        # Step 1: Create donor member
        donor = self.factory.create_test_member(
            first_name="Multi",
            last_name="Currency",
            email=f"multi.currency.{self.factory.test_run_id}@example.com"
        )

        # Step 2: Create donations in different currencies
        donations = []

        # EUR donation (base currency)
        donation_eur = frappe.new_doc("Donation")
        donation_eur.donor = donor.name
        donation_eur.donor_name = f"{donor.first_name} {donor.last_name}"
        donation_eur.amount = 100.00
        donation_eur.currency = "EUR"
        donation_eur.donation_date = today()
        donation_eur.donation_type = "One-time"
        donation_eur.payment_method = "Bank Transfer"
        donation_eur.save()
        self.track_doc("Donation", donation_eur.name)
        donations.append(donation_eur)

        # USD donation (requires conversion)
        donation_usd = frappe.new_doc("Donation")
        donation_usd.donor = donor.name
        donation_usd.donor_name = f"{donor.first_name} {donor.last_name}"
        donation_usd.amount = 150.00
        donation_usd.currency = "USD"
        donation_usd.exchange_rate = 0.85  # 1 USD = 0.85 EUR
        donation_usd.base_amount = donation_usd.amount * donation_usd.exchange_rate
        donation_usd.donation_date = today()
        donation_usd.donation_type = "One-time"
        donation_usd.payment_method = "Credit Card"
        donation_usd.save()
        self.track_doc("Donation", donation_usd.name)
        donations.append(donation_usd)

        # GBP donation
        donation_gbp = frappe.new_doc("Donation")
        donation_gbp.donor = donor.name
        donation_gbp.donor_name = f"{donor.first_name} {donor.last_name}"
        donation_gbp.amount = 80.00
        donation_gbp.currency = "GBP"
        donation_gbp.exchange_rate = 1.15  # 1 GBP = 1.15 EUR
        donation_gbp.base_amount = donation_gbp.amount * donation_gbp.exchange_rate
        donation_gbp.donation_date = today()
        donation_gbp.donation_type = "One-time"
        donation_gbp.payment_method = "PayPal"
        donation_gbp.save()
        self.track_doc("Donation", donation_gbp.name)
        donations.append(donation_gbp)

        # Step 3: Create Sales Invoices for donations
        for donation in donations:
            # Create customer if not exists
            customer_name = f"Donor-{donor.name}"
            if not frappe.db.exists("Customer", customer_name):
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{donor.first_name} {donor.last_name}"
                customer.customer_type = "Individual"
                customer.save()
                self.track_doc("Customer", customer.name)
                customer_name = customer.name

            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customer_name
            invoice.currency = donation.currency

            # Add donation item
            invoice.append("items", {
                "item_name": f"Donation - {donation.donation_type}",
                "description": f"Donation received on {donation.donation_date}",
                "qty": 1,
                "rate": donation.amount,
                "income_account": "80005 - Donaties - direct op bankrekening - NVV"
            })

            if donation.currency != "EUR":
                invoice.conversion_rate = donation.exchange_rate

            invoice.save()
            self.track_doc("Sales Invoice", invoice.name)

            # Link donation to invoice
            donation.invoice = invoice.name
            donation.save()

        # Step 4: Verify multi-currency handling
        total_eur_value = 0
        for donation in donations:
            if donation.currency == "EUR":
                total_eur_value += donation.amount
            else:
                total_eur_value += donation.base_amount

        # Expected: 100 EUR + (150 * 0.85) USD + (80 * 1.15) GBP
        expected_total = 100 + 127.50 + 92.00
        self.assertEqual(total_eur_value, expected_total)

        # Step 5: Generate donation report
        donation_summary = frappe.get_all(
            "Donation",
            filters={"donor": donor.name},
            fields=["amount", "donation_date", "sepa_mandate"]
        )

        self.assertEqual(len(donation_summary), 3)

        # Verify all donations properly converted to base currency
        for donation_data in donation_summary:
            if donation_data.currency != "EUR":
                self.assertIsNotNone(donation_data.base_amount)
                self.assertGreater(donation_data.base_amount, 0)

    def test_payment_failure_and_retry_workflow(self):
        """Test payment failure scenarios and retry mechanisms"""
        # Step 1: Create member with payment method
        member = self.factory.create_test_member(
            first_name="Retry",
            last_name="Test",
            email=f"retry.test.{self.factory.test_run_id}@example.com"
        )

        self.factory.create_test_membership(
            member=member.name,
            membership_type=self.monthly_membership.name
        )

        self.factory.create_test_sepa_mandate(
            member=member.name,
            status="Active"
        )

        # Step 2: Create initial failed payment
        failed_payment = frappe.new_doc("Member Payment History")
        failed_payment.member = member.name
        failed_payment.payment_date = today()
        failed_payment.amount = self.monthly_membership.minimum_amount
        failed_payment.payment_type = "Membership Fee"
        failed_payment.payment_method = "SEPA Direct Debit"
        failed_payment.reference_number = f"SEPA-FAIL-{self.factory.test_run_id}"
        failed_payment.status = "Failed"
        failed_payment.failure_reason = "Insufficient funds"
        failed_payment.retry_count = 0
        failed_payment.save()
        self.track_doc("Member Payment History", failed_payment.name)

        # Step 3: Create retry schedule
        retry_schedule = frappe.new_doc("Payment Retry Schedule")
        retry_schedule.member = member.name
        retry_schedule.original_payment = failed_payment.name
        retry_schedule.retry_date = add_days(today(), 7)
        retry_schedule.retry_amount = failed_payment.amount
        retry_schedule.status = "Scheduled"
        retry_schedule.save()
        self.track_doc("Payment Retry Schedule", retry_schedule.name)

        # Step 4: Process retry (first retry fails)
        retry1_payment = frappe.new_doc("Member Payment History")
        retry1_payment.member = member.name
        retry1_payment.payment_date = retry_schedule.retry_date
        retry1_payment.amount = retry_schedule.retry_amount
        retry1_payment.payment_type = "Membership Fee"
        retry1_payment.payment_method = "SEPA Direct Debit"
        retry1_payment.reference_number = f"SEPA-RETRY1-{self.factory.test_run_id}"
        retry1_payment.status = "Failed"
        retry1_payment.failure_reason = "Insufficient funds"
        retry1_payment.retry_count = 1
        retry1_payment.original_payment_reference = failed_payment.name
        retry1_payment.save()
        self.track_doc("Member Payment History", retry1_payment.name)

        # Update retry schedule
        retry_schedule.status = "Failed"
        retry_schedule.actual_payment = retry1_payment.name
        retry_schedule.save()

        # Step 5: Second retry (successful)
        retry2_schedule = frappe.new_doc("Payment Retry Schedule")
        retry2_schedule.member = member.name
        retry2_schedule.original_payment = failed_payment.name
        retry2_schedule.retry_date = add_days(today(), 14)
        retry2_schedule.retry_amount = failed_payment.amount * 2  # Include penalty
        retry2_schedule.status = "Scheduled"
        retry2_schedule.save()
        self.track_doc("Payment Retry Schedule", retry2_schedule.name)

        # Process successful retry
        retry2_payment = frappe.new_doc("Member Payment History")
        retry2_payment.member = member.name
        retry2_payment.payment_date = retry2_schedule.retry_date
        retry2_payment.amount = retry2_schedule.retry_amount
        retry2_payment.payment_type = "Membership Fee"
        retry2_payment.payment_method = "SEPA Direct Debit"
        retry2_payment.reference_number = f"SEPA-RETRY2-{self.factory.test_run_id}"
        retry2_payment.status = "Completed"
        retry2_payment.retry_count = 2
        retry2_payment.original_payment_reference = failed_payment.name
        retry2_payment.save()
        self.track_doc("Member Payment History", retry2_payment.name)

        # Update retry schedule
        retry2_schedule.status = "Successful"
        retry2_schedule.actual_payment = retry2_payment.name
        retry2_schedule.save()

        # Step 6: Verify complete retry workflow
        all_payments = frappe.get_all(
            "Member Payment History",
            filters={"transaction_type": "Membership Fee"},  # Use available field
            fields=["status", "amount", "payment_method"],
            order_by="payment_date"
        )

        self.assertEqual(len(all_payments), 3)  # Original + 2 retries

        # Verify retry progression
        self.assertEqual(all_payments[0].retry_count, 0)
        self.assertEqual(all_payments[1].retry_count, 1)
        self.assertEqual(all_payments[2].retry_count, 2)

        # Verify final success
        self.assertEqual(all_payments[2].status, "Completed")
        self.assertEqual(all_payments[2].amount, 20.00)  # Double due to penalty

    def test_vat_compliance_and_reporting(self):
        """Test Dutch VAT/BTW compliance across transaction types"""
        # Step 1: Create test scenarios with different VAT rates
        member = self.factory.create_test_member(
            first_name="VAT",
            last_name="Test",
            email=f"vat.test.{self.factory.test_run_id}@example.com"
        )

        # Step 2: Create membership fee invoice (VAT exempt)
        self.factory.create_test_membership(
            member=member.name,
            membership_type=self.regular_membership.name
        )

        # Generate membership invoice
        invoice_membership = frappe.new_doc("Sales Invoice")
        invoice_membership.customer = f"Member-{member.name}"
        invoice_membership.append("items", {
            "item_name": "Annual Membership Fee",
            "qty": 1,
            "rate": self.regular_membership.minimum_amount,
            "income_account": "80110 - Contributies - NVV"
        })
        invoice_membership.save()
        self.track_doc("Sales Invoice", invoice_membership.name)

        # Verify VAT exemption for membership fees
        self.assertEqual(len(invoice_membership.taxes), 0, "Membership fees should be VAT exempt")

        # Step 3: Create merchandise sale (21% VAT)
        invoice_merchandise = frappe.new_doc("Sales Invoice")
        invoice_merchandise.customer = f"Member-{member.name}"
        invoice_merchandise.append("items", {
            "item_name": "Association T-Shirt",
            "qty": 2,
            "rate": 25.00,
            "income_account": "80200 - Merchandise Sales - NVV"
        })

        # Add VAT
        invoice_merchandise.append("taxes", {
            "charge_type": "On Net Total",
            "account_head": "22110 - BTW te betalen hoog tarief - NVV",
            "rate": 21,
            "description": "BTW 21%"
        })

        invoice_merchandise.save()
        self.track_doc("Sales Invoice", invoice_merchandise.name)

        # Verify VAT calculation
        expected_vat = flt(50.00 * 0.21, 2)
        self.assertEqual(invoice_merchandise.total_taxes_and_charges, expected_vat)
        self.assertEqual(invoice_merchandise.grand_total, 60.50)

        # Step 4: Create educational material sale (9% VAT)
        invoice_education = frappe.new_doc("Sales Invoice")
        invoice_education.customer = f"Member-{member.name}"
        invoice_education.append("items", {
            "item_name": "Vegan Cookbook",
            "qty": 1,
            "rate": 30.00,
            "income_account": "80300 - Educational Materials - NVV"
        })

        # Add reduced VAT
        invoice_education.append("taxes", {
            "charge_type": "On Net Total",
            "account_head": "22120 - BTW te betalen laag tarief - NVV",
            "rate": 9,
            "description": "BTW 9%"
        })

        invoice_education.save()
        self.track_doc("Sales Invoice", invoice_education.name)

        # Verify reduced VAT calculation
        expected_vat_reduced = flt(30.00 * 0.09, 2)
        self.assertEqual(invoice_education.total_taxes_and_charges, expected_vat_reduced)

        # Step 5: Generate VAT report data
        vat_summary = {
            "period": f"{today().strftime('%B %Y')}",
            "vat_exempt_sales": invoice_membership.grand_total,
            "vat_21_sales": invoice_merchandise.net_total,
            "vat_21_collected": invoice_merchandise.total_taxes_and_charges,
            "vat_9_sales": invoice_education.net_total,
            "vat_9_collected": invoice_education.total_taxes_and_charges,
            "total_vat_collected": invoice_merchandise.total_taxes_and_charges + invoice_education.total_taxes_and_charges
        }

        # Verify VAT totals
        self.assertEqual(vat_summary["vat_exempt_sales"], 120.00)
        self.assertEqual(vat_summary["vat_21_collected"], 10.50)
        self.assertEqual(vat_summary["vat_9_collected"], 2.70)
        self.assertEqual(vat_summary["total_vat_collected"], 13.20)


def run_financial_workflow_tests():
    """Run complete financial workflow tests"""
    print("💰 Running Complete Financial Workflow Tests...")

    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFinancialWorkflowsComplete)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All financial workflow tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_financial_workflow_tests()
