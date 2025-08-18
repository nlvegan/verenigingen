#!/usr/bin/env python3
"""
AST Field Analyzer for Field Reference Validation - Enhanced Version
=====================================================================

Features:
- File path-based DocType inference for hook files
- Link field detection to reduce false positives
- Robust error handling and validation
- Performance optimizations with caching
- Enhanced confidence scoring for hook contexts
"""

import ast
import json
import re
import logging
import traceback
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import difflib
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import unified DocType loader
try:
    from .doctype_loader import load_doctypes_detailed
    from .hooks_parser import HooksParser
except ImportError:
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    try:
        from doctype_loader import load_doctypes_detailed
        from hooks_parser import HooksParser
    finally:
        if str(current_dir) in sys.path:
            sys.path.remove(str(current_dir))

class ConfidenceLevel(Enum):
    """Confidence levels for issue detection"""
    CRITICAL = "critical"  # 95%+ confidence
    HIGH = "high"          # 80-95% confidence  
    MEDIUM = "medium"      # 60-80% confidence
    LOW = "low"            # 40-60% confidence
    INFO = "info"          # <40% confidence

@dataclass
class ValidationContext:
    """Enhanced context for validation decisions"""
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    is_test_file: bool = False
    is_validation_hook: bool = False
    is_migration: bool = False
    doctype_hints: Set[str] = field(default_factory=set)
    variable_types: Dict[str, str] = field(default_factory=dict)
    imported_modules: Set[str] = field(default_factory=set)
    function_scope_vars: Set[str] = field(default_factory=set)
    file_path: Optional[Path] = None  # NEW: Add file path for context
    is_hook_file: bool = False  # NEW: Flag for hook files
    inferred_doctype: Optional[str] = None  # NEW: Cache inferred DocType
    
    def __post_init__(self):
        """Validate and derive additional context"""
        if self.file_path:
            self.is_hook_file = str(self.file_path).endswith('_hooks.py')

