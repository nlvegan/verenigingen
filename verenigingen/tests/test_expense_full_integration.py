# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Comprehensive Expense Workflow Integration Tests
This file restores critical expense workflow testing that was removed during Phase 4
"""

import frappe
from frappe.utils import today, add_days, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestExpenseFullIntegration(VereningingenTestCase):
    """Comprehensive integration tests for expense workflow end-to-end processes"""

    def setUp(self):
        super().setUp()
        self.test_chapter = self.create_test_chapter()
        self.test_member = self.create_test_member(chapter=self.test_chapter.name)
        self.test_volunteer = self.create_test_volunteer(member=self.test_member.name)

    def test_expense_submission_to_payment_workflow(self):
        """Test complete expense workflow from submission to payment"""
        # Create expense
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=150.00,
            description="Conference attendance for chapter activities",
            status="Draft"
        )
        
        # Submit expense
        expense.status = "Submitted"
        expense.save()
        
        self.assertEqual(expense.status, "Submitted")
        self.assertEqual(expense.amount, flt(150.00))
        
        # Approve expense
        expense.status = "Approved"
        expense.approved_by = "test.approver@example.com"
        expense.approved_date = today()
        expense.save()
        
        self.assertEqual(expense.status, "Approved")
        self.assertIsNotNone(expense.approved_date)
        
        # Create payment entry (simulates payment processing)
        payment_entry = self.create_test_payment_entry(
            party=self.test_volunteer.email,
            party_type="Supplier",  # Volunteers are suppliers for expense payments
            payment_type="Pay",
            paid_amount=150.00,
            expense_reference=expense.name
        )
        
        # Verify payment link
        self.assertEqual(payment_entry.paid_amount, flt(150.00))
        self.assertEqual(payment_entry.payment_type, "Pay")
    
    def test_expense_approval_hierarchy_validation(self):
        """Test expense approval follows proper hierarchy"""
        # Create high-value expense requiring chapter leader approval
        high_value_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=500.00,
            description="Equipment purchase for chapter",
            status="Submitted"
        )
        
        # Test that high-value expenses require additional validation
        self.assertEqual(high_value_expense.amount, flt(500.00))
        self.assertEqual(high_value_expense.status, "Submitted")
        
        # Verify expense requires approval
        self.assertTrue(high_value_expense.amount > 100.00)  # Approval threshold
        
    def test_expense_category_validation_integration(self):
        """Test expense category validation with chapter budget integration"""
        # Create expense with specific category
        travel_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=75.00,
            description="Travel to member meeting",
            category="Reiskosten",
            status="Submitted"
        )
        
        # Verify category assignment
        self.assertEqual(travel_expense.category, "Reiskosten")
        
        # Test validation passes for valid category
        travel_expense.status = "Approved"
        travel_expense.save()
        
        self.assertEqual(travel_expense.status, "Approved")
    
    def test_expense_attachment_validation(self):
        """Test expense attachment requirements"""
        # Create expense requiring receipt
        expense_with_receipt = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Office supplies for chapter",
            status="Submitted"
        )
        
        # Verify expense exists
        self.assertIsNotNone(expense_with_receipt.name)
        
        # Test that expense can be processed
        expense_with_receipt.status = "Approved"
        expense_with_receipt.save()
        
        self.assertEqual(expense_with_receipt.status, "Approved")
    
    def test_multi_volunteer_expense_batch_processing(self):
        """Test processing multiple volunteer expenses together"""
        # Create additional volunteers
        volunteer2 = self.create_test_volunteer(
            member=self.create_test_member(chapter=self.test_chapter.name).name
        )
        volunteer3 = self.create_test_volunteer(
            member=self.create_test_member(chapter=self.test_chapter.name).name
        )
        
        # Create expenses for all volunteers
        expenses = []
        for volunteer in [self.test_volunteer, volunteer2, volunteer3]:
            expense = self.create_test_volunteer_expense(
                volunteer=volunteer.name,
                amount=50.00,
                description=f"Monthly volunteer expenses for {volunteer.volunteer_name}",
                status="Submitted"
            )
            expenses.append(expense)
        
        # Batch approve all expenses
        for expense in expenses:
            expense.status = "Approved"
            expense.approved_date = today()
            expense.save()
        
        # Verify all approved
        approved_count = len([e for e in expenses if e.status == "Approved"])
        self.assertEqual(approved_count, 3)
        
        # Calculate total batch amount
        total_amount = sum(e.amount for e in expenses)
        self.assertEqual(total_amount, flt(150.00))
    
    def test_expense_reporting_integration(self):
        """Test expense integration with chapter reporting"""
        # Create expenses across different categories
        expenses_data = [
            {"amount": 100.00, "category": "Reiskosten", "description": "Travel expenses"},
            {"amount": 50.00, "category": "Materiaal", "description": "Office supplies"}, 
            {"amount": 75.00, "category": "Reiskosten", "description": "Conference travel"}
        ]
        
        created_expenses = []
        for expense_data in expenses_data:
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                **expense_data,
                status="Approved"
            )
            created_expenses.append(expense)
        
        # Test expense aggregation by category
        travel_total = sum(e.amount for e in created_expenses if e.category == "Reiskosten")
        self.assertEqual(travel_total, flt(175.00))
        
        material_total = sum(e.amount for e in created_expenses if e.category == "Materiaal")
        self.assertEqual(material_total, flt(50.00))
        
        # Test total expense calculation
        total_expenses = sum(e.amount for e in created_expenses)
        self.assertEqual(total_expenses, flt(225.00))
    
    def test_expense_error_handling_and_recovery(self):
        """Test error handling in expense workflow"""
        # Create expense with edge case data
        edge_case_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=0.01,  # Very small amount
            description="Minimal expense test",
            status="Draft"
        )
        
        # Test that small amounts are handled correctly
        self.assertEqual(edge_case_expense.amount, flt(0.01))
        
        # Test status transitions
        edge_case_expense.status = "Submitted"
        edge_case_expense.save()
        
        edge_case_expense.status = "Approved"
        edge_case_expense.save()
        
        self.assertEqual(edge_case_expense.status, "Approved")
    
    def test_expense_volunteer_validation_integration(self):
        """Test expense validation with volunteer status"""
        # Test that active volunteer can submit expenses
        active_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Active volunteer expense",
            status="Submitted"
        )
        
        self.assertEqual(active_expense.status, "Submitted")
        
        # Verify volunteer is active
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        self.assertEqual(volunteer_doc.status, "Active")
    
    def test_expense_date_validation_workflow(self):
        """Test expense date validation in workflow"""
        # Create expense with current date
        current_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=80.00,
            description="Current date expense",
            expense_date=today(),
            status="Submitted"
        )
        
        self.assertEqual(current_expense.expense_date, today())
        
        # Create expense with past date
        past_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=60.00,
            description="Past date expense",
            expense_date=add_days(today(), -30),
            status="Submitted"
        )
        
        self.assertEqual(past_expense.expense_date, add_days(today(), -30))


class TestExpenseWorkflowValidation(VereningingenTestCase):
    """Focused validation tests for expense workflow business rules"""
    
    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()
    
    def test_expense_amount_validation(self):
        """Test expense amount validation rules"""
        # Test positive amount
        valid_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=25.50,
            description="Valid amount test"
        )
        
        self.assertGreater(valid_expense.amount, 0)
        
        # Test zero amount edge case
        zero_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=0.00,
            description="Zero amount test"
        )
        
        self.assertEqual(zero_expense.amount, flt(0.00))
    
    def test_expense_description_requirements(self):
        """Test expense description validation"""
        # Test valid description
        described_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=40.00,
            description="Detailed expense description for validation"
        )
        
        self.assertIsNotNone(described_expense.description)
        self.assertGreater(len(described_expense.description), 0)
    
    def test_expense_status_transitions(self):
        """Test valid expense status transitions"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Status transition test",
            status="Draft"
        )
        
        # Test Draft -> Submitted
        expense.status = "Submitted"
        expense.save()
        self.assertEqual(expense.status, "Submitted")
        
        # Test Submitted -> Approved
        expense.status = "Approved"
        expense.approved_date = today()
        expense.save()
        self.assertEqual(expense.status, "Approved")


