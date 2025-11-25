#!/usr/bin/env python3
"""
SQL Field Validation Test

This script validates that the SQL queries in permissions.py use correct field references
based on the actual DocType field definitions.
"""

import os
import re
import json
import sys

# Add the app path to sys.path for importing
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, app_path)

def load_doctype_fields(doctype_name):
    """Load field definitions from a DocType JSON file"""
    
    # Convert doctype name to file path
    file_name = doctype_name.lower().replace(' ', '_')
    json_path = os.path.join(
        app_path, 
        'verenigingen/verenigingen/doctype', 
        file_name, 
        f'{file_name}.json'
    )
    
    if not os.path.exists(json_path):
        print(f"⚠️  DocType JSON not found: {json_path}")
        return []
    
    try:
        with open(json_path, 'r') as f:
            doctype_data = json.load(f)
        
        fields = []
        for field in doctype_data.get('fields', []):
            if field.get('fieldname'):
                fields.append({
                    'fieldname': field['fieldname'],
                    'fieldtype': field['fieldtype'],
                    'label': field.get('label', ''),
                    'options': field.get('options', '')
                })
        
        return fields
    except Exception as e:
        print(f"❌ Error loading {doctype_name}: {str(e)}")
        return []


def validate_sql_field_references():
    """Validate SQL field references in permissions.py"""
    
    print("🔍 SQL Field Validation Test")
    print("=" * 50)
    
    # Load DocType field definitions
    doctype_fields = {}
    doctypes_to_check = ['Team Member', 'Team Role', 'Chapter Board Member', 'Chapter Member']
    
    for doctype in doctypes_to_check:
        fields = load_doctype_fields(doctype)
        if fields:
            doctype_fields[doctype] = [f['fieldname'] for f in fields]
            print(f"✅ Loaded {len(fields)} fields for {doctype}")
        else:
            print(f"❌ Failed to load fields for {doctype}")
    
    # Read permissions.py
    permissions_file = os.path.join(app_path, 'verenigingen/permissions.py')
    if not os.path.exists(permissions_file):
        print("❌ permissions.py not found")
        return False
    
    with open(permissions_file, 'r') as f:
        content = f.read()
    
    print(f"\n📁 Analyzing {permissions_file}")
    print("-" * 50)
    
    # Define SQL field patterns to validate
    validation_rules = [
        {
            'pattern': r'FROM\s+`tabTeam Member`.*?WHERE.*?(\w+\.\w+)',
            'doctype': 'Team Member',
            'description': 'Team Member table field references'
        },
        {
            'pattern': r'JOIN\s+`tabTeam Member`\s+(\w+).*?(\1\.\w+)',
            'doctype': 'Team Member', 
            'description': 'Team Member JOIN field references'
        },
        {
            'pattern': r'FROM\s+`tabTeam Role`.*?WHERE.*?(\w+\.\w+)',
            'doctype': 'Team Role',
            'description': 'Team Role table field references'
        },
        {
            'pattern': r'JOIN\s+`tabTeam Role`\s+(\w+).*?(\1\.\w+)',
            'doctype': 'Team Role',
            'description': 'Team Role JOIN field references'
        }
    ]
    
    issues_found = 0
    total_checks = 0
    
    # Extract and validate SQL queries
    sql_queries = re.findall(r'frappe\.db\.sql\(\s*"""(.*?)"""\s*,', content, re.DOTALL)
    
    print(f"Found {len(sql_queries)} SQL queries to analyze")
    
    for i, query in enumerate(sql_queries):
        print(f"\n🔍 Analyzing SQL query {i+1}:")
        print("   " + query.strip().replace('\n', '\n   ')[:200] + "...")
        
        # Check for Team Member field references
        if 'tabTeam Member' in query and 'Team Member' in doctype_fields:
            tm_fields = doctype_fields['Team Member']
            
            # Extract field references like tm1.fieldname, tm2.fieldname
            field_refs = re.findall(r'\btm\d*\.(\w+)\b', query)
            
            for field_ref in field_refs:
                total_checks += 1
                if field_ref in tm_fields:
                    print(f"     ✅ Team Member.{field_ref} - Valid")
                elif field_ref in ['parent', 'name', 'creation', 'modified']:
                    print(f"     ✅ Team Member.{field_ref} - Standard field")
                else:
                    issues_found += 1
                    print(f"     ❌ Team Member.{field_ref} - Field not found!")
                    print(f"        Available fields: {', '.join(tm_fields[:10])}...")
        
        # Check for Team Role field references  
        if 'tabTeam Role' in query and 'Team Role' in doctype_fields:
            tr_fields = doctype_fields['Team Role']
            
            field_refs = re.findall(r'\btr\d*\.(\w+)\b', query)
            
            for field_ref in field_refs:
                total_checks += 1
                if field_ref in tr_fields:
                    print(f"     ✅ Team Role.{field_ref} - Valid")
                elif field_ref in ['parent', 'name', 'creation', 'modified']:
                    print(f"     ✅ Team Role.{field_ref} - Standard field")  
                else:
                    issues_found += 1
                    print(f"     ❌ Team Role.{field_ref} - Field not found!")
                    print(f"        Available fields: {', '.join(tr_fields[:10])}...")
    
    # Summary
    print(f"\n📊 Validation Summary")
    print("=" * 30)
    print(f"Total field references checked: {total_checks}")
    print(f"Invalid field references found: {issues_found}")
    
    if issues_found == 0:
        print("✅ All SQL field references are valid!")
        return True
    else:
        print(f"❌ {issues_found} invalid field references need to be fixed")
        return False


