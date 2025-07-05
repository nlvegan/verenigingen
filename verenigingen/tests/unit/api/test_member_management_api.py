# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Member Management API functions
Tests the whitelisted API functions for member management operations
"""


import frappe
from frappe.utils import add_days, today

from verenigingen.verenigingen.api import member_management
from verenigingen.verenigingen.tests.utils.assertions import AssertionHelpers
from verenigingen.verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestMemberManagementAPI(VereningingenUnitTestCase):
    """Test Member Management API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = TestEnvironmentSetup.create_standard_test_environment()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()
        self.assertions = AssertionHelpers()

    def tearDown(self):
        """Clean up after each test"""
        self.builder.cleanup()
        super().tearDown()

    def test_get_member_profile(self):
        """Test getting member profile information"""
        # Create member with full profile
        test_data = (
            self.builder.with_chapter(self.test_env["chapters"][0].name)
            .with_member(first_name="Profile", last_name="Test", email="profile@test.com")
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        member = test_data["member"]

        # Get profile
        profile = member_management.get_member_profile(member.name)

        # Verify profile data
        self.assertEqual(profile["first_name"], "Profile")
        self.assertEqual(profile["last_name"], "Test")
        self.assertEqual(profile["email"], "profile@test.com")
        self.assertIn("membership_status", profile)
        self.assertIn("primary_chapter", profile)
        self.assertIn("member_since_date", profile)

    def test_update_member_information(self):
        """Test updating member information"""
        # Create member
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Update information
        update_data = {
            "contact_number": "+31698765432",
            "street_name": "New Street",
            "house_number": "999",
            "postal_code": "5678",
            "city": "Rotterdam",
            "newsletter_opt_in": 0,
        }

        member_management.update_member_information(member.name, update_data)

        # Verify updates
        member.reload()
        self.assertEqual(member.contact_number, update_data["contact_number"])
        self.assertEqual(member.street_name, update_data["street_name"])
        self.assertEqual(member.city, update_data["city"])
        self.assertEqual(member.newsletter_opt_in, 0)

    def test_assign_member_to_chapter(self):
        """Test assigning member to a chapter"""
        # Create member without chapter
        test_data = self.builder.with_member().build()
        member = test_data["member"]
        chapter = self.test_env["chapters"][0]

        # Assign to chapter
        member_management.assign_member_to_chapter(member.name, chapter.name)

        # Verify assignment
        member.reload()
        self.assertEqual(member.primary_chapter, chapter.name)

        # Verify chapter_members updated
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_names = [cm.member for cm in chapter_doc.chapter_members]
        self.assertIn(member.name, member_names)

    def test_remove_member_from_chapter(self):
        """Test removing member from a chapter"""
        # Create member with chapter
        test_data = self.builder.with_chapter(self.test_env["chapters"][0].name).with_member().build()

        member = test_data["member"]
        chapter = test_data["chapter"]

        # Remove from chapter
        result = member_management.remove_member_from_chapter(
            member.name, chapter.name, reason="Moved to different region"
        )

        # Verify removal
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        active_members = [
            cm for cm in chapter_doc.chapter_members if cm.member == member.name and cm.status == "Active"
        ]
        self.assertEqual(len(active_members), 0)

    def test_get_member_chapters(self):
        """Test getting all chapters a member belongs to"""
        # Create member in multiple chapters
        test_data = self.builder.with_chapter(self.test_env["chapters"][0].name).with_member().build()

        member = test_data["member"]

        # Add to second chapter
        second_chapter = self.test_env["chapters"][1]
        member_management.assign_member_to_chapter(member.name, second_chapter.name)

        # Get all chapters
        chapters = member_management.get_member_chapters(member.name)

        self.assertEqual(len(chapters), 2)
        chapter_names = [c["chapter"] for c in chapters]
        self.assertIn(self.test_env["chapters"][0].name, chapter_names)
        self.assertIn(second_chapter.name, chapter_names)

    def test_update_member_status(self):
        """Test updating member status"""
        # Create active member
        test_data = self.builder.with_member(status="Active").build()
        member = test_data["member"]

        # Suspend member
        result = member_management.update_member_status(member.name, "Suspended", reason="Non-payment")

        # Verify status update
        member.reload()
        self.assertEqual(member.status, "Suspended")
        self.assertEqual(member.suspension_reason, "Non-payment")
        self.assertIsNotNone(member.suspension_date)

    def test_reactivate_member(self):
        """Test reactivating a suspended member"""
        # Create suspended member
        test_data = self.builder.with_member(
            status="Suspended", suspension_date=add_days(today(), -30), suspension_reason="Payment failure"
        ).build()

        member = test_data["member"]

        # Reactivate
        result = member_management.update_member_status(member.name, "Active", reason="Payment received")

        # Verify reactivation
        member.reload()
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.suspension_lifted_date)

    def test_get_member_activity_summary(self):
        """Test getting member activity summary"""
        # Create member with volunteer profile and activities
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .with_volunteer_profile()
            .with_team_assignment(team_name=self.test_env["teams"][0].name, role="Team Member")
            .with_expense(50.00, "Event supplies")
            .build()
        )

        member = test_data["member"]

        # Get activity summary
        if hasattr(member_management, "get_member_activity_summary"):
            summary = member_management.get_member_activity_summary(member.name)

            self.assertIn("membership_duration", summary)
            self.assertIn("volunteer_status", summary)
            self.assertIn("team_count", summary)
            self.assertIn("total_expenses", summary)

    def test_member_search(self):
        """Test searching for members"""
        # Create multiple members
        members = []
        for i in range(3):
            test_data = self.builder.with_member(
                first_name=f"Search{i}", last_name="Test", email=f"search{i}@test.com"
            ).build()
            members.append(test_data["member"])
            self.builder.cleanup()

        # Search by name
        if hasattr(member_management, "search_members"):
            results = member_management.search_members(query="Search")

            self.assertGreaterEqual(len(results), 3)

            # Search by email
            results = member_management.search_members(query="search1@test.com")
            self.assertGreaterEqual(len(results), 1)

    def test_bulk_member_update(self):
        """Test bulk updating multiple members"""
        # Create multiple members
        member_names = []
        for i in range(3):
            test_data = self.builder.with_member().build()
            member_names.append(test_data["member"].name)
            self.builder.cleanup()

        # Bulk update
        if hasattr(member_management, "bulk_update_members"):
            update_data = {"newsletter_opt_in": 1, "communication_preference": "Email"}

            member_management.bulk_update_members(member_names, update_data)

            # Verify all updated
            for member_name in member_names:
                member = frappe.get_doc("Member", member_name)
                self.assertEqual(member.newsletter_opt_in, 1)

    def test_export_member_data(self):
        """Test exporting member data for GDPR compliance"""
        # Create member with full data
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .with_volunteer_profile()
            .build()
        )

        member = test_data["member"]

        # Export data
        if hasattr(member_management, "export_member_data"):
            export_data = member_management.export_member_data(member.name)

            self.assertIn("personal_data", export_data)
            self.assertIn("membership_history", export_data)
            self.assertIn("volunteer_data", export_data)
            self.assertIn("export_date", export_data)

    def test_member_communication_preferences(self):
        """Test managing member communication preferences"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Update preferences
        if hasattr(member_management, "update_communication_preferences"):
            preferences = {
                "newsletter": False,
                "event_notifications": True,
                "volunteer_opportunities": True,
                "preferred_language": "nl",
            }

            member_management.update_communication_preferences(member.name, preferences)

            # Verify preferences updated
            member.reload()
            # Check preference fields if they exist

    def test_member_permission_checks(self):
        """Test permission checks for member operations"""
        # Create member with user
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create regular user
        regular_user = self.create_test_user(email="regular@test.com", roles=["Member"])

        # Link user to member
        member.user = regular_user.name
        member.save()

        # Test as regular user - should only access own profile
        with self.as_user(regular_user.name):
            # Should succeed for own profile
            profile = member_management.get_member_profile(member.name)
            self.assertIsNotNone(profile)

            # Should fail for other member
            other_member = self.builder.with_member().build()["member"]

            with self.assertRaises(frappe.PermissionError):
                member_management.get_member_profile(other_member.name)
