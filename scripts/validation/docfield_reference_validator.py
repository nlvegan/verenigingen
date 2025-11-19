#!/usr/bin/env python3
"""
Docfield Reference Validator
Validates that all field references in Python code actually exist in the corresponding doctype definitions.
"""

import ast
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


class DocfieldReferenceValidator:
    """Validates docfield references across the codebase"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = {}
        self.violations = []
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load all doctype definitions and their fields"""
        doctypes = {}
        
        # Find all doctype directories
        doctype_dirs = list(self.app_path.rglob("**/doctype/*/"))
        
        for doctype_dir in doctype_dirs:
            # Look for doctype.json files
            json_files = list(doctype_dir.glob("*.json"))
            
            for json_file in json_files:
                if json_file.stem == json_file.parent.name:  # doctype.json matches directory name
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            doctype_data = json.load(f)
                            
                        doctype_name = doctype_data.get('name', json_file.stem)
                        
                        # Extract field names
                        fields = set()
                        for field in doctype_data.get('fields', []):
                            if field.get('fieldname'):
                                fields.add(field['fieldname'])
                        
                        # Add standard fields that always exist
                        fields.update([
                            'name', 'creation', 'modified', 'modified_by', 'owner',
                            'docstatus', 'parent', 'parentfield', 'parenttype',
                            'idx', '_user_tags', '_comments', '_assign', '_liked_by'
                        ])
                        
                        doctypes[doctype_name] = fields
                        
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Error loading doctype {json_file}: {e}")
                        
        return doctypes
    
    def find_field_references(self, python_file: Path) -> List[Tuple[str, str, int]]:
        """Find all docfield references in a Python file"""
        references = []
        
        try:
            with open(python_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse the AST
            tree = ast.parse(content)
            
            # Find attribute access patterns
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    # Look for patterns like: doc.field_name, self.field_name, etc.
                    if isinstance(node.value, ast.Name):
                        var_name = node.value.id
                        attr_name = node.attr
                        
                        # Skip known non-docfield attributes
                        if attr_name in ['save', 'insert', 'delete', 'reload', 'submit', 'cancel', 
                                        'get', 'set', 'update', 'db_set', 'db_get', 'run_method',
                                        'flags', 'meta', '__dict__', '__class__', '__module__']:
                            continue
                            
                        references.append((var_name, attr_name, node.lineno))
                        
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"Error parsing {python_file}: {e}")
            
        return references
    
    def extract_doctype_from_context(self, python_file: Path, line_num: int) -> str:
        """Try to determine the doctype from context"""
        try:
            with open(python_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # Look for doctype hints in nearby lines
            start = max(0, line_num - 10)
            end = min(len(lines), line_num + 5)
            
            context = '\n'.join(lines[start:end])
            
            # Pattern matching for doctype identification
            patterns = [
                r'frappe\.get_doc\(["\']([^"\']+)["\']',
                r'frappe\.new_doc\(["\']([^"\']+)["\']',
                r'doctype["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                r'self\.doctype\s*==\s*["\']([^"\']+)["\']',
                r'class\s+(\w+)\s*\(',  # Class name might match doctype
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, context, re.IGNORECASE)
                if matches:
                    return matches[0]
                    
            # Check if file path contains doctype info
            path_parts = python_file.parts
            if 'doctype' in path_parts:
                doctype_idx = path_parts.index('doctype')
                if doctype_idx + 1 < len(path_parts):
                    return path_parts[doctype_idx + 1].replace('_', ' ').title()
                    
        except Exception as e:
            print(f"Error extracting doctype context from {python_file}:{line_num}: {e}")
            
        return None
    
    def validate_references(self) -> List[Dict]:
        """Validate all field references in Python files"""
        violations = []
        
        # Load doctype definitions
        self.doctypes = self.load_doctypes()
        print(f"Loaded {len(self.doctypes)} doctypes")
        
        # Find all Python files
        python_files = list(self.app_path.rglob("*.py"))
        
        for python_file in python_files:
            # Skip test files and migrations
            if any(skip in str(python_file) for skip in ['test_', 'migration', '__pycache__']):
                continue
                
            references = self.find_field_references(python_file)
            
            for var_name, field_name, line_num in references:
                # Try to determine the doctype
                doctype = self.extract_doctype_from_context(python_file, line_num)
                
                if doctype and doctype in self.doctypes:
                    if field_name not in self.doctypes[doctype]:
                        violations.append({
                            'file': str(python_file),
                            'line': line_num,
                            'doctype': doctype,
                            'field': field_name,
                            'variable': var_name,
                            'severity': 'error'
                        })
                        
        return violations
    
    def generate_report(self, violations: List[Dict]) -> str:
        """Generate a human-readable report"""
        report = []
        report.append("# Docfield Reference Validation Report")
        report.append(f"Generated: {os.popen('date').read().strip()}")
        report.append("")
        
        if not violations:
            report.append("✅ No docfield reference violations found!")
            return '\n'.join(report)
            
        report.append(f"❌ Found {len(violations)} potential docfield reference violations:")
        report.append("")
        
        # Group by doctype
        by_doctype = {}
        for violation in violations:
            doctype = violation['doctype']
            if doctype not in by_doctype:
                by_doctype[doctype] = []
            by_doctype[doctype].append(violation)
            
        for doctype, doctype_violations in by_doctype.items():
            report.append(f"## {doctype} ({len(doctype_violations)} violations)")
            report.append("")
            
            for violation in doctype_violations:
                report.append(f"- **{violation['field']}** not found in {doctype}")
                report.append(f"  - File: `{violation['file']}:{violation['line']}`")
                report.append(f"  - Variable: `{violation['variable']}.{violation['field']}`")
                report.append("")
                
        # Add summary
        report.append("## Summary")
        report.append(f"- Total violations: {len(violations)}")
        report.append(f"- Doctypes affected: {len(by_doctype)}")
        report.append(f"- Most common issues:")
        
        # Count field frequency
        field_counts = {}
        for violation in violations:
            field = violation['field']
            field_counts[field] = field_counts.get(field, 0) + 1
            
        for field, count in sorted(field_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            report.append(f"  - `{field}`: {count} occurrences")
            
        return '\n'.join(report)
    
    def fix_suggestions(self, violations: List[Dict]) -> List[str]:
        """Generate fix suggestions"""
        suggestions = []
        
        for violation in violations:
            doctype = violation['doctype']
            field = violation['field']
            
            # Check for similar field names
            if doctype in self.doctypes:
                similar_fields = []
                for existing_field in self.doctypes[doctype]:
                    if (field.lower() in existing_field.lower() or 
                        existing_field.lower() in field.lower()):
                        similar_fields.append(existing_field)
                        
                if similar_fields:
                    suggestions.append(f"❓ Did you mean `{similar_fields[0]}` instead of `{field}` in {doctype}?")
                    
        return suggestions[:20]  # Limit to top 20 suggestions


def main():
    """Main execution function"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Starting docfield reference validation...")
    
    validator = DocfieldReferenceValidator(app_path)
    violations = validator.validate_references()
    
    # Generate report
    report = validator.generate_report(violations)
    
    # Save report
    report_file = Path(app_path) / "docfield_validation_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
        
    print(f"📋 Report saved to: {report_file}")
    
    # Generate suggestions
    suggestions = validator.fix_suggestions(violations)
    if suggestions:
        print("\n💡 Fix suggestions:")
        for suggestion in suggestions:
            print(f"  {suggestion}")
    
    # Exit with error code if violations found
    if violations:
        print(f"\n❌ Found {len(violations)} violations - see report for details")
        return 1
    else:
        print("\n✅ No docfield reference violations found!")
        return 0


if __name__ == "__main__":
    exit(main())