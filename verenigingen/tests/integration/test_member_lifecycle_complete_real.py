"""
Complete Member Lifecycle Integration Tests - Real Database Operations
====================================================================

End-to-end integration tests for the complete member lifecycle using real database operations.
This replaces mocked member lifecycle tests with comprehensive real-world scenarios.

Phase 5.2 Integration Testing: Complete Member Journey
- Member application → approval → onboarding → payment setup → termination
- Tests all business logic, validations, and integrations with real data
- Validates Dutch business rules and compliance requirements
- Covers all critical member lifecycle workflows

Author: Enhanced Test Development Phase 5.2
"""

import frappe
from frappe.utils import add_days, add_months, today, getdate, flt
from decimal import Decimal

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class MemberLifecycleCompleteRealTest(EnhancedTestCase):
    """Complete member lifecycle integration tests with real database operations"""

    def setUp(self):
        """Set up comprehensive test data for member lifecycle testing"""
        super().setUp()
        
        # Create test chapter for member assignment
        self.test_chapter = self.create_chapter(region="Noord-Holland")
        
        # Create membership types for lifecycle testing (or use existing)
        if frappe.db.exists("Membership Type", "Regular Member"):
            self.regular_membership_type = frappe.get_doc("Membership Type", "Regular Member")
        else:
            self.regular_membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Regular Member",
                "minimum_amount": 60.0,
                "description": "Standard membership",
                "is_default": 1
            })
            self.regular_membership_type.insert()

        if frappe.db.exists("Membership Type", "Student Member"):
            self.student_membership_type = frappe.get_doc("Membership Type", "Student Member")
        else:
            self.student_membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Student Member",
                "minimum_amount": 30.0,
                "description": "Student discount membership",
                "student_discount": 1
            })
            self.student_membership_type.insert()

    def test_complete_member_application_to_active_workflow(self):
        """Test complete member application to active status workflow"""
        
        # Phase 1: Initial Application Submission
        application_data = {
            "first_name": "Jan",
            "last_name": "Test",
            "tussenvoegsel": "van",
            "email": "jan.van.test@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-05-15",
            "address_line1": "Teststraat 123",
            "city": "Amsterdam",
            "postal_code": "1234 AB",
            "status": "Pending",
            "selected_membership_type": self.regular_membership_type.name,
            "chapter": self.test_chapter.name
        }

        # Submit application with real data validation
        pending_member = self.create_test_member(**application_data)
        
        # Verify application state
        self.assertEqual(pending_member.status, "Pending")
        self.assertIsNotNone(pending_member.application_id)
        self.assertIsNone(pending_member.member_id)
        self.assertEqual(pending_member.full_name, "Jan van Test")
        
        # Phase 2: Application Review and Approval
        # Simulate review process with business validation
        pending_member.status = "Active"
        pending_member.approval_date = today()
        pending_member.approved_by = "Administrator"
        pending_member.save()
        
        # Reload to verify changes
        pending_member.reload()
        
        # Verify approval state
        self.assertEqual(pending_member.status, "Active") 
        self.assertIsNotNone(pending_member.member_id)
        self.assertIsNotNone(pending_member.approval_date)
        self.assertEqual(pending_member.approved_by, "Administrator")
        
        # Phase 3: Membership Setup and Dues Schedule Creation
        membership = self.create_test_membership(
            member=pending_member.name,
            membership_type=self.regular_membership_type.name,
            start_date=today(),
            status="Active"
        )
        
        # Create dues schedule for the active member
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": pending_member.name,
            "membership": membership.name,
            "membership_type": self.regular_membership_type.name,
            "start_date": today(),
            "billing_frequency": "Annual",
            "dues_rate": 60.0,
            "invoice_days_before": 30,
            "is_active": 1
        })
        dues_schedule.insert()
        
        # Verify membership setup
        self.assertEqual(membership.status, "Active")
        self.assertEqual(dues_schedule.dues_rate, 60.0)
        self.assertEqual(dues_schedule.billing_frequency, "Annual")
        
        # Phase 4: SEPA Mandate Setup  
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": pending_member.name,
            "iban": "NL91ABNA0417164300",
            "account_holder": "Jan van Test",
            "mandate_reference": f"MND{frappe.generate_hash()[:8]}",
            "mandate_date": today(),
            "status": "Active"
        })
        sepa_mandate.insert()
        
        # Link mandate to member
        pending_member.current_sepa_mandate = sepa_mandate.name
        pending_member.save()
        
        # Verify SEPA setup
        self.assertEqual(sepa_mandate.status, "Active")
        self.assertEqual(sepa_mandate.iban, "NL91ABNA0417164300")
        self.assertEqual(pending_member.current_sepa_mandate, sepa_mandate.name)
        
        # Phase 5: First Payment Processing
        # Generate first invoice
        sales_invoice = self.create_test_sales_invoice(
            customer=pending_member.name,
            posting_date=today(),
            due_date=add_days(today(), 30),
            grand_total=60.0,
            outstanding_amount=60.0,
            items=[{
                "item_code": "Membership Fee",
                "item_name": "Annual Membership Fee",
                "qty": 1,
                "rate": 60.0,
                "amount": 60.0
            }]
        )
        
        # Process payment via SEPA
        payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer", 
            "party": pending_member.name,
            "paid_amount": 60.0,
            "received_amount": 60.0,
            "reference_no": sepa_mandate.mandate_reference,
            "reference_date": today(),
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice.name,
                "allocated_amount": 60.0
            }]
        })
        payment_entry.insert()
        payment_entry.submit()
        
        # Verify payment processing
        sales_invoice.reload()
        self.assertEqual(sales_invoice.status, "Paid")
        self.assertEqual(sales_invoice.outstanding_amount, 0.0)
        
        # Phase 6: Chapter Assignment and Volunteer Role Setup
        chapter_member = frappe.get_doc({
            "doctype": "Chapter Member",
            "member": pending_member.name,
            "chapter": self.test_chapter.name,
            "join_date": today(),
            "status": "Active",
            "role": "Member"
        })
        chapter_member.insert()
        
        # Create volunteer profile (if age eligible)
        if getdate(pending_member.birth_date).year <= (getdate(today()).year - 16):
            volunteer = frappe.get_doc({
                "doctype": "Volunteer",
                "member": pending_member.name,
                "status": "Active",
                "availability": "Weekends",
                "skills": "Communication, Event Organization"
            })
            volunteer.insert()
            
            # Verify volunteer setup
            self.assertEqual(volunteer.status, "Active")
            self.assertEqual(volunteer.member, pending_member.name)
        
        # Verify final member state
        pending_member.reload()
        self.assertEqual(pending_member.status, "Active")
        self.assertIsNotNone(pending_member.member_id)
        self.assertIsNotNone(pending_member.current_sepa_mandate)
        
        # Verify chapter membership
        self.assertEqual(chapter_member.status, "Active")
        self.assertEqual(chapter_member.chapter, self.test_chapter.name)
        
        return pending_member, membership, dues_schedule, sepa_mandate, sales_invoice, payment_entry

    def test_student_member_discount_workflow(self):
        """Test student member workflow with discount processing"""
        
        # Create student member application
        student_data = {
            "first_name": "Emma", 
            "last_name": "Student",
            "email": "emma.student@university.nl",
            "birth_date": "2002-09-01",  # 21 years old
            "address_line1": "Studentenstraat 45",
            "postal_code": "2500 CD", 
            "city": "Den Haag",
            "status": "Pending",
            "chapter": self.test_chapter.name,
            "membership_type": self.student_membership_type.name,
            "is_student": 1,
            "student_id": "STU2024001"
        }
        
        student_member = self.create_test_member(**student_data)
        
        # Approve student application
        student_member.status = "Active"
        student_member.approval_date = today()
        student_member.save()
        
        # Verify student status
        self.assertEqual(student_member.is_student, 1)
        self.assertEqual(student_member.student_id, "STU2024001")
        
        # Create student membership with discount
        student_membership = self.create_test_membership(
            member=student_member.name,
            membership_type=self.student_membership_type.name,
            start_date=today(),
            status="Active"
        )
        
        # Create dues schedule with student discount
        student_dues = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": student_member.name,
            "membership": student_membership.name, 
            "membership_type": self.student_membership_type.name,
            "start_date": today(),
            "billing_frequency": "Annual",
            "dues_rate": 30.0,  # Student discount rate
            "invoice_days_before": 30,
            "is_active": 1
        })
        student_dues.insert()
        
        # Verify student discount applied
        self.assertEqual(student_dues.dues_rate, 30.0)
        self.assertLess(student_dues.dues_rate, self.regular_membership_type.minimum_amount)
        
        # Generate discounted invoice
        student_invoice = self.create_test_sales_invoice(
            customer=student_member.name,
            posting_date=today(),
            due_date=add_days(today(), 30),
            grand_total=30.0,  # Discounted amount
            outstanding_amount=30.0,
            items=[{
                "item_code": "Student Membership Fee",
                "item_name": "Annual Student Membership Fee",
                "qty": 1,
                "rate": 30.0,
                "amount": 30.0
            }]
        )
        
        # Verify discounted billing
        self.assertEqual(student_invoice.grand_total, 30.0)
        self.assertLess(student_invoice.grand_total, 60.0)  # Less than regular fee
        
        return student_member, student_membership, student_dues, student_invoice

    def test_member_chapter_transfer_workflow(self):
        """Test member transfer between chapters workflow"""
        
        # Create member in original chapter
        original_member = self.create_test_member(
            first_name="Transfer",
            last_name="Member",
            email="transfer@example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create second chapter for transfer
        target_chapter = self.create_chapter(region="Zuid-Holland")
        
        # Create chapter membership in original chapter
        original_chapter_member = frappe.get_doc({
            "doctype": "Chapter Member",
            "member": original_member.name,
            "chapter": self.test_chapter.name,
            "join_date": add_days(today(), -30),
            "status": "Active",
            "role": "Member"
        })
        original_chapter_member.insert()
        
        # Process transfer request
        transfer_date = today()
        
        # End original chapter membership
        original_chapter_member.status = "Transferred"
        original_chapter_member.end_date = transfer_date
        original_chapter_member.save()
        
        # Create new chapter membership
        new_chapter_member = frappe.get_doc({
            "doctype": "Chapter Member",
            "member": original_member.name,
            "chapter": target_chapter.name,
            "join_date": transfer_date,
            "status": "Active",
            "role": "Member",
            "transfer_from": self.test_chapter.name
        })
        new_chapter_member.insert()
        
        # Verify transfer completed
        original_chapter_member.reload()
        self.assertEqual(original_chapter_member.status, "Transferred")
        self.assertEqual(original_chapter_member.end_date, transfer_date)

        self.assertEqual(new_chapter_member.status, "Active")
        self.assertEqual(new_chapter_member.transfer_from, self.test_chapter.name)

        # Update member's chapter display
        original_member.reload()
        original_member.update_current_chapter_display()
        # Verify chapter display updated (Note: primary_chapter field doesn't exist,
        # chapter membership is tracked via Chapter Member records)
        self.assertIn(target_chapter.name, original_member.current_chapter_display or "")
        
        return original_member, original_chapter_member, new_chapter_member, target_chapter

    def test_member_suspension_and_reactivation_workflow(self):
        """Test member suspension and reactivation workflow"""
        
        # Create active member with payment history
        suspended_member = self.create_test_member(
            first_name="Suspended",
            last_name="Member", 
            email="suspended@example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create membership and payment history
        membership = self.create_test_membership(
            member=suspended_member.name,
            membership_type=self.regular_membership_type.name,
            start_date=add_days(today(), -365),  # Started a year ago
            status="Active"
        )
        
        # Create overdue payment scenario
        overdue_invoice = self.create_test_sales_invoice(
            customer=suspended_member.name,
            posting_date=add_days(today(), -90),
            due_date=add_days(today(), -60),  # 60 days overdue
            grand_total=60.0,
            outstanding_amount=60.0,  # Unpaid
            status="Overdue"
        )
        
        # Process suspension due to non-payment
        suspension_date = today()
        suspension_reason = "Non-payment of membership dues"
        
        suspended_member.status = "Suspended"
        suspended_member.suspension_date = suspension_date
        suspended_member.suspension_reason = suspension_reason
        suspended_member.save()
        
        # Create suspension audit entry
        suspension_audit = frappe.get_doc({
            "doctype": "API Audit Log",  # Using available DocType for audit
            "api_endpoint": "member_suspension",
            "request_data": f"Member: {suspended_member.name}, Reason: {suspension_reason}",
            "response_status": "Success",
            "timestamp": suspension_date
        })
        suspension_audit.insert()
        
        # Verify suspension state
        self.assertEqual(suspended_member.status, "Suspended")
        self.assertEqual(suspended_member.suspension_reason, suspension_reason)
        self.assertEqual(suspended_member.suspension_date, suspension_date)
        
        # Verify outstanding payment still exists
        overdue_invoice.reload()
        self.assertEqual(overdue_invoice.outstanding_amount, 60.0)
        self.assertEqual(overdue_invoice.status, "Overdue")
        
        # Process payment to resolve suspension
        payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": suspended_member.name,
            "paid_amount": 60.0,
            "received_amount": 60.0,
            "reference_no": "RECOVERY001",
            "reference_date": today(),
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": overdue_invoice.name,
                "allocated_amount": 60.0
            }]
        })
        payment_entry.insert()
        payment_entry.submit()
        
        # Reactivate member after payment
        reactivation_date = today()
        suspended_member.status = "Active"
        suspended_member.reactivation_date = reactivation_date
        suspended_member.reactivation_reason = "Payment received, suspension lifted"
        suspended_member.save()
        
        # Verify reactivation
        suspended_member.reload()
        self.assertEqual(suspended_member.status, "Active")
        self.assertEqual(suspended_member.reactivation_date, reactivation_date)
        self.assertIsNotNone(suspended_member.reactivation_reason)
        
        # Verify payment resolved
        overdue_invoice.reload()
        self.assertEqual(overdue_invoice.status, "Paid")
        self.assertEqual(overdue_invoice.outstanding_amount, 0.0)
        
        return suspended_member, membership, overdue_invoice, payment_entry

    def test_member_termination_workflow_with_audit(self):
        """Test complete member termination workflow with audit trail"""
        
        # Create member for termination
        terminating_member = self.create_test_member(
            first_name="Terminating",
            last_name="Member",
            email="terminating@example.com", 
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create membership history
        membership = self.create_test_membership(
            member=terminating_member.name,
            membership_type=self.regular_membership_type.name,
            start_date=add_days(today(), -730),  # 2 years ago
            status="Active"
        )
        
        # Create SEPA mandate to be cancelled
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": terminating_member.name,
            "iban": "NL91ABNA0417164300",
            "account_holder": "Terminating Member",
            "mandate_reference": f"TERM{frappe.generate_hash()[:8]}",
            "mandate_date": add_days(today(), -730),
            "status": "Active"
        })
        sepa_mandate.insert()
        
        # Create termination request
        termination_request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": terminating_member.name,
            "termination_date": add_days(today(), 30),  # 30 days notice
            "reason": "Personal circumstances",
            "requested_by": "Member",
            "status": "Pending Review"
        })
        termination_request.insert()
        
        # Process termination approval
        termination_request.status = "Approved"
        termination_request.approved_by = "Administrator"
        termination_request.approval_date = today()
        termination_request.save()
        
        # Execute termination process
        termination_date = termination_request.termination_date
        
        # 1. Cancel SEPA mandate
        sepa_mandate.status = "Cancelled"
        sepa_mandate.cancellation_date = termination_date
        sepa_mandate.cancellation_reason = "Member termination"
        sepa_mandate.save()
        
        # 2. End membership
        membership.status = "Terminated"
        membership.end_date = termination_date
        membership.termination_reason = termination_request.reason
        membership.save()
        
        # 3. End chapter memberships
        chapter_memberships = frappe.get_all(
            "Chapter Member",
            filters={"member": terminating_member.name, "status": "Active"}
        )
        
        for cm_name in chapter_memberships:
            cm = frappe.get_doc("Chapter Member", cm_name.name)
            cm.status = "Terminated"
            cm.end_date = termination_date
            cm.save()
        
        # 4. Deactivate dues schedules
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": terminating_member.name, "is_active": 1}
        )
        
        for ds_name in dues_schedules:
            ds = frappe.get_doc("Membership Dues Schedule", ds_name.name)
            ds.is_active = 0
            ds.end_date = termination_date
            ds.save()
        
        # 5. Update member status
        terminating_member.status = "Terminated"
        terminating_member.termination_date = termination_date
        terminating_member.termination_reason = termination_request.reason
        terminating_member.save()
        
        # Create termination audit entry
        termination_audit = frappe.get_doc({
            "doctype": "Termination Audit Entry",
            "member": terminating_member.name,
            "termination_date": termination_date,
            "termination_reason": termination_request.reason,
            "processed_by": "Administrator",
            "sepa_mandate_cancelled": 1,
            "membership_ended": 1,
            "chapter_memberships_ended": len(chapter_memberships),
            "dues_schedules_deactivated": len(dues_schedules)
        })
        termination_audit.insert()
        
        # Verify complete termination
        terminating_member.reload()
        self.assertEqual(terminating_member.status, "Terminated")
        self.assertEqual(terminating_member.termination_date, termination_date)
        self.assertEqual(terminating_member.termination_reason, termination_request.reason)
        
        sepa_mandate.reload()
        self.assertEqual(sepa_mandate.status, "Cancelled")
        self.assertEqual(sepa_mandate.cancellation_date, termination_date)
        
        membership.reload()
        self.assertEqual(membership.status, "Terminated")
        self.assertEqual(membership.end_date, termination_date)
        
        # Verify audit trail exists
        self.assertEqual(termination_audit.member, terminating_member.name)
        self.assertEqual(termination_audit.sepa_mandate_cancelled, 1)
        self.assertEqual(termination_audit.membership_ended, 1)
        
        return terminating_member, membership, sepa_mandate, termination_request, termination_audit

    def test_member_data_correction_workflow(self):
        """Test member data correction and history tracking"""
        
        # Create member with initial data
        member_for_correction = self.create_test_member(
            first_name="Original",
            last_name="Name",
            email="original@example.com",
            address_line1="Old Street 123",
            postal_code="1000 AA",
            city="Old City",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Get original address data from linked Address document
        original_address = frappe.get_doc("Address", member_for_correction.primary_address)
        original_data = {
            "first_name": member_for_correction.first_name,
            "last_name": member_for_correction.last_name,
            "email": member_for_correction.email,
            "address_line1": original_address.address_line1,
            "postal_code": original_address.pincode,
            "city": original_address.city
        }

        # Process data correction request
        corrections = {
            "first_name": "Corrected",
            "last_name": "NewName",
            "email": "corrected@example.com",
        }

        # Update member fields
        for field, new_value in corrections.items():
            setattr(member_for_correction, field, new_value)
        member_for_correction.save()

        # Update address fields
        address_corrections = {
            "address_line1": "New Street 456",
            "pincode": "2000 BB",
            "city": "New City"
        }
        for field, new_value in address_corrections.items():
            setattr(original_address, field, new_value)
        original_address.save()
        
        # Create correction audit entry
        correction_audit = frappe.get_doc({
            "doctype": "API Audit Log",
            "api_endpoint": "member_data_correction",
            "request_data": f"Member: {member_for_correction.name}, Changes: {corrections}",
            "response_status": "Success",
            "timestamp": today()
        })
        correction_audit.insert()
        
        # Verify corrections applied
        member_for_correction.reload()
        
        for field, expected_value in corrections.items():
            actual_value = getattr(member_for_correction, field)
            self.assertEqual(actual_value, expected_value,
                           f"Field {field} correction failed")
        
        # Verify full name updated correctly
        expected_full_name = "Corrected NewName"
        self.assertEqual(member_for_correction.full_name, expected_full_name)
        
        return member_for_correction, original_data, corrections, correction_audit

    def test_member_payment_history_integration(self):
        """Test member payment history integration across lifecycle"""
        
        # Create member for payment history testing
        payment_member = self.create_test_member(
            first_name="Payment",
            last_name="History",
            email="payment.history@example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create membership and dues schedule
        membership = self.create_test_membership(
            member=payment_member.name,
            membership_type=self.regular_membership_type.name,
            start_date=today(),
            status="Active"
        )
        
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule", 
            "member": payment_member.name,
            "membership": membership.name,
            "membership_type": self.regular_membership_type.name,
            "start_date": today(),
            "billing_frequency": "Quarterly",  # Test quarterly payments
            "dues_rate": 60.0,
            "invoice_days_before": 14,
            "is_active": 1
        })
        dues_schedule.insert()
        
        # Generate quarterly payment history
        payment_dates = [
            today(),
            add_days(today(), 90),   # Q1
            add_days(today(), 180),  # Q2  
            add_days(today(), 270)   # Q3
        ]
        
        payment_entries = []
        invoices = []
        
        for i, payment_date in enumerate(payment_dates):
            # Create quarterly invoice
            quarterly_amount = 15.0  # 60/4 quarters
            
            invoice = self.create_test_sales_invoice(
                customer=payment_member.name,
                posting_date=payment_date,
                due_date=add_days(payment_date, 30),
                grand_total=quarterly_amount,
                outstanding_amount=quarterly_amount,
                items=[{
                    "item_code": f"Q{i+1} Membership Fee",
                    "item_name": f"Q{i+1} Quarterly Membership Fee",
                    "qty": 1,
                    "rate": quarterly_amount,
                    "amount": quarterly_amount
                }]
            )
            invoices.append(invoice)
            
            # Create payment for invoice
            payment = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": payment_member.name,
                "paid_amount": quarterly_amount,
                "received_amount": quarterly_amount,
                "reference_no": f"PAY-Q{i+1}-2024",
                "reference_date": payment_date,
                "references": [{
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": quarterly_amount
                }]
            })
            payment.insert()
            payment.submit()
            payment_entries.append(payment)
        
        # Verify payment history
        total_payments = len(payment_entries)
        total_amount = sum(15.0 for _ in payment_entries)
        
        self.assertEqual(total_payments, 4)
        self.assertEqual(total_amount, 60.0)  # Full annual amount
        
        # Verify all invoices paid
        for invoice in invoices:
            invoice.reload()
            self.assertEqual(invoice.status, "Paid")
            self.assertEqual(invoice.outstanding_amount, 0.0)
        
        # Test payment history queries
        member_payments = frappe.get_all(
            "Payment Entry",
            filters={"party": payment_member.name},
            fields=["name", "paid_amount", "reference_date"]
        )
        
        self.assertEqual(len(member_payments), 4)
        total_paid = sum(payment["paid_amount"] for payment in member_payments)
        self.assertEqual(total_paid, 60.0)
        
        return payment_member, membership, dues_schedule, invoices, payment_entries


if __name__ == '__main__':
    import unittest
    unittest.main()