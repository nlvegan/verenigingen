#!/usr/bin/env python3
"""
Final Field Validator
Ultra-precise validation focusing only on clear field access patterns
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union


class FinalFieldValidator:
    """Ultra-precise field validation"""
    
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
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names only
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
                    
                    doctypes[doctype_name] = fields
                    
                except Exception:
                    continue
                    
        return doctypes
    
    def get_doctype_from_file_path(self, file_path: Path) -> Optional[str]:
        """Extract doctype name from file path"""
        parts = file_path.parts
        if 'doctype' in parts:
            doctype_idx = parts.index('doctype')
            if doctype_idx + 1 < len(parts):
                doctype_dir = parts[doctype_idx + 1]
                doctype_name = doctype_dir.replace('_', ' ').title()
                return doctype_name
        return None
    
    def is_definitely_field_access(self, node: ast.Attribute, source_lines: List[str]) -> bool:
        """Check if this is definitely a field access (not a method call)"""
        
        # Only check self.attribute patterns
        if not isinstance(node.value, ast.Name) or node.value.id != 'self':
            return False
            
        # Skip Frappe framework built-in attributes
        frappe_builtin_attributes = {
            'flags', 'meta', '_doc_before_save', 'doctype', 'name', 'owner',
            'creation', 'modified', 'modified_by', 'docstatus', 'parent',
            'parenttype', 'parentfield', 'idx', '_user_tags', '_comments',
            '_assign', '_liked_by', '_doc_before_validate', '_doc_before_insert',
            '_doc_before_update', '_doc_before_cancel', '_doc_before_delete',
            '_original_modified'
        }
        
        if node.attr in frappe_builtin_attributes:
            return False
            
        # Skip internal/private attributes (start with _)
        if node.attr.startswith('_'):
            return False
            
        # Skip common property patterns that aren't fields
        property_patterns = {
            'board_manager', 'member_manager', 'communication_manager',
            'volunteer_integration_manager', 'validator', 'is_anbi_eligible'
        }
        
        if node.attr in property_patterns:
            return False
            
        # Get the line content
        line_num = node.lineno - 1
        if line_num >= len(source_lines):
            return False
            
        line = source_lines[line_num].strip()
        
        # Skip if it's clearly a method call
        if f"{node.attr}(" in line:
            return False
            
        # Skip if it's an assignment to self (defining methods/properties)
        if f"self.{node.attr} =" in line:
            return False
            
        # Skip if it's in a function definition line
        if line.startswith('def ') and f"{node.attr}(" in line:
            return False
            
        # Skip common patterns that are definitely not fields
        skip_patterns = [
            f"self.{node.attr}()",  # Method call
            f"def {node.attr}(",    # Method definition  
            f"self.{node.attr} = ",  # Assignment
            f"hasattr(self, '{node.attr}')",  # hasattr check
            f'hasattr(self, "{node.attr}")',  # hasattr check
        ]
        
        for pattern in skip_patterns:
            if pattern in line:
                return False
                
        # Look for field access patterns
        field_access_patterns = [
            f"self.{node.attr}",  # Direct access
            f"if self.{node.attr}",  # Conditional
            f"or self.{node.attr}",  # Boolean operation
            f"and self.{node.attr}",  # Boolean operation
            f"not self.{node.attr}",  # Boolean operation
            f"self.{node.attr} or",  # Boolean operation
            f"self.{node.attr} and",  # Boolean operation
            f"return self.{node.attr}",  # Return statement
            f"self.{node.attr}.",  # Chained access
        ]
        
        for pattern in field_access_patterns:
            if pattern in line:
                return True
                
        return False
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate a single file"""
        violations = []
        
        # Only check files in doctype directories
        doctype_name = self.get_doctype_from_file_path(file_path)
        if not doctype_name or doctype_name not in self.doctypes:
            return violations
            
        valid_fields = self.doctypes[doctype_name]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Find attribute access nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if self.is_definitely_field_access(node, source_lines):
                        field_name = node.attr
                        
                        # Check if this field exists in the doctype
                        if field_name not in valid_fields:
                            # Get context
                            line_num = node.lineno - 1
                            context = source_lines[line_num].strip() if line_num < len(source_lines) else ""
                            
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': node.lineno,
                                'field': field_name,
                                'doctype': doctype_name,
                                'context': context,
                                'confidence': 'high'
                            })
                            
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate the entire app"""
        violations = []
        
        # Only check Python files in doctype directories
        for doctype_dir in self.app_path.rglob("**/doctype/*/"):
            for py_file in doctype_dir.glob("*.py"):
                if py_file.name.startswith('test_'):
                    continue
                    
                file_violations = self.validate_file(py_file)
                violations.extend(file_violations)
                
        return violations
    
    def generate_report(self, violations: List[Dict]) -> str:
        """Generate a focused report"""
        if not violations:
            return "✅ No field reference issues found!"
            
        report = []
        report.append(f"❌ Found {len(violations)} field reference issues:")
        report.append("")
        
        # Group by doctype
        by_doctype = {}
        for violation in violations:
            doctype = violation['doctype']
            if doctype not in by_doctype:
                by_doctype[doctype] = []
            by_doctype[doctype].append(violation)
            
        for doctype, doctype_violations in by_doctype.items():
            report.append(f"## {doctype} ({len(doctype_violations)} issues)")
            
            # Show each violation with context
            for violation in doctype_violations:
                report.append(f"- Field `{violation['field']}` does not exist")
                report.append(f"  - File: {violation['file']}:{violation['line']}")
                report.append(f"  - Context: `{violation['context']}`")
                
                # Suggest similar fields
                similar = self.find_similar_fields(violation['field'], violation['doctype'])
                if similar:
                    report.append(f"  - Similar fields: {', '.join(f'`{f}`' for f in similar)}")
                    
                report.append("")
                
        return '\n'.join(report)
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names"""
        if doctype not in self.doctypes:
            return []
            
        similar = []
        field_lower = field_name.lower()
        
        for existing_field in self.doctypes[doctype]:
            existing_lower = existing_field.lower()
            
            # Check for substring matches
            if (field_lower in existing_lower or 
                existing_lower in field_lower or
                abs(len(field_lower) - len(existing_lower)) <= 2):
                similar.append(existing_field)
                
        return similar[:3]


def main():
    """Main function"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Running final field validation (ultra-precise)...")
    validator = FinalFieldValidator(app_path)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    
    violations = validator.validate_app()
    
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        print(f"\n💡 Found {len(violations)} actual field reference issues")
        return 1
    else:
        print("✅ No field reference issues found!")
        return 0


if __name__ == "__main__":
    exit(main())