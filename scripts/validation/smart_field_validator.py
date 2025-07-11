#!/usr/bin/env python3
"""
Smart Field Validator
Intelligent validation of docfield references with context awareness
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple


class SmartFieldValidator:
    """Validates docfield references with context awareness"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_all_doctypes()
        self.false_positives = self.load_false_positives()
        
    def load_all_doctypes(self) -> Dict[str, Set[str]]:
        """Load all doctype definitions"""
        doctypes = {}
        
        # Find all doctype JSON files
        json_files = list(self.app_path.rglob("**/doctype/*/*.json"))
        
        for json_file in json_files:
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract fields
                    fields = set()
                    for field in data.get('fields', []):
                        if field.get('fieldname'):
                            fields.add(field['fieldname'])
                            
                    # Add standard Frappe fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
                        '_user_tags', '_comments', '_assign', '_liked_by', 'doctype'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception as e:
                    print(f"Error loading {json_file}: {e}")
                    
        return doctypes
    
    def load_false_positives(self) -> Set[str]:
        """Load common false positives to ignore"""
        return {
            # Standard methods
            'save', 'insert', 'delete', 'reload', 'submit', 'cancel', 'validate',
            'before_save', 'after_insert', 'before_delete', 'on_update', 'on_submit',
            'on_cancel', 'before_submit', 'before_cancel', 'after_delete',
            
            # Standard attributes
            'flags', 'meta', 'as_dict', 'as_json', 'get_formatted', 'get_value',
            'set_value', 'db_set', 'db_get', 'run_method', 'has_permission',
            'get_doc_before_save', 'get_title', 'get_feed', 'get_timeline_data',
            
            # Common variable names that aren't fields
            'app', 'module', 'method', 'function', 'class', 'object', 'item',
            'key', 'value', 'data', 'result', 'response', 'request', 'config',
            'settings', 'params', 'args', 'kwargs', 'context', 'session',
            'user', 'role', 'permission', 'filter', 'sort', 'limit', 'offset',
            'page', 'size', 'count', 'total', 'sum', 'avg', 'min', 'max',
            
            # Python built-ins and common libraries
            'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
            'append', 'extend', 'remove', 'pop', 'clear', 'copy', 'update',
            'keys', 'values', 'items', 'get', 'set', 'add', 'discard',
            'join', 'split', 'replace', 'strip', 'lower', 'upper', 'title',
            'startswith', 'endswith', 'find', 'index', 'count', 'format',
        }
    
    def extract_doctype_context(self, file_path: Path, line_content: str) -> Optional[str]:
        """Extract doctype from context with improved heuristics"""
        
        # Check file path first
        path_parts = file_path.parts
        if 'doctype' in path_parts:
            doctype_idx = path_parts.index('doctype')
            if doctype_idx + 1 < len(path_parts):
                potential_doctype = path_parts[doctype_idx + 1]
                # Convert from filename to proper doctype name
                doctype_name = potential_doctype.replace('_', ' ').title()
                if doctype_name in self.doctypes:
                    return doctype_name
                    
        # Check line content for doctype hints
        doctype_patterns = [
            r'frappe\.get_doc\(["\']([^"\']+)["\']',
            r'frappe\.new_doc\(["\']([^"\']+)["\']',
            r'doctype\s*[=:]\s*["\']([^"\']+)["\']',
            r'self\.doctype\s*==\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in doctype_patterns:
            matches = re.findall(pattern, line_content, re.IGNORECASE)
            if matches:
                potential_doctype = matches[0]
                if potential_doctype in self.doctypes:
                    return potential_doctype
                    
        return None
    
    def is_likely_field_access(self, node: ast.Attribute, source_lines: List[str]) -> bool:
        """Determine if attribute access is likely a field reference"""
        
        # Get the line content for context
        line_num = node.lineno - 1
        if line_num < len(source_lines):
            line_content = source_lines[line_num]
        else:
            line_content = ""
            
        # Check if it's a method call (followed by parentheses)
        if '(' in line_content and line_content.find('(') > line_content.find(node.attr):
            return False
            
        # Check if the variable name suggests it's a document
        if isinstance(node.value, ast.Name):
            var_name = node.value.id.lower()
            if any(hint in var_name for hint in ['doc', 'self', 'member', 'volunteer', 'chapter']):
                return True
                
        return False
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate a single Python file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Extract doctype from file context
            file_doctype = self.extract_doctype_context(file_path, content)
            
            # Walk through AST nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    
                    # Check if this looks like field access
                    if not self.is_likely_field_access(node, source_lines):
                        continue
                        
                    field_name = node.attr
                    
                    # Skip false positives
                    if field_name in self.false_positives:
                        continue
                        
                    # Skip private/dunder attributes
                    if field_name.startswith('_'):
                        continue
                        
                    # Get line content for context
                    line_content = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                    
                    # Try to determine doctype
                    doctype = (
                        self.extract_doctype_context(file_path, line_content) or 
                        file_doctype
                    )
                    
                    if doctype and doctype in self.doctypes:
                        if field_name not in self.doctypes[doctype]:
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': node.lineno,
                                'field': field_name,
                                'doctype': doctype,
                                'context': line_content.strip(),
                                'confidence': 'high' if file_doctype else 'medium'
                            })
                            
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def validate_app(self, include_tests: bool = False) -> List[Dict]:
        """Validate entire app"""
        violations = []
        
        # Find Python files
        python_files = []
        for pattern in ["**/*.py"]:
            python_files.extend(self.app_path.rglob(pattern))
            
        for py_file in python_files:
            # Skip test files unless requested
            if not include_tests and 'test_' in py_file.name:
                continue
                
            # Skip migrations and __pycache__
            if any(skip in str(py_file) for skip in ['migration', '__pycache__', '.git']):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations
    
    def generate_report(self, violations: List[Dict], limit: int = 50) -> str:
        """Generate validation report"""
        report = []
        
        if not violations:
            report.append("✅ No field reference violations found!")
            return '\n'.join(report)
            
        report.append(f"❌ Found {len(violations)} potential field reference violations:")
        report.append("")
        
        # Sort by confidence and doctype
        violations.sort(key=lambda x: (x['confidence'], x['doctype'], x['field']))
        
        # Group by doctype
        by_doctype = {}
        for violation in violations:
            doctype = violation['doctype']
            if doctype not in by_doctype:
                by_doctype[doctype] = []
            by_doctype[doctype].append(violation)
            
        shown = 0
        for doctype, doctype_violations in by_doctype.items():
            if shown >= limit:
                break
                
            report.append(f"## {doctype} ({len(doctype_violations)} violations)")
            
            for violation in doctype_violations[:10]:  # Limit per doctype
                if shown >= limit:
                    break
                    
                report.append(f"- **{violation['field']}** ({violation['confidence']} confidence)")
                report.append(f"  - `{violation['file']}:{violation['line']}`")
                report.append(f"  - Context: `{violation['context']}`")
                report.append("")
                shown += 1
                
        if len(violations) > shown:
            report.append(f"... and {len(violations) - shown} more violations")
            
        return '\n'.join(report)


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate docfield references")
    parser.add_argument("--include-tests", action="store_true", help="Include test files")
    parser.add_argument("--limit", type=int, default=50, help="Limit output")
    parser.add_argument("--output", type=str, help="Output file")
    
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Validating docfield references...")
    validator = SmartFieldValidator(app_path)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    
    violations = validator.validate_app(include_tests=args.include_tests)
    
    report = validator.generate_report(violations, limit=args.limit)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"📄 Report saved to {args.output}")
    else:
        print(report)
        
    return 1 if violations else 0


if __name__ == "__main__":
    exit(main())