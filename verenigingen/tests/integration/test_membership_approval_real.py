# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Real Integration Test for Membership Approval Workflow
=====================================================

This test validates the complete membership approval workflow without mocking
critical business logic. It serves as a proof-of-concept for eliminating mock
abuse and establishing real integration testing patterns.

Key Testing Principles:
- Uses real database operations with transaction isolation
- Tests actual API endpoints without permission bypasses
- Validates business logic with real data constraints
- Mocks only external services (email, external APIs)
- Uses Enhanced Test Factory for realistic test data generation

This test replaces the mock-heavy patterns that failed to catch the membership
approval workflow bugs that were discovered in production.
"""

import frappe
from frappe.utils import today, add_days, now_datetime
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipApprovalRealIntegration(EnhancedTestCase):
    """
    Real integration test for membership approval workflow
    
    Tests the complete approval process from pending application to active member
    including account creation, role assignment, and invoice generation.
    """

    def setUp(self):
        """Set up test environment with real database operations"""
        super().setUp()
        
        # Create test environment using Enhanced Test Factory
        self.chapter = self.factory.ensure_test_chapter("Test Chapter", {
            "chapter_name": "Test Chapter",
            "short_name": "TST",
            "country": "Netherlands"
        })
        self.membership_type = self.factory.ensure_membership_type("Standard Member", {
            "amount": 25.00,
            "billing_frequency": "Monthly"
        })
        
        # Create test admin user for approval workflow
        self.admin_user = self.create_test_user_with_roles(
            email="approval.admin@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )

    def test_complete_membership_approval_workflow(self):
        """Test end-to-end membership approval workflow with real database operations"""
        
        # Stage 1: Create pending membership application
        member = self.create_test_member(
            first_name="Integration",
            last_name="TestApproval",
            email="integration.approval@example.com",
            status="Pending",
            application_status="Pending",
            selected_membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            birth_date=add_days(today(), -365 * 25)  # 25 years old
        )
        
        # Validate initial state
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertIsNone(member.customer)  # No customer record yet
        
        # Stage 2: Test approval workflow with admin user context  
        with self.as_user(self.admin_user.email):
            # Mock only external services - keep all business logic real
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail') as mock_sendmail:
                # Mock justified: External service configuration, not business logic
                with patch('frappe.db.get_single_value') as mock_settings:
                    # Mock settings retrieval but keep business logic real
                    mock_settings.side_effect = lambda doctype, field: {
                        ('Verenigingen Settings', 'member_contact_email'): 'admin@example.com',
                        ('Verenigingen Settings', 'support_email'): 'support@example.com',
                        ('Global Defaults', 'default_company'): 'Test Company'
                    }.get((doctype, field))
                    
                    # Monitor query performance during approval workflow
                    with self.assertQueryCount(100):  # Reasonable limit for complex workflow
                        # Call actual approval API - NO MOCKING OF BUSINESS LOGIC
                        result = approve_membership_application(
                            member_name=member.name,
                            membership_type=self.membership_type.name,
                            chapter=self.chapter.name,
                            notes="Integration test approval",
                            create_invoice=True
                        )
                    
                    # Validate API response
                    self.assertTrue(result.get('success'))
                    self.assertIn('message', result)
        
        # Stage 3: Validate real database changes (no mocks)
        member.reload()  # Get fresh data from database
        
        # Verify member status changes
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.application_approved_on)
        self.assertEqual(member.application_approved_by, self.admin_user.email)
        
        # Verify customer creation
        self.assertIsNotNone(member.customer)
        customer = frappe.get_doc("Customer", member.customer)
        self.assertEqual(customer.customer_name, f"{member.first_name} {member.last_name}")
        self.assertEqual(customer.member, member.name)
        
        # Stage 4: Validate account creation request was generated
        account_requests = frappe.get_all(
            "Account Creation Request",
            filters={"source_record": member.name},
            fields=["name", "status", "request_type", "email"]
        )
        
        self.assertEqual(len(account_requests), 1)
        account_request = account_requests[0]
        self.assertEqual(account_request["email"], member.email)
        self.assertEqual(account_request["request_type"], "Member")
        self.assertIn(account_request["status"], ["Queued", "Processing", "Completed"])
        
        # Stage 5: Validate membership record creation
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "membership_type", "status", "start_date"]
        )
        
        self.assertEqual(len(memberships), 1)
        membership = memberships[0]
        self.assertEqual(membership["membership_type"], self.membership_type.name)
        self.assertEqual(membership["status"], "Active")
        
        # Stage 6: Validate invoice generation (if requested)
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "custom_is_membership_dues": 1},
            fields=["name", "grand_total", "status", "custom_member"]
        )
        
        # Should have created membership dues invoice
        self.assertGreater(len(invoices), 0)
        invoice = invoices[0]
        self.assertEqual(invoice["custom_member"], member.name)
        self.assertEqual(invoice["grand_total"], self.membership_type.amount)
        
        # Stage 7: Validate chapter membership assignment
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter_members = [m for m in chapter.members if m.member == member.name]
        self.assertEqual(len(chapter_members), 1)
        
        chapter_member = chapter_members[0]
        self.assertEqual(chapter_member.status, "Active")
        self.assertEqual(chapter_member.member_name, member.full_name)

    def test_approval_workflow_validation_errors(self):
        """Test that approval workflow properly validates business rules"""
        
        # Create member without required fields
        member = self.create_test_member(
            first_name="Invalid",
            last_name="TestMember",
            email="invalid.test@example.com",
            status="Pending",
            application_status="Pending",
            # Deliberately missing selected_membership_type
            chapter=self.chapter.name
        )
        
        # Test approval with missing membership type
        with self.as_user(self.admin_user.email):
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail'):
                # Mock justified: External service configuration, not business logic
                with patch('frappe.db.get_single_value') as mock_settings:
                    mock_settings.return_value = 'admin@example.com'
                    
                    # Should raise validation error for missing membership type
                    with self.assertRaises(frappe.ValidationError):
                        approve_membership_application(
                            member_name=member.name,
                            membership_type="",  # Invalid empty membership type
                            create_invoice=True
                        )
        
        # Member status should remain unchanged
        member.reload()
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")

    def test_approval_workflow_permission_validation(self):
        """Test that approval workflow respects permission boundaries"""
        
        member = self.create_test_member(
            first_name="Permission",
            last_name="TestMember",
            email="permission.test@example.com",
            status="Pending",
            application_status="Pending",
            selected_membership_type=self.membership_type.name,
            chapter=self.chapter.name
        )
        
        # Create user without approval permissions
        limited_user = self.create_test_user_with_roles(
            email="limited.user@example.com",
            roles=["Verenigingen Member"]  # No admin permissions
        )
        
        # Test approval with limited permissions should fail
        with self.as_user(limited_user.email):
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail'):
                with patch('frappe.db.get_single_value') as mock_settings:
                    mock_settings.return_value = 'admin@example.com'
                    
                    # Should raise permission error
                    with self.assertRaises(frappe.PermissionError):
                        approve_membership_application(
                            member_name=member.name,
                            membership_type=self.membership_type.name,
                            create_invoice=True
                        )
        
        # Member status should remain unchanged
        member.reload()
        self.assertEqual(member.application_status, "Pending")

    def test_approval_workflow_account_creation_integration(self):
        """Test integration between approval workflow and account creation system"""
        
        # Create member with volunteer interest
        member = self.create_test_member(
            first_name="Account",
            last_name="TestMember", 
            email="account.test@example.com",
            status="Pending",
            application_status="Pending",
            selected_membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            interested_in_volunteering=1
        )
        
        # Create volunteer record to test employee creation
        volunteer = self.create_test_volunteer(
            member=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email,
            status="New"
        )
        
        with self.as_user(self.admin_user.email):
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail') as mock_sendmail:
                # Mock justified: External service configuration, not business logic
                with patch('frappe.db.get_single_value') as mock_settings:
                    mock_settings.side_effect = lambda doctype, field: {
                        ('Verenigingen Settings', 'member_contact_email'): 'admin@example.com',
                        ('Global Defaults', 'default_company'): 'Test Company'
                    }.get((doctype, field))
                    
                    # Approve member with volunteer record
                    result = approve_membership_application(
                        member_name=member.name,
                        membership_type=self.membership_type.name,
                        create_invoice=False
                    )
                    
                    self.assertTrue(result.get('success'))
        
        # Validate account creation request includes employee creation
        account_requests = frappe.get_all(
            "Account Creation Request",
            filters={"source_record": member.name},
            fields=["name", "request_type"]
        )
        
        self.assertEqual(len(account_requests), 1)
        account_request = frappe.get_doc("Account Creation Request", account_requests[0]["name"])
        
        # Should recognize this member has a volunteer record
        # and require employee creation for expense functionality
        from verenigingen.utils.account_creation_manager import AccountCreationManager
        manager = AccountCreationManager(account_request.name)
        manager.load_request()
        
        # Test the requires_employee_creation logic
        requires_employee = manager.requires_employee_creation()
        self.assertTrue(requires_employee, 
            "Account creation should recognize volunteer record and require employee creation")

    def test_approval_workflow_invoice_generation(self):
        """Test invoice generation during approval workflow"""
        
        member = self.create_test_member(
            first_name="Invoice",
            last_name="TestMember",
            email="invoice.test@example.com", 
            status="Pending",
            application_status="Pending",
            selected_membership_type=self.membership_type.name,
            chapter=self.chapter.name
        )
        
        with self.as_user(self.admin_user.email):
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail'):
                # Mock justified: External service configuration, not business logic
                with patch('frappe.db.get_single_value') as mock_settings:
                    mock_settings.side_effect = lambda doctype, field: {
                        ('Verenigingen Settings', 'member_contact_email'): 'admin@example.com',
                        ('Global Defaults', 'default_company'): 'Test Company'
                    }.get((doctype, field))
                    
                    # Test with invoice generation enabled
                    result = approve_membership_application(
                        member_name=member.name,
                        membership_type=self.membership_type.name,
                        create_invoice=True
                    )
                    
                    self.assertTrue(result.get('success'))
        
        # Validate invoice was created with correct details
        member.reload()
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "docstatus": 1},
            fields=["name", "grand_total", "custom_member", "custom_membership_type"]
        )
        
        self.assertGreater(len(invoices), 0)
        invoice = invoices[0]
        self.assertEqual(float(invoice["grand_total"]), float(self.membership_type.amount))
        self.assertEqual(invoice["custom_member"], member.name)
        self.assertEqual(invoice["custom_membership_type"], self.membership_type.name)
        
        # Test without invoice generation
        member2 = self.create_test_member(
            first_name="NoInvoice", 
            last_name="TestMember",
            email="noinvoice.test@example.com",
            status="Pending",
            application_status="Pending", 
            selected_membership_type=self.membership_type.name,
            chapter=self.chapter.name
        )
        
        with self.as_user(self.admin_user.email):
            # Mock justified: External email service, not business logic
            with patch('frappe.sendmail'):
                # Mock justified: External service configuration, not business logic
                with patch('frappe.db.get_single_value') as mock_settings:
                    mock_settings.return_value = 'admin@example.com'
                    
                    # Test with invoice generation disabled
                    result = approve_membership_application(
                        member_name=member2.name,
                        membership_type=self.membership_type.name,
                        create_invoice=False
                    )
                    
                    self.assertTrue(result.get('success'))
        
        # Should not create invoice
        member2.reload()
        if member2.customer:  # Customer might still be created
            no_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member2.customer, "docstatus": 1}
            )
            # Either no customer or no invoices for this test
            self.assertEqual(len(no_invoices), 0)


if __name__ == '__main__':
    import unittest
    unittest.main()