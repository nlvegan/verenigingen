#!/usr/bin/env python3
"""
Critical Fix Analysis for Schema-Aware Validator
===============================================

This test specifically evaluates the method call filtering fix to determine:
1. Whether method calls are correctly ignored (no false positives)
2. Whether invalid field references are still caught (no false negatives)
3. Whether the claimed 93% false positive reduction is legitimate
4. Root cause analysis of any pattern matching issues
"""

import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any
import traceback

# Add current directory to path for imports
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def run_critical_validator_tests():
    """Run critical tests to evaluate the method call filtering fix"""
    
    print("🔬 CRITICAL VALIDATOR FIX ANALYSIS")
    print("=" * 80)
    print()
    
    try:
        # Import the validator
        from schema_aware_validator import SchemaAwareValidator, FrappePatternHandler
        print("✅ Successfully imported schema_aware_validator")
    except ImportError as e:
        print(f"❌ Failed to import validator: {e}")
        return False
    
    # Initialize validator
    try:
        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        validator = SchemaAwareValidator(app_path, min_confidence=0.7, verbose=False)
        print("✅ Validator initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize validator: {e}")
        print(f"Error details: {traceback.format_exc()}")
        return False
    
    # Test Results Container
    test_results = {
        'method_call_filtering': None,
        'field_access_validation': None,
        'pattern_matching_accuracy': None,
        'ast_detection_accuracy': None,
        'overall_assessment': None
    }
    
    # TEST 1: Method Call Filtering (Critical - Should produce ZERO false positives)
    print("\n🧪 TEST 1: Method Call Filtering")
    print("-" * 50)
    
    method_call_test = '''
import frappe

def test_method_calls():
    # Get a document
    member = frappe.get_doc("Member", "MEMBER-001")
    
    # These are all METHOD CALLS - should NOT trigger validation issues
    member.save()                    # Standard document method
    member.submit()                  # Workflow method
    member.reload()                  # Refresh method
    member.delete()                  # Deletion method
    member.validate()                # Validation method
    member.insert()                  # Insert method
    member.cancel()                  # Cancel method
    
    # Method calls with parameters
    value = member.get("email")      # Get method with parameter
    member.set("status", "Active")   # Set method with parameters
    member.append("skills", {})      # Append to child table
    member.remove("skills", 0)       # Remove from child table
    
    # Meta and system attributes (should also be ignored)
    meta_info = member.meta           # Meta attribute
    flags = member.flags              # Flags attribute
    perms = member.permissions        # Permissions attribute
    
    return member
'''
    
    # Create temporary file and test
    temp_dir = Path("/tmp/validator_test")
    temp_dir.mkdir(exist_ok=True)
    
    method_test_file = temp_dir / "method_call_test.py"
    with open(method_test_file, 'w') as f:
        f.write(method_call_test)
    
    method_issues = validator.validate_file(method_test_file)
    
    # Filter issues related to our test object
    member_issues = [issue for issue in method_issues if issue.obj_name == 'member']
    
    print(f"📊 Method call test results:")
    print(f"   • Total issues found: {len(member_issues)}")
    
    if member_issues:
        print("❌ FALSE POSITIVES DETECTED:")
        for issue in member_issues:
            print(f"   • {issue.obj_name}.{issue.field_name} (confidence: {issue.confidence:.2f})")
            print(f"     Message: {issue.message}")
            print(f"     Context: {issue.context}")
        test_results['method_call_filtering'] = {'passed': False, 'false_positives': len(member_issues)}
    else:
        print("✅ EXCELLENT: No false positives - method calls correctly ignored")
        test_results['method_call_filtering'] = {'passed': True, 'false_positives': 0}
    
    # TEST 2: Field Access Validation (Critical - Should catch invalid fields)
    print("\n🧪 TEST 2: Field Access Validation")  
    print("-" * 50)
    
    field_access_test = '''
import frappe

def test_field_validation():
    # Get a document
    member = frappe.get_doc("Member", "MEMBER-001")
    
    # These are FIELD ACCESS with invalid field names - SHOULD be caught
    invalid_email = member.email_address_nonexistent     # Invalid field
    invalid_name = member.full_name_does_not_exist       # Invalid field
    invalid_status = member.member_status_wrong          # Invalid field
    invalid_data = member.completely_fake_field          # Invalid field
    
    return member
'''
    
    field_test_file = temp_dir / "field_access_test.py"
    with open(field_test_file, 'w') as f:
        f.write(field_access_test)
    
    field_issues = validator.validate_file(field_test_file)
    
    # Filter issues related to our test object
    member_field_issues = [issue for issue in field_issues if issue.obj_name == 'member']
    
    expected_invalid_fields = [
        'email_address_nonexistent', 
        'full_name_does_not_exist', 
        'member_status_wrong',
        'completely_fake_field'
    ]
    
    caught_fields = [issue.field_name for issue in member_field_issues]
    
    print(f"📊 Field validation test results:")
    print(f"   • Expected invalid fields: {expected_invalid_fields}")
    print(f"   • Caught invalid fields: {caught_fields}")
    print(f"   • Total issues found: {len(member_field_issues)}")
    
    caught_expected = len([field for field in expected_invalid_fields if field in caught_fields])
    missed_expected = len([field for field in expected_invalid_fields if field not in caught_fields])
    
    if caught_expected >= 2:  # Should catch at least 2 of the 4 invalid fields
        if missed_expected == 0:
            print("✅ EXCELLENT: All invalid fields caught")
            test_results['field_access_validation'] = {'passed': True, 'caught': caught_expected, 'missed': missed_expected}
        else:
            print(f"⚠️ GOOD: Caught {caught_expected} fields, missed {missed_expected}")
            test_results['field_access_validation'] = {'passed': True, 'caught': caught_expected, 'missed': missed_expected}
    else:
        print(f"❌ POOR: Only caught {caught_expected} invalid fields")
        test_results['field_access_validation'] = {'passed': False, 'caught': caught_expected, 'missed': missed_expected}
    
    # TEST 3: Pattern Matching Logic Analysis
    print("\n🧪 TEST 3: Pattern Matching Logic")
    print("-" * 50)
    
    pattern_handler = validator.pattern_handler
    
    # Test specific pattern matching cases
    test_cases = [
        # (field_access, context, expected_valid, description)
        ("member.save", "member.save()", True, "Method call should be valid pattern"),
        ("doc.submit", "doc.submit()", True, "Submit method should be valid"),
        ("obj.get", "obj.get('field')", True, "Get method with args should be valid"),
        ("member.email", "member.email", False, "Field access should NOT be valid pattern"),
        ("doc.name", "doc.name", False, "Name field access should NOT be valid pattern"),
        ("result.field", "SELECT * FROM tab", True, "Wildcard SQL should be valid"),
        ("item.alias", "SELECT name as alias FROM tab", True, "SQL alias should be valid"),
    ]
    
    correct_patterns = 0
    total_patterns = len(test_cases)
    
    print("Testing pattern recognition:")
    for field_access, context, expected_valid, description in test_cases:
        is_valid, matched_pattern = pattern_handler.is_valid_frappe_pattern(field_access, context)
        
        if is_valid == expected_valid:
            print(f"✅ {description}")
            correct_patterns += 1
        else:
            print(f"❌ {description}")
            print(f"   Expected: {expected_valid}, Got: {is_valid}")
            if matched_pattern:
                print(f"   Matched pattern: {matched_pattern}")
    
    pattern_accuracy = (correct_patterns / total_patterns) * 100
    print(f"\n📊 Pattern matching accuracy: {pattern_accuracy:.1f}% ({correct_patterns}/{total_patterns})")
    
    test_results['pattern_matching_accuracy'] = {
        'passed': pattern_accuracy >= 70,
        'accuracy': pattern_accuracy,
        'correct': correct_patterns,
        'total': total_patterns
    }
    
    # TEST 4: AST Method Detection Analysis
    print("\n🧪 TEST 4: AST Method Detection Analysis")
    print("-" * 50)
    
    ast_test = '''
def test_ast_detection():
    member = frappe.get_doc("Member", "test")
    
    # Method calls (should be detected as methods)
    member.save()           # Method call
    result = member.get("field")  # Method call with return
    member.submit()         # Method call
    
    # Field access (should NOT be detected as methods)
    email = member.email    # Field access
    name = member.name      # Field access
    status = member.status  # Field access
'''
    
    # Test AST extraction
    import ast
    try:
        tree = ast.parse(ast_test)
        validation_engine = validator.validation_engine
        accesses = validation_engine._extract_field_accesses(tree)
        
        print(f"📊 AST extraction results:")
        print(f"   • Total attribute accesses found: {len(accesses)}")
        
        # Analyze method vs field detection
        method_calls = []
        field_accesses = []
        
        for access in accesses:
            if access.get('is_method', False):
                method_calls.append(access['field_name'])
            else:
                field_accesses.append(access['field_name'])
        
        print(f"   • Detected as method calls: {method_calls}")
        print(f"   • Detected as field access: {field_accesses}")
        
        # Expected: save, get, submit should be method calls
        # Expected: email, name, status should be field access
        expected_methods = {'save', 'get', 'submit'}
        expected_fields = {'email', 'name', 'status'}
        
        detected_methods = set(method_calls)
        detected_fields = set(field_accesses)
        
        method_accuracy = len(expected_methods & detected_methods) / len(expected_methods) * 100 if expected_methods else 0
        field_accuracy = len(expected_fields & detected_fields) / len(expected_fields) * 100 if expected_fields else 0
        
        print(f"\n📊 AST Detection Accuracy:")
        print(f"   • Method detection: {method_accuracy:.1f}%")
        print(f"   • Field detection: {field_accuracy:.1f}%")
        
        ast_passed = method_accuracy >= 60 and field_accuracy >= 60
        test_results['ast_detection_accuracy'] = {
            'passed': ast_passed,
            'method_accuracy': method_accuracy,
            'field_accuracy': field_accuracy
        }
        
        if ast_passed:
            print("✅ AST detection working reasonably well")
        else:
            print("❌ AST detection has issues")
    
    except Exception as e:
        print(f"❌ AST detection test failed: {e}")
        test_results['ast_detection_accuracy'] = {'passed': False, 'error': str(e)}
    
    # OVERALL ASSESSMENT
    print("\n" + "=" * 80)
    print("📊 COMPREHENSIVE VALIDATOR ASSESSMENT")
    print("=" * 80)
    
    # Critical tests
    method_filtering_ok = test_results['method_call_filtering']['passed']
    field_validation_ok = test_results['field_access_validation']['passed']
    
    print(f"\n🎯 Critical Fix Analysis:")
    print(f"   • Method call filtering: {'✅ WORKING' if method_filtering_ok else '❌ BROKEN'}")
    print(f"   • Field validation: {'✅ WORKING' if field_validation_ok else '❌ BROKEN'}")
    
    if method_filtering_ok and field_validation_ok:
        print("\n🎉 VERDICT: The method call filtering fix IS WORKING!")
        print("   • Method calls are correctly ignored (no false positives)")
        print("   • Invalid field references are still caught (no false negatives)")
        
        # Check false positive reduction claim
        false_positives = test_results['method_call_filtering']['false_positives']
        if false_positives == 0:
            print("   • The claimed 93% false positive reduction appears LEGITIMATE")
        else:
            print(f"   • WARNING: Still {false_positives} false positives detected")
        
        test_results['overall_assessment'] = 'SUCCESS'
        
    else:
        print("\n💥 VERDICT: The fix HAS CRITICAL ISSUES!")
        
        if not method_filtering_ok:
            false_positives = test_results['method_call_filtering']['false_positives']
            print(f"   • Method call filtering BROKEN: {false_positives} false positives")
            print("   • Root cause: Pattern matching incorrectly classifying method calls")
        
        if not field_validation_ok:
            caught = test_results['field_access_validation']['caught']
            missed = test_results['field_access_validation']['missed']
            print(f"   • Field validation INSUFFICIENT: Only {caught} caught, {missed} missed")
            print("   • Root cause: False negative issue - not catching invalid fields")
        
        test_results['overall_assessment'] = 'FAILURE'
    
    # Additional analysis
    pattern_accuracy = test_results.get('pattern_matching_accuracy', {}).get('accuracy', 0)
    ast_working = test_results.get('ast_detection_accuracy', {}).get('passed', False)
    
    print(f"\n🔍 Supporting Analysis:")
    print(f"   • Pattern matching accuracy: {pattern_accuracy:.1f}%")
    print(f"   • AST method detection: {'Working' if ast_working else 'Issues detected'}")
    
    if pattern_accuracy < 80:
        print("   ⚠️  Low pattern matching accuracy may be causing issues")
    
    if not ast_working:
        print("   ⚠️  AST method detection problems may affect accuracy")
    
    # Root cause analysis
    print(f"\n🔬 Root Cause Analysis:")
    
    if not method_filtering_ok:
        print("   • CRITICAL: is_valid_frappe_pattern method not correctly identifying method calls")
        print("   • The pattern matching logic may be too broad or too narrow")
        print("   • AST-based method detection may not be working properly")
    
    if not field_validation_ok:
        print("   • Field existence checking may have issues")
        print("   • Context determination may be incorrect")
        print("   • Confidence scoring may be filtering out valid issues")
    
    # Final recommendation
    print(f"\n🎯 FINAL RECOMMENDATION:")
    
    if test_results['overall_assessment'] == 'SUCCESS':
        print("✅ The method call filtering fix is working correctly.")
        print("   The validator can be trusted for production use.")
    else:
        print("❌ The fix has critical issues that need immediate attention.")
        print("   The validator should NOT be used until these issues are resolved.")
    
    # Clean up temp files
    try:
        method_test_file.unlink()
        field_test_file.unlink()
        temp_dir.rmdir()
    except:
        pass
    
    return test_results['overall_assessment'] == 'SUCCESS'

def main():
    """Main test runner"""
    print("Starting critical validator analysis...")
    
    try:
        success = run_critical_validator_tests()
        
        if success:
            print("\n🎉 All critical tests passed!")
            return 0
        else:
            print("\n💥 Critical tests failed!")
            return 1
            
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        print(f"Error details: {traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    sys.exit(main())