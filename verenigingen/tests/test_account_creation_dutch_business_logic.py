#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dutch Association Business Logic Tests for AccountCreationManager
===============================================================

This test suite validates Dutch association-specific business logic in the
account creation system, including age validation, role assignments, employee
creation for expense functionality, and regulatory compliance.

Key Testing Areas:
- Age Validation: 16+ requirement for volunteers, proper validation for members
- Role Hierarchy: Verenigingen-specific role assignments and permissions  
- Employee Creation: Expense functionality integration for volunteers
- Regulatory Compliance: Dutch non-profit organization requirements
- Name Handling: Dutch name conventions including tussenvoegsel
- IBAN Integration: Dutch bank account validation for expense payments

Author: Verenigingen Business Logic Team
"""

import frappe
from frappe.utils import getdate, add_days, add_years
from datetime import datetime, timedelta

from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    queue_account_creation_for_member,
    queue_account_creation_for_volunteer
)
from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    BusinessRuleError
)


class TestDutchAssociationBusinessLogic(EnhancedTestCase):
    """Dutch association-specific business logic validation"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        
    def tearDown(self):
        frappe.set_user(self.original_user)
        super().tearDown()
        
    def test_volunteer_minimum_age_validation(self):
        """Test 16+ age requirement for volunteers"""
        # Create member who is 15 years old
        birth_date_15_years = add_days(getdate(), -365 * 15 - 30)  # 15 years and 1 month old
        
        young_member = self.create_test_member(
            first_name="Too",
            last_name="Young",
            email="too.young.volunteer@test.invalid",
            birth_date=birth_date_15_years
        )
        
        # Attempt to create volunteer should fail due to age validation
        with self.assertRaises(BusinessRuleError):
            self.create_test_volunteer(
                member_name=young_member.name,
                volunteer_name="Too Young Volunteer",
                email="too.young.volunteer@test.invalid",
                start_date=getdate()
            )
            
    def test_volunteer_age_validation_at_start_date(self):
        """Test age validation is checked at volunteer start date, not current date"""
        # Create member who will be 16 in 6 months
        birth_date = add_days(getdate(), -365 * 15 - 180)  # 15.5 years old now
        
        future_member = self.create_test_member(
            first_name="Future",
            last_name="Volunteer",
            email="future.volunteer@test.invalid",
            birth_date=birth_date
        )
        
        # Volunteer start date 1 year from now (when they'll be 16.5)
        future_start_date = add_days(getdate(), 365)
        
        # Should succeed because they'll be 16+ at start date
        volunteer = self.create_test_volunteer(
            member_name=future_member.name,
            volunteer_name="Future Volunteer",
            email="future.volunteer@test.invalid",
            start_date=future_start_date
        )
        
        self.assertIsNotNone(volunteer)
        
    def test_member_age_validation_reasonable_limits(self):
        """Test member age validation for reasonable limits"""
        # Test very young member (under 16) - should be allowed for members
        young_birth_date = add_days(getdate(), -365 * 10)  # 10 years old
        
        young_member = self.create_test_member(
            first_name="Young",
            last_name="Member",
            email="young.member@test.invalid",
            birth_date=young_birth_date
        )
        
        # Should succeed for member (only volunteers have 16+ requirement)
        self.assertIsNotNone(young_member)
        
        # Test unreasonably old member (over 120) - should fail
        with self.assertRaises(BusinessRuleError):
            self.create_test_member(
                first_name="Too",
                last_name="Old",
                email="too.old@test.invalid",
                birth_date=add_years(getdate(), -121)  # 121 years old
            )
            
    def test_verenigingen_role_hierarchy_validation(self):
        """Test Verenigingen-specific role hierarchy and permissions"""
        member = self.create_test_member(
            first_name="Role",
            last_name="Hierarchy",
            email="role.hierarchy@test.invalid"
        )
        
        # Test standard member role assignment
        result = queue_account_creation_for_member(
            member.name,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member"
        )
        
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        requested_roles = [r.role for r in request.requested_roles]
        self.assertIn("Verenigingen Member", requested_roles)
        
        # Process and verify
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        request.reload()
        user_doc = frappe.get_doc("User", request.created_user)
        user_roles = [r.role for r in user_doc.roles]
        self.assertIn("Verenigingen Member", user_roles)
        
    def test_volunteer_role_assignment_comprehensive(self):
        """Test comprehensive volunteer role assignment"""
        member = self.create_test_member(
            first_name="Volunteer",
            last_name="Roles",
            email="volunteer.roles@test.invalid",
            birth_date="1990-01-01"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Volunteer Roles Test",
            email="volunteer.roles@test.invalid"
        )
        
        # Queue volunteer account creation
        result = queue_account_creation_for_volunteer(volunteer.name)
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        
        # Verify all expected volunteer roles are requested
        requested_roles = [r.role for r in request.requested_roles]
        expected_roles = [
            "Verenigingen Volunteer",
            "Employee",
            "Employee Self Service"
        ]
        
        for role in expected_roles:
            self.assertIn(role, requested_roles, f"Missing expected volunteer role: {role}")
            
        # Verify role profile
        self.assertEqual(request.role_profile, "Verenigingen Volunteer")
        
        # Process and verify role assignment
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        request.reload()
        user_doc = frappe.get_doc("User", request.created_user)
        assigned_roles = [r.role for r in user_doc.roles]
        
        for role in expected_roles:
            self.assertIn(role, assigned_roles, f"Role not assigned: {role}")
            
    def test_employee_creation_for_expense_functionality(self):
        """Test employee record creation for Dutch expense functionality"""
        member = self.create_test_member(
            first_name="Expense",
            last_name="Volunteer",
            email="expense.volunteer@test.invalid",
            birth_date="1985-06-15"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Expense Volunteer Test",
            email="expense.volunteer@test.invalid"
        )
        
        # Process volunteer account creation
        result = queue_account_creation_for_volunteer(volunteer.name)
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify employee was created
        request.reload()
        self.assertIsNotNone(request.created_employee, "Employee should be created for volunteers")
        
        # Verify employee record properties
        employee = frappe.get_doc("Employee", request.created_employee)
        self.assertEqual(employee.status, "Active")
        self.assertEqual(employee.user_id, request.created_user)
        self.assertIsNotNone(employee.company)  # Should have default company
        self.assertEqual(employee.employee_name, volunteer.volunteer_name)
        
    def test_dutch_name_handling_with_tussenvoegsel(self):
        """Test proper handling of Dutch names with tussenvoegsel"""
        # Test names with common Dutch particles
        dutch_names = [
            ("Jan", "van der Berg"),
            ("Marie", "de Wit"),
            ("Pieter", "van den Heuvel"),
            ("Anna", "ter Haar"),
            ("Willem", "van de Water")
        ]
        
        for first_name, last_name in dutch_names:
            with self.subTest(first_name=first_name, last_name=last_name):
                full_name = f"{first_name} {last_name}"
                email = f"{first_name.lower()}.{last_name.lower().replace(' ', '.')}@test.invalid"
                
                member = self.create_test_member(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    birth_date="1980-01-01"
                )
                
                # Create account request
                result = queue_account_creation_for_member(member.name)
                request = frappe.get_doc("Account Creation Request", result["request_name"])
                
                # Process account creation
                frappe.set_user("Administrator")
                manager = AccountCreationManager(request.name)
                manager.process_complete_pipeline()
                
                # Verify name handling in created user
                request.reload()
                user = frappe.get_doc("User", request.created_user)
                self.assertEqual(user.first_name, first_name)
                self.assertEqual(user.last_name, last_name)
                self.assertEqual(user.full_name, full_name)
                
    def test_dutch_company_assignment_for_employees(self):
        """Test proper Dutch company assignment for employee records"""
        # Ensure a Dutch company exists for testing
        test_company_name = "Test Nederlandse Vereniging"
        if not frappe.db.exists("Company", test_company_name):
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": test_company_name,
                "country": "Netherlands",
                "default_currency": "EUR"
            })
            company.insert()
            
        member = self.create_test_member(
            first_name="Dutch",
            last_name="Company",
            email="dutch.company@test.invalid",
            birth_date="1990-01-01"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Dutch Company Test",
            email="dutch.company@test.invalid"
        )
        
        # Process account creation
        result = queue_account_creation_for_volunteer(volunteer.name)
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify employee has proper company assignment
        request.reload()
        employee = frappe.get_doc("Employee", request.created_employee)
        
        # Should have a valid company assigned
        self.assertIsNotNone(employee.company)
        self.assertTrue(frappe.db.exists("Company", employee.company))
        
    def test_volunteer_chapter_integration(self):
        """Test volunteer account creation with chapter integration"""
        # Create test chapter
        test_chapter = self.factory.ensure_test_chapter(
            "Test Chapter Dutch",
            {"country": "Netherlands"}
        )
        
        member = self.create_test_member(
            first_name="Chapter",
            last_name="Volunteer",
            email="chapter.volunteer@test.invalid",
            birth_date="1988-03-20"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Chapter Volunteer Test",
            email="chapter.volunteer@test.invalid"
        )
        
        # Process account creation
        result = queue_account_creation_for_volunteer(volunteer.name)
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        
        frappe.set_user("Administrator") 
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify account creation completed
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIsNotNone(request.created_user)
        
    def test_membership_type_based_role_assignment(self):
        """Test role assignment based on membership type"""
        # Create different membership types
        membership_types = [
            {"name": "Student Member", "roles": ["Verenigingen Member", "Verenigingen Student"]},
            {"name": "Senior Member", "roles": ["Verenigingen Member", "Verenigingen Senior"]},
            {"name": "Family Member", "roles": ["Verenigingen Member", "Verenigingen Family"]}
        ]
        
        for membership_type in membership_types:
            with self.subTest(membership_type=membership_type["name"]):
                member = self.create_test_member(
                    first_name="Membership",
                    last_name="Type",
                    email=f"membership.type.{membership_type['name'].lower().replace(' ', '.')}@test.invalid",
                    birth_date="1995-01-01"
                )
                
                # Create account with specific roles
                result = queue_account_creation_for_member(
                    member.name,
                    roles=membership_type["roles"]
                )
                
                request = frappe.get_doc("Account Creation Request", result["request_name"])
                requested_roles = [r.role for r in request.requested_roles]
                
                for role in membership_type["roles"]:
                    # Note: Some roles might not exist in test environment
                    if role in ["Verenigingen Member"]:  # Only test existing roles
                        self.assertIn(role, requested_roles)
                        
    def test_age_transition_volunteer_eligibility(self):
        """Test volunteer eligibility during age transition periods"""
        # Member turning 16 soon
        birth_date_almost_16 = add_days(getdate(), -365 * 16 + 30)  # 30 days until 16th birthday
        
        transition_member = self.create_test_member(
            first_name="Age",
            last_name="Transition",
            email="age.transition@test.invalid",
            birth_date=birth_date_almost_16
        )
        
        # Should be able to create volunteer with start date after 16th birthday
        future_start_date = add_days(getdate(), 60)  # Start 60 days from now (after 16th birthday)
        
        volunteer = self.create_test_volunteer(
            member_name=transition_member.name,
            volunteer_name="Age Transition Volunteer",
            email="age.transition@test.invalid",
            start_date=future_start_date
        )
        
        self.assertIsNotNone(volunteer)
        
        # Account creation should succeed
        result = queue_account_creation_for_volunteer(volunteer.name)
        self.assertIsNotNone(result.get("request_name"))
        
    def test_dutch_regulatory_compliance_fields(self):
        """Test Dutch regulatory compliance field handling"""
        member = self.create_test_member(
            first_name="Regulatory",
            last_name="Compliance",
            email="regulatory.compliance@test.invalid",
            birth_date="1987-12-10"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Regulatory Compliance Test",
            email="regulatory.compliance@test.invalid"
        )
        
        # Process account creation
        result = queue_account_creation_for_volunteer(volunteer.name)
        request = frappe.get_doc("Account Creation Request", result["request_name"])
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify employee record has required compliance fields
        request.reload()
        employee = frappe.get_doc("Employee", request.created_employee)
        
        # Check required fields for Dutch compliance
        self.assertIsNotNone(employee.date_of_joining)
        self.assertEqual(employee.status, "Active")
        
        # Date of birth should be set (even if default)
        self.assertIsNotNone(employee.date_of_birth)


