#!/usr/bin/env python3
"""
Debug version of improved validator to see what's happening
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ValidationIssue:
    """Represents a field validation issue"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: str
    issue_type: str
    suggested_fix: Optional[str] = None

class DebugImprovedFieldValidator:
    """Debug version with extra logging"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.doctypes = self.load_all_doctypes()
        
    def load_all_doctypes(self) -> Dict[str, Dict]:
        """Load doctypes from all installed apps"""
        doctypes = {}
        
        # Standard apps to check
        app_paths = [
            self.bench_path / "apps" / "frappe",  # Core Frappe
            self.bench_path / "apps" / "erpnext",  # ERPNext if available
            self.bench_path / "apps" / "payments",  # Payments app if available
            self.app_path,  # Current app (verenigingen)
        ]
        
        for app_path in app_paths:
            if app_path.exists():
                app_doctypes = self._load_doctypes_from_app(app_path)
                doctypes.update(app_doctypes)
                
        return doctypes
    
    def _load_doctypes_from_app(self, app_path: Path) -> Dict[str, Dict]:
        """Load doctypes from a specific app"""
        doctypes = {}
        
        # Find all doctype JSON files
        for json_file in app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names
                    fields = set()
                    for field in data.get('fields', []):
                        fieldname = field.get('fieldname')
                        if fieldname:
                            fields.add(fieldname)
                            
                    # Add standard Frappe document fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
                        'doctype', '_user_tags', '_comments', '_assign', '_liked_by'
                    ])
                    
                    doctypes[doctype_name] = {
                        'fields': fields,
                        'data': data,
                        'app': app_path.name
                    }
                    
                except Exception as e:
                    continue
                    
        return doctypes
        
    def _guess_doctype_from_validation_context(self, content: str, lines: List[str], line_no: int) -> Optional[str]:
        """Guess DocType from validation function context"""
        
        print(f"DEBUG: Looking for validation context at line {line_no}")
        
        # Look for function definition pattern: def validate_xxx(doc, method):
        for i in range(max(0, line_no - 20), line_no):
            if i < len(lines):
                line = lines[i].strip()
                if line.startswith('def ') and '(doc, method)' in line:
                    func_name = line.split('def ')[1].split('(')[0].strip()
                    print(f"DEBUG: Found validation function: {func_name}")
                    
                    # Map function names to DocTypes based on common patterns
                    doctype_mappings = {
                        'validate_termination_request': 'Membership Termination Request',
                        'validate_verenigingen_settings': 'Verenigingen Settings',
                        'validate_member': 'Member',
                        'validate_membership': 'Membership',
                        'validate_volunteer': 'Verenigingen Volunteer',
                        'validate_chapter': 'Chapter',
                        'validate_volunteer_expense': 'Volunteer Expense',
                        'validate_sepa_mandate': 'SEPA Mandate',
                        'validate_payment_plan': 'Payment Plan',
                        'validate_membership_application': 'Membership Application',
                        'validate_direct_debit_batch': 'Direct Debit Batch',
                        'validate_donation_campaign': 'Donation Campaign',
                        'validate_membership_dues_schedule': 'Membership Dues Schedule',
                    }
                    
                    if func_name in doctype_mappings:
                        mapped_doctype = doctype_mappings[func_name]
                        print(f"DEBUG: Mapped to DocType: {mapped_doctype}")
                        return mapped_doctype
                    else:
                        print(f"DEBUG: No mapping found for function: {func_name}")
        
        print(f"DEBUG: No validation function found")
        return None
        
    def _guess_doctype_from_context(self, content: str, node: ast.Attribute, obj_name: str) -> Optional[str]:
        """Enhanced DocType guessing from context using AST"""
        
        print(f"DEBUG: Guessing DocType for {obj_name}.{node.attr} at line {node.lineno}")
        
        # Extract context around the node
        lines = content.splitlines()
        
        # Special case: Handle validation functions with (doc, method) pattern
        if obj_name == 'doc':
            print(f"DEBUG: Detected 'doc' object, checking validation context")
            doctype = self._guess_doctype_from_validation_context(content, lines, node.lineno)
            if doctype:
                print(f"DEBUG: Found DocType from validation context: {doctype}")
                return doctype
            else:
                print(f"DEBUG: No DocType found from validation context")
        
        print(f"DEBUG: No DocType detected")
        return None
        
    def test_single_field(self, content: str, target_line: int):
        """Test a single field detection"""
        
        tree = ast.parse(content)
        source_lines = content.splitlines()
        
        # Walk through AST nodes to find attribute access
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.lineno == target_line:
                # Extract object and attribute names
                if hasattr(node.value, 'id'):
                    obj_name = node.value.id
                    field_name = node.attr
                    
                    print(f"Found {obj_name}.{field_name} at line {node.lineno}")
                    
                    # Try to determine DocType from context
                    doctype = self._guess_doctype_from_context(content, node, obj_name)
                    
                    if doctype:
                        print(f"Detected DocType: {doctype}")
                        
                        if doctype in self.doctypes:
                            doctype_info = self.doctypes[doctype]
                            fields = doctype_info['fields']
                            
                            if field_name in fields:
                                print(f"✅ Field '{field_name}' exists in {doctype}")
                            else:
                                print(f"❌ Field '{field_name}' does NOT exist in {doctype}")
                                print(f"Available fields: {sorted(list(fields))[:10]}...")
                        else:
                            print(f"DocType '{doctype}' not found in loaded doctypes")
                    else:
                        print("No DocType detected")
                    
                    break

def test_specific_case():
    """Test the specific case that's failing"""
    
    validator = DebugImprovedFieldValidator('/home/frappe/frappe-bench/apps/verenigingen')
    
    # Read the validations.py file
    file_path = Path('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/validations.py')
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("Testing doc.termination_type detection:")
    print("="*50)
    
    # Find the line with doc.termination_type
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        if 'doc.termination_type' in line:
            print(f"Found at line {i}: {line.strip()}")
            validator.test_single_field(content, i)
            break

if __name__ == "__main__":
    test_specific_case()