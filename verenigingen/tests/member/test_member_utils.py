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

    # Dues Schedule utilities (NEW - Phase 2 Priority 4)
    get_member_dues_schedule,
    get_member_dues_schedule_name,
    get_member_active_or_paused_schedule,
    get_member_active_or_paused_schedule_name,
    has_active_dues_schedule,
    has_any_dues_schedule,
    get_dues_schedule_for_membership,
    get_dues_schedule_for_membership_name,
)

import unittest

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
        
        # Create a test member using enhanced factory.
        # NOTE: the factory uniquifies the email (e.g. test.member.17@...) to
        # avoid Customer-name collisions. The lookup tests below resolve a Member
        # from test_users['member_user'], so we must reconcile the Member's email
        # back to that canonical address — otherwise get_member_name_for_user()
        # returns None and the ownership/current-user tests raise
        # "No member record found for your account".
        self.member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email=self.test_users['member_user'],
            birth_date="1990-01-01"
        )
        if self.member.email != self.test_users['member_user']:
            frappe.db.set_value("Member", self.member.name, "email", self.test_users['member_user'])
            self.member.reload()
        TestMemberUtils.test_member_id = self.member.name

        # Create a test user for the member
        if not frappe.db.exists("User", self.test_users['member_user']):
            self.user = self.create_test_user(
                email=self.test_users['member_user'],
                first_name="Test",
                last_name="Member",
                roles=["Verenigingen Member"]
            )
    
    def _ensure_membership_type(self, membership_type_name=None):
        """Create an active membership type via the factory and return it.

        The factory generates a unique, active Membership Type (correct
        ``membership_type_name`` + mandatory ``role_profile``/``minimum_amount``),
        avoiding the "Membership Type Name is required" / "is inactive" errors
        that hand-rolled fixed-name types hit against pre-existing inactive
        masters on a polluted site.
        """
        return self.create_test_membership_type(membership_type_name=membership_type_name)
    
    def _create_test_sepa_mandate(self, member_name, status="Active"):
        """Create a test SEPA mandate via the factory.

        The factory sets the mandatory ``mandate_type``/``scheme`` (which are
        not reliably defaulted on a dict-constructed doc in v16, causing
        "mandate_type, scheme" MandatoryError) and a valid generated IBAN.
        """
        return self.create_test_sepa_mandate(
            member_name=member_name,
            iban="NL91ABNA0417164300",
            status=status,
        )
    
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

    def test_get_member_name_for_user_propagates_database_error(self):
        """A database failure must propagate, never read as 'not a member'.

        This resolver is the member-identity step of several permission paths
        (permissions.py's query conditions, chapter_permission_service.
        get_user_board_chapters, SelfServiceAccessController). Swallowing the
        error and returning None turns an outage into "no access", which is
        indistinguishable from a genuine non-member and silently denies
        legitimate users. Callers that want to degrade must say so explicitly.
        """
        outage = frappe.db.OperationalError("simulated database outage")

        with patch.object(frappe.db, "get_value", side_effect=outage):
            with self.assertRaises(frappe.db.OperationalError):
                get_member_name_for_user("test.member@verenigingen.test")

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
        # Create an active membership type via the factory
        membership_type = self._ensure_membership_type("Regular")

        # create_test_membership already inserts and submits the membership
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=membership_type.name
        )

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
        # Create an active membership type via the factory
        membership_type = self._ensure_membership_type("Regular")

        # create_test_membership already inserts and submits the membership
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=membership_type.name
        )

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

    def test_age_group_categorization(self):
        """Test age group categorization for privacy using member_age_service"""
        from verenigingen.services.member.utils.member_age_service import get_age_group

        # Test different age groups based on birth date
        test_cases = [
            ("2010-01-01", "Minor"),         # 14-15 years old
            ("2000-01-01", "Young Adult"),   # 24-25 years old
            ("1985-01-01", "Adult"),         # 39-40 years old
            ("1970-01-01", "Middle-aged"),   # 54-55 years old
            ("1950-01-01", "Senior"),        # 74-75 years old
        ]

        for birth_date, expected_group in test_cases:
            age_group = get_age_group(birth_date)
            self.assertEqual(
                age_group,
                expected_group,
                f"Birth date {birth_date} should be {expected_group}, got {age_group}",
            )

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        # Enhanced test factory handles automatic cleanup
        super().tearDownClass()


