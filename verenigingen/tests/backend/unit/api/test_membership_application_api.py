# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Membership Application API functions
Tests the whitelisted API functions for membership applications
"""


import frappe
from frappe.utils import add_days, today

from verenigingen.verenigingen.api import membership_application
from verenigingen.tests.utils.assertions import AssertionHelpers
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder


class TestMembershipApplicationAPI(VereningingenUnitTestCase):
    """Test Membership Application API functions"""

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()
        self.assertions = AssertionHelpers()

    def tearDown(self):
        """Clean up after each test"""
        self.builder.cleanup()
        super().tearDown()

    def test_submit_application_valid_data(self):
        """Test submitting a valid membership application"""
        application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": "test.applicant@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),  # 25 years old
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "newsletter_opt_in": 1,
            "agree_to_terms": 1,
        }

        # Submit application
        result = membership_application.submit_application(application_data)

        # Verify result
        self.assertIn("member_name", result)
        self.assertIn("application_id", result)
        self.assertEqual(result["status"], "success")

        # Verify member created
        member = frappe.get_doc("Member", result["member_name"])
        self.track_doc("Member", member.name)

        self.assertEqual(member.first_name, application_data["first_name"])
        self.assertEqual(member.last_name, application_data["last_name"])
        self.assertEqual(member.email, application_data["email"])
        self.assertEqual(member.status, "Application Submitted")
        self.assertEqual(member.application_status, "Pending Review")

    def test_submit_application_duplicate_email(self):
        """Test submitting application with duplicate email"""
        # Create existing member
        test_data = self.builder.with_member(email="existing@example.com", status="Active").build()

        # Try to submit with same email
        application_data = {
            "first_name": "Duplicate",
            "last_name": "Email",
            "email": "existing@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "agree_to_terms": 1,
        }

        # Should raise validation error
        with self.assertRaises(frappe.ValidationError) as context:
            membership_application.submit_application(application_data)

        self.assertIn("already exists", str(context.exception))

    def test_submit_application_special_characters(self):
        """Test submitting application with special characters in name"""
        application_data = {
            "first_name": "José",
            "last_name": "O'Brien-García",
            "email": "jose.obrien@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 30),
            "street_name": "Çağlayan Street",
            "house_number": "123A",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "agree_to_terms": 1,
        }

        # Submit application
        result = membership_application.submit_application(application_data)

        # Verify special characters handled correctly
        member = frappe.get_doc("Member", result["member_name"])
        self.track_doc("Member", member.name)

        self.assertEqual(member.first_name, "José")
        self.assertEqual(member.last_name, "O'Brien-García")

    def test_submit_application_missing_required_fields(self):
        """Test submitting application with missing required fields"""
        # Missing email
        application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            # "email": missing
            "contact_number": "+31612345678",
            "agree_to_terms": 1,
        }

        with self.assertRaises(frappe.ValidationError) as context:
            membership_application.submit_application(application_data)

        self.assertIn("required", str(context.exception).lower())

    def test_submit_application_invalid_email_format(self):
        """Test submitting application with invalid email format"""
        application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": "invalid-email-format",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "agree_to_terms": 1,
        }

        with self.assertRaises(frappe.ValidationError) as context:
            membership_application.submit_application(application_data)

        self.assertIn("email", str(context.exception).lower())

    def test_get_application_status(self):
        """Test getting application status"""
        # Create application member
        test_data = self.builder.with_member(
            status="Application Submitted", application_status="Pending Review"
        ).build()

        member = test_data["member"]

        # Get status
        status = membership_application.get_application_status(member.name)

        self.assertEqual(status["status"], "Application Submitted")
        self.assertEqual(status["application_status"], "Pending Review")
        self.assertIn("submitted_date", status)

    def test_update_application(self):
        """Test updating an existing application"""
        # Create application member
        test_data = self.builder.with_member(
            status="Application Submitted", application_status="Pending Review"
        ).build()

        member = test_data["member"]

        # Update data
        update_data = {
            "contact_number": "+31687654321",
            "street_name": "Updated Street",
            "house_number": "456",
        }

        membership_application.update_application(member.name, update_data)

        # Verify updates
        member.reload()
        self.assertEqual(member.contact_number, update_data["contact_number"])
        self.assertEqual(member.street_name, update_data["street_name"])
        self.assertEqual(member.house_number, update_data["house_number"])

    def test_validate_postal_code(self):
        """Test postal code validation for chapter assignment"""
        # Create chapter with postal codes
        test_data = self.builder.with_chapter(
            name="Amsterdam Chapter", postal_codes="1000-1099,1100-1199"
        ).build()

        # Test valid postal code
        application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": "postal.test@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1050",  # Within Amsterdam range
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "agree_to_terms": 1,
        }

        result = membership_application.submit_application(application_data)

        # Verify chapter assignment
        member = frappe.get_doc("Member", result["member_name"])
        self.track_doc("Member", member.name)

        self.assertEqual(member.primary_chapter, "Amsterdam Chapter")

    def test_submit_application_with_sepa_details(self):
        """Test submitting application with SEPA payment details"""
        application_data = {
            "first_name": "SEPA",
            "last_name": "Test",
            "email": "sepa.test@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 30),
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bank_account_name": "SEPA Test",
            "agree_to_terms": 1,
            "agree_to_sepa_mandate": 1,
        }

        result = membership_application.submit_application(application_data)

        # Verify SEPA details stored
        member = frappe.get_doc("Member", result["member_name"])
        self.track_doc("Member", member.name)

        self.assertEqual(member.payment_method, "SEPA Direct Debit")
        self.assertEqual(member.iban, "NL91 ABNA 0417 1643 00")  # Formatted
        self.assertEqual(member.bank_account_name, "SEPA Test")

    def test_submit_application_age_validation(self):
        """Test age validation for membership applications"""
        # Test underage applicant
        application_data = {
            "first_name": "Young",
            "last_name": "Applicant",
            "email": "young@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 15),  # 15 years old
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam",
            "country": "Netherlands",
            "preferred_payment_method": "Bank Transfer",
            "agree_to_terms": 1,
        }

        # This might require parental consent or special handling
        result = membership_application.submit_application(application_data)

        member = frappe.get_doc("Member", result["member_name"])
        self.track_doc("Member", member.name)

        # Verify age calculated
        self.assertLessEqual(member.age, 15)

    def test_resend_confirmation_email(self):
        """Test resending application confirmation email"""
        # Create application member
        test_data = self.builder.with_member(
            status="Application Submitted", email="confirmation@example.com"
        ).build()

        member = test_data["member"]

        # Test resend confirmation
        if hasattr(membership_application, "resend_confirmation_email"):
            membership_application.resend_confirmation_email(member.name)

            # Verify email queued
            self.assertions.assert_email_sent(member.email, subject_contains="Application Confirmation")
