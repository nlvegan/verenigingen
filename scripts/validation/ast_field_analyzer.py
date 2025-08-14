#!/usr/bin/env python3
"""
AST Field Analyzer - Advanced Code Analysis for Field Reference Validation
Ultra-precise field validation using sophisticated Abstract Syntax Tree analysis

ENHANCED VERSION with:
- Unified DocType loader integration
- Advanced confidence scoring system
- Enhanced false positive reduction
- Modernized AST analysis techniques
- Context-aware validation
- Performance optimizations
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

# Import unified DocType loader - secure import without modifying sys.path
try:
    from .doctype_loader import load_doctypes_detailed
except ImportError:
    # Fallback for direct script execution
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    try:
        from doctype_loader import load_doctypes_detailed
    finally:
        # Clean up sys.path modification
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
    """Advanced AST-based field reference analyzer with sophisticated detection logic"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.verbose = verbose
        # Use unified DocType loader for enhanced accuracy
        self.doctypes = load_doctypes_detailed(str(self.app_path), verbose=False)
        self.child_table_mapping = self._build_child_table_mapping()
        self.issues = []
        
        # Build comprehensive patterns
        self.excluded_patterns = self._build_excluded_patterns()
        self.framework_patterns = self._build_framework_patterns()
        self.test_patterns = self._build_test_patterns()
        self.doctype_name_patterns = self._build_doctype_name_patterns()
        
        # Enhanced tracking for false positive reduction
        self.iteration_variables = set()  # Track loop/comprehension variables
        self.function_parameters = {}     # Track function parameter -> expected DocType mapping
        self.child_table_vars = {}       # Track variables that represent child table records
        self.dynamic_variables = {}      # Track variables assigned from function calls
        
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
        # Start with basic mappings
        patterns = {
            'member': 'Member',
            'membership': 'Membership',
            'volunteer': 'Volunteer',
            'chapter': 'Chapter',
            'team': 'Team',
            'team_member': 'Team Member',
            'expense': 'Volunteer Expense',
            'mandate': 'SEPA Mandate',
            'batch': 'Direct Debit Batch',
            'payment': 'Payment Plan',
            'invoice': 'Sales Invoice',
            'sales_invoice': 'Sales Invoice',
            'donation': 'Donation',
            'donation_campaign': 'Donation Campaign',
            'application': 'Membership Application',
            'termination': 'Membership Termination Request',
            'termination_request': 'Membership Termination Request',
            'schedule': 'Membership Dues Schedule',
            'board_member': 'Chapter Board Member',
            'contact_request': 'Member Contact Request',
            'contribution': 'Contribution Amendment Request',
            'sepa_mandate': 'SEPA Mandate',
            'direct_debit': 'Direct Debit Batch',
            'payment_plan': 'Payment Plan',
            'volunteer_expense': 'Volunteer Expense',
            'membership_type': 'Membership Type',
            'chapter_member': 'Chapter Member',
            'volunteer_skill': 'Volunteer Skill',
            'volunteer_availability': 'Volunteer Availability',
            'member_payment': 'Member Payment History',
            'payment_history': 'Member Payment History',
        }
        
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
    
    def get_doctype_stats(self) -> Dict[str, int]:
        """Get statistics about loaded DocTypes from unified loader"""
        stats = {
            'total_doctypes': len(self.doctypes),
            'child_tables': len(self.child_table_mapping),
            'total_fields': sum(len(dt.get('fields', set())) for dt in self.doctypes.values()),
            'custom_fields': sum(dt.get('custom_fields_count', 0) for dt in self.doctypes.values())
        }
        return stats
    
    def _get_enhanced_field_suggestions(self, doctype_name: str, invalid_field: str) -> List[str]:
        """Get enhanced field suggestions using unified loader data"""
        if doctype_name not in self.doctypes:
            return []
        
        doctype_info = self.doctypes[doctype_name]
        available_fields = list(doctype_info.get('fields', set()))
        
        # Use difflib for better suggestions
        suggestions = difflib.get_close_matches(invalid_field, available_fields, n=5, cutoff=0.6)
        return suggestions
    
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
    
    def _enhance_confidence_scoring(self, issue: ValidationIssue, context: ValidationContext) -> ConfidenceLevel:
        """Enhanced confidence scoring with modern heuristics"""
        confidence_score = 0.5  # Start at medium
        
        # High confidence indicators
        if issue.reference in ['frappe.db.get_value', 'frappe.db.set_value', 'frappe.get_doc']:
            confidence_score += 0.3
        
        if issue.doctype in self.doctypes and issue.field not in self.doctypes[issue.doctype].get('fields', set()):
            confidence_score += 0.2
            
        # Medium confidence indicators
        if context.function_name and 'test' not in context.function_name.lower():
            confidence_score += 0.1
            
        if not context.is_test_file:
            confidence_score += 0.1
            
        # Low confidence indicators (reduce score)
        if context.is_migration or context.is_test_file:
            confidence_score -= 0.2
            
        if issue.field in ['field', 'value', 'data', 'item']:  # Generic names
            confidence_score -= 0.2
            
        # Convert score to confidence level using constants
        if confidence_score >= ConfidenceThresholds.CRITICAL:
            return ConfidenceLevel.CRITICAL
        elif confidence_score >= ConfidenceThresholds.HIGH:
            return ConfidenceLevel.HIGH
        elif confidence_score >= ConfidenceThresholds.MEDIUM:
            return ConfidenceLevel.MEDIUM
        elif confidence_score >= ConfidenceThresholds.LOW:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.INFO
    
    def analyze_file_context(self, tree: ast.AST, file_path: Path) -> ValidationContext:
        """Analyze entire file context for better understanding"""
        context = ValidationContext()
        
        # Check if it's a test file
        file_str = str(file_path)
        context.is_test_file = any(pattern in file_str for pattern in [
            '/test_', '/tests/', '_test.py', 'test.py'
        ])
        
        # Check if it's a migration
        context.is_migration = '/migrations/' in file_str or '/patches/' in file_str
        
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
    
    def calculate_confidence(self, issue: ValidationIssue, context: ValidationContext) -> ConfidenceLevel:
        """Calculate confidence level for an issue based on multiple factors"""
        confidence_score = 50  # Start at medium
        
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
            
        if issue.field in self.excluded_patterns['common_attributes']:
            confidence_score -= 40
        
        # Check for legacy or dynamic fields
        if self._is_likely_legacy_or_dynamic_field(issue.field, issue.doctype):
            confidence_score -= 50
        
        # Check if it looks like a method call
        if '()' in issue.context or f'{issue.field}(' in issue.context:
            confidence_score -= 35
        
        # Map score to confidence level
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
    
    def is_excluded_pattern(self, obj_name: str, field_name: str, context_line: str, 
                           file_context: ValidationContext) -> bool:
        """Modernized exclusion checking with context awareness"""
        
        # Skip test assertions
        if file_context.is_test_file:
            if any(assert_method in context_line for assert_method in [
                'assertEqual', 'assertTrue', 'assertFalse', 'assertIn'
            ]):
                return True
        
        # Check all exclusion categories
        for category in self.excluded_patterns.values():
            if field_name in category:
                return True
        
        # Skip method calls
        if f'{field_name}(' in context_line or f'.{field_name}()' in context_line:
            return True
        
        # Skip assignments (setting attributes)
        if f'{obj_name}.{field_name} =' in context_line:
            return True
        
        # Skip private/protected attributes
        if field_name.startswith('_'):
            return True
        
        # Skip if object name suggests non-DocType
        non_doctype_vars = {
            'f', 'file', 'fp', 'data', 'result', 'response', 'request', 'settings',
            'config', 'options', 'params', 'args', 'kwargs', 'obj', 'item', 'element',
            'node', 'tree', 'root', 'parent', 'child', 'sibling', 'next', 'prev',
            'json_file', 'meta', 'self', 'template', 'ctx', 'context', 'ret', 'res',
            'val', 'value', 'key', 'attr', 'prop', 'property', 'field_meta'
        }
        
        if obj_name in non_doctype_vars:
            return True
        
        # Skip if it's accessing a module
        if obj_name in file_context.imported_modules:
            return True
        
        return False
    
    def detect_doctype_with_modern_logic(self, node: ast.Attribute, source_lines: List[str],
                                        file_context: ValidationContext) -> Optional[str]:
        """Modern DocType detection with multiple strategies and confidence"""
        
        obj_name = node.value.id if hasattr(node.value, 'id') else None
        if not obj_name:
            return None
        
        line_num = node.lineno
        
        # Strategy 1: Direct variable assignment tracking (most accurate)
        assignment_doctype = self._track_variable_assignment(obj_name, source_lines, line_num)
        if assignment_doctype:
            return assignment_doctype
        
        # Strategy 2: Child table iteration patterns
        child_doctype = self._detect_child_table_iteration(obj_name, source_lines, line_num)
        if child_doctype:
            return child_doctype
        
        # Strategy 3: Function parameter analysis
        if obj_name in ['doc', 'self']:
            param_doctype = self._analyze_function_parameters(source_lines, line_num, file_context)
            if param_doctype:
                return param_doctype
        
        # Strategy 4: Enhanced variable name mapping
        mapped_doctype = self._map_variable_to_doctype(obj_name)
        if mapped_doctype:
            return mapped_doctype
        
        # Strategy 5: Context-based inference
        inferred_doctype = self._infer_from_context(obj_name, source_lines, line_num, file_context)
        if inferred_doctype:
            return inferred_doctype
        
        return None
    
    def _track_variable_assignment(self, var_name: str, lines: List[str], current_line: int, depth: int = 0) -> Optional[str]:
        """Track variable assignments to determine DocType with enhanced recursion protection"""
        
        # First check dynamic variables collected during AST parsing (highest priority)
        if var_name in self.dynamic_variables:
            return self.dynamic_variables[var_name]
        
        # Enhanced recursion protection
        MAX_RECURSION_DEPTH = 5  # Reduced from 10 for better safety
        MAX_SEARCH_RANGE = 30    # Reduced search range to prevent excessive processing
        
        if depth > MAX_RECURSION_DEPTH:
            if self.verbose:
                print(f"  ⚠️ Recursion depth limit reached for variable tracking: {var_name}")
            return None
            
        # Additional protection against stack overflow
        try:
            import sys
            if sys.getrecursionlimit() - len(sys._current_frames()) < 50:
                if self.verbose:
                    print(f"  ⚠️ Stack space low, stopping variable tracking: {var_name}")
                return None
        except (AttributeError, RuntimeError):
            # Fallback if stack inspection fails
            pass
            
        # Look backwards for assignment with limited range
        search_range = range(max(0, current_line - MAX_SEARCH_RANGE), current_line)
        
        patterns = [
            (rf'{var_name}\s*=\s*frappe\.get_doc\(\s*["\']([^"\']+)["\']', 1),
            (rf'{var_name}\s*=\s*frappe\.new_doc\(\s*["\']([^"\']+)["\']', 1),
            (rf'{var_name}\s*=\s*self\.get_doc\(\s*["\']([^"\']+)["\']', 1),
            (rf'{var_name}\s*=\s*get_doc\(\s*["\']([^"\']+)["\']', 1),
            (rf'{var_name}\s*=\s*.*\.get\(\s*["\']([^"\']+)["\']', 1),
            # Handle variable assignment from another variable
            (rf'{var_name}\s*=\s*(\w+)(?:\[.*\])?$', 1),
        ]
        
        for i in search_range:
            if i < len(lines):
                line = lines[i]
                for pattern, group_idx in patterns:
                    match = re.search(pattern, line)
                    if match:
                        result = match.group(group_idx)
                        if result in self.doctypes:
                            return result
                        # If it's another variable, recursively track it
                        elif result != var_name and result.isidentifier():
                            return self._track_variable_assignment(result, lines, i, depth + 1)
        
        return None
    
    def _detect_child_table_iteration(self, var_name: str, lines: List[str], current_line: int) -> Optional[str]:
        """Detect child table iteration patterns"""
        
        # Look for iteration patterns
        search_range = range(max(0, current_line - 10), min(len(lines), current_line + 3))
        context = '\n'.join(lines[i] for i in search_range if i < len(lines))
        
        patterns = [
            rf'for\s+{var_name}\s+in\s+(\w+)\.(\w+):',
            rf'{var_name}\s*=\s*(\w+)\.(\w+)\[',
            rf'for\s+{var_name}\s+in\s+self\.(\w+):',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                if len(match.groups()) == 2:
                    parent_var = match.group(1)
                    child_field = match.group(2)
                    
                    # Look up in child table mapping
                    for key, child_doctype in self.child_table_mapping.items():
                        if key.endswith(f'.{child_field}'):
                            return child_doctype
                else:
                    # Single field access on self
                    field_name = match.group(1)
                    # Check if this field is a child table field
                    for doctype_info in self.doctypes.values():
                        for child_field, child_doctype in doctype_info.get('child_tables', []):
                            if child_field == field_name:
                                return child_doctype
        
        return None
    
    def _analyze_function_parameters(self, lines: List[str], current_line: int, 
                                    file_context: ValidationContext) -> Optional[str]:
        """Analyze function parameters to determine DocType"""
        
        # Find the containing function
        for i in range(current_line - 1, max(0, current_line - 100), -1):
            line = lines[i].strip()
            
            # Check for function definition
            if line.startswith('def '):
                func_match = re.match(r'def\s+(\w+)\s*\(', line)
                if func_match:
                    func_name = func_match.group(1)
                    
                    # Map validation function names to DocTypes
                    validation_mappings = {
                        'validate_member': 'Member',
                        'validate_membership': 'Membership',
                        'validate_volunteer': 'Volunteer',
                        'validate_chapter': 'Chapter',
                        'validate_team': 'Team',
                        'validate_team_member': 'Team Member',
                        'validate_expense': 'Volunteer Expense',
                        'validate_mandate': 'SEPA Mandate',
                        'validate_payment': 'Payment Plan',
                        'validate_donation': 'Donation',
                        'validate_application': 'Membership Application',
                        'validate_termination': 'Membership Termination Request',
                        'validate_termination_request': 'Membership Termination Request',
                        'validate_schedule': 'Membership Dues Schedule',
                        'validate_contribution': 'Contribution Amendment Request',
                        'on_update_member': 'Member',
                        'after_insert_membership': 'Membership',
                        'before_save_volunteer': 'Volunteer',
                    }
                    
                    if func_name in validation_mappings:
                        return validation_mappings[func_name]
                    
                    # Try to infer from function name patterns
                    for prefix in ['validate_', 'on_update_', 'after_insert_', 'before_save_']:
                        if func_name.startswith(prefix):
                            potential_doctype = func_name[len(prefix):].replace('_', ' ').title()
                            if potential_doctype in self.doctypes:
                                return potential_doctype
                    
                    # Check if function has doctype hints
                    if file_context.doctype_hints:
                        # Return the most likely hint
                        return next(iter(file_context.doctype_hints), None)
        
        return None
    
    def _map_variable_to_doctype(self, var_name: str) -> Optional[str]:
        """Map variable names to DocTypes using comprehensive patterns"""
        
        # Check direct mapping
        if var_name in self.doctype_name_patterns:
            doctype = self.doctype_name_patterns[var_name]
            if doctype in self.doctypes:
                return doctype
        
        # Try case-insensitive matching
        var_lower = var_name.lower()
        for pattern, doctype in self.doctype_name_patterns.items():
            if pattern.lower() == var_lower and doctype in self.doctypes:
                return doctype
        
        # Try partial matching for compound names
        if '_' in var_name:
            parts = var_name.split('_')
            # Try different combinations
            for i in range(len(parts)):
                for j in range(i + 1, len(parts) + 1):
                    partial = '_'.join(parts[i:j])
                    if partial in self.doctype_name_patterns:
                        doctype = self.doctype_name_patterns[partial]
                        if doctype in self.doctypes:
                            return doctype
        
        return None
    
    def _infer_from_context(self, var_name: str, lines: List[str], current_line: int,
                           file_context: ValidationContext) -> Optional[str]:
        """Infer DocType from surrounding context"""
        
        # Look for nearby DocType references
        context_range = range(max(0, current_line - 10), min(len(lines), current_line + 10))
        
        for i in context_range:
            if i < len(lines):
                line = lines[i]
                # Look for DocType string literals
                for doctype in self.doctypes.keys():
                    if f'"{doctype}"' in line or f"'{doctype}'" in line:
                        # Check if it's related to our variable
                        if var_name in line:
                            return doctype
        
        # If in validation context, check hints
        if file_context.is_validation_hook and file_context.doctype_hints:
            return next(iter(file_context.doctype_hints), None)
        
        return None
    
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single file with modern detection logic and false positive reduction"""
        violations = []
        
        # Input validation and safety checks
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB limit to prevent memory issues
        
        try:
            # Validate file path
            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                return violations
                
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                logger.warning(f"File too large ({file_size} bytes), skipping: {file_path}")
                if self.verbose:
                    print(f"  ⚠️ Skipping large file: {file_path}")
                return violations
            
            if file_size == 0:
                # Empty file, nothing to analyze
                return violations
            
            # Safe file reading with encoding detection
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Try with different encodings
                for encoding in ['latin-1', 'cp1252', 'utf-8-sig']:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            content = f.read()
                        logger.info(f"Successfully read {file_path} with {encoding} encoding")
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    # If all encodings fail, skip the file
                    logger.error(f"Could not decode file with any encoding: {file_path}")
                    return violations
            
            # Parse AST
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Reset per-file state to prevent memory accumulation
            self._reset_file_state()
            
            # First pass: collect variable context to reduce false positives
            context_visitor = VariableContextVisitor()
            context_visitor.visit(tree)
            
            # Update tracking data from context (per-file only)
            self.iteration_variables.update(context_visitor.iteration_vars)
            self.function_parameters.update(context_visitor.function_params)
            self.child_table_vars.update(context_visitor.child_table_vars)
            self.dynamic_variables.update(context_visitor.dynamic_vars)
            
            # Analyze file context
            file_context = self.analyze_file_context(tree, file_path)
            
            # Walk through AST nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if not hasattr(node.value, 'id'):
                        continue
                        
                    obj_name = node.value.id
                    field_name = node.attr
                    line_num = node.lineno
                    
                    # Get line context
                    context_line = source_lines[line_num - 1].strip() if 1 <= line_num <= len(source_lines) else ""
                    
                    # Enhanced false positive detection
                    if self._is_false_positive(obj_name, field_name, context_line, file_context):
                        continue
                    
                    # Check for defensive programming patterns
                    if self._is_defensive_pattern(obj_name, field_name, source_lines, line_num):
                        if self.verbose:
                            print(f"  ✓ Skipped defensive programming pattern: {obj_name}.{field_name}")
                        continue
                    
                    # Skip excluded patterns
                    if self.is_excluded_pattern(obj_name, field_name, context_line, file_context):
                        continue
                    
                    # Detect DocType with modern logic
                    doctype = self.detect_doctype_with_modern_logic(node, source_lines, file_context)
                    
                    if doctype and doctype in self.doctypes:
                        doctype_info = self.doctypes[doctype]
                        fields = doctype_info['fields']
                        
                        if field_name not in fields:
                            # Create issue
                            issue = ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"{obj_name}.{field_name}",
                                message=f"Field '{field_name}' does not exist in {doctype}",
                                context=context_line,
                                confidence=ConfidenceLevel.MEDIUM,
                                issue_type="missing_field",
                                suggested_fix=self._suggest_fix(field_name, fields)
                            )
                            
                            # Calculate confidence
                            issue.confidence = self.calculate_confidence(issue, file_context)
                            
                            # Only include high-confidence issues by default
                            if issue.confidence in [ConfidenceLevel.CRITICAL, ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]:
                                violations.append(issue)
        
        except SyntaxError as e:
            error_msg = f"Syntax error in {file_path} at line {e.lineno}: {e.msg}"
            logger.error(error_msg)
            if self.verbose:
                print(f"  ❌ Syntax error: {error_msg}")
        except UnicodeDecodeError as e:
            error_msg = f"Unicode decode error in {file_path}: {e}"
            logger.error(error_msg)
            if self.verbose:
                print(f"  ❌ Encoding error: {file_path} (skipped)")
        except RecursionError as e:
            error_msg = f"Recursion limit exceeded in {file_path}: {e}"
            logger.error(error_msg)
            if self.verbose:
                print(f"  ⚠️ Recursion error: {file_path} (analysis truncated)")
        except MemoryError as e:
            error_msg = f"Memory error processing {file_path}: {e}"
            logger.critical(error_msg)
            if self.verbose:
                print(f"  💥 Memory error: {file_path} (skipped)")
        except Exception as e:
            error_msg = f"Unexpected error processing {file_path}: {type(e).__name__}: {e}"
            logger.error(error_msg)
            if self.verbose:
                print(f"  ❌ Error: {error_msg}")
                print(f"     Traceback: {traceback.format_exc()}")
        
        return violations
    
    def _reset_file_state(self):
        """Reset per-file state to prevent memory accumulation during batch processing"""
        self.iteration_variables.clear()
        # Keep function_parameters as it's useful across files for pattern recognition
        self.child_table_vars.clear()
        self.dynamic_variables.clear()
    
    def _is_false_positive(self, obj_name: str, field_name: str, context_line: str, file_context: ValidationContext) -> bool:
        """Enhanced false positive detection using collected context"""
        
        # 1. Skip iteration variables from loops and comprehensions
        if obj_name in self.iteration_variables:
            if self.verbose:
                print(f"  ✓ Skipped iteration variable: {obj_name}.{field_name}")
            return True
        
        # 2. Skip function parameters (unless we have specific DocType context)
        for func_params in self.function_parameters.values():
            if obj_name in func_params:
                # Check if we have specific DocType context for this parameter
                if obj_name not in self.dynamic_variables:
                    if self.verbose:
                        print(f"  ✓ Skipped function parameter: {obj_name}.{field_name}")
                    return True
        
        # 3. Skip child table variables
        if obj_name in self.child_table_vars:
            if self.verbose:
                print(f"  ✓ Skipped child table variable: {obj_name}.{field_name}")
            return True
        
        # 4. Skip common iteration patterns in list comprehensions
        if re.search(rf'\b{re.escape(obj_name)}\s+for\s+{re.escape(obj_name)}\s+in\b', context_line):
            if self.verbose:
                print(f"  ✓ Skipped comprehension pattern: {obj_name}.{field_name}")
            return True
        
        # 5. Skip variables with common iteration names
        if obj_name in ['d', 'item', 'row', 'entry', 'record', 'line', 'r', 'i', 'x']:
            # These are commonly used in iterations
            if any(pattern in context_line.lower() for pattern in ['for ', ' in ', 'sum(', 'map(', 'filter(']):
                if self.verbose:
                    print(f"  ✓ Skipped common iteration variable: {obj_name}.{field_name}")
                return True
        
        # 6. Skip obvious method calls on built-in types
        if field_name in ['append', 'extend', 'remove', 'pop', 'clear', 'keys', 'values', 'items', 
                         'get', 'update', 'split', 'join', 'strip', 'replace', 'format']:
            if self.verbose:
                print(f"  ✓ Skipped built-in method: {obj_name}.{field_name}")
            return True
        
        # 7. Skip access to attributes that are commonly child table records
        if re.search(rf'for\s+{re.escape(obj_name)}\s+in\s+\w+\.\w+', context_line):
            # Pattern: for item in self.items:
            if self.verbose:
                print(f"  ✓ Skipped child table iteration: {obj_name}.{field_name}")
            return True
        
        # 8. Skip variables that are clearly database query results
        if re.search(rf'{re.escape(obj_name)}\s*=.*frappe\.(db\.)?get_', context_line):
            # These are database results, not DocType objects
            if self.verbose:
                print(f"  ✓ Skipped database query result: {obj_name}.{field_name}")
            return True
        
        # 9. Skip defensive hasattr() checks
        if f'hasattr({obj_name}, "{field_name}")' in context_line or f"hasattr({obj_name}, '{field_name}')" in context_line:
            if self.verbose:
                print(f"  ✓ Skipped defensive hasattr() check: {obj_name}.{field_name}")
            return True
        
        # 10. Skip getattr() with fallback patterns  
        if f'getattr({obj_name}, "{field_name}"' in context_line or f"getattr({obj_name}, '{field_name}'" in context_line:
            if self.verbose:
                print(f"  ✓ Skipped getattr() with fallback: {obj_name}.{field_name}")
            return True
        
        # 11. Skip field access inside conditional hasattr checks
        # Pattern: if hasattr(obj, 'field'): obj.field
        if re.search(rf'if\s+hasattr\s*\(\s*{re.escape(obj_name)}\s*,\s*["\']?{re.escape(field_name)}["\']?\s*\)', context_line):
            if self.verbose:
                print(f"  ✓ Skipped conditional hasattr access: {obj_name}.{field_name}")
            return True
        
        return False
    
    def _is_defensive_pattern(self, obj_name: str, field_name: str, source_lines: List[str], line_num: int) -> bool:
        """Check surrounding lines for defensive programming patterns"""
        
        # Check current line and a few lines before/after for defensive patterns
        start_line = max(0, line_num - 3)
        end_line = min(len(source_lines), line_num + 2)
        
        surrounding_context = '\n'.join(source_lines[start_line:end_line])
        
        # Pattern 1: hasattr check followed by field access
        hasattr_pattern = rf'hasattr\s*\(\s*{re.escape(obj_name)}\s*,\s*["\']?{re.escape(field_name)}["\']?\s*\)'
        if re.search(hasattr_pattern, surrounding_context, re.IGNORECASE):
            return True
        
        # Pattern 2: try/except around field access
        try_except_pattern = rf'try\s*:.*{re.escape(obj_name)}\.{re.escape(field_name)}.*except'
        if re.search(try_except_pattern, surrounding_context, re.DOTALL | re.IGNORECASE):
            return True
        
        # Pattern 3: getattr with default value
        getattr_pattern = rf'getattr\s*\(\s*{re.escape(obj_name)}\s*,\s*["\']?{re.escape(field_name)}["\']?\s*,'
        if re.search(getattr_pattern, surrounding_context, re.IGNORECASE):
            return True
        
        # Pattern 4: Field used in conditional check (might be dynamic/computed)
        if_pattern = rf'if\s+{re.escape(obj_name)}\.{re.escape(field_name)}\s*:'
        if re.search(if_pattern, surrounding_context, re.IGNORECASE):
            return True
        
        # Pattern 5: Field used in conditional check with not
        if_not_pattern = rf'if\s+not\s+{re.escape(obj_name)}\.{re.escape(field_name)}\s*:'
        if re.search(if_not_pattern, surrounding_context, re.IGNORECASE):
            return True
        
        return False
    
    def _suggest_fix(self, field_name: str, valid_fields: Set[str]) -> Optional[str]:
        """Suggest similar field names using modern string matching"""
        
        # Use difflib for better matching
        close_matches = difflib.get_close_matches(field_name, valid_fields, n=3, cutoff=0.6)
        
        if close_matches:
            return f"Did you mean: {', '.join(close_matches)}?"
        
        # Try substring matching
        field_lower = field_name.lower()
        substring_matches = [f for f in valid_fields if field_lower in f.lower() or f.lower() in field_lower]
        
        if substring_matches:
            return f"Similar fields: {', '.join(substring_matches[:3])}"
        
        return None
    
    def validate_app(self, confidence_threshold: ConfidenceLevel = ConfidenceLevel.MEDIUM) -> List[ValidationIssue]:
        """Validate the entire app with confidence filtering"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning Python files in {self.app_path} with modern detection logic...")
        
        # Define confidence priority
        confidence_priority = {
            ConfidenceLevel.CRITICAL: 5,
            ConfidenceLevel.HIGH: 4,
            ConfidenceLevel.MEDIUM: 3,
            ConfidenceLevel.LOW: 2,
            ConfidenceLevel.INFO: 1
        }
        
        threshold_value = confidence_priority[confidence_threshold]
        
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip certain directories
            if any(skip in str(py_file) for skip in [
                'node_modules', '__pycache__', '.git', 'migrations',
                'archived_unused', 'backup', '.disabled', 'patches'
            ]):
                continue
            
            files_checked += 1
            file_violations = self.validate_file(py_file)
            
            # Filter by confidence threshold
            filtered_violations = [
                v for v in file_violations 
                if confidence_priority.get(v.confidence, 0) >= threshold_value
            ]
            
            if filtered_violations:
                print(f"  - Found {len(filtered_violations)} issues in {py_file.relative_to(self.app_path)}")
            
            violations.extend(filtered_violations)
        
        print(f"📊 Checked {files_checked} Python files")
        return violations
    
    def generate_report(self, violations: List[ValidationIssue], detailed: bool = False) -> str:
        """Generate a modern, actionable report"""
        if not violations:
            return "✅ No field reference issues found with modern detection!"
        
        report = []
        report.append(f"📊 Field Validation Report (Modern Detection)")
        report.append(f"{'='*60}")
        report.append(f"Total issues found: {len(violations)}")
        report.append("")
        
        # Group by confidence level
        by_confidence = {}
        for v in violations:
            by_confidence.setdefault(v.confidence, []).append(v)
        
        # Report by confidence level
        for confidence in [ConfidenceLevel.CRITICAL, ConfidenceLevel.HIGH, 
                          ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW, ConfidenceLevel.INFO]:
            if confidence in by_confidence:
                issues = by_confidence[confidence]
                report.append(f"\n{confidence.value.upper()} Confidence ({len(issues)} issues):")
                report.append("-" * 40)
                
                # Show sample issues
                sample_size = 5 if not detailed else len(issues)
                for issue in issues[:sample_size]:
                    report.append(f"  📍 {issue.file}:{issue.line}")
                    report.append(f"     Field: {issue.field} not in {issue.doctype}")
                    if issue.suggested_fix:
                        report.append(f"     💡 {issue.suggested_fix}")
                    report.append(f"     Context: {issue.context[:80]}...")
                    report.append("")
                
                if len(issues) > sample_size:
                    report.append(f"  ... and {len(issues) - sample_size} more\n")
        
        # Summary statistics
        report.append("\n📈 Summary Statistics:")
        report.append("-" * 40)
        
        # Group by DocType
        by_doctype = {}
        for v in violations:
            by_doctype.setdefault(v.doctype, 0)
            by_doctype[v.doctype] += 1
        
        top_doctypes = sorted(by_doctype.items(), key=lambda x: x[1], reverse=True)[:5]
        report.append("Top affected DocTypes:")
        for doctype, count in top_doctypes:
            report.append(f"  - {doctype}: {count} issues")
        
        return '\n'.join(report)


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
    
    print("🚀 AST Field Analyzer - Advanced Code Analysis")
    print(f"   Confidence threshold: {threshold.value}")
    print("")
    
    validator = ASTFieldAnalyzer(app_path, verbose=verbose)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    print(f"🔗 Built {len(validator.child_table_mapping)} child table mappings")
    print(f"🎯 Using modern detection logic with confidence scoring")
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
        print("\n✅ No critical issues found with modern detection!")
        return 0


if __name__ == "__main__":
    exit(main())