"""
Comprehensive test suite for role profile management system.

Tests the BaseRoleProfileManager, TeamRoleProfileManager, and ChapterRoleProfileManager
classes with realistic scenarios and edge cases.

Author: Verenigingen Development Team
Last Updated: 2025-08-26
"""

# Unused import removed - using EnhancedTestCase
from unittest.mock import patch, MagicMock
from typing import Dict, List, Any

import frappe
# FrappeTestCase import removed - all classes use EnhancedTestCase
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

from verenigingen.utils.base_role_profile_manager import (
    BaseRoleProfileManager,
    EntityConfig,
    validate_doctype_fields,
    validate_entity_configuration,
    validate_role_profile_dependencies,
    validate_system_configuration,
    validate_all_role_profiles,
    ERROR_CODES
)
from verenigingen.utils.team_role_profile_manager import (
    TeamRoleProfileManager,
    TEAM_CONFIG,
    _team_manager
)
from verenigingen.utils.chapter_role_profile_manager import (
    ChapterRoleProfileManager,
    CHAPTER_CONFIG,
    _chapter_manager
)


class TestValidationFunctions(EnhancedTestCase):
    """Test standalone validation functions"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        # Clean up any existing test data
        self.cleanup_test_data()
        
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
        super().tearDown()
        
    def cleanup_test_data(self):
        """Remove test data from database"""
        # Delete test role profiles
        test_profiles = ["Test Role Profile", "Test Empty Profile", "Test Invalid Profile"]
        for profile in test_profiles:
            if DocumentExistenceValidator.check_document_exists("Role Profile", profile):
                # EnhancedTestCase handles cleanup automatically
        
        # Delete test teams
        test_teams = ["Test Team", "Test Team No Config", "Test Team Invalid"]
        for team in test_teams:
            if DocumentExistenceValidator.check_document_exists("Team", team):
                # EnhancedTestCase handles cleanup automatically
    
    def test_validate_doctype_fields_success(self):
        """Test successful DocType field validation"""
        # Test with User DocType (known to exist) - use actual fields not virtual 'name'
        result = validate_doctype_fields("User", ["email", "enabled", "first_name"])
        self.assertIsNone(result)
    
    def test_validate_doctype_fields_missing_fields(self):
        """Test DocType field validation with missing fields"""
        result = validate_doctype_fields("User", ["name", "nonexistent_field", "another_missing"])
        
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Missing required fields", result["error"])
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
    
    def test_validate_doctype_fields_invalid_doctype(self):
        """Test DocType field validation with invalid DocType"""
        result = validate_doctype_fields("NonexistentDocType", ["field1"])
        
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Error validating", result["error"])
        self.assertEqual(result["error_code"], ERROR_CODES["SYSTEM_ERROR"])
    
    def test_validate_role_profile_dependencies_success(self):
        """Test successful role profile dependency validation"""
        # Create test role profile with valid roles
        role_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Role Profile",
            "roles": [
                {"role": "System Manager"},
                {"role": "All"}
            ]
        })
        role_profile.insert()
        
        result = validate_role_profile_dependencies("Test Role Profile", TEAM_CONFIG)
        self.assertIsNone(result)
    
    def test_validate_role_profile_dependencies_nonexistent(self):
        """Test role profile dependency validation with nonexistent profile"""
        result = validate_role_profile_dependencies("Nonexistent Profile", TEAM_CONFIG)
        
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"])
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])
    
    def test_validate_role_profile_dependencies_empty_roles(self):
        """Test role profile dependency validation with empty roles"""
        # Create role profile with no roles
        role_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Empty Profile"
        })
        role_profile.insert()
        
        result = validate_role_profile_dependencies("Test Empty Profile", TEAM_CONFIG)
        
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("no roles configured", result["error"])
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])


class TestTeamRoleProfileManager(EnhancedTestCase):
    """Test TeamRoleProfileManager functionality"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.manager = _team_manager
        self.cleanup_test_data()
        self.create_test_data()
    
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
        super().tearDown()
    
    def cleanup_test_data(self):
        """Remove test data from database"""
        # Delete test data
        test_items = [
            ("Team", ["Test Team Valid", "Test Team No Config", "Test Team Role Specific"]),
            ("Role Profile", ["Test Team Profile", "Test Chair Profile", "Test Member Profile"]),
            ("User", ["test.volunteer@example.com"]),
            ("Volunteer", ["Test Volunteer"]),
            ("Member", ["Test Member"])
        ]
        
        for doctype, names in test_items:
            for name in names:
                if DocumentExistenceValidator.check_document_exists(doctype, name):
                    # EnhancedTestCase handles cleanup automatically
    
    def create_test_data(self):
        """Create test data for team role profile testing"""
        # Create test role profiles with correct role names
        test_role_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Team Profile",
            "roles": [{"role": "System Manager"}]
        })
        test_role_profile.insert()
        
        chair_profile = frappe.get_doc({
            "doctype": "Role Profile", 
            "role_profile": "Test Chair Profile",
            "roles": [{"role": "System Manager"}, {"role": "All"}]
        })
        chair_profile.insert()
        
        member_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Member Profile", 
            "roles": [{"role": "All"}]
        })
        member_profile.insert()
        
        # Create test teams
        team_valid = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team Valid",
            "description": "Test team with valid role profile config", 
            "status": "Active",
            "default_role_profile": "Test Team Profile",
            "enable_role_specific_profiles": 0
        })
        team_valid.insert()
        
        team_no_config = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team No Config",
            "description": "Test team with no role profile config",
            "status": "Active",
            "enable_role_specific_profiles": 0
        })
        team_no_config.insert()
        
        team_role_specific = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team Role Specific",
            "description": "Test team with role-specific profiles",
            "status": "Active",
            "enable_role_specific_profiles": 1,
            "role_specific_profiles": []
        })
        team_role_specific.insert()
        
        # Create test user/member/volunteer
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": "test.volunteer@example.com",
            "first_name": "Test",
            "last_name": "Volunteer",
            "enabled": 1,
            "user_type": "System User"
        })
        test_user.insert()
        
        test_member = frappe.get_doc({
            "doctype": "Member",
            "name": "Test Member",
            "first_name": "Test",
            "last_name": "Volunteer",
            "email": "test.volunteer@example.com",
            "user": "test.volunteer@example.com",
            "status": "Active"
        })
        test_member.insert()
        
        test_volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "name": "Test Volunteer",
            "member": "Test Member"
        })
        test_volunteer.insert()
    
    def test_get_entity_role_profile_config_valid(self):
        """Test getting role profile config for valid team"""
        config = self.manager.get_entity_role_profile_config("Test Team Valid")
        
        self.assertEqual(config["default_profile"], "Test Team Profile")
        self.assertFalse(config["enable_role_specific"])
        self.assertEqual(config["role_specific_profiles"], {})
    
    def test_get_entity_role_profile_config_no_config(self):
        """Test getting role profile config for team with no config"""
        config = self.manager.get_entity_role_profile_config("Test Team No Config")
        
        self.assertIsNone(config["default_profile"])
        self.assertFalse(config["enable_role_specific"])
        self.assertEqual(config["role_specific_profiles"], {})
    
    def test_determine_role_profile_for_member_default(self):
        """Test determining role profile with default config"""
        role_profile = self.manager.determine_role_profile_for_member("Test Team Valid")
        self.assertEqual(role_profile, "Test Team Profile")
    
    def test_determine_role_profile_for_member_no_config(self):
        """Test determining role profile with no config"""
        role_profile = self.manager.determine_role_profile_for_member("Test Team No Config")
        self.assertIsNone(role_profile)
    
    def test_assign_role_profile_success(self):
        """Test successful role profile assignment"""
        result = self.manager.assign_role_profile(
            "test.volunteer@example.com", 
            "Test Team Valid"
        )
        
        self.assertTrue(result["success"])
        self.assertIn("assigned", result["message"])
        self.assertEqual(result["role_profile"], "Test Team Profile")
        
        # Verify user has the role profile
        user_doc = frappe.get_doc("User", "test.volunteer@example.com")
        role_profiles = [rp.role_profile for rp in user_doc.role_profiles or []]
        self.assertIn("Test Team Profile", role_profiles)
    
    def test_assign_role_profile_no_config(self):
        """Test role profile assignment with no config"""
        result = self.manager.assign_role_profile(
            "test.volunteer@example.com",
            "Test Team No Config"
        )
        
        self.assertTrue(result["success"])  # Should succeed with no action
        self.assertEqual(result["action"], "no_config")
        self.assertIn("No role profile configured", result["message"])
    
    def test_assign_role_profile_invalid_user(self):
        """Test role profile assignment with invalid user"""
        result = self.manager.assign_role_profile(
            "nonexistent@example.com",
            "Test Team Valid"
        )
        
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])
        self.assertIn("does not exist", result["error"])
    
    def test_remove_role_profile_success(self):
        """Test successful role profile removal"""
        # First assign a role profile
        self.manager.assign_role_profile("test.volunteer@example.com", "Test Team Valid")
        
        # Then remove it
        result = self.manager.remove_role_profile(
            "test.volunteer@example.com",
            "Test Team Valid"
        )
        
        self.assertTrue(result["success"])
        self.assertIn("removed", result["message"])
        
        # Verify user no longer has the role profile
        user_doc = frappe.get_doc("User", "test.volunteer@example.com")
        role_profiles = [rp.role_profile for rp in user_doc.role_profiles or []]
        self.assertNotIn("Test Team Profile", role_profiles)
    
    def test_bulk_assign_role_profiles(self):
        """Test bulk role profile assignment"""
        # Add test volunteer to team
        team_member = frappe.get_doc({
            "doctype": "Team Member",
            "parent": "Test Team Valid",
            "volunteer": "Test Volunteer",
            "team_role": "Member",
            "status": "Active"
        })
        team_member.insert()
        
        result = self.manager.bulk_assign_role_profiles("Test Team Valid")
        
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["assigned"], 1)
        self.assertEqual(result["skipped"], 0)


