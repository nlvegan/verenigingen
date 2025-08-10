#!/usr/bin/env python3
"""
Debug the entire validation pipeline to find exactly where invalid fields are being lost
"""

import sys
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from schema_aware_validator import SchemaAwareValidator

def debug_validation_pipeline():
    """Debug the entire validation pipeline step by step"""
    
    print("🔍 DEBUGGING VALIDATION PIPELINE")
    print("=" * 70)
    
    # Initialize validator
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = SchemaAwareValidator(app_path, min_confidence=0.1, verbose=False)
    
    # Create simple test file - one invalid field per line
    test_code = '''import frappe
member = frappe.get_doc("Member", "test")
test1 = member.email_address_nonexistent
test2 = member.full_name_does_not_exist
test3 = member.member_status_wrong
test4 = member.completely_fake_field
'''
    
    # Create test file
    temp_dir = Path("/tmp/validator_debug")
    temp_dir.mkdir(exist_ok=True)
    
    test_file = temp_dir / "debug_pipeline.py"
    with open(test_file, 'w') as f:
        f.write(test_code)
    
    print(f"📄 Created test file with simple invalid field accesses")
    
    # Step 1: Manual pipeline execution
    print("\n🔍 STEP 1: File Reading")
    try:
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        print(f"✅ File read successfully: {len(lines)} lines")
    except Exception as e:
        print(f"❌ File reading failed: {e}")
        return
    
    # Step 2: Context Analysis
    print("\n🔍 STEP 2: Context Analysis")
    try:
        file_contexts = validator.context_analyzer.analyze_file_context(test_file)
        print(f"✅ Context analysis complete: {len(file_contexts)} contexts")
        
        # Show contexts for key lines
        for line_num in [3, 4, 5, 6]:  # Lines with invalid field access
            context = file_contexts.get(line_num)
            if context:
                member_type = context.variable_assignments.get('member', 'NOT_FOUND')
                print(f"   Line {line_num}: member type = '{member_type}'")
            else:
                print(f"   Line {line_num}: NO CONTEXT")
    except Exception as e:
        print(f"❌ Context analysis failed: {e}")
        return
    
    # Step 3: AST Field Extraction
    print("\n🔍 STEP 3: AST Field Extraction")
    try:
        import ast
        tree = ast.parse(content, filename=str(test_file))
        field_accesses = validator.validation_engine._extract_field_accesses(tree)
        print(f"✅ AST extraction complete: {len(field_accesses)} field accesses")
        
        member_accesses = [access for access in field_accesses if access['obj_name'] == 'member']
        print(f"   Member accesses found: {len(member_accesses)}")
        
        for access in member_accesses:
            print(f"   • Line {access['line']}: {access['obj_name']}.{access['field_name']}")
    except Exception as e:
        print(f"❌ AST extraction failed: {e}")
        return
    
    # Step 4: Individual Field Validation
    print("\n🔍 STEP 4: Individual Field Validation")
    
    issues_found = []
    
    for access in member_accesses:
        line_num = access['line']
        obj_name = access['obj_name']
        field_name = access['field_name']
        
        print(f"\n   Validating: {obj_name}.{field_name} (Line {line_num})")
        
        # Get line context
        line_context = file_contexts.get(line_num)
        if not line_context:
            print(f"      ❌ No line context found")
            continue
        
        # Call the validation method directly
        try:
            issue = validator.validation_engine._validate_field_access(
                access, line_context, lines, str(test_file)
            )
            
            if issue:
                print(f"      ✅ Issue created: {issue.field_name} (confidence: {issue.confidence})")
                issues_found.append(issue)
            else:
                print(f"      ❌ No issue created - let's trace why...")
                
                # Trace through validation logic step by step
                broader_context = validator.validation_engine._get_broader_context(lines, line_num, 5)
                
                # Check builtin patterns
                if obj_name in validator.context_analyzer.builtin_patterns['python_builtins']:
                    print(f"         SKIPPED: {obj_name} is Python builtin")
                    continue
                
                if obj_name in validator.context_analyzer.builtin_patterns['frappe_objects']:
                    print(f"         SKIPPED: {obj_name} is Frappe builtin")
                    continue
                
                # Check frappe document methods
                if field_name in validator.pattern_handler.valid_patterns.get('frappe_document_methods', []):
                    print(f"         SKIPPED: {field_name} is Frappe document method")
                    continue
                
                # Check pattern matching
                is_valid_pattern, pattern_type = validator.pattern_handler.is_valid_frappe_pattern(
                    f"{obj_name}.{field_name}", broader_context
                )
                if is_valid_pattern:
                    print(f"         SKIPPED: Valid Frappe pattern ({pattern_type})")
                    continue
                
                # Determine object type
                obj_type = validator.validation_engine._determine_object_type(obj_name, line_context, broader_context)
                print(f"         Object type: '{obj_type}'")
                
                if not obj_type or obj_type == 'unknown':
                    print(f"         SKIPPED: Unknown object type")
                    continue
                
                # Check confidence factors
                confidence = 1.0
                if obj_name in line_context.sql_variables:
                    print(f"         SKIPPED: SQL variable")
                    continue
                
                if obj_name in line_context.frappe_api_calls:
                    confidence *= 0.3
                    print(f"         Confidence reduced to {confidence} (API call)")
                
                if field_name in line_context.property_methods:
                    print(f"         SKIPPED: Property method")
                    continue
                
                # Check field existence
                field_exists = validator.schema_reader.is_valid_field(obj_type, field_name)
                print(f"         Field exists: {field_exists}")
                print(f"         Final confidence: {confidence}")
                print(f"         Min confidence threshold: {validator.validation_engine.min_confidence}")
                
                if not field_exists and confidence >= validator.validation_engine.min_confidence:
                    print(f"         💥 BUG: Should have created issue but didn't!")
                else:
                    print(f"         Logic says no issue (but this might be wrong)")
                
        except Exception as e:
            print(f"      ❌ Validation failed: {e}")
            import traceback
            print(f"         {traceback.format_exc()}")
    
    # Step 5: Compare with actual validate_file method
    print(f"\n🔍 STEP 5: Actual validate_file Method")
    actual_issues = validator.validate_file(test_file)
    actual_member_issues = [issue for issue in actual_issues if issue.obj_name == 'member']
    
    print(f"   Actual issues found: {len(actual_member_issues)}")
    for issue in actual_member_issues:
        print(f"   • {issue.obj_name}.{issue.field_name} (line {issue.line_number}, confidence: {issue.confidence})")
    
    # Step 6: Analysis and Conclusion
    print(f"\n📊 ANALYSIS")
    print(f"   Individual validation found: {len(issues_found)} issues")
    print(f"   Actual validate_file found: {len(actual_member_issues)} issues")
    
    if len(issues_found) != len(actual_member_issues):
        print(f"   💥 DISCREPANCY DETECTED!")
        print(f"   The bug is somewhere between individual validation and the full pipeline!")
        
        # Let's check if it's in the main validation loop
        print(f"\n🔍 CHECKING MAIN VALIDATION LOOP...")
        
        # Look at the validate_file method implementation
        print(f"   The validate_file method should:")
        print(f"   1. Get file contexts ✅")
        print(f"   2. Extract field accesses ✅") 
        print(f"   3. Loop through accesses and validate each ❓")
        print(f"   4. Filter by confidence threshold ❓")
        print(f"   5. Return issues ❓")
        
        # Let's manually replicate the main loop
        print(f"\n🔍 MANUAL LOOP REPLICATION...")
        manual_issues = []
        
        for access in member_accesses:
            line_context = file_contexts.get(access['line'])
            if line_context:
                issue = validator.validation_engine._validate_field_access(
                    access, line_context, lines, str(test_file)
                )
                if issue and issue.confidence >= validator.validation_engine.min_confidence:
                    manual_issues.append(issue)
        
        print(f"   Manual loop found: {len(manual_issues)} issues")
        
        if len(manual_issues) == len(issues_found):
            print(f"   💥 BUG IS IN THE MAIN VALIDATE_FILE METHOD!")
        else:
            print(f"   💥 BUG IS IN CONFIDENCE FILTERING OR ELSEWHERE!")
    
    else:
        print(f"   ✅ No discrepancy - the issue is in the individual validation logic")
    
    # Clean up
    try:
        test_file.unlink()
        temp_dir.rmdir()
    except:
        pass

if __name__ == "__main__":
    debug_validation_pipeline()