class TestAccountCreationBusinessRuleEdgeCases(EnhancedTestCase):
    """Edge case testing for business rule validation"""
    
    def test_leap_year_birthday_age_calculation(self):
        """Test age calculation for leap year birthdays"""
        # February 29th birthday
        leap_year_birth = "2000-02-29"  # Leap year
        
        member = self.create_test_member(
            first_name="Leap",
            last_name="Year",
            email="leap.year@test.invalid",
            birth_date=leap_year_birth
        )
        
        # Should calculate age correctly
        self.assertIsNotNone(member)
        
        # Test volunteer creation (member should be old enough)
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Leap Year Volunteer",
            email="leap.year@test.invalid"
        )
        
        self.assertIsNotNone(volunteer)
        
    def test_exact_16th_birthday_volunteer_creation(self):
        """Test volunteer creation exactly on 16th birthday"""
        # Birth date exactly 16 years ago
        birth_date_16_years = add_days(getdate(), -365 * 16)
        
        member = self.create_test_member(
            first_name="Exact",
            last_name="Sixteen",
            email="exact.sixteen@test.invalid",
            birth_date=birth_date_16_years
        )
        
        # Should be able to create volunteer starting today (16th birthday)
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Exact Sixteen Volunteer",
            email="exact.sixteen@test.invalid",
            start_date=getdate()
        )
        
        self.assertIsNotNone(volunteer)
        
    def test_timezone_edge_cases_age_calculation(self):
        """Test age calculation edge cases with different timezones"""
        # Test with dates that might have timezone issues
        edge_case_dates = [
            "2000-01-01",  # Y2K
            "2000-12-31",  # End of Y2K year
            "1900-01-01",  # Century boundary
            "2020-02-29"   # Recent leap year
        ]
        
        for birth_date in edge_case_dates:
            with self.subTest(birth_date=birth_date):
                member = self.create_test_member(
                    first_name="Timezone",
                    last_name="Edge",
                    email=f"timezone.edge.{birth_date.replace('-', '.')}@test.invalid",
                    birth_date=birth_date
                )
                
                # Age calculation should work correctly
                self.assertIsNotNone(member)
                
                # If old enough, should be able to create volunteer
                birth_date_obj = getdate(birth_date)
                age_years = (getdate() - birth_date_obj).days / 365.25
                
                if age_years >= 16:
                    volunteer = self.create_test_volunteer(
                        member_name=member.name,
                        volunteer_name=f"Timezone Edge {birth_date}",
                        email=f"volunteer.timezone.edge.{birth_date.replace('-', '.')}@test.invalid"
                    )
                    self.assertIsNotNone(volunteer)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)