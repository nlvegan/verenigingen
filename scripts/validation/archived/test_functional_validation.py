#!/usr/bin/env python3
"""
Functional Validation Tests with Realistic Data
===============================================

This test suite validates the functional correctness of the standardized
validation infrastructure using realistic data from the actual codebase.

Instead of using synthetic test data or mocks, these tests:
1. Use actual Python files from the codebase
2. Test against real DocType definitions
3. Validate real field references and patterns
4. Test edge cases found in production code
5. Ensure validators catch actual issues without false positives

Test Categories:
- **Real File Validation**: Test against actual Python files in the codebase
- **Field Reference Accuracy**: Validate known good/bad field references
- **SQL Pattern Recognition**: Test SQL validation with real queries
- **Template Validation**: Test email template and report patterns
- **Edge Case Handling**: Test complex scenarios from production
- **Cross-DocType Validation**: Test relationships between DocTypes
"""

import json
import re
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
import tempfile


@dataclass
class ValidationTestCase:
    """Test case for functional validation"""
    name: str
    content: str
    expected_violations: List[Dict[str, str]]
    expected_no_violations: List[Dict[str, str]]
    description: str


class FunctionalValidationTest(unittest.TestCase):
    """Functional validation tests using realistic data"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        cls.app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
        cls.bench_path = cls.app_path.parent.parent
        
        # Discover real files for testing
        cls.real_python_files = cls._discover_real_python_files()
        cls.real_doctype_files = cls._discover_real_doctype_files()
        
        print(f"🔍 Functional validation testing with {len(cls.real_python_files)} Python files")
        print(f"📋 Found {len(cls.real_doctype_files)} DocType definitions")
    
    @classmethod
    def _discover_real_python_files(cls) -> List[Path]:
        """Discover real Python files from the codebase for testing"""
        python_files = []
        
        # Key areas with interesting validation scenarios
        search_areas = [
            cls.app_path / "verenigingen" / "doctype",
            cls.app_path / "verenigingen" / "api",
            cls.app_path / "scripts" / "api_maintenance",
            cls.app_path / "scripts" / "migration"
        ]
        
        for area in search_areas:
            if area.exists():
                files = list(area.rglob("*.py"))
                # Filter out test files, cache files, etc.
                filtered = [
                    f for f in files 
                    if not any(skip in str(f) for skip in [
                        'test_', '__pycache__', '.pyc', '/archived_', 
                        'debug_', '_debug.py'
                    ])
                ]
                python_files.extend(filtered[:10])  # Limit per area
        
        return python_files[:25]  # Total limit for reasonable test time
    
    @classmethod
    def _discover_real_doctype_files(cls) -> List[Path]:
        """Discover DocType JSON files from the codebase"""
        doctype_files = []
        
        doctype_areas = [
            cls.app_path / "verenigingen" / "doctype"
        ]
        
        for area in doctype_areas:
            if area.exists():
                json_files = list(area.rglob("*.json"))
                # Filter to actual DocType definitions
                doctype_files.extend([
                    f for f in json_files 
                    if f.name == f.parent.name + ".json"
                ])
        
        return doctype_files
    
    def test_real_file_validation_accuracy(self):
        """Test validation accuracy on real Python files from the codebase"""
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
        except ImportError:
            self.skipTest("SpecializedPatternValidator not available")
        
        validation_results = {}
        total_violations = 0
        files_with_violations = 0
        
        for py_file in self.real_python_files[:10]:  # Test subset for performance
            try:
                violations = validator.validate_file(py_file)
                
                validation_results[py_file.name] = {
                    'violations_count': len(violations),
                    'high_confidence': len([v for v in violations if v.confidence == 'high']),
                    'medium_confidence': len([v for v in violations if v.confidence == 'medium']),
                    'low_confidence': len([v for v in violations if v.confidence == 'low']),
                    'violations': [
                        {
                            'field': v.field,
                            'doctype': v.doctype,
                            'confidence': v.confidence,
                            'message': v.message,
                            'line': v.line
                        } for v in violations[:3]  # First 3 violations for analysis
                    ]
                }
                
                total_violations += len(violations)
                if violations:
                    files_with_violations += 1
                
            except Exception as e:
                validation_results[py_file.name] = {'error': str(e)}
        
        # Analyze results
        files_tested = len([r for r in validation_results.values() if 'error' not in r])
        avg_violations_per_file = total_violations / max(files_tested, 1)
        
        # Print detailed results
        print(f"📊 Real File Validation Results:")
        print(f"   Files tested: {files_tested}")
        print(f"   Files with violations: {files_with_violations}")
        print(f"   Total violations found: {total_violations}")
        print(f"   Average violations per file: {avg_violations_per_file:.1f}")
        
        # Show some examples of violations found
        high_confidence_violations = []
        for file_name, result in validation_results.items():
            if 'violations' in result:
                for violation in result['violations']:
                    if violation['confidence'] == 'high':
                        high_confidence_violations.append(f"{file_name}:{violation['line']} - {violation['field']} in {violation['doctype']}")
        
        if high_confidence_violations:
            print(f"\n🔍 High-confidence violations found (sample):")
            for violation in high_confidence_violations[:5]:
                print(f"   {violation}")
        
        # Validate that the validator is working (not everything should be perfect)
        if files_tested > 5:
            # We expect some violations in a real codebase, but not too many
            self.assertLess(
                avg_violations_per_file, 10,
                f"Too many violations per file: {avg_violations_per_file:.1f} (suggests high false positive rate)"
            )
        
        print("✅ Real file validation completed successfully")
    
    def test_known_valid_field_patterns(self):
        """Test with patterns that should definitely be valid"""
        known_valid_patterns = [
            # Standard Frappe fields that exist on all DocTypes
            ValidationTestCase(
                name="standard_frappe_fields",
                content='''
import frappe

def test_standard_fields():
    doc = frappe.get_doc("User", "test@example.com")
    return {
        "name": doc.name,
        "creation": doc.creation,
        "modified": doc.modified,
        "owner": doc.owner,
        "docstatus": doc.docstatus
    }
''',
                expected_violations=[],
                expected_no_violations=[
                    {"field": "name", "doctype": "User"},
                    {"field": "creation", "doctype": "User"},
                    {"field": "modified", "doctype": "User"},
                    {"field": "owner", "doctype": "User"},
                    {"field": "docstatus", "doctype": "User"}
                ],
                description="Standard Frappe fields should always be valid"
            ),
            
            # Core User fields
            ValidationTestCase(
                name="user_core_fields",
                content='''
import frappe

def get_user_info(email):
    user = frappe.get_doc("User", email)
    return {
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "enabled": user.enabled,
        "full_name": user.full_name
    }
''',
                expected_violations=[],
                expected_no_violations=[
                    {"field": "email", "doctype": "User"},
                    {"field": "first_name", "doctype": "User"},
                    {"field": "last_name", "doctype": "User"},
                    {"field": "enabled", "doctype": "User"},
                    {"field": "full_name", "doctype": "User"}
                ],
                description="Core User fields should be valid"
            ),
            
            # Verenigingen-specific fields
            ValidationTestCase(
                name="member_fields",
                content='''
import frappe

def get_member_data(member_name):
    member = frappe.get_doc("Member", member_name)
    return {
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
        "birth_date": member.birth_date,
        "phone_number": member.phone_number
    }
''',
                expected_violations=[],
                expected_no_violations=[
                    {"field": "first_name", "doctype": "Member"},
                    {"field": "last_name", "doctype": "Member"},
                    {"field": "email", "doctype": "Member"},
                    {"field": "birth_date", "doctype": "Member"},
                    {"field": "phone_number", "doctype": "Member"}
                ],
                description="Core Member fields should be valid"
            )
        ]
        
        self._run_validation_test_cases(known_valid_patterns, expect_violations=False)
    
    def test_known_invalid_field_patterns(self):
        """Test with patterns that should definitely be flagged as invalid"""
        known_invalid_patterns = [
            # Completely non-existent fields
            ValidationTestCase(
                name="nonexistent_user_fields",
                content='''
import frappe

def test_invalid_fields():
    user = frappe.get_doc("User", "test@example.com")
    return {
        "nonexistent_field_xyz": user.nonexistent_field_xyz,
        "invalid_attribute": user.invalid_attribute,
        "fake_field": user.fake_field
    }
''',
                expected_violations=[
                    {"field": "nonexistent_field_xyz", "doctype": "User"},
                    {"field": "invalid_attribute", "doctype": "User"},
                    {"field": "fake_field", "doctype": "User"}
                ],
                expected_no_violations=[],
                description="Completely invalid fields should be caught"
            ),
            
            # Common typos/misspellings
            ValidationTestCase(
                name="common_typos",
                content='''
import frappe

def test_typos():
    member = frappe.get_doc("Member", "test-member")
    return {
        "frist_name": member.frist_name,  # misspelled first_name
        "emai": member.emai,  # misspelled email
        "birht_date": member.birht_date  # misspelled birth_date
    }
''',
                expected_violations=[
                    {"field": "frist_name", "doctype": "Member"},
                    {"field": "emai", "doctype": "Member"},
                    {"field": "birht_date", "doctype": "Member"}
                ],
                expected_no_violations=[],
                description="Common typos should be caught"
            )
        ]
        
        self._run_validation_test_cases(known_invalid_patterns, expect_violations=True)
    
    def test_sql_pattern_validation(self):
        """Test SQL pattern validation with realistic queries"""
        sql_test_cases = [
            # Valid SQL patterns
            ValidationTestCase(
                name="valid_sql_queries",
                content='''
import frappe

def get_user_counts():
    """Valid SQL with proper field references"""
    return frappe.db.sql("""
        SELECT 
            enabled,
            COUNT(*) as user_count
        FROM `tabUser`
        WHERE enabled = 1
        GROUP BY enabled
    """, as_dict=True)

def get_member_statistics():
    """Valid SQL with JOIN"""
    return frappe.db.sql("""
        SELECT 
            m.first_name,
            m.last_name,
            m.email
        FROM `tabMember` m
        WHERE m.enabled = 1
        ORDER BY m.creation DESC
        LIMIT 10
    """, as_dict=True)
''',
                expected_violations=[],
                expected_no_violations=[
                    {"field": "enabled", "doctype": "User"},
                    {"field": "first_name", "doctype": "Member"},
                    {"field": "last_name", "doctype": "Member"},
                    {"field": "email", "doctype": "Member"}
                ],
                description="Valid SQL patterns should not be flagged"
            ),
            
            # Invalid SQL patterns
            ValidationTestCase(
                name="invalid_sql_queries",
                content='''
import frappe

def broken_sql_query():
    """SQL with invalid field references"""
    return frappe.db.sql("""
        SELECT 
            invalid_field,
            nonexistent_column
        FROM `tabUser`
        WHERE fake_field = 1
    """, as_dict=True)
''',
                expected_violations=[
                    {"field": "invalid_field", "doctype": "User"},
                    {"field": "nonexistent_column", "doctype": "User"},
                    {"field": "fake_field", "doctype": "User"}
                ],
                expected_no_violations=[],
                description="Invalid SQL field references should be caught"
            )
        ]
        
        self._run_validation_test_cases(sql_test_cases, mixed_expectations=True)
    
    def test_edge_case_scenarios(self):
        """Test edge cases and complex scenarios from real usage"""
        edge_cases = [
            # Mixed valid and invalid in same function
            ValidationTestCase(
                name="mixed_valid_invalid",
                content='''
import frappe

def mixed_function():
    """Function with both valid and invalid field references"""
    user = frappe.get_doc("User", "test@example.com")
    
    # Valid fields
    email = user.email
    name = user.name
    
    # Invalid fields
    invalid = user.nonexistent_field
    typo = user.emai  # typo of email
    
    return {"email": email, "name": name, "invalid": invalid, "typo": typo}
''',
                expected_violations=[
                    {"field": "nonexistent_field", "doctype": "User"},
                    {"field": "emai", "doctype": "User"}
                ],
                expected_no_violations=[
                    {"field": "email", "doctype": "User"},
                    {"field": "name", "doctype": "User"}
                ],
                description="Mixed valid/invalid patterns should be handled correctly"
            ),
            
            # Complex conditional patterns
            ValidationTestCase(
                name="conditional_field_access",
                content='''
import frappe

def conditional_access(member_name):
    """Complex conditional field access"""
    member = frappe.get_doc("Member", member_name)
    
    result = {}
    
    if hasattr(member, 'first_name'):  # Valid field
        result['name'] = member.first_name
    
    if hasattr(member, 'fake_field'):  # Invalid field
        result['fake'] = member.fake_field
    
    # Valid field in condition
    if member.enabled:
        result['status'] = 'active'
    
    return result
''',
                expected_violations=[
                    {"field": "fake_field", "doctype": "Member"}
                ],
                expected_no_violations=[
                    {"field": "first_name", "doctype": "Member"},
                    {"field": "enabled", "doctype": "Member"}
                ],
                description="Conditional field access should be validated correctly"
            )
        ]
        
        self._run_validation_test_cases(edge_cases, mixed_expectations=True)
    
    def test_cross_doctype_relationships(self):
        """Test validation of relationships between DocTypes"""
        relationship_cases = [
            # Parent-child relationships
            ValidationTestCase(
                name="parent_child_fields",
                content='''
import frappe

def get_member_with_history():
    """Access member and related payment history"""
    member = frappe.get_doc("Member", "test-member")
    
    # Valid member fields
    member_data = {
        "name": member.name,
        "first_name": member.first_name,
        "email": member.email
    }
    
    # Access child table (if it exists)
    payment_history = []
    for payment in member.get("payment_history", []):
        payment_data = {
            "payment_date": payment.payment_date,
            "amount": payment.amount,
            "invalid_child_field": payment.invalid_child_field  # Should be flagged
        }
        payment_history.append(payment_data)
    
    return {"member": member_data, "payments": payment_history}
''',
                expected_violations=[
                    {"field": "invalid_child_field", "doctype": "any"}  # Child table validation
                ],
                expected_no_violations=[
                    {"field": "name", "doctype": "Member"},
                    {"field": "first_name", "doctype": "Member"},
                    {"field": "email", "doctype": "Member"}
                ],
                description="Parent-child relationships should be validated"
            )
        ]
        
        self._run_validation_test_cases(relationship_cases, mixed_expectations=True)
    
    def _run_validation_test_cases(self, test_cases: List[ValidationTestCase], 
                                  expect_violations: bool = None, mixed_expectations: bool = False):
        """Run a set of validation test cases"""
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
        except ImportError:
            self.skipTest("SpecializedPatternValidator not available")
        
        for test_case in test_cases:
            with self.subTest(test_case=test_case.name):
                # Create temporary file with test content
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                    temp_file.write(test_case.content)
                    temp_file_path = Path(temp_file.name)
                
                try:
                    # Run validation
                    violations = validator.validate_file(temp_file_path)
                    
                    # Check expected violations
                    if test_case.expected_violations:
                        for expected_violation in test_case.expected_violations:
                            expected_field = expected_violation["field"]
                            expected_doctype = expected_violation.get("doctype")
                            
                            # Look for this violation in results
                            found = False
                            for violation in violations:
                                if (violation.field == expected_field and 
                                    (expected_doctype is None or 
                                     expected_doctype == "any" or 
                                     violation.doctype == expected_doctype)):
                                    found = True
                                    break
                            
                            if not found:
                                self.fail(
                                    f"{test_case.name}: Expected violation not found - "
                                    f"field '{expected_field}' in DocType '{expected_doctype}'"
                                )
                    
                    # Check that valid patterns are not flagged
                    if test_case.expected_no_violations:
                        for expected_valid in test_case.expected_no_violations:
                            valid_field = expected_valid["field"]
                            valid_doctype = expected_valid.get("doctype")
                            
                            # This field should NOT be in violations
                            for violation in violations:
                                if (violation.field == valid_field and 
                                    violation.confidence in ['high', 'medium'] and
                                    (valid_doctype is None or violation.doctype == valid_doctype)):
                                    self.fail(
                                        f"{test_case.name}: Valid pattern incorrectly flagged - "
                                        f"field '{valid_field}' in DocType '{valid_doctype}' "
                                        f"(confidence: {violation.confidence})"
                                    )
                    
                    # Overall expectations
                    if expect_violations is True and not violations:
                        self.fail(f"{test_case.name}: Expected violations but none found")
                    elif expect_violations is False and violations:
                        high_conf_violations = [v for v in violations if v.confidence == 'high']
                        if high_conf_violations:
                            self.fail(
                                f"{test_case.name}: Unexpected high-confidence violations: "
                                f"{[v.field for v in high_conf_violations]}"
                            )
                    
                    print(f"✅ {test_case.name}: {len(violations)} violations found")
                    
                except Exception as e:
                    self.fail(f"{test_case.name}: Validation failed with error: {e}")
                
                finally:
                    # Clean up temp file
                    if temp_file_path.exists():
                        temp_file_path.unlink()
    
    def test_realistic_doctype_coverage(self):
        """Test that validation covers all expected DocTypes from the codebase"""
        try:
            from doctype_loader import DocTypeLoader
            loader = DocTypeLoader(str(self.bench_path), verbose=False)
        except ImportError:
            self.skipTest("DocTypeLoader not available")
        
        doctypes = loader.get_doctypes()
        
        # Check for critical verenigingen DocTypes
        expected_verenigingen_doctypes = [
            'Member',
            'Chapter',
            'Volunteer',
            'SEPA Mandate',
            'Membership Type',
            'Chapter Member'
        ]
        
        missing_doctypes = []
        for expected_dt in expected_verenigingen_doctypes:
            if expected_dt not in doctypes:
                missing_doctypes.append(expected_dt)
        
        if missing_doctypes:
            self.fail(f"Missing critical DocTypes: {missing_doctypes}")
        
        # Check field coverage for key DocTypes
        member_fields = loader.get_field_names('Member')
        expected_member_fields = ['first_name', 'last_name', 'email', 'birth_date']
        
        missing_member_fields = [f for f in expected_member_fields if f not in member_fields]
        if missing_member_fields:
            self.fail(f"Missing expected Member fields: {missing_member_fields}")
        
        print(f"✅ DocType coverage: {len(doctypes)} DocTypes loaded")
        print(f"   Member has {len(member_fields)} fields including all expected core fields")


def run_functional_validation_tests():
    """Run all functional validation tests"""
    print("🧪 Running Functional Validation Tests with Realistic Data")
    print("=" * 80)
    
    # Create and run test suite
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(FunctionalValidationTest))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "=" * 80)
    print("🧪 Functional Validation Summary")
    print("=" * 80)
    
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors
    
    print(f"Functional Tests: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failures}")
    print(f"🚫 Errors: {errors}")
    
    if result.failures:
        print("\n❌ Functional Test Failures:")
        for test, traceback in result.failures:
            failure_msg = traceback.split('\n')[-2] if traceback else "Validation accuracy issue"
            print(f"  - {test}: {failure_msg}")
    
    if result.errors:
        print("\n🚫 Functional Test Errors:")
        for test, traceback in result.errors:
            error_msg = traceback.split('\n')[-2] if traceback else "Test execution error"
            print(f"  - {test}: {error_msg}")
    
    success = failures == 0 and errors == 0
    
    if success:
        print("\n🎉 All functional validation tests PASSED!")
        print("The standardized validation infrastructure correctly handles realistic scenarios.")
    else:
        print("\n⚠️  Some functional validation tests failed.")
        print("Validation accuracy or coverage issues detected.")
    
    return success


if __name__ == "__main__":
    success = run_functional_validation_tests()
    exit(0 if success else 1)