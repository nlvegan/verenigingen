"""
Comprehensive tests for VolunteerExpenseApproverService

Tests the expense approver determination logic for volunteers based on
their organizational assignments (board, chapter, team).

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe.utils import today

from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerExpenseApproverService(EnhancedTestCase):
    """Test suite for VolunteerExpenseApproverService"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create national board chapter in settings
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.national_board_chapter:
            # Create national chapter (no chapter_name parameter needed - autoname)
            national_chapter = self.create_test_chapter()
            settings.national_board_chapter = national_chapter.name
            settings.save()

    def test_national_board_member_approver(self):
        """Test approver selection for national board members"""
        # Create treasurer for national board
        treasurer_member = self.create_test_member(
            first_name="National",
            last_name="Treasurer",
            email="treasurer@example.com"
        )
        # Explicitly create user for treasurer
        if not frappe.db.exists("User", treasurer_member.email):
            from verenigingen.utils.member_account_service import create_member_user_account
            create_member_user_account(treasurer_member, send_welcome_email=False)
            treasurer_member.reload()

        treasurer_volunteer = self.create_test_volunteer(treasurer_member.name)

        # Create the volunteer who needs an approver
        member = self.create_test_member(
            first_name="Board",
            last_name="Member",
            email="boardmember@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Add both to national board
        settings = frappe.get_single("Verenigingen Settings")
        national_chapter = frappe.get_doc("Chapter", settings.national_board_chapter)

        # Add treasurer
        national_chapter.append("board_members", {
            "volunteer": treasurer_volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })

        # Add board member
        national_chapter.append("board_members", {
            "volunteer": volunteer.name,
            "chapter_role": "Secretary",
            "is_active": 1,
            "from_date": today()
        })

        national_chapter.save()

        # Test: Board member's approver should be the treasurer
        service = VolunteerExpenseApproverService(volunteer.name)
        approver = service.get_expense_approver()

        self.assertEqual(approver, treasurer_member.email)

    def test_chapter_member_approver(self):
        """Test approver selection for chapter members"""
        # Create a regular chapter with treasurer
        chapter = self.create_test_chapter()

        treasurer_member = self.create_test_member(
            first_name="Chapter",
            last_name="Treasurer",
            email="chaptertreasurer@example.com"
        )
        # Explicitly create user for treasurer
        if not frappe.db.exists("User", treasurer_member.email):
            from verenigingen.utils.member_account_service import create_member_user_account
            create_member_user_account(treasurer_member, send_welcome_email=False)
            treasurer_member.reload()

        treasurer_volunteer = self.create_test_volunteer(treasurer_member.name)

        # Add treasurer to chapter
        chapter.append("board_members", {
            "volunteer": treasurer_volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })
        chapter.save()

        # Create chapter member
        member = self.create_test_member(
            first_name="Chapter",
            last_name="Member",
            email="chaptermember@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Add member to chapter
        chapter.append("members", {
            "member": member.name,
            "enabled": 1,
            "join_date": today()
        })
        chapter.save()

        # Test: Chapter member's approver should be chapter treasurer
        service = VolunteerExpenseApproverService(volunteer.name)
        approver = service.get_expense_approver()

        self.assertEqual(approver, treasurer_member.email)

    def test_team_member_approver(self):
        """Test approver selection via team's chapter"""
        # Create chapter with treasurer
        chapter = self.create_test_chapter()

        treasurer_member = self.create_test_member(
            first_name="Team",
            last_name="Treasurer",
            email="teamtreasurer@example.com"
        )
        # Explicitly create user for treasurer
        if not frappe.db.exists("User", treasurer_member.email):
            from verenigingen.utils.member_account_service import create_member_user_account
            create_member_user_account(treasurer_member, send_welcome_email=False)
            treasurer_member.reload()

        treasurer_volunteer = self.create_test_volunteer(treasurer_member.name)

        # Add treasurer to chapter
        chapter.append("board_members", {
            "volunteer": treasurer_volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })
        chapter.save()

        # Create team linked to chapter
        import time
        unique_team_name = f"Test Team {int(time.time() * 1000)}"
        team = frappe.get_doc({
            "doctype": "Team",
            "team_name": unique_team_name,
            "chapter": chapter.name
        })
        team.insert()

        # Create team member
        member = self.create_test_member(
            first_name="Team",
            last_name="Member",
            email="teammember@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Create or get a Team Role
        if not frappe.db.exists("Team Role", "Member"):
            team_role = frappe.get_doc({
                "doctype": "Team Role",
                "role_name": "Member"
            })
            team_role.insert()

        # Add volunteer to team
        team.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": "Member",
            "status": "Active",
            "from_date": today()
        })
        team.save()

        # Test: Team member's approver should be chapter treasurer
        service = VolunteerExpenseApproverService(volunteer.name)
        approver = service.get_expense_approver()

        self.assertEqual(approver, treasurer_member.email)

    def test_fallback_approver(self):
        """Test fallback to system manager"""
        # Create volunteer with no organizational ties
        member = self.create_test_member(
            first_name="Standalone",
            last_name="Volunteer",
            email="standalone@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Test: Should fallback to system manager or Administrator
        service = VolunteerExpenseApproverService(volunteer.name)
        approver = service.get_expense_approver()

        self.assertIsNotNone(approver)
        # Should be either a system user or Administrator
        self.assertTrue(
            frappe.db.exists("User", approver) or approver == "Administrator"
        )

    def test_financial_role_priority_order(self):
        """Test that Treasurer is preferred over Secretary"""
        chapter = self.create_test_chapter()

        # Create both treasurer and secretary
        treasurer_member = self.create_test_member(
            first_name="Priority",
            last_name="Treasurer",
            email="priority_treasurer@example.com"
        )
        # Explicitly create user for treasurer
        if not frappe.db.exists("User", treasurer_member.email):
            from verenigingen.utils.member_account_service import create_member_user_account
            create_member_user_account(treasurer_member, send_welcome_email=False)
            treasurer_member.reload()

        treasurer_volunteer = self.create_test_volunteer(treasurer_member.name)

        secretary_member = self.create_test_member(
            first_name="Priority",
            last_name="Secretary",
            email="priority_secretary@example.com"
        )
        # Explicitly create user for secretary
        if not frappe.db.exists("User", secretary_member.email):
            from verenigingen.utils.member_account_service import create_member_user_account
            create_member_user_account(secretary_member, send_welcome_email=False)
            secretary_member.reload()

        secretary_volunteer = self.create_test_volunteer(secretary_member.name)

        # Add both to chapter (secretary first to test priority)
        chapter.append("board_members", {
            "volunteer": secretary_volunteer.name,
            "chapter_role": "Secretary",
            "is_active": 1,
            "from_date": today()
        })

        chapter.append("board_members", {
            "volunteer": treasurer_volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })
        chapter.save()

        # Test: Should return treasurer, not secretary
        service = VolunteerExpenseApproverService(None)  # Service instance
        approver = service.get_board_financial_approver(chapter.name)

        self.assertEqual(approver, treasurer_member.email)

    def test_exclude_volunteer_from_approval(self):
        """Test that volunteer cannot approve their own expenses"""
        chapter = self.create_test_chapter()

        # Create volunteer who is the treasurer
        member = self.create_test_member(
            first_name="Self",
            last_name="Treasurer",
            email="selftreasurer@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Add as treasurer
        chapter.append("board_members", {
            "volunteer": volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })
        chapter.save()

        # Test: Should NOT return self as approver
        service = VolunteerExpenseApproverService(volunteer.name)
        approver = service.get_board_financial_approver(chapter.name, exclude_volunteer=volunteer.name)

        # Should return None (no other financial officer) or different user
        if approver:
            self.assertNotEqual(approver, member.email)

    def test_expense_approver_role_assignment(self):
        """Test automatic role assignment"""
        # Create user without expense approver role (use unique email)
        import time
        unique_email = f"needsrole{int(time.time() * 1000)}@example.com"

        user = frappe.get_doc({
            "doctype": "User",
            "email": unique_email,
            "first_name": "Needs",
            "last_name": "Role",
            "send_welcome_email": 0
        })
        user.insert()

        # Verify user doesn't have role initially
        self.assertNotIn("Expense Approver", [r.role for r in user.roles])

        # Use service to ensure role
        service = VolunteerExpenseApproverService(None)
        service.ensure_user_has_expense_approver_role(user.email)

        # Reload and verify role was added
        user.reload()
        self.assertIn("Expense Approver", [r.role for r in user.roles])


class TestVolunteerExpenseApproverServiceEdgeCases(EnhancedTestCase):
    """Edge case tests for expense approver service"""

    def test_inactive_board_members_excluded(self):
        """Test that inactive board members are not selected as approvers"""
        chapter = self.create_test_chapter()

        # Create inactive treasurer
        inactive_member = self.create_test_member(
            first_name="Inactive",
            last_name="Treasurer",
            email="inactivetreasurer@example.com"
        )
        inactive_volunteer = self.create_test_volunteer(inactive_member.name)

        # Add as treasurer but inactive
        chapter.append("board_members", {
            "volunteer": inactive_volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 0,  # Inactive!
            "from_date": today()
        })
        chapter.save()

        # Test: Should not return inactive treasurer
        service = VolunteerExpenseApproverService(None)
        approver = service.get_board_financial_approver(chapter.name)

        self.assertIsNone(approver)

    def test_disabled_user_excluded(self):
        """Test that disabled users are not selected as approvers"""
        chapter = self.create_test_chapter()

        # Create member with disabled user
        member = self.create_test_member(
            first_name="Disabled",
            last_name="Treasurer",
            email="disableduser@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        # Disable the user
        if frappe.db.exists("User", member.email):
            user = frappe.get_doc("User", member.email)
            user.enabled = 0
            user.save()

        # Add as treasurer
        chapter.append("board_members", {
            "volunteer": volunteer.name,
            "chapter_role": "Treasurer",
            "is_active": 1,
            "from_date": today()
        })
        chapter.save()

        # Test: Should not return disabled user
        service = VolunteerExpenseApproverService(None)
        approver = service.get_board_financial_approver(chapter.name)

        self.assertIsNone(approver)

    def test_nonexistent_volunteer(self):
        """Test behavior with nonexistent volunteer"""
        service = VolunteerExpenseApproverService("NONEXISTENT-VOL-123")

        # Should return Administrator as safe fallback
        approver = service.get_expense_approver()
        self.assertEqual(approver, "Administrator")
