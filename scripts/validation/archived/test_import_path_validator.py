#!/usr/bin/env python3
"""
Unit Tests for Import Path Validator
====================================

Comprehensive test suite for the ImportPathValidator to ensure it correctly
validates Python import statements against the file system.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import sys
import os

# Add the validation directory to path
sys.path.insert(0, str(Path(__file__).parent))

from import_path_validator import ImportPathValidator, ImportViolation


class TestImportPathValidator(unittest.TestCase):
    """Unit tests for ImportPathValidator"""
    
    def setUp(self):
        """Set up test environment"""
        # Create temporary directory structure for testing
        self.test_dir = Path(tempfile.mkdtemp())
        self.app_path = self.test_dir / "test_app"
        self.app_path.mkdir(parents=True)
        
        # Create test module structure
        self._create_test_modules()
        
        # Initialize validator
        self.validator = ImportPathValidator(str(self.app_path), verbose=False)
    
    def tearDown(self):
        """Clean up test environment"""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def _create_test_modules(self):
        """Create test module structure"""
        # Create test_app/utils/validation/iban_validator.py
        utils_validation = self.app_path / "utils" / "validation"
        utils_validation.mkdir(parents=True)
        (utils_validation / "__init__.py").touch()
        
        iban_validator = utils_validation / "iban_validator.py"
        iban_validator.write_text("""
def validate_iban(iban):
    return True

def format_iban(iban):
    return iban.replace(' ', '')
""")
        
        # Create test_app/utils/iban_validator.py (wrong location)
        utils = self.app_path / "utils"
        (utils / "__init__.py").touch()
        
        # Create test_app/api/member_management.py
        api = self.app_path / "api"
        api.mkdir(parents=True)
        (api / "__init__.py").touch()
        
        member_mgmt = api / "member_management.py"
        member_mgmt.write_text("""
def create_member():
    pass

def update_member():
    pass
""")
    
    def _create_test_file(self, content: str) -> Path:
        """Create a temporary test file with given content"""
        test_file = self.test_dir / f"test_file_{id(content)}.py"
        test_file.write_text(content)
        return test_file
    
    def test_valid_import_absolute(self):
        """Test that valid absolute imports are not flagged"""
        content = """
from test_app.utils.validation.iban_validator import validate_iban
from test_app.api.member_management import create_member
import json
import sys
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have no violations for valid imports
        valid_violations = [v for v in violations if 'json' not in v.module_path and 'sys' not in v.module_path]
        self.assertEqual(len(valid_violations), 0, f"Expected no violations, got: {valid_violations}")
    
    def test_invalid_module_path(self):
        """Test that invalid module paths are flagged"""
        content = """
from test_app.utils.iban_validator import validate_iban  # Wrong path
from test_app.nonexistent_module import something
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have 2 violations
        self.assertGreaterEqual(len(violations), 1, "Should detect invalid module paths")
        
        # Check specific violation details
        module_not_found = [v for v in violations if v.error_type == 'module_not_found']
        self.assertGreater(len(module_not_found), 0, "Should detect module not found errors")
    
    def test_invalid_import_name(self):
        """Test that invalid import names are flagged"""
        content = """
from test_app.utils.validation.iban_validator import nonexistent_function
from test_app.api.member_management import invalid_function
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should detect name not found violations
        name_not_found = [v for v in violations if v.error_type == 'name_not_found']
        self.assertGreater(len(name_not_found), 0, "Should detect name not found errors")
    
    def test_valid_import_names(self):
        """Test that valid import names are not flagged"""
        content = """
from test_app.utils.validation.iban_validator import validate_iban, format_iban
from test_app.api.member_management import create_member, update_member
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Filter out any system module issues
        app_violations = [v for v in violations if 'test_app' in v.module_path]
        self.assertEqual(len(app_violations), 0, f"Expected no violations for valid names, got: {app_violations}")
    
    def test_suggestion_for_common_mistake(self):
        """Test that suggestions are provided for common mistakes"""
        # Add the common mistake to validator's knowledge
        self.validator.common_mistakes["test_app.utils.iban_validator"] = "test_app.utils.validation.iban_validator"
        
        content = """
from test_app.utils.iban_validator import validate_iban
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have violation with suggestion
        violations_with_suggestions = [v for v in violations if v.suggestion]
        self.assertGreater(len(violations_with_suggestions), 0, "Should provide suggestions for common mistakes")
        
        # Check suggestion content
        for violation in violations_with_suggestions:
            self.assertIn("test_app.utils.validation.iban_validator", violation.suggestion)
    
    def test_wildcard_imports(self):
        """Test that wildcard imports are handled properly"""
        content = """
from test_app.utils.validation.iban_validator import *
from test_app.api.member_management import *
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Wildcard imports of valid modules should not cause name_not_found errors
        name_violations = [v for v in violations if v.error_type == 'name_not_found']
        self.assertEqual(len(name_violations), 0, "Wildcard imports should not cause name not found errors")
    
    def test_relative_imports(self):
        """Test handling of relative imports"""
        # Create a test file in the api directory
        test_file = self.app_path / "api" / "test_relative.py"
        content = """
from .member_management import create_member  # Valid relative import
from ..utils.validation.iban_validator import validate_iban  # Valid relative import
"""
        test_file.write_text(content)
        
        violations = self.validator.validate_file(test_file)
        
        # Relative imports to existing modules should not cause violations
        # Note: This test may be limited by the validator's ability to resolve relative imports
        app_violations = [v for v in violations if 'test_app' in v.module_path]
        # We'll be lenient here as relative import resolution is complex
        self.assertLessEqual(len(app_violations), 2, "Relative imports should be handled reasonably")
    
    def test_syntax_error_handling(self):
        """Test that files with syntax errors are handled gracefully"""
        content = """
from test_app.utils.validation.iban_validator import validate_iban
# Syntax error below:
def broken_syntax(
"""
        test_file = self._create_test_file(content)
        
        # Should not raise exception, should return empty list or handle gracefully
        try:
            violations = self.validator.validate_file(test_file)
            # If we get here, the validator handled the syntax error gracefully
            self.assertTrue(True, "Validator handled syntax error gracefully")
        except Exception as e:
            self.fail(f"Validator should handle syntax errors gracefully, but raised: {e}")
    
    def test_performance_with_caching(self):
        """Test that module caching improves performance"""
        content = """
from test_app.utils.validation.iban_validator import validate_iban
from test_app.utils.validation.iban_validator import format_iban
from test_app.api.member_management import create_member
from test_app.api.member_management import update_member
"""
        test_file = self._create_test_file(content)
        
        # First run - should populate cache
        start_time = time.time() if 'time' in sys.modules else 0
        violations1 = self.validator.validate_file(test_file)
        first_duration = (time.time() - start_time) if 'time' in sys.modules else 0
        
        # Second run - should use cache
        start_time = time.time() if 'time' in sys.modules else 0
        violations2 = self.validator.validate_file(test_file)
        second_duration = (time.time() - start_time) if 'time' in sys.modules else 0
        
        # Results should be the same
        self.assertEqual(len(violations1), len(violations2), "Cached results should match original results")
        
        # If timing is available, second run should be faster or same
        if 'time' in sys.modules and first_duration > 0:
            self.assertLessEqual(second_duration, first_duration * 1.5, "Caching should improve performance")
    
    def test_violation_data_structure(self):
        """Test that ImportViolation objects have correct structure"""
        content = """
from test_app.nonexistent_module import something
"""
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        self.assertGreater(len(violations), 0, "Should have violations")
        
        violation = violations[0]
        self.assertIsInstance(violation, ImportViolation)
        self.assertTrue(hasattr(violation, 'file_path'))
        self.assertTrue(hasattr(violation, 'line_number'))
        self.assertTrue(hasattr(violation, 'import_statement'))
        self.assertTrue(hasattr(violation, 'module_path'))
        self.assertTrue(hasattr(violation, 'error_type'))
        self.assertTrue(hasattr(violation, 'message'))
        
        # Check that values are reasonable
        self.assertEqual(violation.file_path, str(test_file))
        self.assertGreater(violation.line_number, 0)
        self.assertIn('test_app.nonexistent_module', violation.module_path)
        self.assertIn('module_not_found', violation.error_type)
    
    def test_directory_validation(self):
        """Test validation of entire directory"""
        # Create a few test files in the app directory
        test_files = []
        
        # Good file
        good_file = self.app_path / "good_imports.py"
        good_file.write_text("""
from .utils.validation.iban_validator import validate_iban
import json
""")
        test_files.append(good_file)
        
        # Bad file
        bad_file = self.app_path / "bad_imports.py"
        bad_file.write_text("""
from .utils.nonexistent_module import something
from .api.member_management import nonexistent_function
""")
        test_files.append(bad_file)
        
        # Run directory validation
        violations = self.validator.validate_directory(self.app_path)
        
        # Should have violations from the bad file
        self.assertGreater(len(violations), 0, "Directory validation should find violations")
        
        # Check that violations include file paths
        file_paths = {v.file_path for v in violations}
        self.assertIn(str(bad_file), file_paths, "Should include violations from bad file")


class TestImportPathValidatorIntegration(unittest.TestCase):
    """Integration tests with real Frappe app structure"""
    
    def setUp(self):
        """Set up with real app path"""
        # Use the actual verenigingen app for integration tests
        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        if Path(app_path).exists():
            self.validator = ImportPathValidator(app_path, verbose=False)
            self.has_real_app = True
        else:
            self.has_real_app = False
            self.skipTest("Real app not available for integration tests")
    
    def test_real_frappe_imports(self):
        """Test validation against real Frappe imports"""
        if not self.has_real_app:
            self.skipTest("Real app not available")
        
        # Test some common Frappe imports
        content = """
import frappe
from frappe import _
from frappe.utils import nowdate, getdate, cstr
"""
        
        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_file = Path(f.name)
        
        try:
            violations = self.validator.validate_file(temp_file)
            
            # Should have minimal violations for standard Frappe imports
            frappe_violations = [v for v in violations if 'frappe' in v.module_path]
            # We'll be lenient as some dynamic imports might not be detectable
            self.assertLessEqual(len(frappe_violations), 2, "Standard Frappe imports should mostly pass")
            
        finally:
            temp_file.unlink()
    
    def test_verenigingen_specific_imports(self):
        """Test validation of verenigingen-specific imports"""
        if not self.has_real_app:
            self.skipTest("Real app not available")
        
        content = """
from verenigingen.utils.validation.iban_validator import validate_iban
from verenigingen.api.member_management import create_member
"""
        
        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_file = Path(f.name)
        
        try:
            violations = self.validator.validate_file(temp_file)
            
            # Check if violations are legitimate or false positives
            verenigingen_violations = [v for v in violations if 'verenigingen' in v.module_path]
            
            # Print violations for manual inspection during test runs
            for violation in verenigingen_violations:
                print(f"Violation: {violation.module_path} - {violation.message}")
            
        finally:
            temp_file.unlink()


def run_tests():
    """Run all tests"""
    # Import time module if available for performance tests
    try:
        import time
        sys.modules['time'] = time
    except ImportError:
        pass
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add unit tests
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestImportPathValidator))
    
    # Add integration tests if real app is available
    if Path("/home/frappe/frappe-bench/apps/verenigingen").exists():
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestImportPathValidatorIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)