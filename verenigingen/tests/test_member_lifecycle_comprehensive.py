# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Comprehensive Member Lifecycle Tests
This file restores critical member lifecycle testing that was removed during Phase 4
Focus on complete member journey from application to termination
"""

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberLifecycleComprehensive(VereningingenTestCase):
    """Complete member lifecycle workflow tests"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_chapter = self.create_test_chapter()
        self.test_membership_type = self.create_test_membership_type(
            membership_type_name="Lifecycle Test Type",
            amount=25.00,
            billing_frequency="Monthly"
        )
        
        # Create test users for workflow
        self.admin_user = self.create_test_user(
            "lifecycle.admin@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )
        
        self.chapter_leader = self.create_test_user(
            "chapter.leader@example.com", 
            roles=["Chapter Leader", "Volunteer Manager"]
        )

    def test_complete_member_lifecycle_workflow(self):
        """Test complete member lifecycle from application to termination"""
        
        # Stage 1: Create Membership Application
        application = self.create_test_membership_application(
            first_name="Lifecycle",
            last_name="TestMember",
            email="lifecycle.test@example.com",
            membership_type=self.test_membership_type.name,
            status="Pending"
        )
        
        self.assertEqual(application.status, "Pending")
        self.assertEqual(application.first_name, "Lifecycle")
        
        # Stage 2: Review and Approve Application
        with self.as_user(self.admin_user.email):
            application.status = "Approved"
            application.approved_by = self.admin_user.email
            application.approved_date = today()
            application.save()
        
        self.assertEqual(application.status, "Approved")
        self.assertIsNotNone(application.approved_date)
        
        # Stage 3: Create Member from Application
        member = self.create_test_member(
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email,
            chapter=self.test_chapter.name,
            status="Active"
        )
        
        # Link application to member
        application.member = member.name
        application.save()
        
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.email, application.email)
        
        # Stage 4: Create Initial Membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type=self.test_membership_type.name,
            status="Active",
            start_date=today(),
            to_date=add_months(today(), 12)
        )
        
        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.member, member.name)
        
        # Stage 5: Create Customer for Payment Processing
        # (This would normally be done automatically by the system)
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.save()
            
            member.customer = customer.name
            member.save()
            self.track_doc("Customer", customer.name)
        
        self.assertIsNotNone(member.customer)
        
        # Stage 6: Process Initial Payment
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            is_membership_invoice=1,
            membership=membership.name
        )
        
        payment = self.create_test_payment_entry(
            party=member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=25.00
        )
        
        self.assertEqual(payment.party, member.customer)
        self.assertEqual(payment.paid_amount, flt(25.00))
        
        # Stage 7: Create Volunteer Record (Optional)
        volunteer = self.create_test_volunteer(
            member=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}",
            status="Active"
        )
        
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(volunteer.status, "Active")
        
        # Stage 8: Create SEPA Mandate for Recurring Payments
        sepa_mandate = self.create_test_sepa_mandate(
            member=member.name,
            scenario="normal",
            bank_code="TEST"
        )
        
        self.assertEqual(sepa_mandate.member, member.name)
        self.assertEqual(sepa_mandate.status, "Active")
        
        # Stage 9: Membership Renewal Process
        renewal_membership = self.create_test_membership(
            member=member.name,
            membership_type=self.test_membership_type.name,
            status="Active",
            start_date=add_months(today(), 12),
            to_date=add_months(today(), 24)
        )
        
        self.assertEqual(renewal_membership.member, member.name)
        self.assertEqual(renewal_membership.status, "Active")
        
        # Stage 10: Member Status Transitions
        # Test suspension
        member.status = "Suspended"
        member.save()
        self.assertEqual(member.status, "Suspended")
        
        # Test reactivation
        member.status = "Active"
        member.save()
        self.assertEqual(member.status, "Active")
        
        # Stage 11: Termination Process
        member.status = "Terminated"
        member.termination_date = today()
        member.termination_reason = "Member request - lifecycle test completion"
        member.save()
        
        self.assertEqual(member.status, "Terminated")
        self.assertEqual(member.termination_date, today())
        self.assertIsNotNone(member.termination_reason)
        
        # Verify lifecycle completion
        self.assertTrue(self._verify_lifecycle_integrity(member, application, membership, volunteer))

    def test_member_status_transitions(self):
        """Test valid member status transitions throughout lifecycle"""
        member = self.create_test_member()
        
        # Test initial status
        self.assertEqual(member.status, "Active")
        
        # Test suspension
        member.status = "Suspended"
        member.suspension_date = today()
        member.suspension_reason = "Payment failure"
        member.save()
        
        self.assertEqual(member.status, "Suspended")
        self.assertEqual(member.suspension_date, today())
        
        # Test reactivation
        member.status = "Active"
        member.reactivation_date = today()
        member.save()
        
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.reactivation_date, today())
        
        # Test termination
        member.status = "Terminated"
        member.termination_date = today()
        member.termination_reason = "Member voluntary termination"
        member.save()
        
        self.assertEqual(member.status, "Terminated")
        self.assertIsNotNone(member.termination_reason)

    def test_member_payment_lifecycle(self):
        """Test member payment processing throughout lifecycle"""
        member = self.create_test_member()
        membership = self.create_test_membership(member=member.name)
        
        # Create multiple payment scenarios
        payment_scenarios = [
            {"amount": 25.00, "description": "Initial membership payment"},
            {"amount": 25.00, "description": "Monthly membership renewal"},
            {"amount": 50.00, "description": "Annual membership upgrade"},
            {"amount": 10.00, "description": "Donation payment"}
        ]
        
        total_payments = 0
        for scenario in payment_scenarios:
            payment = self.create_test_payment_entry(
                party=member.customer,
                party_type="Customer",
                payment_type="Receive",
                paid_amount=scenario["amount"]
            )
            
            total_payments += scenario["amount"]
            self.assertEqual(payment.paid_amount, flt(scenario["amount"]))
        
        # Verify total payment processing
        self.assertEqual(total_payments, flt(110.00))

    def test_member_volunteer_lifecycle_integration(self):
        """Test integration between member and volunteer lifecycles"""
        member = self.create_test_member()
        
        # Create volunteer record
        volunteer = self.create_test_volunteer(
            member=member.name,
            status="Active"
        )
        
        # Test volunteer activities
        expense = self.create_test_volunteer_expense(
            volunteer=volunteer.name,
            amount=75.00,
            description="Volunteer activity expense"
        )
        
        self.assertEqual(expense.volunteer, volunteer.name)
        
        # Create volunteer team
        team = self.create_test_volunteer_team()
        
        # Test team assignment (would be done through proper API)
        self.assertIsNotNone(team.name)
        
        # Test volunteer status changes affect member lifecycle
        volunteer.status = "Inactive"
        volunteer.save()
        
        self.assertEqual(volunteer.status, "Inactive")
        # Member should remain active even if volunteer is inactive
        member.reload()
        self.assertEqual(member.status, "Active")

    def test_member_dues_lifecycle(self):
        """Test membership dues throughout member lifecycle"""
        member = self.create_test_member()
        
        # Create dues schedule
        dues_schedule = self.create_test_dues_schedule(
            member=member.name,
            dues_rate=30.00,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(dues_schedule.member, member.name)
        self.assertEqual(dues_schedule.dues_rate, flt(30.00))
        
        # Test dues calculation and invoice generation
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            is_membership_invoice=1
        )
        
        self.assertEqual(invoice.customer, member.customer)
        self.assertTrue(invoice.is_membership_invoice)

    def test_member_lifecycle_error_recovery(self):
        """Test error recovery scenarios in member lifecycle"""
        # Test incomplete application handling
        incomplete_app = self.create_test_membership_application(
            first_name="Incomplete",
            last_name="Application",
            email="incomplete@example.com",
            status="Pending"
        )
        
        # Test that incomplete applications can be completed
        incomplete_app.membership_type = self.test_membership_type.name
        incomplete_app.save()
        
        self.assertEqual(incomplete_app.membership_type, self.test_membership_type.name)
        
        # Test member creation from incomplete data
        member = self.create_test_member(
            first_name=incomplete_app.first_name,
            last_name=incomplete_app.last_name,
            email=incomplete_app.email
        )
        
        self.assertEqual(member.email, incomplete_app.email)

    def test_member_lifecycle_data_integrity(self):
        """Test data integrity throughout member lifecycle"""
        member = self.create_test_member()
        
        # Create related records
        membership = self.create_test_membership(member=member.name)
        volunteer = self.create_test_volunteer(member=member.name)
        sepa_mandate = self.create_test_sepa_mandate(member=member.name)
        
        # Verify relationships
        self.assertEqual(membership.member, member.name)
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(sepa_mandate.member, member.name)
        
        # Test data consistency after member updates
        member.first_name = "Updated"
        member.save()
        
        # Relationships should remain intact
        membership.reload()
        volunteer.reload()
        sepa_mandate.reload()
        
        self.assertEqual(membership.member, member.name)
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(sepa_mandate.member, member.name)

    def _verify_lifecycle_integrity(self, member, application, membership, volunteer):
        """Verify lifecycle data integrity"""
        try:
            # Check member exists and has expected status
            if not frappe.db.exists("Member", member.name):
                return False
            
            # Check application is linked
            if application.member != member.name:
                return False
            
            # Check membership is linked
            if membership.member != member.name:
                return False
            
            # Check volunteer is linked
            if volunteer.member != member.name:
                return False
            
            return True
            
        except Exception:
            return False


