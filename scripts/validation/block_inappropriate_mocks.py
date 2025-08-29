#!/usr/bin/env python3
"""
Pre-commit Hook: Block Inappropriate Mocks in Test Files
Phase 4 Week 3 - Mock Prevention Enforcement

Prevents inappropriate mocks from being introduced in test files based on the
systematic mock elimination strategy. Enforces A+ testing standards by blocking
business logic mocks while allowing legitimate external service mocks.

Usage:
    python block_inappropriate_mocks.py test_file1.py test_file2.py
    
Exit codes:
    0: No inappropriate mocks found
    1: Inappropriate mocks detected (blocks commit)
"""

import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict


class MockPatternValidator:
    """
    Validates test files against inappropriate mock patterns
    Based on Phase 4 Week 3 mock classification system
    """
    
    def __init__(self):
        # Patterns that are PROHIBITED - these block commits
        self.prohibited_patterns = [
            # Database operation mocks (core business logic) - matches any module path
            (r"@patch\(['\"][^'\"]*frappe\.db\.get_value", "Database query mocks are prohibited - use real database operations"),
            (r"@patch\(['\"][^'\"]*frappe\.db\.exists", "Database existence mocks are prohibited - use real database checks"),
            (r"@patch\(['\"][^'\"]*frappe\.db\.sql", "SQL query mocks are prohibited - use real database queries"),
            (r"@patch\(['\"][^'\"]*frappe\.db\.count", "Database count mocks are prohibited - use real count operations"),
            
            # Document operation mocks (core business logic) - matches any module path
            (r"@patch\(['\"][^'\"]*frappe\.get_doc", "Document retrieval mocks are prohibited - use real document operations"),
            (r"@patch\(['\"][^'\"]*frappe\.get_all", "Document listing mocks are prohibited - use real document queries"),
            (r"@patch\(['\"][^'\"]*frappe\.new_doc", "Document creation mocks are prohibited - use real document creation"),
            
            # Internal business logic mocks
            (r"@patch\(['\"][^'\"]*\.validate_", "Validation function mocks are prohibited - test real validation logic"),
            (r"@patch\(['\"][^'\"]*\.save\b", "Document save mocks are prohibited - use real document persistence"),
            (r"@patch\(['\"][^'\"]*\.insert\b", "Document insert mocks are prohibited - use real document creation"),
            (r"@patch\(['\"][^'\"]*\.submit\b", "Document submit mocks are prohibited - use real submission workflow"),
            
            # Template and rendering mocks (internal presentation logic)
            (r"@patch\(['\"]frappe\.render_template", "Template rendering mocks are prohibited - use real template generation"),
            
            # Permission bypass detection
            (r"ignore_permissions\s*=\s*True", "Permission bypasses are prohibited - use proper permission validation"),
            
            # Specific business logic mocks identified in Week 3
            (r"@patch\(['\"][^'\"]*send_payment_reminder_email", "Internal email generation mocks prohibited - mock only frappe.sendmail"),
            (r"@patch\(['\"][^'\"]*get_data\b", "Report generation mocks prohibited - use real database queries"),
            (r"@patch\(['\"][^'\"]*create_membership_invoice", "Invoice creation mocks prohibited - use real business logic"),
            (r"@patch\(['\"][^'\"]*suspend_member", "Suspension workflow mocks prohibited - test real suspension logic"),
            (r"@patch\(['\"][^'\"]*get_member_suspension_status", "Status query mocks prohibited - use real database operations"),
        ]
        
        # Patterns that are LEGITIMATE - these are allowed
        self.legitimate_patterns = [
            # External service mocks (appropriate)
            r"@patch\(['\"]frappe\.sendmail",
            r"@patch\(['\"]mollie\.",
            r"@patch\(['\"]eboekhouden\.",
            r"@patch\(['\"]sms_gateway\.",
            r"@patch\(['\"]postal_code_api\.",
            r"@patch\(['\"]external_bank_api\.",
            r"@patch\(['\"]requests\.",
        ]
        
    def check_file(self, filepath: str) -> List[Tuple[int, str, str]]:
        """
        Check a file for inappropriate mock patterns
        
        Returns:
            List of (line_number, line_content, violation_message) tuples
        """
        violations = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line_stripped = line.strip()
                    
                    # Skip comments and empty lines
                    if not line_stripped or line_stripped.startswith('#'):
                        continue
                    
                    # Check if this line contains a legitimate mock first
                    is_legitimate = any(
                        re.search(pattern, line, re.IGNORECASE) 
                        for pattern in self.legitimate_patterns
                    )
                    
                    if is_legitimate:
                        continue  # Skip legitimate mocks
                    
                    # Check for prohibited patterns
                    for pattern, message in self.prohibited_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            violations.append((line_num, line_stripped, message))
                            
        except Exception as e:
            violations.append((0, f"Error reading file: {e}", "File processing error"))
            
        return violations


def format_violations(filepath: str, violations: List[Tuple[int, str, str]]) -> str:
    """Format violations for display"""
    if not violations:
        return ""
    
    output = [f"\n❌ INAPPROPRIATE MOCKS DETECTED in {filepath}:"]
    output.append("=" * 60)
    
    for line_num, line_content, message in violations:
        output.append(f"Line {line_num}: {message}")
        output.append(f"   Code: {line_content}")
        output.append("")
    
    output.append("🔧 REMEDIATION:")
    output.append("   - Replace mocked business logic with real operations")
    output.append("   - Use Enhanced Test Factory for realistic test data")
    output.append("   - Mock only external services (frappe.sendmail, mollie, etc.)")
    output.append("   - See TESTING_PATTERNS_GUIDE.md for A+ patterns")
    output.append("")
    
    return "\n".join(output)


def main():
    """Main entry point for pre-commit hook"""
    if len(sys.argv) < 2:
        print("Usage: python block_inappropriate_mocks.py test_file1.py [test_file2.py ...]")
        sys.exit(1)
    
    validator = MockPatternValidator()
    total_violations = 0
    
    print("🔍 Scanning test files for inappropriate mocks...")
    print("   Based on Phase 4 Week 3 systematic mock elimination strategy")
    print("")
    
    for filepath in sys.argv[1:]:
        # Only check test files
        if not ('test' in Path(filepath).name.lower() or 'test' in str(Path(filepath).parent)):
            continue
            
        violations = validator.check_file(filepath)
        
        if violations:
            print(format_violations(filepath, violations))
            total_violations += len(violations)
        else:
            print(f"✅ {filepath} - No inappropriate mocks detected")
    
    if total_violations > 0:
        print(f"\n🚫 COMMIT BLOCKED: {total_violations} inappropriate mock(s) detected")
        print("\n📚 RESOURCES:")
        print("   - TESTING_PATTERNS_GUIDE.md - A+ testing patterns")
        print("   - Enhanced Test Factory - Real test data generation")
        print("   - HTTP Integration Testing - Test through security framework")
        print("")
        print("💡 QUICK FIX:")
        print("   Replace @patch('frappe.db.*') with real database operations")
        print("   Replace @patch('frappe.get_doc') with Enhanced Test Factory")
        print("   Mock only external services: frappe.sendmail, mollie, etc.")
        sys.exit(1)
    else:
        print(f"\n✅ ALL CLEAR: No inappropriate mocks detected")
        print("   A+ testing standards maintained!")
        sys.exit(0)


if __name__ == "__main__":
    main()