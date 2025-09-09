"""
Test Payment Plan Management System - Proper Test Implementation
Converted from script-style test to proper Enhanced Test Factory usage
"""

import frappe
from frappe.utils import add_months, flt, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentPlanSystem(EnhancedTestCase):
    """Test the payment plan management system using proper test patterns"""

    def test_create_payment_plan(self):
        """Test creating a payment plan through Enhanced Test Factory"""
        # Use Enhanced Test Factory to create test member with proper validation
        member = self.create_test_member(
            first_name="Test",
            last_name="Payment User",
            birth_date="1990-01-01"
        )

        # Create payment plan using proper API
        payment_plan = frappe.get_doc({
            "doctype": "Payment Plan",
            "member": member.name,
            "plan_type": "Equal Installments",
            "total_amount": 150.0,
            "number_of_installments": 3,
            "frequency": "Monthly",
            "start_date": today(),
            "status": "Draft",
            "reason": "Test payment plan for system validation",
            "payment_method": "Bank Transfer"
        })
        payment_plan.insert()

        self.assertEqual(payment_plan.member, member.name)
        self.assertEqual(payment_plan.total_amount, 150.0)
        self.assertEqual(payment_plan.number_of_installments, 3)
        self.assertEqual(payment_plan.status, "Draft")

    def test_payment_plan_validation(self):
        """Test payment plan validation logic"""
        member = self.create_test_member(
            first_name="Test",
            last_name="Validation User",
            birth_date="1990-01-01"
        )

        # Test invalid payment plan (negative amount)
        with self.assertRaises(frappe.ValidationError):
            payment_plan = frappe.get_doc({
                "doctype": "Payment Plan",
                "member": member.name,
                "plan_type": "Equal Installments",
                "total_amount": -100.0,  # Invalid negative amount
                "number_of_installments": 3,
                "frequency": "Monthly",
                "start_date": today(),
                "status": "Draft",
                "payment_method": "Bank Transfer"
            })
            payment_plan.insert()

    def test_installment_generation(self):
        """Test installment generation for payment plans"""
        member = self.create_test_member(
            first_name="Test",
            last_name="Installment User",
            birth_date="1990-01-01"
        )

        payment_plan = frappe.get_doc({
            "doctype": "Payment Plan",
            "member": member.name,
            "plan_type": "Equal Installments",
            "total_amount": 150.0,
            "number_of_installments": 3,
            "frequency": "Monthly",
            "start_date": today(),
            "status": "Active",
            "payment_method": "Bank Transfer"
        })
        payment_plan.insert()
        payment_plan.submit()

        # Verify installment calculation
        expected_installment_amount = 150.0 / 3
        self.assertEqual(payment_plan.installment_amount, expected_installment_amount)

        # Test installment dates are properly calculated
        if hasattr(payment_plan, 'installments'):
            self.assertEqual(len(payment_plan.installments), 3)
            for i, installment in enumerate(payment_plan.installments):
                expected_date = add_months(today(), i)
                self.assertEqual(installment.due_date, expected_date)
                self.assertEqual(installment.amount, expected_installment_amount)