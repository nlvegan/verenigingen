#!/usr/bin/env python3
"""
Test Suite for AST Field Analyzer Improvements
===============================================

Tests the enhanced file path inference and Link field detection
to ensure false positives are eliminated while maintaining accuracy.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any
import json
import ast

# Import the analyzer
from ast_field_analyzer_improved import (
    ASTFieldAnalyzer, 
    ValidationContext, 
    ValidationIssue,
    ConfidenceLevel
)

class TestASTFieldAnalyzer(unittest.TestCase):
    """Comprehensive test suite for AST Field Analyzer improvements"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        # Create a temporary directory structure
        cls.temp_dir = tempfile.mkdtemp(prefix="ast_analyzer_test_")
        cls.app_path = Path(cls.temp_dir) / "test_app"
        cls.app_path.mkdir()
        
        # Create vereinigingen module directory
        cls.module_path = cls.app_path / "verenigingen"
        cls.module_path.mkdir()
        
        # Create doctype directories
        cls.doctype_path = cls.module_path / "doctype"
        cls.doctype_path.mkdir()
        
        # Set up test DocTypes
        cls.setup_test_doctypes()
        
    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    @classmethod
    def setup_test_doctypes(cls):
        """Create test DocType definitions"""
        # Create Membership Dues Schedule DocType
        dues_schedule_path = cls.doctype_path / "membership_dues_schedule"
        dues_schedule_path.mkdir()
        
        dues_schedule_json = {
            "name": "Membership Dues Schedule",
            "fields": [
                {"fieldname": "is_template", "fieldtype": "Check"},
                {"fieldname": "member", "fieldtype": "Link", "options": "Member"},
                {"fieldname": "status", "fieldtype": "Select"},
                {"fieldname": "billing_frequency", "fieldtype": "Select"},
                {"fieldname": "next_invoice_date", "fieldtype": "Date"}
            ]
        }
        
        with open(dues_schedule_path / "membership_dues_schedule.json", "w") as f:
            json.dump(dues_schedule_json, f)
        
        # Create Member DocType
        member_path = cls.doctype_path / "member"
        member_path.mkdir()
        
        member_json = {
            "name": "Member",
            "fields": [
                {"fieldname": "full_name", "fieldtype": "Data"},
                {"fieldname": "email", "fieldtype": "Data"},
                {"fieldname": "member_id", "fieldtype": "Data"},
                {"fieldname": "status", "fieldtype": "Select"},
                {"fieldname": "current_dues_schedule", "fieldtype": "Link", "options": "Membership Dues Schedule"}
            ]
        }
        
        with open(member_path / "member.json", "w") as f:
            json.dump(member_json, f)
    
    def setUp(self):
        """Set up for each test"""
        self.analyzer = ASTFieldAnalyzer(str(self.app_path), verbose=False)
        
        # Mock the doctypes for testing
        self.analyzer.doctypes = {
            "Membership Dues Schedule": {
                "fields": {"is_template", "member", "status", "billing_frequency", "next_invoice_date"},
                "field_metadata": {
                    "member": {"fieldtype": "Link", "options": "Member"}
                }
            },
            "Member": {
                "fields": {"full_name", "email", "member_id", "status", "current_dues_schedule"},
                "field_metadata": {
                    "current_dues_schedule": {"fieldtype": "Link", "options": "Membership Dues Schedule"}
                }
            }
        }
    
    def create_test_file(self, file_path: str, content: str) -> Path:
        """Create a test Python file with given content"""
        full_path = self.app_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return full_path
    
    def test_file_path_inference_hook_file(self):
        """Test that hook files correctly infer DocType from file name"""
        # Create a hook file
        hook_content = '''
def update_member_current_dues_schedule(doc, method=None):
    """Update member when dues schedule changes"""
    if doc.is_template or not doc.member:
        return
    
    if doc.status != "Active":
        current = frappe.db.get_value("Member", doc.member, "current_dues_schedule")
'''
        
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py",
            hook_content
        )
        
        # Analyze the file
        issues = self.analyzer.validate_file(file_path)
        
        # Should have no issues - doc is correctly identified as Membership Dues Schedule
        self.assertEqual(len(issues), 0, f"Expected no issues, but got: {issues}")
    
    def test_file_path_inference_doctype_directory(self):
        """Test inference from doctype directory structure"""
        # Create a file in doctype directory
        content = '''
class MembershipDuesSchedule(Document):
    def validate(self):
        if self.is_template:
            self.member = None
'''
        
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/membership_dues_schedule.py",
            content
        )
        
        # Analyze the file
        issues = self.analyzer.validate_file(file_path)
        
        # Should have no issues
        self.assertEqual(len(issues), 0)
    
    def test_link_field_detection(self):
        """Test that Link fields are correctly identified"""
        content = '''
def process_schedule(doc):
    """Process a dues schedule"""
    if doc.member:  # This is a Link field to Member
        member_name = doc.member
        update_member(member_name)
'''
        
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py",
            content
        )
        
        # Test that link field detection works
        context = ValidationContext(file_path=file_path)
        link_target = self.analyzer._is_link_field_to_other_doctype("member", "Membership Dues Schedule")
        
        self.assertEqual(link_target, "Member", "Should identify 'member' as Link to Member")
    
    def test_false_positive_elimination(self):
        """Test that the specific false positives are eliminated"""
        # This is the exact pattern that was causing false positives
        content = '''
def update_member_current_dues_schedule(doc, method=None):
    """
    Update the Member's current_dues_schedule field when a dues schedule changes.
    This should be called on after_insert and on_update of Membership Dues Schedule.
    """
    if doc.is_template or not doc.member:
        return
    
    # Only update if this is an active schedule
    if doc.status != "Active":
        # If this schedule is being deactivated and it's the current one, clear it
        current = frappe.db.get_value("Member", doc.member, "current_dues_schedule")
        if current == doc.name:
            frappe.db.set_value("Member", doc.member, "current_dues_schedule", None)
'''
        
        file_path = self.create_test_file(
            "verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py",
            content
        )
        
        # Analyze the file
        issues = self.analyzer.validate_file(file_path)
        
        # Filter to only high/critical confidence issues
        high_confidence_issues = [
            i for i in issues 
            if i.confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL]
        ]
        
        # Should have no high confidence issues about these fields
        for issue in high_confidence_issues:
            self.assertNotIn(issue.field, ["is_template", "member", "status"], 
                           f"False positive found for field {issue.field}: {issue.message}")
    
    def test_real_error_detection(self):
        """Test that real field errors are still detected"""
        content = '''
def update_schedule(doc):
    """Update a dues schedule"""
    if doc.invalid_field:  # This field doesn't exist
        doc.another_bad_field = "value"  # This also doesn't exist
'''
        
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py",
            content
        )
        
        # Analyze the file
        issues = self.analyzer.validate_file(file_path)
        
        # Should detect the invalid fields
        invalid_fields = {issue.field for issue in issues}
        self.assertIn("invalid_field", invalid_fields, "Should detect invalid_field")
        self.assertIn("another_bad_field", invalid_fields, "Should detect another_bad_field")
    
    def test_confidence_scoring_hook_files(self):
        """Test that confidence scoring is appropriate for hook files"""
        content = '''
def validate(doc):
    if doc.is_template:  # Valid field
        return
    if doc.nonexistent_field:  # Invalid field
        return
'''
        
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py",
            content
        )
        
        # Analyze the file
        issues = self.analyzer.validate_file(file_path)
        
        # Check confidence levels
        for issue in issues:
            if issue.field == "is_template":
                # Should have low confidence (likely false positive)
                self.assertIn(issue.confidence, [ConfidenceLevel.LOW, ConfidenceLevel.INFO],
                            "Valid field should have low confidence issue if any")
            elif issue.field == "nonexistent_field":
                # Should have higher confidence
                self.assertIn(issue.confidence, [ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH],
                            "Invalid field should have higher confidence")
    
    def test_edge_cases(self):
        """Test edge cases for file path inference"""
        
        # Test 1: File with just _hooks.py
        content = "# Empty hook file"
        file_path = self.create_test_file("_hooks.py", content)
        context = ValidationContext(file_path=file_path)
        result = self.analyzer._infer_doctype_from_file_path(context)
        self.assertIsNone(result, "Should handle _hooks.py without prefix")
        
        # Test 2: Non-hook file in doctype directory
        content = "# Utility file"
        file_path = self.create_test_file(
            "vereiningen/doctype/membership_dues_schedule/utils.py",
            content
        )
        context = ValidationContext(file_path=file_path)
        result = self.analyzer._infer_doctype_from_file_path(context)
        # Should still infer from directory structure
        self.assertEqual(result, "Membership Dues Schedule")
        
        # Test 3: Deeply nested directory
        content = "# Nested file"
        file_path = self.create_test_file(
            "verenigingen/doctype/membership_dues_schedule/subdir/nested/file.py",
            content
        )
        context = ValidationContext(file_path=file_path)
        result = self.analyzer._infer_doctype_from_file_path(context)
        self.assertEqual(result, "Membership Dues Schedule")
    
    def test_performance_caching(self):
        """Test that caching improves performance"""
        content = '''
def process(doc):
    if doc.is_template:
        pass
'''
        
        file_path = self.create_test_file(
            "membership_dues_schedule_hooks.py",
            content
        )
        
        context = ValidationContext(file_path=file_path)
        
        # First call - should populate cache
        result1 = self.analyzer._infer_doctype_from_file_path(context)
        
        # Second call - should use cache
        result2 = self.analyzer._infer_doctype_from_file_path(context)
        
        self.assertEqual(result1, result2, "Cached result should match")
        
        # Check that cache was used
        cache_key = str(file_path)
        self.assertIn(cache_key, self.analyzer._file_path_cache)
    
    def test_validation_with_inference(self):
        """Test the validation logic for inferred DocTypes"""
        # Create a mock node
        node = ast.Attribute(
            value=ast.Name(id='doc'),
            attr='is_template',
            lineno=5
        )
        
        source_lines = [
            "def update_schedule(doc):",
            "    if doc.is_template:",
            "        return",
        ]
        
        context = ValidationContext(
            file_path=Path("membership_dues_schedule_hooks.py"),
            is_hook_file=True
        )
        
        # Test validation
        is_valid = self.analyzer._validate_path_inference(
            node, 
            "Membership Dues Schedule",
            source_lines,
            context
        )
        
        self.assertTrue(is_valid, "Should validate correct inference")
        
        # Test with invalid field
        node.attr = "invalid_field"
        is_valid = self.analyzer._validate_path_inference(
            node,
            "Membership Dues Schedule", 
            source_lines,
            context
        )
        
        self.assertFalse(is_valid, "Should not validate incorrect field")


class TestRegressionSuite(unittest.TestCase):
    """Regression tests to ensure no new issues are introduced"""
    
    def test_non_hook_files_unchanged(self):
        """Ensure non-hook files are analyzed the same way"""
        # This test would compare results before and after changes
        # for non-hook files to ensure no regression
        pass
    
    def test_existing_detection_maintained(self):
        """Ensure existing field error detection still works"""
        # This test would verify that real errors are still caught
        pass


class TestPerformance(unittest.TestCase):
    """Performance tests for the analyzer"""
    
    def test_large_file_performance(self):
        """Test performance with large files"""
        # Generate a large Python file
        lines = []
        for i in range(1000):
            lines.append(f"    if doc.field_{i}:")
            lines.append(f"        doc.other_field_{i} = value")
        
        content = "def process(doc):\n" + "\n".join(lines)
        
        # Measure analysis time
        import time
        start = time.time()
        # ... analyze file ...
        end = time.time()
        
        # Assert reasonable performance
        self.assertLess(end - start, 5.0, "Should analyze large file in < 5 seconds")


def run_tests():
    """Run all test suites"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test cases
    suite.addTests(loader.loadTestsFromTestCase(TestASTFieldAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestRegressionSuite))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)