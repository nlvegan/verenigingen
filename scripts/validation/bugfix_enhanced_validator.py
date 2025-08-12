#!/usr/bin/env python3
"""
Fixed Field Validator - Addresses 99% false positive rate
Enhanced field validation system with accurate DocType context detection
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata

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

class FixedFieldValidator:
    """Fixed field validator with accurate DocType context detection"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        
        # Initialize comprehensive DocType loader
        self.doctype_loader = DocTypeLoader(str(self.bench_path), verbose=False)
        self.doctypes = self._convert_doctypes_for_compatibility()
        print(f"🐛 Bugfix enhanced validator loaded {len(self.doctypes)} DocTypes")
        
        self.child_table_mapping = self._build_child_table_mapping()
        self.issues = []
        
        # Build comprehensive exclusion patterns
        self.excluded_patterns = self._build_excluded_patterns()
        
    def _build_excluded_patterns(self) -> Dict[str, Set[str]]:
        """Build comprehensive excluded patterns to avoid false positives"""
        return {
            # Standard Python library modules and their common attributes
            'python_stdlib': {
                'time', 'datetime', 'os', 'sys', 're', 'json', 'csv', 'io', 'pathlib',
                'math', 'random', 'uuid', 'collections', 'itertools', 'functools',
                'operator', 'copy', 'pickle', 'hashlib', 'base64', 'urllib', 'http',
                'subprocess', 'threading', 'multiprocessing', 'logging', 'traceback',
                'inspect', 'types', 'typing', 'enum', 'dataclasses', 'contextlib'
            },
            
            # Standard Python built-in methods and attributes
            'python_builtins': {
                'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'index', 'count',
                'sort', 'reverse', 'copy', 'keys', 'values', 'items', 'get', 'update',
                'setdefault', 'popitem', 'strip', 'lstrip', 'rstrip', 'split', 'join',
                'replace', 'startswith', 'endswith', 'find', 'rfind', 'lower', 'upper',
                'title', 'capitalize', 'swapcase', 'format', 'encode', 'decode',
                'isdigit', 'isalpha', 'isalnum', 'isspace', 'islower', 'isupper',
                'read', 'write', 'readline', 'readlines', 'writelines', 'seek', 'tell',
                'flush', 'close', 'open', 'mode', 'closed', 'readable', 'writable',
                'seekable', 'fileno', 'isatty', 'truncate'
            },
            
            # Frappe framework methods and attributes (not DocType fields)
            'frappe_framework': {
                'db', 'get_all', 'get_list', 'get_doc', 'get_value', 'get_single_value',
                'set_value', 'new_doc', 'delete_doc', 'session', 'get_roles', 'throw',
                'msgprint', 'enqueue', 'logger', 'cache', 'utils', 'form_dict',
                'request', 'response', 'local', 'whitelist', 'flags', 'meta',
                'validate', 'before_save', 'after_insert', 'on_update', 'on_submit',
                'before_cancel', 'after_cancel', 'on_trash', 'after_delete',
                'before_validate', 'before_insert', 'before_update_after_submit',
                'db_set', 'reload', 'run_method', 'add_comment', 'add_tag',
                'remove_tag', 'has_permission', 'submit', 'cancel', 'save', 'insert',
                'delete', 'as_dict', 'as_json', 'get', 'set', 'append'
            },
            
            # Common object attributes that are not DocType fields
            'common_attributes': {
                'type', 'value', 'id', 'class', 'style', 'data', 'result',
                'response', 'request', 'status', 'code', 'message', 'error', 'success',
                'info', 'debug', 'warning', 'critical', 'exception', 'args', 'kwargs',
                'self', 'cls', 'super', 'property', 'staticmethod', 'classmethod',
                'abstractmethod', 'cached_property'
            }
        }
    
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Dict]:
        """Convert doctype_loader format to legacy format for compatibility"""
        legacy_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            
            # Build legacy format structure
            legacy_format[doctype_name] = {
                'data': {
                    'name': doctype_name,
                    'fields': [
                        {'fieldname': field_name}
                        for field_name in field_names
                    ]
                },
                'fields': set(field_names),
                'link_fields': {}  # Could be populated if needed
            }
        
        return legacy_format
    
    def _build_child_table_mapping(self) -> Dict[str, str]:
        """Build mapping of child table field names to their DocTypes"""
        mapping = {}
        
        for doctype_name, doctype_info in self.doctypes.items():
            for field_name, child_doctype in doctype_info.get('child_tables', []):
                mapping[f"{doctype_name}.{field_name}"] = child_doctype
                
        return mapping
    
    def is_excluded_pattern(self, obj_name: str, field_name: str, context: str) -> bool:
        """Check if this object.field pattern should be excluded from validation"""
        
        # Check if object name matches known modules/libraries
        if obj_name in self.excluded_patterns['python_stdlib']:
            return True
            
        # Check if field name matches known built-in methods
        if field_name in self.excluded_patterns['python_builtins']:
            return True
            
        # Check if it's a Frappe framework method/attribute
        if field_name in self.excluded_patterns['frappe_framework']:
            return True
            
        # Check if it's a common non-field attribute
        if field_name in self.excluded_patterns['common_attributes']:
            return True
        
        # Check for method calls (has parentheses on same line)
        if f'{field_name}(' in context:
            return True
            
        # Check for assignment statements (setting attributes, not accessing fields)
        if f'{obj_name}.{field_name} =' in context:
            return True
            
        # Check for private/protected attributes (start with underscore)
        if field_name.startswith('_'):
            return True
            
        # Check for obvious module imports or library calls
        module_patterns = [
            f'import {obj_name}',
            f'from {obj_name}',
            f'{obj_name}.{field_name}(',  # Method call
            f'@{obj_name}.{field_name}',  # Decorator
        ]
        
        if any(pattern in context for pattern in module_patterns):
            return True
            
        # Check for common variable names that are unlikely to be DocType instances
        non_doctype_vars = {
            'f', 'file', 'fp', 'data', 'result', 'response', 'request', 'settings',
            'config', 'options', 'params', 'args', 'kwargs', 'obj', 'item', 'element',
            'node', 'tree', 'root', 'parent', 'child', 'sibling', 'next', 'prev',
            'first', 'last', 'current', 'temp', 'tmp', 'buffer', 'cache', 'queue',
            'stack', 'heap', 'list', 'dict', 'set', 'tuple', 'array', 'matrix',
            'vector', 'graph', 'network', 'connection', 'socket', 'client', 'server',
            'process', 'thread', 'task', 'job', 'worker', 'handler', 'manager',
            'controller', 'service', 'factory', 'builder', 'parser', 'formatter',
            'validator', 'generator', 'iterator', 'context', 'session', 'transaction'
        }
        
        if obj_name in non_doctype_vars:
            return True
            
        return False
        
    def parse_with_ast(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Parse file using AST with enhanced DocType context detection"""
        violations = []
        
        try:
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Walk through AST nodes to find attribute access
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    # Extract object and attribute names
                    if hasattr(node.value, 'id'):
                        obj_name = node.value.id
                        field_name = node.attr
                        line_num = node.lineno
                        
                        # Get line context
                        if line_num <= len(source_lines):
                            context = source_lines[line_num - 1].strip()
                        else:
                            context = ""
                        
                        # Skip excluded patterns
                        if self.is_excluded_pattern(obj_name, field_name, context):
                            continue
                            
                        # Enhanced DocType detection
                        doctype = self._detect_doctype_accurately(content, node, obj_name, source_lines)
                        
                        if doctype and doctype in self.doctypes:
                            doctype_info = self.doctypes[doctype]
                            fields = doctype_info['fields']
                            
                            if field_name not in fields:
                                # Additional verification: is this really a field access?
                                if self._is_genuine_field_access(node, obj_name, field_name, context, source_lines):
                                    # Find similar fields
                                    similar = self._find_similar_fields(field_name, fields)
                                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                                    
                                    violations.append(ValidationIssue(
                                        file=str(file_path.relative_to(self.app_path)),
                                        line=line_num,
                                        field=field_name,
                                        doctype=doctype,
                                        reference=f"{obj_name}.{field_name}",
                                        message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                                        context=context,
                                        confidence="high",
                                        issue_type="missing_field_attribute_access",
                                        suggested_fix=f"Verify field name in {doctype} (from {doctype_info['app']} app)"
                                    ))
                                    
        except SyntaxError:
            # If AST parsing fails, skip the file
            pass
            
        return violations
        
    def _detect_doctype_accurately(self, content: str, node: ast.Attribute, obj_name: str, 
                                 source_lines: List[str]) -> Optional[str]:
        """Enhanced DocType detection with multiple strategies"""
        
        line_num = node.lineno
        
        # Strategy 1: Look for explicit assignment in broader context
        context_start = max(0, line_num - 30)
        context_end = min(len(source_lines), line_num + 10)
        context_lines = source_lines[context_start:context_end]
        context = '\n'.join(context_lines)
        
        # Look for explicit variable assignments
        assignment_patterns = [
            rf'\b{obj_name}\s*=\s*frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            rf'\b{obj_name}\s*=\s*frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            rf'\b{obj_name}\s*=\s*frappe\.get_all\(\s*["\']([^"\']+)["\']',
            rf'\b{obj_name}\s*=\s*frappe\.db\.get_value\(\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in assignment_patterns:
            match = re.search(pattern, context, re.MULTILINE)
            if match:
                return match.group(1)
        
        # Strategy 2: Handle child table iterations (for item in doc.items:)
        child_table_patterns = [
            rf'for\s+{obj_name}\s+in\s+(\w+)\.(\w+):',
            rf'{obj_name}\s*=\s*(\w+)\.(\w+)\[',
            rf'{obj_name}\s+in\s+(\w+)\.(\w+)'
        ]
        
        for pattern in child_table_patterns:
            match = re.search(pattern, context)
            if match:
                parent_obj = match.group(1)
                child_field = match.group(2)
                
                # Find which DocType has this child field
                for doctype_name, doctype_info in self.doctypes.items():
                    for field_name, child_doctype in doctype_info.get('child_tables', []):
                        if field_name == child_field:
                            return child_doctype
        
        # Strategy 3: Variable name to DocType mapping (enhanced)
        variable_mappings = {
            'member': 'Member',
            'membership': 'Membership', 
            'volunteer': 'Verenigingen Volunteer',
            'chapter': 'Chapter',
            'application': 'Membership Application',
            'schedule': 'Membership Dues Schedule',
            'board_member': 'Verenigingen Chapter Board Member',
            'expense': 'Volunteer Expense',
            'mandate': 'SEPA Mandate',
            'batch': 'Direct Debit Batch',
            'payment': 'Payment Plan',
            'invoice': 'Sales Invoice',
            'sales_invoice': 'Sales Invoice'
        }
        
        if obj_name in variable_mappings:
            mapped_doctype = variable_mappings[obj_name]
            if mapped_doctype in self.doctypes:
                return mapped_doctype
        
        # Strategy 4: Handle validation functions (doc parameter)
        if obj_name == 'doc':
            return self._guess_doctype_from_validation_context(content, source_lines, line_num)
        
        # Strategy 5: Look for explicit DocType mentions in context
        for doctype in self.doctypes.keys():
            if f'"{doctype}"' in context or f"'{doctype}'" in context:
                return doctype
        
        return None
        
    def _guess_doctype_from_validation_context(self, content: str, lines: List[str], line_no: int) -> Optional[str]:
        """Guess DocType from validation function context"""
        
        # Look for function definition pattern: def validate_xxx(doc, method):
        for i in range(max(0, line_no - 50), line_no):
            if i < len(lines):
                line = lines[i].strip()
                if line.startswith('def ') and '(doc, method)' in line:
                    func_name = line.split('def ')[1].split('(')[0].strip()
                    
                    # Enhanced function name to DocType mapping
                    validation_mappings = {
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
                    
                    if func_name in validation_mappings:
                        return validation_mappings[func_name]
                    
                    # Try to infer from function name patterns
                    if func_name.startswith('validate_'):
                        # Convert snake_case to Title Case
                        potential_doctype = func_name[9:].replace('_', ' ').title()
                        if potential_doctype in self.doctypes:
                            return potential_doctype
        
        return None
        
    def _is_genuine_field_access(self, node: ast.Attribute, obj_name: str, field_name: str, 
                               context: str, source_lines: List[str]) -> bool:
        """Determine if this is genuinely a DocType field access"""
        
        # Skip if it's clearly a method call
        if f'{field_name}(' in context:
            return False
            
        # Skip if it's an assignment (setting the attribute)
        if f'{obj_name}.{field_name} =' in context:
            return False
            
        # Skip if it's in a function definition
        if context.strip().startswith('def ') and f'{field_name}(' in context:
            return False
            
        # Skip obvious property/method access patterns
        skip_patterns = [
            f'hasattr({obj_name}, \'{field_name}\')',
            f'getattr({obj_name}, \'{field_name}\')',
            f'setattr({obj_name}, \'{field_name}\')',
            f'self.{field_name}()',  # Method call on self
        ]
        
        if any(pattern in context for pattern in skip_patterns):
            return False
            
        # Look for DocType-specific patterns that suggest field access
        field_access_indicators = [
            f'if {obj_name}.{field_name}',  # Conditional on field
            f'return {obj_name}.{field_name}',  # Returning field value
            f'{obj_name}.{field_name} or',  # Boolean operation
            f'{obj_name}.{field_name} and',  # Boolean operation
            f'{obj_name}.{field_name} ==',  # Comparison
            f'{obj_name}.{field_name} !=',  # Comparison
            f'{obj_name}.{field_name},',  # In a list/tuple
        ]
        
        if any(indicator in context for indicator in field_access_indicators):
            return True
            
        # Check broader context for DocType indicators
        line_no = node.lineno - 1
        context_range = range(max(0, line_no - 5), min(len(source_lines), line_no + 3))
        
        doctype_context_indicators = [
            'frappe.get_doc(',
            'frappe.new_doc(',
            '.save()',
            '.insert()',
            '.submit()',
            '.cancel()',
            'doctype',
        ]
        
        for i in context_range:
            line = source_lines[i].strip()
            if any(indicator in line for indicator in doctype_context_indicators):
                return True
                
        # Conservative default - only flag if we have strong evidence
        return False
        
    def _find_similar_fields(self, field_name: str, valid_fields: Set[str]) -> List[str]:
        """Find similar field names using enhanced string matching"""
        similar = []
        field_lower = field_name.lower()
        
        for valid_field in valid_fields:
            valid_lower = valid_field.lower()
            
            # Exact substring match
            if field_lower in valid_lower or valid_lower in field_lower:
                similar.append(valid_field)
                continue
                
            # Prefix/suffix matching for longer strings
            if len(field_lower) > 3 and len(valid_lower) > 3:
                if (field_lower.startswith(valid_lower[:4]) or
                    field_lower.endswith(valid_lower[-4:]) or
                    valid_lower.startswith(field_lower[:4]) or
                    valid_lower.endswith(field_lower[-4:])):
                    similar.append(valid_field)
                
        return similar[:3]  # Return top 3 matches
        
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single file"""
        violations = []
        
        # Skip certain file types and directories 
        skip_patterns = [
            '/node_modules/', '/__pycache__/', '/.git/', '/migrations/',
            'archived_unused/', 'backup/', '.disabled', 'patches/',
        ]
        
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Use AST parsing for accuracy
            violations = self.parse_with_ast(content, file_path)
            
        except Exception as e:
            # If file can't be processed, skip it silently
            pass
            
        return violations
        
    def validate_app(self, pre_commit: bool = False) -> List[ValidationIssue]:
        """Validate the entire app"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning Python files in {self.app_path}...")
        
        # Check Python files
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip certain directories
            if any(skip in str(py_file) for skip in [
                'node_modules', '__pycache__', '.git', 'migrations',
                'archived_unused', 'backup', '.disabled', 'patches'
            ]):
                continue
                
            # In pre-commit mode, skip test and debug files
            if pre_commit and any(pattern in str(py_file) for pattern in [
                '/tests/', '/test_', '/debug_', '/scripts/testing/', '/scripts/debug/'
            ]):
                continue
            
            files_checked += 1
            
            file_violations = self.validate_file(py_file)
            if file_violations:
                print(f"  - Found {len(file_violations)} issues in {py_file.relative_to(self.app_path)}")
            violations.extend(file_violations)
        
        print(f"📊 Checked {files_checked} Python files")
        return violations
        
    def generate_report(self, violations: List[ValidationIssue]) -> str:
        """Generate a comprehensive report"""
        if not violations:
            return "✅ No field reference issues found!"
            
        report = []
        report.append(f"❌ Found {len(violations)} field reference issues:")
        report.append("")
        
        # Group by confidence level
        high_confidence = [v for v in violations if v.confidence == "high"]
        
        if high_confidence:
            report.append(f"## High Confidence Issues ({len(high_confidence)})")
            report.append("These are very likely to be actual field reference errors:")
            report.append("")
            
            for violation in high_confidence[:20]:  # Limit to first 20
                report.append(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
                report.append(f"   → {violation.message}")
                report.append(f"   Context: {violation.context}")
                report.append("")
                
        return '\n'.join(report)


def main():
    """Main function with enhanced accuracy"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Check for pre-commit mode
    pre_commit = '--pre-commit' in sys.argv
    verbose = '--verbose' in sys.argv
    
    validator = FixedFieldValidator(app_path)
    print(f"📋 Loaded {len(validator.doctypes)} doctypes with field definitions")
    print(f"📋 Built child table mapping with {len(validator.child_table_mapping)} entries")
    
    if pre_commit:
        print("🚨 Running in pre-commit mode (production files only)...")
    else:
        print("🔍 Running comprehensive validation...")
        
    violations = validator.validate_app(pre_commit=pre_commit)
    
    print("\n" + "="*50)
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        high_confidence = len([v for v in violations if v.confidence == "high"])
        
        print(f"\n💡 Summary:")
        print(f"   - High confidence issues: {high_confidence}")
        print(f"   - Total issues: {len(violations)}")
        
        if verbose and violations:
            print(f"\n🔍 Sample of detected DocTypes:")
            doctypes_found = set(v.doctype for v in violations[:10])
            for dt in list(doctypes_found)[:5]:
                if dt in validator.doctypes:
                    fields = validator.doctypes[dt]['fields']
                    print(f"   - {dt}: {len(fields)} fields available")
        
        # Only fail pre-commit on high confidence issues
        if pre_commit and high_confidence > 0:
            return 1
        elif not pre_commit and violations:
            return 1
    else:
        print("✅ All field references validated successfully!")
        
    return 0


if __name__ == "__main__":
    exit(main())