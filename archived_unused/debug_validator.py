#!/usr/bin/env python3
"""
Debug Validator
Quick test to debug DocType detection
"""

import ast
import json
import re
from pathlib import Path

def test_validation_detection():
    """Test the validation function detection"""
    
    # Read the validations.py file
    content = """
def validate_termination_request(doc, method):
    if doc.termination_type in disciplinary_types:
        if not doc.secondary_approver and doc.status == "Pending Approval":
            frappe.throw(_("Secondary approver is required"))
"""
    
    lines = content.splitlines()
    
    # Look for function definition pattern: def validate_xxx(doc, method):
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith('def ') and '(doc, method)' in line:
            func_name = line.split('def ')[1].split('(')[0].strip()
            print(f"Found validation function: {func_name}")
            
            # Map function names to DocTypes based on common patterns
            doctype_mappings = {
                'validate_termination_request': 'Membership Termination Request',
                'validate_verenigingen_settings': 'Verenigingen Settings',
            }
            
            if func_name in doctype_mappings:
                print(f"Mapped to DocType: {doctype_mappings[func_name]}")
                return doctype_mappings[func_name]
    
    return None

def test_with_actual_file():
    """Test with actual validations.py file"""
    
    file_path = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/validations.py")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        print("File content preview:")
        print(content[:500])
        print("\n" + "="*50 + "\n")
        
        lines = content.splitlines()
        
        # Parse with AST
        tree = ast.parse(content)
        
        # Find all attribute access
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if hasattr(node.value, 'id') and node.value.id == 'doc':
                    line_num = node.lineno
                    field_name = node.attr
                    
                    print(f"Found doc.{field_name} at line {line_num}")
                    
                    # Look for function definition
                    for i in range(max(0, line_num - 20), line_num):
                        if i < len(lines):
                            line = lines[i].strip()
                            if line.startswith('def ') and '(doc, method)' in line:
                                func_name = line.split('def ')[1].split('(')[0].strip()
                                print(f"  -> Found in function: {func_name}")
                                
                                # Map function names to DocTypes
                                doctype_mappings = {
                                    'validate_termination_request': 'Membership Termination Request',
                                    'validate_verenigingen_settings': 'Verenigingen Settings',
                                }
                                
                                if func_name in doctype_mappings:
                                    print(f"  -> Should map to DocType: {doctype_mappings[func_name]}")
                                else:
                                    print(f"  -> No mapping found for: {func_name}")
                                break
                    print()
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing validation function detection:")
    print("="*40)
    test_validation_detection()
    print("\n" + "="*40 + "\n")
    print("Testing with actual file:")
    test_with_actual_file()