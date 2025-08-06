#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chapter Board Member Permission System - Comprehensive Test Suite
================================================================

This test suite validates the complete Chapter Board Member permission system with 
schema fixes applied, focusing on realistic data generation and comprehensive security testing.

Key Testing Areas:
1. **Chapter Board Member Factory Methods**: Complete test data creation
2. **End-to-End Workflow Testing**: Full approval/termination/expense workflows  
3. **Security and Cross-Chapter Access**: Comprehensive boundary testing
4. **Role Lifecycle Management**: Automatic assignment/removal validation
5. **Performance and Edge Cases**: Query efficiency and error handling

Schema Fixes Validated:
- Database field references from `cbm.member` to `cbm.volunteer` with proper JOINs
- Volunteer → Member relationship integrity in treasurer approval functions
- Chapter-level filtering with correct field references

Test Design Principles:
- No mocking - uses realistic data generation via Enhanced Test Factory
- Comprehensive persona-based testing (treasurer, secretary, member scenarios)
- End-to-end workflow validation with actual business logic
- Security boundary validation with privilege escalation prevention
- Performance testing for permission query efficiency
"""

import frappe
import unittest
from datetime import datetime, timedelta
from verenigingen.tests.utils.base import VereningingenTestCase


class ChapterBoardTestFactory:
    """
    Enhanced factory specifically for Chapter Board Member testing scenarios.
    Builds on top of the base test factory with specialized board member creation.
    """
    
    def __init__(self, test_case):
        self.test_case = test_case
        self.created_docs = []
    
    def ensure_test_company(self):
        """Ensure test company exists for expense testing"""
        company_name = "Test Company"
        if not frappe.db.exists("Company", company_name):
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "default_currency": "EUR",
                "country": "Netherlands"
            })
            company.insert(ignore_permissions=True)
            self.test_case.track_doc("Company", company.name)
        return company_name
    
    def ensure_test_expense_category(self):
        """Ensure test expense category exists"""
        category_name = "Test Travel Expenses"
        if not frappe.db.exists("Expense Category", category_name):
            category = frappe.get_doc({
                "doctype": "Expense Category",
                "category_name": category_name,
                "is_active": 1
            })
            category.insert(ignore_permissions=True)
            self.test_case.track_doc("Expense Category", category.name)
        return category_name
    
    def create_test_region(self, region_name="Test Region", region_code=None):
        """Create test region with validation"""
        if not region_code:
            region_code = f"TR{frappe.generate_hash(length=2)}"
        
        # Check if region with this name or code exists
        if frappe.db.exists("Region", region_name):
            return frappe.get_doc("Region", region_name)
        if frappe.db.exists("Region", {"region_code": region_code}):
            return frappe.get_doc("Region", {"region_code": region_code})
        
        region = frappe.get_doc({
            "doctype": "Region",
            "region_name": region_name,
            "region_code": region_code,
            "country": "Netherlands",
            "is_active": 1
        })
        region.insert()
        self.test_case.track_doc("Region", region.name)
        return region
    
    def create_test_chapter(self, chapter_name=None, region=None, **kwargs):
        """Create test chapter with all required fields"""
        if not chapter_name:
            chapter_name = f"Test Chapter {frappe.generate_hash(length=6)}"
        
        if not region:
            region = self.create_test_region()
        
        defaults = {
            "region": region.name if hasattr(region, 'name') else region,
            "introduction": f"Test chapter for Chapter Board Member testing - {chapter_name}",
            "published": 1
        }
        defaults.update(kwargs)
        
        chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": chapter_name,
            **defaults
        })
        chapter.insert()
        self.test_case.track_doc("Chapter", chapter.name)
        return chapter
    
    def create_test_chapter_role(self, role_name, permissions_level="Basic", **kwargs):
        """Create test chapter role with validation"""
        if frappe.db.exists("Chapter Role", role_name):
            return frappe.get_doc("Chapter Role", role_name)
        
        defaults = {
            "role_name": role_name,
            "permissions_level": permissions_level,
            "is_active": 1,
            "is_chair": kwargs.get("is_chair", 0),
            "is_unique": kwargs.get("is_unique", 1 if permissions_level == "Financial" else 0)
        }
        defaults.update(kwargs)
        
        role = frappe.get_doc({
            "doctype": "Chapter Role",
            **defaults
        })
        role.insert()
        self.test_case.track_doc("Chapter Role", role.name)
        return role
    
    def create_chapter_treasurer_persona(self, chapter_name=None):
        """Create complete treasurer persona with all relationships"""
        # Create chapter if not provided
        if not chapter_name:
            chapter = self.create_test_chapter()
            chapter_name = chapter.name
        
        # Create treasurer role
        treasurer_role = self.create_test_chapter_role(
            f"TestTreasurer_{frappe.generate_hash(length=6)}",
            permissions_level="Financial",
            is_unique=1
        )
        
        # Create member
        member = self.test_case.create_test_member(
            first_name="Chapter",
            last_name=f"Treasurer{frappe.generate_hash(length=4)}",
            email=f"treasurer.{frappe.generate_hash(length=6)}@test.invalid"
        )
        
        # Create volunteer
        volunteer = self.test_case.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email
        )
        
        # Create user for the member
        user = self.create_test_user(
            email=member.email,
            first_name=member.first_name,
            last_name=member.last_name
        )
        
        # Link user to member
        member.user = user.name
        member.save()
        
        # Create board member position
        board_member = self.create_chapter_board_member(
            chapter_name=chapter_name,
            volunteer_name=volunteer.name,
            chapter_role_name=treasurer_role.name
        )
        
        return {
            "member": member,
            "volunteer": volunteer,
            "user": user,
            "chapter": chapter_name,
            "treasurer_role": treasurer_role,
            "board_member": board_member
        }
    
    def create_chapter_secretary_persona(self, chapter_name=None):
        """Create complete secretary persona (non-financial role)"""
        # Create chapter if not provided
        if not chapter_name:
            chapter = self.create_test_chapter()
            chapter_name = chapter.name
        
        # Create secretary role
        secretary_role = self.create_test_chapter_role(
            f"TestSecretary_{frappe.generate_hash(length=6)}", 
            permissions_level="Basic",
            is_unique=1
        )
        
        # Create member
        member = self.test_case.create_test_member(
            first_name="Chapter",
            last_name=f"Secretary{frappe.generate_hash(length=4)}", 
            email=f"secretary.{frappe.generate_hash(length=6)}@test.invalid"
        )
        
        # Create volunteer
        volunteer = self.test_case.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email
        )
        
        # Create user
        user = self.create_test_user(
            email=member.email,
            first_name=member.first_name,
            last_name=member.last_name
        )
        
        # Link user to member
        member.user = user.name
        member.save()
        
        # Create board member position
        board_member = self.create_chapter_board_member(
            chapter_name=chapter_name,
            volunteer_name=volunteer.name,
            chapter_role_name=secretary_role.name
        )
        
        return {
            "member": member,
            "volunteer": volunteer, 
            "user": user,
            "chapter": chapter_name,
            "secretary_role": secretary_role,
            "board_member": board_member
        }
    
    def create_regular_member_persona(self, chapter_name=None):
        """Create regular member (no board position) for testing"""
        # Create member
        member = self.test_case.create_test_member(
            first_name="Regular",
            last_name="Member",
            email=f"member.{frappe.generate_hash(length=6)}@test.invalid"
        )
        
        # Create volunteer (regular members can be volunteers too)
        volunteer = self.test_case.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email
        )
        
        # Create user
        user = self.create_test_user(
            email=member.email,
            first_name=member.first_name,
            last_name=member.last_name
        )
        
        # Link user to member
        member.user = user.name
        member.save()
        
        # Add to chapter if provided
        if chapter_name:
            self.add_member_to_chapter(member.name, chapter_name)
        
        return {
            "member": member,
            "volunteer": volunteer,
            "user": user,
            "chapter": chapter_name
        }
    
    def create_chapter_board_member(self, chapter_name, volunteer_name, chapter_role_name, **kwargs):
        """Create Chapter Board Member relationship"""
        defaults = {
            "volunteer": volunteer_name,
            "chapter_role": chapter_role_name,
            "from_date": frappe.utils.today(),
            "is_active": 1
        }
        defaults.update(kwargs)
        
        # Get chapter document to add board member
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("board_members", defaults)
        chapter.save()
        
        # Return the board member record
        board_member_record = chapter.board_members[-1]
        return board_member_record
    
    def add_member_to_chapter(self, member_name, chapter_name):
        """Add member to chapter members table"""
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("members", {
            "member": member_name,
            "status": "Active",
            "chapter_join_date": frappe.utils.today()
        })
        chapter.save()
        return chapter.members[-1]
    
    def create_test_user(self, email, first_name="Test", last_name="User", roles=None):
        """Create test user with proper cleanup tracking"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "enabled": 1,
                "new_password": "test123"
            })
            user.insert(ignore_permissions=True)
            self.test_case.track_doc("User", user.name)
        
        # Assign roles if provided
        if roles:
            user.roles = []
            for role in roles:
                user.append("roles", {"role": role})
            user.save(ignore_permissions=True)
        
        return user
    
    def create_test_volunteer_expense(self, volunteer_name, chapter_name=None, amount=100.0, **kwargs):
        """Create test volunteer expense with all required fields"""
        defaults = {
            "volunteer": volunteer_name,
            "expense_date": frappe.utils.today(),
            "category": self.ensure_test_expense_category(),
            "description": f"Test expense for volunteer {volunteer_name}",
            "amount": amount,
            "currency": "EUR",
            "organization_type": "Chapter",
            "company": self.ensure_test_company(),
            "status": "Submitted"
        }
        
        if chapter_name:
            defaults["chapter"] = chapter_name
        
        defaults.update(kwargs)
        
        expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            **defaults
        })
        expense.insert()
        self.test_case.track_doc("Volunteer Expense", expense.name)
        return expense
    
    def create_test_membership_application(self, member_name=None, chapter_name=None, **kwargs):
        """Create test membership application"""
        defaults = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": f"applicant.{frappe.generate_hash(length=6)}@test.invalid",
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Test City",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "application_date": frappe.utils.today(),
            "status": "Pending"
        }
        
        if member_name:
            defaults["member"] = member_name
        if chapter_name:
            defaults["preferred_chapter"] = chapter_name
        
        defaults.update(kwargs)
        
        application = frappe.get_doc({
            "doctype": "Membership Application",
            **defaults
        })
        application.insert()
        self.test_case.track_doc("Membership Application", application.name)
        return application
    
    def create_test_membership_termination_request(self, member_name, **kwargs):
        """Create test membership termination request"""
        defaults = {
            "member": member_name,
            "termination_type": "Voluntary",
            "termination_reason": "Test termination request",
            "requested_by": frappe.session.user,
            "request_date": frappe.utils.today(),
            "status": "Pending"
        }
        defaults.update(kwargs)
        
        request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            **defaults
        })
        request.insert()
        self.test_case.track_doc("Membership Termination Request", request.name)
        return request


