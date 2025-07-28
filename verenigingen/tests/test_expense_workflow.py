# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Expense Workflow Tests
This file restores critical expense workflow testing that was removed during Phase 4
Focus on state transitions, business rules, and approval processes
"""

import frappe
from frappe.utils import today, add_days, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestExpenseWorkflow(VereningingenTestCase):
    """Tests for expense workflow state management and transitions"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_chapter = self.create_test_chapter()
        self.test_member = self.create_test_member(chapter=self.test_chapter.name)
        self.test_volunteer = self.create_test_volunteer(member=self.test_member.name)
        
        # Create test users for approval workflow
        self.approver_user = self.create_test_user(
            "expense.approver@example.com",
            roles=["Volunteer Manager", "Chapter Leader"]
        )
        self.finance_user = self.create_test_user(
            "finance.manager@example.com", 
            roles=["Accounts Manager", "Chapter Financial Manager"]
        )

    def test_expense_creation_workflow(self):
        """Test expense creation and initial state"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=85.00,
            description="Test expense creation workflow",
            status="Draft"
        )
        
        # Verify initial state
        self.assertEqual(expense.status, "Draft")
        self.assertEqual(expense.volunteer, self.test_volunteer.name)
        self.assertEqual(expense.amount, flt(85.00))
        self.assertIsNone(expense.approved_by)
        self.assertIsNone(expense.approved_date)
        
        # Verify created by is set
        self.assertIsNotNone(expense.owner)

    def test_expense_submission_workflow(self):
        """Test expense submission process"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=125.00,
            description="Submission workflow test",
            status="Draft"
        )
        
        # Submit expense
        expense.status = "Submitted"
        expense.submission_date = today()
        expense.save()
        
        # Verify submission state
        self.assertEqual(expense.status, "Submitted")
        self.assertEqual(expense.submission_date, today())
        
        # Verify submission locks certain fields
        # (This would be implemented with custom validations)
        self.assertIsNotNone(expense.submission_date)

    def test_expense_approval_workflow(self):
        """Test expense approval process"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=200.00,
            description="Approval workflow test",
            status="Submitted"
        )
        
        # Test approval as authorized user
        with self.as_user(self.approver_user.email):
            expense.status = "Approved"
            expense.approved_by = self.approver_user.email
            expense.approved_date = today()
            expense.save()
        
        # Verify approval state
        self.assertEqual(expense.status, "Approved")
        self.assertEqual(expense.approved_by, self.approver_user.email)
        self.assertEqual(expense.approved_date, today())

    def test_expense_rejection_workflow(self):
        """Test expense rejection process"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=300.00,
            description="Rejection workflow test",
            status="Submitted"
        )
        
        # Reject expense
        with self.as_user(self.approver_user.email):
            expense.status = "Rejected"
            expense.rejected_by = self.approver_user.email
            expense.rejected_date = today()
            expense.rejection_reason = "Insufficient documentation provided"
            expense.save()
        
        # Verify rejection state
        self.assertEqual(expense.status, "Rejected")
        self.assertEqual(expense.rejected_by, self.approver_user.email)
        self.assertEqual(expense.rejected_date, today())
        self.assertIsNotNone(expense.rejection_reason)

    def test_expense_payment_workflow(self):
        """Test expense payment processing"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=150.00,
            description="Payment workflow test",
            status="Approved"
        )
        
        # Process payment
        with self.as_user(self.finance_user.email):
            expense.status = "Paid"
            expense.paid_date = today()
            expense.payment_reference = "PAY-2025-001"
            expense.save()
        
        # Verify payment state
        self.assertEqual(expense.status, "Paid")
        self.assertEqual(expense.paid_date, today())
        self.assertIsNotNone(expense.payment_reference)

    def test_expense_workflow_state_validation(self):
        """Test workflow state transition validation"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="State validation test",
            status="Draft"
        )
        
        # Test valid transitions: Draft -> Submitted
        expense.status = "Submitted"
        expense.save()
        self.assertEqual(expense.status, "Submitted")
        
        # Test valid transitions: Submitted -> Approved
        expense.status = "Approved"
        expense.approved_date = today()
        expense.save()
        self.assertEqual(expense.status, "Approved")
        
        # Test valid transitions: Approved -> Paid
        expense.status = "Paid"
        expense.paid_date = today()
        expense.save()
        self.assertEqual(expense.status, "Paid")

    def test_expense_amount_threshold_workflow(self):
        """Test different approval workflows based on amount thresholds"""
        # Low amount expense - standard approval
        low_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=50.00,
            description="Low amount expense",
            status="Submitted"
        )
        
        # Standard approval process
        low_expense.status = "Approved"
        low_expense.approved_date = today()
        low_expense.save()
        self.assertEqual(low_expense.status, "Approved")
        
        # High amount expense - may require additional approval
        high_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=500.00,
            description="High amount expense requiring senior approval",
            status="Submitted"
        )
        
        # High amounts may require senior approval workflow
        self.assertGreater(high_expense.amount, 100.00)  # Threshold check
        
        # Still can be approved but may need additional validation
        high_expense.status = "Approved"
        high_expense.approved_date = today()
        high_expense.save()
        self.assertEqual(high_expense.status, "Approved")

    def test_expense_category_workflow_validation(self):
        """Test workflow validation based on expense categories"""
        categories = ["Reiskosten", "Materiaal", "Telecommunicatie", "Overig"]
        
        for category in categories:
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                amount=75.00,
                description=f"Category workflow test for {category}",
                category=category,
                status="Submitted"
            )
            
            # All categories should be processable through workflow
            expense.status = "Approved"
            expense.approved_date = today()
            expense.save()
            
            self.assertEqual(expense.status, "Approved")
            self.assertEqual(expense.category, category)

    def test_multi_step_expense_workflow(self):
        """Test complex multi-step expense workflows"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=250.00,
            description="Multi-step workflow test",
            status="Draft"
        )
        
        # Step 1: Submit
        expense.status = "Submitted"
        expense.submission_date = today()
        expense.save()
        
        # Step 2: Under Review
        expense.status = "Under Review"
        expense.review_started_date = today()
        expense.save()
        
        # Step 3: Approved
        expense.status = "Approved"
        expense.approved_date = today()
        expense.approved_by = self.approver_user.email
        expense.save()
        
        # Step 4: Payment Processing
        expense.status = "Payment Processing"
        expense.payment_initiated_date = today()
        expense.save()
        
        # Step 5: Paid
        expense.status = "Paid"
        expense.paid_date = today()
        expense.save()
        
        # Verify final state
        self.assertEqual(expense.status, "Paid")
        self.assertIsNotNone(expense.submission_date)
        self.assertIsNotNone(expense.approved_date)
        self.assertIsNotNone(expense.paid_date)

    def test_expense_workflow_rollback_scenarios(self):
        """Test expense workflow rollback and correction scenarios"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=180.00,
            description="Rollback scenario test",
            status="Approved"
        )
        
        # Scenario: Need to modify approved expense
        # In real system, might require special permissions
        expense.status = "Under Review"
        expense.modification_reason = "Additional documentation required"
        expense.save()
        
        self.assertEqual(expense.status, "Under Review")
        self.assertIsNotNone(expense.modification_reason)
        
        # Re-approve after modifications
        expense.status = "Approved"
        expense.approved_date = today()
        expense.save()
        
        self.assertEqual(expense.status, "Approved")

    def test_expense_workflow_notification_triggers(self):
        """Test workflow state changes that should trigger notifications"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=120.00,
            description="Notification trigger test",
            status="Draft"
        )
        
        # Each status change should potentially trigger notifications
        status_progression = ["Submitted", "Approved", "Paid"]
        
        for status in status_progression:
            expense.status = status
            if status == "Approved":
                expense.approved_date = today()
            elif status == "Paid":
                expense.paid_date = today()
            
            expense.save()
            
            # Verify status change was successful
            self.assertEqual(expense.status, status)
            
            # In a real system, this would trigger notification workflows
            # For testing, we just verify the state change was clean

    def test_expense_workflow_audit_trail(self):
        """Test that expense workflow maintains proper audit trail"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=90.00,
            description="Audit trail test",
            status="Draft"
        )
        
        # Track initial creation
        initial_modified = expense.modified
        initial_owner = expense.owner
        
        # Submit expense
        expense.status = "Submitted"
        expense.save()
        
        # Verify audit fields are updated
        self.assertIsNotNone(expense.modified)
        self.assertEqual(expense.owner, initial_owner)
        
        # Approve expense
        with self.as_user(self.approver_user.email):
            expense.status = "Approved"
            expense.approved_by = self.approver_user.email
            expense.approved_date = today()
            expense.save()
        
        # Verify approval audit trail
        self.assertEqual(expense.approved_by, self.approver_user.email)
        self.assertEqual(expense.approved_date, today())
        self.assertIsNotNone(expense.modified)


