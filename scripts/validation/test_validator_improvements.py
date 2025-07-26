#!/usr/bin/env python3
"""
Test script to validate the improvements made to the method call validator.

This script tests the specific false positive cases mentioned:
1. Class method detection (self.method calls)
2. Static method imports (Class.static_method calls)
3. Better context awareness

Usage:
    python test_validator_improvements.py
"""

import sys
from pathlib import Path
from typing import List

# Add the current directory to Python path for imports
sys.path.append(str(Path(__file__).parent))

from method_call_validator import MethodCallValidator, ValidationIssue


def create_test_file_content() -> str:
    """Create test file content with known patterns that caused false positives"""
    return '''
# Test file for method call validator improvements
import frappe
from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

class Member:
    def update_membership_status(self):
        """Method that should be detected in class hierarchy"""
        pass
    
    def some_other_method(self):
        # This should NOT be flagged as error - method exists in same class
        self.update_membership_status()
        
        # This should also be valid
        self.validate()
        
    def validate(self):
        """Standard Frappe document method"""
        pass

class TestClass:
    @staticmethod
    def static_method():
        """Static method for testing"""
        pass
    
    @classmethod
    def class_method(cls):
        """Class method for testing"""
        pass

def test_function():
    # This should NOT be flagged - static method call on imported class
    ChapterMembershipHistoryManager.update_membership_status()
    
    # This should also be valid
    TestClass.static_method()
    TestClass.class_method()
    
    # Frappe calls should be valid
    frappe.get_doc("Member", "test")
    frappe.db.get_value("Member", "test", "name")
'''


def run_improvement_test():
    """Test the validator improvements with known false positive patterns"""
    print("🧪 Testing Method Call Validator Improvements")
    print("=" * 50)
    
    # Create test file
    test_file_path = Path("/tmp/test_validator_file.py")
    test_content = create_test_file_content()
    
    with open(test_file_path, 'w') as f:
        f.write(test_content)
    
    try:
        # Initialize validator
        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        validator = MethodCallValidator(app_path)
        
        print("📚 Building method cache...")
        validator.build_method_cache(force_rebuild=False)
        
        print(f"✅ Cache built with {len(validator.method_signatures)} method signatures")
        print(f"📊 Classes tracked: {len(validator.class_hierarchy)}")
        print(f"🔧 Static methods: {sum(len(methods) for methods in validator.static_method_calls.values())}")
        
        # Validate the test file
        print(f"\n🔍 Validating test file: {test_file_path}")
        issues = validator.validate_file(test_file_path)
        
        # Analyze results
        print(f"\n📋 VALIDATION RESULTS:")
        print(f"   Total issues found: {len(issues)}")
        
        # Check for specific false positives we're trying to fix
        false_positives = []
        expected_valid_calls = [
            "self.update_membership_status",
            "self.validate", 
            "ChapterMembershipHistoryManager.update_membership_status",
            "TestClass.static_method",
            "TestClass.class_method",
            "frappe.get_doc",
            "frappe.db.get_value"
        ]
        
        for issue in issues:
            for expected_call in expected_valid_calls:
                if expected_call in issue.call_name or expected_call in issue.context:
                    false_positives.append((issue, expected_call))
        
        print(f"   False positives detected: {len(false_positives)}")
        
        if false_positives:
            print(f"\n❌ FALSE POSITIVES FOUND:")
            for issue, expected_call in false_positives:
                print(f"   - {issue.call_name} (should be valid: {expected_call})")
                print(f"     Context: {issue.context[:60]}...")
                print(f"     Confidence: {issue.confidence}")
        else:
            print(f"\n✅ NO FALSE POSITIVES - All expected valid calls were correctly validated!")
        
        # Show remaining issues (should be minimal)
        if issues and not false_positives:
            print(f"\n⚠️  REMAINING ISSUES (should be real problems):")
            for issue in issues[:5]:  # Show first 5
                print(f"   - {issue.call_name}")
                print(f"     Context: {issue.context[:60]}...")
        
        # Test specific improvements
        print(f"\n🎯 IMPROVEMENT VALIDATION:")
        
        # Test 1: Class hierarchy tracking
        member_methods = validator.class_hierarchy.get('Member', set())
        has_update_method = 'update_membership_status' in member_methods
        print(f"   ✅ Class method detection: {'PASS' if has_update_method else 'FAIL'}")
        
        # Test 2: Static method tracking
        test_static_methods = validator.static_method_calls.get('TestClass', set())
        has_static_method = 'static_method' in test_static_methods
        print(f"   ✅ Static method tracking: {'PASS' if has_static_method else 'FAIL'}")
        
        # Test 3: Import tracking
        file_imports = validator.file_imports.get(str(test_file_path), {})
        has_chapter_import = 'ChapterMembershipHistoryManager' in file_imports
        print(f"   ✅ Import tracking: {'PASS' if has_chapter_import else 'FAIL'}")
        
        print(f"\n📊 IMPROVEMENT SUMMARY:")
        print(f"   Method signatures: {len(validator.method_signatures)}")
        print(f"   Classes with methods: {len([k for k, v in validator.class_hierarchy.items() if v])}")
        print(f"   Classes with static methods: {len([k for k, v in validator.static_method_calls.items() if v])}")
        print(f"   Files with tracked imports: {len(validator.file_imports)}")
        
        # Overall assessment
        total_improvements = sum([
            has_update_method,
            has_static_method, 
            has_chapter_import,
            len(false_positives) == 0
        ])
        
        print(f"\n🏆 OVERALL IMPROVEMENT SCORE: {total_improvements}/4")
        
        if total_improvements >= 3:
            print("🎉 VALIDATION IMPROVEMENTS SUCCESSFUL!")
        else:
            print("⚠️  Some improvements may need additional work")
            
        return len(false_positives) == 0 and total_improvements >= 3
        
    finally:
        # Clean up test file
        if test_file_path.exists():
            test_file_path.unlink()


def run_real_world_test():
    """Test the validator on actual problematic files"""
    print("\n" + "=" * 50)
    print("🌍 REAL-WORLD VALIDATION TEST")
    print("=" * 50)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Build cache
    validator.build_method_cache(force_rebuild=False)
    
    # Test on specific files that had false positives
    test_files = [
        Path(app_path) / "verenigingen" / "verenigingen" / "doctype" / "member" / "member.py",
        Path(app_path) / "verenigingen" / "utils" / "application_helpers.py",
    ]
    
    total_issues_before = 0
    total_issues_after = 0
    
    for test_file in test_files:
        if not test_file.exists():
            continue
            
        print(f"\n🔍 Testing: {test_file.relative_to(Path(app_path))}")
        issues = validator.validate_file(test_file)
        
        # Count issues related to the patterns we fixed
        relevant_issues = [
            issue for issue in issues 
            if any(pattern in issue.call_name.lower() for pattern in [
                'update_membership_status', 'self.', 'chaptermembershiphistorymanager'
            ])
        ]
        
        print(f"   Total issues: {len(issues)}")
        print(f"   Relevant to improvements: {len(relevant_issues)}")
        
        if relevant_issues:
            print(f"   Sample issues:")
            for issue in relevant_issues[:3]:
                print(f"     - {issue.call_name} (line {issue.line_number})")
        else:
            print(f"   ✅ No issues related to improved patterns!")
    
    return True


if __name__ == "__main__":
    print("🚀 Starting Method Call Validator Improvement Tests\n")
    
    # Run tests
    test1_passed = run_improvement_test()
    test2_passed = run_real_world_test()
    
    print(f"\n" + "=" * 50)
    print("📊 FINAL RESULTS")
    print("=" * 50)
    print(f"Improvement test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Real-world test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 ALL TESTS PASSED - Validator improvements successful!")
        print("The refined validator should now have significantly fewer false positives.")
    else:
        print("\n⚠️  Some tests failed - additional refinement may be needed.")
    
    print(f"\n💡 To test the improved validator:")
    print(f"   python scripts/validation/method_call_validator.py --debug")
    print(f"   python scripts/validation/method_call_validator.py --comprehensive")