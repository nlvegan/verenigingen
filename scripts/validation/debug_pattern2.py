#!/usr/bin/env python3
"""Debug problematic_pattern_2"""

import tempfile
import os
from advanced_javascript_field_validator import AdvancedJavaScriptFieldValidator


test_code = '''
frappe.model.get_value("Member", member_name, "fake_field", function(r) {
    // Should be flagged
    console.log(r.message.fake_field);
});
'''

print("🔍 Debug problematic_pattern_2")
print("=" * 40)
print("Test code:")
print(test_code)

with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
    f.write(test_code)
    temp_file = f.name

try:
    validator = AdvancedJavaScriptFieldValidator()
    
    print(f"\nMember doctype available: {'Member' in validator.doctypes}")
    if 'Member' in validator.doctypes:
        member_fields = validator.doctypes['Member']
        print(f"'fake_field' in Member fields: {'fake_field' in member_fields}")
    
    issues = validator.validate_javascript_file(temp_file)
    print(f"\nIssues found: {len(issues)}")
    for issue in issues:
        print(f"  - Line {issue.line_number}: {issue.description}")
    
    # Debug line by line
    print("\nLine-by-line debug:")
    with open(temp_file, 'r') as f:
        lines = f.read().split('\n')
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if line and not line.startswith('//'):
            print(f"\nLine {line_num}: {line}")
            
            should_ignore = validator._should_ignore_line(line, line_num, test_code)
            print(f"  Should ignore: {should_ignore}")
            
            field_refs = validator._extract_field_references(line, line_num)
            print(f"  Field references: {len(field_refs)}")
            for ref in field_refs:
                print(f"    - {ref.field_name} (context: {ref.context})")
            
            doctype = validator._determine_doctype_context(line, test_code, line_num)
            print(f"  DocType context: {doctype}")

finally:
    os.unlink(temp_file)