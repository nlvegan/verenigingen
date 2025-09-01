#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Unit Tests for member_utils.py
===========================================

Tests for all utility functions in verenigingen.utils.member_utils module.
These tests ensure the standardized lookup patterns work correctly and handle
all edge cases properly.

Key Features Tested:
- Member lookup by user email/ID
- Volunteer lookup by user email/ID  
- Active membership retrieval with field validation
- Chapter membership queries
- Customer-member relationships
- SEPA mandate lookups
- Error handling and validation
- Field existence validation against DocType schemas
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, MagicMock

from verenigingen.utils.member_utils import (
    # Member lookup functions
    get_member_name_for_user,
    get_current_user_member_name,
    get_current_user_member_doc,
    get_current_user_member_name_required,
    get_current_user_member_info,
    
    # Member-customer relationships
    get_member_customer,
    get_member_for_customer,
    
    # Volunteer functions
    get_volunteer_for_member,
    get_volunteer_for_current_user,
    get_volunteer_name_for_user,
    is_member_volunteer,
    is_current_user_volunteer,
    
    # Membership functions  
    get_active_membership_for_member,
    get_active_membership_for_current_user,
    
    # Chapter functions
    get_member_chapters,
    get_current_user_chapters,
    
    # SEPA functions
    get_member_sepa_mandate,
    has_active_sepa_mandate,
    
    # Validation functions
    validate_member_ownership,
    require_member_record,
    has_mollie_subscription,
)

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberUtils(EnhancedTestCase):
    """
    Comprehensive test suite for member_utils.py utilities
    
    Uses EnhancedTestCase for business logic validation and field safety
    """

    @classmethod
    def setUpClass(cls):
        """Set up test data that persists across all test methods"""
        super().setUpClass()
        
        # Create test users for various scenarios
        cls.test_users = {
            'member_user': 'test.member@verenigingen.test',
            'volunteer_user': 'test.volunteer@verenigingen.test',
            'admin_user': 'test.admin@verenigingen.test',
            'no_member_user': 'test.nomember@verenigingen.test'
        }
        
        # Will be populated by individual tests
        cls.test_member_id = None
        cls.test_volunteer_id = None
        cls.test_customer_id = None

    def setUp(self):
        """Set up for each test method"""
        super().setUp()
        
        # Create a test member using enhanced factory
        self.member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email=self.test_users['member_user'],
            birth_date="1990-01-01"
        )
        TestMemberUtils.test_member_id = self.member.name
        
        # Create a test user for the member
        if not frappe.db.exists("User", self.test_users['member_user']):
            self.user = self.create_test_user(
                email=self.test_users['member_user'],
                first_name="Test",
                last_name="Member",
                roles=["Verenigingen Member"]
            )
    
    def _ensure_membership_type(self, membership_type_name):
        """Create membership type if it doesn't exist"""
        if not frappe.db.exists("Membership Type", membership_type_name):
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type": membership_type_name,
                "amount": 25.0
            })
            membership_type.insert()
            return membership_type
        return frappe.get_doc("Membership Type", membership_type_name)
    
    def _create_test_sepa_mandate(self, member_name, status="Active"):
        """Create a test SEPA mandate"""
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": member_name,
            "mandate_id": frappe.generate_hash(length=8),
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "account_holder_name": "Test Account Holder",
            "status": status,
            "sign_date": frappe.utils.today()
        })
        mandate.insert()
        return mandate
    
    def _add_member_to_chapter(self, member_name, chapter_name, status="Active"):
        """Add member to chapter using child table"""
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append("members", {
            "member": member_name,
            "status": status,
            "enabled": 1
        })
        chapter_doc.save()
        return chapter_doc

    def test_get_member_name_for_user_success(self):
        """Test successful member lookup by user email"""
        member_name = get_member_name_for_user(self.test_users['member_user'])
        
        self.assertIsNotNone(member_name)
        self.assertEqual(member_name, self.member.name)

    def test_get_member_name_for_user_fallback_user_field(self):
        """Test fallback to user field for older records"""
        # Create member with user field instead of email
        member = self.create_test_member(
            first_name="Legacy",
            last_name="User", 
            birth_date="1985-01-01"
        )
        # Manually set user field for legacy compatibility test
        frappe.db.set_value("Member", member.name, "user", "legacy.user@test.com")
        frappe.db.set_value("Member", member.name, "email", "")
        
        member_name = get_member_name_for_user("legacy.user@test.com")
        self.assertEqual(member_name, member.name)

    def test_get_member_name_for_user_not_found(self):
        """Test member lookup with non-existent user"""
        member_name = get_member_name_for_user("nonexistent@test.com")
        self.assertIsNone(member_name)

    def test_get_member_name_for_user_empty_input(self):
        """Test member lookup with empty input"""
        member_name = get_member_name_for_user("")
        self.assertIsNone(member_name)
        
        member_name = get_member_name_for_user(None)
        self.assertIsNone(member_name)

    @patch('frappe.session')
    def test_get_current_user_member_name(self, mock_session):
        """Test current user member lookup"""
        mock_session.user = self.test_users['member_user']
        
        member_name = get_current_user_member_name()
        self.assertEqual(member_name, self.member.name)

    @patch('frappe.session')
    def test_get_current_user_member_name_not_found(self, mock_session):
        """Test current user member lookup with no member record"""
        mock_session.user = self.test_users['no_member_user']
        
        member_name = get_current_user_member_name()
        self.assertIsNone(member_name)

    @patch('frappe.session')
    def test_get_current_user_member_doc_success(self, mock_session):
        """Test retrieving current user's member document"""
        mock_session.user = self.test_users['member_user']
        
        member_doc = get_current_user_member_doc()
        self.assertEqual(member_doc.name, self.member.name)
        self.assertEqual(member_doc.email, self.test_users['member_user'])

    @patch('frappe.session')  
    def test_get_current_user_member_doc_not_found(self, mock_session):
        """Test retrieving member document when no member exists"""
        mock_session.user = self.test_users['no_member_user']
        
        with self.assertRaises(frappe.DoesNotExistError):
            get_current_user_member_doc()

    @patch('frappe.session')
    def test_get_current_user_member_name_required_success(self, mock_session):
        """Test required member name lookup - success case"""
        mock_session.user = self.test_users['member_user']
        
        member_name = get_current_user_member_name_required()
        self.assertEqual(member_name, self.member.name)

    @patch('frappe.session')
    def test_get_current_user_member_name_required_not_found(self, mock_session):
        """Test required member name lookup - failure case"""
        mock_session.user = self.test_users['no_member_user'] 
        
        with self.assertRaises(frappe.DoesNotExistError):
            get_current_user_member_name_required()

    @patch('frappe.session')
    def test_get_current_user_member_info_success(self, mock_session):
        """Test retrieving member info with field validation"""
        mock_session.user = self.test_users['member_user']
        
        member_info = get_current_user_member_info()
        
        self.assertIsNotNone(member_info)
        # Check for the actual fields returned by the function
        self.assertIn('full_name', member_info)
        self.assertIn('email', member_info)
        self.assertEqual(member_info['email'], self.test_users['member_user'])

    @patch('frappe.session')
    def test_get_current_user_member_info_not_found(self, mock_session):
        """Test member info retrieval when no member exists"""
        mock_session.user = self.test_users['no_member_user']
        
        member_info = get_current_user_member_info()
        self.assertIsNone(member_info)

    def test_get_volunteer_for_member_success(self):
        """Test volunteer lookup for member"""
        # Create volunteer linked to member
        volunteer = self.create_test_volunteer(self.member.name)
        TestMemberUtils.test_volunteer_id = volunteer.name
        
        volunteer_name = get_volunteer_for_member(self.member.name)
        self.assertEqual(volunteer_name, volunteer.name)

    def test_get_volunteer_for_member_not_found(self):
        """Test volunteer lookup when no volunteer exists"""
        volunteer_name = get_volunteer_for_member(self.member.name)
        self.assertIsNone(volunteer_name)

    def test_get_volunteer_for_member_empty_input(self):
        """Test volunteer lookup with empty input"""
        volunteer_name = get_volunteer_for_member("")
        self.assertIsNone(volunteer_name)

    def test_get_volunteer_name_for_user_by_email(self):
        """Test volunteer lookup by user email"""
        # Create volunteer with email
        volunteer = self.create_test_volunteer(self.member.name)
        # Set email on volunteer
        frappe.db.set_value("Volunteer", volunteer.name, "email", self.test_users['volunteer_user'])
        
        volunteer_name = get_volunteer_name_for_user(self.test_users['volunteer_user'])
        self.assertEqual(volunteer_name, volunteer.name)

    def test_get_volunteer_name_for_user_by_user_field(self):
        """Test volunteer lookup by user field (fallback)"""
        volunteer = self.create_test_volunteer(self.member.name)
        # Set user field for fallback test
        frappe.db.set_value("Volunteer", volunteer.name, "user", "volunteer.legacy@test.com")
        frappe.db.set_value("Volunteer", volunteer.name, "email", "")
        
        volunteer_name = get_volunteer_name_for_user("volunteer.legacy@test.com")
        self.assertEqual(volunteer_name, volunteer.name)

    def test_get_volunteer_name_for_user_not_found(self):
        """Test volunteer lookup with non-existent user"""
        volunteer_name = get_volunteer_name_for_user("nonexistent@test.com")
        self.assertIsNone(volunteer_name)

    def test_is_member_volunteer_true(self):
        """Test checking if member is volunteer - true case"""
        volunteer = self.create_test_volunteer(self.member.name)
        
        result = is_member_volunteer(self.member.name)
        self.assertTrue(result)

    def test_is_member_volunteer_false(self):
        """Test checking if member is volunteer - false case"""
        result = is_member_volunteer(self.member.name)
        self.assertFalse(result)

    def test_get_active_membership_for_member_success(self):
        """Test active membership lookup with field validation"""
        # Create membership type first
        self._ensure_membership_type("Regular")
        
        # Create active membership using enhanced factory pattern
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name="Regular"
        )
        # Ensure the membership is active and submitted
        membership.status = "Active"
        membership.submit()  # Use submit() instead of setting docstatus manually
        
        result = get_active_membership_for_member(self.member.name)
        
        self.assertIsNotNone(result, f"Expected membership result but got None for member {self.member.name}")
        self.assertEqual(result['name'], membership.name)
        self.assertEqual(result['status'], "Active")

    def test_get_active_membership_for_member_not_found(self):
        """Test membership lookup when no active membership exists"""
        result = get_active_membership_for_member(self.member.name)
        self.assertIsNone(result)

    def test_get_active_membership_for_member_field_validation(self):
        """Test membership lookup with field validation"""
        # Create membership type first
        self._ensure_membership_type("Regular")
        
        # Create membership using enhanced factory pattern
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name="Regular"
        )
        # Ensure the membership is active and submitted
        membership.status = "Active"
        membership.submit()  # Use submit() instead of setting docstatus manually
        
        # Test successful lookup
        result = get_active_membership_for_member(self.member.name)
        
        # Should return membership dict
        self.assertIsNotNone(result, f"Expected membership result but got None for member {self.member.name}")
        self.assertEqual(result['name'], membership.name)
        self.assertEqual(result['status'], "Active")

    def test_get_member_customer_success(self):
        """Test customer lookup for member"""
        # Member should already have a customer created by enhanced test factory
        customer_name = get_member_customer(self.member.name)
        self.assertIsNotNone(customer_name)
        self.assertIsInstance(customer_name, str)

    def test_get_member_customer_not_found(self):
        """Test customer lookup when no customer linked"""
        # Create member without customer - modify existing member
        original_customer = self.member.customer
        self.member.customer = None
        self.member.save()
        
        try:
            # Test no customer found
            customer_name = get_member_customer(self.member.name)
            self.assertIsNone(customer_name)
        finally:
            # Restore original customer link
            self.member.customer = original_customer
            self.member.save()

    def test_get_member_for_customer_success(self):
        """Test reverse lookup: member from customer"""
        # Use existing customer from member
        customer_name = self.member.customer
        self.assertIsNotNone(customer_name, "Member should have a customer")
        
        # Test successful reverse lookup
        member_name = get_member_for_customer(customer_name)
        self.assertEqual(member_name, self.member.name)

    def test_get_member_for_customer_not_found(self):
        """Test reverse lookup when no member linked to customer"""
        # Test with non-existent customer
        member_name = get_member_for_customer("NON-EXISTENT-CUSTOMER")
        self.assertIsNone(member_name)

    def test_get_member_sepa_mandate_success(self):
        """Test SEPA mandate lookup for member"""
        # Create SEPA mandate using test factory
        mandate = self._create_test_sepa_mandate(self.member.name, "Active")
        
        mandate_info = get_member_sepa_mandate(self.member.name)
        
        self.assertIsNotNone(mandate_info)
        self.assertEqual(mandate_info['name'], mandate.name)
        self.assertEqual(mandate_info['status'], "Active")
        self.assertIn('iban', mandate_info)
        self.assertIn('sign_date', mandate_info)  # Test correct field name

    def test_get_member_sepa_mandate_not_found(self):
        """Test SEPA mandate lookup when no mandate exists"""
        mandate_info = get_member_sepa_mandate(self.member.name)
        self.assertIsNone(mandate_info)

    def test_get_member_sepa_mandate_inactive_filtered(self):
        """Test SEPA mandate lookup filters inactive mandates"""
        # Create inactive mandate
        mandate = self._create_test_sepa_mandate(self.member.name, "Cancelled")
        
        # Test that inactive mandate is not returned
        mandate_info = get_member_sepa_mandate(self.member.name)
        self.assertIsNone(mandate_info)

    def test_has_active_sepa_mandate_true(self):
        """Test SEPA mandate check - true case"""
        mandate = self._create_test_sepa_mandate(self.member.name, "Active")
        
        result = has_active_sepa_mandate(self.member.name)
        self.assertTrue(result)

    def test_has_active_sepa_mandate_false(self):
        """Test SEPA mandate check - false case"""
        result = has_active_sepa_mandate(self.member.name)
        self.assertFalse(result)

    def test_get_member_chapters_success(self):
        """Test chapter membership lookup"""
        # Create chapter and add member
        chapter = self.create_test_chapter()
        self._add_member_to_chapter(self.member.name, chapter.name, "Active")
        
        chapters = get_member_chapters(self.member.name)
        
        self.assertIsInstance(chapters, list)
        self.assertGreater(len(chapters), 0)
        self.assertEqual(chapters[0], chapter.name)

    def test_get_member_chapters_empty(self):
        """Test chapter membership lookup when no chapters"""
        chapters = get_member_chapters(self.member.name)
        
        self.assertIsInstance(chapters, list)
        self.assertEqual(len(chapters), 0)

    def test_get_member_chapters_active_filter(self):
        """Test chapter membership with active filter"""
        # Create chapters with different statuses
        active_chapter = self.create_test_chapter()
        inactive_chapter = self.create_test_chapter()
        
        # Create chapter memberships
        self._add_member_to_chapter(self.member.name, active_chapter.name, "Active")
        self._add_member_to_chapter(self.member.name, inactive_chapter.name, "Inactive")
        
        # Test active-only filter
        active_chapters = get_member_chapters(self.member.name, active_only=True)
        self.assertEqual(len(active_chapters), 1)
        self.assertEqual(active_chapters[0], active_chapter.name)

    def test_validate_member_ownership_success(self):
        """Test member ownership validation - success case"""
        with patch('frappe.session') as mock_session:
            mock_session.user = self.test_users['member_user']
            
            # Should not raise exception for own member record
            try:
                validate_member_ownership(self.member.name)
            except Exception:
                self.fail("validate_member_ownership raised exception for valid ownership")

    def test_validate_member_ownership_failure(self):
        """Test member ownership validation - failure case"""
        # Create another member
        other_member = self.create_test_member(
            first_name="Other",
            last_name="Member",
            email="other@test.com",
            birth_date="1985-01-01"
        )
        
        with patch('frappe.session') as mock_session:
            mock_session.user = self.test_users['member_user']
            
            # Should raise exception for different member record
            with self.assertRaises(frappe.PermissionError):
                validate_member_ownership(other_member.name)

    def test_validate_member_ownership_invalid_member(self):
        """Test member ownership validation with invalid member ID"""
        with patch('frappe.session') as mock_session:
            mock_session.user = self.test_users['member_user']
            
            with self.assertRaises(frappe.DoesNotExistError):
                validate_member_ownership("invalid-member-id")

    def test_validate_member_ownership_no_current_member(self):
        """Test member ownership validation when current user has no member record"""
        with patch('frappe.session') as mock_session:
            mock_session.user = self.test_users['no_member_user']
            
            with self.assertRaises(frappe.DoesNotExistError):
                validate_member_ownership(self.member.name)


    def test_edge_cases_and_boundary_conditions(self):
        """Test various edge cases and boundary conditions"""
        # Test with very long email addresses
        long_email = "a" * 100 + "@" + "b" * 100 + ".com"
        self.assertIsNone(get_member_name_for_user(long_email))
        
        # Test with special characters in email
        special_email = "test+special@domain-name.co.uk"
        self.assertIsNone(get_member_name_for_user(special_email))
        
        # Test with Unicode characters
        unicode_email = "test.ñoño@domäin.org"
        self.assertIsNone(get_member_name_for_user(unicode_email))

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        # Enhanced test factory handles automatic cleanup
        super().tearDownClass()


if __name__ == '__main__':
    import unittest
    unittest.main()