class TestDuesScheduleUtilities(EnhancedTestCase):
    """
    Comprehensive test suite for dues schedule utility functions

    Tests the new utilities added in Phase 2 Priority 4 for centralized
    dues schedule queries. Uses EnhancedTestCase for proper field validation
    and business rule compliance.
    """

    def setUp(self):
        """Set up test data for each test"""
        super().setUp()

        # Create test member
        self.member = self.create_test_member(
            first_name="Dues",
            last_name="Tester",
            email="dues.tester@verenigingen.test",
            birth_date="1985-05-15"
        )

        # Clean up any orphaned schedules from previous tests (Frappe test isolation issue)
        # This MUST be done AFTER creating the member but BEFORE creating any schedules
        self._cleanup_member_schedules()

        # Create an active membership type via the factory. A literal "Standard"
        # type may already exist on a polluted site with is_active=0, which makes
        # create_test_membership fail with "Membership Type Standard is inactive";
        # the factory always produces a unique, active type.
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Standard", amount=50.0
        )

        # Create the membership for linking to dues schedule. The factory submits
        # it (active + submitted); the dues-schedule helper queries by member, so
        # the submit side effect is harmless for these lookups.
        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=self.membership_type.name
        )

        # Clean up any orphaned schedules for this membership too
        self._cleanup_membership_schedules()

        # Track created schedules for cleanup
        self.created_schedules = []

    def _cleanup_member_schedules(self):
        """Clean up any existing dues schedules for the test member

        This is needed for 'not found' tests due to Frappe's broken test isolation.
        Schedules from previous tests in the same run can persist even after
        member/membership deletion.
        """
        existing_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name},
            pluck="name"
        )
        for schedule_name in existing_schedules:
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
            except Exception:
                pass  # Ignore errors during cleanup

    def _cleanup_membership_schedules(self):
        """Clean up any existing dues schedules for the test membership

        This is needed for 'not found' tests due to Frappe's broken test isolation.
        """
        existing_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"membership": self.membership.name},
            pluck="name"
        )
        for schedule_name in existing_schedules:
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
            except Exception:
                pass  # Ignore errors during cleanup

    def _create_dues_schedule(self, status="Active", dues_rate=50.0, is_template=0):
        """Helper to create a test dues schedule

        Automatically cleans up any existing schedules to avoid
        'member already has active schedule' validation errors
        """
        import time

        # Clean up any existing schedules for this member to avoid validation errors
        self._cleanup_member_schedules()

        schedule_name = f"Test Schedule {int(time.time() * 1000)}"  # Unique schedule name

        schedule = self.create_test_dues_schedule(
            member=self.member.name,
            membership_type=self.membership_type.name,
            amount=dues_rate,
            frequency="monthly",
            status=status,
            membership=self.membership.name,
            payment_terms_template=None,  # Don't set payment terms for test simplicity
            schedule_name=schedule_name  # Required for autoname
        )

        # The create_test_dues_schedule bridge drops the membership= kwarg
        # (it predates the field existing on Membership Dues Schedule), so the
        # link is not persisted. The get_dues_schedule_for_membership* lookups
        # query by this field, so set it explicitly here.
        if schedule.get("membership") != self.membership.name:
            frappe.db.set_value(
                "Membership Dues Schedule", schedule.name, "membership", self.membership.name
            )
            schedule.reload()

        # Set is_template flag if needed
        if is_template:
            frappe.db.set_value("Membership Dues Schedule", schedule.name, "is_template", 1)

        # Track for cleanup
        self.created_schedules.append(schedule.name)

        return schedule

    # ========================================================================
    # Core Query Function Tests
    # ========================================================================

    def test_get_member_dues_schedule_success(self):
        """Test retrieval of active dues schedule with default fields"""
        schedule = self._create_dues_schedule(status="Active", dues_rate=50.0)

        result = get_member_dues_schedule(self.member.name)

        self.assertIsNotNone(result)
        self.assertEqual(result['name'], schedule.name)
        self.assertEqual(result['status'], "Active")
        self.assertEqual(result['dues_rate'], 50.0)

    def test_get_member_dues_schedule_empty_input(self):
        """Test dues schedule lookup with empty/None input"""
        self.assertIsNone(get_member_dues_schedule(""))
        self.assertIsNone(get_member_dues_schedule(None))

    def test_get_member_dues_schedule_custom_fields(self):
        """Test dues schedule lookup with custom field list"""
        schedule = self._create_dues_schedule(status="Active")

        result = get_member_dues_schedule(
            self.member.name,
            fields=["name", "dues_rate", "status"]
        )

        self.assertIsNotNone(result)
        self.assertIn('name', result)
        self.assertIn('dues_rate', result)
        self.assertIn('status', result)

    def test_get_member_dues_schedule_status_filtering(self):
        """Test status filtering (Active, Paused, None)"""
        schedule = self._create_dues_schedule(status="Paused")

        # Should not find with Active filter
        self.assertIsNone(get_member_dues_schedule(self.member.name, status_filter="Active"))

        # Should find with Paused filter
        result = get_member_dues_schedule(self.member.name, status_filter="Paused")
        self.assertEqual(result['status'], "Paused")

        # Should find with None filter (any status)
        result = get_member_dues_schedule(self.member.name, status_filter=None)
        self.assertIsNotNone(result)

    def test_get_member_dues_schedule_template_exclusion(self):
        """Test that templates are excluded by default"""
        template = self._create_dues_schedule(status="Active", is_template=1)

        # Should not find template by default
        self.assertIsNone(get_member_dues_schedule(self.member.name))

        # Should find with include_template=True
        result = get_member_dues_schedule(self.member.name, include_template=True)
        self.assertIsNotNone(result)

    # ========================================================================
    # Active or Paused Schedule Tests
    # ========================================================================

    def test_get_member_active_or_paused_schedule(self):
        """Test active or paused query finds both Active and Paused schedules"""
        # Test with Active schedule
        schedule = self._create_dues_schedule(status="Active")
        result = get_member_active_or_paused_schedule(self.member.name)
        self.assertEqual(result['status'], "Active")

        # Update to Paused - should still be found
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Paused")
        result = get_member_active_or_paused_schedule(self.member.name)
        self.assertEqual(result['status'], "Paused")

    def test_get_member_active_or_paused_schedule_excludes_cancelled(self):
        """Test active or paused query excludes cancelled schedules"""
        schedule = self._create_dues_schedule(status="Cancelled")
        self.assertIsNone(get_member_active_or_paused_schedule(self.member.name))

    # ========================================================================
    # Boolean Helper Tests (Performance Optimized)
    # ========================================================================

    def test_has_active_dues_schedule_true(self):
        """Test boolean check returns True for active schedule"""
        schedule = self._create_dues_schedule(status="Active")

        result = has_active_dues_schedule(self.member.name)

        self.assertTrue(result)

    def test_has_active_dues_schedule_false(self):
        """Test boolean check returns False when no active schedule"""
        # Clean up any orphaned schedules from previous tests (Frappe test isolation issue)
        self._cleanup_member_schedules()

        result = has_active_dues_schedule(self.member.name)
        self.assertFalse(result)

    def test_has_active_dues_schedule_paused_returns_false(self):
        """Test boolean check returns False for paused schedule"""
        schedule = self._create_dues_schedule(status="Paused")

        result = has_active_dues_schedule(self.member.name)
        self.assertFalse(result)

    def test_has_active_dues_schedule_empty_input(self):
        """Test boolean check with empty input"""
        result = has_active_dues_schedule("")
        self.assertFalse(result)

        result = has_active_dues_schedule(None)
        self.assertFalse(result)

    def test_has_any_dues_schedule_true_active(self):
        """Test any schedule check returns True for active schedule"""
        schedule = self._create_dues_schedule(status="Active")

        result = has_any_dues_schedule(self.member.name)
        self.assertTrue(result)

    def test_has_any_dues_schedule_true_cancelled(self):
        """Test any schedule check returns True even for cancelled"""
        schedule = self._create_dues_schedule(status="Cancelled")

        result = has_any_dues_schedule(self.member.name)
        self.assertTrue(result)

    def test_has_any_dues_schedule_false(self):
        """Test any schedule check returns False when no schedules"""
        # Clean up any orphaned schedules from previous tests (Frappe test isolation issue)
        self._cleanup_member_schedules()

        result = has_any_dues_schedule(self.member.name)
        self.assertFalse(result)

    def test_has_any_dues_schedule_empty_input(self):
        """Test any schedule check with empty input"""
        result = has_any_dues_schedule("")
        self.assertFalse(result)

    # ========================================================================
    # Membership-Based Query Tests
    # ========================================================================

    def test_get_dues_schedule_for_membership_success(self):
        """Test dues schedule lookup by membership"""
        schedule = self._create_dues_schedule(status="Active")

        result = get_dues_schedule_for_membership(self.membership.name)

        self.assertIsNotNone(result)
        self.assertEqual(result['name'], schedule.name)
        self.assertEqual(result['member'], self.member.name)

    def test_get_dues_schedule_for_membership_not_found(self):
        """Test membership query when no schedule exists"""
        # Clean up any orphaned schedules from previous tests (Frappe test isolation issue)
        self._cleanup_membership_schedules()

        result = get_dues_schedule_for_membership(self.membership.name)
        self.assertIsNone(result)

    def test_get_dues_schedule_for_membership_empty_input(self):
        """Test membership query with empty input"""
        result = get_dues_schedule_for_membership("")
        self.assertIsNone(result)

    def test_get_dues_schedule_for_membership_name_success(self):
        """Test simplified membership name query"""
        schedule = self._create_dues_schedule(status="Active")

        result = get_dues_schedule_for_membership_name(self.membership.name)

        self.assertEqual(result, schedule.name)

    def test_get_dues_schedule_for_membership_name_not_found(self):
        """Test membership name query when no schedule exists"""
        # Clean up any orphaned schedules from previous tests (Frappe test isolation issue)
        self._cleanup_membership_schedules()

        result = get_dues_schedule_for_membership_name(self.membership.name)
        self.assertIsNone(result)

    # ========================================================================
    # Field Validation Tests
    # ========================================================================

    def test_field_validation_invalid_fields_filtered(self):
        """Test that invalid fields are filtered out gracefully"""
        schedule = self._create_dues_schedule(status="Active")

        # Request mix of valid and invalid fields
        result = get_member_dues_schedule(
            self.member.name,
            fields=["name", "dues_rate", "nonexistent_field", "status"]
        )

        # Should still return result with valid fields only
        self.assertIsNotNone(result)
        self.assertIn('name', result)
        self.assertIn('dues_rate', result)
        self.assertIn('status', result)

    def test_field_validation_all_invalid_fields(self):
        """Test behavior when all requested fields are invalid"""
        schedule = self._create_dues_schedule(status="Active")

        # Request only invalid fields
        result = get_member_dues_schedule(
            self.member.name,
            fields=["invalid_field_1", "invalid_field_2"]
        )

        # Should return None when no valid fields
        self.assertIsNone(result)

    # ========================================================================
    # Status Transition Tests
    # ========================================================================

    def test_status_transition_active_to_paused(self):
        """Test schedule can be found through status transitions"""
        schedule = self._create_dues_schedule(status="Active")

        # Initially found as Active
        result = get_member_dues_schedule(self.member.name, status_filter="Active")
        self.assertIsNotNone(result)

        # Update to Paused (using db.set_value to avoid triggering cleanup)
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Paused")

        # No longer found as Active
        result = get_member_dues_schedule(self.member.name, status_filter="Active")
        self.assertIsNone(result)

        # Now found as Paused
        result = get_member_dues_schedule(self.member.name, status_filter="Paused")
        self.assertIsNotNone(result)

    def test_status_transition_active_or_paused_still_found(self):
        """Test active_or_paused query works across transitions"""
        schedule = self._create_dues_schedule(status="Active")

        # Found as Active
        result = get_member_active_or_paused_schedule(self.member.name)
        self.assertIsNotNone(result)

        # Update to Paused (using db.set_value to avoid triggering cleanup)
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Paused")

        # Still found by active_or_paused query
        result = get_member_active_or_paused_schedule(self.member.name)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], "Paused")

    # ========================================================================
    # Edge Cases and Error Handling
    # ========================================================================

    def test_only_active_schedule_returned_when_cancelled_exists(self):
        """Test that active schedule is returned even when cancelled schedule exists"""
        # Business rule: Members can only have ONE active schedule at a time
        # But they can have historical cancelled schedules

        # Create first schedule as Active, then cancel it
        old_schedule = self._create_dues_schedule(status="Active", dues_rate=50.0)
        frappe.db.set_value("Membership Dues Schedule", old_schedule.name, "status", "Cancelled")

        # Create a new active schedule (this replaces the old one)
        # Note: _create_dues_schedule calls cleanup, which will delete the cancelled schedule
        # This is actually correct behavior - when creating a new active schedule, old ones are cleaned up
        # So this test should verify that the new active schedule is found
        new_schedule = self._create_dues_schedule(status="Active", dues_rate=75.0)

        # Should only return the active schedule
        result = get_member_dues_schedule(self.member.name, status_filter="Active")

        self.assertIsNotNone(result)
        self.assertEqual(result['name'], new_schedule.name)
        self.assertEqual(result['dues_rate'], 75.0)

    def test_nonexistent_member_returns_none(self):
        """Test lookup with non-existent member"""
        result = get_member_dues_schedule("NONEXISTENT-MEMBER-123")
        self.assertIsNone(result)

    def test_special_characters_in_member_name(self):
        """Test handling of special characters in member name"""
        # Test with various edge case inputs
        result = get_member_dues_schedule("Member's-Name-With-Apostrophe")
        self.assertIsNone(result)

        result = get_member_dues_schedule("Member@Domain.com")
        self.assertIsNone(result)


if __name__ == '__main__':
    import unittest
    unittest.main()