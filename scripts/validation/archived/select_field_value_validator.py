#!/usr/bin/env python3
"""
Select Field Value Validator
============================

Validates that values assigned to Select fields match their defined options.
This addresses a critical validation gap discovered during Phase 3 Integration Testing.

Problem Solved
--------------
During Phase 3 testing, we discovered that invalid Select field values like
`status = "Approved"` were not caught when the valid options were 
`["Requested", "Queued", "Processing", "Completed", "Failed", "Cancelled"]`.

This validator fills that gap by:
1. Identifying all Select field assignments in code
2. Extracting the assigned values
3. Validating against the field's defined options
4. Reporting violations with file:line locations

Integration
-----------
Can be integrated into pre-commit hooks to prevent invalid Select values
from entering the codebase.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

# Import the DocType loader
sys.path.insert(0, str(Path(__file__).parent))
from doctype_loader import DocTypeLoader


@dataclass
class SelectFieldViolation:
    """Represents a Select field value constraint violation"""
    file_path: str
    line_number: int
    doctype: str
    field_name: str
    invalid_value: str
    valid_options: List[str]
    context: str
    confidence: float = 1.0


class SelectFieldValueValidator:
    """Validates Select field value assignments against their defined options"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.verbose = verbose
        
        # Load DocType schemas
        bench_path = self.app_path.parent.parent
        self.loader = DocTypeLoader(str(bench_path), verbose=False)
        self.doctypes = self.loader.get_doctypes()
        
        # Cache Select field options for quick lookup
        self.select_fields = self._build_select_field_cache()
        
        if self.verbose:
            print(f"📋 Loaded {len(self.doctypes)} DocTypes")
            print(f"🎯 Found {len(self.select_fields)} Select fields to validate")
    
    def _build_select_field_cache(self) -> Dict[Tuple[str, str], List[str]]:
        """Build a cache of (doctype, field) -> valid_options"""
        cache = {}
        
        for doctype_name, doctype_meta in self.doctypes.items():
            # Check standard fields
            for field_name, field_meta in doctype_meta.fields.items():
                if field_meta.fieldtype == 'Select' and field_meta.options:
                    options = self._parse_select_options(field_meta.options)
                    if options:
                        cache[(doctype_name, field_name)] = options
            
            # Check custom fields
            for field_name, field_meta in doctype_meta.custom_fields.items():
                if field_meta.fieldtype == 'Select' and field_meta.options:
                    options = self._parse_select_options(field_meta.options)
                    if options:
                        cache[(doctype_name, field_name)] = options
        
        return cache
    
    def _parse_select_options(self, options_str: str) -> List[str]:
        """Parse Select field options (newline-separated)"""
        if not options_str:
            return []
        
        # Handle both newline and comma separated (some legacy formats)
        if '\n' in options_str:
            options = [opt.strip() for opt in options_str.split('\n') if opt.strip()]
        elif ',' in options_str:
            options = [opt.strip() for opt in options_str.split(',') if opt.strip()]
        else:
            # Single option
            options = [options_str.strip()] if options_str.strip() else []
        
        return options
    
    def validate_file(self, file_path: Path) -> List[SelectFieldViolation]:
        """Validate Select field values in a Python file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception:
            return violations
        
        # Parse AST
        try:
            tree = ast.parse(content, filename=str(file_path))
            assignments = self._extract_field_assignments(tree, lines)
        except SyntaxError:
            # Fallback to regex
            assignments = self._extract_assignments_regex(lines)
        
        # Validate each assignment
        for assignment in assignments:
            violation = self._validate_assignment(assignment, str(file_path))
            if violation:
                violations.append(violation)
        
        return violations
    
    def _extract_field_assignments(self, tree: ast.AST, lines: List[str]) -> List[Dict]:
        """Extract field assignments from AST"""
        assignments = []
        
        class AssignmentVisitor(ast.NodeVisitor):
            def visit_Assign(self, node):
                # Look for doc.field = "value" patterns
                if len(node.targets) == 1:
                    target = node.targets[0]
                    
                    # Check for attribute assignment (obj.field)
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        obj_name = target.value.id
                        field_name = target.attr
                        
                        # Extract the assigned value if it's a string constant
                        value = None
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            value = node.value.value
                        elif isinstance(node.value, ast.Str):  # Python 3.7 compatibility
                            value = node.value.s
                        
                        if value and field_name in ['status', 'state', 'type', 'category', 'priority']:
                            # Common Select field names
                            assignments.append({
                                'obj_name': obj_name,
                                'field_name': field_name,
                                'value': value,
                                'line': node.lineno,
                                'context': lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                            })
                
                # Also check for dict assignments like doc['status'] = "value"
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
                    target = node.targets[0]
                    if isinstance(target.value, ast.Name) and isinstance(target.slice, ast.Constant):
                        obj_name = target.value.id
                        field_name = target.slice.value
                        
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            value = node.value.value
                            
                            assignments.append({
                                'obj_name': obj_name,
                                'field_name': field_name,
                                'value': value,
                                'line': node.lineno,
                                'context': lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                            })
                
                self.generic_visit(node)
            
            def visit_Call(self, node):
                # Check for set_value calls: doc.set_value('status', 'Approved')
                if (isinstance(node.func, ast.Attribute) and 
                    node.func.attr in ['set_value', 'set', 'update']):
                    
                    if isinstance(node.func.value, ast.Name):
                        obj_name = node.func.value.id
                        
                        # Extract field and value from arguments
                        if len(node.args) >= 2:
                            field_name = None
                            value = None
                            
                            if isinstance(node.args[0], ast.Constant):
                                field_name = node.args[0].value
                            if isinstance(node.args[1], ast.Constant):
                                value = node.args[1].value
                            
                            if field_name and value and isinstance(value, str):
                                assignments.append({
                                    'obj_name': obj_name,
                                    'field_name': field_name,
                                    'value': value,
                                    'line': node.lineno,
                                    'context': lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                                })
                
                self.generic_visit(node)
        
        visitor = AssignmentVisitor()
        visitor.visit(tree)
        return assignments
    
    def _extract_assignments_regex(self, lines: List[str]) -> List[Dict]:
        """Fallback regex-based extraction"""
        assignments = []
        
        patterns = [
            # doc.status = "value"
            r'(\w+)\.(\w+)\s*=\s*["\']([^"\']+)["\']',
            # doc['status'] = "value"
            r'(\w+)\[["\'](\w+)["\']\]\s*=\s*["\']([^"\']+)["\']',
            # doc.set_value('status', 'value')
            r'(\w+)\.set_value\(["\'](\w+)["\'],\s*["\']([^"\']+)["\']\)',
        ]
        
        for i, line in enumerate(lines):
            for pattern in patterns:
                matches = re.findall(pattern, line)
                for match in matches:
                    assignments.append({
                        'obj_name': match[0],
                        'field_name': match[1],
                        'value': match[2],
                        'line': i + 1,
                        'context': line.strip()
                    })
        
        return assignments
    
    def _validate_assignment(self, assignment: Dict, file_path: str) -> Optional[SelectFieldViolation]:
        """Validate a single field assignment"""
        obj_name = assignment['obj_name']
        field_name = assignment['field_name']
        value = assignment['value']
        
        # Try to determine the DocType
        # This is simplified - in practice would need better type inference
        doctype = self._infer_doctype(obj_name, assignment['context'])
        
        if not doctype:
            return None
        
        # Check if this is a Select field with constraints
        key = (doctype, field_name)
        if key not in self.select_fields:
            return None
        
        valid_options = self.select_fields[key]
        
        # Check if value is valid
        if value not in valid_options:
            return SelectFieldViolation(
                file_path=file_path,
                line_number=assignment['line'],
                doctype=doctype,
                field_name=field_name,
                invalid_value=value,
                valid_options=valid_options,
                context=assignment['context']
            )
        
        return None
    
    def _infer_doctype(self, obj_name: str, context: str) -> Optional[str]:
        """Try to infer the DocType from variable name and context"""
        
        # Check context for frappe.get_doc patterns
        patterns = [
            r'frappe\.get_doc\(["\'](\w+)["\']',
            r'frappe\.new_doc\(["\'](\w+)["\']',
            r'DocType:\s*["\'](\w+)["\']',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                doctype = match.group(1)
                if doctype in self.doctypes:
                    return doctype
        
        # Try to infer from variable naming
        name_mappings = {
            'member': 'Member',
            'chapter': 'Chapter',
            'volunteer': 'Volunteer',
            'invoice': 'Sales Invoice',
            'payment': 'Payment Entry',
            'account_creation_request': 'Account Creation Request',
            'chapter_join_request': 'Chapter Join Request',
        }
        
        obj_lower = obj_name.lower()
        for pattern, doctype in name_mappings.items():
            if pattern in obj_lower and doctype in self.doctypes:
                return doctype
        
        return None
    
    def validate_directory(self, directory: Optional[Path] = None) -> List[SelectFieldViolation]:
        """Validate all Python files in a directory"""
        search_path = directory or self.app_path
        violations = []
        
        if self.verbose:
            print(f"🔍 Validating Select field values in {search_path}")
        
        file_count = 0
        for py_file in search_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            file_count += 1
            
            if self.verbose and file_count % 50 == 0:
                print(f"   Processed {file_count} files, found {len(violations)} violations...")
        
        if self.verbose:
            print(f"✅ Validated {file_count} files")
        
        return violations
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Determine if a file should be skipped"""
        skip_patterns = ['__pycache__', '.git', 'node_modules', '.pyc']
        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)
    
    def generate_report(self, violations: List[SelectFieldViolation]) -> str:
        """Generate a validation report"""
        if not violations:
            return "✅ No Select field value violations found!"
        
        report = []
        report.append(f"❌ Found {len(violations)} Select field value violations\n")
        
        # Group by file
        by_file = defaultdict(list)
        for v in violations:
            by_file[v.file_path].append(v)
        
        for file_path, file_violations in sorted(by_file.items()):
            report.append(f"\n📄 {file_path}")
            for v in file_violations:
                report.append(f"   Line {v.line_number}: {v.doctype}.{v.field_name} = '{v.invalid_value}'")
                report.append(f"   ❌ Invalid value. Valid options: {v.valid_options[:5]}")
                if len(v.valid_options) > 5:
                    report.append(f"      ... and {len(v.valid_options) - 5} more options")
                report.append(f"   Context: {v.context}")
        
        return '\n'.join(report)


def main():
    """Main function for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Select Field Value Validator')
    parser.add_argument('--app-path', default='/home/frappe/frappe-bench/apps/verenigingen',
                       help='Path to the Frappe app')
    parser.add_argument('--file', type=str,
                       help='Validate single file')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--pre-commit', action='store_true',
                       help='Pre-commit mode (exit with error if violations found)')
    
    args = parser.parse_args()
    
    # Initialize validator
    validator = SelectFieldValueValidator(
        app_path=args.app_path,
        verbose=args.verbose
    )
    
    # Run validation
    if args.file:
        violations = validator.validate_file(Path(args.file))
    else:
        violations = validator.validate_directory()
    
    # Generate report
    report = validator.generate_report(violations)
    print(report)
    
    # Exit code for pre-commit
    if args.pre_commit and violations:
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())