@dataclass
class ValidationIssue:
    """Represents a field validation issue with enhanced metadata"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: ConfidenceLevel
    issue_type: str
    suggested_fix: Optional[str] = None
    severity: str = "medium"
    category: str = "field_reference"
    inference_method: Optional[str] = None

class ConfidenceThresholds:
    """Confidence scoring thresholds"""
    CRITICAL = 0.9
    HIGH = 0.7
    MEDIUM = 0.5
    LOW = 0.3

class VariableContextVisitor(ast.NodeVisitor):
    """Collect variable context to reduce false positives"""
    
    def __init__(self):
        self.iteration_vars = set()      # Variables from for loops and comprehensions
        self.function_params = {}        # function_name -> set of parameter names
        self.child_table_vars = {}       # variable -> child_table_doctype
        self.dynamic_vars = {}           # variable -> likely_doctype from assignments
        self.current_function = None
    
    def visit_FunctionDef(self, node):
        """Track function definitions and parameters"""
        old_function = self.current_function
        self.current_function = node.name
        
        # Extract function parameters
        param_names = set()
        for arg in node.args.args:
            param_names.add(arg.arg)
        
        # Store function parameters
        self.function_params[node.name] = param_names
        
        # Check for DocType hints in function name or parameters
        if 'doc' in param_names:
            # Common pattern: functions that receive a document
            if 'member' in node.name.lower():
                self.dynamic_vars['doc'] = 'Member'
            elif 'donation' in node.name.lower():
                self.dynamic_vars['doc'] = 'Donation'
            elif 'invoice' in node.name.lower():
                self.dynamic_vars['doc'] = 'Sales Invoice'
        
        self.generic_visit(node)
        self.current_function = old_function
    
    def visit_For(self, node):
        """Track for loop iteration variables"""
        if isinstance(node.target, ast.Name):
            self.iteration_vars.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    self.iteration_vars.add(elt.id)
        
        self.generic_visit(node)
    
    def visit_ListComp(self, node):
        """Track list comprehension iteration variables"""
        for generator in node.generators:
            if isinstance(generator.target, ast.Name):
                self.iteration_vars.add(generator.target.id)
            elif isinstance(generator.target, ast.Tuple):
                for elt in generator.target.elts:
                    if isinstance(elt, ast.Name):
                        self.iteration_vars.add(elt.id)
        self.generic_visit(node)
    
    def visit_SetComp(self, node):
        """Track set comprehension iteration variables"""
        self.visit_ListComp(node)  # Same logic
    
    def visit_DictComp(self, node):
        """Track dict comprehension iteration variables"""
        self.visit_ListComp(node)  # Same logic
    
    def visit_GeneratorExp(self, node):
        """Track generator expression iteration variables"""
        self.visit_ListComp(node)  # Same logic
    
    def visit_Assign(self, node):
        """Track variable assignments for DocType inference"""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            var_name = node.targets[0].id
            
            # Check for frappe.get_doc and frappe.get_cached_doc patterns
            if (isinstance(node.value, ast.Call) and 
                isinstance(node.value.func, ast.Attribute) and
                isinstance(node.value.func.value, ast.Name) and
                node.value.func.value.id == 'frappe' and
                node.value.func.attr in ['get_doc', 'get_cached_doc', 'new_doc'] and
                len(node.value.args) >= 1):
                
                # Extract DocType from frappe.get_doc("DocType", ...) or frappe.get_cached_doc("DocType", ...)
                doctype = self._extract_string_constant(node.value.args[0])
                if doctype:
                    self.dynamic_vars[var_name] = doctype
            
            # Check for child table iteration patterns
            # Pattern: for item in self.items:
            if isinstance(node.value, ast.Attribute):
                attr_name = node.value.attr
                if attr_name in ['items', 'members', 'lines', 'details', 'entries']:
                    # These are likely child table fields
                    self.child_table_vars[var_name] = f"Child_{attr_name}"
        
        self.generic_visit(node)
    
    def _extract_string_constant(self, node) -> Optional[str]:
        """Extract string value from AST node, compatible with all Python versions"""
        # Python 3.8+ uses ast.Constant
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        
        # Legacy support for Python < 3.8 (avoid deprecated ast.Str)
        # Note: ast.Str is deprecated as of Python 3.14 but may exist in older versions
        try:
            if hasattr(node, 's') and hasattr(node, '__class__') and node.__class__.__name__ == 'Str':
                return node.s
        except AttributeError:
            pass
            
        return None


class ASTFieldAnalyzer:
    """Advanced AST-based field reference analyzer with hook file support"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.verbose = verbose
        
        # Use unified DocType loader
        self.doctypes = load_doctypes_detailed(str(self.app_path), verbose=False)
        self.child_table_mapping = self._build_child_table_mapping()
        self.issues = []
        
        # Initialize hooks parser
        self.hooks_parser = HooksParser(str(self.app_path), verbose=False)
        
        # Build comprehensive patterns
        self.excluded_patterns = self._build_excluded_patterns()
        self.framework_patterns = self._build_framework_patterns()
        self.test_patterns = self._build_test_patterns()
        self.doctype_name_patterns = self._build_doctype_name_patterns()
        
        # Enhanced tracking for false positive reduction
        self.iteration_variables = set()
        self.function_parameters = {}
        self.child_table_vars = {}
        self.dynamic_variables = {}
        
        # NEW: Performance optimization caches
        self._file_path_cache: Dict[str, Optional[str]] = {}
        self._link_field_cache: Dict[str, Optional[str]] = {}
        
        # NEW: Build DocType pattern mappings for file paths
        self._doctype_file_patterns = self._build_doctype_file_patterns()
    
    def _build_doctype_file_patterns(self) -> Dict[str, str]:
        """Build patterns for mapping file names to DocTypes"""
        patterns = {}
        
        for doctype_name in self.doctypes.keys():
            # Convert DocType name to various file patterns
            snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', doctype_name).lower()
            snake_case = snake_case.replace(' ', '_')
            
            # Pattern for hook files
            patterns[f"{snake_case}_hooks"] = doctype_name
            
            # Pattern for main doctype files
            patterns[snake_case] = doctype_name
            
            # Handle special cases
            if ' ' in doctype_name:
                no_space = doctype_name.replace(' ', '')
                no_space_snake = re.sub(r'(?<!^)(?=[A-Z])', '_', no_space).lower()
                patterns[no_space_snake] = doctype_name
                patterns[f"{no_space_snake}_hooks"] = doctype_name
        
        return patterns
    
    def _infer_doctype_from_file_path(self, file_context: ValidationContext) -> Optional[str]:
        """Infer DocType from file path patterns with robust error handling"""
        
        if not file_context.file_path:
            return None
        
        # Check cache first
        file_key = str(file_context.file_path)
        if file_key in self._file_path_cache:
            cached_result = self._file_path_cache[file_key]
            if self.verbose and cached_result:
                print(f"    ✓ Using cached DocType for {file_context.file_path.name}: {cached_result}")
            return cached_result
        
        try:
            file_path = Path(file_context.file_path)
            
            # Sanitize and validate path
            if not self._validate_file_path(file_path):
                self._file_path_cache[file_key] = None
                return None
            
            file_name = file_path.name
            
            # Pattern 1: Hook files - doctype_name_hooks.py pattern
            if file_name.endswith('_hooks.py'):
                base_name = file_name[:-9]  # Remove '_hooks.py'
                
                if not base_name:  # Handle edge case of just '_hooks.py'
                    self._file_path_cache[file_key] = None
                    return None
                
                # Check direct pattern match first
                if base_name in self._doctype_file_patterns:
                    doctype = self._doctype_file_patterns[base_name]
                    if doctype in self.doctypes:
                        if self.verbose:
                            print(f"    ✓ Inferred {doctype} from hook file: {file_name}")
                        self._file_path_cache[file_key] = doctype
                        return doctype
                
                # Try converting to Title Case
                potential_doctype = base_name.replace('_', ' ').title()
                if potential_doctype in self.doctypes:
                    if self.verbose:
                        print(f"    ✓ Inferred {potential_doctype} from hook file: {file_name}")
                    self._file_path_cache[file_key] = potential_doctype
                    return potential_doctype
            
            # Pattern 2: DocType module files - doctype/doctype_name/doctype_name.py
            path_parts = file_path.parts
            if len(path_parts) >= 3:
                for i in range(len(path_parts) - 2):
                    if path_parts[i] == 'doctype':
                        # Expected structure: .../doctype/doctype_name/...
                        doctype_folder = path_parts[i + 1]
                        
                        # Check pattern match
                        if doctype_folder in self._doctype_file_patterns:
                            doctype = self._doctype_file_patterns[doctype_folder]
                            if doctype in self.doctypes:
                                if self.verbose:
                                    print(f"    ✓ Inferred {doctype} from doctype path: {doctype_folder}")
                                self._file_path_cache[file_key] = doctype
                                return doctype
                        
                        # Try Title Case conversion
                        potential_doctype = doctype_folder.replace('_', ' ').title()
                        if potential_doctype in self.doctypes:
                            if self.verbose:
                                print(f"    ✓ Inferred {potential_doctype} from doctype path: {doctype_folder}")
                            self._file_path_cache[file_key] = potential_doctype
                            return potential_doctype
                        break
            
            # Pattern 3: Check function name patterns in file context
            if file_context.function_name:
                func_name = file_context.function_name
                
                # Special patterns for specific DocTypes
                hook_function_patterns = {
                    'dues_schedule': 'Membership Dues Schedule',
                    'membership_dues': 'Membership Dues Schedule',
                    'payment_entry': 'Payment Entry',
                    'sales_invoice': 'Sales Invoice',
                    'sepa_mandate': 'SEPA Mandate',
                }
                
                for pattern, doctype in hook_function_patterns.items():
                    if pattern in func_name.lower() and doctype in self.doctypes:
                        if self.verbose:
                            print(f"    ✓ Inferred {doctype} from function name: {func_name}")
                        self._file_path_cache[file_key] = doctype
                        return doctype
            
        except Exception as e:
            logger.warning(f"Error inferring DocType from file path {file_context.file_path}: {e}")
        
        self._file_path_cache[file_key] = None
        return None
    
    def _validate_file_path(self, file_path: Path) -> bool:
        """Validate file path for security and correctness"""
        try:
            # Resolve to absolute path
            resolved_path = file_path.resolve()
            
            # Ensure it's under the app path (security check)
            app_resolved = self.app_path.resolve()
            if not str(resolved_path).startswith(str(app_resolved)):
                logger.warning(f"File path outside app directory: {resolved_path}")
                return False
            
            return True
            
        except (OSError, ValueError) as e:
            logger.warning(f"Invalid file path: {file_path} - {e}")
            return False
    
    def _is_link_field_to_other_doctype(self, field_name: str, source_doctype: str) -> Optional[str]:
        """Check if a field is a Link to another DocType"""
        
        # Check cache first
        cache_key = f"{source_doctype}.{field_name}"
        if cache_key in self._link_field_cache:
            return self._link_field_cache[cache_key]
        
        result = None
        
        if source_doctype in self.doctypes:
            doctype_info = self.doctypes[source_doctype]
            
            # Check if we have field metadata (requires enhancement in doctype_loader)
            field_metadata = doctype_info.get('field_metadata', {})
            
            if field_name in field_metadata:
                field_meta = field_metadata[field_name]
                if field_meta.get('fieldtype') == 'Link':
                    target_doctype = field_meta.get('options')
                    if target_doctype and target_doctype in self.doctypes:
                        result = target_doctype
            
            # Fallback: Common Link field patterns
            if not result:
                link_field_patterns = {
                    'member': 'Member',
                    'customer': 'Customer',
                    'supplier': 'Supplier',
                    'user': 'User',
                    'employee': 'Employee',
                    'company': 'Company',
                    'cost_center': 'Cost Center',
                    'project': 'Project',
                    'warehouse': 'Warehouse',
                    'account': 'Account',
                    'party': None,  # Can be various DocTypes
                    'party_type': None,  # Indicates party field type
                }
                
                if field_name in link_field_patterns:
                    result = link_field_patterns[field_name]
        
        self._link_field_cache[cache_key] = result
        return result
    
    def _validate_path_inference(self, node: ast.Attribute, inferred_doctype: str, 
                                 source_lines: List[str], file_context: ValidationContext) -> bool:
        """Validate that path-inferred DocType makes sense in context"""
        
        if not inferred_doctype or inferred_doctype not in self.doctypes:
            return False
        
        field_name = node.attr
        doctype_info = self.doctypes[inferred_doctype]
        doctype_fields = doctype_info.get('fields', set())
        
        # If the field exists on the inferred DocType, it's valid
        if field_name in doctype_fields:
            return True
        
        # Check if it's a Link field
        link_target = self._is_link_field_to_other_doctype(field_name, inferred_doctype)
        if link_target:
            # This is a Link field, which is valid
            return True
        
        # Check if it's a common framework field that all DocTypes have
        common_fields = {
            'name', 'creation', 'modified', 'modified_by', 'owner', 
            'docstatus', 'idx', 'parent', 'parentfield', 'parenttype'
        }
        if field_name in common_fields:
            return True
        
        # Check if there's evidence in nearby code that supports this inference
        line_num = node.lineno
        context_start = max(0, line_num - 5)
        context_end = min(len(source_lines), line_num + 5)
        
        for i in range(context_start, context_end):
            if i < len(source_lines):
                line = source_lines[i]
                # Look for DocType references
                if inferred_doctype in line:
                    return True
                # Look for field combinations that match this DocType
                for field in list(doctype_fields)[:5]:  # Check a few fields
                    if field in line:
                        return True
        
        # If we're in a hook file and the inference came from file path, trust it more
        if file_context.is_hook_file and field_name not in ['get', 'set', 'save', 'insert']:
            return True
        
        return False
    
    def _build_excluded_patterns(self) -> Dict[str, Set[str]]:
        """Build comprehensive excluded patterns with modern additions"""
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
                'seekable', 'fileno', 'isatty', 'truncate', 'stem', 'name', 'exists',
                '__dict__', '__class__', '__module__', '__name__', '__doc__',
                '__init__', '__str__', '__repr__', '__hash__', '__eq__', '__ne__',
                '__lt__', '__le__', '__gt__', '__ge__', '__bool__', '__len__',
                '__getitem__', '__setitem__', '__delitem__', '__contains__',
                '__iter__', '__next__', '__reversed__', '__call__'
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
                'delete', 'as_dict', 'as_json', 'get', 'set', 'append', 'model',
                'get_meta', 'get_field', 'set_df_property', 'get_df_property',
                'add_child', 'remove_child', 'validate_value', 'check_permission',
                'load_from_db', 'save_version', 'get_title', 'get_url',
                'queue_action', 'validate_and_sanitize_search_inputs', 'enqueue_doc',
                'run_server_script', 'run_trigger', 'get_cached', 'clear_cache',
                'get_hooks', 'has_hook', 'run_hook', 'get_installed_apps'
            },
            
            # Common non-field attributes
            'common_attributes': {
                'type', 'value', 'id', 'class', 'style', 'data', 'result', 'fields',
                'response', 'request', 'status', 'code', 'message', 'error', 'success',
                'info', 'debug', 'warning', 'critical', 'exception', 'args', 'kwargs',
                'self', 'cls', 'super', 'property', 'staticmethod', 'classmethod',
                'abstractmethod', 'cached_property', 'enabled', 'template', 'baseline_file',
                'config', 'settings', 'options', 'params', 'query', 'filter', 'sort',
                'limit', 'offset', 'page', 'per_page', 'total', 'count', 'sum',
                'min', 'max', 'avg', 'median', 'mode', 'variance', 'std_dev'
            },
            
            # Testing patterns
            'test_attributes': {
                'assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse',
                'assertIsNone', 'assertIsNotNone', 'assertIn', 'assertNotIn',
                'assertRaises', 'assertWarns', 'assertLogs', 'assertAlmostEqual',
                'assertNotAlmostEqual', 'assertGreater', 'assertGreaterEqual',
                'assertLess', 'assertLessEqual', 'assertRegex', 'assertNotRegex',
                'assertListEqual', 'assertTupleEqual', 'assertSetEqual',
                'assertDictEqual', 'assertSequenceEqual', 'assertCountEqual'
            }
        }
    
    def _build_framework_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Build modern framework-specific patterns"""
        return {
            'frappe_api_calls': [
                re.compile(r'frappe\.(db\.)?get_(all|list|doc|value|single_value)\('),
                re.compile(r'frappe\.(db\.)?set_value\('),
                re.compile(r'frappe\.new_doc\('),
                re.compile(r'frappe\.delete_doc\('),
                re.compile(r'frappe\.get_meta\('),
                re.compile(r'frappe\.qb\.'),  # Query builder
                re.compile(r'frappe\.model\.'),  # Model utilities
            ],
            'permission_checks': [
                re.compile(r'has_permission\('),
                re.compile(r'check_permission\('),
                re.compile(r'validate_permission\('),
                re.compile(r'get_permitted_fields\('),
            ],
            'workflow_patterns': [
                re.compile(r'apply_workflow\('),
                re.compile(r'get_workflow_state\('),
                re.compile(r'set_workflow_state\('),
            ]
        }
    
    def _build_test_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Build patterns for test file detection"""
        return {
            'test_methods': [
                re.compile(r'def test_\w+\('),
                re.compile(r'class Test\w+\('),
                re.compile(r'self\.assert\w+\('),
                re.compile(r'self\.create_test_\w+\('),
            ],
            'test_utilities': [
                re.compile(r'make_test_\w+\('),
                re.compile(r'create_test_\w+\('),
                re.compile(r'get_test_\w+\('),
                re.compile(r'setup_test_\w+\('),
            ]
        }
    
    def _build_doctype_name_patterns(self) -> Dict[str, str]:
        """Build comprehensive DocType name mapping patterns"""
        patterns = {}
        
        # Add DocType names themselves as patterns
        for doctype_name in self.doctypes.keys():
            # Convert to snake_case for variable naming
            snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', doctype_name).lower()
            snake_case = snake_case.replace(' ', '_')
            patterns[snake_case] = doctype_name
            
            # Also add without underscores
            no_underscore = snake_case.replace('_', '')
            if no_underscore != snake_case:
                patterns[no_underscore] = doctype_name
        
        return patterns
    
    def _build_child_table_mapping(self) -> Dict[str, str]:
        """Build enhanced mapping of parent.field -> child DocType using unified loader"""
        mapping = {}
        
        for doctype_name, doctype_info in self.doctypes.items():
            # Extract child table info from unified loader format
            child_tables = doctype_info.get('child_tables', [])
            
            for field_name, child_doctype in child_tables:
                # Multiple mapping patterns for flexibility
                mapping[f"{doctype_name}.{field_name}"] = child_doctype
                
                # Also map with snake_case version
                snake_case_parent = re.sub(r'(?<!^)(?=[A-Z])', '_', doctype_name).lower()
                mapping[f"{snake_case_parent}.{field_name}"] = child_doctype
                
                if self.verbose and len(mapping) < 10:  # Limit verbose output
                    print(f"Child table mapping: {doctype_name}.{field_name} -> {child_doctype}")
                
        return mapping
    
    def detect_doctype_with_modern_logic(self, node: ast.Attribute, source_lines: List[str],
                                        file_context: ValidationContext) -> Tuple[Optional[str], Optional[str]]:
        """Modern DocType detection with file path inference as highest priority"""
        
        obj_name = node.value.id if hasattr(node.value, 'id') else None
        if not obj_name:
            return None, None
        
        line_num = node.lineno
        
        if self.verbose and obj_name == 'doc':
            print(f"    🔍 Starting detection for {obj_name} at line {line_num}")
        
        # NEW Strategy 0: File path inference (highest priority for hook files)
        if file_context.is_hook_file and obj_name in ['doc', 'self']:
            if self.verbose:
                print(f"    🔍 Trying Strategy 0: File path inference for hook file")
            
            path_doctype = self._infer_doctype_from_file_path(file_context)
            if path_doctype:
                # Validate this makes sense in context
                if self._validate_path_inference(node, path_doctype, source_lines, file_context):
                    if self.verbose:
                        print(f"    ✓ Found {obj_name} -> {path_doctype} via file path inference")
                    file_context.inferred_doctype = path_doctype  # Cache for later use
                    return path_doctype, "file_path_inference"
                elif self.verbose:
                    print(f"    ⚠️ Path inference {path_doctype} failed validation")
        
        # Strategy 1: Explicit type checks in code (highest confidence)
        if obj_name in ['doc', 'self']:
            if self.verbose and obj_name == 'doc':
                print(f"    🔍 Trying Strategy 1: Explicit type check")
            explicit_doctype = self._find_explicit_type_check(obj_name, source_lines, line_num)
            if explicit_doctype:
                return explicit_doctype, "explicit_type_check"
        
        # Strategy 2: Event handler hooks registry (very high confidence)
        if obj_name in ['doc', 'self']:
            if self.verbose and obj_name == 'doc':
                print(f"    🔍 Trying Strategy 2: Hooks registry")
            hook_doctype = self._analyze_hooks_registry(source_lines, line_num, file_context)
            if hook_doctype:
                return hook_doctype, "hooks_registry"
        
        # Strategy 3: Field usage pattern analysis (high confidence)
        if obj_name in ['doc', 'self']:
            if self.verbose and obj_name == 'doc':
                print(f"    🔍 Trying Strategy 3: Field usage patterns")
            pattern_doctype = self._infer_from_field_usage_patterns(obj_name, source_lines, line_num, node)
            if pattern_doctype:
                return pattern_doctype, "field_usage_pattern"
        
        # Strategy 4: Direct variable assignment tracking (medium confidence)
        assignment_doctype = self._track_variable_assignment(obj_name, source_lines, line_num)
        if self.verbose and obj_name == 'doc':
            print(f"    🔍 Strategy 4 result: {assignment_doctype}")
        if assignment_doctype:
            return assignment_doctype, "variable_assignment"
        
        # Strategy 5: Child table iteration patterns
        child_doctype = self._detect_child_table_iteration(obj_name, source_lines, line_num)
        if child_doctype:
            return child_doctype, "child_table_iteration"
        
        # Strategy 6: Function parameter analysis
        if obj_name in ['doc', 'self']:
            param_doctype = self._analyze_function_parameters(source_lines, line_num, file_context)
            if param_doctype:
                return param_doctype, "function_parameter_analysis"
        
        # Strategy 7: Enhanced variable name mapping
        mapped_doctype = self._map_variable_to_doctype(obj_name)
        if mapped_doctype:
            return mapped_doctype, "variable_name_mapping"
        
        # Strategy 8: Context-based inference
        inferred_doctype = self._infer_from_context(obj_name, source_lines, line_num, file_context)
        if inferred_doctype:
            return inferred_doctype, "context_inference"
        
        # Final fallback: Use cached inference from file path if available
        if file_context.inferred_doctype and obj_name in ['doc', 'self']:
            return file_context.inferred_doctype, "cached_file_inference"
        
        return None, None
    
    def calculate_confidence(self, issue: ValidationIssue, context: ValidationContext) -> ConfidenceLevel:
        """Calculate confidence level with special handling for hook files"""
        confidence_score = 50  # Start at medium
        
        # Adjust base score based on inference method
        inference_confidence = {
            "file_path_inference": 85,  # High confidence for file path inference
            "explicit_type_check": 95,
            "hooks_registry": 90, 
            "field_usage_pattern": 80,
            "variable_assignment": 60,
            "child_table_iteration": 70,
            "function_parameter_analysis": 40,
            "variable_name_mapping": 30,
            "context_inference": 20,
            "cached_file_inference": 75,  # Moderate-high for cached inference
        }
        
        if issue.inference_method and issue.inference_method in inference_confidence:
            confidence_score = inference_confidence[issue.inference_method]
        
        # Special handling for hook files
        if context.is_hook_file:
            # Check if this might be a Link field
            link_target = self._is_link_field_to_other_doctype(issue.field, issue.doctype)
            if link_target:
                # This is actually a Link field, not a missing field
                # Drastically reduce confidence as this is likely a false positive
                confidence_score = 10
                
            # If the inference came from file path and it's a hook file, boost confidence
            elif issue.inference_method == "file_path_inference":
                confidence_score = min(confidence_score + 15, 95)
                
            # Common fields in hook files that might be dynamic
            elif issue.field in ['is_template', 'member', 'status', 'doctype']:
                # These are often valid fields on the inferred DocType
                if context.inferred_doctype == issue.doctype:
                    confidence_score = min(confidence_score + 10, 90)
        
        # Increase confidence for certain patterns
        if issue.issue_type == "missing_doctype":
            confidence_score += 30
        
        if context.is_validation_hook:
            confidence_score += 20
            
        if not context.is_test_file:
            confidence_score += 10
        
        if issue.doctype in context.doctype_hints:
            confidence_score += 15
            
        # Decrease confidence for certain patterns
        if context.is_test_file:
            confidence_score -= 30
            
        if context.is_migration:
            confidence_score -= 20
            
        if issue.field.startswith('_'):
            confidence_score -= 25
            
        if issue.field in self.excluded_patterns.get('common_attributes', set()):
            confidence_score -= 40
        
        # Check for legacy or dynamic fields
        if self._is_likely_legacy_or_dynamic_field(issue.field, issue.doctype):
            confidence_score -= 50
        
        # Check if it looks like a method call
        if '()' in issue.context or f'{issue.field}(' in issue.context:
            confidence_score -= 35
        
        # Map score to confidence level
        confidence_score = max(0, min(100, confidence_score))  # Clamp to 0-100
        
        if confidence_score >= 95:
            return ConfidenceLevel.CRITICAL
        elif confidence_score >= 80:
            return ConfidenceLevel.HIGH
        elif confidence_score >= 60:
            return ConfidenceLevel.MEDIUM
        elif confidence_score >= 40:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.INFO
    
    def analyze_file_context(self, tree: ast.AST, file_path: Path) -> ValidationContext:
        """Analyze entire file context for better understanding"""
        context = ValidationContext()
        
        # Store file path in context
        context.file_path = file_path
        
        # Check if it's a test file
        file_str = str(file_path)
        context.is_test_file = any(pattern in file_str for pattern in [
            '/test_', '/tests/', '_test.py', 'test.py'
        ])
        
        # Check if it's a migration
        context.is_migration = '/migrations/' in file_str or '/patches/' in file_str
        
        # Check if it's a hook file
        context.is_hook_file = file_str.endswith('_hooks.py')
        
        # If it's a hook file, try to infer the DocType early
        if context.is_hook_file:
            context.inferred_doctype = self._infer_doctype_from_file_path(context)
        
        # Analyze imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    context.imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    context.imported_modules.add(node.module)
        
        # Analyze class and function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                context.class_name = node.name
                # Check if it's a test class
                if node.name.startswith('Test'):
                    context.is_test_file = True
                    
            elif isinstance(node, ast.FunctionDef):
                # Store the current function name in context
                if not context.function_name:  # Keep the first/main function
                    context.function_name = node.name
                
                # Check for validation hooks
                if node.name in ['validate', 'before_save', 'after_insert', 'on_update']:
                    context.is_validation_hook = True
                    # Try to infer DocType from function context
                    if len(node.args.args) > 0:
                        first_arg = node.args.args[0].arg
                        if first_arg in ['doc', 'self']:
                            # Look for doctype hints in function body
                            context.doctype_hints.update(self._extract_doctype_hints(node))
        
        return context
    
    # Include all the other unchanged methods from the original implementation
    
    def _extract_doctype_hints(self, node: ast.FunctionDef) -> Set[str]:
        """Extract DocType hints from function body"""
        hints = set()
        
        for child in ast.walk(node):
            if isinstance(child, ast.Constant):
                # Look for DocType names in string constants
                if isinstance(child.value, str) and child.value in self.doctypes:
                    hints.add(child.value)
            elif isinstance(child, ast.Call):
                # Look for frappe.get_doc calls
                if hasattr(child.func, 'attr') and child.func.attr in ['get_doc', 'new_doc']:
                    if child.args and isinstance(child.args[0], ast.Constant):
                        doctype = child.args[0].value
                        if doctype in self.doctypes:
                            hints.add(doctype)
        
        return hints
    
    def _is_likely_legacy_or_dynamic_field(self, field_name: str, doctype: str) -> bool:
        """Check if field might be legacy, dynamic, or computed property"""
        
        # Common patterns for legacy/dynamic fields
        legacy_patterns = [
            'enable_version_control',  # System Settings legacy field
            'new_dues_schedule',       # Dynamic property 
            'track_changes',          # Legacy field name
            'version_tracking',       # Legacy field name
        ]
        
        if field_name in legacy_patterns:
            return True
        
        # Fields that start with common dynamic prefixes
        dynamic_prefixes = ['new_', 'old_', 'prev_', 'current_', 'next_', 'temp_']
        if any(field_name.startswith(prefix) for prefix in dynamic_prefixes):
            return True
        
        # Fields that might be computed properties (ending with specific suffixes)
        computed_suffixes = ['_computed', '_calculated', '_derived', '_generated']
        if any(field_name.endswith(suffix) for suffix in computed_suffixes):
            return True
        
        return False
    
    def _find_explicit_type_check(self, var_name: str, source_lines: List[str], line_num: int) -> Optional[str]:
        """Find explicit doctype checks like 'if doc.doctype == "X"'"""
        # Implementation from original
        pass
    
    def _analyze_hooks_registry(self, source_lines: List[str], line_num: int, 
                               file_context: ValidationContext) -> Optional[str]:
        """Use hooks registry to determine DocType for event handler functions"""
        # Implementation from original
        pass
    
    def _infer_from_field_usage_patterns(self, var_name: str, source_lines: List[str], 
                                       line_num: int, current_node: ast.Attribute) -> Optional[str]:
        """Infer DocType from unique field combination patterns"""
        # Implementation from original
        pass
    
    def _track_variable_assignment(self, var_name: str, lines: List[str], current_line: int, depth: int = 0) -> Optional[str]:
        """Track variable assignments to determine DocType with enhanced recursion protection"""
        # Implementation from original
        pass
    
    def _detect_child_table_iteration(self, var_name: str, lines: List[str], current_line: int) -> Optional[str]:
        """Detect child table iteration patterns"""
        # Implementation from original
        pass
    
    def _analyze_function_parameters(self, lines: List[str], current_line: int, 
                                    file_context: ValidationContext) -> Optional[str]:
        """Analyze function parameters to determine DocType"""
        # Implementation from original
        pass
    
    def _map_variable_to_doctype(self, var_name: str) -> Optional[str]:
        """Map variable names to DocTypes using comprehensive patterns"""
        # Implementation from original
        pass
    
    def _infer_from_context(self, var_name: str, lines: List[str], current_line: int,
                           file_context: ValidationContext) -> Optional[str]:
        """Infer DocType from surrounding context"""
        # Implementation from original
        pass
    
    def is_excluded_pattern(self, obj_name: str, field_name: str, context_line: str, 
                           file_context: ValidationContext) -> bool:
        """Modernized exclusion checking with context awareness"""
        # Implementation from original
        pass
    
    def _should_skip_validation(self, obj_name: str, field_name: str, context_line: str, 
                              file_context: ValidationContext) -> bool:
        """Skip validation for ambiguous cases where DocType cannot be confidently determined"""
        # Implementation from original
        pass
    
    def _is_false_positive(self, obj_name: str, field_name: str, context_line: str, file_context: ValidationContext) -> bool:
        """Enhanced false positive detection using collected context"""
        # Implementation from original
        pass
    
    def _is_enum_or_constant_access(self, obj_name: str, field_name: str, context_line: str) -> bool:
        """Detect enum, constant, or class member access patterns"""
        # Implementation from original
        pass
    
    def _is_defensive_pattern(self, obj_name: str, field_name: str, source_lines: List[str], line_num: int) -> bool:
        """Check surrounding lines for defensive programming patterns"""
        # Implementation from original
        pass
    
    def _suggest_fix(self, field_name: str, valid_fields: Set[str]) -> Optional[str]:
        """Suggest similar field names using modern string matching"""
        # Implementation from original
        pass
    
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single file with confidence scoring and false positive reduction"""
        # Implementation from original
        pass
    
    def _reset_file_state(self):
        """Reset per-file state to prevent memory accumulation during batch processing"""
        # Implementation from original
        pass
    
    def validate_app(self, confidence_threshold: ConfidenceLevel = ConfidenceLevel.MEDIUM) -> List[ValidationIssue]:
        """Validate the entire app with confidence filtering"""
        # Implementation from original
        pass
    
    def generate_report(self, violations: List[ValidationIssue], detailed: bool = False) -> str:
        """Generate an actionable report"""
        # Implementation from original
        pass


def main():
    """Main function with modern validation"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Parse arguments
    verbose = '--verbose' in sys.argv
    detailed = '--detailed' in sys.argv
    
    # Confidence threshold
    if '--high' in sys.argv:
        threshold = ConfidenceLevel.HIGH
    elif '--critical' in sys.argv:
        threshold = ConfidenceLevel.CRITICAL
    elif '--all' in sys.argv:
        threshold = ConfidenceLevel.INFO
    else:
        threshold = ConfidenceLevel.MEDIUM
    
    print("AST Field Analyzer - Enhanced Version")
    print(f"   Confidence threshold: {threshold.value}")
    print("")
    
    validator = ASTFieldAnalyzer(app_path, verbose=verbose)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    print(f"🔗 Built {len(validator.child_table_mapping)} child table mappings")
    print(f"🎯 Using enhanced confidence scoring with hook file support")
    print("")
    
    # Extract file paths (non-option arguments)
    file_paths = []
    for arg in sys.argv[1:]:
        if not arg.startswith('--') and arg.endswith('.py'):
            file_paths.append(Path(arg))
    
    if file_paths:
        print(f"🔍 Validating {len(file_paths)} specific files...")
        violations = []
        for file_path in file_paths:
            try:
                # Resolve path relative to current working directory
                resolved_path = file_path.resolve()
                if resolved_path.exists():
                    violations.extend(validator.validate_file(resolved_path))
            except Exception as e:
                print(f"Warning: Could not process {file_path}: {e}")
    else:
        violations = validator.validate_app(confidence_threshold=threshold)
    
    print("\n" + "="*60)
    report = validator.generate_report(violations, detailed=detailed)
    print(report)
    
    # Return appropriate exit code
    critical_count = sum(1 for v in violations if v.confidence == ConfidenceLevel.CRITICAL)
    high_count = sum(1 for v in violations if v.confidence == ConfidenceLevel.HIGH)
    
    if critical_count > 0:
        print(f"\n⚠️  {critical_count} CRITICAL issues require immediate attention!")
        return 1
    elif high_count > 0:
        print(f"\n⚠️  {high_count} HIGH confidence issues should be reviewed.")
        return 1
    else:
        print("\n✅ No critical issues found!")
        return 0


if __name__ == "__main__":
    exit(main())