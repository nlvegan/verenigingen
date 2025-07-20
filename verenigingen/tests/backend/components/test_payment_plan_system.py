# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for the payment plan management system
Tests payment plan creation, installment generation, payment processing, and workflows
"""

import frappe
from frappe.utils import today, add_months, add_days, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanSystem(VereningingenTestCase):
    """Test the payment plan management system functionality"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()
        
    def create_simple_test_member(self):
        """Create a simple test member for testing"""
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Member"
        member.email = f"test.member.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
        
    def test_equal_installments_plan_creation(self):
        """Test creating payment plan with equal installments"""
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = 150.0
        payment_plan.number_of_installments = 3
        payment_plan.frequency = "Monthly"
        payment_plan.start_date = today()
        payment_plan.status = "Draft"
        payment_plan.reason = "Test payment plan"
        payment_plan.payment_method = "Bank Transfer"
        
        payment_plan.save()
        self.track_doc("Payment Plan", payment_plan.name)
        
        # Validate configuration
        self.assertEqual(payment_plan.installment_amount, 50.0)  # 150 / 3
        self.assertEqual(len(payment_plan.installments), 3)
        self.assertIsNotNone(payment_plan.end_date)
        
        # Validate installments
        for i, installment in enumerate(payment_plan.installments):
            self.assertEqual(installment.installment_number, i + 1)
            self.assertEqual(installment.amount, 50.0)
            self.assertEqual(installment.status, "Pending")
            self.assertIsNotNone(installment.due_date)
            
        # Validate total amount matches
        total_installments = sum(flt(inst.amount) for inst in payment_plan.installments)
        self.assertEqual(total_installments, payment_plan.total_amount)
        
    def test_deferred_payment_plan(self):
        """Test creating deferred payment plan"""
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.plan_type = "Deferred Payment"
        payment_plan.total_amount = 120.0
        payment_plan.start_date = today()
        payment_plan.end_date = add_months(today(), 3)
        payment_plan.status = "Draft"
        payment_plan.reason = "Deferred payment test"
        
        payment_plan.save()
        self.track_doc("Payment Plan", payment_plan.name)
        
        # Validate deferred configuration
        self.assertEqual(payment_plan.number_of_installments, 1)
        self.assertEqual(payment_plan.installment_amount, 120.0)
        self.assertEqual(len(payment_plan.installments), 1)
        
        # Validate single installment
        installment = payment_plan.installments[0]
        self.assertEqual(installment.amount, 120.0)
        self.assertEqual(installment.due_date, payment_plan.end_date)
        
    def test_custom_schedule_plan(self):
        """Test creating custom schedule payment plan"""
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.plan_type = "Custom Schedule"
        payment_plan.total_amount = 200.0
        payment_plan.start_date = today()
        payment_plan.status = "Draft"
        
        # Manually add custom installments
        payment_plan.append("installments", {
            "installment_number": 1,
            "due_date": add_days(today(), 30),
            "amount": 80.0,
            "status": "Pending"
        })
        
        payment_plan.append("installments", {
            "installment_number": 2,
            "due_date": add_days(today(), 60),
            "amount": 70.0,
            "status": "Pending"
        })
        
        payment_plan.append("installments", {
            "installment_number": 3,
            "due_date": add_days(today(), 90),
            "amount": 50.0,
            "status": "Pending"
        })
        
        payment_plan.save()
        self.track_doc("Payment Plan", payment_plan.name)
        
        # Validate custom schedule
        self.assertEqual(len(payment_plan.installments), 3)
        self.assertEqual(payment_plan.installments[0].amount, 80.0)
        self.assertEqual(payment_plan.installments[1].amount, 70.0)
        self.assertEqual(payment_plan.installments[2].amount, 50.0)
        
    def test_payment_processing(self):
        """Test processing payments for installments"""
        payment_plan = self.create_test_payment_plan()
        
        # Process first installment
        first_installment = payment_plan.installments[0]
        original_amount = first_installment.amount
        
        payment_plan.process_payment(
            installment_number=1,
            payment_amount=original_amount,
            payment_reference="TEST-PAY-001",
            payment_date=today()
        )
        
        # Reload and validate
        payment_plan.reload()
        first_installment = payment_plan.installments[0]
        
        self.assertEqual(first_installment.status, "Paid")
        self.assertEqual(first_installment.payment_reference, "TEST-PAY-001")
        self.assertEqual(payment_plan.total_paid, original_amount)
        self.assertEqual(payment_plan.remaining_balance, payment_plan.total_amount - original_amount)
        
    def test_partial_payment_processing(self):
        """Test processing partial payments"""
        payment_plan = self.create_test_payment_plan()
        
        # Process partial payment
        installment_amount = payment_plan.installments[0].amount
        partial_amount = installment_amount / 2
        
        payment_plan.process_payment(
            installment_number=1,
            payment_amount=partial_amount,
            payment_reference="PARTIAL-001"
        )
        
        # Reload and validate
        payment_plan.reload()
        first_installment = payment_plan.installments[0]
        
        # Should still be pending with reduced amount
        self.assertEqual(first_installment.status, "Pending")
        self.assertEqual(first_installment.amount, installment_amount - partial_amount)
        self.assertTrue("Partial payment" in first_installment.notes)
        
    def test_overdue_installment_processing(self):
        """Test marking installments as overdue"""
        payment_plan = self.create_test_payment_plan()
        
        # Set first installment due date in the past
        payment_plan.installments[0].due_date = add_days(today(), -5)
        payment_plan.save()
        
        # Mark as overdue
        payment_plan.mark_installment_overdue(1)
        
        # Validate status change
        payment_plan.reload()
        self.assertEqual(payment_plan.installments[0].status, "Overdue")
        self.assertEqual(payment_plan.consecutive_missed_payments, 1)
        
    def test_payment_plan_completion(self):
        """Test payment plan completion workflow"""
        payment_plan = self.create_test_payment_plan()
        
        # Pay all installments
        for i, installment in enumerate(payment_plan.installments):
            payment_plan.process_payment(
                installment_number=i + 1,
                payment_amount=installment.amount,
                payment_reference=f"PAY-{i+1:03d}"
            )
            
        # Reload and validate completion
        payment_plan.reload()
        self.assertEqual(payment_plan.status, "Completed")
        self.assertEqual(payment_plan.remaining_balance, 0)
        self.assertEqual(payment_plan.total_paid, payment_plan.total_amount)
        
        # All installments should be paid
        for installment in payment_plan.installments:
            self.assertEqual(installment.status, "Paid")
            
    def test_payment_plan_suspension(self):
        """Test payment plan suspension due to consecutive failures"""
        payment_plan = self.create_test_payment_plan()
        
        # Mark multiple installments as overdue
        for i in range(3):
            payment_plan.installments[i].due_date = add_days(today(), -(i+1)*5)
            payment_plan.mark_installment_overdue(i + 1)
            
        # Should be suspended after 3 consecutive failures
        payment_plan.reload()
        self.assertEqual(payment_plan.status, "Suspended")
        self.assertEqual(payment_plan.consecutive_missed_payments, 3)
        
    def test_payment_plan_approval_workflow(self):
        """Test payment plan approval workflow"""
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = 90.0
        payment_plan.number_of_installments = 3
        payment_plan.frequency = "Monthly"
        payment_plan.start_date = today()
        payment_plan.status = "Pending Approval"
        payment_plan.approval_required = 1
        payment_plan.reason = "Financial hardship"
        
        payment_plan.save()
        self.track_doc("Payment Plan", payment_plan.name)
        
        # Approve the plan
        payment_plan.approved_by = frappe.session.user
        payment_plan.approval_date = frappe.utils.now()
        payment_plan.status = "Active"
        payment_plan.save()
        payment_plan.submit()
        
        # Validate approval
        self.assertEqual(payment_plan.status, "Active")
        self.assertEqual(payment_plan.approved_by, frappe.session.user)
        self.assertIsNotNone(payment_plan.approval_date)
        
    def test_payment_plan_api_request(self):
        """Test payment plan API request functionality"""
        from verenigingen.api.payment_plan_management import request_payment_plan
        
        # Set session user to member email for permission test
        self.test_member.email = "test.member@example.com"
        self.test_member.save()
        
        with self.set_user(self.test_member.email):
            result = request_payment_plan(
                member=self.test_member.name,
                total_amount=120.0,
                preferred_installments=4,
                preferred_frequency="Monthly",
                reason="Need payment plan for monthly dues"
            )
            
            self.assertTrue(result.get("success"))
            self.assertIsNotNone(result.get("payment_plan_id"))
            
            # Validate created plan
            plan = frappe.get_doc("Payment Plan", result["payment_plan_id"])
            self.track_doc("Payment Plan", plan.name)
            
            self.assertEqual(plan.member, self.test_member.name)
            self.assertEqual(plan.total_amount, 120.0)
            self.assertEqual(plan.number_of_installments, 4)
            self.assertEqual(plan.frequency, "Monthly")
            self.assertEqual(plan.status, "Pending Approval")
            
    def test_payment_plan_preview_calculation(self):
        """Test payment plan preview calculation API"""
        from verenigingen.api.payment_plan_management import calculate_payment_plan_preview
        
        result = calculate_payment_plan_preview(
            total_amount=180.0,
            installments=6,
            frequency="Monthly"
        )
        
        self.assertTrue(result.get("success"))
        preview = result.get("preview")
        
        self.assertEqual(preview["total_amount"], 180.0)
        self.assertEqual(preview["installment_amount"], 30.0)
        self.assertEqual(preview["number_of_installments"], 6)
        self.assertEqual(preview["frequency"], "Monthly")
        self.assertIsNotNone(preview["start_date"])
        self.assertIsNotNone(preview["end_date"])
        
    def test_get_member_payment_plans_api(self):
        """Test API to get member payment plans"""
        from verenigingen.api.payment_plan_management import get_member_payment_plans
        
        # Create test payment plans
        plan1 = self.create_test_payment_plan()
        plan2 = self.create_test_payment_plan()
        
        # Set member email for permission test
        self.test_member.email = "test.member@example.com"
        self.test_member.save()
        
        with self.set_user(self.test_member.email):
            result = get_member_payment_plans()
            
            self.assertTrue(result.get("success"))
            plans = result.get("payment_plans", [])
            
            # Should find our test plans
            plan_names = [p["name"] for p in plans]
            self.assertIn(plan1.name, plan_names)
            self.assertIn(plan2.name, plan_names)
            
            # Validate plan structure
            test_plan_data = next(p for p in plans if p["name"] == plan1.name)
            self.assertEqual(test_plan_data["total_amount"], plan1.total_amount)
            self.assertEqual(test_plan_data["number_of_installments"], plan1.number_of_installments)
            self.assertTrue("installments" in test_plan_data)
            
    def test_dues_schedule_integration(self):
        """Test payment plan integration with membership dues schedule"""
        # Create membership type and dues schedule
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Create payment plan linked to dues schedule
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.membership_dues_schedule = dues_schedule.name
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = dues_schedule.dues_rate * 3  # 3 months
        payment_plan.number_of_installments = 3
        payment_plan.frequency = "Monthly"
        payment_plan.start_date = today()
        payment_plan.status = "Active"
        
        payment_plan.save()
        payment_plan.submit()
        self.track_doc("Payment Plan", payment_plan.name)
        
        # Dues schedule should be paused
        dues_schedule.reload()
        self.assertEqual(dues_schedule.status, "Payment Plan Active")
        self.assertEqual(dues_schedule.payment_plan, payment_plan.name)
        
    def test_payment_plan_cancellation(self):
        """Test payment plan cancellation"""
        payment_plan = self.create_test_payment_plan()
        
        # Cancel the plan
        payment_plan.cancel_plan("Member requested cancellation")
        
        # Validate cancellation
        self.assertEqual(payment_plan.status, "Cancelled")
        
    def test_installment_validation(self):
        """Test validation of payment plan configuration"""
        # Test invalid number of installments
        with self.assertRaises(frappe.ValidationError):
            payment_plan = frappe.new_doc("Payment Plan")
            payment_plan.member = self.test_member.name
            payment_plan.plan_type = "Equal Installments"
            payment_plan.total_amount = 100.0
            payment_plan.number_of_installments = 0  # Invalid
            payment_plan.save()
            
        # Test missing frequency
        with self.assertRaises(frappe.ValidationError):
            payment_plan = frappe.new_doc("Payment Plan")
            payment_plan.member = self.test_member.name
            payment_plan.plan_type = "Equal Installments"
            payment_plan.total_amount = 100.0
            payment_plan.number_of_installments = 3
            payment_plan.frequency = ""  # Missing
            payment_plan.save()
            
    def test_scheduled_overdue_processing(self):
        """Test scheduled processing of overdue installments"""
        from verenigingen.verenigingen.doctype.payment_plan.payment_plan import process_overdue_installments
        
        # Create payment plan with overdue installment
        payment_plan = self.create_test_payment_plan()
        payment_plan.installments[0].due_date = add_days(today(), -1)
        payment_plan.installments[0].status = "Pending"
        payment_plan.save()
        
        # Run scheduled processing
        updated_count = process_overdue_installments()
        
        # Should have processed our overdue installment
        self.assertGreaterEqual(updated_count, 1)
        
        # Verify installment is now overdue
        payment_plan.reload()
        self.assertEqual(payment_plan.installments[0].status, "Overdue")
        
    # Helper methods
    
    def create_test_payment_plan(self):
        """Create a standard test payment plan"""
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = self.test_member.name
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = 120.0
        payment_plan.number_of_installments = 4
        payment_plan.frequency = "Monthly"
        payment_plan.start_date = today()
        payment_plan.status = "Active"
        payment_plan.reason = "Test payment plan"
        payment_plan.payment_method = "Bank Transfer"
        
        payment_plan.save()
        self.track_doc("Payment Plan", payment_plan.name)
        return payment_plan
        
    def create_test_membership_type(self):
        """Create a simple test membership type"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Membership {frappe.generate_hash(length=6)}"
        membership_type.amount = 30.0
        membership_type.is_active = 1
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_dues_schedule(self, membership_type):
        """Create a test dues schedule"""
        # First create a membership
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        # Then create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.dues_rate = membership_type.amount
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule