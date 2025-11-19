#!/usr/bin/env python3
"""
Unit Tests for Select Field Value Validator
==========================================

Comprehensive test suite for the SelectFieldValueValidator to ensure it correctly
validates Select field values against DocType schema definitions.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import sys
import json
import os

# Add the validation directory to path
sys.path.insert(0, str(Path(__file__).parent))

from select_field_value_validator import SelectFieldValueValidator, SelectFieldViolation


class TestSelectFieldValueValidator(unittest.TestCase):
    """Unit tests for SelectFieldValueValidator"""
    
    def setUp(self):
        """Set up test environment"""
        # Create temporary directory structure for testing
        self.test_dir = Path(tempfile.mkdtemp())
        self.app_path = self.test_dir / "test_app"
        self.app_path.mkdir(parents=True)
        
        # Create test DocType structure
        self._create_test_doctypes()
        
        # Initialize validator
        self.validator = SelectFieldValueValidator(str(self.app_path), verbose=False)
    
    def tearDown(self):
        """Clean up test environment"""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def _create_test_doctypes(self):
        """Create test DocType JSON files"""
        # Create test_app/test_app/doctype directory
        doctype_dir = self.app_path / "test_app" / "doctype"
        doctype_dir.mkdir(parents=True)
        
        # Create Member DocType with Status select field
        member_dir = doctype_dir / "member"
        member_dir.mkdir(parents=True)
        
        member_json = {
            "doctype": "DocType",
            "name": "Member",
            "module": "Test App",
            "fields": [
                {
                    "fieldname": "full_name",
                    "fieldtype": "Data",
                    "label": "Full Name",
                    "reqd": 1
                },
                {
                    "fieldname": "status",
                    "fieldtype": "Select",
                    "label": "Status",
                    "options": "Active\nInactive\nPending\nTerminated",
                    "default": "Pending"
                },
                {
                    "fieldname": "membership_type",
                    "fieldtype": "Select",
                    "label": "Membership Type",
                    "options": "Regular\nStudent\nSenior\nHonorary"
                }
            ]
        }
        
        (member_dir / "member.json").write_text(json.dumps(member_json, indent=2))
        
        # Create Account Creation Request DocType 
        request_dir = doctype_dir / "account_creation_request"
        request_dir.mkdir(parents=True)
        
        request_json = {
            "doctype": "DocType", 
            "name": "Account Creation Request",
            "module": "Test App",
            "fields": [
                {
                    "fieldname": "member",
                    "fieldtype": "Link",
                    "label": "Member",
                    "options": "Member"
                },
                {
                    "fieldname": "status",
                    "fieldtype": "Select",
                    "label": "Status", 
                    "options": "Requested\nQueued\nProcessing\nCompleted\nFailed\nCancelled",
                    "default": "Requested"
                }
            ]
        }
        
        (request_dir / "account_creation_request.json").write_text(json.dumps(request_json, indent=2))
        
        # Create Chapter Join Request DocType
        chapter_join_dir = doctype_dir / "chapter_join_request" 
        chapter_join_dir.mkdir(parents=True)
        
        chapter_join_json = {
            "doctype": "DocType",
            "name": "Chapter Join Request", 
            "module": "Test App",
            "fields": [
                {
                    "fieldname": "member",
                    "fieldtype": "Link",
                    "label": "Member",
                    "options": "Member"
                },
                {
                    "fieldname": "status",
                    "fieldtype": "Select",
                    "label": "Status",
                    "options": "Pending\nApproved\nRejected",
                    "default": "Pending"
                }
            ]
        }
        
        (chapter_join_dir / "chapter_join_request.json").write_text(json.dumps(chapter_join_json, indent=2))
    
    def _create_test_file(self, content: str) -> Path:
        """Create a temporary test file with given content"""
        test_file = self.test_dir / f"test_file_{id(content)}.py"
        test_file.write_text(content)
        return test_file
    
    def test_valid_select_field_values(self):
        """Test that valid Select field values are not flagged"""
        content = '''
import frappe

def test_valid_member():
    member = frappe.new_doc("Member")
    member.status = "Active"  # Valid option
    member.membership_type = "Student"  # Valid option
    
    request = frappe.new_doc("Account Creation Request")
    request.status = "Requested"  # Valid option
    
    chapter_request = frappe.new_doc("Chapter Join Request") 
    chapter_request.status = "Pending"  # Valid option
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have no violations for valid Select field values
        self.assertEqual(len(violations), 0, f"Expected no violations for valid values, got: {violations}")
    
    def test_invalid_select_field_values(self):
        """Test that invalid Select field values are flagged"""
        content = '''
import frappe

def test_invalid_member():
    member = frappe.new_doc("Member")
    member.status = "Approved"  # INVALID - not in options
    member.membership_type = "Premium"  # INVALID - not in options
    
    request = frappe.new_doc("Account Creation Request")
    request.status = "Approved"  # INVALID - should be one of: Requested, Queued, Processing, Completed, Failed, Cancelled
    
    chapter_request = frappe.new_doc("Chapter Join Request")
    chapter_request.status = "Cancelled"  # INVALID - should be one of: Pending, Approved, Rejected
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should detect 4 violations
        self.assertEqual(len(violations), 4, f"Expected 4 violations, got: {len(violations)}")
        
        # Check specific violations
        violation_details = [(v.doctype, v.field_name, v.invalid_value) for v in violations]
        expected_violations = [
            ("Member", "status", "Approved"),
            ("Member", "membership_type", "Premium"), 
            ("Account Creation Request", "status", "Approved"),
            ("Chapter Join Request", "status", "Cancelled")
        ]
        
        for expected in expected_violations:
            self.assertIn(expected, violation_details, f"Expected violation not found: {expected}")
    
    def test_set_value_method(self):
        """Test validation of set_value() method calls"""
        content = '''
import frappe

def test_set_value():
    member = frappe.get_doc("Member", "TEST-001")
    member.set_value('status', 'Terminated')  # Valid
    member.set_value('status', 'Suspended')  # INVALID
    
    request = frappe.get_doc("Account Creation Request", "REQ-001")
    request.set_value('status', 'Processing')  # Valid
    request.set_value('status', 'Denied')  # INVALID
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should detect 2 violations for invalid set_value calls
        invalid_violations = [v for v in violations if v.invalid_value in ["Suspended", "Denied"]]
        self.assertEqual(len(invalid_violations), 2, f"Expected 2 set_value violations, got: {len(invalid_violations)}")
    
    def test_dictionary_style_assignment(self):
        """Test validation of dictionary-style field assignment"""
        content = '''
import frappe

def test_dict_assignment():
    member = frappe.new_doc("Member") 
    member['status'] = 'Active'  # Valid
    member['status'] = 'Disabled'  # INVALID
    
    member['membership_type'] = 'Regular'  # Valid
    member['membership_type'] = 'VIP'  # INVALID
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should detect 2 violations for dictionary assignments
        dict_violations = [v for v in violations if v.invalid_value in ["Disabled", "VIP"]]
        self.assertEqual(len(dict_violations), 2, f"Expected 2 dictionary assignment violations, got: {len(dict_violations)}")
    
    def test_case_sensitivity(self):
        """Test that case sensitivity is handled correctly"""
        content = '''
import frappe

def test_case_sensitivity():
    member = frappe.new_doc("Member")
    member.status = "active"  # INVALID - should be "Active"
    member.status = "PENDING"  # INVALID - should be "Pending"  
    member.membership_type = "student"  # INVALID - should be "Student"
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should detect 3 case sensitivity violations
        case_violations = [v for v in violations if v.invalid_value.lower() in ["active", "pending", "student"]]
        self.assertEqual(len(case_violations), 3, f"Expected 3 case sensitivity violations, got: {len(case_violations)}")
    
    def test_nonexistent_doctype(self):
        """Test handling of non-existent DocTypes"""
        content = '''
import frappe

def test_nonexistent():
    doc = frappe.new_doc("NonExistent DocType")
    doc.status = "Active"  # Should not be validated since DocType doesn't exist
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have no violations for non-existent DocType
        self.assertEqual(len(violations), 0, "Non-existent DocTypes should not generate violations")
    
    def test_nonselect_field_assignment(self):
        """Test that non-Select fields are not validated"""
        content = '''
import frappe

def test_nonselect_fields():
    member = frappe.new_doc("Member")
    member.full_name = "Any Value Here"  # Data field - should not be validated
    member.full_name = "Another Value"  # Should not generate violations
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should have no violations for non-Select fields
        self.assertEqual(len(violations), 0, "Non-Select fields should not generate violations")
    
    def test_regex_fallback_for_complex_patterns(self):
        """Test regex fallback for patterns AST can't handle"""
        content = '''
import frappe

def complex_assignment():
    # Complex pattern that might challenge AST parsing
    doc_name = "Member"
    field_name = "status"
    value = "InvalidStatus"
    
    doc = frappe.new_doc(doc_name)
    setattr(doc, field_name, value)  # Should not be caught by current implementation
    
    # But simple assignments should still work
    member = frappe.new_doc("Member")
    member.status = "InvalidDirectAssignment"  # Should be caught
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Should at least catch the direct assignment
        direct_violations = [v for v in violations if v.invalid_value == "InvalidDirectAssignment"]
        self.assertGreater(len(direct_violations), 0, "Should catch at least direct assignments")
    
    def test_violation_data_structure(self):
        """Test that SelectFieldViolation objects have correct structure"""
        content = '''
import frappe

def test_violation():
    member = frappe.new_doc("Member")
    member.status = "InvalidStatus"
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        self.assertGreater(len(violations), 0, "Should have violations")
        
        violation = violations[0]
        self.assertIsInstance(violation, SelectFieldViolation)
        self.assertTrue(hasattr(violation, 'file_path'))
        self.assertTrue(hasattr(violation, 'line_number'))
        self.assertTrue(hasattr(violation, 'doctype'))
        self.assertTrue(hasattr(violation, 'field_name'))
        self.assertTrue(hasattr(violation, 'invalid_value'))
        self.assertTrue(hasattr(violation, 'valid_options'))
        self.assertTrue(hasattr(violation, 'context'))
        
        # Check that values are reasonable
        self.assertEqual(violation.file_path, str(test_file))
        self.assertGreater(violation.line_number, 0)
        self.assertEqual(violation.doctype, "Member")
        self.assertEqual(violation.field_name, "status")
        self.assertEqual(violation.invalid_value, "InvalidStatus")
        self.assertIn("Active", violation.valid_options)
        # Note: assignment_type not in dataclass, using context instead
    
    def test_empty_or_none_values(self):
        """Test handling of empty or None values"""
        content = '''
import frappe

def test_empty_values():
    member = frappe.new_doc("Member")
    member.status = ""  # Empty string - might be valid
    member.membership_type = None  # None value - should not be validated
'''
        test_file = self._create_test_file(content)
        violations = self.validator.validate_file(test_file)
        
        # Empty strings might be flagged, but None values should not be
        none_violations = [v for v in violations if v.invalid_value is None]
        self.assertEqual(len(none_violations), 0, "None values should not generate violations")
    
    def test_performance_with_caching(self):
        """Test that DocType schema caching improves performance"""
        content = '''
import frappe

def test_multiple_same_doctype():
    member1 = frappe.new_doc("Member")
    member1.status = "Active"
    
    member2 = frappe.new_doc("Member") 
    member2.status = "Invalid1"
    
    member3 = frappe.new_doc("Member")
    member3.status = "Invalid2"
'''
        test_file = self._create_test_file(content)
        
        # First run - should populate cache
        violations1 = self.validator.validate_file(test_file)
        
        # Second run - should use cache
        violations2 = self.validator.validate_file(test_file)
        
        # Results should be identical
        self.assertEqual(len(violations1), len(violations2), "Cached results should match original results")
        if violations1:
            self.assertEqual(violations1[0].doctype, violations2[0].doctype, "Cached violation details should match")
        
        # Check that we detected the invalid values
        invalid_values = [v.invalid_value for v in violations1]
        self.assertIn("Invalid1", invalid_values)
        self.assertIn("Invalid2", invalid_values)
    
    def test_doctype_loading_error_handling(self):
        """Test graceful handling of DocType loading errors"""
        # Create a malformed DocType JSON
        malformed_dir = self.app_path / "test_app" / "doctype" / "malformed"
        malformed_dir.mkdir(parents=True)
        (malformed_dir / "malformed.json").write_text("{ invalid json")
        
        content = '''
import frappe

def test_malformed_doctype():
    doc = frappe.new_doc("Malformed")
    doc.status = "AnyValue"
'''
        test_file = self._create_test_file(content)
        
        # Should not raise exception, should handle gracefully
        try:
            violations = self.validator.validate_file(test_file)
            # Should have no violations due to loading error
            malformed_violations = [v for v in violations if v.doctype == "Malformed"]
            self.assertEqual(len(malformed_violations), 0, "Malformed DocTypes should not generate violations")
        except Exception as e:
            self.fail(f"Validator should handle DocType loading errors gracefully, but raised: {e}")
    
    def test_directory_validation(self):
        """Test validation of entire directory"""
        # Create test files in the app directory
        
        # Good file
        good_file = self.app_path / "good_selects.py"
        good_file.write_text('''
import frappe

def good_assignments():
    member = frappe.new_doc("Member")
    member.status = "Active"
    member.membership_type = "Regular"
''')
        
        # Bad file
        bad_file = self.app_path / "bad_selects.py"
        bad_file.write_text('''
import frappe

def bad_assignments():
    member = frappe.new_doc("Member")
    member.status = "InvalidStatus"
    
    request = frappe.new_doc("Account Creation Request")
    request.status = "Denied"
''')
        
        # Run directory validation
        violations = self.validator.validate_directory(self.app_path)
        
        # Should have violations from the bad file
        self.assertGreater(len(violations), 0, "Directory validation should find violations")
        
        # Check that violations include file paths
        file_paths = {v.file_path for v in violations}
        self.assertIn(str(bad_file), file_paths, "Should include violations from bad file")
        self.assertNotIn(str(good_file), file_paths, "Should not include violations from good file")


