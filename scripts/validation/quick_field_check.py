#!/usr/bin/env python3
"""
Quick Field Reference Checker
Fast validation of common docfield reference patterns
"""

import re
import json
from pathlib import Path
from typing import Set, List, Dict


def load_doctype_fields(doctype_path: Path) -> Set[str]:
    """Load fields from a doctype JSON file"""
    try:
        with open(doctype_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        fields = set()
        for field in data.get('fields', []):
            if field.get('fieldname'):
                fields.add(field['fieldname'])
                
        # Add standard fields
        fields.update([
            'name', 'creation', 'modified', 'modified_by', 'owner',
            'docstatus', 'parent', 'parentfield', 'parenttype', 'idx'
        ])
        
        return fields
    except:
        return set()


def check_file_for_field_references(file_path: Path, doctype_name: str, valid_fields: Set[str]) -> List[Dict]:
    """Check a single file for invalid field references"""
    violations = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Common patterns for field access
        patterns = [
            r'(?:self|doc|member|volunteer|chapter|migration)\.(\w+)',
            r'getattr\([^,]+,\s*["\'](\w+)["\']',
            r'setattr\([^,]+,\s*["\'](\w+)["\']',
            r'hasattr\([^,]+,\s*["\'](\w+)["\']',
            r'\.get\(["\'](\w+)["\']',
            r'\.set\(["\'](\w+)["\']',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Skip known methods and standard attributes
                if field_name in ['save', 'insert', 'delete', 'reload', 'submit', 'cancel',
                                'get', 'set', 'update', 'db_set', 'db_get', 'run_method',
                                'flags', 'meta', 'as_dict', 'as_json', 'doctype']:
                    continue
                    
                if field_name not in valid_fields:
                    violations.append({
                        'file': str(file_path),
                        'line': line_num,
                        'field': field_name,
                        'doctype': doctype_name
                    })
                    
    except Exception as e:
        print(f"Error checking {file_path}: {e}")
        
    return violations


def main():
    """Quick field reference check"""
    app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
    violations = []
    
    # Find all doctype directories
    doctype_dirs = list(app_path.rglob("**/doctype/*/"))
    
    for doctype_dir in doctype_dirs:
        # Get doctype name from directory
        doctype_name = doctype_dir.name
        
        # Load doctype fields
        json_file = doctype_dir / f"{doctype_name}.json"
        if not json_file.exists():
            continue
            
        valid_fields = load_doctype_fields(json_file)
        if not valid_fields:
            continue
            
        # Check Python files in this doctype directory
        python_files = list(doctype_dir.glob("*.py"))
        
        for py_file in python_files:
            if py_file.name.startswith('test_'):
                continue
                
            file_violations = check_file_for_field_references(py_file, doctype_name, valid_fields)
            violations.extend(file_violations)
            
    # Report results
    if violations:
        print(f"❌ Found {len(violations)} potential field reference issues:")
        for violation in violations[:10]:  # Show first 10
            print(f"  {violation['file']}:{violation['line']} - {violation['field']} not in {violation['doctype']}")
        if len(violations) > 10:
            print(f"  ... and {len(violations) - 10} more")
        return 1
    else:
        print("✅ No obvious field reference issues found")
        return 0


if __name__ == "__main__":
    exit(main())