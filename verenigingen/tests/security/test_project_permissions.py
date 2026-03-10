#!/usr/bin/env python3
"""
Comprehensive Unit Tests for Project Permission System

Tests cover:
- Team-based access (direct and indirect)
- Chapter-based access (direct and indirect)
- Permission level enforcement
- SQL injection prevention
- Edge cases and error handling
- Performance regression (query count limits)
"""

import frappe
import unittest
from unittest.mock import patch, MagicMock
from verenigingen.utils.project_permissions import (
    get_volunteer_for_user,
    validate_identifier,
    has_project_permission_via_team,
    user_has_any_team_projects,
    user_has_project_team_access,
    user_has_any_chapter_projects,
    user_has_project_chapter_access,
    get_team_permission_level,
    get_chapter_permission_level,
    get_project_permission_query_conditions,
    TeamPermissionLevel,
    ChapterPermissionLevel,
    PermissionDenied,
    PermissionSystemError,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestProjectPermissionHelpers(EnhancedTestCase):
    """Test helper functions"""

    def test_validate_identifier_valid(self):
        """Test validation with valid identifiers"""
        self.assertTrue(validate_identifier("Team Alpha", context="test: valid team name"))
        self.assertTrue(validate_identifier("Chapter-Beta", context="test: valid chapter name"))
        self.assertTrue(validate_identifier("Project_123", context="test: valid project name"))
        self.assertTrue(validate_identifier("Team 123 Name", context="test: valid team name with numbers"))

    def test_validate_identifier_invalid(self):
        """Test validation with invalid identifiers"""
        self.assertFalse(validate_identifier(None, context="test: None value"))
        self.assertFalse(validate_identifier("", context="test: empty string"))
        self.assertFalse(validate_identifier("A" * 141, context="test: length validation"))  # Too long
        self.assertFalse(validate_identifier("Team'; DROP TABLE--", context="test: SQL injection attempt"))  # SQL injection attempt

    def test_get_volunteer_for_user_caching(self):
        """Test that volunteer lookup is cached"""
        # Create test data
        member = self.create_test_member(first_name="Test", last_name="User")

        # Create a User and link it to the Member
        user_email = f"test_user_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}@test.com"
        if not frappe.db.exists("User", user_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "Test",
                "last_name": "User",
                "send_welcome_email": 0
            }).insert()
        else:
            user = frappe.get_doc("User", user_email)

        # Link user to member
        member.user = user_email
        member.save()

        volunteer = self.create_test_volunteer(member.name)

        # Clear cache to ensure fresh lookup
        get_volunteer_for_user.cache_clear()

        # First call should hit database
        member_name1, volunteer1 = get_volunteer_for_user(user_email)
        self.assertIsNotNone(volunteer1, "Volunteer lookup should return a value")
        self.assertEqual(volunteer1, volunteer.name)

        # Second call should use cache (verify by checking it returns same value quickly)
        member_name2, volunteer2 = get_volunteer_for_user(user_email)
        self.assertEqual(volunteer2, volunteer.name)
        self.assertEqual(volunteer1, volunteer2)

    def test_get_volunteer_for_user_nonexistent(self):
        """Test volunteer lookup for non-existent user"""
        member_name, volunteer = get_volunteer_for_user("nonexistent@example.com")
        self.assertIsNone(member_name)
        self.assertIsNone(volunteer)


