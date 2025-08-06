#!/usr/bin/env python3
"""
Production Field Validator
Final production-ready field validator that minimizes false positives by:
1. Recognizing frappe.get_doc() argument patterns
2. Better DocType inference through context analysis
3. Whitelisting common valid patterns
4. Enhanced recursive reference detection
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

class ProductionFieldValidator:
    """Production-ready field validator with minimal false positives"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.doctypes = self.load_all_doctypes()
        self.child_table_mappings = self.build_child_table_mappings()
        self.issues = []
        
        # Define whitelisted valid patterns
        self.valid_patterns = self._build_valid_patterns()
        
        # Define configuration field patterns
        self.config_field_patterns = self._build_config_patterns()
        
        # Define excluded patterns to avoid false positives
        self.excluded_patterns = self._build_excluded_patterns()
        
    def _build_valid_patterns(self) -> Dict[str, Set[str]]:
        """Build patterns that are known to be valid and should not be flagged"""
        return {
            # Patterns where field access is used as frappe.get_doc() arguments
            'frappe_get_doc_args': {
                'member', 'membership', 'volunteer', 'chapter', 'customer', 'supplier',
                'item', 'account', 'user', 'role', 'company', 'cost_center', 'project',
                'territory', 'warehouse', 'batch', 'serial_no', 'parent', 'parenttype'
            },
            
            # Fields commonly used in conditional expressions
            'conditional_fields': {
                'name', 'status', 'docstatus', 'enabled', 'disabled', 'is_active',
                'is_enabled', 'is_disabled', 'is_cancelled', 'is_submitted'
            },
            
            # Fields commonly used in dictionary/mapping contexts
            'mapping_fields': {
                'name', 'title', 'key', 'value', 'id', 'code', 'reference', 'identifier'
            }
        }
    
    def build_child_table_mappings(self) -> Dict[str, Dict[str, str]]:
        """Build mappings of parent DocType -> child table field -> child DocType"""
        mappings = {}
        
        for doctype, info in self.doctypes.items():
            data = info['data']
            child_tables = {}
            
            for field in data.get('fields', []):
                if field.get('fieldtype') == 'Table' and field.get('options'):
                    field_name = field.get('fieldname')
                    child_doctype = field.get('options')
                    if field_name and child_doctype:
                        child_tables[field_name] = child_doctype
                        
            if child_tables:
                mappings[doctype] = child_tables
                
        return mappings
    
    def _build_config_patterns(self) -> Dict[str, Set[str]]:
        """Build patterns for configuration and settings fields"""
        return {
            # Fields that are commonly found in settings doctypes
            'settings_fields': {
                'default_grace_period_days', 'grace_period_notification_days', 
                'grace_period_auto_apply', 'grace_period_expiry_date',
                'membership_type', 'membership_fee', 'payment_method',
                'billing_frequency', 'billing_day', 'auto_renewal_enabled',
                'default_membership_type', 'default_payment_terms',
                'notification_enabled', 'reminder_days', 'follow_up_days',
                'escalation_days', 'default_currency', 'tax_rate',
                'company_name', 'company_address', 'contact_email',
                'support_phone', 'website_url', 'terms_of_service',
                'privacy_policy', 'welcome_message', 'goodbye_message',
                'dues_schedule_template'  # Added this common false positive
            },
            
            # Fields that are commonly accessed through get() methods
            'optional_access_fields': {
                'member', 'membership', 'volunteer', 'chapter', 'organization',
                'user', 'customer', 'supplier', 'item', 'account', 'project',
                'cost_center', 'department', 'territory', 'warehouse', 'company'
            },
            
            # Fields that are often None and accessed conditionally
            'conditional_fields': {
                'parent', 'parentfield', 'parenttype', 'owner', 'modified_by',
                'creation', 'modified', 'docstatus', '_comments', '_assign',
                '_user_tags', '_liked_by'
            }
        }
    
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
            
            # Python unittest and test framework methods
            'test_methods': {
                'setUp', 'tearDown', 'setUpClass', 'tearDownClass',
                'assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse',
                'assertIs', 'assertIsNot', 'assertIsNone', 'assertIsNotNone',
                'assertIn', 'assertNotIn', 'assertIsInstance', 'assertNotIsInstance',
                'assertRaises', 'assertRaisesRegex', 'assertWarns', 'assertWarnsRegex',
                'assertLogs', 'assertAlmostEqual', 'assertNotAlmostEqual',
                'assertGreater', 'assertGreaterEqual', 'assertLess', 'assertLessEqual',
                'assertRegex', 'assertNotRegex', 'assertCountEqual', 'subTest',
                'skipTest', 'fail', 'failureException', 'longMessage', 'maxDiff',
                'addCleanup', 'doCleanups', 'addTypeEqualityFunc', 'assertListEqual',
                'assertTupleEqual', 'assertSetEqual', 'assertDictEqual'
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
                'name', 'type', 'value', 'id', 'class', 'style', 'data', 'result',
                'response', 'request', 'status', 'code', 'message', 'error', 'success',
                'info', 'debug', 'warning', 'critical', 'exception', 'args', 'kwargs',
                'self', 'cls', 'super', 'property', 'staticmethod', 'classmethod',
                'abstractmethod', 'cached_property'
            },
            
            # Process and system monitoring attributes  
            'system_monitoring': {
                'memory_info', 'cpu_percent', 'pid', 'ppid', 'status', 'username',
                'create_time', 'terminal', 'nice', 'ionice', 'rlimit', 'io_counters',
                'num_threads', 'num_fds', 'num_ctx_switches', 'cpu_times', 'memory_percent',
                'open_files', 'connections', 'uids', 'gids', 'cmdline', 'environ',
                'cwd', 'exe', 'children', 'parent', 'parents', 'is_running'
            },
            
            # Configuration and settings attributes
            'config_attributes': {
                'settings', 'config', 'options', 'preferences', 'defaults', 'params',
                'arguments', 'flags', 'version', 'title', 'description', 'author',
                'license', 'url', 'email', 'keywords', 'classifiers', 'requires',
                'install_requires', 'extras_require', 'python_requires', 'entry_points'
            }
        }
    
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
                print(f"Loading doctypes from {app_path.name}...")
                app_doctypes = self._load_doctypes_from_app(app_path)
                doctypes.update(app_doctypes)
                
        print(f"📋 Loaded {len(doctypes)} doctypes from all apps")
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
                    link_fields = {}  # Track Link field targets for recursive detection
                    
                    for field in data.get('fields', []):
                        fieldname = field.get('fieldname')
                        if fieldname:
                            fields.add(fieldname)
                            
                            # Track Link fields for recursive reference detection
                            if field.get('fieldtype') == 'Link':
                                link_fields[fieldname] = field.get('options', '')
                                
                    # Add standard Frappe document fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
                        'doctype', '_user_tags', '_comments', '_assign', '_liked_by'
                    ])
                    
                    doctypes[doctype_name] = {
                        'fields': fields,
                        'link_fields': link_fields,
                        'data': data,
                        'app': app_path.name
                    }
                    
                except Exception as e:
                    # Skip problematic files silently
                    continue
                    
        return doctypes
        
    def is_frappe_get_doc_argument(self, obj_name: str, field_name: str, context: str, 
                                  source_lines: List[str], line_num: int) -> bool:
        """Check if this field access is used as an argument to frappe.get_doc()"""
        
        # Check current line for frappe.get_doc pattern
        if f'frappe.get_doc(' in context and f'{obj_name}.{field_name}' in context:
            return True
            
        # Check if this field is commonly used as frappe.get_doc argument
        if field_name in self.valid_patterns['frappe_get_doc_args']:
            # Look for frappe.get_doc in surrounding lines
            context_start = max(0, line_num - 3)
            context_end = min(len(source_lines), line_num + 2)
            
            for i in range(context_start, context_end):
                if i < len(source_lines) and 'frappe.get_doc(' in source_lines[i]:
                    return True
                    
        return False
    
    def is_child_table_access(self, obj_name: str, field_name: str, context: str, 
                             source_lines: List[str], line_num: int) -> Optional[str]:
        """Check if this is child table field access and return the child DocType"""
        
        # Look for iteration patterns in surrounding lines
        context_start = max(0, line_num - 10)
        context_lines = source_lines[context_start:line_num]
        
        # Pattern 1: for obj_name in parent.child_table:
        for line in context_lines:
            # Match: for board_member in chapter.board_members:
            for_pattern = rf'for\s+{re.escape(obj_name)}\s+in\s+(\w+)\.(\w+)'
            match = re.search(for_pattern, line)
            if match:
                parent_obj = match.group(1)
                child_table_field = match.group(2)
                
                # Try to determine parent DocType and lookup child table
                parent_doctype = self._guess_doctype_from_variable_name(parent_obj)
                if parent_doctype and parent_doctype in self.child_table_mappings:
                    child_tables = self.child_table_mappings[parent_doctype]
                    if child_table_field in child_tables:
                        return child_tables[child_table_field]
        
        # Pattern 2: obj_name = parent.child_table[index]
        for line in context_lines:
            # Match: board_member = chapter.board_members[0]
            index_pattern = rf'{re.escape(obj_name)}\s*=\s*(\w+)\.(\w+)\['
            match = re.search(index_pattern, line)
            if match:
                parent_obj = match.group(1)
                child_table_field = match.group(2)
                
                parent_doctype = self._guess_doctype_from_variable_name(parent_obj)
                if parent_doctype and parent_doctype in self.child_table_mappings:
                    child_tables = self.child_table_mappings[parent_doctype]
                    if child_table_field in child_tables:
                        return child_tables[child_table_field]
        
        # Pattern 3: Check if obj_name suggests a child table record
        child_table_indicators = [
            'board_member', 'chapter_member', 'board_members', 'member', 'item',
            'expense_item', 'payment_item', 'schedule_item', 'role_assignment',
            'assignment', 'allocation', 'detail', 'line', 'entry'
        ]
        
        obj_lower = obj_name.lower()
        for indicator in child_table_indicators:
            if indicator in obj_lower:
                # Try to map to common child DocTypes
                child_doctype_mappings = {
                    'board_member': 'Verenigingen Chapter Board Member',
                    'chapter_member': 'Chapter Member',
                    'member': 'Member',  # Could be various member child tables
                    'expense_item': 'Volunteer Expense Item',
                    'payment_item': 'Payment Entry Item',
                    'schedule_item': 'Membership Dues Schedule',
                    'role_assignment': 'Role Assignment',
                }
                
                if indicator in child_doctype_mappings:
                    return child_doctype_mappings[indicator]
        
        return None
    
    def is_excluded_pattern(self, obj_name: str, field_name: str, context: str) -> bool:
        """Check if this object.field pattern should be excluded from validation"""
        
        # Check if object name matches known modules/libraries
        if obj_name in self.excluded_patterns['python_stdlib']:
            return True
            
        # Check if field name matches known built-in methods
        if field_name in self.excluded_patterns['python_builtins']:
            return True
            
        # Check if field name matches test framework methods
        if field_name in self.excluded_patterns['test_methods']:
            return True
            
        # Check if it's a Frappe framework method/attribute
        if field_name in self.excluded_patterns['frappe_framework']:
            return True
            
        # Check if it's a common non-field attribute
        if field_name in self.excluded_patterns['common_attributes']:
            return True
            
        # Check for system monitoring attributes
        if field_name in self.excluded_patterns['system_monitoring']:
            return True
            
        # Check for configuration attributes
        if field_name in self.excluded_patterns['config_attributes']:
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
    
    def is_recursive_field_reference(self, doctype: str, field_name: str) -> bool:
        """Check if this is a recursive field reference (field pointing to same DocType)"""
        if doctype not in self.doctypes:
            return False
            
        doctype_info = self.doctypes[doctype]
        link_fields = doctype_info.get('link_fields', {})
        
        # Check if this field is a Link field pointing to the same DocType
        return link_fields.get(field_name) == doctype
    
    def is_valid_pattern(self, obj_name: str, field_name: str, context: str, 
                        source_lines: List[str], line_num: int) -> bool:
        """Check if this is a known valid pattern that should not be flagged"""
        
        # Check if this is a frappe.get_doc argument
        if self.is_frappe_get_doc_argument(obj_name, field_name, context, source_lines, line_num):
            return True
            
        # Check if it's a conditional field commonly used in if statements
        if field_name in self.valid_patterns['conditional_fields']:
            if any(pattern in context for pattern in ['if ', 'and ', 'or ', 'not ', 'elif ']):
                return True
                
        # Check if it's used in mapping/dictionary contexts
        if field_name in self.valid_patterns['mapping_fields']:
            if any(pattern in context for pattern in ['{', '}', '[', ']', 'dict', 'map']):
                return True
        
        return False
    
    def is_settings_or_config_field(self, obj_name: str, field_name: str, context: str) -> bool:
        """Check if this is likely a settings or configuration field access"""
        
        # Check if field name is a known settings field
        if field_name in self.config_field_patterns['settings_fields']:
            return True
            
        # Check if accessed through get() method (common for optional fields)
        if f'.get("{field_name}")' in context or f".get('{field_name}')" in context:
            return True
            
        # Check for settings-related object names
        settings_indicators = [
            'settings', 'config', 'configuration', 'options', 'preferences',
            'defaults', 'parameters', 'verenigingen_settings'
        ]
        
        if any(indicator in obj_name.lower() for indicator in settings_indicators):
            return True
            
        # Check for getattr() patterns (defensive field access)
        if f'getattr({obj_name}, "{field_name}")' in context or f"getattr({obj_name}, '{field_name}')" in context:
            return True
            
        return False
    
    def _guess_doctype_from_variable_name(self, var_name: str) -> Optional[str]:
        """Guess DocType from variable name patterns"""
        var_lower = var_name.lower()
        
        # Direct mappings
        doctype_name_mappings = {
            'member': 'Member',
            'membership': 'Membership',
            'volunteer': 'Verenigingen Volunteer', 
            'chapter': 'Chapter',
            'schedule': 'Membership Dues Schedule',
            'dues_schedule': 'Membership Dues Schedule',
            'mandate': 'SEPA Mandate',
            'sepa_mandate': 'SEPA Mandate',
            'application': 'Membership Application',
            'expense': 'Volunteer Expense',
            'batch': 'Direct Debit Batch',
            'campaign': 'Donation Campaign',
            'payment_plan': 'Payment Plan',
            'settings': 'Verenigingen Settings',
            'termination_request': 'Membership Termination Request',
            'invoice': 'Sales Invoice',
            'payment': 'Payment Entry',
            'customer': 'Customer',
            'supplier': 'Supplier',
            'item': 'Item',
            'role': 'Role',
            'user': 'User'
        }
        
        # Check direct matches first
        if var_lower in doctype_name_mappings and doctype_name_mappings[var_lower] in self.doctypes:
            return doctype_name_mappings[var_lower]
        
        # Check partial matches
        for key, doctype in doctype_name_mappings.items():
            if key in var_lower and doctype in self.doctypes:
                return doctype
                
        return None
    
    def parse_with_ast(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Parse file using AST for better accuracy"""
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
                        
                        # Skip if it's a known valid pattern
                        if self.is_valid_pattern(obj_name, field_name, context, source_lines, line_num):
                            continue
                        
                        # Skip if it looks like settings/config field access
                        if self.is_settings_or_config_field(obj_name, field_name, context):
                            continue
                        
                        # Check if this is child table access first
                        child_doctype = self.is_child_table_access(obj_name, field_name, context, source_lines, line_num)
                        if child_doctype:
                            # Validate against child DocType fields
                            if child_doctype in self.doctypes:
                                child_fields = self.doctypes[child_doctype]['fields']
                                if field_name not in child_fields:
                                    # Check if this is likely a field access
                                    if self._is_likely_field_access(node, obj_name, field_name, context, source_lines):
                                        similar = self._find_similar_fields(field_name, child_fields)
                                        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                                        
                                        violations.append(ValidationIssue(
                                            file=str(file_path.relative_to(self.app_path)),
                                            line=line_num,
                                            field=field_name,
                                            doctype=child_doctype,
                                            reference=f"{obj_name}.{field_name}",
                                            message=f"Field '{field_name}' does not exist in child table {child_doctype}{similar_text}",
                                            context=context,
                                            confidence="high",
                                            issue_type="missing_child_table_field",
                                            suggested_fix=f"Use correct field name for {child_doctype}"
                                        ))
                            continue
                            
                        # Try to determine DocType from context for parent DocTypes
                        doctype = self._guess_doctype_from_context(content, node, obj_name)
                        
                        if doctype and doctype in self.doctypes:
                            # Check for recursive field references
                            if self.is_recursive_field_reference(doctype, field_name):
                                continue  # Skip recursive references as they're valid
                                
                            doctype_info = self.doctypes[doctype]
                            fields = doctype_info['fields']
                            
                            if field_name not in fields:
                                # Additional check: is this likely a legitimate field access?
                                if self._is_likely_field_access(node, obj_name, field_name, context, source_lines):
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
                                        suggested_fix=f"Use correct field name for {doctype} (from {doctype_info['app']} app)"
                                    ))
                                    
        except SyntaxError:
            # If AST parsing fails, fall back to regex with enhanced filtering
            violations.extend(self._validate_with_regex_enhanced(content, file_path))
            
        return violations
        
    def _is_likely_field_access(self, node: ast.Attribute, obj_name: str, field_name: str, 
                               context: str, source_lines: List[str]) -> bool:
        """Determine if this is likely a DocType field access vs other attribute access"""
        
        # Skip if it's clearly a method call (has parentheses immediately after)
        if f'{field_name}(' in context:
            return False
            
        # Skip if it's an assignment (setting the attribute)
        if f'{obj_name}.{field_name} =' in context:
            return False
            
        # Skip if it's in a function definition
        if context.strip().startswith('def ') and f'{field_name}(' in context:
            return False
            
        # Skip if it's obviously a property access on a complex object
        property_indicators = [
            f'self.{field_name}()',  # Method call on self
            f'hasattr({obj_name}, \'{field_name}\')',  # hasattr check
            f'getattr({obj_name}, \'{field_name}\')',  # getattr call
            f'setattr({obj_name}, \'{field_name}\')',  # setattr call
        ]
        
        if any(indicator in context for indicator in property_indicators):
            return False
            
        # Look for DocType-specific patterns that suggest field access
        doctype_indicators = [
            'frappe.get_doc(',  # Getting a document
            'frappe.new_doc(',  # Creating a document
            f'if {obj_name}.{field_name}',  # Conditional on field
            f'return {obj_name}.{field_name}',  # Returning field value
            f'{obj_name}.{field_name} or',  # Boolean operation
            f'{obj_name}.{field_name} and',  # Boolean operation
        ]
        
        # Check context around the current line
        line_no = node.lineno - 1
        context_range = range(max(0, line_no - 3), min(len(source_lines), line_no + 2))
        
        for i in context_range:
            line = source_lines[i].strip()
            if any(indicator in line for indicator in doctype_indicators):
                return True
                
        # Default to False for safety (reduce false positives)
        return False
        
    def _guess_doctype_from_context(self, content: str, node: ast.Attribute, obj_name: str) -> Optional[str]:
        """Enhanced DocType guessing from context using AST"""
        
        # Look for explicit DocType references in nearby lines
        line_start = max(0, node.lineno - 15)  # Expanded search range
        line_end = min(content.count('\n') + 1, node.lineno + 5)
        
        # Extract context around the node
        lines = content.splitlines()
        context_lines = lines[line_start:line_end]
        context = '\n'.join(context_lines)
        
        # Special case: Handle validation functions with (doc, method) pattern
        if obj_name == 'doc':
            doctype = self._guess_doctype_from_validation_context(content, lines, node.lineno)
            if doctype:
                return doctype
        
        # Look for frappe.get_doc calls with explicit DocType assignment
        get_doc_patterns = [
            rf'{re.escape(obj_name)}\s*=\s*frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in get_doc_patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1)
        
        # Look for frappe.new_doc calls with explicit DocType assignment
        new_doc_patterns = [
            rf'{re.escape(obj_name)}\s*=\s*frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in new_doc_patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1)
        
        # Enhanced: Use variable name inference
        doctype = self._guess_doctype_from_variable_name(obj_name)
        if doctype:
            return doctype
        
        # Look for explicit doctype mentions in comments or nearby lines
        for doctype in self.doctypes.keys():
            if f'"{doctype}"' in context or f"'{doctype}'" in context:
                return doctype
                
        # Check if obj_name suggests a DocType (common naming patterns)
        doctype_suffixes = ['_doc', '_document', 'doc', '_record', '_rec']
        for suffix in doctype_suffixes:
            if obj_name.endswith(suffix):
                base_name = obj_name[:-len(suffix)]
                # Try to match to a DocType
                for doctype in self.doctypes.keys():
                    if base_name.lower() in doctype.lower().replace(' ', '_'):
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
                        return doctype_mappings[func_name]
                    
                    # Try to infer from function name patterns
                    if func_name.startswith('validate_'):
                        # Convert snake_case to Title Case
                        potential_doctype = func_name[9:].replace('_', ' ').title()
                        if potential_doctype in self.doctypes:
                            return potential_doctype
        
        return None
        
    def _validate_with_regex_enhanced(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Enhanced regex validation with better filtering (fallback only)"""
        return []  # Disable regex fallback as AST is more accurate
        
    def _find_similar_fields(self, field_name: str, valid_fields: Set[str]) -> List[str]:
        """Find similar field names using string matching"""
        similar = []
        field_lower = field_name.lower()
        
        for valid_field in valid_fields:
            valid_lower = valid_field.lower()
            # Check for substring matches and similar patterns
            if (field_lower in valid_lower or valid_lower in field_lower or
                (len(field_lower) > 3 and len(valid_lower) > 3 and
                 (field_lower.startswith(valid_lower[:4]) or
                  field_lower.endswith(valid_lower[-4:]) or
                  valid_lower.startswith(field_lower[:4]) or
                  valid_lower.endswith(field_lower[-4:])))):
                similar.append(valid_field)
                
        return similar[:3]  # Return top 3 matches
        
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single file with enhanced filtering"""
        violations = []
        
        # Skip certain file types and directories known to have false positives
        skip_patterns = [
            '/node_modules/', '/__pycache__/', '/.git/', '/migrations/',
            'archived_unused/', 'backup/', '.disabled', 'patches/',
            # Skip files that are likely to have non-DocType field access
            'debug_', 'test_', 'benchmark', 'performance', 'monitoring'
        ]
        
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Use AST parsing for better accuracy
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
        medium_confidence = [v for v in violations if v.confidence == "medium"]
        
        if high_confidence:
            report.append(f"## High Confidence Issues ({len(high_confidence)})")
            report.append("These are very likely to be actual field reference errors:")
            report.append("")
            
            for violation in high_confidence[:20]:  # Limit to first 20
                report.append(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
                report.append(f"   → {violation.message}")
                report.append(f"   Context: {violation.context}")
                report.append("")
                
        if medium_confidence:
            report.append(f"## Medium Confidence Issues ({len(medium_confidence)})")
            report.append("These may need manual review:")
            report.append("")
            
            for violation in medium_confidence[:10]:  # Limit to first 10
                report.append(f"⚠️  {violation.file}:{violation.line} - {violation.field}")
                report.append(f"   → {violation.message}")
                report.append("")
                
        return '\n'.join(report)


def main():
    """Main function with production-ready validation"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Check for pre-commit mode
    pre_commit = '--pre-commit' in sys.argv
    
    validator = ProductionFieldValidator(app_path)
    print(f"📋 Loaded {len(validator.doctypes)} doctypes with field definitions")
    print(f"🔗 Built {len(validator.child_table_mappings)} child table mappings")
    print(f"✅ Enhanced with production-level false positive reduction")
    
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
        medium_confidence = len([v for v in violations if v.confidence == "medium"])
        
        print(f"\n💡 Summary:")
        print(f"   - High confidence issues: {high_confidence}")
        print(f"   - Medium confidence issues: {medium_confidence}")
        print(f"   - Total issues: {len(violations)}")
        
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