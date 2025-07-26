#!/usr/bin/env python3
"""
Validate that the method call validator improvements are working
by testing on actual codebase files that had false positives.
"""

import sys
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from method_call_validator import MethodCallValidator


def test_member_class_improvements():
    """Test improvements on Member class file"""
    print("🧪 Testing Member Class Improvements")
    print("=" * 40)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Load cache if available
    validator.build_method_cache(force_rebuild=False)
    
    member_file = Path(app_path) / "verenigingen" / "verenigingen" / "doctype" / "member" / "member.py"
    
    if not member_file.exists():
        print("❌ Member file not found")
        return False
    
    print(f"📄 Testing: {member_file.relative_to(Path(app_path))}")
    
    # Validate the file
    issues = validator.validate_file(member_file)
    
    # Filter issues for patterns we specifically improved
    improvement_patterns = [
        'self.update_membership_status',
        'self.validate',
        'self.save',
        'self.insert'
    ]
    
    false_positives = []
    for issue in issues:
        for pattern in improvement_patterns:
            if pattern in issue.call_name:
                false_positives.append((issue, pattern))
    
    print(f"📊 Results:")
    print(f"   Total issues: {len(issues)}")
    print(f"   False positives (improved patterns): {len(false_positives)}")
    
    if false_positives:
        print(f"\n❌ Remaining false positives:")
        for issue, pattern in false_positives[:5]:
            print(f"   {issue.call_name} (line {issue.line_number}) - {pattern}")
    else:
        print(f"✅ No false positives for improved patterns!")
    
    # Check if Member class methods are properly tracked
    member_methods = validator.class_hierarchy.get('Member', set())
    has_update_method = 'update_membership_status' in member_methods
    
    print(f"\n🔍 Class hierarchy check:")
    print(f"   Member class methods tracked: {len(member_methods)}")
    print(f"   update_membership_status in Member: {'✅' if has_update_method else '❌'}")
    
    # Show sample of member methods
    sample_methods = list(member_methods)[:5]
    print(f"   Sample methods: {sample_methods}")
    
    return len(false_positives) == 0 and has_update_method


def test_application_helpers_improvements():
    """Test improvements on application helpers file"""
    print("\n🧪 Testing Application Helpers Improvements")
    print("=" * 40)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Load cache if available
    validator.build_method_cache(force_rebuild=False)
    
    helpers_file = Path(app_path) / "verenigingen" / "utils" / "application_helpers.py"
    
    if not helpers_file.exists():
        print("❌ Application helpers file not found")
        return False
    
    print(f"📄 Testing: {helpers_file.relative_to(Path(app_path))}")
    
    # Validate the file
    issues = validator.validate_file(helpers_file)
    
    # Filter for ChapterMembershipHistoryManager static method calls
    static_method_issues = []
    for issue in issues:
        if 'ChapterMembershipHistoryManager' in issue.call_name:
            static_method_issues.append(issue)
    
    print(f"📊 Results:")
    print(f"   Total issues: {len(issues)}")
    print(f"   ChapterMembershipHistoryManager static method issues: {len(static_method_issues)}")
    
    # Check import tracking for this file
    file_imports = validator.file_imports.get(str(helpers_file), {})
    has_chapter_import = any('ChapterMembershipHistoryManager' in imp for imp in file_imports.values())
    
    print(f"\n🔍 Import tracking check:")
    print(f"   File imports tracked: {len(file_imports)}")
    print(f"   ChapterMembershipHistoryManager import: {'✅' if has_chapter_import else '❌'}")
    
    if static_method_issues:
        print(f"\n❌ Static method issues found:")
        for issue in static_method_issues[:3]:
            print(f"   {issue.call_name} (line {issue.line_number})")
    else:
        print(f"✅ No static method issues!")
    
    return len(static_method_issues) == 0 and has_chapter_import


def test_overall_improvement_metrics():
    """Test overall improvement metrics"""
    print("\n🧪 Testing Overall Improvement Metrics")
    print("=" * 40)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Load cache
    validator.build_method_cache(force_rebuild=False)
    
    print(f"📊 Cache Statistics:")
    print(f"   Method signatures: {len(validator.method_signatures):,}")
    print(f"   Classes tracked: {len(validator.class_hierarchy)}")
    print(f"   Classes with methods: {len([k for k, v in validator.class_hierarchy.items() if v])}")
    print(f"   Static method calls tracked: {sum(len(methods) for methods in validator.static_method_calls.values())}")
    print(f"   Files with imports: {len(validator.file_imports)}")
    
    # Check for specific classes we care about
    important_classes = ['Member', 'ChapterMembershipHistoryManager', 'Chapter', 'Volunteer']
    
    print(f"\n🎯 Important Classes Check:")
    for class_name in important_classes:
        in_hierarchy = class_name in validator.class_hierarchy
        method_count = len(validator.class_hierarchy.get(class_name, set()))
        print(f"   {class_name}: {'✅' if in_hierarchy else '❌'} ({method_count} methods)")
    
    # Check static methods
    print(f"\n🔧 Static Methods Check:")
    for class_name, methods in list(validator.static_method_calls.items())[:5]:
        print(f"   {class_name}: {list(methods)[:3]}")
    
    success_metrics = [
        len(validator.class_hierarchy) > 500,  # Should have many classes
        sum(len(methods) for methods in validator.static_method_calls.values()) > 100,  # Should have static methods
        len(validator.file_imports) > 500,  # Should track many imports
        'Member' in validator.class_hierarchy,  # Should track Member class
    ]
    
    score = sum(success_metrics)
    print(f"\n🏆 Overall Score: {score}/4")
    
    return score >= 3


if __name__ == "__main__":
    print("🚀 Method Call Validator Improvement Validation")
    print("=" * 50)
    
    test1 = test_member_class_improvements()
    test2 = test_application_helpers_improvements()  
    test3 = test_overall_improvement_metrics()
    
    print(f"\n" + "=" * 50)
    print("🏆 FINAL VALIDATION RESULTS")
    print("=" * 50)
    print(f"Member class improvements: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Application helpers improvements: {'✅ PASS' if test2 else '❌ FAIL'}")
    print(f"Overall improvement metrics: {'✅ PASS' if test3 else '❌ FAIL'}")
    
    overall_success = sum([test1, test2, test3]) >= 2
    
    if overall_success:
        print(f"\n🎉 VALIDATION SUCCESSFUL!")
        print(f"The refined method call validator shows significant improvements:")
        print(f"- Better class method detection (self.method calls)")
        print(f"- Enhanced static method tracking")
        print(f"- Improved import awareness")
        print(f"- Reduced false positives on legitimate method calls")
    else:
        print(f"\n⚠️  VALIDATION NEEDS MORE WORK")
        print(f"Some improvements are not fully working yet.")
    
    print(f"\n💡 Usage:")
    print(f"   python scripts/validation/method_call_validator.py")
    print(f"   python scripts/validation/method_call_validator.py --comprehensive")