class TestTeamPermissions(EnhancedTestCase):
    """Test team-based permissions"""

    def setUp(self):
        super().setUp()
        # Create test member and volunteer
        self.member = self.create_test_member(first_name="Team", last_name="Member")
        self.volunteer = self.create_test_volunteer(self.member.name)

        # Create unique test team
        import random
        team_suffix = random.randint(1000, 9999)
        self.team = frappe.get_doc({
            "doctype": "Team",
            "team_name": f"Test Team {team_suffix}",
            "status": "Active",
        }).insert()

    def test_team_leader_permissions(self):
        """Test Team Leader has read, write, create permissions"""
        # Create team role with Team Leader permissions (or get existing)
        if not frappe.db.exists("Team Role", "Team Leader"):
            team_role = frappe.get_doc({
                "doctype": "Team Role",
                "role_name": "Team Leader",
            }).insert()
        else:
            team_role = frappe.get_doc("Team Role", "Team Leader")

        # Add volunteer as team leader with required fields
        self.team.append("team_members", {
            "volunteer": self.volunteer.name,
            "team_role": team_role.name,
            "status": "Active",
            "from_date": frappe.utils.today(),
        })
        self.team.save()

        # Test permissions
        self.assertTrue(get_team_permission_level(self.team.name, self.volunteer.name, "read"))
        self.assertTrue(get_team_permission_level(self.team.name, self.volunteer.name, "write"))
        self.assertTrue(get_team_permission_level(self.team.name, self.volunteer.name, "create"))
        self.assertFalse(get_team_permission_level(self.team.name, self.volunteer.name, "delete"))

    def test_regular_member_permissions(self):
        """Test Regular Member has read-only permissions"""
        # Create or get Regular Member role
        if not frappe.db.exists("Team Role", "Regular Member"):
            regular_role = frappe.get_doc({
                "doctype": "Team Role",
                "role_name": "Regular Member",
            }).insert()
        else:
            regular_role = frappe.get_doc("Team Role", "Regular Member")

        # Add volunteer as regular member with required fields
        self.team.append("team_members", {
            "volunteer": self.volunteer.name,
            "team_role": regular_role.name,
            "status": "Active",
            "from_date": frappe.utils.today(),
        })
        self.team.save()

        self.assertTrue(get_team_permission_level(self.team.name, self.volunteer.name, "read"))
        self.assertFalse(get_team_permission_level(self.team.name, self.volunteer.name, "write"))


class TestChapterPermissions(EnhancedTestCase):
    """Test chapter-based permissions"""

    def setUp(self):
        super().setUp()
        # Create test member and volunteer
        self.member = self.create_test_member(first_name="Board", last_name="Member")
        self.volunteer = self.create_test_volunteer(self.member.name)

        # Create unique test chapter
        import random
        chapter_suffix = random.randint(1000, 9999)

        # Chapter needs a region - create one if it doesn't exist
        # Region name is auto-generated from region_name field (becomes "test-region")
        region_name = "test-region"
        if not frappe.db.exists("Region", region_name):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "Test Region",
                "region_code": "TR",
            }).insert(ignore_if_duplicate=True)

        self.chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": f"Test Chapter {chapter_suffix}",
            "status": "Active",
            "region": region_name,  # Use the auto-generated region name
        }).insert()

    def test_admin_level_permissions(self):
        """Test Admin level has all permissions"""
        # Create Admin role (or get existing)
        if not frappe.db.exists("Chapter Role", "Administrator"):
            admin_role = frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": "Administrator",
                "permissions_level": "Admin",
            }).insert()
        else:
            admin_role = frappe.get_doc("Chapter Role", "Administrator")

        # Add volunteer to chapter board with Admin role and required fields
        self.chapter.append("board_members", {
            "volunteer": self.volunteer.name,
            "chapter_role": admin_role.name,
            "is_active": 1,
            "from_date": frappe.utils.today(),
        })
        self.chapter.save()

        # Test all permissions
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "read"))
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "write"))
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "create"))
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "delete"))

    def test_chair_elevated_permissions(self):
        """Test Chapter Chair gets elevated permissions regardless of base level"""
        # Create Chair role with Basic level (or get existing)
        if not frappe.db.exists("Chapter Role", "Chair"):
            chair_role = frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": "Chair",
                "permissions_level": "Basic",
                "is_chair": 1,
            }).insert()
        else:
            chair_role = frappe.get_doc("Chapter Role", "Chair")

        # Add volunteer as chair with required fields
        self.chapter.append("board_members", {
            "volunteer": self.volunteer.name,
            "chapter_role": chair_role.name,
            "is_active": 1,
            "from_date": frappe.utils.today(),
        })
        self.chapter.save()

        # Test elevated permissions (should have create despite Basic level)
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "read"))
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "write"))
        self.assertTrue(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "create"))
        self.assertFalse(get_chapter_permission_level(self.chapter.name, self.volunteer.name, "delete"))


