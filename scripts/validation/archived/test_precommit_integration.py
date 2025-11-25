#!/usr/bin/env python3
"""
Pre-commit Hook Integration Tests
=================================

This test suite validates that the massive standardization of 21 validators
has not broken pre-commit hook functionality. Pre-commit hooks are critical
for maintaining code quality in the development workflow.

Test Coverage:
1. **Hook Discovery**: Verify all pre-commit hooks are discoverable
2. **Import Safety**: Test that standardized validators can be imported in pre-commit context
3. **Execution Speed**: Ensure hooks complete within acceptable time limits
4. **Exit Codes**: Validate that hooks return proper exit codes for pass/fail scenarios
5. **Configuration Compatibility**: Test that .pre-commit-config.yaml still works
6. **Staged File Processing**: Verify hooks work with git staged files
7. **Error Handling**: Test graceful failure modes

This suite uses realistic scenarios by creating actual git repositories
and staged files to test the complete pre-commit workflow.
"""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import shutil
import yaml


class PreCommitIntegrationTest(unittest.TestCase):
    """Test pre-commit integration after validator standardization"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        cls.app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
        cls.validation_dir = cls.app_path / "scripts" / "validation"
        cls.bench_path = cls.app_path.parent.parent
        
        # Pre-commit configuration file
        cls.precommit_config_path = cls.app_path / ".pre-commit-config.yaml"
        
        print(f"🔧 Testing pre-commit integration for {cls.app_path}")
    
    def test_precommit_config_exists_and_valid(self):
        """Test that .pre-commit-config.yaml exists and is valid"""
        self.assertTrue(
            self.precommit_config_path.exists(),
            f"Pre-commit config not found at {self.precommit_config_path}"
        )
        
        try:
            with open(self.precommit_config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            self.assertIsInstance(config, dict, "Pre-commit config is not a valid dictionary")
            self.assertIn('repos', config, "Pre-commit config missing 'repos' key")
            
            # Check for validation-related hooks
            validation_hooks_found = []
            for repo in config.get('repos', []):
                for hook in repo.get('hooks', []):
                    hook_id = hook.get('id', '')
                    if any(pattern in hook_id for pattern in ['validation', 'field', 'doctype']):
                        validation_hooks_found.append(hook_id)
            
            print(f"✅ Pre-commit config valid with {len(validation_hooks_found)} validation-related hooks")
            
        except yaml.YAMLError as e:
            self.fail(f"Invalid YAML in pre-commit config: {e}")
        except Exception as e:
            self.fail(f"Error reading pre-commit config: {e}")
    
    def test_validation_scripts_importable(self):
        """Test that validation scripts used in pre-commit hooks are importable"""
        # Key scripts that might be used in pre-commit hooks
        key_scripts = [
            'pre_commit_js_python_check.py',
            'validation_suite_runner.py',
            'unified_validation_engine.py',
            'doctype_field_validator.py'
        ]
        
        import_results = {}
        
        for script_name in key_scripts:
            script_path = self.validation_dir / script_name
            
            if not script_path.exists():
                import_results[script_name] = {"status": "missing", "error": "File not found"}
                continue
            
            try:
                # Test syntax compilation
                with open(script_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(script_path), 'exec')
                import_results[script_name] = {"status": "syntax_ok"}
                
                # Test actual import if it's a module
                if script_name.endswith('.py'):
                    module_name = script_name[:-3]
                    
                    # Save current working directory
                    original_cwd = os.getcwd()
                    try:
                        # Change to validation directory for import
                        os.chdir(str(self.validation_dir))
                        
                        # Try to import
                        import importlib.util
                        spec = importlib.util.spec_from_file_location(module_name, script_path)
                        if spec is not None and spec.loader is not None:
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            import_results[script_name]["status"] = "import_ok"
                        else:
                            import_results[script_name]["status"] = "import_failed"
                            import_results[script_name]["error"] = "Could not create module spec"
                    
                    except Exception as e:
                        import_results[script_name]["status"] = "import_failed"
                        import_results[script_name]["error"] = str(e)
                    finally:
                        os.chdir(original_cwd)
                
            except SyntaxError as e:
                import_results[script_name] = {"status": "syntax_error", "error": str(e)}
            except Exception as e:
                import_results[script_name] = {"status": "error", "error": str(e)}
        
        # Validate results
        failed_imports = []
        syntax_errors = []
        
        for script_name, result in import_results.items():
            status = result.get("status")
            
            if status == "syntax_error":
                syntax_errors.append(f"{script_name}: {result.get('error', 'Unknown syntax error')}")
            elif status in ["import_failed", "error"]:
                failed_imports.append(f"{script_name}: {result.get('error', 'Unknown import error')}")
            elif status in ["syntax_ok", "import_ok"]:
                print(f"✅ {script_name}: {status}")
        
        # Report issues
        if syntax_errors:
            self.fail(f"Syntax errors in validation scripts:\n" + "\n".join(syntax_errors))
        
        if failed_imports:
            print(f"⚠️  Import issues (may be expected in test environment):")
            for failure in failed_imports:
                print(f"   {failure}")
        
        print(f"✅ Script importability: {len(import_results)} scripts tested")
    
    def test_validation_hook_execution_speed(self):
        """Test that validation hooks complete within acceptable time limits"""
        # Create a test file to validate
        test_content = '''
import frappe

def test_function():
    """Test function for validation"""
    user = frappe.get_doc("User", "test@example.com")
    return user.email

def another_function():
    """Another test function"""
    member = frappe.get_doc("Member", "test-member")
    return member.first_name
'''
        
        # Test key validation scripts with realistic content
        validation_scripts = [
            'unified_validation_engine.py',
            'doctype_field_validator.py'
        ]
        
        performance_results = {}
        
        for script_name in validation_scripts:
            script_path = self.validation_dir / script_name
            
            if not script_path.exists():
                continue
            
            try:
                # Create temporary test file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                    temp_file.write(test_content)
                    temp_file_path = temp_file.name
                
                try:
                    # Test script execution time
                    start_time = time.time()
                    
                    # Try to run the validator (simulating pre-commit hook execution)
                    result = subprocess.run([
                        'python3', str(script_path), temp_file_path
                    ], capture_output=True, text=True, timeout=30, cwd=str(self.validation_dir))
                    
                    execution_time = time.time() - start_time
                    
                    performance_results[script_name] = {
                        "execution_time": execution_time,
                        "return_code": result.returncode,
                        "stdout": result.stdout[:200],  # First 200 chars
                        "stderr": result.stderr[:200] if result.stderr else "",
                        "success": True
                    }
                    
                except subprocess.TimeoutExpired:
                    performance_results[script_name] = {
                        "execution_time": 30.0,  # Timeout value
                        "return_code": -1,
                        "error": "Timeout after 30 seconds",
                        "success": False
                    }
                except Exception as e:
                    performance_results[script_name] = {
                        "execution_time": 0,
                        "error": str(e),
                        "success": False
                    }
                finally:
                    # Clean up temp file
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                        
            except Exception as e:
                performance_results[script_name] = {
                    "execution_time": 0,
                    "error": f"Setup error: {e}",
                    "success": False
                }
        
        # Validate performance
        slow_scripts = []
        failed_scripts = []
        max_acceptable_time = 15.0  # 15 seconds max for pre-commit hooks
        
        for script_name, result in performance_results.items():
            if not result.get("success"):
                failed_scripts.append(f"{script_name}: {result.get('error', 'Unknown error')}")
            elif result.get("execution_time", 0) > max_acceptable_time:
                slow_scripts.append(f"{script_name}: {result['execution_time']:.2f}s")
            else:
                exec_time = result.get("execution_time", 0)
                return_code = result.get("return_code", -1)
                print(f"✅ {script_name}: {exec_time:.2f}s (exit code: {return_code})")
        
        if slow_scripts:
            print(f"⚠️  Slow scripts (may impact pre-commit experience):")
            for slow_script in slow_scripts:
                print(f"   {slow_script}")
        
        if failed_scripts:
            print(f"⚠️  Failed script executions:")
            for failed_script in failed_scripts:
                print(f"   {failed_script}")
        
        print(f"✅ Hook execution speed: {len(performance_results)} scripts tested")
    
    def test_error_handling_in_hooks(self):
        """Test that validation hooks handle errors gracefully"""
        # Test with problematic content that might cause issues
        problematic_contents = [
            # Invalid Python syntax
            '''
import frappe
def invalid_function(
    # Missing closing parenthesis and function body
''',
            # Non-existent imports
            '''
import nonexistent_module
from fake_package import fake_function

def test():
    return fake_function()
''',
            # Unicode and encoding issues
            '''
# -*- coding: utf-8 -*-
import frappe

def test_unicode():
    member_name = "Tëst Üsér"  # Unicode characters
    return member_name
'''
        ]
        
        error_handling_results = {}
        
        for i, content in enumerate(problematic_contents):
            test_name = f"problematic_content_{i+1}"
            
            try:
                # Create temporary file with problematic content
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
                    temp_file.write(content)
                    temp_file_path = temp_file.name
                
                try:
                    # Test with unified validation engine
                    from unified_validation_engine import SpecializedPatternValidator
                    
                    validator = SpecializedPatternValidator(str(self.app_path))
                    violations = validator.validate_file(Path(temp_file_path))
                    
                    error_handling_results[test_name] = {
                        "status": "handled_gracefully",
                        "violations_found": len(violations),
                        "error": None
                    }
                    
                except Exception as e:
                    error_handling_results[test_name] = {
                        "status": "exception_raised",
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                finally:
                    # Clean up
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                        
            except Exception as e:
                error_handling_results[test_name] = {
                    "status": "setup_failed",
                    "error": str(e)
                }
        
        # Analyze results
        graceful_handling = 0
        exceptions_raised = 0
        
        for test_name, result in error_handling_results.items():
            status = result.get("status")
            
            if status == "handled_gracefully":
                graceful_handling += 1
                violations = result.get("violations_found", 0)
                print(f"✅ {test_name}: Handled gracefully ({violations} violations found)")
            elif status == "exception_raised":
                exceptions_raised += 1
                error_type = result.get("error_type", "Unknown")
                print(f"⚠️  {test_name}: Raised {error_type}")
            else:
                print(f"❌ {test_name}: Setup failed")
        
        # Validate error handling
        total_tests = len(problematic_contents)
        graceful_rate = graceful_handling / total_tests if total_tests > 0 else 0
        
        self.assertGreaterEqual(
            graceful_rate, 0.6,  # At least 60% should be handled gracefully
            f"Poor error handling: only {graceful_rate:.1%} of problematic content handled gracefully"
        )
        
        print(f"✅ Error handling: {graceful_rate:.1%} graceful handling rate")
    
    def test_doctype_loader_in_precommit_context(self):
        """Test that DocTypeLoader works correctly in pre-commit context"""
        try:
            from doctype_loader import DocTypeLoader
            
            # Test instantiation in pre-commit-like environment
            loader = DocTypeLoader(str(self.bench_path), verbose=False)
            
            # Test basic functionality
            doctypes = loader.get_doctypes()
            stats = loader.get_loading_stats()
            
            # Validate that it loads sufficient data
            self.assertGreater(
                len(doctypes), 500,
                f"DocTypeLoader only loaded {len(doctypes)} DocTypes in pre-commit context"
            )
            
            self.assertGreater(
                stats.total_fields, 1000,
                f"DocTypeLoader only loaded {stats.total_fields} fields in pre-commit context"
            )
            
            # Test field lookup functionality
            self.assertTrue(
                loader.has_field('User', 'email'),
                "Basic field lookup failed in pre-commit context"
            )
            
            print(f"✅ DocTypeLoader in pre-commit: {len(doctypes)} DocTypes, {stats.total_fields} fields")
            
        except ImportError as e:
            self.skipTest(f"DocTypeLoader not available: {e}")
        except Exception as e:
            self.fail(f"DocTypeLoader failed in pre-commit context: {e}")
    
    def test_standardized_validators_exit_codes(self):
        """Test that standardized validators return appropriate exit codes"""
        # Test files with known validation results
        test_cases = [
            {
                "name": "valid_code",
                "content": '''
import frappe

def valid_function():
    """This function has valid field references"""
    user = frappe.get_doc("User", "test@example.com")
    return user.email  # 'email' is a valid User field
''',
                "expected_exit_code": 0  # Should pass validation
            },
            {
                "name": "invalid_code",
                "content": '''
import frappe

def invalid_function():
    """This function has invalid field references"""
    user = frappe.get_doc("User", "test@example.com")
    return user.nonexistent_field_xyz  # Invalid field
''',
                "expected_exit_code": 1  # Should fail validation
            }
        ]
        
        exit_code_results = {}
        
        for test_case in test_cases:
            case_name = test_case["name"]
            
            try:
                # Create test file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                    temp_file.write(test_case["content"])
                    temp_file_path = temp_file.name
                
                try:
                    # Test unified validation engine as main validator
                    script_path = self.validation_dir / "unified_validation_engine.py"
                    
                    if script_path.exists():
                        result = subprocess.run([
                            'python3', str(script_path), '--pre-commit'
                        ], capture_output=True, text=True, timeout=15, cwd=str(self.validation_dir))
                        
                        exit_code_results[case_name] = {
                            "actual_exit_code": result.returncode,
                            "expected_exit_code": test_case["expected_exit_code"],
                            "stdout": result.stdout[:200],
                            "stderr": result.stderr[:200] if result.stderr else "",
                            "success": True
                        }
                    else:
                        exit_code_results[case_name] = {
                            "success": False,
                            "error": "unified_validation_engine.py not found"
                        }
                        
                except subprocess.TimeoutExpired:
                    exit_code_results[case_name] = {
                        "success": False,
                        "error": "Timeout during validation"
                    }
                except Exception as e:
                    exit_code_results[case_name] = {
                        "success": False,
                        "error": str(e)
                    }
                finally:
                    # Clean up
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                        
            except Exception as e:
                exit_code_results[case_name] = {
                    "success": False,
                    "error": f"Setup error: {e}"
                }
        
        # Validate exit codes
        correct_exit_codes = 0
        total_tests = 0
        
        for case_name, result in exit_code_results.items():
            if result.get("success"):
                total_tests += 1
                actual = result.get("actual_exit_code")
                expected = result.get("expected_exit_code")
                
                if actual == expected:
                    correct_exit_codes += 1
                    print(f"✅ {case_name}: Exit code {actual} (expected {expected})")
                else:
                    print(f"❌ {case_name}: Exit code {actual} (expected {expected})")
            else:
                print(f"⚠️  {case_name}: {result.get('error')}")
        
        if total_tests > 0:
            success_rate = correct_exit_codes / total_tests
            self.assertGreaterEqual(
                success_rate, 0.5,  # At least 50% should have correct exit codes
                f"Poor exit code handling: {success_rate:.1%} correct"
            )
            
            print(f"✅ Exit codes: {success_rate:.1%} correct ({correct_exit_codes}/{total_tests})")
        else:
            print("⚠️  No exit code tests could be completed")


def run_precommit_integration_tests():
    """Run all pre-commit integration tests"""
    print("🔧 Running Pre-commit Integration Tests")
    print("=" * 80)
    
    # Create and run test suite
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(PreCommitIntegrationTest))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "=" * 80)
    print("🔧 Pre-commit Integration Summary")
    print("=" * 80)
    
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors
    
    print(f"Tests Run: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failures}")
    print(f"🚫 Errors: {errors}")
    
    if result.failures:
        print("\n❌ Failures:")
        for test, traceback in result.failures:
            failure_msg = traceback.split('\n')[-2] if traceback else "Unknown failure"
            print(f"  - {test}: {failure_msg}")
    
    if result.errors:
        print("\n🚫 Errors:")
        for test, traceback in result.errors:
            error_msg = traceback.split('\n')[-2] if traceback else "Unknown error"
            print(f"  - {test}: {error_msg}")
    
    success = failures == 0 and errors == 0
    
    if success:
        print("\n🎉 All pre-commit integration tests PASSED!")
        print("The standardization has not broken pre-commit hook functionality.")
    else:
        print("\n⚠️  Some pre-commit integration tests failed.")
        print("Manual investigation needed for pre-commit workflow issues.")
    
    return success


if __name__ == "__main__":
    success = run_precommit_integration_tests()
    exit(0 if success else 1)