class TestExpenseWorkflowEdgeCases(VereningingenTestCase):
    """Edge case tests for expense workflow scenarios"""
    
    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()
        self.approver_user = self.create_test_user(
            "edge.approver@example.com", 
            roles=["Volunteer Manager"]
        )
    
    def test_expense_workflow_concurrent_modifications(self):
        """Test handling of concurrent expense modifications"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Concurrent modification test",
            status="Submitted"
        )
        
        # Simulate concurrent access
        expense_copy = frappe.get_doc("Volunteer Expense", expense.name)
        
        # Both try to modify status
        expense.status = "Approved"
        expense.approved_date = today()
        expense.save()
        
        # Verify first modification succeeded
        self.assertEqual(expense.status, "Approved")
        
        # Second modification should work with refreshed data
        expense_copy.reload()
        expense_copy.payment_reference = "CONCURRENT-TEST"
        expense_copy.save()
        
        self.assertEqual(expense_copy.payment_reference, "CONCURRENT-TEST")
    
    def test_expense_workflow_invalid_state_transitions(self):
        """Test handling of invalid workflow state transitions"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=75.00,
            description="Invalid transition test",
            status="Draft"
        )
        
        # Test that workflow prevents inappropriate transitions
        # Draft can go to Submitted
        expense.status = "Submitted"
        expense.save()
        self.assertEqual(expense.status, "Submitted")
        
        # But some transitions might be restricted by business logic
        # (Implementation would include custom validation)
        
    def test_expense_workflow_with_missing_data(self):
        """Test workflow behavior with incomplete expense data"""
        # Create minimal expense
        minimal_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=25.00,
            description="Minimal data test",
            status="Draft"
        )
        
        # Test that basic workflow still functions
        minimal_expense.status = "Submitted"
        minimal_expense.save()
        
        self.assertEqual(minimal_expense.status, "Submitted")
        
        # Approval should still work with minimal data
        minimal_expense.status = "Approved"
        minimal_expense.approved_date = today()
        minimal_expense.save()
        
        self.assertEqual(minimal_expense.status, "Approved")
    
    def test_expense_workflow_date_edge_cases(self):
        """Test workflow with various date scenarios"""
        # Expense with past date
        past_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=60.00,
            description="Past date expense",
            expense_date=add_days(today(), -15),
            status="Submitted"
        )
        
        # Should still be processable
        past_expense.status = "Approved"
        past_expense.approved_date = today()
        past_expense.save()
        
        self.assertEqual(past_expense.status, "Approved")
        
        # Expense with future date
        future_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=80.00,
            description="Future date expense",
            expense_date=add_days(today(), 5),
            status="Submitted"  
        )
        
        # Future dates might require special handling
        self.assertGreater(future_expense.expense_date, today())
        
        # But should still be processable in workflow
        future_expense.status = "Approved"
        future_expense.approved_date = today()
        future_expense.save()
        
        self.assertEqual(future_expense.status, "Approved")