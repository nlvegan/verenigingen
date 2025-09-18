#!/usr/bin/env python3
"""
Test Quality Enforcement Script
==============================

Pre-commit hook to prevent problematic testing patterns that create false confidence.
This script blocks new mock abuse, permission bypasses, and ensures compliance with
testing standards established in the Testing Reformation Plan.

Usage:
    python scripts/validation/test_quality_enforcer.py [files...]

Exit codes:
    0: All files pass validation
    1: Validation failures found
    2: Script error

Validation Rules:
- Block new database operation mocks
- Require justification for external service mocks
- Prevent permission bypasses in test files
- Enforce Enhanced Test Factory usage for integration tests
- Validate field references against DocType schemas
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class TestQualityEnforcer:
    """Enforces test quality standards and blocks problematic patterns"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        
        # Prohibited mock patterns (refined to avoid false positives)
        self.prohibited_mocks = [
            # Core database operations that must never be mocked
            r"patch\s*\(\s*['\"]frappe\.get_doc['\"]",
            r"patch\s*\(\s*['\"]frappe\.get_all['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.exists['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.set_value['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.sql['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.get_list['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.count['\"]"
        ]
        
        # Configuration access patterns (allowed for external service config)
        self.allowed_config_mocks = [
            r"frappe\.db\.get_single_value.*Settings",
            r"frappe\.db\.get_global_config",
            r"frappe\.db\.get_single.*Settings"
        ]
        
        # Mock justification taxonomy - categorized by justification type
        self.external_service_mocks = [
            r"patch\s*\(\s*['\"]frappe\.sendmail['\"]",  # Email service
            r"patch\s*\(\s*['\"]requests\.post['\"]",    # HTTP requests
            r"patch\s*\(\s*['\"]requests\.get['\"]",     # HTTP requests
            r"patch\s*\(\s*['\"]smtplib\.",              # SMTP service
            r"patch\s*\(\s*['\"]urllib\."                # URL operations
        ]
        
        self.infrastructure_mocks = [
            r"patch\s*\(\s*['\"]redis\.Redis['\"]",      # Redis cache
            r"patch\s*\(\s*['\"]frappe\.cache['\"]",     # Frappe cache
            r"patch\s*\(\s*['\"]celery\.",               # Background tasks
            r"patch\s*\(\s*['\"]frappe\.publish_realtime['\"]"  # WebSocket
        ]
        
        # Business logic mocks that should NEVER be allowed
        self.never_mock_patterns = [
            r"patch\s*\(\s*['\"].*validate_.*['\"]",     # Validation functions
            r"patch\s*\(\s*['\"].*business_rule.*['\"]", # Business rules
            r"patch\s*\(\s*['\"].*process_.*['\"]"       # Process functions  
        ]
        
        # Permission bypass patterns (including hidden bypasses)
        self.permission_bypasses = [
            r"ignore_permissions\s*=\s*True",
            r"\.insert\s*\(\s*ignore_permissions\s*=\s*True",
            r"\.save\s*\(\s*ignore_permissions\s*=\s*True",
            r"\.delete\s*\(\s*ignore_permissions\s*=\s*True",
            r"frappe\.set_user\s*\(\s*['\"]Administrator['\"]",  # Hidden bypass via user switching
            r"frappe\.session\.user\s*=\s*['\"]Administrator['\"]" # Direct session manipulation
        ]

    def validate_file(self, file_path: str) -> bool:
        """Validate a single test file against quality standards"""
        if not self._is_test_file(file_path):
            return True
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            file_valid = True
            
            # Check for prohibited mock patterns
            file_valid &= self._check_prohibited_mocks(file_path, content)
            
            # Check for never-mock business logic patterns
            file_valid &= self._check_never_mock_patterns(file_path, content)
            
            # Check for permission bypasses
            file_valid &= self._check_permission_bypasses(file_path, content)
            
            # Check mock justifications
            file_valid &= self._check_mock_justifications(file_path, content)
            
            # Check Enhanced Test Factory usage for integration tests
            file_valid &= self._check_enhanced_test_factory_usage(file_path, content)
            
            # Validate field references
            file_valid &= self._check_field_references(file_path, content)
            
            return file_valid
            
        except Exception as e:
            self.errors.append(f"{file_path}: Error reading file - {str(e)}")
            return False

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file that should be validated"""
        path = Path(file_path)
        
        # Check for test file patterns
        test_indicators = [
            path.name.startswith('test_'),
            '/tests/' in str(path),
            path.name.endswith('_test.py'),
            'TestCase' in path.name
        ]
        
        return any(test_indicators) and path.suffix == '.py'

    def _check_prohibited_mocks(self, file_path: str, content: str) -> bool:
        """Check for prohibited database operation mocks"""
        valid = True
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Check if line contains any prohibited mock patterns
            for pattern in self.prohibited_mocks:
                if re.search(pattern, line, re.IGNORECASE):
                    # Check if this is an allowed configuration access pattern
                    is_allowed = False
                    for allowed_pattern in self.allowed_config_mocks:
                        if re.search(allowed_pattern, line, re.IGNORECASE):
                            is_allowed = True
                            break
                    
                    if not is_allowed:
                        self.errors.append(
                            f"{file_path}:{line_num}: PROHIBITED mock pattern detected: {line.strip()}\n"
                            f"  -> Database operations must not be mocked in integration tests\n"
                            f"  -> Use real database operations with Enhanced Test Factory\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns"
                        )
                        valid = False
                    
        return valid

    def _check_never_mock_patterns(self, file_path: str, content: str) -> bool:
        """Check for business logic mocks that should never be allowed"""
        valid = True
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            for pattern in self.never_mock_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.errors.append(
                        f"{file_path}:{line_num}: BUSINESS LOGIC MOCK PROHIBITED: {line.strip()}\n"
                        f"  -> Business logic and validation functions must NEVER be mocked\n"
                        f"  -> This defeats the purpose of integration testing\n"
                        f"  -> Use real business logic to catch actual bugs\n"
                        f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns"
                    )
                    valid = False
                    
        return valid

    def _check_permission_bypasses(self, file_path: str, content: str) -> bool:
        """Check for permission bypasses in test files"""
        valid = True
        lines = content.split('\n')
        
        # Allow permission bypasses only in specific contexts
        allowed_contexts = [
            'setUp',
            'setUpClass', 
            'create_test_data',
            'tearDown',
            'cleanup'
        ]
        
        # Track if we're inside a docstring
        in_docstring = False
        docstring_delimiter = None
        
        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()
            
            # Check for docstring delimiters
            if '"""' in line:
                if not in_docstring:
                    in_docstring = True
                    docstring_delimiter = '"""'
                elif docstring_delimiter == '"""':
                    in_docstring = False
                    docstring_delimiter = None
            elif "'''" in line:
                if not in_docstring:
                    in_docstring = True
                    docstring_delimiter = "'''"
                elif docstring_delimiter == "'''":
                    in_docstring = False
                    docstring_delimiter = None
            
            # Skip documentation lines (comments and docstrings)
            if (stripped_line.startswith('#') or in_docstring):
                continue
                
            for pattern in self.permission_bypasses:
                if re.search(pattern, line, re.IGNORECASE):
                    # Check if in allowed context
                    context = self._find_function_context(lines, line_num)
                    
                    if context not in allowed_contexts:
                        self.errors.append(
                            f"{file_path}:{line_num}: PERMISSION BYPASS detected in test logic: {line.strip()}\n"
                            f"  -> Found in context: {context}\n"
                            f"  -> Permission bypasses only allowed in test setup/teardown\n"
                            f"  -> Test actual permission boundaries instead of bypassing them\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns"
                        )
                        valid = False
                        
        return valid

    def _check_mock_justifications(self, file_path: str, content: str) -> bool:
        """Check that external service and infrastructure mocks have proper justification"""
        valid = True
        lines = content.split('\n')
        
        # Combined list of all patterns requiring justification
        all_mock_patterns = self.external_service_mocks + self.infrastructure_mocks
        
        for line_num, line in enumerate(lines, 1):
            for pattern in all_mock_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Determine mock category for better error messages
                    mock_category = "external service" if pattern in self.external_service_mocks else "infrastructure"
                    
                    # Check for justification comment within 3 lines before or after
                    justification_found = False
                    
                    start_line = max(0, line_num - 4)
                    end_line = min(len(lines), line_num + 3)
                    
                    for check_line in range(start_line, end_line):
                        if check_line < len(lines):
                            comment_line = lines[check_line]
                            if ('# Mock justified:' in comment_line or
                                '# External service' in comment_line or
                                '# Mock external' in comment_line or
                                '# Infrastructure' in comment_line):
                                justification_found = True
                                break
                    
                    if not justification_found:
                        self.warnings.append(
                            f"{file_path}:{line_num}: {mock_category.title()} mock lacks justification: {line.strip()}\n"
                            f"  -> Add comment: # Mock justified: <reason>\n"
                            f"  -> Example: # Mock justified: {mock_category.title()} - email service, not business logic\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for examples"
                        )
                        
        return valid

    def _check_enhanced_test_factory_usage(self, file_path: str, content: str) -> bool:
        """Check that integration tests use Enhanced Test Factory"""
        # Skip this check for unit tests
        if 'unit/' in file_path or '_unit.py' in file_path:
            return True
            
        valid = True
        
        # Check for integration test indicators
        integration_indicators = [
            'integration/',
            'test_.*_integration.py',
            '_integration.py',
            'test_.*_real.py',
            '_real.py'
        ]
        
        is_integration_test = any(re.search(indicator, file_path) 
                                 for indicator in integration_indicators)
        
        if is_integration_test:
            # Check for Enhanced Test Factory usage
            if 'from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase' not in content:
                if 'class Test' in content and 'TestCase' in content:
                    self.errors.append(
                        f"{file_path}: Integration test must use Enhanced Test Factory\n"
                        f"  -> Import: from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase\n"
                        f"  -> Inherit from: class TestMyFeature(EnhancedTestCase)\n"
                        f"  -> See docs/testing/TESTING_STANDARDS.md for examples"
                    )
                    valid = False
                    
        return valid

    def _check_field_references(self, file_path: str, content: str) -> bool:
        """Basic field reference validation (enhanced validation in separate script)"""
        valid = True
        
        # Look for obvious field reference errors
        problematic_patterns = [
            # Note: member_name = member.name is actually CORRECT (getting document ID)
            # Removed overly broad pattern that flagged legitimate .name field usage
            r'source_record.*=.*member_name', # Opposite error: assigning string to doc variable
            r'\.non_existent_field',          # Obviously wrong field name
            r'\.fake_field',                  # Test field that doesn't exist
            r'\.test_field_123'               # Clearly made up field names
        ]
        
        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            for pattern in problematic_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.warnings.append(
                        f"{file_path}:{line_num}: Suspicious field reference: {line.strip()}\n"
                        f"  -> Verify field exists in DocType schema\n"
                        f"  -> Use Enhanced Test Factory for validated field references"
                    )
                    
        return valid

    def _find_function_context(self, lines: List[str], line_num: int) -> str:
        """Find which function contains the given line number"""
        for i in range(line_num - 1, -1, -1):
            line = lines[i].strip()
            if line.startswith('def '):
                match = re.search(r'def\s+(\w+)\s*\(', line)
                if match:
                    return match.group(1)
        return "unknown"

    def validate_files(self, file_paths: List[str]) -> bool:
        """Validate multiple files"""
        all_valid = True
        
        for file_path in file_paths:
            if os.path.exists(file_path):
                file_valid = self.validate_file(file_path)
                all_valid &= file_valid
            else:
                self.errors.append(f"File not found: {file_path}")
                all_valid = False
                
        return all_valid

    def report_results(self):
        """Print validation results"""
        if self.errors:
            print("\n🔴 TEST QUALITY VIOLATIONS FOUND:")
            print("=" * 60)
            for error in self.errors:
                print(f"\nERROR: {error}")
                
        if self.warnings:
            print("\n🟡 TEST QUALITY WARNINGS:")
            print("=" * 60)
            for warning in self.warnings:
                print(f"\nWARNING: {warning}")
                
        if not self.errors and not self.warnings:
            print("✅ All files pass test quality validation")
        elif not self.errors:
            print(f"\n✅ No critical errors found ({len(self.warnings)} warnings)")
        else:
            print(f"\n❌ {len(self.errors)} critical errors, {len(self.warnings)} warnings")
            print("\nFIX REQUIRED: Address errors before committing")
            print("See docs/testing/TESTING_STANDARDS.md for correct patterns")


def main():
    """Main entry point for pre-commit hook"""
    parser = argparse.ArgumentParser(
        description="Enforce test quality standards for Verenigingen"
    )
    parser.add_argument(
        'files', 
        nargs='*', 
        help='Files to validate (if none provided, validates all test files)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors'
    )
    
    args = parser.parse_args()
    
    enforcer = TestQualityEnforcer()
    
    if args.files:
        files_to_check = args.files
    else:
        # Find all test files if none provided
        files_to_check = []
        for root, dirs, files in os.walk('.'):
            for file in files:
                file_path = os.path.join(root, file)
                if enforcer._is_test_file(file_path):
                    files_to_check.append(file_path)
    
    success = enforcer.validate_files(files_to_check)
    enforcer.report_results()
    
    # Exit with error code if validation failed
    if not success or (args.strict and enforcer.warnings):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()