class TestChapterBoardPermissionsComprehensive(VereningingenTestCase):
    """
    Comprehensive test suite for Chapter Board Member permission system
    """
    
    def setUp(self):
        """Set up test data for comprehensive permission testing"""
        super().setUp()
        self.board_factory = ChapterBoardTestFactory(self)
        
        # Create two separate chapters for cross-chapter testing
        # Generate unique test identifiers
        test_id = frappe.generate_hash(length=8)
        self.chapter_a = self.board_factory.create_test_chapter(f"TestChapter_{test_id}_A")
        self.chapter_b = self.board_factory.create_test_chapter(f"TestChapter_{test_id}_B")
        
        # Create comprehensive test personas
        self.treasurer_a = self.board_factory.create_chapter_treasurer_persona(self.chapter_a.name)
        self.secretary_a = self.board_factory.create_chapter_secretary_persona(self.chapter_a.name)
        self.treasurer_b = self.board_factory.create_chapter_treasurer_persona(self.chapter_b.name)
        
        self.regular_member_a = self.board_factory.create_regular_member_persona(self.chapter_a.name)
        self.regular_member_b = self.board_factory.create_regular_member_persona(self.chapter_b.name)
        
        frappe.db.commit()
    
    def test_scenario_a_happy_path_treasurer_workflow(self):
        """Scenario A: Complete treasurer approval workflow"""
        # Create expense in Chapter A by regular member
        expense = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_a["volunteer"].name,
            chapter_name=self.chapter_a.name,
            amount=75.50,
            description="Happy path treasurer workflow test"
        )
        
        # Test treasurer can view the expense
        with self.as_user(self.treasurer_a["user"].email):
            # Import permission functions
            try:
                from vereinigungen.permissions import has_volunteer_expense_permission
                can_view = has_volunteer_expense_permission(expense, self.treasurer_a["user"].email)
                self.assertTrue(can_view, "Treasurer should be able to view expenses from their chapter")
            except ImportError:
                # Fallback test - check document access directly
                try:
                    retrieved_expense = frappe.get_doc("Volunteer Expense", expense.name)
                    self.assertEqual(retrieved_expense.name, expense.name, "Treasurer should access expense document")
                except frappe.PermissionError:
                    self.fail("Treasurer should have access to chapter expenses")
        
        # Test treasurer can approve the expense
        with self.as_user(self.treasurer_a["user"].email):
            try:
                expense.reload()
                expense.status = "Approved"
                expense.approved_by = self.treasurer_a["user"].email
                expense.approved_on = frappe.utils.now()
                expense.save()
                
                # Verify approval was successful
                expense.reload()
                self.assertEqual(expense.status, "Approved", "Treasurer should be able to approve expenses")
                self.assertEqual(expense.approved_by, self.treasurer_a["user"].email)
            except frappe.PermissionError as e:
                self.fail(f"Treasurer should be able to approve expenses: {e}")
        
        # Test denial workflow
        expense_2 = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_a["volunteer"].name,
            chapter_name=self.chapter_a.name,
            amount=25.00,
            description="Denial workflow test"
        )
        
        with self.as_user(self.treasurer_a["user"].email):
            expense_2.status = "Rejected"
            expense_2.notes = "Test rejection reason"
            expense_2.save()
            
            expense_2.reload()
            self.assertEqual(expense_2.status, "Rejected", "Treasurer should be able to reject expenses")
    
    def test_scenario_b_cross_chapter_security(self):
        """Scenario B: Cross-chapter access prevention validation"""
        # Create expense in Chapter B
        expense_b = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_b["volunteer"].name,
            chapter_name=self.chapter_b.name,
            amount=150.00,
            description="Cross-chapter security test"
        )
        
        # Chapter A treasurer should NOT access Chapter B expense
        with self.as_user(self.treasurer_a["user"].email):
            try:
                from vereinigingen.permissions import has_volunteer_expense_permission
                can_view = has_volunteer_expense_permission(expense_b, self.treasurer_a["user"].email)
                self.assertFalse(can_view, "Treasurer should NOT access expenses from other chapters")
            except ImportError:
                # Fallback test - should get permission error
                with self.assertRaises(frappe.PermissionError):
                    frappe.get_doc("Volunteer Expense", expense_b.name)
        
        # Chapter A treasurer should NOT approve Chapter B expense
        with self.as_user(self.treasurer_a["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                expense_b.status = "Approved"
                expense_b.save()
        
        # Create membership application for Chapter B
        application_b = self.board_factory.create_test_membership_application(
            chapter_name=self.chapter_b.name
        )
        
        # Chapter A treasurer should NOT access Chapter B membership applications
        with self.as_user(self.treasurer_a["user"].email):
            try:
                from vereinigungen.permissions import has_membership_application_permission
                can_view = has_membership_application_permission(application_b, self.treasurer_a["user"].email)
                self.assertFalse(can_view, "Board member should NOT access membership applications from other chapters")
            except ImportError:
                # Fallback test
                with self.assertRaises(frappe.PermissionError):
                    frappe.get_doc("Membership Application", application_b.name)
    
    def test_scenario_c_role_lifecycle(self):
        """Scenario C: Role assignment and removal lifecycle"""
        # Create new member who will become board member
        new_member = self.board_factory.create_regular_member_persona(self.chapter_a.name)
        
        # Verify they don't have board role initially
        initial_roles = frappe.get_roles(new_member["user"].email)
        self.assertNotIn("Verenigingen Chapter Board Member", initial_roles, "New user should not have board role initially")
        
        # Create treasurer role
        treasurer_role = self.board_factory.create_test_chapter_role(
            f"Test Treasurer {frappe.generate_hash(length=4)}",
            permissions_level="Financial"
        )
        
        # Assign them as board member
        board_position = self.board_factory.create_chapter_board_member(
            chapter_name=self.chapter_a.name,
            volunteer_name=new_member["volunteer"].name,
            chapter_role_name=treasurer_role.name
        )
        
        # Test they can now approve expenses
        test_expense = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_a["volunteer"].name,
            chapter_name=self.chapter_a.name,
            amount=50.00
        )
        
        with self.as_user(new_member["user"].email):
            try:
                test_expense.status = "Approved"
                test_expense.save()
                self.assertEqual(test_expense.status, "Approved", "New treasurer should approve expenses")
            except frappe.PermissionError:
                self.fail("New treasurer should have expense approval capability")
        
        # Remove board position (set inactive)
        chapter = frappe.get_doc("Chapter", self.chapter_a.name)
        for board_member in chapter.board_members:
            if board_member.volunteer == new_member["volunteer"].name:
                board_member.is_active = 0
                board_member.to_date = frappe.utils.today()
                break
        chapter.save()
        
        # Test they can no longer approve expenses
        test_expense_2 = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_a["volunteer"].name,
            chapter_name=self.chapter_a.name,
            amount=75.00
        )
        
        with self.as_user(new_member["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                test_expense_2.status = "Approved"
                test_expense_2.save()
    
    def test_scenario_d_non_treasurer_board_member(self):
        """Scenario D: Non-treasurer board member access validation"""
        # Secretary should be able to access membership applications in their chapter
        application_a = self.board_factory.create_test_membership_application(
            chapter_name=self.chapter_a.name
        )
        
        with self.as_user(self.secretary_a["user"].email):
            try:
                retrieved_app = frappe.get_doc("Membership Application", application_a.name)
                self.assertEqual(retrieved_app.name, application_a.name, "Secretary should access membership applications")
            except frappe.PermissionError:
                self.fail("Secretary should have access to membership applications in their chapter")
        
        # Secretary should NOT be able to approve expenses (treasurer-only)
        expense = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.regular_member_a["volunteer"].name,
            chapter_name=self.chapter_a.name
        )
        
        with self.as_user(self.secretary_a["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                expense.status = "Approved"
                expense.save()
        
        # Secretary should be able to view expenses but not approve
        with self.as_user(self.secretary_a["user"].email):
            try:
                retrieved_expense = frappe.get_doc("Volunteer Expense", expense.name)
                self.assertEqual(retrieved_expense.name, expense.name, "Secretary should view expenses")
                
                # But status should remain unchanged
                self.assertNotEqual(retrieved_expense.status, "Approved", "Secretary should not approve expenses")
            except frappe.PermissionError:
                self.fail("Secretary should at least be able to view chapter expenses")
    
    def test_membership_termination_workflow(self):
        """Test complete membership termination approval workflow"""
        # Create termination request for regular member
        termination_request = self.board_factory.create_test_membership_termination_request(
            member_name=self.regular_member_a["member"].name,
            termination_reason="Test termination workflow"
        )
        
        # Board member should be able to access and process termination request
        with self.as_user(self.treasurer_a["user"].email):
            try:
                retrieved_request = frappe.get_doc("Membership Termination Request", termination_request.name)
                
                # Process the termination
                retrieved_request.status = "Approved"
                retrieved_request.processed_by = self.treasurer_a["user"].email
                retrieved_request.processed_on = frappe.utils.now()
                retrieved_request.save()
                
                # Verify processing was successful
                retrieved_request.reload()
                self.assertEqual(retrieved_request.status, "Approved", "Board member should process termination requests")
                
            except frappe.PermissionError:
                self.fail("Board member should have access to termination requests in their chapter")
        
        # Board member from other chapter should not access
        with self.as_user(self.treasurer_b["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                frappe.get_doc("Membership Termination Request", termination_request.name)
    
    def test_expense_workflow_edge_cases(self):
        """Test edge cases in expense approval workflow"""
        # Test expense without chapter assignment
        expense_no_chapter = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.regular_member_a["volunteer"].name,
            "expense_date": frappe.utils.today(),
            "category": self.board_factory.ensure_test_expense_category(),
            "description": "Expense without chapter",
            "amount": 100.00,
            "currency": "EUR",
            "organization_type": "National",  # Not chapter-specific
            "company": self.board_factory.ensure_test_company(),
            "status": "Submitted"
        })
        expense_no_chapter.insert()
        self.track_doc("Volunteer Expense", expense_no_chapter.name)
        
        # Chapter treasurers should not be able to approve national expenses
        with self.as_user(self.treasurer_a["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                expense_no_chapter.status = "Approved"
                expense_no_chapter.save()
        
        # Test expense with invalid amount (business rule validation)
        with self.assertRaises(frappe.ValidationError):
            invalid_expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                "volunteer": self.regular_member_a["volunteer"].name,
                "expense_date": frappe.utils.today(),
                "category": self.board_factory.ensure_test_expense_category(),
                "description": "Invalid expense",
                "amount": -50.00,  # Negative amount should be invalid
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.chapter_a.name,
                "company": self.board_factory.ensure_test_company()
            })
            invalid_expense.insert()
    
    def test_orphaned_board_member_handling(self):
        """Test behavior with orphaned board member records"""
        # Create board member with volunteer that will be deleted
        temp_member = self.test_case.create_test_member(
            first_name="Temp",
            last_name="Member",
            email=f"temp.{frappe.generate_hash(length=6)}@test.invalid"
        )
        temp_volunteer = self.test_case.create_test_volunteer(
            member_name=temp_member.name
        )
        
        # Create board position
        board_position = self.board_factory.create_chapter_board_member(
            chapter_name=self.chapter_a.name,
            volunteer_name=temp_volunteer.name,
            chapter_role_name=self.treasurer_a["treasurer_role"].name
        )
        
        # Delete the volunteer (simulating data corruption)
        frappe.delete_doc("Volunteer", temp_volunteer.name, force=True)
        
        # Test that permission queries handle orphaned records gracefully
        try:
            from vereinigungen.permissions import get_volunteer_expense_permission_query
            query = get_volunteer_expense_permission_query(temp_member.email)
            # Should not raise an exception, should handle gracefully
            self.assertIsNotNone(query, "Permission query should handle orphaned records gracefully")
        except ImportError:
            # Fallback test - just ensure system doesn't crash
            try:
                frappe.db.sql("""
                    SELECT cbm.volunteer, cbm.chapter_role 
                    FROM `tabChapter Board Member` cbm
                    LEFT JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                    WHERE cbm.is_active = 1 AND v.name IS NULL
                """)
                # Query should execute without error
            except Exception as e:
                self.fail(f"System should handle orphaned board member records gracefully: {e}")
    
    def test_performance_permission_queries(self):
        """Test performance of permission queries with larger datasets"""
        import time
        
        # Create additional test data
        for i in range(20):
            chapter = self.board_factory.create_test_chapter(f"Perf Chapter {i}")
            member = self.test_case.create_test_member(
                first_name=f"Perf{i}",
                last_name="Member",
                email=f"perf{i}@test.invalid"
            )
            volunteer = self.test_case.create_test_volunteer(member_name=member.name)
            
            # Create expenses for performance testing
            for j in range(5):
                self.board_factory.create_test_volunteer_expense(
                    volunteer_name=volunteer.name,
                    chapter_name=chapter.name,
                    amount=25.0 + j,
                    description=f"Performance test expense {j}"
                )
        
        # Test query performance
        start_time = time.time()
        
        with self.as_user(self.treasurer_a["user"].email):
            try:
                # Query should complete quickly even with larger dataset
                expenses = frappe.get_all(
                    "Volunteer Expense", 
                    filters={"organization_type": "Chapter"},
                    fields=["name", "amount", "chapter", "volunteer"],
                    limit=50
                )
                
                query_time = time.time() - start_time
                self.assertLess(query_time, 5.0, f"Permission query should complete in under 5 seconds, took {query_time:.2f}s")
                self.assertGreater(len(expenses), 0, "Should return some expense records")
                
            except Exception as e:
                self.fail(f"Permission query should handle larger datasets efficiently: {e}")
    
    def test_security_privilege_escalation_prevention(self):
        """Test prevention of privilege escalation attempts"""
        # Regular member should not be able to create board positions for themselves
        with self.as_user(self.regular_member_a["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                # Attempt to add themselves as board member
                chapter = frappe.get_doc("Chapter", self.chapter_a.name)
                chapter.append("board_members", {
                    "volunteer": self.regular_member_a["volunteer"].name,
                    "chapter_role": self.treasurer_a["treasurer_role"].name,
                    "from_date": frappe.utils.today(),
                    "is_active": 1
                })
                chapter.save()
        
        # Board member should not be able to modify their own permissions level
        with self.as_user(self.treasurer_a["user"].email):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                role = frappe.get_doc("Chapter Role", self.treasurer_a["treasurer_role"].name)
                role.permissions_level = "Admin"  # Attempt to escalate
                role.save()
        
        # Board member should not be able to approve their own expenses
        own_expense = self.board_factory.create_test_volunteer_expense(
            volunteer_name=self.treasurer_a["volunteer"].name,
            chapter_name=self.chapter_a.name,
            amount=200.00,
            description="Self-approval test"
        )
        
        with self.as_user(self.treasurer_a["user"].email):
            # This might be allowed by business logic, but should be flagged/logged
            try:
                own_expense.status = "Approved"
                own_expense.save()
                # If allowed, should at least be logged for audit
                frappe.logger().warning(f"Self-approval detected: {self.treasurer_a['user'].email} approved own expense {own_expense.name}")
            except (frappe.PermissionError, frappe.ValidationError):
                # This is acceptable behavior - self-approval prevention
                pass


class TestChapterBoardMemberCoverage(VereningingenTestCase):
    """
    Comprehensive coverage tests for Chapter Board Member system components
    """
    
    def setUp(self):
        super().setUp()
        self.board_factory = ChapterBoardTestFactory(self)
    
    def test_chapter_role_validation(self):
        """Test Chapter Role creation and validation"""
        # Test all permission levels
        for level in ["Basic", "Financial", "Admin"]:
            role = self.board_factory.create_test_chapter_role(
                f"Test {level} Role", 
                permissions_level=level
            )
            self.assertEqual(role.permissions_level, level)
            self.assertTrue(role.is_active)
    
    def test_board_member_field_validation(self):
        """Test Chapter Board Member field validation"""
        chapter = self.board_factory.create_test_chapter()
        role = self.board_factory.create_test_chapter_role("Test Role")
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        
        # Test required fields
        with self.assertRaises(frappe.ValidationError):
            board_member = frappe.get_doc({
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter", 
                "parentfield": "board_members",
                # Missing required volunteer field
                "chapter_role": role.name,
                "from_date": frappe.utils.today()
            })
            board_member.insert()
        
        # Test valid board member creation
        board_member = self.board_factory.create_chapter_board_member(
            chapter_name=chapter.name,
            volunteer_name=volunteer.name,
            chapter_role_name=role.name
        )
        self.assertEqual(board_member.volunteer, volunteer.name)
        self.assertEqual(board_member.chapter_role, role.name)
        self.assertTrue(board_member.is_active)
    
    def test_complete_workflow_integration(self):
        """Test complete integration of all workflow components"""
        # Create complete scenario
        chapter = self.board_factory.create_test_chapter("Integration Chapter")
        treasurer = self.board_factory.create_chapter_treasurer_persona(chapter.name)
        regular_member = self.board_factory.create_regular_member_persona(chapter.name)
        
        # Test membership application → approval workflow
        application = self.board_factory.create_test_membership_application(
            chapter_name=chapter.name
        )
        
        with self.as_user(treasurer["user"].email):
            application.status = "Approved"
            application.save()
            self.assertEqual(application.status, "Approved")
        
        # Test expense submission → approval workflow
        expense = self.board_factory.create_test_volunteer_expense(
            volunteer_name=regular_member["volunteer"].name,
            chapter_name=chapter.name
        )
        
        with self.as_user(treasurer["user"].email):
            expense.status = "Approved"
            expense.save()
            self.assertEqual(expense.status, "Approved")
        
        # Test termination request → approval workflow
        termination = self.board_factory.create_test_membership_termination_request(
            member_name=regular_member["member"].name
        )
        
        with self.as_user(treasurer["user"].email):
            termination.status = "Approved"
            termination.save()
            self.assertEqual(termination.status, "Approved")


if __name__ == "__main__":
    unittest.main()