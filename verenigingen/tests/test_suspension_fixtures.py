"""
Test fixtures and utilities for suspension system tests
"""

import unittest
from unittest.mock import MagicMock, patch


class SuspensionTestFixtures:
    """Test fixtures for suspension system tests"""

    @staticmethod
    def create_mock_member(
        member_id="TEST-MEMBER-001",
        status="Active",
        has_user=True,
        user_email="test@example.com",
        chapter="TEST-CHAPTER-001",
        notes=None,
    ):
        """Create a mock member document"""
        mock_member = MagicMock()
        mock_member.name = member_id
        mock_member.status = status
        mock_member.notes = notes
        mock_member.primary_chapter = chapter
        mock_member.user = user_email if has_user else None
        mock_member.pre_suspension_status = None
        mock_member.membership_badge_color = "#28a745"  # Green by default

        # Mock save method
        mock_member.save = MagicMock()
        mock_member.flags = MagicMock()

        return mock_member

    @staticmethod
    def create_mock_user(email="test@example.com", enabled=True, bio=None):
        """Create a mock user document"""
        mock_user = MagicMock()
        mock_user.email = email
        mock_user.enabled = enabled
        mock_user.bio = bio
        mock_user.roles = []

        # Mock save method
        mock_user.save = MagicMock()
        mock_user.flags = MagicMock()

        return mock_user

    @staticmethod
    def create_mock_chapter(chapter_id="TEST-CHAPTER-001", has_board_access=True):
        """Create a mock chapter document"""
        mock_chapter = MagicMock()
        mock_chapter.name = chapter_id
        mock_chapter.user_has_board_access = MagicMock(return_value=has_board_access)

        return mock_chapter

    @staticmethod
    def create_mock_team_member(team="TEST-TEAM", user="test@example.com", role="Member", docstatus=1):
        """Create a mock team member document"""
        mock_team_member = MagicMock()
        mock_team_member.parent = team
        mock_team_member.user = user
        mock_team_member.role = role
        mock_team_member.docstatus = docstatus

        # Mock document methods
        mock_team_member.cancel = MagicMock()
        mock_team_member.delete = MagicMock()
        mock_team_member.flags = MagicMock()

        return mock_team_member

    @staticmethod
    def create_mock_settings(national_chapter=None):
        """Create mock verenigingen settings"""
        mock_settings = MagicMock()
        mock_settings.national_chapter = national_chapter
        return mock_settings

    @staticmethod
    def create_suspension_result(
        success=True,
        member_suspended=True,
        user_suspended=True,
        teams_suspended=2,
        actions_taken=None,
        errors=None,
    ):
        """Create a mock suspension result"""
        if actions_taken is None:
            actions_taken = [
                "Member status changed from Active to Suspended",
                "User account suspended",
                f"Suspended {teams_suspended} team membership(s)",
            ]

        if errors is None:
            errors = []

        return {
            "success": success,
            "member_suspended": member_suspended,
            "user_suspended": user_suspended,
            "teams_suspended": teams_suspended,
            "actions_taken": actions_taken,
            "errors": errors,
        }

    @staticmethod
    def create_unsuspension_result(
        success=True, member_unsuspended=True, user_unsuspended=True, actions_taken=None, errors=None
    ):
        """Create a mock unsuspension result"""
        if actions_taken is None:
            actions_taken = [
                "Member status restored to Active",
                "User account reactivated",
                "Note: Team memberships require manual restoration",
            ]

        if errors is None:
            errors = []

        return {
            "success": success,
            "member_unsuspended": member_unsuspended,
            "user_unsuspended": user_unsuspended,
            "actions_taken": actions_taken,
            "errors": errors,
        }

    @staticmethod
    def create_suspension_status(
        is_suspended=True,
        member_status="Suspended",
        user_suspended=True,
        active_teams=0,
        pre_suspension_status="Active",
        can_unsuspend=True,
    ):
        """Create a mock suspension status"""
        return {
            "is_suspended": is_suspended,
            "member_status": member_status,
            "user_suspended": user_suspended,
            "active_teams": active_teams,
            "pre_suspension_status": pre_suspension_status,
            "can_unsuspend": can_unsuspend,
        }

    @staticmethod
    def create_suspension_preview(
        member_status="Active",
        has_user_account=True,
        active_teams=2,
        team_details=None,
        active_memberships=1,
        membership_details=None,
        can_suspend=True,
        is_currently_suspended=False,
    ):
        """Create a mock suspension preview"""
        if team_details is None:
            team_details = [
                {"team": "TEST-TEAM-A", "role": "Member"},
                {"team": "TEST-TEAM-B", "role": "Leader"},
            ]

        if membership_details is None:
            membership_details = [{"name": "MEMBERSHIP-001", "membership_type": "Regular"}]

        return {
            "member_status": member_status,
            "has_user_account": has_user_account,
            "active_teams": active_teams,
            "team_details": team_details,
            "active_memberships": active_memberships,
            "membership_details": membership_details,
            "can_suspend": can_suspend,
            "is_currently_suspended": is_currently_suspended,
        }

    @staticmethod
    def create_bulk_suspension_result(success_count=2, failed_count=0, details=None):
        """Create a mock bulk suspension result"""
        if details is None:
            details = [
                {
                    "member": "TEST-MEMBER-001",
                    "status": "success",
                    "actions": ["Member suspended", "User account disabled"],
                },
                {
                    "member": "TEST-MEMBER-002",
                    "status": "success",
                    "actions": ["Member suspended", "User account disabled"],
                },
            ]

        return {"success": success_count, "failed": failed_count, "details": details}


