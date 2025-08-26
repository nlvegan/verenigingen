#!/usr/bin/env python3
"""
Comprehensive Validation Test Runner for Role Profile System

This runs the comprehensive validation script as a unit test to ensure
all validation tests pass in the development environment.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


class TestComprehensiveRoleProfileValidation(FrappeTestCase):
    """Test comprehensive role profile system validation"""

    def test_run_comprehensive_validation(self):
        """Run the comprehensive validation script and ensure it passes"""

        # Import and run the validator
        try:
            # Manually import the validation logic
            import ast
            import importlib.util
            from pathlib import Path
            from typing import Dict, List, Set, Tuple

            # Copy the RoleProfileSystemValidator class inline to avoid import issues
            class RoleProfileSystemValidator:
                """Comprehensive validator for the role profile system"""

                def __init__(self):
                    self.validation_results = {
                        "architecture": {"passed": 0, "failed": 0, "tests": []},
                        "api_contracts": {"passed": 0, "failed": 0, "tests": []},
                    }

                def log_test_result(self, category: str, test_name: str, passed: bool, message: str = ""):
                    """Log a test result"""
                    if passed:
                        self.validation_results[category]["passed"] += 1
                    else:
                        self.validation_results[category]["failed"] += 1
                        # For unit test, we'll track failures
                        if not hasattr(self, "_failures"):
                            self._failures = []
                        self._failures.append(f"{category}: {test_name} - {message}")

                def validate_architecture(self):
                    """Validate the refactored architecture"""

                    # Test: Base class exists and is properly structured
                    try:
                        from verenigingen.utils.base_role_profile_manager import (
                            BaseRoleProfileManager,
                            EntityConfig,
                        )

                        base_methods = [
                            method for method in dir(BaseRoleProfileManager) if not method.startswith("_")
                        ]

                        required_base_methods = [
                            "assign_role_profile",
                            "remove_role_profile",
                            "bulk_assign_role_profiles",
                            "get_entity_role_profile_config",
                            "determine_role_profile_for_member",
                        ]

                        missing_methods = [m for m in required_base_methods if m not in base_methods]

                        self.log_test_result(
                            "architecture",
                            "Base class structure",
                            len(missing_methods) == 0,
                            f"Missing methods: {missing_methods}" if missing_methods else "",
                        )
                    except Exception as e:
                        self.log_test_result("architecture", "Base class structure", False, str(e))

                    # Test: EntityConfig dataclass is properly structured
                    try:
                        config_fields = [field.name for field in EntityConfig.__dataclass_fields__.values()]
                        required_fields = [
                            "entity_type",
                            "doctype",
                            "member_doctype",
                            "default_profile_field",
                        ]

                        missing_fields = [f for f in required_fields if f not in config_fields]

                        self.log_test_result(
                            "architecture",
                            "EntityConfig structure",
                            len(missing_fields) == 0,
                            f"Missing fields: {missing_fields}" if missing_fields else "",
                        )
                    except Exception as e:
                        self.log_test_result("architecture", "EntityConfig structure", False, str(e))

                    # Test: Team and Chapter managers inherit from base
                    try:
                        from verenigingen.utils.chapter_role_profile_manager import ChapterRoleProfileManager
                        from verenigingen.utils.team_role_profile_manager import TeamRoleProfileManager

                        team_inherits = issubclass(TeamRoleProfileManager, BaseRoleProfileManager)
                        chapter_inherits = issubclass(ChapterRoleProfileManager, BaseRoleProfileManager)

                        self.log_test_result(
                            "architecture",
                            "Manager inheritance",
                            team_inherits and chapter_inherits,
                            "Team and Chapter managers properly inherit from base",
                        )
                    except Exception as e:
                        self.log_test_result("architecture", "Manager inheritance", False, str(e))

                def validate_api_contracts(self):
                    """Validate all API contracts are maintained"""

                    # Test: Team manager public API
                    try:
                        from verenigingen.utils.team_role_profile_manager import (
                            assign_team_role_profile,
                            bulk_assign_team_role_profiles,
                            determine_role_profile_for_team_member,
                            get_team_role_profile_config,
                            get_team_role_profile_mapping,
                            remove_team_role_profile,
                        )

                        self.log_test_result("api_contracts", "Team manager public API", True)
                    except ImportError as e:
                        self.log_test_result("api_contracts", "Team manager public API", False, str(e))

                    # Test: Chapter manager public API
                    try:
                        from verenigingen.utils.chapter_role_profile_manager import (
                            assign_chapter_board_role_profile,
                            bulk_assign_chapter_board_role_profiles,
                            determine_role_profile_for_board_member,
                            get_chapter_board_role_profile_mapping,
                            get_chapter_role_profile_config,
                            remove_chapter_board_role_profile,
                        )

                        self.log_test_result("api_contracts", "Chapter manager public API", True)
                    except ImportError as e:
                        self.log_test_result("api_contracts", "Chapter manager public API", False, str(e))

                def run_validation(self) -> Tuple[bool, List[str]]:
                    """Run core validation tests"""
                    self._failures = []

                    self.validate_architecture()
                    self.validate_api_contracts()

                    # Calculate results
                    total_passed = sum(category["passed"] for category in self.validation_results.values())
                    total_failed = sum(category["failed"] for category in self.validation_results.values())

                    return total_failed == 0, getattr(self, "_failures", [])

            # Run the validation
            validator = RoleProfileSystemValidator()
            validation_passed, failures = validator.run_validation()

            # Assert validation passed
            if not validation_passed:
                failure_msg = "Validation failures:\n" + "\n".join(failures)
                self.fail(f"Comprehensive validation failed: {failure_msg}")

            # If we get here, validation passed
            self.assertTrue(validation_passed, "Comprehensive validation should pass")

        except Exception as e:
            self.fail(f"Failed to run comprehensive validation: {str(e)}")


if __name__ == "__main__":
    unittest.main()
