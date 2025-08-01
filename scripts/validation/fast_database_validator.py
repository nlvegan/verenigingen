#!/usr/bin/env python3
"""
Quick Database Field Validator

Focuses on the most common and critical database query field issues.
Designed to be fast enough for pre-commit hooks.
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional


class QuickDBFieldValidator:
    """Quick validation for critical database field issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name')
                    if not doctype_name:
                        continue
                        
                    fields = set()
                    for field in data.get('fields', []):
                        if 'fieldname' in field:
                            fields.add(field['fieldname'])
                    
                    # Add standard fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception:
                    continue
                    
        return doctypes
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Quick validation of critical issues in a file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Quick regex-based validation for common patterns
            violations.extend(self._check_get_all_filters(content, file_path))
            violations.extend(self._check_get_value_calls(content, file_path))
            
        except Exception:
            pass
            
        return violations
    
    def _check_get_all_filters(self, content: str, file_path: Path) -> List[Dict]:
        """Check frappe.get_all() filters for non-existent fields"""
        violations = []
        lines = content.splitlines()
        
        # Pattern: frappe.get_all("DocType", filters={"field": value})
        pattern = r'frappe\.(?:get_all|get_list)\s*\(\s*["\']([^"\']+)["\']\s*,.*?filters\s*=\s*\{[^}]*["\']([^"\']+)["\']'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            doctype = match.group(1)
            field = match.group(2)
            
            if doctype in self.doctypes and field not in self.doctypes[doctype]:
                line_num = content[:match.start()].count('\n') + 1
                context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                violations.append({
                    'file': str(file_path.relative_to(self.app_path)),
                    'line': line_num,
                    'field': field,
                    'doctype': doctype,
                    'context': context,
                    'issue_type': 'filter_field',
                    'severity': 'high'  # These cause runtime errors
                })
        
        return violations
    
    def _check_get_value_calls(self, content: str, file_path: Path) -> List[Dict]:
        """Check frappe.db.get_value() calls for non-existent fields"""
        violations = []
        lines = content.splitlines()
        
        # Pattern: frappe.db.get_value("DocType", ..., ["field1", "field2"])
        pattern = r'frappe\.db\.get_value\s*\(\s*["\']([^"\']+)["\'].*?\[([^\]]+)\]'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            doctype = match.group(1)
            fields_str = match.group(2)
            
            if doctype not in self.doctypes:
                continue
                
            # Extract field names from the list
            field_pattern = r'["\']([^"\']+)["\']'
            fields = re.findall(field_pattern, fields_str)
            
            for field in fields:
                if field not in self.doctypes[doctype]:
                    line_num = content[:match.start()].count('\n') + 1
                    context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    
                    violations.append({
                        'file': str(file_path.relative_to(self.app_path)),
                        'line': line_num,
                        'field': field,
                        'doctype': doctype,
                        'context': context,
                        'issue_type': 'select_field',
                        'severity': 'high'
                    })
        
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Quick validation of the entire app"""
        violations = []
        
        # Focus on the most important files first
        priority_patterns = [
            "**/templates/pages/*.py",  # Web pages (user-facing)
            "**/api/*.py",              # API endpoints  
            "**/doctype/*/*.py"         # DocType controllers
        ]
        
        for pattern in priority_patterns:
            for py_file in self.app_path.glob(pattern):
                if '__pycache__' not in str(py_file):
                    file_violations = self.validate_file(py_file)
                    violations.extend(file_violations)
        
        return violations


def main():
    """Run quick database field validation"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"
    
    print("🔍 Running quick database field validation...")
    
    validator = QuickDBFieldValidator(app_path)
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    
    violations = validator.validate_app()
    
    if violations:
        # Sort by severity and show most critical first
        critical_violations = [v for v in violations if v['severity'] == 'high']
        
        if critical_violations:
            print(f"\n❌ Found {len(critical_violations)} CRITICAL database field issues:")
            print("   These will cause runtime errors!")
            print("-" * 60)
            
            for v in critical_violations[:10]:  # Show first 10
                print(f"📁 {v['file']}:{v['line']}")
                print(f"   ⚠️  {v['doctype']}.{v['field']} - Field does not exist")
                print(f"   💾 {v['context'][:80]}...")
                print()
                
            if len(critical_violations) > 10:
                print(f"   ... and {len(critical_violations) - 10} more critical issues")
                
        return 1
    else:
        print("✅ No critical database field issues found!")
        return 0


if __name__ == "__main__":
    exit(main())