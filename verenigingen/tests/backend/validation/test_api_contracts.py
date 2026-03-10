#!/usr/bin/env python3
"""
API Contract Tests for Role Profile System

Tests that all API contracts are maintained and functionality works correctly.
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestRoleProfileAPIContracts(EnhancedTestCase):
    """Test role profile system API contracts"""

    def test_imports_work(self):
        """Test that all imports work correctly"""
        try:
            from verenigingen.utils.team_role_profile_manager import (
                _team_manager,
                TEAM_CONFIG,
                TeamRoleProfileManager
            )
            from verenigingen.utils.chapter_role_profile_manager import (
                _chapter_manager,
                CHAPTER_CONFIG,
                ChapterRoleProfileManager
            )
            from verenigingen.utils.base_role_profile_manager import (
                BaseRoleProfileManager,
                EntityConfig,
                validate_system_configuration,
                validate_all_role_profiles,
                ERROR_CODES
            )
            self.assertTrue(True, "All imports successful")
        except ImportError as e:
            self.fail(f"Import error: {e}")

    def test_manager_initialization(self):
        """Test that managers initialize correctly"""
        from verenigingen.utils.team_role_profile_manager import _team_manager, TEAM_CONFIG
        from verenigingen.services.chapter.chapter_role_profile_manager import _chapter_manager, CHAPTER_CONFIG
        
        # Test configurations exist and have expected values
        self.assertEqual(TEAM_CONFIG.entity_type, "team")
        self.assertEqual(TEAM_CONFIG.doctype, "Team")
        self.assertEqual(CHAPTER_CONFIG.entity_type, "chapter") 
        self.assertEqual(CHAPTER_CONFIG.doctype, "Chapter")
        
        # Test managers are instances of correct classes
        self.assertIsNotNone(_team_manager)
        self.assertIsNotNone(_chapter_manager)

    def test_api_methods_exist(self):
        """Test that required API methods exist and are callable"""
        from verenigingen.utils.team_role_profile_manager import _team_manager
        from verenigingen.services.chapter.chapter_role_profile_manager import _chapter_manager
        
        required_methods = [
            "assign_role_profile",
            "remove_role_profile", 
            "bulk_assign_role_profiles",
            "determine_role_profile_for_member",
            "get_entity_role_profile_config"
        ]
        
        for method_name in required_methods:
            # Test team manager
            self.assertTrue(hasattr(_team_manager, method_name),
                          f"Team manager missing method: {method_name}")
            self.assertTrue(callable(getattr(_team_manager, method_name)),
                          f"Team manager method not callable: {method_name}")
            
            # Test chapter manager  
            self.assertTrue(hasattr(_chapter_manager, method_name),
                          f"Chapter manager missing method: {method_name}")
            self.assertTrue(callable(getattr(_chapter_manager, method_name)),
                          f"Chapter manager method not callable: {method_name}")

    def test_validation_functions_exist(self):
        """Test that validation functions exist and are callable"""
        from verenigingen.utils.base_role_profile_manager import (
            validate_system_configuration,
            validate_all_role_profiles,
            validate_doctype_fields,
            validate_entity_configuration,
            validate_role_profile_dependencies
        )
        
        validation_functions = [
            validate_system_configuration,
            validate_all_role_profiles,
            validate_doctype_fields,
            validate_entity_configuration,
            validate_role_profile_dependencies
        ]
        
        for func in validation_functions:
            self.assertTrue(callable(func), f"Function not callable: {func.__name__}")

    def test_error_codes_defined(self):
        """Test that error codes are properly defined"""
        from verenigingen.utils.base_role_profile_manager import ERROR_CODES
        
        expected_codes = [
            "VALIDATION_ERROR", 
            "NOT_FOUND",
            "CONFIGURATION_ERROR",
            "SYSTEM_ERROR"
        ]
        
        for code in expected_codes:
            self.assertIn(code, ERROR_CODES, f"Missing error code: {code}")
            self.assertIsInstance(ERROR_CODES[code], str, f"Error code {code} not a string")

    def test_validation_functions_return_correct_format(self):
        """Test that validation functions return expected data structures"""
        from verenigingen.utils.base_role_profile_manager import (
            validate_system_configuration,
            validate_all_role_profiles
        )
        
        # Test system configuration validation
        try:
            result = validate_system_configuration()
            self.assertIsInstance(result, dict, "System validation should return dict")
            expected_keys = ["success", "errors", "warnings", "teams_checked", "chapters_checked", "summary"]
            for key in expected_keys:
                self.assertIn(key, result, f"Missing key in system validation: {key}")
        except Exception as e:
            self.fail(f"System validation failed: {e}")
        
        # Test role profile validation
        try:
            result = validate_all_role_profiles()
            self.assertIsInstance(result, dict, "Profile validation should return dict")
            expected_keys = ["success", "errors", "warnings", "profiles_checked", "summary"]
            for key in expected_keys:
                self.assertIn(key, result, f"Missing key in profile validation: {key}")
        except Exception as e:
            self.fail(f"Profile validation failed: {e}")

    def test_entity_config_structure(self):
        """Test that EntityConfig dataclass has expected structure"""
        from verenigingen.utils.base_role_profile_manager import EntityConfig
        from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG
        from verenigingen.utils.chapter_role_profile_manager import CHAPTER_CONFIG
        
        required_attrs = [
            "entity_type", "entity_label", "doctype", "member_doctype",
            "default_profile_field", "log_context"
        ]
        
        for config in [TEAM_CONFIG, CHAPTER_CONFIG]:
            for attr in required_attrs:
                self.assertTrue(hasattr(config, attr), 
                              f"Config missing attribute: {attr}")
                self.assertIsInstance(getattr(config, attr), str,
                                    f"Config attribute {attr} should be string")

    def test_manager_input_validation(self):
        """Test that managers properly validate inputs"""
        from verenigingen.utils.team_role_profile_manager import _team_manager
        
        # Test with empty/invalid inputs
        result = _team_manager.assign_role_profile("", "")
        self.assertIsInstance(result, dict, "Should return dict for invalid inputs")
        self.assertFalse(result.get("success", True), "Should fail for empty inputs")
        
        result = _team_manager.assign_role_profile(None, None)
        self.assertIsInstance(result, dict, "Should return dict for None inputs")
        self.assertFalse(result.get("success", True), "Should fail for None inputs")


if __name__ == "__main__":
    unittest.main()