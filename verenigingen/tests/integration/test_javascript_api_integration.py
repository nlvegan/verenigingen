# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Integration tests for JavaScript API calls
Tests the complete flow of JavaScript actions calling whitelisted Python methods
"""


import frappe
from frappe.utils import random_string, today

from verenigingen.tests.utils.base import VereningingenIntegrationTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestJavaScriptAPIIntegration(VereningingenIntegrationTestCase):
    """Test JavaScript button actions and their API calls end-to-end"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = TestEnvironmentSetup.create_standard_test_environment()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        try:
            self.builder.cleanup()
        except Exception as e:
            frappe.logger().error(f"Cleanup error in test: {str(e)}")
        super().tearDown()

    def test_volunteer_activity_workflow(self):
        """Test complete volunteer activity workflow from JavaScript actions"""
        # Create volunteer
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]
        test_data["member"]

        # Simulate "Add Activity" button click
        activity_data = {
            "activity_type": "Event Support",
            "description": "Annual Conference Support",
            "date": today(),
            "hours": 8,
        }

        # API call from JavaScript
        frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
            doc=volunteer.as_dict(),
            **activity_data,
        )

        # Verify activity added
        volunteer.reload()
        self.assertEqual(len(volunteer.activities), 1)

        # Simulate "End Activity" button click
        activity = volunteer.activities[0]
        frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.end_activity",
            doc=volunteer.as_dict(),
            activity_name=activity.name,
            end_time=frappe.utils.now_datetime(),
        )

        # Verify activity completed
        volunteer.reload()
        self.assertEqual(volunteer.activities[0].status, "Completed")

        # Simulate "View Timeline" button click
        history = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.get_volunteer_history",
            doc=volunteer.as_dict(),
        )

        # Verify history includes the activity
        self.assertEqual(history["total_hours"], 8.0)
        self.assertEqual(len(history["activities"]), 1)

    def test_chapter_board_management_workflow(self):
        """Test chapter board member management from JavaScript actions"""
        # Create chapter and members
        chapter = frappe.get_doc(
            {"doctype": "Chapter", "chapter_name": "Integration Test Chapter", "chapter_code": "ITC"}
        )
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)

        members = []
        for i in range(3):
            test_data = self.builder.with_member(first_name=f"Board{i}", last_name="Member").build()
            members.append(test_data["member"])

        # Simulate "Manage Board Members" button click - Add members
        for i, member in enumerate(members):
            roles = ["President", "Secretary", "Treasurer"]
            frappe.call(
                "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
                doc=chapter.as_dict(),
                member=member.name,
                role=roles[i],
                start_date=today(),
            )

        # Verify board members added
        chapter.reload()
        self.assertEqual(len(chapter.board_members), 3)

        # Test the board member status field specifically
        for board_member in chapter.board_members:
            self.assertEqual(board_member.status, "Active")

        # Simulate role transition for President
        frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.transition_board_role",
            doc=chapter.as_dict(),
            member=members[0].name,
            new_role="Board Member",
            transition_date=today(),
        )

        # Verify transition
        chapter.reload()
        president_entries = [bm for bm in chapter.board_members if bm.member == members[0].name]
        self.assertEqual(len(president_entries), 2)  # Old and new role

        # Simulate "View Board History" button click
        history = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_board_history",
            chapter_name=chapter.name,
            include_inactive=True,
        )

        # Verify history includes all entries
        self.assertGreaterEqual(len(history), 4)  # 3 original + 1 transition

        # Simulate "Sync with Volunteer System" button click
        sync_result = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.sync_chapter_board_members",
            chapter_name=chapter.name,
        )

        # Verify volunteers created
        self.assertEqual(sync_result["created"], 3)

        # Verify all members now have volunteer records
        for member in members:
            member.reload()
            self.assertTrue(member.volunteer)

    def test_member_account_creation_workflow(self):
        """Test member account creation workflow from JavaScript actions"""
        # Create member
        test_data = self.builder.with_member(
            first_name="Account", last_name="Creation", email=f"account.creation.{random_string(8)}@test.com"
        ).build()

        member = test_data["member"]

        # Simulate "Create Customer" button click
        customer_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.create_customer", doc=member.as_dict()
        )

        # Verify customer created
        self.assertTrue(customer_result)
        member.reload()
        self.assertEqual(member.customer, customer_result)

        # Simulate "Create User" button click
        user_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.create_user", doc=member.as_dict()
        )

        # Verify user created
        self.assertTrue(user_result)
        member.reload()
        self.assertEqual(member.user, user_result)

        # Simulate "Create Volunteer" button click
        volunteer_result = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member",
            member_name=member.name,
        )

        # Verify volunteer created
        self.assertTrue(volunteer_result)
        member.reload()
        self.assertEqual(member.volunteer, volunteer_result)

    def test_payment_processing_workflow(self):
        """Test payment processing workflow from JavaScript actions"""
        # Create member with SEPA payment method
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bank_account_name="Test Member",
            first_name="Payment",
            last_name="Test",
        ).build()

        member = test_data["member"]

        # Simulate "Process Payment" button click - validate mandate
        validation_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.validate_mandate_creation",
            member_name=member.name,
        )

        self.assertTrue(validation_result)

        # Create SEPA mandate
        mandate_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_and_link_mandate_enhanced",
            member_name=member.name,
            bank_account_name=member.bank_account_name,
            iban=member.iban,
        )

        # Verify mandate created
        self.assertEqual(mandate_result["status"], "success")
        self.assertIn("mandate", mandate_result)

        # Verify member has active mandate
        active_mandate = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.get_active_sepa_mandate",
            doc=member.as_dict(),
        )

        self.assertIsNotNone(active_mandate)
        self.assertEqual(active_mandate["status"], "Active")

    def test_member_suspension_reactivation_workflow(self):
        """Test member suspension and reactivation workflow"""
        # Create active member with membership
        test_data = self.builder.with_member(status="Active").with_membership().build()

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit membership
        membership.submit()

        # Simulate "Suspend Member" action
        suspension = frappe.get_doc(
            {
                "doctype": "Member Suspension",
                "member": member.name,
                "suspension_reason": "Non-payment",
                "suspension_date": today(),
                "status": "Approved",
            }
        )
        suspension.insert(ignore_permissions=True)
        self.track_doc("Member Suspension", suspension.name)

        # Verify member suspended
        member.reload()
        self.assertEqual(member.status, "Suspended")

        # Simulate "Reactivate Member" action
        member.status = "Active"
        member.save()

        # Update suspension record
        suspension.reactivation_date = today()
        suspension.reactivation_reason = "Payment received"
        suspension.save()

        # Verify member reactivated
        member.reload()
        self.assertEqual(member.status, "Active")

    def test_fee_management_workflow(self):
        """Test membership fee management workflow"""
        # Create member with membership
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Standard Annual",
                "amount": 120,
                "currency": "EUR",
                "subscription_period": "Annual",
            }
        )
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)

        test_data = self.builder.with_member().with_membership(membership_type=membership_type.name).build()

        member = test_data["member"]
        membership = test_data["membership"]
        membership.submit()

        # Get current fee
        current_fee = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.get_current_membership_fee",
            doc=member.as_dict(),
        )

        self.assertEqual(current_fee, 120)

        # Apply fee override (admin action)
        member.membership_fee_override = 90
        member.fee_override_reason = "Hardship discount"
        member.save()

        # Get display fee (should show override)
        display_fee = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.get_display_membership_fee",
            doc=member.as_dict(),
        )

        self.assertEqual(display_fee, 90)

    def test_skill_management_workflow(self):
        """Test volunteer skill management workflow"""
        # Create volunteer
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]

        # Simulate "Add Skill" button clicks
        skills = [
            {
                "skill_name": "Project Management",
                "skill_category": "Management",
                "proficiency_level": "Expert",
            },
            {
                "skill_name": "Python Programming",
                "skill_category": "Technical",
                "proficiency_level": "Advanced",
            },
            {
                "skill_name": "Event Planning",
                "skill_category": "Administrative",
                "proficiency_level": "Intermediate",
            },
        ]

        for skill in skills:
            volunteer.append("skills", skill)

        volunteer.save(ignore_permissions=True)

        # Get skills by category
        categorized_skills = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.get_skills_by_category",
            doc=volunteer.as_dict(),
        )

        # Verify categorization
        self.assertEqual(len(categorized_skills), 3)
        self.assertIn("Management", categorized_skills)
        self.assertIn("Technical", categorized_skills)
        self.assertIn("Administrative", categorized_skills)

    def test_error_recovery_workflow(self):
        """Test error handling and recovery in JavaScript workflows"""
        # Test creating user with invalid email
        test_data = self.builder.with_member(email="invalid-email").build()  # Invalid email format

        member = test_data["member"]

        # Attempt to create user should fail gracefully
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.member.member.Member.create_user", doc=member.as_dict()
            )

        # Fix email and retry
        member.email = f"valid.email.{random_string(8)}@test.com"
        member.save()

        # Now should succeed
        user_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.Member.create_user", doc=member.as_dict()
        )

        self.assertTrue(user_result)

    def test_concurrent_operations(self):
        """Test handling of concurrent JavaScript operations"""
        # Create chapter
        chapter = frappe.get_doc(
            {"doctype": "Chapter", "chapter_name": "Concurrent Test Chapter", "chapter_code": "CTC"}
        )
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)

        # Create multiple members
        members = []
        for i in range(5):
            test_data = self.builder.with_member(first_name=f"Concurrent{i}", last_name="Member").build()
            members.append(test_data["member"])

        # Simulate rapid "Add Board Member" clicks
        for member in members:
            try:
                frappe.call(
                    "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
                    doc=chapter.as_dict(),
                    member=member.name,
                    role="Board Member",
                    start_date=today(),
                )
            except frappe.ValidationError:
                # Handle duplicate member errors gracefully
                pass

        # Verify all members added correctly
        chapter.reload()
        added_members = [bm.member for bm in chapter.board_members if bm.status == "Active"]
        self.assertEqual(len(added_members), 5)

    def test_permission_based_actions(self):
        """Test JavaScript actions with different user permissions"""
        # Create test users with different roles
        admin_user = self.create_test_user(
            email=f"admin.{random_string(8)}@test.com", roles=["System Manager", "Verenigingen Admin"]
        )

        member_user = self.create_test_user(
            email=f"member.{random_string(8)}@test.com", roles=["Verenigingen Member"]
        )

        # Create member
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Test as admin - should succeed
        with self.as_user(admin_user.name):
            customer_result = frappe.call(
                "verenigingen.verenigingen.doctype.member.member.Member.create_customer", doc=member.as_dict()
            )
            self.assertTrue(customer_result)

        # Test as regular member - should fail
        with self.as_user(member_user.name):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.verenigingen.doctype.member.member.Member.create_user", doc=member.as_dict()
                )
