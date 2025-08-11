#!/usr/bin/env python3
"""
Debug object type detection to understand why some invalid fields aren't caught
"""

import sys
import ast
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from schema_aware_validator import SchemaAwareValidator

def debug_object_type_detection():
    """Debug the object type detection process"""
    
    print("🔍 DEBUGGING OBJECT TYPE DETECTION")
    print("=" * 60)
    
    # Initialize validator
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = SchemaAwareValidator(app_path, min_confidence=0.1, verbose=False)
    
    # Create detailed test file with more context
    test_code = '''
import frappe

def test_object_type_detection():
    print("Testing object type detection")
    
    # Clear assignment - should be detected as Member type
    member = frappe.get_doc("Member", "MEMBER-001")
    
    # Test each invalid field individually
    test1 = member.email_address_nonexistent     # Line ~10
    test2 = member.full_name_does_not_exist      # Line ~11  
    test3 = member.member_status_wrong           # Line ~12
    test4 = member.completely_fake_field         # Line ~13
    
    # Also test some valid fields for comparison
    valid1 = member.email                        # Line ~16
    valid2 = member.name                         # Line ~17
    
    return member
'''
    
    # Create test file
    temp_dir = Path("/tmp/validator_debug")
    temp_dir.mkdir(exist_ok=True)
    
    test_file = temp_dir / "debug_object_type.py"
    with open(test_file, 'w') as f:
        f.write(test_code)
    
    # Parse and extract field accesses manually
    print("🔍 Manual AST analysis...")
    
    tree = ast.parse(test_code)
    validation_engine = validator.validation_engine
    accesses = validation_engine._extract_field_accesses(tree)
    
    print(f"📊 Found {len(accesses)} field accesses:")
    
    member_accesses = [access for access in accesses if access['obj_name'] == 'member']
    print(f"   • Member accesses: {len(member_accesses)}")
    
    for access in member_accesses:
        print(f"   • Line {access['line']}: {access['obj_name']}.{access['field_name']}")
    
    # Analyze file context
    print(f"\n🔍 Context analysis...")
    contexts = validator.context_analyzer.analyze_file_context(test_file)
    
    print(f"   • Total contexts: {len(contexts)}")
    
    # Check context for each line with member access
    for access in member_accesses:
        line_num = access['line']
        context = contexts.get(line_num)
        
        print(f"\n   Line {line_num} - {access['obj_name']}.{access['field_name']}:")
        
        if context:
            print(f"      • Variable assignments: {context.variable_assignments}")
            print(f"      • SQL variables: {context.sql_variables}")
            print(f"      • Child table iterations: {context.child_table_iterations}")
            print(f"      • Property methods: {context.property_methods}")
            print(f"      • Frappe API calls: {context.frappe_api_calls}")
            
            # Test object type determination
            obj_type = validation_engine._determine_object_type(
                access['obj_name'], context, "broader_context_placeholder"
            )
            print(f"      • Determined object type: '{obj_type}'")
            
            # Test field existence
            if obj_type and obj_type != 'unknown':
                field_exists = validator.schema_reader.is_valid_field(obj_type, access['field_name'])
                print(f"      • Field exists: {field_exists}")
                
                # Test if it would create a validation issue
                if not field_exists:
                    print(f"      ✅ SHOULD CREATE ISSUE: {access['field_name']} not in {obj_type}")
                else:
                    print(f"      ❌ Field is valid, no issue")
            else:
                print(f"      ❌ PROBLEM: Could not determine object type, no validation possible")
        else:
            print(f"      ❌ PROBLEM: No context found for line {line_num}")
    
    # Now run the actual validation to compare
    print(f"\n🔍 Running actual validation...")
    issues = validator.validate_file(test_file)
    
    member_issues = [issue for issue in issues if issue.obj_name == 'member']
    print(f"📊 Actual validation results:")
    print(f"   • Total member issues: {len(member_issues)}")
    
    for issue in member_issues:
        print(f"   • {issue.obj_name}.{issue.field_name} (line {issue.line_number}, confidence: {issue.confidence:.2f})")
    
    # Compare expected vs actual
    expected_invalid_fields = [
        'email_address_nonexistent',
        'full_name_does_not_exist', 
        'member_status_wrong',
        'completely_fake_field'
    ]
    
    found_invalid_fields = [issue.field_name for issue in member_issues]
    
    print(f"\n📊 Comparison:")
    print(f"   • Expected invalid: {expected_invalid_fields}")
    print(f"   • Actually caught: {found_invalid_fields}")
    
    missed_fields = [field for field in expected_invalid_fields if field not in found_invalid_fields]
    if missed_fields:
        print(f"   ❌ MISSED FIELDS: {missed_fields}")
        
        # For each missed field, let's trace through validation logic
        for field in missed_fields:
            print(f"\n🔍 Tracing validation for missed field: '{field}'")
            
            # Find the access for this field
            field_access = next((access for access in member_accesses if access['field_name'] == field), None)
            if field_access:
                line_num = field_access['line']
                context = contexts.get(line_num)
                
                if context:
                    # Manually run through the validation logic
                    obj_name = field_access['obj_name']
                    field_name = field_access['field_name']
                    
                    print(f"      • Object: {obj_name}, Field: {field_name}, Line: {line_num}")
                    
                    # Check builtin patterns
                    if obj_name in validator.context_analyzer.builtin_patterns['python_builtins']:
                        print(f"      • SKIPPED: {obj_name} is Python builtin")
                        continue
                    
                    if obj_name in validator.context_analyzer.builtin_patterns['frappe_objects']:
                        print(f"      • SKIPPED: {obj_name} is Frappe builtin")
                        continue
                    
                    # Check frappe document methods
                    if field_name in validator.pattern_handler.valid_patterns.get('frappe_document_methods', []):
                        print(f"      • SKIPPED: {field_name} is Frappe document method")
                        continue
                    
                    # Check pattern matching
                    is_valid_pattern, pattern_type = validator.pattern_handler.is_valid_frappe_pattern(
                        f"{obj_name}.{field_name}", "broader_context"
                    )
                    if is_valid_pattern:
                        print(f"      • SKIPPED: Valid Frappe pattern ({pattern_type})")
                        continue
                    
                    # Determine object type
                    obj_type = validation_engine._determine_object_type(obj_name, context, "broader_context")
                    print(f"      • Object type: '{obj_type}'")
                    
                    if not obj_type or obj_type == 'unknown':
                        print(f"      • SKIPPED: Unknown object type")
                        continue
                    
                    # Check confidence factors
                    confidence = 1.0
                    if obj_name in context.sql_variables:
                        print(f"      • SKIPPED: SQL variable (confidence would be very low)")
                        continue
                    
                    if obj_name in context.frappe_api_calls:
                        confidence *= 0.3
                        print(f"      • Confidence reduced to {confidence} (API call)")
                    
                    if field_name in context.property_methods:
                        print(f"      • SKIPPED: Property method")
                        continue
                    
                    # Check field existence
                    field_exists = validator.schema_reader.is_valid_field(obj_type, field_name)
                    print(f"      • Field exists: {field_exists}")
                    print(f"      • Final confidence: {confidence}")
                    print(f"      • Min confidence threshold: {validator.validation_engine.min_confidence}")
                    
                    if not field_exists and confidence >= validator.validation_engine.min_confidence:
                        print(f"      ✅ SHOULD HAVE CREATED ISSUE - This is the bug!")
                    else:
                        print(f"      ❌ Validation logic says no issue")
    
    # Clean up
    try:
        test_file.unlink()
        temp_dir.rmdir()
    except:
        pass

if __name__ == "__main__":
    debug_object_type_detection()