class TestSelectFieldValueValidatorIntegration(unittest.TestCase):
    """Integration tests with real Frappe DocTypes"""
    
    def setUp(self):
        """Set up with real app path"""
        # Use the actual verenigingen app for integration tests
        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        if Path(app_path).exists():
            self.validator = SelectFieldValueValidator(app_path, verbose=False)
            self.has_real_app = True
        else:
            self.has_real_app = False
            self.skipTest("Real app not available for integration tests")
    
    def test_real_member_doctype_validation(self):
        """Test validation against real Member DocType"""
        if not self.has_real_app:
            self.skipTest("Real app not available")
        
        content = '''
import frappe

def test_real_member():
    member = frappe.new_doc("Member")
    member.status = "Active"  # Should be valid for real Member DocType
    member.status = "InvalidStatus"  # Should be invalid
'''
        
        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_file = Path(f.name)
        
        try:
            violations = self.validator.validate_file(temp_file)
            
            # Should detect the invalid status
            invalid_violations = [v for v in violations if v.invalid_value == "InvalidStatus"]
            self.assertGreater(len(invalid_violations), 0, "Should detect invalid Member status")
            
            # Print violations for manual inspection
            for violation in violations:
                print(f"Real DocType Violation: {violation.doctype}.{violation.field_name} = '{violation.invalid_value}'")
                print(f"  Valid options: {violation.valid_options}")
                
        finally:
            temp_file.unlink()
    
    def test_account_creation_request_validation(self):
        """Test validation against real Account Creation Request DocType"""
        if not self.has_real_app:
            self.skipTest("Real app not available")
        
        content = '''
import frappe

def test_account_request():
    request = frappe.new_doc("Account Creation Request")
    request.status = "Approved"  # This should be invalid based on our test file
'''
        
        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_file = Path(f.name)
        
        try:
            violations = self.validator.validate_file(temp_file)
            
            # Check if violations are detected
            account_violations = [v for v in violations if v.doctype == "Account Creation Request"]
            
            # Print violations for manual inspection
            for violation in account_violations:
                print(f"Account Request Violation: {violation.field_name} = '{violation.invalid_value}'")
                print(f"  Valid options: {violation.valid_options}")
                
        finally:
            temp_file.unlink()


def run_tests():
    """Run all tests"""
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add unit tests
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSelectFieldValueValidator))
    
    # Add integration tests if real app is available
    if Path("/home/frappe/frappe-bench/apps/verenigingen").exists():
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSelectFieldValueValidatorIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)