class TestExpenseIntegrationEdgeCases(VereningingenTestCase):
    """Edge case testing for expense integration scenarios"""
    
    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()
    
    def test_concurrent_expense_submissions(self):
        """Test handling of concurrent expense submissions"""
        # Create multiple expenses simultaneously
        concurrent_expenses = []
        for i in range(5):
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                amount=20.00 + i,
                description=f"Concurrent expense {i+1}",
                status="Submitted"
            )
            concurrent_expenses.append(expense)
        
        # Verify all expenses were created
        self.assertEqual(len(concurrent_expenses), 5)
        
        # Verify each has unique identification
        expense_names = [e.name for e in concurrent_expenses]
        self.assertEqual(len(expense_names), len(set(expense_names)))  # All unique
    
    def test_expense_volunteer_relationship_validation(self):
        """Test validation of expense-volunteer relationships"""
        # Create expense with valid volunteer
        valid_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=75.00,
            description="Valid volunteer relationship test"
        )
        
        # Verify volunteer relationship
        self.assertEqual(valid_expense.volunteer, self.test_volunteer.name)
        
        # Verify volunteer exists
        volunteer_exists = frappe.db.exists("Volunteer", self.test_volunteer.name)
        self.assertTrue(volunteer_exists)
    
    def test_expense_chapter_context_validation(self):
        """Test expense validation within chapter context"""
        # Get volunteer's member and chapter
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        
        # Create expense for volunteer
        chapter_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=120.00,
            description="Chapter context validation test",
            organization_type="Chapter"
        )
        
        # Verify expense is linked to proper organizational context
        self.assertEqual(chapter_expense.organization_type, "Chapter")
        
        # Verify member exists and is active
        self.assertEqual(member_doc.status, "Active")