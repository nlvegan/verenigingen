#!/usr/bin/env python3
"""
Debug field validation issues to understand why invalid fields are not being caught
"""

import sys
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from schema_aware_validator import SchemaAwareValidator

def debug_field_validation():
    """Debug why field validation is failing"""
    
    print("🔍 DEBUGGING FIELD VALIDATION")
    print("=" * 50)
    
    # Initialize validator with verbose mode
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = SchemaAwareValidator(app_path, min_confidence=0.1, verbose=True)  # Lower confidence threshold
    
    # Check what Member fields actually exist
    print("📋 Checking Member DocType schema...")
    member_schema = validator.schema_reader.doctypes.get("Member")
    if member_schema:
        print(f"✅ Member DocType found")
        print(f"   • Standard fields: {len(member_schema.fields)}")
        print(f"   • Custom fields: {len(member_schema.custom_fields)}")
        print(f"   • Sample fields: {list(member_schema.fields.keys())[:10]}")
    else:
        print("❌ Member DocType not found!")
        return
    
    # Test field existence directly
    print("\n🧪 Testing field existence directly...")
    test_fields = [
        'email_address_nonexistent',
        'full_name_does_not_exist', 
        'member_status_wrong',
        'completely_fake_field',
        'email',  # This should exist
        'name'    # This should exist
    ]
    
    for field in test_fields:
        exists = validator.schema_reader.is_valid_field("Member", field)
        print(f"   • {field:<30}: {'EXISTS' if exists else 'NOT EXISTS'}")
    
    # Create detailed test file
    test_code = '''
import frappe

def test_detailed_field_validation():
    print("Testing field validation")
    
    # This should work - get a Member document
    member = frappe.get_doc("Member", "MEMBER-001")
    
    # These should all be flagged as invalid
    test1 = member.email_address_nonexistent     # Invalid field
    test2 = member.full_name_does_not_exist       # Invalid field  
    test3 = member.member_status_wrong            # Invalid field
    test4 = member.completely_fake_field          # Invalid field
    
    # These might be valid (for comparison)
    if hasattr(member, 'email'):
        valid_email = member.email
    if hasattr(member, 'name'):
        valid_name = member.name
    
    return member
'''
    
    # Create test file
    temp_dir = Path("/tmp/validator_debug")
    temp_dir.mkdir(exist_ok=True)
    
    test_file = temp_dir / "debug_validation.py"
    with open(test_file, 'w') as f:
        f.write(test_code)
    
    print(f"\n🔍 Running detailed validation on test file...")
    issues = validator.validate_file(test_file)
    
    print(f"📊 Validation results:")
    print(f"   • Total issues: {len(issues)}")
    
    if not issues:
        print("❌ No issues found - this is the problem!")
        
        # Let's debug the validation process step by step
        print("\n🐛 Debugging validation process...")
        
        # Check contexts
        contexts = validator.context_analyzer.analyze_file_context(test_file)
        print(f"   • File contexts analyzed: {len(contexts)}")
        
        for line_num, context in contexts.items():
            if line_num <= 5:  # Show first few contexts
                print(f"   • Line {line_num}: assignments={context.variable_assignments}")
        
        # Check if 'member' variable is being recognized
        member_contexts = [ctx for ctx in contexts.values() if 'member' in ctx.variable_assignments]
        print(f"   • Contexts with 'member' variable: {len(member_contexts)}")
        
        if member_contexts:
            member_type = member_contexts[0].variable_assignments['member']
            print(f"   • Member variable type detected as: '{member_type}'")
            
            # Check if this type exists in schema
            type_exists = member_type in validator.schema_reader.doctypes
            print(f"   • Type exists in schema: {type_exists}")
        
        # Let's manually check what the AST parser finds
        print("\n🔍 Checking AST field extraction...")
        
        with open(test_file, 'r') as f:
            content = f.read()
        
        import ast
        try:
            tree = ast.parse(content)
            accesses = validator.validation_engine._extract_field_accesses(tree)
            print(f"   • AST field accesses found: {len(accesses)}")
            
            for access in accesses:
                if access['obj_name'] == 'member':
                    print(f"   • Found: {access['obj_name']}.{access['field_name']} (line {access['line']})")
        except Exception as e:
            print(f"   • AST parsing failed: {e}")
    
    else:
        print("✅ Issues found:")
        for i, issue in enumerate(issues):
            print(f"   {i+1}. {issue.obj_name}.{issue.field_name}")
            print(f"      DocType: {issue.doctype}")
            print(f"      Message: {issue.message}")
            print(f"      Confidence: {issue.confidence}")
            print(f"      Context: {issue.context}")
            print()
    
    # Additional debug: Check confidence scoring
    print("\n🎯 Testing confidence scoring...")
    
    # Test with different confidence levels
    for min_conf in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9]:
        temp_validator = SchemaAwareValidator(app_path, min_confidence=min_conf, verbose=False)
        temp_issues = temp_validator.validate_file(test_file)
        temp_member_issues = [issue for issue in temp_issues if issue.obj_name == 'member']
        print(f"   • Min confidence {min_conf:.1f}: {len(temp_member_issues)} member issues")
    
    # Clean up
    try:
        test_file.unlink()
        temp_dir.rmdir()
    except:
        pass

if __name__ == "__main__":
    debug_field_validation()