class TestChapterRoleProfileManager(EnhancedTestCase):
    """Test ChapterRoleProfileManager functionality"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.manager = _chapter_manager
        self.cleanup_test_data()
        self.create_test_data()
    
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
        super().tearDown()
    
    def cleanup_test_data(self):
        """Remove test data from database"""
        test_items = [
            ("Chapter", ["Test Chapter Valid", "Test Chapter No Config"]),
            ("Role Profile", ["Test Board Profile"]),
            ("User", ["test.board@example.com"]),
            ("Member", ["Test Board Member"])
        ]
        
        for doctype, names in test_items:
            for name in names:
                if DocumentExistenceValidator.check_document_exists(doctype, name):
                    # EnhancedTestCase handles cleanup automatically
    
    def create_test_data(self):
        """Create test data for chapter role profile testing"""
        # Create test role profile
        board_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Board Profile",
            "roles": [{"role": "System Manager"}]
        })
        board_profile.insert()
        
        # Create test chapters
        chapter_valid = frappe.get_doc({
            "doctype": "Chapter",
            "name": "Test Chapter Valid",  # Explicit name for prompt autoname
            "status": "Active",
            "default_board_role_profile": "Test Board Profile",
            "enable_board_role_specific_profiles": 0
        })
        chapter_valid.insert()
        
        chapter_no_config = frappe.get_doc({
            "doctype": "Chapter",
            "name": "Test Chapter No Config",  # Explicit name for prompt autoname
            "status": "Active",
            "enable_board_role_specific_profiles": 0
        })
        chapter_no_config.insert()
        
        # Create test user/member
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": "test.board@example.com",
            "first_name": "Test",
            "last_name": "Board",
            "enabled": 1,
            "user_type": "System User"
        })
        test_user.insert()
        
        test_member = frappe.get_doc({
            "doctype": "Member",
            "name": "Test Board Member",
            "first_name": "Test",
            "last_name": "Board",
            "email": "test.board@example.com",
            "user": "test.board@example.com",
            "status": "Active"
        })
        test_member.insert()
    
    def test_get_chapter_role_profile_config_valid(self):
        """Test getting role profile config for valid chapter"""
        config = self.manager.get_entity_role_profile_config("Test Chapter Valid")
        
        self.assertEqual(config["default_profile"], "Test Board Profile")
        self.assertFalse(config["enable_role_specific"])
        self.assertEqual(config["role_specific_profiles"], {})
    
    def test_determine_role_profile_for_member_default(self):
        """Test determining role profile with default config"""
        role_profile = self.manager.determine_role_profile_for_member("Test Chapter Valid")
        self.assertEqual(role_profile, "Test Board Profile")
    
    def test_assign_chapter_board_role_profile_success(self):
        """Test successful chapter board role profile assignment"""
        result = self.manager.assign_role_profile(
            "test.board@example.com",
            "Test Chapter Valid"
        )
        
        self.assertTrue(result["success"])
        self.assertIn("assigned", result["message"])
        self.assertEqual(result["role_profile"], "Test Board Profile")
        
        # Verify user has the role profile
        user_doc = frappe.get_doc("User", "test.board@example.com")
        role_profiles = [rp.role_profile for rp in user_doc.role_profiles or []]
        self.assertIn("Test Board Profile", role_profiles)


class TestSystemValidation(EnhancedTestCase):
    """Test system-wide validation functions"""
    
    def test_validate_system_configuration(self):
        """Test system-wide configuration validation"""
        result = validate_system_configuration()
        
        # Should return a structured result
        self.assertIn("success", result)
        self.assertIn("errors", result)
        self.assertIn("warnings", result)
        self.assertIn("teams_checked", result)
        self.assertIn("chapters_checked", result)
        self.assertIn("summary", result)
        
        # Should check some teams and chapters (assuming test data exists)
        self.assertGreaterEqual(result["teams_checked"], 0)
        self.assertGreaterEqual(result["chapters_checked"], 0)
    
    def test_validate_all_role_profiles(self):
        """Test all role profiles validation"""
        result = validate_all_role_profiles()
        
        # Should return a structured result
        self.assertIn("success", result)
        self.assertIn("errors", result)
        self.assertIn("warnings", result)
        self.assertIn("profiles_checked", result)
        self.assertIn("summary", result)
        
        # Should check some role profiles (assuming system profiles exist)
        self.assertGreaterEqual(result["profiles_checked"], 0)


class TestBaseRoleProfileManagerAbstract(EnhancedTestCase):
    """Test BaseRoleProfileManager abstract behavior"""
    
    def test_cannot_instantiate_base_class_directly(self):
        """Test that BaseRoleProfileManager cannot be instantiated directly"""
        with self.assertRaises(TypeError):
            # Should fail because abstract methods aren't implemented
            BaseRoleProfileManager(TEAM_CONFIG)
    
    def test_entity_config_validation(self):
        """Test EntityConfig validation"""
        # Valid config should work
        valid_config = EntityConfig(
            entity_type="test",
            entity_label="Test",
            doctype="User",  # Known to exist
            member_doctype="User",
            role_doctype="Role",
            default_profile_field="name",  # Known to exist on User
            enable_specific_field="enabled",  # Known to exist on User
            specific_profiles_field=None,
            child_table_doctype="User Role",
            role_field_in_child="role",
            member_enabled_field="enabled",
            member_status_field=None,
            member_status_active_value=None,
            member_role_field="name",
            log_context="Test Context"
        )
        
        # This should work without throwing an exception
        # We'll create a simple concrete implementation just for testing
        class TestManager(BaseRoleProfileManager):
            def _user_still_in_other_entities(self, user, other_entities):
                return False
            def _get_bulk_members_data(self, entity_name):
                return []
            def _get_user_from_member_doc(self, doc):
                return None
        
        # This should not raise an exception
        manager = TestManager(valid_config)
        self.assertEqual(manager.config.entity_type, "test")


if __name__ == "__main__":
    unittest.main()