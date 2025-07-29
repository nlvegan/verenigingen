#!/usr/bin/env python3
"""
Debug Advanced JavaScript Field Validator
==========================================

Debug script to understand why the validator isn't catching real DocType field issues.
"""

import tempfile
import os
from advanced_javascript_field_validator import AdvancedJavaScriptFieldValidator


def debug_problematic_pattern():
    """Debug why problematic patterns aren't being caught"""
    
    # Test code that should trigger an error
    test_code = '''
    frappe.ui.form.on('Member', {
        refresh: function(frm) {
            frm.set_value("nonexistent_field", "value"); // Should be flagged
        }
    });
    '''
    
    print("🔍 Debug: Testing problematic pattern")
    print("=" * 50)
    print("Test code:")
    print(test_code)
    print()
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(test_code)
        temp_file = f.name
    
    try:
        validator = AdvancedJavaScriptFieldValidator()
        
        # Check if Member doctype exists
        print(f"Member doctype available: {'Member' in validator.doctypes}")
        if 'Member' in validator.doctypes:
            member_fields = validator.doctypes['Member']
            print(f"Member has {len(member_fields)} fields")
            print(f"'nonexistent_field' in Member fields: {'nonexistent_field' in member_fields}")
        print()
        
        # Validate the file with debug
        print("Running validation...")
        issues = validator.validate_javascript_file(temp_file)
        
        print(f"Issues found: {len(issues)}")
        for issue in issues:
            print(f"  - Line {issue.line_number}: {issue.description}")
            print(f"    Expression: {issue.expression}")
        
        # Let's also debug line by line
        print("\nLine-by-line analysis:")
        with open(temp_file, 'r') as f:
            lines = f.read().split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if line and not line.startswith('//'):
                print(f"Line {line_num}: {line}")
                
                # Check if line should be ignored
                should_ignore = validator._should_ignore_line(line, line_num, test_code)
                print(f"  Should ignore: {should_ignore}")
                
                # Check for field references
                field_refs = validator._extract_field_references(line, line_num)
                print(f"  Field references found: {len(field_refs)}")
                for ref in field_refs:
                    print(f"    - Field: {ref.field_name}, Context: {ref.context}")
                
                # Check DocType context
                doctype = validator._determine_doctype_context(line, test_code, line_num)
                print(f"  DocType context: {doctype}")
                print()
        
    finally:
        os.unlink(temp_file)


def debug_field_patterns():
    """Debug field extraction patterns"""
    
    validator = AdvancedJavaScriptFieldValidator()
    
    test_lines = [
        'frm.set_value("nonexistent_field", "value");',
        'frm.get_field("invalid_field").hidden = 1;',
        'frappe.model.get_value("Member", member_name, "fake_field", function(r) {',
        'fields: ["name", "nonexistent_field"]',
    ]
    
    print("🔍 Debug: Field extraction patterns")
    print("=" * 50)
    
    for line in test_lines:
        print(f"Testing line: {line}")
        
        # Test each pattern individually
        for i, pattern in enumerate(validator.doctype_field_patterns):
            matches = list(re.finditer(pattern, line, re.IGNORECASE))
            if matches:
                print(f"  Pattern {i} matched: {pattern}")
                for match in matches:
                    print(f"    Field found: {match.group(1)}")
        
        print()


if __name__ == "__main__":
    import re  # Import re for the debug function
    debug_problematic_pattern()
    print("\n" + "=" * 60 + "\n")
    debug_field_patterns()