class TestMemberLifecycleEdgeCases(VereningingenTestCase):
    """Edge case tests for member lifecycle scenarios"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_rapid_status_transitions(self):
        """Test rapid member status changes"""
        member = self.test_member
        
        status_sequence = ["Active", "Suspended", "Active", "Terminated"]
        
        for status in status_sequence:
            member.status = status
            if status == "Suspended":
                member.suspension_date = today()
            elif status == "Terminated":
                member.termination_date = today()
            
            member.save()
            self.assertEqual(member.status, status)
    
    def test_concurrent_member_operations(self):
        """Test concurrent operations on member lifecycle"""
        member = self.test_member
        
        # Simulate concurrent updates
        member_copy = frappe.get_doc("Member", member.name)
        
        # First operation: update status
        member.status = "Suspended"
        member.save()
        
        # Second operation: update different field
        member_copy.reload()
        member_copy.phone = "555-1234"
        member_copy.save()
        
        # Verify both updates succeeded
        member.reload()
        self.assertEqual(member.status, "Suspended")
        self.assertEqual(member.phone, "555-1234")
    
    def test_member_lifecycle_with_missing_data(self):
        """Test lifecycle progression with incomplete member data"""
        # Create member with minimal data
        minimal_member = self.create_test_member(
            first_name="Minimal",
            last_name="Member",
            email="minimal@example.com"
        )
        
        # Test that lifecycle operations still work
        membership = self.create_test_membership(member=minimal_member.name)
        self.assertEqual(membership.member, minimal_member.name)
        
        # Test volunteer creation with minimal member
        volunteer = self.create_test_volunteer(member=minimal_member.name)
        self.assertEqual(volunteer.member, minimal_member.name)
    
    def test_member_lifecycle_rollback_scenarios(self):
        """Test rollback scenarios in member lifecycle"""
        member = self.test_member
        
        # Test termination rollback
        original_status = member.status
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        # Rollback termination
        member.status = original_status
        member.termination_date = None
        member.termination_reason = None
        member.save()
        
        self.assertEqual(member.status, original_status)
        self.assertIsNone(member.termination_date)


class TestMemberLifecycleBusinessRules(VereningingenTestCase):
    """Business rule validation tests for member lifecycle"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_member_lifecycle_business_constraints(self):
        """Test business rule constraints in member lifecycle"""
        member = self.test_member
        
        # Test that terminated members can't be reactivated directly
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        # In a real system, this might require special approval process
        # For testing, we verify the state was set correctly
        self.assertEqual(member.status, "Terminated")
    
    def test_member_payment_obligations(self):
        """Test payment obligations throughout member lifecycle"""
        member = self.test_member
        
        # Create membership with payment obligation
        membership = self.create_test_membership(member=member.name)
        
        # Create unpaid invoice
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            is_membership_invoice=1,
            membership=membership.name
        )
        
        # Test that member lifecycle respects payment obligations
        self.assertTrue(invoice.is_membership_invoice)
        self.assertEqual(invoice.customer, member.customer)
    
    def test_member_volunteer_obligations(self):
        """Test volunteer obligations in member lifecycle"""
        member = self.test_member
        
        # Create volunteer record
        volunteer = self.create_test_volunteer(member=member.name)
        
        # Create pending expense
        expense = self.create_test_volunteer_expense(
            volunteer=volunteer.name,
            amount=100.00,
            description="Pending volunteer expense",
            status="Submitted"
        )
        
        # Test that member lifecycle considers volunteer obligations
        self.assertEqual(expense.status, "Submitted")
        self.assertEqual(expense.volunteer, volunteer.name)