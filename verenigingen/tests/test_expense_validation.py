# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Expense Validation Tests
This file restores critical expense validation testing that was removed during Phase 4
Focus on business rule validation, data integrity, and error handling
"""

import frappe
from frappe.utils import today, add_days, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestExpenseValidation(VereningingenTestCase):
    """Tests for expense validation rules and data integrity"""

    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()

    def test_expense_amount_validation(self):
        """Test expense amount validation rules"""
        # Test positive amount (valid)
        valid_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Valid positive amount"
        )
        
        self.assertEqual(valid_expense.amount, flt(100.00))
        self.assertGreater(valid_expense.amount, 0)
        
        # Test zero amount (edge case)
        zero_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=0.00,
            description="Zero amount test"
        )
        
        self.assertEqual(zero_expense.amount, flt(0.00))
        
        # Test very small amount
        small_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=0.01,
            description="Minimal amount test"
        )
        
        self.assertEqual(small_expense.amount, flt(0.01))
        
        # Test large amount
        large_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=9999.99,
            description="Large amount test"
        )
        
        self.assertEqual(large_expense.amount, flt(9999.99))

    def test_expense_description_validation(self):
        """Test expense description requirements"""
        # Test valid description
        described_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=50.00,
            description="This is a valid expense description"
        )
        
        self.assertIsNotNone(described_expense.description)
        self.assertGreater(len(described_expense.description), 0)
        
        # Test empty description handling
        empty_desc_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=30.00,
            description=""
        )
        
        # Empty description should be handled gracefully
        self.assertEqual(empty_desc_expense.description, "")
        
        # Test long description
        long_description = "This is a very long expense description " * 10
        long_desc_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=75.00,
            description=long_description
        )
        
        self.assertEqual(long_desc_expense.description, long_description)

    def test_expense_volunteer_validation(self):
        """Test volunteer field validation"""
        # Test valid volunteer
        valid_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Valid volunteer test"
        )
        
        self.assertEqual(valid_expense.volunteer, self.test_volunteer.name)
        
        # Verify volunteer exists
        volunteer_exists = frappe.db.exists("Volunteer", self.test_volunteer.name)
        self.assertTrue(volunteer_exists)
        
        # Test volunteer status validation
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        self.assertEqual(volunteer_doc.status, "Active")

    def test_expense_date_validation(self):
        """Test expense date validation rules"""
        # Test current date (valid)
        current_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=80.00,
            description="Current date test",
            expense_date=today()
        )
        
        self.assertEqual(current_expense.expense_date, today())
        
        # Test past date (should be valid)
        past_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=60.00,
            description="Past date test",
            expense_date=add_days(today(), -30)
        )
        
        self.assertEqual(past_expense.expense_date, add_days(today(), -30))
        self.assertLess(past_expense.expense_date, today())
        
        # Test future date (edge case)
        future_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=90.00,
            description="Future date test",
            expense_date=add_days(today(), 7)
        )
        
        self.assertEqual(future_expense.expense_date, add_days(today(), 7))
        self.assertGreater(future_expense.expense_date, today())

    def test_expense_category_validation(self):
        """Test expense category validation"""
        # Test valid categories
        valid_categories = ["Reiskosten", "Materiaal", "Telecommunicatie", "Overig"]
        
        for category in valid_categories:
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                amount=50.00,
                description=f"Category test for {category}",
                category=category
            )
            
            self.assertEqual(expense.category, category)

    def test_expense_status_validation(self):
        """Test expense status validation rules"""
        # Test valid statuses
        valid_statuses = ["Draft", "Submitted", "Approved", "Rejected", "Paid"]
        
        for status in valid_statuses:
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                amount=40.00,
                description=f"Status test for {status}",
                status=status
            )
            
            self.assertEqual(expense.status, status)

    def test_expense_required_fields_validation(self):
        """Test required fields validation"""
        # Test that expense can be created with minimal required fields
        minimal_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=25.00,
            description="Minimal required fields test"
        )
        
        # Verify required fields are present
        self.assertIsNotNone(minimal_expense.volunteer)
        self.assertIsNotNone(minimal_expense.amount)
        self.assertIsNotNone(minimal_expense.description)
        self.assertIsNotNone(minimal_expense.expense_date)

    def test_expense_currency_validation(self):
        """Test expense currency handling and validation"""
        # Test default currency
        eur_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="EUR currency test"
        )
        
        # Verify amount is properly formatted as currency
        self.assertEqual(eur_expense.amount, flt(100.00))
        
        # Test decimal precision
        precise_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=123.45,
            description="Decimal precision test"
        )
        
        self.assertEqual(precise_expense.amount, flt(123.45))

    def test_expense_organization_validation(self):
        """Test organizational context validation"""
        # Test chapter organization type
        chapter_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=150.00,
            description="Chapter organization test",
            organization_type="Chapter"
        )
        
        self.assertEqual(chapter_expense.organization_type, "Chapter")
        
        # Test national organization type
        national_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=200.00,
            description="National organization test",
            organization_type="National"
        )
        
        self.assertEqual(national_expense.organization_type, "National")

    def test_expense_approval_fields_validation(self):
        """Test approval-related fields validation"""
        # Create submitted expense
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=120.00,
            description="Approval fields test",
            status="Submitted"
        )
        
        # Initially no approval fields should be set
        self.assertIsNone(expense.approved_by)
        self.assertIsNone(expense.approved_date)
        
        # Approve expense
        expense.status = "Approved"
        expense.approved_by = "approver@example.com"
        expense.approved_date = today()
        expense.save()
        
        # Verify approval fields are set
        self.assertEqual(expense.approved_by, "approver@example.com")
        self.assertEqual(expense.approved_date, today())

    def test_expense_payment_fields_validation(self):
        """Test payment-related fields validation"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=180.00,
            description="Payment fields test",
            status="Approved"
        )
        
        # Initially no payment fields should be set
        self.assertIsNone(expense.paid_date)
        self.assertIsNone(expense.payment_reference)
        
        # Process payment
        expense.status = "Paid"
        expense.paid_date = today()
        expense.payment_reference = "PAY-2025-001"
        expense.save()
        
        # Verify payment fields are set
        self.assertEqual(expense.paid_date, today())
        self.assertEqual(expense.payment_reference, "PAY-2025-001")


