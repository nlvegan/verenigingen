#!/usr/bin/env python3
"""
Accurate Field Validator - Ultra-precise field validation with <5% false positive rate
Addresses the core issues in DocType context detection
"""

import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

# Import comprehensive DocType loader
sys.path.insert(0, str(Path(__file__).parent.parent))
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata, get_unified_doctype_loader

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

class AccurateFieldValidator:
    """Ultra-accurate field validator with precise DocType context detection"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.verbose = verbose
        
        # Use comprehensive DocType loader (standardized)
        # Resolves the real bench (walk-up, or git for a worktree outside it); `app_path.parent.parent`
        # is the bench only for <bench>/apps/<app>.
        self.doctype_loader = get_unified_doctype_loader(str(self.app_path), verbose=verbose)
        self.doctypes = self._convert_doctypes_for_compatibility()
        
        self.custom_fields = self._load_custom_fields()
        self._apply_custom_fields_to_doctypes()
        self.child_table_mapping = self._build_child_table_mapping()
        self.issues = []
        self.unvalidated_files = 0
        
        # Build comprehensive exclusion patterns
        self.excluded_patterns = self._build_excluded_patterns()
        self._add_reduced_fp_exclusions()
        self.reduced_fp_mode = False
        
        # Load manager properties
        self.manager_properties = self._load_manager_properties()
        
    def enable_reduced_fp_mode(self):
        """Enable reduced false positive mode with additional exclusions"""
        self.reduced_fp_mode = True
    
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Dict]:
        """Convert comprehensive DocType loader format to legacy format for compatibility"""
        legacy_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        if self.verbose:
            print(f"🔍 DocType Field Validator using comprehensive loader - loaded {len(doctype_metas)} DocTypes")
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            
            # Extract child table relationships
            child_tables = []
            for field_name, field_info in doctype_meta.fields.items():
                if field_info.fieldtype == 'Table' and field_info.options:
                    child_tables.append((field_name, field_info.options))
            
            legacy_format[doctype_name] = {
                'fields': field_names,
                'data': {'name': doctype_name},  # Minimal data structure
                'app': doctype_meta.app,
                'child_tables': child_tables,
                'file': doctype_meta.json_file_path or 'unknown'
            }
            
        return legacy_format

    def _add_reduced_fp_exclusions(self):
        """Add the query-alias and test-name exclusions that --reduced-fp-mode consults.

        #2934: these were assigned after the `return` of _convert_doctypes_for_compatibility
        (dead code), and that method runs before excluded_patterns exists, so they never applied.
        """
        # Add query alias patterns to exclusions
        self.excluded_patterns['query_aliases'] = {
            'membership', 'invoice', 'member_name', 'member_id', 'amount', 
            'status', 'customer_name', 'outstanding_amount', 'currency'
        }
        
        # Add test-specific exclusions
        self.excluded_patterns['test_patterns'] = {
            'old_rate', 'new_rate', 'end_date', 'membership_name', 'cancellation_date',
            'state', 'allow_edit', 'doc_status'
        }
        
    def _build_excluded_patterns(self) -> Dict[str, Set[str]]:
        """Build comprehensive excluded patterns to avoid false positives"""
        return {
            # Standard Python library and built-in methods
            'python_builtins': {
                'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'index', 'count',
                'sort', 'reverse', 'copy', 'keys', 'values', 'items', 'get', 'update',
                'setdefault', 'popitem', 'strip', 'lstrip', 'rstrip', 'split', 'join',
                'replace', 'startswith', 'endswith', 'find', 'rfind', 'lower', 'upper',
                'title', 'capitalize', 'swapcase', 'format', 'encode', 'decode',
                'isdigit', 'isalpha', 'isalnum', 'isspace', 'islower', 'isupper',
                'read', 'write', 'readline', 'readlines', 'writelines', 'seek', 'tell',
                'flush', 'close', 'open', 'mode', 'closed', 'readable', 'writable',
                'seekable', 'fileno', 'isatty', 'truncate', 'stem', 'name', 'exists'
            },
            
            # Frappe framework methods and attributes
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
                'delete', 'as_dict', 'as_json', 'get', 'set', 'append', 'model'
            },
            
            # Common non-field attributes
            'common_attributes': {
                'type', 'value', 'id', 'class', 'style', 'data', 'result', 'fields',
                'response', 'request', 'status', 'code', 'message', 'error', 'success',
                'info', 'debug', 'warning', 'critical', 'exception', 'args', 'kwargs',
                'self', 'cls', 'super', 'property', 'staticmethod', 'classmethod',
                'abstractmethod', 'cached_property', 'enabled', 'template', 'baseline_file'
            }
        }
    
    def _load_manager_properties(self) -> Dict[str, Set[str]]:
        """Load @property methods from DocType Python files"""
        manager_properties = {}
        
        # Common manager property patterns
        common_managers = {
            'Chapter': {'member_manager', 'board_manager', 'communication_manager', 'volunteer_integration_manager'},
            'Member': {'payment_mixin', 'termination_handler'},
            'Direct Debit Batch': {'sepa_processor'},
        }
        
        # Start with common patterns
        manager_properties.update(common_managers)
        
        # Scan DocType Python files for @property decorators
        for py_file in self.app_path.rglob("**/doctype/*/*.py"):
            if py_file.name.startswith('test_') or py_file.name.startswith('__'):
                continue
                
            doctype_name = self._to_title_case(py_file.parent.name)
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Simple regex to find @property decorated methods
                property_pattern = r'@property\s+def\s+(\w+)\s*\('
                properties = re.findall(property_pattern, content)
                
                if properties:
                    if doctype_name not in manager_properties:
                        manager_properties[doctype_name] = set()
                    manager_properties[doctype_name].update(properties)
                    
            except Exception:
                pass
                
        return manager_properties
    
    def _load_custom_fields(self) -> List[Dict]:
        """Load custom fields from fixtures and other sources"""
        custom_fields = []
        
        # Load from fixtures/custom_field.json
        fixtures_path = self.app_path / "verenigingen" / "fixtures" / "custom_field.json"
        if fixtures_path.exists():
            try:
                with open(fixtures_path, 'r', encoding='utf-8') as f:
                    custom_fields.extend(json.load(f))
                if self.verbose:
                    print(f"📋 Loaded {len(custom_fields)} custom fields from fixtures")
            except Exception as e:
                if self.verbose:
                    print(f"⚠️  Error loading custom fields from fixtures: {e}")
        
        # Also check for programmatically created custom fields
        # Common patterns in ERPNext/custom apps
        known_custom_fields = [
            {"dt": "Employee", "fieldname": "expense_approver", "fieldtype": "Link", "options": "User"},
            {"dt": "Payment Entry", "fieldname": "eboekhouden_mutation_nr", "fieldtype": "Data"},
            {"dt": "Party Account", "fieldname": "party", "fieldtype": "Dynamic Link"},
            {"dt": "Party Account", "fieldname": "project", "fieldtype": "Link", "options": "Project"},
            {"dt": "User", "fieldname": "home_page", "fieldtype": "Data"},
            {"dt": "Discounted Invoice", "fieldname": "mandate_reference", "fieldtype": "Data"},
            {"dt": "Verenigingen Volunteer", "fieldname": "notes", "fieldtype": "Text"},
            {"dt": "Employee", "fieldname": "remarks", "fieldtype": "Text"},
            {"dt": "Web Template Field", "fieldname": "description", "fieldtype": "Text"},
        ]
        
        # Add known custom fields that might not be in fixtures
        for field in known_custom_fields:
            if not any(cf.get('dt') == field['dt'] and cf.get('fieldname') == field['fieldname'] 
                      for cf in custom_fields):
                custom_fields.append(field)
        
        return custom_fields
    
    def _apply_custom_fields_to_doctypes(self):
        """Apply custom fields to loaded DocTypes"""
        for custom_field in self.custom_fields:
            dt = custom_field.get('dt')
            fieldname = custom_field.get('fieldname')
            
            if dt and fieldname:
                # If DocType exists in our loaded doctypes, add the field
                if dt in self.doctypes:
                    self.doctypes[dt]['fields'].add(fieldname)
                else:
                    # Create a minimal entry for DocTypes we haven't loaded
                    self.doctypes[dt] = {
                        'fields': {fieldname},
                        'data': {'custom_only': True},
                        'app': 'custom',
                        'child_tables': [],
                        'file': 'custom_field'
                    }
                    
        if self.verbose:
            print(f"📋 Applied custom fields to {len(self.custom_fields)} DocTypes")
    
    def _to_title_case(self, snake_case: str) -> str:
        """Convert snake_case to Title Case"""
        return ' '.join(word.capitalize() for word in snake_case.split('_'))
    
    
    def _build_child_table_mapping(self) -> Dict[str, str]:
        """Build precise mapping of parent.field -> child DocType"""
        mapping = {}
        
        for doctype_name, doctype_info in self.doctypes.items():
            for field_name, child_doctype in doctype_info.get('child_tables', []):
                mapping[f"{doctype_name}.{field_name}"] = child_doctype
                if self.verbose:
                    print(f"Child table mapping: {doctype_name}.{field_name} -> {child_doctype}")
                
        return mapping
    
    def is_excluded_pattern(self, obj_name: str, field_name: str, context: str) -> bool:
        """Enhanced exclusion checking with ultra-precise filtering"""
        
        # Check if field name matches known built-in methods
        if field_name in self.excluded_patterns['python_builtins']:
            return True
            
        # Check if it's a Frappe framework method/attribute
        if field_name in self.excluded_patterns['frappe_framework']:
            return True
            
        # Check if it's a common non-field attribute
        if field_name in self.excluded_patterns['common_attributes']:
            return True
            
        # Enhanced exclusions for reduced false positive mode
        if self.reduced_fp_mode:
            if field_name in self.excluded_patterns.get('query_aliases', set()):
                return True
            if field_name in self.excluded_patterns.get('test_patterns', set()):
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
            
        # Check for obvious non-DocType variable names
        non_doctype_vars = {
            'f', 'file', 'fp', 'data', 'result', 'response', 'request', 'settings',
            'config', 'options', 'params', 'args', 'kwargs', 'obj', 'item', 'element',
            'node', 'tree', 'root', 'parent', 'child', 'sibling', 'next', 'prev',
            'first', 'last', 'current', 'temp', 'tmp', 'buffer', 'cache', 'queue',
            'stack', 'heap', 'list', 'dict', 'set', 'tuple', 'array', 'matrix',
            'vector', 'graph', 'network', 'connection', 'socket', 'client', 'server',
            'process', 'thread', 'task', 'job', 'worker', 'handler', 'manager',
            'controller', 'service', 'factory', 'builder', 'parser', 'formatter',
            'validator', 'generator', 'iterator', 'context', 'session', 'transaction',
            'json_file', 'meta', 'self', 'template', 'row', 'record', 'entry', 
            'invoice_item', 'payment', 'account', 'step', 'field', 'user_doc',
            'employee', 'volunteer_doc', 'employee_doc'
        }
        
        if obj_name in non_doctype_vars:
            return True
            
        return False
        
    def parse_with_ast(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Parse file using AST with ultra-precise DocType context detection"""
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
                            
                        # Ultra-precise DocType detection
                        doctype = self._detect_doctype_precisely(content, node, obj_name, source_lines)
                        
                        if self.verbose:
                            print(f"Analyzing {obj_name}.{field_name} -> detected as {doctype}")
                        
                        if doctype and doctype in self.doctypes:
                            doctype_info = self.doctypes[doctype]
                            fields = doctype_info['fields']
                            
                            if field_name not in fields:
                                # Check if this is a manager property access
                                if doctype in self.manager_properties and field_name in self.manager_properties[doctype]:
                                    # Skip - this is a valid @property method access
                                    continue
                                
                                # Skip custom fields - they're added dynamically
                                if field_name.startswith('custom_'):
                                    continue
                                
                                # Skip common field name patterns that are often aliases or computed
                                if field_name.endswith(('_name', '_id', '_count', '_total', '_status')):
                                    continue
                                
                                # Final verification: is this genuinely a field access?
                                if self._is_genuine_field_access(node, obj_name, field_name, context, source_lines):
                                    # Find similar fields
                                    similar = self._find_similar_fields(field_name, fields)
                                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                                    
                                    # Calculate confidence level
                                    confidence = self._calculate_confidence(
                                        node, obj_name, field_name, doctype, context, source_lines
                                    )
                                    
                                    violations.append(ValidationIssue(
                                        file=self._display_path(file_path),
                                        line=line_num,
                                        field=field_name,
                                        doctype=doctype,
                                        reference=f"{obj_name}.{field_name}",
                                        message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                                        context=context,
                                        confidence=confidence,
                                        issue_type="missing_field_attribute_access",
                                        suggested_fix=f"Verify field name in {doctype} (from {doctype_info['app']} app)"
                                    ))
                                    
        except SyntaxError:
            # If AST parsing fails, skip the file
            pass
            
        return violations
        
    def _detect_doctype_precisely(self, content: str, node: ast.Attribute, obj_name: str, 
                                 source_lines: List[str]) -> Optional[str]:
        """Ultra-precise DocType detection with multiple strategies"""
        
        line_num = node.lineno
        
        # Strategy 1: Child table iteration detection (most accurate)
        context_start = max(0, line_num - 10)
        context_end = min(len(source_lines), line_num + 5)
        context_lines = source_lines[context_start:context_end]
        context = '\n'.join(context_lines)
        
        # Look for "for obj_name in parent.child_field:" pattern
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
                
                if self.verbose:
                    print(f"Found child table pattern: {parent_obj}.{child_field}")
                
                # First try to identify the parent DocType
                parent_doctype = None
                
                # Look for parent object's doctype assignment
                parent_patterns = [
                    rf'{parent_obj}\s*=\s*frappe\.get_doc\(["\']([^"\']+)["\']',
                    rf'{parent_obj}\s*=\s*frappe\.new_doc\(["\']([^"\']+)["\']',
                ]
                
                parent_context = '\n'.join(source_lines[max(0, line_num - 50):line_num])
                for pattern in parent_patterns:
                    parent_match = re.search(pattern, parent_context)
                    if parent_match:
                        parent_doctype = parent_match.group(1)
                        break
                
                # If we found the parent DocType, use its specific mapping
                if parent_doctype and parent_doctype in self.doctypes:
                    doctype_info = self.doctypes[parent_doctype]
                    for field_name, child_doctype in doctype_info.get('child_tables', []):
                        if field_name == child_field:
                            if self.verbose:
                                print(f"  -> Mapped to child DocType: {child_doctype} (parent: {parent_doctype})")
                            return child_doctype
                
                # Fallback: look through all doctypes (less accurate)
                for doctype_name, doctype_info in self.doctypes.items():
                    for field_name, child_doctype in doctype_info.get('child_tables', []):
                        if field_name == child_field:
                            if self.verbose:
                                print(f"  -> Mapped to child DocType: {child_doctype} (guessed from {doctype_name})")
                            return child_doctype
        
        # Strategy 2: Explicit variable assignments
        broader_context = '\n'.join(source_lines[max(0, line_num - 30):line_num + 10])
        
        assignment_patterns = [
            rf'\b{obj_name}\s*=\s*frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            rf'\b{obj_name}\s*=\s*frappe\.new_doc\(\s*["\']([^"\']*)["\']',
        ]
        
        for pattern in assignment_patterns:
            match = re.search(pattern, broader_context, re.MULTILINE)
            if match:
                if self.verbose:
                    print(f"Found assignment pattern: {match.group(1)}")
                return match.group(1)
        
        # Strategy 3: Conservative variable name to DocType mapping
        # Only map when we have very high confidence
        # Removed ambiguous mappings that cause false positives
        precise_mappings = {
            # These are less ambiguous
            'membership_application': 'Membership Application',
            'volunteer_expense': 'Volunteer Expense',
            'sepa_mandate': 'SEPA Mandate',
            'direct_debit_batch': 'Direct Debit Batch',
            'payment_plan': 'Payment Plan',
            'sales_invoice': 'Sales Invoice',
            'membership_dues_schedule': 'Membership Dues Schedule',
            # Keep some common ones but be careful
            'member_doc': 'Member',
            'volunteer_doc': 'Verenigingen Volunteer',
            'chapter_doc': 'Chapter',
        }
        
        if obj_name in precise_mappings:
            mapped_doctype = precise_mappings[obj_name]
            if mapped_doctype in self.doctypes:
                if self.verbose:
                    print(f"Mapped variable {obj_name} -> {mapped_doctype}")
                return mapped_doctype
        
        # Strategy 4: Validation function context for 'doc' parameter
        if obj_name == 'doc':
            return self._guess_doctype_from_validation_context(content, source_lines, line_num)
        
        return None
        
    def _guess_doctype_from_validation_context(self, content: str, lines: List[str], line_no: int) -> Optional[str]:
        """Guess DocType from validation function context"""
        
        # Look for function definition pattern: def validate_xxx(doc, method):
        # Search backwards to find the closest preceding validation function
        for i in range(line_no - 1, max(0, line_no - 50), -1):
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
        """Ultra-precise determination of genuine DocType field access"""
        
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
            
        # Look for strong field access indicators
        field_access_indicators = [
            f'if {obj_name}.{field_name}',  # Conditional on field
            f'return {obj_name}.{field_name}',  # Returning field value
            f'{obj_name}.{field_name} or',  # Boolean operation
            f'{obj_name}.{field_name} and',  # Boolean operation
            f'{obj_name}.{field_name} ==',  # Comparison
            f'{obj_name}.{field_name} !=',  # Comparison
            f'{obj_name}.{field_name},',  # In a list/tuple
            f'[{obj_name}.{field_name}',  # In array access
            f'"{obj_name}.{field_name}"',  # In string context (frappe.db calls)
        ]
        
        if any(indicator in context for indicator in field_access_indicators):
            return True
            
        # Check broader context for DocType indicators (conservative)
        line_no = node.lineno - 1
        context_range = range(max(0, line_no - 3), min(len(source_lines), line_no + 2))
        
        doctype_context_indicators = [
            'frappe.get_doc(',
            'frappe.new_doc(',
            '.save()',
            '.insert()',
            '.submit()',
            '.cancel()',
            'for board_member in',  # Strong indicator for child table iteration
            'for schedule in',
            'for member in',
        ]
        
        for i in context_range:
            line = source_lines[i].strip()
            if any(indicator in line for indicator in doctype_context_indicators):
                return True
                
        # Ultra-conservative default - only flag with very strong evidence
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
        
    def _calculate_confidence(self, node: ast.Attribute, obj_name: str, field_name: str, 
                            doctype: str, context: str, source_lines: List[str]) -> str:
        """Calculate confidence level for the validation issue"""
        
        # Start with high confidence
        confidence_score = 100
        
        # Check if it's a custom field pattern
        if field_name.startswith('custom_'):
            confidence_score -= 40  # Custom fields are often added dynamically
            
        # Check if it's in a test file
        file_path = getattr(node, '__file__', '')
        if any(pattern in str(file_path) for pattern in ['test_', '_test.py', '/tests/', 'debug_']):
            confidence_score -= 30
            
        # Check for SQL context patterns
        sql_patterns = [
            'frappe.db.sql',
            'as_dict=True',
            'SELECT.*FROM',
            '\\.format\\(',  # escaped: a bare '.format(' is an invalid regex (#2960)
            'GROUP BY',
            'ORDER BY',
            'frappe.db.get_value',
            'frappe.db.get_list',
            'frappe.db.get_all',
            'JOIN',
            'LEFT JOIN',
            'INNER JOIN',
            'AS\\s+\\w+',  # SQL aliases
            'COUNT\\(',
            'SUM\\(',
            'MAX\\(',
            'MIN\\(',
            'AVG\\(',
        ]
        context_window = '\n'.join(source_lines[max(0, node.lineno-10):node.lineno+5])
        if any(re.search(pattern, context_window, re.IGNORECASE) for pattern in sql_patterns):
            confidence_score -= 50  # SQL results often have different fields
            
        # Check for API/external data patterns
        api_patterns = [
            'requests.get',
            'requests.post',
            'json.loads',
            'api_response',
            'external_data',
            'third_party'
        ]
        if any(pattern in context_window for pattern in api_patterns):
            confidence_score -= 40
            
        # Check if similar fields exist (likely typo)
        doctype_info = self.doctypes.get(doctype, {})
        fields = doctype_info.get('fields', set())
        similar_fields = self._find_similar_fields(field_name, fields)
        if similar_fields:
            confidence_score += 20  # Likely a typo if similar fields exist
            
        # Convert score to category
        if confidence_score >= 80:
            return "high"
        elif confidence_score >= 50:
            return "medium"
        else:
            return "low"
        
    def _display_path(self, file_path: Path) -> str:
        """Path relative to the app root, whether given absolute or (as pre-commit does) relative.

        `Path.relative_to` raised ValueError on a repo-relative path, which was swallowed (#2960).
        """
        resolved = Path(file_path).resolve()
        try:  # outside the app root (unreachable via pre-commit): fall back to the path as passed
            return str(resolved.relative_to(self.app_path.resolve()))
        except ValueError:
            return str(file_path)

    def is_test_or_debug_file(self, path: Path) -> bool:
        """Pre-commit mode validates production files only. Shared by the app scan and the
        per-file path: the hook's own `exclude` regex only matches top-level tests/, so without
        this the hook (file mode) saw test files the scan (and the baseline) never did (#2960)."""
        rel = self._rooted_rel_path(path)
        return any(pattern in rel for pattern in PRE_COMMIT_SKIP_PATTERNS)

    def _rooted_rel_path(self, file_path: Path) -> str:
        """'/'-prefixed app-relative path, the string every skip pattern is matched against.

        Matching the ABSOLUTE path made a checkout under any ancestor named tests/, test_*,
        backup/ or patches/ skip every file silently (#2960 review F1).
        """
        return "/" + self._display_path(file_path).replace("\\", "/").lstrip("/")

    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single file"""
        violations = []
        
        # Skip certain file types and directories 
        skip_patterns = [
            '/node_modules/', '/__pycache__/', '/.git/', '/migrations/',
            'archived_unused/', 'backup/', '.disabled', 'patches/',
        ]
        
        if any(pattern in self._rooted_rel_path(file_path) for pattern in skip_patterns):
            return violations
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Use AST parsing for accuracy
            violations = self.parse_with_ast(content, file_path)
            
        except SyntaxError:
            # Not parseable Python: other hooks report that, there is nothing to validate here.
            pass
        except Exception as e:
            # Never silent (#2960): a blanket `pass` here hid three faults that made the whole
            # hook report nothing. stderr, so it shows in a hook run and in CI logs.
            self.unvalidated_files += 1
            print(f"doctype_field_validator: could not validate {file_path}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            
        return violations
        
    def validate_app(self, pre_commit: bool = False) -> List[ValidationIssue]:
        """Validate the entire app"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning Python files in {self.app_path}...")
        
        # Check Python files
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip certain directories
            if any(skip in self._rooted_rel_path(py_file) for skip in [
                'node_modules', '__pycache__', '.git', 'migrations',
                'archived_unused', 'backup', '.disabled', 'patches'
            ]):
                continue
                
            # In pre-commit mode, skip test and debug files
            if pre_commit and self.is_test_or_debug_file(py_file):
                continue
            
            files_checked += 1
            
            file_violations = self.validate_file(py_file)
            if file_violations:
                print(f"  - Found {len(file_violations)} issues in {self._display_path(py_file)}")
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
        
        # Show first 10 issues for inspection
        for violation in violations[:10]:
            report.append(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
            report.append(f"   → {violation.message}")
            report.append(f"   Context: {violation.context}")
            report.append("")
                
        return '\n'.join(report)


# Present whenever erpnext is loaded; the baseline holds findings on erpnext doctypes.
ERPNEXT_SENTINEL_DOCTYPE = "Sales Invoice"
PRE_COMMIT_SKIP_PATTERNS = ['/tests/', '/test_', '/debug_', '/scripts/testing/', '/scripts/debug/']


BASELINE_PATH = Path(__file__).resolve().parent.parent / "doctype_field_validator_baseline.txt"
BASELINE_HEADER = """# Known field-reference findings (#2960) -- the ratchet baseline for
# scripts/validation/archived/doctype_field_validator.py (the `doctype-field-validator` hook).
# Format:
#     <path>::<doctype>::<field>::<count>
#
# The hook was blind (see #2960) until its regex, path handling and app path were fixed; these
# are the high-confidence findings it then reported. They are NOT triaged: several look like the
# variable-name guess (#2925), so they are recorded, not asserted to be defects.
#
# A run fails only if it introduces a NEW key here, or raises an existing key's count. This
# file should only ever SHRINK: fix a site (or teach the validator it is a false positive)
# and regenerate with `--update-baseline`. Do not raise a count to silence a new finding.
# Only high-confidence findings are recorded (only those fail a commit). They include findings
# on other apps' doctypes (frappe/erpnext/hrms/website) that a bench loads: this hook runs
# locally on a bench only (it is not a CI job), unlike the #2323 baseline, so there is no
# bench-vs-CI difference to scope away. A bench WITHOUT erpnext would see every erpnext-doctype
# reference as new, so the hook then warns and skips (exit 0) instead of blocking.
"""


def baseline_key(issue: ValidationIssue) -> str:
    # No line number: a key must survive an unrelated edit above the site.
    return f"{issue.file}::{issue.doctype}::{issue.field}"


def load_baseline(path: Path = BASELINE_PATH) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, count = line.rpartition("::")
        counts[key] = int(count)
    return counts


def write_baseline(issues: List[ValidationIssue], path: Path = BASELINE_PATH) -> int:
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[baseline_key(issue)] = counts.get(baseline_key(issue), 0) + 1
    body = "".join(f"{key}::{counts[key]}\n" for key in sorted(counts))
    path.write_text(BASELINE_HEADER + body, encoding="utf-8")
    return sum(counts.values())


def new_findings(issues: List[ValidationIssue], baseline: Dict[str, int]) -> List[ValidationIssue]:
    """Findings beyond what the baseline allows for their key (a new key, or a higher count)."""
    seen: Dict[str, int] = {}
    new = []
    for issue in issues:
        key = baseline_key(issue)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > baseline.get(key, 0):
            new.append(issue)
    return new


def main():
    """Main function with ultra-precise validation"""
    import sys

    # The app root from this file's location (scripts/validation/archived/ -> repo root), not a
    # hardcoded absolute path that exists on no other machine (#2960).
    app_path = str(Path(__file__).resolve().parents[3])

    # Check for options
    update_baseline = '--update-baseline' in sys.argv
    pre_commit = '--pre-commit' in sys.argv or update_baseline
    use_baseline = '--no-baseline' not in sys.argv
    verbose = '--verbose' in sys.argv
    # The baseline is recorded in the hook's mode, so regenerating it must use that mode too.
    reduced_fp_mode = '--reduced-fp-mode' in sys.argv or update_baseline
    single_file = None
    
    # Extract file paths (non-option arguments)
    file_paths = []
    for arg in sys.argv[1:]:
        if not arg.startswith('--') and arg.endswith('.py'):
            file_paths.append(Path(arg))
    if update_baseline:
        file_paths = []
    
    validator = AccurateFieldValidator(app_path, verbose=verbose)
    
    # Apply reduced false positive mode if requested
    if reduced_fp_mode:
        validator.enable_reduced_fp_mode()
    
    if not verbose:
        print(f"📋 Loaded {len(validator.doctypes)} doctypes with field definitions")
        print(f"📋 Built child table mapping with {len(validator.child_table_mapping)} entries")
    
    if file_paths:
        print(f"🔍 Validating {len(file_paths)} files from pre-commit...")
        violations = []
        for file_path in file_paths:
            if file_path.exists() and not (pre_commit and validator.is_test_or_debug_file(file_path)):
                violations.extend(validator.validate_file(file_path))
    elif pre_commit:
        print("🚨 Running in pre-commit mode (production files only)...")
        violations = validator.validate_app(pre_commit=pre_commit)
    else:
        print("🔍 Running comprehensive validation...")
        violations = validator.validate_app(pre_commit=pre_commit)
        
    if (pre_commit or update_baseline) and ERPNEXT_SENTINEL_DOCTYPE not in validator.doctype_loader.get_doctypes():
        # Ask the LOADER, not validator.doctypes: custom_field.json fixtures synthesize an entry
        # for Sales Invoice even where erpnext is absent. A bench without erpnext loads none of its doctypes, so every reference to one would
        # read as a NEW finding and block every commit (#2960 review F2). Do not guess.
        print(f"⚠️  {ERPNEXT_SENTINEL_DOCTYPE} not loaded: erpnext is not on this bench, so field "
              "references to its doctypes cannot be checked. Skipping the check (and the baseline).")
        return 1 if update_baseline else 0

    if update_baseline:
        # Only what the hook can fail on: high confidence.
        recorded = [v for v in violations if v.confidence == "high"]
        print(f"Wrote {BASELINE_PATH.name}: {write_baseline(recorded)} findings")
        return 0

    if pre_commit and use_baseline:
        # Only high-confidence findings fail a commit, so only those are ratcheted; the
        # medium/low ones stay visible and non-blocking.
        high = [v for v in violations if v.confidence == "high"]
        fresh = {id(v) for v in new_findings(high, load_baseline())}
        suppressed = len(high) - len(fresh)
        violations = [v for v in violations if v.confidence != "high" or id(v) in fresh]
        print(f"Ratchet: {suppressed} baselined high-confidence finding(s) suppressed "
              f"({BASELINE_PATH.name}).")

    if validator.unvalidated_files:
        # stderr is hidden on a passing pre-commit run, so say it on stdout too.
        print(f"⚠️  {validator.unvalidated_files} file(s) could not be validated (see stderr)")

    print("\n" + "="*50)
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        # Group by confidence level
        high_conf = [v for v in violations if v.confidence == "high"]
        medium_conf = [v for v in violations if v.confidence == "medium"]
        low_conf = [v for v in violations if v.confidence == "low"]
        
        print(f"\n💡 Summary:")
        print(f"   - Total issues found: {len(violations)}")
        print(f"   - High confidence: {len(high_conf)}")
        print(f"   - Medium confidence: {len(medium_conf)}")
        print(f"   - Low confidence: {len(low_conf)}")
        
        # In pre-commit mode, only fail on high confidence issues
        if pre_commit:
            if high_conf:
                print(f"\n❌ Pre-commit check failed: {len(high_conf)} high confidence issues found")
                return len(high_conf)
            else:
                print("\n✅ Pre-commit check passed (no high confidence issues)")
                if medium_conf or low_conf:
                    print(f"⚠️  Found {len(medium_conf)} medium and {len(low_conf)} low confidence issues (not blocking commit)")
                return 0
        else:
            return 1 if violations else 0
    else:
        print("✅ All field references validated successfully!")
        
    return 0


if __name__ == "__main__":
    exit(main())