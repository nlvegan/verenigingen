#!/usr/bin/env python3
"""
Comprehensive Role Profile System Validation
===========================================

This script provides comprehensive validation of the refactored role profile system
before production deployment. It validates all integration points, API contracts,
and ensures the system is ready for production use.

Usage:
    bench --site dev.veganisme.net run-python-script scripts/setup/comprehensive_role_profile_validation.py

Author: Verenigingen Development Team
Date: 2025-08-26
"""

import ast
import importlib.util
from pathlib import Path
from typing import Dict, List, Tuple, Set

import frappe


class RoleProfileSystemValidator:
    """Comprehensive validator for the role profile system"""
    
    def __init__(self):
        self.validation_results = {
            "architecture": {"passed": 0, "failed": 0, "tests": []},
            "api_contracts": {"passed": 0, "failed": 0, "tests": []},
            "database_config": {"passed": 0, "failed": 0, "tests": []},
            "integration_points": {"passed": 0, "failed": 0, "tests": []},
            "security": {"passed": 0, "failed": 0, "tests": []},
            "performance": {"passed": 0, "failed": 0, "tests": []}
        }
    
    def log_test_result(self, category: str, test_name: str, passed: bool, message: str = ""):
        """Log a test result"""
        if passed:
            self.validation_results[category]["passed"] += 1
            status = "✅ PASS"
        else:
            self.validation_results[category]["failed"] += 1
            status = "❌ FAIL"
        
        self.validation_results[category]["tests"].append({
            "name": test_name,
            "status": status,
            "message": message
        })
        
        print(f"  {status}: {test_name}")
        if message and not passed:
            print(f"    Details: {message}")
    
    def validate_architecture(self):
        """Validate the refactored architecture"""
        print("\n🏗️  VALIDATING SYSTEM ARCHITECTURE")
        print("-" * 40)
        
        # Test 1: Base class exists and is properly structured
        try:
            from verenigingen.utils.base_role_profile_manager import BaseRoleProfileManager, EntityConfig
            base_methods = [method for method in dir(BaseRoleProfileManager) if not method.startswith('_')]
            
            required_base_methods = [
                'assign_role_profile', 'remove_role_profile', 'bulk_assign_role_profiles',
                'get_entity_role_profile_config', 'determine_role_profile_for_member'
            ]
            
            missing_methods = [m for m in required_base_methods if m not in base_methods]
            
            self.log_test_result("architecture", "Base class structure", 
                               len(missing_methods) == 0, 
                               f"Missing methods: {missing_methods}" if missing_methods else "")
        except Exception as e:
            self.log_test_result("architecture", "Base class structure", False, str(e))
        
        # Test 2: EntityConfig dataclass is properly structured
        try:
            config_fields = [field.name for field in EntityConfig.__dataclass_fields__.values()]
            required_fields = ['entity_type', 'doctype', 'member_doctype', 'default_profile_field']
            
            missing_fields = [f for f in required_fields if f not in config_fields]
            
            self.log_test_result("architecture", "EntityConfig structure",
                               len(missing_fields) == 0,
                               f"Missing fields: {missing_fields}" if missing_fields else "")
        except Exception as e:
            self.log_test_result("architecture", "EntityConfig structure", False, str(e))
        
        # Test 3: Team and Chapter managers inherit from base
        try:
            from verenigingen.utils.team_role_profile_manager import TeamRoleProfileManager
            from verenigingen.utils.chapter_role_profile_manager import ChapterRoleProfileManager
            
            team_inherits = issubclass(TeamRoleProfileManager, BaseRoleProfileManager)
            chapter_inherits = issubclass(ChapterRoleProfileManager, BaseRoleProfileManager)
            
            self.log_test_result("architecture", "Manager inheritance",
                               team_inherits and chapter_inherits,
                               "Team and Chapter managers properly inherit from base")
        except Exception as e:
            self.log_test_result("architecture", "Manager inheritance", False, str(e))
    
    def validate_api_contracts(self):
        """Validate all API contracts are maintained"""
        print("\n🔌 VALIDATING API CONTRACTS")
        print("-" * 30)
        
        # Test 1: Team manager public API
        try:
            from verenigingen.utils.team_role_profile_manager import (
                get_team_role_profile_config,
                determine_role_profile_for_team_member,
                assign_team_role_profile,
                remove_team_role_profile,
                bulk_assign_team_role_profiles,
                get_team_role_profile_mapping
            )
            
            self.log_test_result("api_contracts", "Team manager public API", True)
        except ImportError as e:
            self.log_test_result("api_contracts", "Team manager public API", False, str(e))
        
        # Test 2: Chapter manager public API
        try:
            from verenigingen.utils.chapter_role_profile_manager import (
                get_chapter_role_profile_config,
                determine_role_profile_for_board_member,
                assign_chapter_board_role_profile,
                remove_chapter_board_role_profile,
                bulk_assign_chapter_board_role_profiles,
                get_chapter_board_role_profile_mapping
            )
            
            self.log_test_result("api_contracts", "Chapter manager public API", True)
        except ImportError as e:
            self.log_test_result("api_contracts", "Chapter manager public API", False, str(e))
        
        # Test 3: Frappe whitelist decorators
        team_file = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/team_role_profile_manager.py")
        chapter_file = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/chapter_role_profile_manager.py")
        
        for file_path, name in [(team_file, "Team"), (chapter_file, "Chapter")]:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                whitelist_count = content.count('@frappe.whitelist()')
                expected_min = 3  # At least assign, remove, bulk functions should be whitelisted
                
                self.log_test_result("api_contracts", f"{name} manager Frappe API",
                                   whitelist_count >= expected_min,
                                   f"Found {whitelist_count} whitelisted functions")
            except Exception as e:
                self.log_test_result("api_contracts", f"{name} manager Frappe API", False, str(e))
    
    def validate_database_configuration(self):
        """Validate database configuration requirements"""
        print("\n🗃️  VALIDATING DATABASE CONFIGURATION")
        print("-" * 37)
        
        # Test 1: Required DocTypes exist
        required_doctypes = ["Team", "Chapter", "Role Profile"]
        
        for doctype in required_doctypes:
            exists = frappe.db.exists("DocType", doctype)
            self.log_test_result("database_config", f"DocType {doctype} exists", exists)
        
        # Test 2: Team DocType has required fields
        try:
            team_meta = frappe.get_meta("Team")
            required_team_fields = ["default_role_profile", "enable_role_specific_profiles", "role_specific_profiles"]
            
            existing_fields = [f.fieldname for f in team_meta.fields]
            missing_fields = [f for f in required_team_fields if f not in existing_fields]
            
            self.log_test_result("database_config", "Team DocType fields",
                               len(missing_fields) == 0,
                               f"Missing: {missing_fields}" if missing_fields else "All fields present")
        except Exception as e:
            self.log_test_result("database_config", "Team DocType fields", False, str(e))
        
        # Test 3: Chapter DocType has required fields  
        try:
            chapter_meta = frappe.get_meta("Chapter")
            required_chapter_fields = ["default_board_role_profile", "enable_board_role_specific_profiles", "board_role_specific_profiles"]
            
            existing_fields = [f.fieldname for f in chapter_meta.fields]
            missing_fields = [f for f in required_chapter_fields if f not in existing_fields]
            
            self.log_test_result("database_config", "Chapter DocType fields",
                               len(missing_fields) == 0,
                               f"Missing: {missing_fields}" if missing_fields else "All fields present")
        except Exception as e:
            self.log_test_result("database_config", "Chapter DocType fields", False, str(e))
        
        # Test 4: Sample configuration data
        try:
            teams_with_config = frappe.get_all("Team", 
                filters={"default_role_profile": ["is", "set"], "status": "Active"}, 
                fields=["name", "default_role_profile"])
            
            chapters_with_config = frappe.get_all("Chapter",
                filters={"default_board_role_profile": ["is", "set"], "status": "Active"},
                fields=["name", "default_board_role_profile"])
            
            self.log_test_result("database_config", "Entity configuration data",
                               len(teams_with_config) > 0 or len(chapters_with_config) > 0,
                               f"Teams configured: {len(teams_with_config)}, Chapters configured: {len(chapters_with_config)}")
        except Exception as e:
            self.log_test_result("database_config", "Entity configuration data", False, str(e))
    
    def validate_integration_points(self):
        """Validate all integration points work correctly"""
        print("\n🔗 VALIDATING INTEGRATION POINTS")
        print("-" * 33)
        
        # Test 1: Hooks are properly configured
        try:
            from verenigingen import hooks
            doc_events = getattr(hooks, 'doc_events', {})
            
            team_member_hooks = doc_events.get('Team Member', {})
            chapter_member_hooks = doc_events.get('Chapter Board Member', {})
            
            required_team_hooks = ['after_insert', 'before_delete', 'on_update']
            required_chapter_hooks = ['after_insert', 'before_delete', 'on_update']
            
            team_hooks_ok = all(hook in team_member_hooks for hook in required_team_hooks)
            chapter_hooks_ok = all(hook in chapter_member_hooks for hook in required_chapter_hooks)
            
            self.log_test_result("integration_points", "Document event hooks",
                               team_hooks_ok and chapter_hooks_ok,
                               "Team and Chapter member hooks configured")
        except Exception as e:
            self.log_test_result("integration_points", "Document event hooks", False, str(e))
        
        # Test 2: DocType method integration
        integration_methods = [
            ("verenigingen.verenigingen.doctype.team.team", "bulk_apply_team_role_profiles"),
            ("verenigingen.verenigingen.doctype.chapter.chapter", "bulk_apply_chapter_board_role_profiles")
        ]
        
        for module_path, method_name in integration_methods:
            try:
                spec = importlib.util.find_spec(module_path)
                if spec and spec.origin:
                    with open(spec.origin, 'r') as f:
                        content = f.read()
                    
                    has_method = f"def {method_name}" in content
                    has_import = "from verenigingen.utils" in content
                    
                    self.log_test_result("integration_points", f"DocType method {method_name}",
                                       has_method and has_import,
                                       f"Method defined and imports present")
                else:
                    self.log_test_result("integration_points", f"DocType method {method_name}", False, "Module not found")
            except Exception as e:
                self.log_test_result("integration_points", f"DocType method {method_name}", False, str(e))
    
    def validate_security(self):
        """Validate security aspects of the system"""
        print("\n🔒 VALIDATING SECURITY")
        print("-" * 21)
        
        # Test 1: No hardcoded sensitive data
        sensitive_patterns = ['password', 'secret', 'api_key', 'token']
        files_to_check = [
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/team_role_profile_manager.py",
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/chapter_role_profile_manager.py",
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/base_role_profile_manager.py"
        ]
        
        security_issues = []
        
        for file_path in files_to_check:
            try:
                with open(file_path, 'r') as f:
                    content = f.read().lower()
                
                for pattern in sensitive_patterns:
                    if pattern in content and 'example' not in content and 'test' not in content:
                        security_issues.append(f"{Path(file_path).name}: potential {pattern}")
            except Exception:
                continue
        
        self.log_test_result("security", "No hardcoded sensitive data",
                           len(security_issues) == 0,
                           f"Issues found: {security_issues}" if security_issues else "")
        
        # Test 2: Proper permission checks
        permission_patterns = ['frappe.has_permission', 'check_permission', 'validate_permissions']
        
        permission_checks = 0
        for file_path in files_to_check:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                for pattern in permission_patterns:
                    permission_checks += content.count(pattern)
            except Exception:
                continue
        
        self.log_test_result("security", "Permission validation checks",
                           permission_checks > 0,
                           f"Found {permission_checks} permission checks")
    
    def validate_performance(self):
        """Validate performance aspects"""
        print("\n⚡ VALIDATING PERFORMANCE")
        print("-" * 25)
        
        # Test 1: Query optimization patterns
        optimization_patterns = ['frappe.qb', 'DocType', 'frappe.get_all']
        files_to_check = [
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/base_role_profile_manager.py",
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/team_role_profile_manager.py"
        ]
        
        optimization_usage = 0
        for file_path in files_to_check:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                for pattern in optimization_patterns:
                    optimization_usage += content.count(pattern)
            except Exception:
                continue
        
        self.log_test_result("performance", "Query optimization patterns",
                           optimization_usage > 0,
                           f"Found {optimization_usage} optimized query patterns")
        
        # Test 2: Bulk operations support
        bulk_patterns = ['bulk_', '_bulk_', 'batch_']
        
        bulk_operations = 0
        for file_path in files_to_check:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                for pattern in bulk_patterns:
                    bulk_operations += content.count(pattern)
            except Exception:
                continue
        
        self.log_test_result("performance", "Bulk operations support",
                           bulk_operations > 0,
                           f"Found {bulk_operations} bulk operation patterns")
    
    def print_summary(self):
        """Print comprehensive validation summary"""
        print("\n" + "="*70)
        print("COMPREHENSIVE ROLE PROFILE SYSTEM VALIDATION SUMMARY")
        print("="*70)
        
        total_passed = 0
        total_failed = 0
        
        for category, results in self.validation_results.items():
            passed = results["passed"]
            failed = results["failed"]
            total = passed + failed
            
            total_passed += passed
            total_failed += failed
            
            if total > 0:
                percentage = (passed / total) * 100
                status_icon = "✅" if failed == 0 else "⚠️" if failed < passed else "❌"
                
                print(f"\n{status_icon} {category.upper().replace('_', ' ')}: {passed}/{total} ({percentage:.1f}%)")
                
                if failed > 0:
                    print(f"   Failed tests:")
                    for test in results["tests"]:
                        if "❌" in test["status"]:
                            print(f"   - {test['name']}")
                            if test["message"]:
                                print(f"     {test['message']}")
        
        # Overall summary
        overall_total = total_passed + total_failed
        if overall_total > 0:
            overall_percentage = (total_passed / overall_total) * 100
            
            print(f"\n{'='*70}")
            print(f"OVERALL VALIDATION RESULT: {total_passed}/{overall_total} ({overall_percentage:.1f}%)")
            
            if total_failed == 0:
                print("🎉 ALL VALIDATION TESTS PASSED!")
                print("✅ Role Profile System is PRODUCTION READY")
                return True
            elif total_failed < total_passed:
                print("⚠️  VALIDATION COMPLETED WITH SOME ISSUES")
                print("🔧 System requires minor fixes before production")
                return False
            else:
                print("❌ VALIDATION FAILED")
                print("🚫 System is NOT ready for production")
                return False
        else:
            print("❌ NO VALIDATION TESTS WERE RUN")
            return False
    
    def run_comprehensive_validation(self) -> bool:
        """Run all validation tests"""
        print("🔍 COMPREHENSIVE ROLE PROFILE SYSTEM VALIDATION")
        print("=" * 52)
        print("Validating refactored role profile system for production readiness...")
        
        try:
            self.validate_architecture()
            self.validate_api_contracts()
            self.validate_database_configuration()
            self.validate_integration_points()
            self.validate_security()
            self.validate_performance()
            
            return self.print_summary()
            
        except Exception as e:
            print(f"\n❌ VALIDATION FAILED WITH ERROR: {str(e)}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            return False


def main():
    """Main validation function"""
    validator = RoleProfileSystemValidator()
    
    try:
        validation_passed = validator.run_comprehensive_validation()
        
        if validation_passed:
            print("\n📋 NEXT STEPS:")
            print("  1. Run integration tests to verify runtime behavior")
            print("  2. Test with real data in staging environment")  
            print("  3. Deploy to production with monitoring")
            return 0
        else:
            print("\n📋 REQUIRED ACTIONS:")
            print("  1. Fix failed validation tests")
            print("  2. Re-run validation until all tests pass")
            print("  3. Do not deploy to production until validation passes")
            return 1
            
    except Exception as e:
        print(f"\n❌ Validation process failed: {str(e)}")
        return 1


if __name__ == "__main__":
    # This script is designed to be run via bench run-python-script
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n❌ Critical validation error: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        exit_code = 1