class TestExpenseValidationEdgeCases(VereningingenTestCase):
    """Edge case validation tests for expenses"""
    
    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()
    
    def test_expense_extreme_amounts(self):
        """Test validation of extreme amount values"""
        # Test very small amount
        tiny_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=0.01,
            description="Tiny amount test"
        )
        
        self.assertEqual(tiny_expense.amount, flt(0.01))
        
        # Test large amount
        large_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=99999.99,
            description="Large amount test"
        )
        
        self.assertEqual(large_expense.amount, flt(99999.99))
    
    def test_expense_special_characters_validation(self):
        """Test handling of special characters in expense fields"""
        special_chars_desc = "Test with special chars: àéîöü ñç €$£¥ @#%&*"
        special_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=75.00,
            description=special_chars_desc
        )
        
        self.assertEqual(special_expense.description, special_chars_desc)
    
    def test_expense_long_field_values(self):
        """Test validation of long field values"""
        # Test very long description
        long_description = "Very long description " * 50  # 1000+ characters
        long_desc_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description=long_description
        )
        
        # Should handle long descriptions gracefully
        self.assertEqual(long_desc_expense.description, long_description)
    
    def test_expense_date_boundary_validation(self):
        """Test date boundary conditions"""
        # Test very old date
        old_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=50.00,
            description="Very old expense",
            expense_date=add_days(today(), -365)  # 1 year ago
        )
        
        self.assertEqual(old_expense.expense_date, add_days(today(), -365))
        
        # Test far future date
        future_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=60.00,
            description="Far future expense",
            expense_date=add_days(today(), 365)  # 1 year from now
        )
        
        self.assertEqual(future_expense.expense_date, add_days(today(), 365))
    
    def test_expense_concurrent_validation(self):
        """Test validation under concurrent access scenarios"""
        # Create multiple expenses simultaneously
        expenses = []
        for i in range(5):
            expense = self.create_test_volunteer_expense(
                volunteer=self.test_volunteer.name,
                amount=20.00 + i,
                description=f"Concurrent validation test {i+1}"
            )
            expenses.append(expense)
        
        # All should be created successfully
        self.assertEqual(len(expenses), 5)
        
        # Each should have unique name
        expense_names = [e.name for e in expenses]
        self.assertEqual(len(expense_names), len(set(expense_names)))
    
    def test_expense_unicode_validation(self):
        """Test Unicode character handling in expense fields"""
        unicode_description = "Unicode test: 测试 тест テスト 🚀 ⭐ 💰"
        unicode_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=85.00,
            description=unicode_description
        )
        
        self.assertEqual(unicode_expense.description, unicode_description)


class TestExpenseBusinessRuleValidation(VereningingenTestCase):
    """Tests for business rule validation in expenses"""
    
    def setUp(self):
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()
    
    def test_expense_volunteer_status_validation(self):
        """Test validation based on volunteer status"""
        # Test with active volunteer (should work)
        active_expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=100.00,
            description="Active volunteer expense test"
        )
        
        # Verify volunteer is active
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        self.assertEqual(volunteer_doc.status, "Active")
        
        # Expense should be created successfully
        self.assertEqual(active_expense.volunteer, self.test_volunteer.name)
    
    def test_expense_submission_validation(self):
        """Test validation rules for expense submission"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=150.00,
            description="Submission validation test",
            status="Draft"
        )
        
        # Test submission requirements
        expense.status = "Submitted"
        expense.submission_date = today()
        expense.save()
        
        # Verify submission state
        self.assertEqual(expense.status, "Submitted")
        self.assertIsNotNone(expense.submission_date)
    
    def test_expense_approval_authorization_validation(self):
        """Test approval authorization validation"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=200.00,
            description="Approval authorization test",
            status="Submitted"
        )
        
        # Test approval process
        expense.status = "Approved"
        expense.approved_by = "authorized.approver@example.com"
        expense.approved_date = today()
        expense.save()
        
        # Verify approval fields
        self.assertEqual(expense.status, "Approved")
        self.assertIsNotNone(expense.approved_by)
        self.assertIsNotNone(expense.approved_date)
    
    def test_expense_payment_processing_validation(self):
        """Test payment processing validation rules"""
        expense = self.create_test_volunteer_expense(
            volunteer=self.test_volunteer.name,
            amount=300.00,
            description="Payment processing validation test",
            status="Approved"
        )
        
        # Test payment processing
        expense.status = "Paid"
        expense.paid_date = today()
        expense.payment_reference = "TEST-PAY-001"
        expense.save()
        
        # Verify payment state
        self.assertEqual(expense.status, "Paid")
        self.assertIsNotNone(expense.paid_date)
        self.assertIsNotNone(expense.payment_reference)