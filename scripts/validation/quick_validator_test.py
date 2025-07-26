#!/usr/bin/env python3
"""
Quick test of the enhanced method call validator improvements.
Tests specific patterns without full cache rebuild.
"""

import sys
import ast
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from method_call_validator import MethodCallValidator


def test_specific_improvements():
    """Test specific improvements on a minimal test case"""
    print("🧪 Quick Validator Improvement Test")
    print("=" * 40)
    
    # Create simple test content
    test_content = '''
from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

class TestClass:
    @staticmethod
    def static_method():
        pass
    
    def update_membership_status(self):
        pass
    
    def test_method(self):
        # Should be valid - same class method
        self.update_membership_status()
        
        # Should be valid - static method
        TestClass.static_method()
        
        # Should be valid - imported static method
        ChapterMembershipHistoryManager.update_membership_status()
'''
    
    # Create validator and test on the content directly
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Create a temporary test file
    test_file = Path("/tmp/quick_test.py")
    with open(test_file, 'w') as f:
        f.write(test_content)
    
    try:
        # Parse and extract methods from test content
        tree = ast.parse(test_content, filename=str(test_file))
        module_name = "test_module"
        
        # Test our extraction methods
        print("📚 Testing method extraction...")
        validator._extract_imports_from_file(tree, str(test_file))
        validator._extract_classes_and_methods(tree, test_file, module_name)
        
        # Check what we extracted
        print(f"✅ Classes tracked: {len(validator.class_hierarchy)}")
        print(f"   Classes: {list(validator.class_hierarchy.keys())}")
        
        print(f"✅ Static methods tracked: {sum(len(m) for m in validator.static_method_calls.values())}")
        for class_name, methods in validator.static_method_calls.items():
            print(f"   {class_name}: {list(methods)}")
        
        print(f"✅ Imports tracked: {len(validator.file_imports)}")
        for file_path, imports in validator.file_imports.items():
            print(f"   {Path(file_path).name}: {imports}")
        
        # Test method calls
        print(f"\n🔍 Testing method call validation...")
        calls = validator._extract_method_calls(tree, test_file, test_content.split('\n'))
        
        print(f"Found {len(calls)} method calls:")
        valid_calls = 0
        invalid_calls = 0
        
        for call in calls:
            is_valid = validator._is_valid_call(call)
            status = "✅ VALID" if is_valid else "❌ INVALID"
            print(f"   {call.full_call} - {status}")
            
            if is_valid:
                valid_calls += 1
            else:
                invalid_calls += 1
                # Test specific validation paths
                if call.object_name == 'self':
                    class_context = validator._find_current_class_context(call)
                    method_exists = validator._method_exists_in_class(call.name, class_context) if class_context else False
                    print(f"     Class context: {class_context}, Method exists: {method_exists}")
                elif call.object_name and '.' not in call.object_name:
                    is_static = validator._is_static_method_call(call)
                    print(f"     Static method check: {is_static}")
        
        print(f"\n📊 RESULTS:")
        print(f"   Valid calls: {valid_calls}")
        print(f"   Invalid calls: {invalid_calls}")
        
        # Expected: all calls should be valid
        success = invalid_calls == 0
        
        if success:
            print("🎉 ALL IMPROVEMENTS WORKING!")
        else:
            print("⚠️  Some improvements need work")
        
        return success
        
    finally:
        if test_file.exists():
            test_file.unlink()


def test_real_patterns():
    """Test on actual problematic patterns from the codebase"""
    print("\n" + "=" * 40)
    print("🌍 Real Pattern Test")
    print("=" * 40)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Test a simple member.py file section
    member_file = Path(app_path) / "verenigingen" / "verenigingen" / "doctype" / "member" / "member.py"
    if member_file.exists():
        print(f"Testing: {member_file.relative_to(Path(app_path))}")
        
        # Build minimal cache for this file only
        validator._extract_methods_from_file(member_file)
        
        print(f"Methods found in Member class: {len(validator.class_hierarchy.get('Member', set()))}")
        member_methods = validator.class_hierarchy.get('Member', set())
        if 'update_membership_status' in member_methods:
            print("✅ update_membership_status found in Member class")
        else:
            print("❌ update_membership_status NOT found in Member class")
        
        # Test a few lines that had false positives
        issues = validator.validate_file(member_file)
        self_issues = [i for i in issues if 'self.' in i.call_name and 'update_membership_status' in i.call_name]
        
        print(f"Self.update_membership_status issues: {len(self_issues)}")
        
        return len(self_issues) == 0
    
    return True


if __name__ == "__main__":
    test1 = test_specific_improvements()
    test2 = test_real_patterns()
    
    print(f"\n" + "=" * 40)
    print("🏆 FINAL RESULTS")
    print("=" * 40)
    print(f"Extraction test: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Real pattern test: {'✅ PASS' if test2 else '❌ FAIL'}")
    
    if test1 and test2:
        print("\n🎉 Validator improvements successful!")
    else:
        print("\n⚠️  Additional work needed")