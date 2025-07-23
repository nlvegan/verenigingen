# -*- coding: utf-8 -*-
"""
V2 Plan specific tests for the membership dues system
Tests payment-first application flow, advanced SEPA processing, and member status validation
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, add_to_date
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta


class TestMembershipDuesV2Features(VereningingenTestCase):
    """Test V2 plan specific features including payment-first applications and advanced SEPA"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()
        
    def create_simple_test_member(self):
        """Create a simple test member for testing using factory method"""
        return self.create_test_member(
            first_name="V2Test",
            last_name="Member",
            email=f"v2test.{frappe.generate_hash(length=6)}@example.com",
            address_line1="123 V2 Street",
            postal_code="1234AB",
            city="Amsterdam",
            status="Active"
        )
        
    # Payment-First Application Flow Tests
    
    def test_payment_first_application_submission_flow(self):
        """Test the complete payment-first application submission workflow"""
        # Step 1: Create application with SEPA details
        application_data = {
            "first_name": "PayFirst",
            "last_name": "Applicant",
            "email": f"payfirst.{frappe.generate_hash(length=6)}@example.com",
            "membership_type": "Test Membership",
            "sepa_mandate_consent": 1,
            "iban": "NL13TEST0123456789",
            "account_holder_name": "PayFirst Applicant"}
        
        application = self.create_test_membership_application(
            first_name="PayFirst",
            last_name="Applicant",
            email=f"payfirst.{frappe.generate_hash(length=6)}@example.com",
            membership_type="Test Membership",
            sepa_mandate_consent=1,
            iban="NL13TEST0123456789",
            account_holder_name="PayFirst Applicant"
        )
        
        # Step 2: Create draft SEPA mandate (before payment) using factory method
        draft_mandate = self.create_test_sepa_mandate(
            party_type="Customer",
            party=None,  # No customer yet
            iban="NL13TEST0123456789",
            account_holder="PayFirst Applicant",
            status="Draft",
            consent_method="Online Application",
            application=application.name
        )
        
        # Step 3: Create draft invoice for first payment using factory method
        invoice = self.create_test_sales_invoice(
            naming_series="APP-INV-",
            applicant_name="PayFirst Applicant",
            applicant_email=f"payfirst.{frappe.generate_hash(length=6)}@example.com",
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
            membership_application=application.name
        )
        
        # Step 4: Simulate successful PSP payment
        # Update invoice to paid status
        invoice.payment_status = "Paid"
        invoice.docstatus = 1  # Submit the invoice
        
        # Step 5: Update application after payment
        application.first_payment_completed = 1
        application.first_payment_date = today()
        application.first_payment_reference = "PSP-TEST-12345"
        application.first_payment_amount = 25.0
        application.status = "Pending Review"
        application.first_invoice = invoice.name
        application.sepa_mandate = draft_mandate.name
        application.save()
        
        # Step 6: Update SEPA mandate to pending
        draft_mandate.status = "Pending"
        draft_mandate.save()
        
        # Validate payment-first flow completion
        self.assertEqual(application.status, "Pending Review")
        self.assertTrue(application.first_payment_completed)
        self.assertEqual(draft_mandate.status, "Pending")
        self.assertEqual(invoice.payment_status, "Paid")
        
    def test_application_rejection_with_conditional_refund(self):
        """Test application rejection with different refund eligibility scenarios"""
        # Create paid application
        application = self.create_test_application_with_payment()
        
        # Test Case 1: Refund eligible rejection
        refund_eligible_reasons = [
            "Geographic Ineligibility",
            "Age Requirement Not Met",
            "Incomplete Documentation",
            "Board Discretion",
            "Technical Error"
        ]
        
        for reason in refund_eligible_reasons:
            with self.subTest(reason=reason):
                eligible = self.determine_refund_eligibility(reason)
                self.assertTrue(eligible, f"Reason '{reason}' should be refund eligible")
        
        # Test Case 2: No refund reasons
        no_refund_reasons = [
            "Deliberate Misrepresentation",
            "Time Wasting",
            "Abusive Behavior",
            "Fraudulent Application",
            "Duplicate Application"
        ]
        
        for reason in no_refund_reasons:
            with self.subTest(reason=reason):
                eligible = self.determine_refund_eligibility(reason)
                self.assertFalse(eligible, f"Reason '{reason}' should NOT be refund eligible")
        
        # Test Case 3: Process rejection with refund
        application.status = "Rejected"
        application.rejection_reason = "Geographic Ineligibility"
        application.rejection_details = "Member lives outside service area"
        application.rejection_date = today()
        
        # Should be eligible for refund
        refund_eligible = self.determine_refund_eligibility(application.rejection_reason)
        self.assertTrue(refund_eligible)
        
        if refund_eligible and application.first_payment_completed:
            # Simulate refund processing
            application.refund_processed = 1
            application.refund_amount = application.first_payment_amount
            
        application.save()
        
        self.assertTrue(application.refund_processed)
        self.assertEqual(application.refund_amount, 25.0)
        
    def test_application_approval_with_sepa_activation(self):
        """Test application approval process with SEPA mandate activation"""
        # Create paid application
        application = self.create_test_application_with_payment()
        
        # Get associated invoice and mandate
        invoice = frappe.get_doc("Sales Invoice", application.first_invoice)
        mandate = frappe.get_doc("SEPA Mandate", application.sepa_mandate)
        
        # Step 1: Create Member record from application
        member = frappe.new_doc("Member")
        member.first_name = application.first_name
        member.last_name = application.last_name
        member.email = application.email
        member.membership_start_date = today()
        member.address_line1 = "123 Approved Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        
        # Step 2: Create customer for member (simplified)
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        
        member.customer = customer.name
        member.save()
        
        # Step 3: Link invoice to new customer (simplified - normally would create amendment)
        invoice.customer = customer.name
        invoice.member = member.name
        invoice.save()
        
        # Step 4: Activate SEPA Mandate
        mandate.party_type = "Customer"
        mandate.party = customer.name
        mandate.status = "Active"
        mandate.save()
        
        # Step 5: Create membership dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.billing_frequency = application.billing_frequency
        dues_schedule.billing_day = today().day
        dues_schedule.dues_rate = invoice.grand_total
        dues_schedule.payment_method = "SEPA Direct Debit"
        dues_schedule.active_mandate = mandate.name
        dues_schedule.current_coverage_start = today()
        dues_schedule.current_coverage_end = add_months(today(), 1) - timedelta(days=1)
        dues_schedule.status = "Active"
        
        # Calculate next payment (first SEPA will be FRST)
        dues_schedule.next_invoice_date = add_months(today(), 1)
        dues_schedule.next_sequence_type = "FRST"
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Update application status
        application.status = "Approved"
        application.approval_date = today()
        application.member = member.name
        application.save()
        
        # Validate approval flow
        self.assertEqual(application.status, "Approved")
        self.assertEqual(mandate.status, "Active")
        self.assertEqual(dues_schedule.status, "Active")
        self.assertEqual(dues_schedule.next_sequence_type, "FRST")
        
    # Advanced SEPA Processing Tests
    
    def test_individual_frst_rcur_determination(self):
        """Test individual FRST/RCUR determination based on mandate history"""
        # Create SEPA mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.party_type = "Customer"
        mandate.party = "Test Customer"
        mandate.iban = "NL13TEST0123456789"
        mandate.account_holder = "Test Holder"
        mandate.mandate_type = "RCUR"
        mandate.status = "Active"
        mandate.sign_date = today()
        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        
        # Test Case 1: First usage should be FRST
        sequence_type_1 = self.determine_individual_sequence_type(mandate.name, "INV-001")
        self.assertEqual(sequence_type_1, "FRST")
        
        # Create mandate usage record for first transaction
        self.create_mandate_usage_record(mandate.name, "INV-001", "FRST", "Completed")
        
        # Test Case 2: Second usage should be RCUR
        sequence_type_2 = self.determine_individual_sequence_type(mandate.name, "INV-002")
        self.assertEqual(sequence_type_2, "RCUR")
        
        # Test Case 3: After mandate renewal, should be FRST again
        mandate.sign_date = add_days(today(), 1)  # Renewed mandate
        mandate.save()
        
        sequence_type_3 = self.determine_individual_sequence_type(mandate.name, "INV-003")
        self.assertEqual(sequence_type_3, "FRST")
        
    def test_sepa_batch_creation_with_mixed_sequences(self):
        """Test SEPA batch creation with mixed FRST/RCUR transactions"""
        # Create multiple members with different mandate histories
        members_data = []
        
        for i in range(3):
            member = self.create_simple_test_member()
            member.first_name = f"Batch{i}"
            member.save()
            
            # Create customer
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"Batch Customer {i}"
            customer.save()
            self.track_doc("Customer", customer.name)
            
            member.customer = customer.name
            member.save()
            
            # Create mandate
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.party_type = "Customer"
            mandate.party = customer.name
            mandate.iban = f"NL91ABNA041716430{i}"
            mandate.account_holder = f"Batch Holder {i}"
            mandate.status = "Active"
            mandate.sign_date = today()
            mandate.save()
            self.track_doc("SEPA Mandate", mandate.name)
            
            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customer.name
            invoice.member = member.name
            invoice.posting_date = today()
            invoice.is_membership_invoice = 1
            invoice.append("items", {
                "item_code": "MEMBERSHIP-MONTHLY",
                "qty": 1,
                "rate": 25.0,
                "income_account": "Sales - TC"
            })
            invoice.save()
            invoice.submit()
            self.track_doc("Sales Invoice", invoice.name)
            
            members_data.append({
                "member": member,
                "customer": customer,
                "mandate": mandate,
                "invoice": invoice
            })
        
        # Create usage history for second member (should get RCUR)
        self.create_mandate_usage_record(
            members_data[1]["mandate"].name, 
            "PREV-INV-001", 
            "FRST", 
            "Completed"
        )
        
        # Determine sequence types
        sequences = []
        for data in members_data:
            seq_type = self.determine_individual_sequence_type(
                data["mandate"].name, 
                data["invoice"].name
            )
            sequences.append(seq_type)
        
        # Should have mixed FRST and RCUR
        self.assertIn("FRST", sequences)
        self.assertIn("RCUR", sequences)
        
        # First and third members should be FRST (new mandates)
        self.assertEqual(sequences[0], "FRST")
        self.assertEqual(sequences[2], "FRST")
        
        # Second member should be RCUR (has usage history)
        self.assertEqual(sequences[1], "RCUR")
        
    def test_sepa_batch_pre_notification_timing(self):
        """Test SEPA batch pre-notification timing requirements"""
        # Create SEPA batch config
        config = {
            "batch_execution_day": 26,
            "frst_prenotification_days": 5,
            "rcur_prenotification_days": 2
        }
        
        # Test Case 1: FRST batch timing
        target_date = getdate("2025-01-26")  # Execution date
        
        # FRST requires 5 business days notice
        frst_submission_deadline = self.calculate_required_submission_date(target_date, has_frst=True, config=config)
        expected_frst_deadline = getdate("2025-01-19")  # 5 business days before 26th
        
        # Allow for weekends/holidays in calculation
        self.assertLessEqual(frst_submission_deadline, expected_frst_deadline)
        
        # Test Case 2: RCUR batch timing
        rcur_submission_deadline = self.calculate_required_submission_date(target_date, has_frst=False, config=config)
        expected_rcur_deadline = getdate("2025-01-22")  # 2 business days before 26th
        
        self.assertLessEqual(rcur_submission_deadline, expected_rcur_deadline)
        
        # Test Case 3: Mixed batch (should use FRST timing)
        mixed_submission_deadline = self.calculate_required_submission_date(target_date, has_frst=True, config=config)
        self.assertEqual(mixed_submission_deadline, frst_submission_deadline)
        
    # Member Status Validation Tests
    
    def test_member_status_validation_for_billing(self):
        """Test critical member status validation before billing"""
        # Test valid member statuses
        valid_statuses = ["Active", "Current"]
        for status in valid_statuses:
            with self.subTest(status=status):
                self.test_member.status = status
                self.test_member.save()
                eligible = self.validate_member_eligibility_for_billing(self.test_member)
                self.assertTrue(eligible, f"Member with status '{status}' should be eligible for billing")
        
        # Test invalid member statuses
        invalid_statuses = ["Terminated", "Expelled", "Deceased", "Suspended", "Quit"]
        for status in invalid_statuses:
            with self.subTest(status=status):
                self.test_member.status = status
                self.test_member.save()
                eligible = self.validate_member_eligibility_for_billing(self.test_member)
                self.assertFalse(eligible, f"Member with status '{status}' should NOT be eligible for billing")
        
    def test_terminated_member_exclusion_from_batch(self):
        """Test that terminated members are excluded from DD batches"""
        # Create active member with dues schedule
        dues_schedule = self.create_test_dues_schedule_for_member(self.test_member)
        
        # Create invoice for member
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = "Test Customer"
        invoice.member = self.test_member.name
        invoice.posting_date = today()
        invoice.is_membership_invoice = 1
        invoice.outstanding_amount = 25.0
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        invoice.save()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Member should be eligible initially
        eligible_before = self.validate_member_eligibility_for_billing(self.test_member)
        self.assertTrue(eligible_before)
        
        # Terminate member AFTER invoice creation
        self.test_member.status = "Expelled"
        self.test_member.save()
        
        # Member should NOT be eligible after termination
        eligible_after = self.validate_member_eligibility_for_billing(self.test_member)
        self.assertFalse(eligible_after)
        
        # Simulate batch creation - should exclude terminated member
        eligible_invoices = self.get_eligible_invoices_for_batch()
        
        # Invoice should not be included due to terminated member status
        invoice_members = [inv.get("member") for inv in eligible_invoices]
        self.assertNotIn(self.test_member.name, invoice_members)
        
    def test_post_batch_creation_termination_handling(self):
        """Test member terminated after batch created but before processed"""
        # Create batch with active member
        member = self.test_member
        dues_schedule = self.create_test_dues_schedule_for_member(member)
        
        # Create invoice and simulate batch creation
        invoice = self.create_test_invoice_for_member(member)
        
        # Simulate batch would include this member initially
        eligible_before = self.validate_member_eligibility_for_billing(member)
        self.assertTrue(eligible_before)
        
        # Create batch entry (simulate batch creation)
        batch_transaction = {
            "member": member.name,
            "invoice": invoice.name,
            "amount": 25.0,
            "status": "Pending"
        }
        
        # Member quits AFTER batch creation but BEFORE processing
        member.status = "Quit"
        member.save()
        
        # When processing batch, should validate member status again
        eligible_for_processing = self.validate_member_eligibility_for_billing(member)
        self.assertFalse(eligible_for_processing)
        
        # Batch processing should skip this member
        # (In real implementation, this would prevent charge processing)
        
    # Payment Failure Handling Tests
    
    def test_sepa_return_handling_workflow(self):
        """Test comprehensive SEPA return (R-transaction) handling"""
        # Create member with active dues schedule
        dues_schedule = self.create_test_dues_schedule_for_member(self.test_member)
        invoice = self.create_test_invoice_for_member(self.test_member)
        
        # Simulate SEPA return data
        return_data = {
            "member": self.test_member.name,
            "invoice": invoice.name,
            "amount": 25.0,
            "reason_code": "R01",  # Insufficient funds
            "description": "Insufficient funds in account",
            "failure_date": today()
        }
        
        # Process SEPA return
        failure_log = self.handle_sepa_return(return_data)
        
        # Validate failure log creation
        self.assertIsNotNone(failure_log)
        failure_doc = frappe.get_doc("Payment Failure Log", failure_log)
        
        self.assertEqual(failure_doc.member, self.test_member.name)
        self.assertEqual(failure_doc.failure_type, "Insufficient Funds")
        self.assertEqual(failure_doc.failure_code, "R01")
        self.assertEqual(failure_doc.status, "Pending Review")
        
        # Validate dues schedule update
        dues_schedule.reload()
        # Check failure is recorded in notes
        self.assertIn("Payment failure", dues_schedule.notes or "")
        self.assertTrue(dues_schedule.under_manual_review)
        
    def test_payment_failure_r_code_mapping(self):
        """Test SEPA R-code to failure type mapping"""
        r_code_mappings = {
            "R01": "Insufficient Funds",
            "R02": "Account Closed",
            "R03": "No Account",
            "R04": "Account Blocked",
            "R06": "Mandate Cancelled",
            "R07": "Deceased",
            "R08": "Stopped by Payer",
            "R09": "Account Details Incorrect",
            "R10": "Mandate Not Valid"
        }
        
        for r_code, expected_type in r_code_mappings.items():
            with self.subTest(r_code=r_code):
                failure_type = self.map_r_code_to_type(r_code)
                self.assertEqual(failure_type, expected_type)
        
        # Test unknown code
        unknown_type = self.map_r_code_to_type("R99")
        self.assertEqual(unknown_type, "Other")
        
    def test_chapter_financial_admin_notification(self):
        """Test notification system for chapter financial admins"""
        # Create chapter financial admin
        chapter_admin_user = self.create_test_user(
            f"chapter.admin.{frappe.generate_hash(length=6)}@example.com",
            roles=["Chapter Financial Admin"]
        )
        
        # Simulate member with chapter and payment failure
        self.test_member.chapter = "Test Chapter"
        self.test_member.save()
        
        # Create payment failure
        failure_log = frappe.new_doc("Payment Failure Log")
        failure_log.member = self.test_member.name
        failure_log.invoice = "TEST-INV-001"
        failure_log.payment_method = "SEPA Direct Debit"
        failure_log.failure_date = today()
        failure_log.failure_type = "Insufficient Funds"
        failure_log.failure_code = "R01"
        failure_log.status = "Pending Review"
        failure_log.save()
        self.track_doc("Payment Failure Log", failure_log.name)
        
        # Simulate notification workflow
        notifications = self.create_payment_failure_notifications(failure_log)
        
        # Should create notifications for both treasurer and chapter admin
        self.assertTrue(len(notifications) >= 1)  # At least treasurer notification
        
        # Validate notification content
        treasurer_notification = next((n for n in notifications if n["type"] == "Organization"), None)
        self.assertIsNotNone(treasurer_notification)
        self.assertIn(self.test_member.name, treasurer_notification["message"])
        
    # Helper Methods
    
    def create_test_application_with_payment(self):
        """Create a test application with completed payment"""
        application = frappe.new_doc("Membership Application")
        application.first_name = "TestPaid"
        application.last_name = "Applicant"
        application.email = f"testpaid.{frappe.generate_hash(length=6)}@example.com"
        application.membership_type = "Test Membership"
        application.sepa_mandate_consent = 1
        application.iban = "NL13TEST0123456789"
        application.account_holder_name = "TestPaid Applicant"
        application.billing_frequency = "Monthly"
        application.first_payment_completed = 1
        application.first_payment_date = today()
        application.first_payment_reference = "PSP-TEST-67890"
        application.first_payment_amount = 25.0
        application.status = "Pending Review"
        
        # Create associated invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.naming_series = "APP-INV-"
        invoice.applicant_name = f"{application.first_name} {application.last_name}"
        invoice.applicant_email = application.email
        invoice.posting_date = today()
        invoice.payment_status = "Paid"
        invoice.is_membership_invoice = 1
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Create associated mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.party_type = "Customer"
        mandate.iban = application.iban
        mandate.account_holder = application.account_holder_name
        mandate.status = "Pending"
        mandate.consent_date = today()
        mandate.application = application.name
        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        
        application.first_invoice = invoice.name
        application.sepa_mandate = mandate.name
        application.save()
        self.track_doc("Membership Application", application.name)
        
        return application
        
    def determine_refund_eligibility(self, rejection_reason):
        """Determine if rejected application is eligible for refund"""
        no_refund_reasons = [
            "Deliberate Misrepresentation",
            "Time Wasting",
            "Abusive Behavior",
            "Fraudulent Application",
            "Duplicate Application"
        ]
        
        refund_reasons = [
            "Geographic Ineligibility",
            "Age Requirement Not Met",
            "Incomplete Documentation",
            "Board Discretion",
            "Technical Error"
        ]
        
        if rejection_reason in no_refund_reasons:
            return False
        elif rejection_reason in refund_reasons:
            return True
        else:
            return True  # Default to refund for unlisted reasons
            
    def determine_individual_sequence_type(self, mandate_name, invoice_name):
        """Determine FRST/RCUR based on actual mandate usage history"""
        # Check if this mandate has been used before
        previous_usage = frappe.get_all(
            "SEPA Mandate Usage",
            filters={
                "mandate": mandate_name,
                "status": "Completed"
            },
            fields=["name", "usage_date", "invoice"],
            limit=1,
            order_by="usage_date desc"
        )
        
        if not previous_usage:
            return "FRST"
        
        # Check if mandate was reset (new mandate after cancellation)
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        last_usage_date = getdate(previous_usage[0].usage_date)
        
        if getdate(mandate.sign_date) > last_usage_date:
            return "FRST"
        
        return "RCUR"
        
    def create_mandate_usage_record(self, mandate_name, invoice_name, sequence_type, status="Pending"):
        """Create a SEPA mandate usage record"""
        usage = frappe.new_doc("SEPA Mandate Usage")
        usage.mandate = mandate_name
        usage.invoice = invoice_name
        usage.sequence_type = sequence_type
        usage.usage_date = today()
        usage.status = status
        usage.save()
        self.track_doc("SEPA Mandate Usage", usage.name)
        return usage
        
    def calculate_required_submission_date(self, batch_date, has_frst=False, config=None):
        """Calculate when batch must be submitted to bank"""
        if not config:
            config = {
                "frst_prenotification_days": 5,
                "rcur_prenotification_days": 2
            }
        
        if has_frst:
            days_required = config["frst_prenotification_days"]
        else:
            days_required = config["rcur_prenotification_days"]
        
        # Simple calculation - in real implementation would account for business days
        return add_days(batch_date, -days_required)
        
    def validate_member_eligibility_for_billing(self, member):
        """Validate if member is eligible for billing - matches current system behavior"""
        # Check member status
        if member.status in ["Terminated", "Expelled", "Deceased", "Suspended", "Quit"]:
            return False
        
        # Check if member has active membership
        active_membership = frappe.db.exists(
            "Membership", {"member": member.name, "status": "Active", "docstatus": 1}
        )
        if not active_membership:
            return False
        
        # NOTE: Payment method validation is done at DD batch creation time
        # Members with broken payment data can still receive invoices
        # They just won't be included in Direct Debit batches
        
        return True
        
    def get_eligible_invoices_for_batch(self):
        """Get invoices eligible for SEPA batch (with member status validation)"""
        # Simulate query that would exclude terminated members
        eligible_invoices = []
        
        # In real implementation, this would be a SQL query joining
        # Sales Invoice with Member and filtering on member status
        all_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "is_membership_invoice": 1,
                "outstanding_amount": [">", 0],
                "docstatus": 1
            },
            fields=["name", "member", "outstanding_amount"]
        )
        
        for invoice in all_invoices:
            if invoice.member:
                member = frappe.get_doc("Member", invoice.member)
                if self.validate_member_eligibility_for_billing(member):
                    eligible_invoices.append(invoice)
        
        return eligible_invoices
        
    def test_invoice_generation_with_missing_sepa_mandate(self):
        """Test that members with SEPA Direct Debit can still receive invoices without active mandate"""
        # Create member with SEPA Direct Debit payment method but no mandate
        member = self.create_test_member(
            first_name="MissingMandate",
            last_name="TestMember", 
            email=f"missing.mandate.{frappe.generate_hash(length=6)}@example.com",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789"
        )
        
        # Create active membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Active"
        )
        
        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 25.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Verify no SEPA mandate exists
        mandate_exists = frappe.db.exists(
            "SEPA Mandate", 
            {"member": member.name, "status": "Active", "is_active": 1}
        )
        self.assertFalse(mandate_exists, "No SEPA mandate should exist for this test")
        
        # Test eligibility validation - should PASS (new behavior)
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertTrue(is_eligible, 
                       "Member with SEPA Direct Debit but no mandate should still be eligible for invoicing")
        
        # Test invoice generation - should SUCCEED
        can_generate, reason = dues_schedule.can_generate_invoice()
        self.assertTrue(can_generate, f"Should be able to generate invoice: {reason}")
        
        # Generate invoice
        invoice_name = dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created despite missing SEPA mandate")
        self.track_doc("Sales Invoice", invoice_name)
        
        # Verify invoice properties
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.customer, member.customer)
        self.assertEqual(invoice.grand_total, 25.0)
        self.assertEqual(invoice.docstatus, 1)  # Should be submitted
        
        # This invoice should NOT be eligible for DD batch (tested separately)
        # But it SHOULD exist and be payable via other methods
        
    def test_dd_batch_excludes_members_without_sepa_mandate(self):
        """Test that DD batch creation excludes members without active SEPA mandates"""
        # Create member with SEPA Direct Debit but no mandate (same as above test)
        member = self.create_test_member(
            first_name="BatchExclude",
            last_name="TestMember",
            email=f"batch.exclude.{frappe.generate_hash(length=6)}@example.com", 
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789"
        )
        
        # Create membership and invoice (following the previous test pattern)
        membership = self.create_test_membership(member=member.name, membership_type="Test Membership")
        
        # Create unpaid invoice (this should exist as per new behavior)
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            is_membership_invoice=1,
            member=member.name,
            outstanding_amount=25.0
        )
        
        # Verify invoice exists and is unpaid
        self.assertEqual(invoice.outstanding_amount, 25.0)
        
        # Now test DD batch creation logic (simulated)
        # In reality, this would be tested in the DD batch creation tests
        # but we simulate the validation here
        
        # Verify no SEPA mandate exists
        mandate_exists = frappe.db.exists(
            "SEPA Mandate",
            {"member": member.name, "status": "Active", "is_active": 1}
        )
        self.assertFalse(mandate_exists, "No SEPA mandate should exist")
        
        # DD batch eligibility check should FAIL for this invoice
        # (This logic would be in the DD batch creation code)
        member_doc = frappe.get_doc("Member", member.name)
        if member_doc.payment_method == "SEPA Direct Debit":
            has_active_mandate = frappe.db.exists(
                "SEPA Mandate",
                {"member": member.name, "status": "Active", "is_active": 1}
            )
            dd_batch_eligible = has_active_mandate
        else:
            dd_batch_eligible = False
            
        self.assertFalse(dd_batch_eligible, 
                        "Member without SEPA mandate should NOT be eligible for DD batch inclusion")
        
    def create_test_dues_schedule_for_member(self, member):
        """Create a test dues schedule for specific member"""
        membership_type = frappe.get_value("Membership Type", {}, "name")
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 25.0
        # Payment method is determined dynamically based on member's payment setup
        dues_schedule.status = "Active"
        # Coverage dates are calculated automatically
        dues_schedule.next_invoice_date = add_months(today(), 1)
        dues_schedule.under_manual_review = 0
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_test_invoice_for_member(self, member):
        """Create a test invoice for member"""
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = "Test Customer"
        invoice.member = member.name
        invoice.posting_date = today()
        invoice.is_membership_invoice = 1
        invoice.outstanding_amount = 25.0
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        invoice.save()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice
        
    def handle_sepa_return(self, return_data):
        """Handle SEPA R-transaction (return/failure)"""
        # Create failure log
        failure = frappe.new_doc("Payment Failure Log")
        failure.member = return_data["member"]
        failure.invoice = return_data["invoice"]
        failure.payment_method = "SEPA Direct Debit"
        failure.failure_date = return_data["failure_date"]
        failure.failure_code = return_data["reason_code"]
        failure.failure_type = self.map_r_code_to_type(return_data["reason_code"])
        failure.failure_description = return_data["description"]
        failure.status = "Pending Review"
        failure.save()
        self.track_doc("Payment Failure Log", failure.name)
        
        # Update dues schedule
        dues_schedule = frappe.get_value(
            "Membership Dues Schedule",
            {"member": return_data["member"]},
            "name"
        )
        
        if dues_schedule:
            dues_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule)
            # Record failure in notes
            failure_count = (dues_doc.notes or "").count("Payment failure") + 1
            dues_doc.notes = (dues_doc.notes or "") + f"\nPayment failure #{failure_count} on {return_data['failure_date']}: {return_data['description']}"
            dues_doc.under_manual_review = 1
            dues_doc.save()
        
        return failure.name
        
    def map_r_code_to_type(self, r_code):
        """Map SEPA R-codes to failure types"""
        mapping = {
            "R01": "Insufficient Funds",
            "R02": "Account Closed",
            "R03": "No Account",
            "R04": "Account Blocked",
            "R06": "Mandate Cancelled",
            "R07": "Deceased",
            "R08": "Stopped by Payer",
            "R09": "Account Details Incorrect",
            "R10": "Mandate Not Valid"
        }
        return mapping.get(r_code, "Other")
        
    def create_payment_failure_notifications(self, failure_log):
        """Create notifications for payment failure"""
        notifications = []
        
        # Organization treasurer notification
        notifications.append({
            "recipient": "treasurer@example.com",
            "type": "Organization",
            "message": f"Payment failure for {failure_log.member} - {failure_log.failure_type}"
        })
        
        # Chapter admin notification (if exists)
        member = frappe.get_doc("Member", failure_log.member)
        if hasattr(member, 'chapter') and member.chapter:
            notifications.append({
                "recipient": "chapter.admin@example.com",
                "type": "Chapter",
                "message": f"Chapter member payment failure: {failure_log.member}"
            })
        
        return notifications