class SuspensionTestUtilities:
    """Test utilities for suspension system tests"""

    @staticmethod
    def setup_permission_mocks(
        user_roles=None,
        requesting_member="TEST-REQUESTING-MEMBER",
        has_board_access=True,
        national_chapter=None,
    ):
        """Set up common permission-related mocks"""
        if user_roles is None:
            user_roles = ["User"]

        mocks = {}

        # Mock frappe.get_roles
        mocks["get_roles"] = patch("frappe.get_roles", return_value=user_roles)

        # Mock requesting member lookup
        mocks["get_value"] = patch("frappe.db.get_value", return_value=requesting_member)

        # Mock chapter with board access
        mock_chapter = SuspensionTestFixtures.create_mock_chapter(has_board_access=has_board_access)

        # Mock settings
        mock_settings = SuspensionTestFixtures.create_mock_settings(national_chapter=national_chapter)

        # Mock get_doc to return appropriate objects
        def get_doc_side_effect(doctype, name):
            if doctype == "Chapter":
                return mock_chapter
            return MagicMock()

        mocks["get_doc"] = patch("frappe.get_doc", side_effect=get_doc_side_effect)
        mocks["get_single"] = patch("frappe.get_single", return_value=mock_settings)

        return mocks

    @staticmethod
    def setup_suspension_mocks(
        member_status="Active",
        user_enabled=True,
        has_user=True,
        user_email="test@example.com",
        teams_suspended=2,
    ):
        """Set up common suspension-related mocks"""
        mocks = {}

        # Mock member document
        mock_member = SuspensionTestFixtures.create_mock_member(
            status=member_status, has_user=has_user, user_email=user_email
        )

        # Mock user document
        mock_user = SuspensionTestFixtures.create_mock_user(email=user_email, enabled=user_enabled)

        # Mock get_doc to return appropriate objects
        def get_doc_side_effect(doctype, name):
            if doctype == "Member":
                return mock_member
            elif doctype == "User":
                return mock_user
            return MagicMock()

        mocks["get_doc"] = patch("frappe.get_doc", side_effect=get_doc_side_effect)
        mocks["get_value"] = patch("frappe.db.get_value", return_value=user_email if has_user else None)
        mocks["exists"] = patch("frappe.db.exists", return_value=has_user)
        mocks["suspend_teams"] = patch(
            "verenigingen.utils.termination_integration.suspend_team_memberships_safe",
            return_value=teams_suspended,
        )

        mocks["member"] = mock_member
        mocks["user"] = mock_user

        return mocks

    @staticmethod
    def assert_suspension_success(test_case, result, expected_actions=None):
        """Assert that a suspension result indicates success"""
        test_case.assertTrue(result["success"])
        test_case.assertTrue(result.get("member_suspended", False))

        if expected_actions:
            for action in expected_actions:
                test_case.assertIn(action, result.get("actions_taken", []))

    @staticmethod
    def assert_suspension_failure(test_case, result, expected_error=None):
        """Assert that a suspension result indicates failure"""
        test_case.assertFalse(result["success"])

        if expected_error:
            test_case.assertIn(expected_error, result.get("error", ""))

    @staticmethod
    def assert_permission_granted(test_case, permission_result):
        """Assert that permission was granted"""
        test_case.assertTrue(permission_result)

    @staticmethod
    def assert_permission_denied(test_case, permission_result):
        """Assert that permission was denied"""
        test_case.assertFalse(permission_result)


class SuspensionTestBase(unittest.TestCase):
    """Base test case for suspension tests with common setup"""

    def setUp(self):
        """Set up common test data"""
        self.fixtures = SuspensionTestFixtures()
        self.utilities = SuspensionTestUtilities()

        # Common test data
        self.test_member_name = "TEST-MEMBER-001"
        self.test_user_email = "test@example.com"
        self.test_suspension_reason = "Test suspension"
        self.test_unsuspension_reason = "Test unsuspension"
        self.test_chapter = "TEST-CHAPTER-001"
        self.test_requesting_member = "TEST-REQUESTING-MEMBER"
        self.national_chapter = "NATIONAL-CHAPTER"

    def tearDown(self):
        """Clean up after tests"""

    def create_mock_member(self, **kwargs):
        """Create a mock member with test defaults"""
        defaults = {
            "member_id": self.test_member_name,
            "user_email": self.test_user_email,
            "chapter": self.test_chapter,
        }
        defaults.update(kwargs)
        return self.fixtures.create_mock_member(**defaults)

    def assert_suspension_success(self, result, expected_actions=None):
        """Assert suspension success using utilities"""
        return self.utilities.assert_suspension_success(self, result, expected_actions)

    def assert_suspension_failure(self, result, expected_error=None):
        """Assert suspension failure using utilities"""
        return self.utilities.assert_suspension_failure(self, result, expected_error)


if __name__ == "__main__":
    # This file contains fixtures and utilities, not tests to run
    print("Suspension test fixtures and utilities loaded successfully")
    print("Available fixtures:")
    print("- SuspensionTestFixtures: Mock data creation")
    print("- SuspensionTestUtilities: Test helper functions")
    print("- SuspensionTestBase: Base test case class")
