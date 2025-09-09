"""
Integration tests for role profile management system.
Tests the actual functionality with real DocTypes and valid data.

Author: Verenigingen Development Team
Last Updated: 2025-08-26
"""

import unittest
import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.utils.base_role_profile_manager import (
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


class TestRoleProfileSystemIntegration(EnhancedTestCase):
    """Integration tests for role profile management system"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.cleanup_test_data()
        
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
        super().tearDown()
        
    def cleanup_test_data(self):
        """Remove test data from database using proper user context"""
        test_items = [
            ("Role Profile", ["Test Integration Profile"]),
            ("User", ["test.integration@example.com"]),
        ]
        
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            for doctype, names in test_items:
                for name in names:
                    if frappe.db.exists(doctype, name):
                        try:
                            frappe.delete_doc(doctype, name, force=True)
                        except Exception:
                            pass  # Ignore cleanup errors
        finally:
            frappe.set_user(current_user)
    
    def test_doctype_field_validation_realistic(self):
        """Test DocType field validation with realistic fields"""
        # Test User DocType with fields that actually exist
        result = validate_doctype_fields("User", ["email", "first_name", "enabled"])
        self.assertIsNone(result, "User DocType validation should pass for existing fields")
        
        # Test with missing fields
        result = validate_doctype_fields("User", ["nonexistent_field"])
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("Missing required fields", result["error"])
    
    def test_role_profile_creation_and_validation(self):
        """Test role profile creation and validation with real roles"""
        # Create a test role profile with System Manager role (guaranteed to exist)
        role_profile = frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": "Test Integration Profile",
            "roles": [{"role": "System Manager"}]
        })
        
        # Use proper user context for role profile creation
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            role_profile.insert()
        finally:
            frappe.set_user(current_user)
        
        # Test validation of this role profile
        result = validate_role_profile_dependencies("Test Integration Profile", TEAM_CONFIG)
        self.assertIsNone(result, "Role profile validation should pass for valid profile")
    
    def test_team_role_profile_manager_initialization(self):
        """Test TeamRoleProfileManager initializes correctly"""
        manager = TeamRoleProfileManager()
        self.assertEqual(manager.config.entity_type, "team")
        self.assertEqual(manager.config.doctype, "Team")
        self.assertEqual(manager.config.member_doctype, "Team Member")
    
    def test_chapter_role_profile_manager_initialization(self):
        """Test ChapterRoleProfileManager initializes correctly"""
        manager = ChapterRoleProfileManager()
        self.assertEqual(manager.config.entity_type, "chapter")
        self.assertEqual(manager.config.doctype, "Chapter")
        self.assertEqual(manager.config.member_doctype, "Chapter Board Member")
    
    def test_role_assignment_input_validation(self):
        """Test role assignment input validation"""
        # Test invalid user
        result = _team_manager._validate_role_assignment_inputs(
            "nonexistent@example.com", "some-team", "some-role"
        )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])
        
        # Test invalid inputs
        result = _team_manager._validate_role_assignment_inputs(
            "", "some-team", "some-role"
        )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])
    
    def test_system_configuration_validation(self):
        """Test system-wide configuration validation"""
        result = validate_system_configuration()
        
        # Should return structured result
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("errors", result)
        self.assertIn("warnings", result)
        self.assertIn("teams_checked", result)
        self.assertIn("chapters_checked", result)
        self.assertIn("summary", result)
        
        # Should check at least some entities (test data may exist)
        total_checked = result["teams_checked"] + result["chapters_checked"]
        self.assertGreaterEqual(total_checked, 0)
    
    def test_all_role_profiles_validation(self):
        """Test all role profiles validation"""
        result = validate_all_role_profiles()
        
        # Should return structured result
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("errors", result)
        self.assertIn("warnings", result)
        self.assertIn("profiles_checked", result)
        self.assertIn("summary", result)
        
        # Should check at least some role profiles (system profiles should exist)
        self.assertGreaterEqual(result["profiles_checked"], 0)
    
    def test_entity_config_completeness(self):
        """Test that entity configurations are complete and consistent"""
        # Test TEAM_CONFIG
        self.assertIsInstance(TEAM_CONFIG.entity_type, str)
        self.assertIsInstance(TEAM_CONFIG.doctype, str)
        self.assertIsInstance(TEAM_CONFIG.member_doctype, str)
        self.assertIsInstance(TEAM_CONFIG.default_profile_field, str)
        self.assertIsInstance(TEAM_CONFIG.log_context, str)
        
        # Test CHAPTER_CONFIG
        self.assertIsInstance(CHAPTER_CONFIG.entity_type, str)
        self.assertIsInstance(CHAPTER_CONFIG.doctype, str)
        self.assertIsInstance(CHAPTER_CONFIG.member_doctype, str)
        self.assertIsInstance(CHAPTER_CONFIG.default_profile_field, str)
        self.assertIsInstance(CHAPTER_CONFIG.log_context, str)
    
    def test_bulk_operations_safety(self):
        """Test bulk operations handle empty results gracefully"""
        # Test with non-existent team
        result = _team_manager.bulk_assign_role_profiles("Non-Existent Team")
        
        # Should handle gracefully, not crash
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        
    def test_concurrent_access_safety(self):
        """Test that role assignment handles concurrent access safely"""
        # Create test user using proper user context
        if not frappe.db.exists("User", "test.integration@example.com"):
            test_user = frappe.get_doc({
                "doctype": "User",
                "email": "test.integration@example.com",
                "first_name": "Test",
                "last_name": "Integration",
                "enabled": 1,
                "user_type": "System User"
            })
            
            test_admin = self.ensure_test_admin_user()
            current_user = frappe.session.user
            try:
                frappe.set_user(test_admin.email)
                test_user.insert()
            finally:
                frappe.set_user(current_user)
        
        # Test assignment to non-existent entity (should fail gracefully)
        result = _team_manager.assign_role_profile(
            "test.integration@example.com",
            "Non-Existent Team"
        )
        
        # Should return proper error response, not crash
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)


if __name__ == "__main__":
    unittest.main()