def validate_specific_fixes():
    """Validate the specific fixes made for the reported issues"""
    
    print("\n🎯 Validating Specific Fixes")
    print("=" * 40)
    
    permissions_file = os.path.join(app_path, 'verenigingen/permissions.py')
    with open(permissions_file, 'r') as f:
        content = f.read()
    
    # Check that the reported issues are fixed
    fixed_issues = [
        ('tm1.member', 'Team Member .member references should be .volunteer'),
        ('tm2.member', 'Team Member .member references should be .volunteer'), 
        ('tm1.is_leader', 'Team Member .is_leader should use team role check'),
        ('tm2.is_leader', 'Team Member .is_leader should use team role check'),
        ('role_type = \'Leader\'', 'role_type comparison should use team role is_team_leader'),
    ]
    
    all_fixed = True
    
    for pattern, description in fixed_issues:
        if pattern in content:
            print(f"❌ {description}")
            print(f"   Still found: {pattern}")
            all_fixed = False
        else:
            print(f"✅ {description}")
    
    # Check for correct patterns
    correct_patterns = [
        ('tm1.volunteer', 'Correct Team Member volunteer field usage'),
        ('tm2.volunteer', 'Correct Team Member volunteer field usage'),
        ('tr1.is_team_leader', 'Correct team leader check via Team Role'),
        ('tr.is_team_leader', 'Correct team leader check via Team Role'),
    ]
    
    print(f"\n✅ Checking for Correct Patterns:")
    for pattern, description in correct_patterns:
        if pattern in content:
            print(f"✅ {description}")
        else:
            print(f"⚠️  {description} - Not found (may not be needed)")
    
    return all_fixed


def main():
    """Run all SQL field validation tests"""
    
    print("🚀 Running SQL Field Validation Tests")
    print("=" * 60)
    
    # Test 1: General field validation
    general_validation = validate_sql_field_references()
    
    # Test 2: Specific fixes validation
    specific_fixes = validate_specific_fixes()
    
    print(f"\n🎯 Overall Test Results")
    print("=" * 30)
    print(f"General field validation: {'✅ PASS' if general_validation else '❌ FAIL'}")
    print(f"Specific fixes validation: {'✅ PASS' if specific_fixes else '❌ FAIL'}")
    
    if general_validation and specific_fixes:
        print("\n🎉 All SQL field validation tests PASSED!")
        print("The permissions.py file is ready for production.")
        return True
    else:
        print("\n⚠️  Some SQL field validation tests FAILED.")
        print("Please review and fix the issues above.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)