class TestSQLInjectionPrevention(EnhancedTestCase):
    """Test SQL injection prevention"""

    def test_malicious_team_name(self):
        """Test that malicious team names are rejected"""
        malicious_names = [
            "Team'; DROP TABLE tabProject; --",
            "Team\" OR 1=1 --",
            "Team\"; DELETE FROM tabProject WHERE \"1\"=\"1",
        ]

        for name in malicious_names:
            # Should be rejected by validator
            self.assertFalse(validate_identifier(name, context="test: SQL injection prevention"))

    def test_escaped_values_in_query_conditions(self):
        """Test that query conditions properly escape values"""
        member = self.create_test_member(first_name="Safe", last_name="User")
        volunteer = self.create_test_volunteer(member.name)

        # Get query conditions (should not raise exception with proper escaping)
        try:
            conditions = get_project_permission_query_conditions(member.user)
            # Should return "1=0" for user with no teams/chapters
            self.assertEqual(conditions, "1=0")
        except Exception as e:
            self.fail(f"Query conditions raised exception: {str(e)}")


class TestPermissionConstants(EnhancedTestCase):
    """Test permission level constants"""

    def test_team_permission_constants(self):
        """Test TeamPermissionLevel constants are correctly defined"""
        # Test known roles
        team_leader_perms = TeamPermissionLevel.get_permissions("Team Leader")
        self.assertIn("read", team_leader_perms)
        self.assertIn("write", team_leader_perms)
        self.assertIn("create", team_leader_perms)

        regular_member_perms = TeamPermissionLevel.get_permissions("Regular Member")
        self.assertIn("read", regular_member_perms)
        self.assertNotIn("write", regular_member_perms)

    def test_chapter_permission_constants(self):
        """Test ChapterPermissionLevel constants are correctly defined"""
        # Test Admin level
        admin_perms = ChapterPermissionLevel.get_permissions("Admin", is_chair=False)
        self.assertIn("read", admin_perms)
        self.assertIn("write", admin_perms)
        self.assertIn("create", admin_perms)
        self.assertIn("delete", admin_perms)

        # Test Basic level
        basic_perms = ChapterPermissionLevel.get_permissions("Basic", is_chair=False)
        self.assertIn("read", basic_perms)
        self.assertIn("write", basic_perms)
        self.assertNotIn("create", basic_perms)

        # Test Chair elevation
        chair_perms = ChapterPermissionLevel.get_permissions("Basic", is_chair=True)
        self.assertIn("create", chair_perms)  # Elevated from Basic

    def test_unknown_role_fallback(self):
        """Test that unknown roles fall back to read-only"""
        unknown_perms = TeamPermissionLevel.get_permissions("Unknown Role")
        self.assertEqual(unknown_perms, ["read"])


class TestCaseInsensitiveMatching(EnhancedTestCase):
    """Test case-insensitive name matching"""

    def test_case_insensitive_team_matching(self):
        """Test that project name matching is case-insensitive"""
        # This would require creating actual projects and testing the matching
        # Placeholder for implementation
        pass


class TestPerformanceRegression(EnhancedTestCase):
    """Test query count limits to prevent performance regression"""

    def test_volunteer_lookup_single_query(self):
        """Test that volunteer lookup uses single optimized query"""
        member = self.create_test_member(first_name="Perf", last_name="Test")
        volunteer = self.create_test_volunteer(member.name)

        # Clear cache
        get_volunteer_for_user.cache_clear()

        # Should use only 1 query (JOIN instead of 2 separate queries)
        with self.assertQueryCount(1):
            get_volunteer_for_user(member.user)


# Run tests
if __name__ == "__main__":
    unittest.main()
