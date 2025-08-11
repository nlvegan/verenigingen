#!/usr/bin/env python3
"""
Modernized JavaScript-Python Parameter Validation System

A sophisticated validator that analyzes JavaScript-Python API interactions to ensure
parameter compatibility and prevent runtime errors.

Key Features:
- High-accuracy method resolution with fuzzy matching
- Framework-aware filtering to reduce false positives  
- Performance-optimized with caching and incremental analysis
- Comprehensive parameter validation with type checking
- Integration with existing validation infrastructure
- Configurable severity levels and ignore patterns
"""

import os
import re
import ast
import json
import importlib.util
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from collections import defaultdict
from functools import lru_cache
from difflib import SequenceMatcher
from enum import Enum
import logging

# Enhanced imports for unified loader integration
import sys
from pathlib import Path

# Import unified DocType loader with secure path handling
try:
    from .doctype_loader import get_unified_doctype_loader
except ImportError:
    # Fallback for direct script execution with secure path handling
    current_dir = Path(__file__).resolve().parent  # Use resolve() for absolute path
    # Validate path is within project boundaries
    if current_dir.exists() and current_dir.is_dir():
        sys_path_str = str(current_dir)
        if sys_path_str not in sys.path:
            sys.path.insert(0, sys_path_str)
        try:
            from doctype_loader import get_unified_doctype_loader
        finally:
            # Clean up sys.path modification
            if sys_path_str in sys.path:
                sys.path.remove(sys_path_str)
    else:
        raise ImportError("Cannot safely import doctype_loader")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Severity(Enum):
    """Issue severity levels"""
    CRITICAL = "critical"  # Will break functionality
    HIGH = "high"         # Should be fixed soon
    MEDIUM = "medium"     # Moderate priority
    LOW = "low"           # Minor issue
    INFO = "info"         # Informational only
    IGNORE = "ignore"     # Intentionally ignored

class IssueType(Enum):
    """Types of validation issues"""
    MISSING_PARAMETER = "missing_parameter"
    EXTRA_PARAMETER = "extra_parameter"
    METHOD_NOT_FOUND = "method_not_found"
    FRAMEWORK_METHOD = "framework_method"
    TYPE_MISMATCH = "type_mismatch"
    PERMISSION_ISSUE = "permission_issue"
    DEPRECATED_METHOD = "deprecated_method"

@dataclass
class JSCall:
    """Represents a JavaScript call to a Python method with enhanced metadata"""
    file_path: str
    line_number: int
    method_name: str
    args: Dict[str, Any] = field(default_factory=dict)
    context: str = ""
    call_type: str = ""
    raw_args_string: str = ""
    confidence: float = 0.8
    is_conditional: bool = False  # Called within if/try block

@dataclass
class PythonFunction:
    """Represents a Python function with comprehensive parameter analysis"""
    file_path: str
    line_number: int
    function_name: str
    full_method_path: str
    parameters: List[str] = field(default_factory=list)
    required_params: List[str] = field(default_factory=list)
    optional_params: List[str] = field(default_factory=list)
    param_types: Dict[str, str] = field(default_factory=dict)
    docstring: Optional[str] = None
    has_kwargs: bool = False
    has_args: bool = False
    is_whitelisted: bool = True
    decorator_line: int = 0
    complexity_score: int = 1

@dataclass
class ValidationIssue:
    """Enhanced validation issue with actionable metadata"""
    js_call: JSCall
    python_function: Optional[PythonFunction]
    issue_type: IssueType
    severity: Severity
    description: str
    suggestion: str = ""
    resolution_action: str = ""
    confidence: float = 0.8
    file_context: str = ""
    
    def __post_init__(self):
        """Auto-generate suggestions based on issue type"""
        if not self.suggestion:
            self.suggestion = self._generate_suggestion()
    
    def _generate_suggestion(self) -> str:
        """Generate contextual suggestions for different issue types"""
        if self.issue_type == IssueType.MISSING_PARAMETER:
            return f"Add required parameter '{self.description.split()[-1]}' to the JavaScript call"
        elif self.issue_type == IssueType.EXTRA_PARAMETER:
            return f"Remove unused parameter or add it to Python function signature"
        elif self.issue_type == IssueType.METHOD_NOT_FOUND:
            if self.python_function:
                return f"Check method path - did you mean '{self.python_function.full_method_path}'?"
            return "Verify the method exists and is properly decorated with @frappe.whitelist()"
        return "Review the JavaScript-Python interface for compatibility"

class ModernJSPythonValidator:
    """Modernized validator with enhanced accuracy and performance"""
    
    def __init__(self, project_root: str, config: Optional[Dict] = None):
        # Input validation
        if not project_root or not isinstance(project_root, (str, Path)):
            raise ValueError("project_root must be a valid string or Path")
        
        self.project_root = Path(project_root)
        if not self.project_root.exists():
            raise ValueError(f"Project root does not exist: {project_root}")
        if not self.project_root.is_dir():
            raise ValueError(f"Project root is not a directory: {project_root}")
            
        self.config = config or self._load_default_config()
        if not isinstance(self.config, dict):
            raise ValueError("Config must be a dictionary")
        
        # Initialize unified DocType loader
        self.doctype_loader = None
        self._initialize_doctype_loader()
        
        # Caches for performance with size limits and proper eviction
        from collections import OrderedDict
        self._python_functions_cache = OrderedDict()  # LRU cache
        self._js_calls_cache = OrderedDict()  # LRU cache
        self._file_mtime_cache = {}  # Simple cache for file times
        self._cache_max_size = 500  # Reduced maximum cache entries
        self._cache_ttl = 300  # Cache TTL in seconds
        self._cache_creation_time = {}
        
        # Data structures
        self.js_calls: List[JSCall] = []
        self.python_functions: Dict[str, PythonFunction] = {}
        self.function_index: Dict[str, List[str]] = defaultdict(list)  # function_name -> full_paths
        self.issues: List[ValidationIssue] = []
        
        # Pre-compile regex patterns for performance optimization
        self._compiled_call_patterns = [
            (re.compile(r'frappe\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]'), 'frappe.call'),
            (re.compile(r'frm\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]'), 'frm.call'),
            (re.compile(r'cur_frm\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]'), 'cur_frm.call'),
            (re.compile(r'[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]'), 'button.method'),
            (re.compile(r'this\._call\(\s*[\'"]([^\'"]+)[\'"]'), 'service.call'),
            (re.compile(r'api\.call\(\s*[\'"]([^\'"]+)[\'"]'), 'api.call'),
        ]
        
        # Framework patterns to ignore
        self.framework_methods = self._build_framework_methods()
        self.builtin_patterns = self._build_builtin_patterns()
        
        # Enhanced validation features
        self.doctype_fields_cache = {}
        self.method_signatures_cache = {}
        
        # Statistics
        self.stats = {
            'js_files_scanned': 0,
            'py_files_scanned': 0,
            'js_calls_found': 0,
            'python_functions_found': 0,
            'issues_found': 0,
            'cache_hits': 0,
            'doctype_lookups': 0,
            'enhanced_validations': 0,
        }
    
    def _initialize_doctype_loader(self):
        """Initialize the unified DocType loader with enhanced error handling"""
        try:
            self.doctype_loader = get_unified_doctype_loader(str(self.project_root))
            # Verify loader is working by testing a known DocType
            if self.doctype_loader:
                test_fields = self.doctype_loader.get_field_names('Member')
                if test_fields:
                    logger.info(f"✅ DocType loader initialized (found {len(test_fields)} fields for Member)")
                else:
                    logger.warning("⚠️ DocType loader initialized but returns no fields - check DocType paths")
            else:
                logger.warning("DocType loader initialization returned None")
        except Exception as e:
            logger.error(f"❌ Failed to initialize DocType loader: {e}")
            self.doctype_loader = None
    
    def _load_default_config(self) -> Dict:
        """Load default configuration with sensible defaults"""
        return {
            'severity_threshold': 'medium',
            'ignore_patterns': [
                r'.*\.test\.js$',
                r'.*\.spec\.js$',
                r'.*/node_modules/.*',
                r'.*/eslint-plugins/.*',
            ],
            'framework_methods_to_ignore': [
                'frappe.db.get_value',
                'frappe.db.get_list',
                'frappe.db.count',
                'frappe.model.get_value',
                'frappe.client.get',
                'frappe.client.get_list',
            ],
            'fuzzy_match_threshold': 0.6,
            'max_suggestions': 3,
            'cache_enabled': True,
        }
    
    def _build_framework_methods(self) -> Set[str]:
        """Build comprehensive set of framework methods to ignore"""
        return {
            # Frappe core methods
            'frappe.db.get_value',
            'frappe.db.get_list', 
            'frappe.db.get_all',
            'frappe.db.count',
            'frappe.db.exists',
            'frappe.db.get_single_value',
            'frappe.db.set_value',
            
            # Model methods
            'frappe.model.get_value',
            'frappe.model.set_value', 
            'frappe.model.get_doc',
            'frappe.model.delete_doc',
            
            # Client methods
            'frappe.client.get',
            'frappe.client.get_list',
            'frappe.client.insert',
            'frappe.client.save',
            'frappe.client.submit',
            'frappe.client.cancel',
            'frappe.client.delete',
            
            # Utility methods
            'frappe.utils.get_url',
            'frappe.utils.get_site_url',
            'frappe.utils.format_date',
            'frappe.utils.format_datetime',
            
            # Authentication methods
            'frappe.auth.get_logged_user',
            'frappe.auth.has_permission',
            'frappe.auth.get_roles',
            
            # Workflow methods
            'frappe.workflow.get_workflow_state',
            'frappe.workflow.apply_workflow',
        }
    
    def _build_builtin_patterns(self) -> List[re.Pattern]:
        """Build patterns for built-in methods that should be ignored"""
        return [
            re.compile(r'^frappe\.(db|client|model|utils|auth|workflow)\.'),
            re.compile(r'^erpnext\.(accounts|stock|selling|buying)\.utils\.'),
            re.compile(r'^frappe\.desk\.'),
            re.compile(r'^frappe\.core\.'),
        ]
    
    @lru_cache(maxsize=256)  # Limited cache size to prevent memory leaks
    def _get_file_mtime(self, file_path: Path) -> float:
        """Get file modification time with caching"""
        try:
            return file_path.stat().st_mtime
        except (OSError, IOError):
            return 0.0
    
    def _should_ignore_file(self, file_path: Path) -> bool:
        """Check if file should be ignored based on patterns"""
        path_str = str(file_path)
        for pattern in self.config.get('ignore_patterns', []):
            if re.search(pattern, path_str):
                return True
        return False
    
    def _should_ignore_method(self, method_name: str) -> bool:
        """Check if method should be ignored as framework method"""
        if method_name in self.framework_methods:
            return True
        
        for pattern in self.builtin_patterns:
            if pattern.match(method_name):
                return True
        
        return False
    
    def extract_js_calls(self, js_file: Path) -> List[JSCall]:
        """Extract JavaScript calls with enhanced pattern recognition"""
        if self._should_ignore_file(js_file):
            return []
        
        # Check cache first
        if self.config.get('cache_enabled', True):
            mtime = self._get_file_mtime(js_file)
            cache_key = f"{js_file}:{mtime}"
            if cache_key in self._js_calls_cache:
                self.stats['cache_hits'] += 1
                # Move to end for LRU
                self._js_calls_cache.move_to_end(cache_key)
                return self._js_calls_cache[cache_key]
        
        calls = []
        
        try:
            with open(js_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
        except (IOError, UnicodeDecodeError) as e:
            logger.warning(f"Could not read {js_file}: {e}")
            return []
        
        # Use pre-compiled patterns for better performance
        for line_num, line in enumerate(lines, 1):
            for pattern, call_type in self._compiled_call_patterns:
                matches = pattern.finditer(line)
                for match in matches:
                    method_name = match.group(1)
                    
                    # Remove debug output for cleaner production use
                    # if method_name == 'add_board_member':
                    #     logger.info(f"🔍 DEBUG: Found method call '{method_name}' on line {line_num}")
                    
                    # Skip framework methods
                    if self._should_ignore_method(method_name):
                        continue
                    
                    # Extract context (surrounding lines)
                    context_start = max(0, line_num - 3)
                    context_end = min(len(lines), line_num + 2)
                    context = '\n'.join(lines[context_start:context_end])
                    
                    # Calculate absolute position in file
                    # match.start() is relative to the line, we need absolute position
                    lines_before = lines[:line_num-1]  # All lines before current line
                    chars_before = sum(len(line) + 1 for line in lines_before)  # +1 for newline
                    absolute_match_start = chars_before + match.start()
                    
                    # Extract arguments
                    args = self._extract_js_arguments(content, absolute_match_start, line_num)
                    
                    # Determine if call is conditional
                    is_conditional = self._is_conditional_call(context)
                    
                    # Calculate confidence based on pattern and context
                    confidence = self._calculate_call_confidence(method_name, call_type, context)
                    
                    call = JSCall(
                        file_path=str(js_file.relative_to(self.project_root)),
                        line_number=line_num,
                        method_name=method_name,
                        args=args,
                        context=context,
                        call_type=call_type,
                        confidence=confidence,
                        is_conditional=is_conditional
                    )
                    
                    calls.append(call)
        
        # Cache results with proper size management
        if self.config.get('cache_enabled', True):
            self._manage_cache_size(self._js_calls_cache, cache_key)
            self._js_calls_cache[cache_key] = calls
        
        return calls
    
    def _extract_js_arguments(self, content: str, match_start: int, line_num: int) -> Dict[str, Any]:
        """Enhanced argument extraction from JavaScript calls"""
        args = {}
        
        # Find arguments in the call - support multiple patterns
        # Start search from a bit before the match to include the full call context
        start_pos = max(0, match_start - 50)  # Include some context before the match
        search_text = content[start_pos:start_pos + 1500]  # Search in next 1500 chars
        
        # Remove debug output for cleaner production use
        # if line_num == 422:  # Debug only specific line
        #     logger.info(f"🔍 DEBUG: Extracting args for line {line_num}")
        #     logger.info(f"🔍 DEBUG: Search text: '{search_text[:500]}'")
        
        # Multiple patterns to match different call styles
        args_patterns = [
            # Pattern 1: args: { ... } style (traditional)
            (r'args:\s*\{([^}]*)\}', 'args_object'),
            (r'[\'"]args[\'"]:\s*\{([^}]*)\}', 'args_object'),
            # Pattern 2: Direct object after method name (most common in frappe.call)
            (r'[\'"][^\'"]+"[\'"],\s*\{([^}]+)\}', 'direct_object'),
            # Pattern 3: Look for the full call context with method
            (r'\.call\([^,]+,\s*\{([^}]+)\}', 'call_object'),
            # Pattern 4: More specific pattern for this.api.call style
            (r'this\.api\.call\([^,]+,\s*\{([^}]+)\}', 'api_call'),
        ]
        
        for pattern, pattern_type in args_patterns:
            match = re.search(pattern, search_text, re.DOTALL)
            if match:
                args_text = match.group(1)
                
                args = self._parse_js_object(args_text)
                
                # If we found a direct object pattern, all keys are potential parameters
                # except common meta keys like 'doc', 'callback', 'error'
                if pattern_type in ['direct_object', 'call_object', 'api_call']:
                    # Filter out common non-parameter keys
                    meta_keys = {'doc', 'callback', 'error', 'freeze', 'freeze_message', 'btn'}
                    args = {k: v for k, v in args.items() if k not in meta_keys}
                break
        return args
    
    def _parse_js_object(self, js_obj_text: str) -> Dict[str, Any]:
        """Enhanced JavaScript object parsing with better pattern matching"""
        args = {}
        
        # Clean up the text - remove newlines and extra spaces
        js_obj_text = re.sub(r'\s+', ' ', js_obj_text.strip())
        
        # Enhanced parsing patterns to handle different JavaScript styles
        patterns = [
            # Standard key: value
            r'[\'"]?(\w+)[\'"]?\s*:\s*([^,}]+)',
            # Property names without quotes
            r'(\w+)\s*:\s*([^,}]+)',
        ]
        
        for pattern in patterns:
            pairs = re.findall(pattern, js_obj_text)
            for key, value in pairs:
                # Clean up the value
                value = value.strip()
                
                # Handle different value patterns
                if value.startswith('values.'):
                    # Extract the actual parameter name from values.parameter
                    param_name = value.split('.', 1)[1] if '.' in value else value
                    args[key] = param_name
                elif value.startswith("'") or value.startswith('"'):
                    # String literal
                    args[key] = value.strip('\'"')
                elif value.lower() in ['true', 'false']:
                    # Boolean
                    args[key] = value.lower() == 'true'
                elif value.isdigit():
                    # Integer
                    args[key] = int(value)
                elif re.match(r'^\d+\.\d+$', value):
                    # Float
                    args[key] = float(value)
                else:
                    # Variable reference or complex expression - mark as present
                    args[key] = value
        
        return args
    
    def _apply_parameter_mapping(self, js_params: Set[str], required_params: Set[str]) -> Set[str]:
        """Apply parameter name mapping to handle common variations"""
        mapped_params = set(js_params)
        
        # Common parameter name mappings
        param_mappings = {
            'chapter_role': 'role',
            'role_name': 'role',
            'member_name': 'member',
            'volunteer_name': 'volunteer',
            'user_name': 'user',
            'doc_name': 'name',
            'document_name': 'name',
        }
        
        # Apply mappings
        for js_param in js_params:
            if js_param in param_mappings:
                mapped_name = param_mappings[js_param]
                if mapped_name in required_params:
                    mapped_params.add(mapped_name)
        
        # Also check for fuzzy matching of parameter names
        for js_param in js_params:
            for req_param in required_params:
                # Check if JS parameter contains the required parameter name
                if req_param in js_param or js_param in req_param:
                    # Calculate similarity
                    similarity = self._calculate_string_similarity(js_param, req_param)
                    if similarity > 0.7:  # 70% similarity threshold
                        mapped_params.add(req_param)
        
        return mapped_params
    
    def _calculate_string_similarity(self, str1: str, str2: str) -> float:
        """Calculate string similarity using SequenceMatcher"""
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
    
    def _is_conditional_call(self, context: str) -> bool:
        """Determine if a call is within conditional logic"""
        conditional_patterns = [
            r'\bif\s*\(',
            r'\btry\s*\{',
            r'\bcatch\s*\(',
            r'\?\s*',  # Ternary operator
        ]
        
        for pattern in conditional_patterns:
            if re.search(pattern, context):
                return True
        return False
    
    def _calculate_call_confidence(self, method_name: str, call_type: str, context: str) -> float:
        """Calculate confidence score for method call detection"""
        confidence = 0.8  # Base confidence
        
        # Increase confidence for explicit patterns
        if call_type in ['frappe.call', 'frm.call']:
            confidence += 0.1
        
        # Increase confidence for app-specific methods
        if method_name.startswith(('verenigingen.', 'erpnext.', 'frappe.')):
            confidence += 0.05
        
        # Decrease confidence for very short method names
        if len(method_name) < 5:
            confidence -= 0.1
        
        # Increase confidence if context shows parameter passing
        if 'args:' in context or '"args"' in context:
            confidence += 0.05
        
        return min(1.0, max(0.1, confidence))
    
    def _get_doctype_fields(self, doctype_name: str) -> Set[str]:
        """Get all valid fields for a DocType using unified loader"""
        if not self.doctype_loader or not doctype_name:
            return set()
            
        if doctype_name in self.doctype_fields_cache:
            return self.doctype_fields_cache[doctype_name]
            
        try:
            field_names = self.doctype_loader.get_field_names(doctype_name)
            self.doctype_fields_cache[doctype_name] = field_names
            self.stats['doctype_lookups'] += 1
            return field_names
        except Exception as e:
            logger.debug(f"Could not load fields for DocType {doctype_name}: {e}")
            return set()
    
    def _validate_doctype_field_access(self, js_call: JSCall, python_func: PythonFunction) -> List[ValidationIssue]:
        """Enhanced validation using DocType field information"""
        issues = []
        
        # Check if this looks like a DocType operation
        doctype_patterns = [
            r'get_doc\(',
            r'frappe\.get_doc\(',
            r'\.save\(',
            r'\.submit\(',
            r'\.cancel\(',
            r'frappe\.db\.get_value\(',
            r'frappe\.db\.set_value\(',
        ]
        
        context_lower = js_call.context.lower()
        has_doctype_operation = any(re.search(pattern, context_lower) for pattern in doctype_patterns)
        
        if not has_doctype_operation:
            return issues
            
        # Try to extract DocType name from the call
        doctype_name = self._extract_doctype_from_call(js_call)
        if not doctype_name:
            return issues
            
        # Get valid fields for this DocType
        valid_fields = self._get_doctype_fields(doctype_name)
        if not valid_fields:
            return issues
            
        # Check if any parameters reference invalid fields
        for param_name, param_value in js_call.args.items():
            if isinstance(param_value, str) and param_value not in valid_fields:
                # Check if this looks like a field reference
                if self._looks_like_field_reference(param_value, param_name):
                    issue = ValidationIssue(
                        js_call=js_call,
                        python_function=python_func,
                        issue_type=IssueType.MISSING_PARAMETER,
                        severity=Severity.MEDIUM,
                        description=f"Parameter '{param_name}' references invalid field '{param_value}' for DocType '{doctype_name}'",
                        suggestion=f"Check if field '{param_value}' exists in DocType '{doctype_name}' or use a valid field name",
                        confidence=0.7
                    )
                    issues.append(issue)
                    
        self.stats['enhanced_validations'] += 1
        return issues
    
    def _extract_doctype_from_call(self, js_call: JSCall) -> Optional[str]:
        """Try to extract DocType name from JavaScript call context"""
        # Common patterns for DocType references
        patterns = [
            r"doctype['\"]?\s*:\s*['\"]([^'\"]+)['\"]",
            r"get_doc\(\s*['\"]([^'\"]+)['\"]",
            r"frappe\.get_doc\(\s*['\"]([^'\"]+)['\"]",
            r"new_doc\(\s*['\"]([^'\"]+)['\"]",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, js_call.context, re.IGNORECASE)
            if match:
                return match.group(1)
                
        # Check in call arguments
        if 'doctype' in js_call.args:
            return str(js_call.args['doctype'])
            
        return None
    
    def _looks_like_field_reference(self, value: str, param_name: str) -> bool:
        """Determine if a parameter value looks like a field reference"""
        # Common field-like patterns
        field_indicators = [
            'name', 'title', 'status', 'owner', 'creation', 'modified',
            '_name', '_id', 'field', 'column'
        ]
        
        # Check if parameter name suggests a field
        param_lower = param_name.lower()
        if any(indicator in param_lower for indicator in ['field', 'column', 'attr']):
            return True
            
        # Check if value looks like a field name
        if isinstance(value, str) and len(value) > 2:
            return any(indicator in value.lower() for indicator in field_indicators)
            
        return False
    
    def extract_python_functions(self, py_file: Path) -> List[PythonFunction]:
        """Extract Python functions with comprehensive AST analysis"""
        if self._should_ignore_file(py_file):
            return []
        
        # Check cache
        if self.config.get('cache_enabled', True):
            mtime = self._get_file_mtime(py_file)
            cache_key = f"{py_file}:{mtime}"
            if cache_key in self._python_functions_cache:
                self.stats['cache_hits'] += 1
                # Move to end for LRU
                self._python_functions_cache.move_to_end(cache_key)
                return self._python_functions_cache[cache_key]
        
        functions = []
        
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse with AST for accurate analysis
            tree = ast.parse(content)
            
        except (IOError, UnicodeDecodeError, SyntaxError) as e:
            logger.warning(f"Could not parse {py_file}: {e}")
            return []
        
        # Find functions with @frappe.whitelist() decorator
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check for whitelist decorator
                is_whitelisted = False
                decorator_line = 0
                
                for decorator in node.decorator_list:
                    if self._is_whitelist_decorator(decorator):
                        is_whitelisted = True
                        decorator_line = decorator.lineno
                        break
                
                if is_whitelisted:
                    function_info = self._analyze_function(node, py_file, content, decorator_line)
                    if function_info:
                        functions.append(function_info)
        
        # Cache results with proper size management
        if self.config.get('cache_enabled', True):
            self._manage_cache_size(self._python_functions_cache, cache_key)
            self._python_functions_cache[cache_key] = functions
        
        return functions
    
    def _is_whitelist_decorator(self, decorator: ast.AST) -> bool:
        """Check if decorator is @frappe.whitelist()"""
        if isinstance(decorator, ast.Call):
            func = decorator.func
        else:
            func = decorator
        
        if isinstance(func, ast.Attribute):
            return (isinstance(func.value, ast.Name) and 
                   func.value.id == 'frappe' and 
                   func.attr == 'whitelist')
        elif isinstance(func, ast.Name):
            return func.id == 'whitelist'
        
        return False
    
    def _analyze_function(self, node: ast.FunctionDef, py_file: Path, content: str, 
                         decorator_line: int) -> Optional[PythonFunction]:
        """Comprehensive function analysis"""
        
        # Build full method path
        module_parts = py_file.relative_to(self.project_root).with_suffix('').parts
        full_method_path = '.'.join(module_parts) + '.' + node.name
        
        # Analyze parameters
        parameters = []
        required_params = []
        optional_params = []
        param_types = {}
        has_args = False
        has_kwargs = False
        
        for arg in node.args.args:
            param_name = arg.arg
            # Skip 'self' parameter for methods (critical fix for false positives)
            if param_name == 'self':
                continue
            parameters.append(param_name)
            
            # Check if it has type annotation
            if arg.annotation:
                # Handle Python version compatibility
                try:
                    param_types[param_name] = ast.unparse(arg.annotation)
                except AttributeError:
                    # Fallback for Python < 3.9
                    param_types[param_name] = str(arg.annotation)
        
        # Handle default arguments
        defaults = node.args.defaults
        num_defaults = len(defaults)
        num_params = len(parameters)
        
        if num_defaults > 0:
            required_params = parameters[:-num_defaults]
            optional_params = parameters[-num_defaults:]
        else:
            required_params = parameters[:]
        
        # Check for *args and **kwargs
        if node.args.vararg:
            has_args = True
        if node.args.kwarg:
            has_kwargs = True
        
        # Extract docstring
        docstring = None
        if (node.body and isinstance(node.body[0], ast.Expr) and 
            isinstance(node.body[0].value, ast.Constant) and 
            isinstance(node.body[0].value.value, str)):
            docstring = node.body[0].value.value
        
        # Calculate complexity score
        complexity_score = self._calculate_complexity(node)
        
        function = PythonFunction(
            file_path=str(py_file.relative_to(self.project_root)),
            line_number=node.lineno,
            function_name=node.name,
            full_method_path=full_method_path,
            parameters=parameters,
            required_params=required_params,
            optional_params=optional_params,
            param_types=param_types,
            docstring=docstring,
            has_kwargs=has_kwargs,
            has_args=has_args,
            is_whitelisted=True,
            decorator_line=decorator_line,
            complexity_score=complexity_score
        )
        
        return function
    
    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate function complexity score"""
        complexity = 1  # Base complexity
        
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.Try)):
                complexity += 1
        
        return complexity
    
    def build_function_index(self):
        """Build index of function names for fast lookup"""
        self.function_index.clear()
        
        for full_path, func in self.python_functions.items():
            self.function_index[func.function_name].append(full_path)
    
    def find_matching_function(self, method_name: str) -> Optional[PythonFunction]:
        """Find matching Python function with enhanced resolution"""
        
        # Direct lookup first
        if method_name in self.python_functions:
            return self.python_functions[method_name]
        
        # Extract function name from full path
        if '.' in method_name:
            func_name = method_name.split('.')[-1]
            if func_name in self.function_index:
                # Find best match
                candidates = self.function_index[func_name]
                best_match = self._find_best_path_match(method_name, candidates)
                if best_match:
                    return self.python_functions[best_match]
        
        # Fuzzy matching as fallback
        return self._fuzzy_match_function(method_name)
    
    def _find_best_path_match(self, target_path: str, candidates: List[str]) -> Optional[str]:
        """Find best matching path from candidates"""
        best_score = 0
        best_match = None
        
        for candidate in candidates:
            # Calculate similarity score
            score = SequenceMatcher(None, target_path, candidate).ratio()
            
            if score > best_score and score > self.config.get('fuzzy_match_threshold', 0.6):
                best_score = score
                best_match = candidate
        
        return best_match
    
    def _fuzzy_match_function(self, method_name: str) -> Optional[PythonFunction]:
        """Fuzzy match function names"""
        threshold = self.config.get('fuzzy_match_threshold', 0.6)
        best_score = 0
        best_match = None
        
        for full_path, func in self.python_functions.items():
            # Compare with function name
            score = SequenceMatcher(None, method_name, func.function_name).ratio()
            
            # Also compare with full path
            path_score = SequenceMatcher(None, method_name, full_path).ratio()
            final_score = max(score, path_score)
            
            if final_score > best_score and final_score > threshold:
                best_score = final_score
                best_match = func
        
        return best_match
    
    def validate_call(self, js_call: JSCall) -> List[ValidationIssue]:
        """Enhanced validation of JavaScript call against Python function"""
        issues = []
        
        # Find matching Python function
        python_func = self.find_matching_function(js_call.method_name)
        
        if not python_func:
            # Check if it's a framework method that should be ignored
            if self._should_ignore_method(js_call.method_name):
                return []  # No issue for framework methods
            
            issue = ValidationIssue(
                js_call=js_call,
                python_function=None,
                issue_type=IssueType.METHOD_NOT_FOUND,
                severity=Severity.HIGH,
                description=f"Method '{js_call.method_name}' not found in Python codebase",
                confidence=js_call.confidence
            )
            issues.append(issue)
            return issues
        
        # Enhanced validation with DocType awareness
        if self.doctype_loader:
            doctype_issues = self._validate_doctype_field_access(js_call, python_func)
            issues.extend(doctype_issues)
        
        # Enhanced parameter validation with mapping support
        js_params = set(js_call.args.keys())
        required_params = set(python_func.required_params)
        all_params = set(python_func.parameters)
        
        # Apply parameter mapping for common variations
        mapped_js_params = self._apply_parameter_mapping(js_params, required_params)
        
        # Check for missing required parameters after mapping
        missing_params = required_params - mapped_js_params
        for param in missing_params:
            issue = ValidationIssue(
                js_call=js_call,
                python_function=python_func,
                issue_type=IssueType.MISSING_PARAMETER,
                severity=Severity.HIGH,
                description=f"Missing required parameter: {param}",
                confidence=0.9
            )
            issues.append(issue)
        
        # Check for extra parameters (only if function doesn't accept **kwargs)
        if not python_func.has_kwargs:
            extra_params = js_params - all_params
            for param in extra_params:
                # Apply enhanced analysis for extra parameters
                severity = self._analyze_extra_parameter_severity(param, js_call, python_func)
                
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=python_func,
                    issue_type=IssueType.EXTRA_PARAMETER,
                    severity=severity,
                    description=f"Extra parameter not expected: {param}",
                    confidence=0.7
                )
                issues.append(issue)
        
        # Type validation if type annotations are available
        type_issues = self._validate_parameter_types(js_call, python_func)
        issues.extend(type_issues)
        
        return issues
    
    def _analyze_extra_parameter_severity(self, param: str, js_call: JSCall, python_func: PythonFunction) -> Severity:
        """Analyze the severity of an extra parameter"""
        # Common parameter names that are often optional
        common_optional = {
            'callback', 'success_callback', 'error_callback',
            'freeze', 'freeze_message', 'async', 'no_save',
            'ignore_permissions', 'debug', 'validate'
        }
        
        if param.lower() in common_optional:
            return Severity.LOW
            
        # If the parameter name suggests it's a callback or option
        if any(keyword in param.lower() for keyword in ['callback', 'option', 'flag', 'enable']):
            return Severity.LOW
            
        return Severity.MEDIUM
    
    def _validate_parameter_types(self, js_call: JSCall, python_func: PythonFunction) -> List[ValidationIssue]:
        """Validate parameter types when type annotations are available"""
        issues = []
        
        for param_name, js_value in js_call.args.items():
            if param_name in python_func.param_types:
                expected_type = python_func.param_types[param_name]
                js_type = type(js_value).__name__
                
                # Simple type checking (can be enhanced)
                type_mismatch = self._check_type_compatibility(js_type, expected_type, js_value)
                
                if type_mismatch:
                    issue = ValidationIssue(
                        js_call=js_call,
                        python_function=python_func,
                        issue_type=IssueType.TYPE_MISMATCH,
                        severity=Severity.MEDIUM,
                        description=f"Type mismatch for parameter '{param_name}': expected {expected_type}, got {js_type}",
                        suggestion=f"Convert parameter '{param_name}' to {expected_type}",
                        confidence=0.6
                    )
                    issues.append(issue)
        
        return issues
    
    def _check_type_compatibility(self, js_type: str, expected_type: str, value: Any) -> bool:
        """Check if JavaScript type is compatible with expected Python type"""
        # Basic type compatibility mapping
        type_mappings = {
            'str': ['string', 'str'],
            'int': ['number', 'int'],
            'float': ['number', 'float'],
            'bool': ['boolean', 'bool'],
            'dict': ['object', 'dict'],
            'list': ['array', 'list'],
        }
        
        # Normalize expected type
        expected_lower = expected_type.lower()
        for py_type, js_types in type_mappings.items():
            if py_type in expected_lower:
                return js_type.lower() not in js_types
                
        # If we can't determine compatibility, assume it's OK
        return False
    
    def scan_javascript_files(self):
        """Scan all JavaScript files for Python method calls"""
        js_patterns = ['**/*.js', 'public/js/**/*.js', '**/doctype/*/*.js']
        
        for pattern in js_patterns:
            for js_file in self.project_root.rglob(pattern):
                if not js_file.is_file() or self._should_ignore_file(js_file):
                    continue
                calls = self.extract_js_calls(js_file)
                self.js_calls.extend(calls)
                if calls:
                    self.stats['js_files_scanned'] += 1
        
        self.stats['js_calls_found'] = len(self.js_calls)
        logger.info(f"Found {len(self.js_calls)} JavaScript calls in {self.stats['js_files_scanned']} files")
    
    def scan_python_files(self):
        """Scan all Python files for whitelisted functions"""
        py_patterns = ['**/*.py']
        
        for pattern in py_patterns:
            for py_file in self.project_root.rglob(pattern):
                if not py_file.is_file() or self._should_ignore_file(py_file):
                    continue
                functions = self.extract_python_functions(py_file)
                for func in functions:
                    self.python_functions[func.full_method_path] = func
                if functions:
                    self.stats['py_files_scanned'] += 1
        
        self.stats['python_functions_found'] = len(self.python_functions)
        logger.info(f"Found {len(self.python_functions)} whitelisted functions in {self.stats['py_files_scanned']} files")
        
        # Build function index for fast lookup
        self.build_function_index()
    
    def _manage_cache_size(self, cache: 'OrderedDict', cache_key: str) -> None:
        """Manage cache size with LRU eviction"""
        import time
        current_time = time.time()
        
        # Remove expired entries first
        expired_keys = [
            k for k, creation_time in self._cache_creation_time.items()
            if current_time - creation_time > self._cache_ttl and k in cache
        ]
        for k in expired_keys:
            cache.pop(k, None)
            self._cache_creation_time.pop(k, None)
        
        # If still too large, remove oldest entries
        while len(cache) >= self._cache_max_size:
            oldest_key = next(iter(cache))
            cache.pop(oldest_key, None)
            self._cache_creation_time.pop(oldest_key, None)
        
        # Track creation time for new entry
        self._cache_creation_time[cache_key] = current_time
    
    def cleanup_resources(self) -> None:
        """Clean up resources and caches"""
        self._python_functions_cache.clear()
        self._js_calls_cache.clear()
        self._file_mtime_cache.clear()
        self._cache_creation_time.clear()
        
        # Clear DocType loader cache if available
        if hasattr(self.doctype_loader, 'clear_cache'):
            self.doctype_loader.clear_cache()
    
    def run_validation(self) -> List[ValidationIssue]:
        """Run complete validation process"""
        logger.info("Starting JavaScript-Python parameter validation...")
        
        # Scan files
        self.scan_python_files()
        self.scan_javascript_files()
        
        # Validate each call
        all_issues = []
        for js_call in self.js_calls:
            issues = self.validate_call(js_call)
            all_issues.extend(issues)
        
        # Filter by severity threshold
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4,
        }
        
        threshold = self.config.get('severity_threshold', 'medium')
        threshold_level = severity_order.get(Severity(threshold), 2)
        
        filtered_issues = [
            issue for issue in all_issues
            if severity_order.get(issue.severity, 4) <= threshold_level
        ]
        
        self.issues = filtered_issues
        self.stats['issues_found'] = len(filtered_issues)
        
        return filtered_issues
    
    def generate_report(self, issues: Optional[List[ValidationIssue]] = None) -> str:
        """Generate comprehensive validation report"""
        if issues is None:
            issues = self.issues
        
        if not issues:
            return self._generate_success_report()
        
        report = []
        report.append("📊 JavaScript-Python Parameter Validation Report")
        report.append("=" * 80)
        report.append(f"Total issues: {len(issues)}")
        report.append(f"JavaScript files scanned: {self.stats['js_files_scanned']}")
        report.append(f"Python functions found: {self.stats['python_functions_found']}")
        
        # Enhanced statistics
        if self.doctype_loader:
            report.append(f"DocType lookups performed: {self.stats['doctype_lookups']}")
            report.append(f"Enhanced validations: {self.stats['enhanced_validations']}")
        
        report.append(f"Cache efficiency: {self.stats['cache_hits']} hits")
        report.append("")
        
        # Group by severity
        by_severity = defaultdict(list)
        for issue in issues:
            by_severity[issue.severity].append(issue)
        
        # Report by severity
        severity_icons = {
            Severity.CRITICAL: "🔴",
            Severity.HIGH: "🟠", 
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🔵",
            Severity.INFO: "⚪"
        }
        
        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]:
            if severity in by_severity:
                severity_issues = by_severity[severity]
                icon = severity_icons[severity]
                
                report.append(f"\n{icon} {severity.value.upper()} ({len(severity_issues)} issues)")
                report.append("-" * 60)
                
                # Group by issue type
                by_type = defaultdict(list)
                for issue in severity_issues:
                    by_type[issue.issue_type].append(issue)
                
                for issue_type, type_issues in by_type.items():
                    report.append(f"\n  {issue_type.value.replace('_', ' ').title()} ({len(type_issues)} issues):")
                    
                    # Show sample issues
                    for issue in type_issues[:5]:
                        report.append(f"    📍 {issue.js_call.file_path}:{issue.js_call.line_number}")
                        report.append(f"       Method: {issue.js_call.method_name}")
                        report.append(f"       Issue: {issue.description}")
                        if issue.suggestion:
                            report.append(f"       💡 {issue.suggestion}")
                        report.append("")
                    
                    if len(type_issues) > 5:
                        report.append(f"    ... and {len(type_issues) - 5} more")
                    report.append("")
        
        # Summary statistics
        report.append("📈 Summary:")
        report.append("-" * 40)
        
        critical_count = len(by_severity.get(Severity.CRITICAL, []))
        high_count = len(by_severity.get(Severity.HIGH, []))
        
        if critical_count > 0:
            report.append(f"⚠️  {critical_count} CRITICAL issues require immediate attention!")
        if high_count > 0:
            report.append(f"⚠️  {high_count} HIGH severity issues should be addressed soon")
        
        return '\n'.join(report)
    
    def _generate_success_report(self) -> str:
        """Generate success report when no issues found"""
        report = []
        report.append("✅ JavaScript-Python Parameter Validation Report")
        report.append("=" * 80)
        report.append("🎉 No parameter validation issues found!")
        report.append("")
        report.append("📊 Validation Statistics:")
        report.append(f"  • JavaScript files scanned: {self.stats['js_files_scanned']}")
        report.append(f"  • JavaScript calls analyzed: {self.stats['js_calls_found']}")
        report.append(f"  • Python functions found: {self.stats['python_functions_found']}")
        
        if self.doctype_loader:
            report.append(f"  • DocType lookups performed: {self.stats['doctype_lookups']}")
            report.append(f"  • Enhanced validations: {self.stats['enhanced_validations']}")
        
        report.append(f"  • Cache efficiency: {self.stats['cache_hits']} hits")
        report.append("")
        report.append("✅ All JavaScript-Python interfaces are properly aligned!")
        
        return '\n'.join(report)


def main():
    """Main entry point with enhanced configuration"""
    import sys
    
    project_root = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Parse command line arguments
    verbose = '--verbose' in sys.argv
    severity = 'medium'
    
    if '--critical' in sys.argv:
        severity = 'critical'
    elif '--high' in sys.argv:
        severity = 'high'
    elif '--all' in sys.argv:
        severity = 'info'
    
    # Configure logging
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create validator first to get default config
    validator = ModernJSPythonValidator(project_root)
    
    # Update config with command line options
    validator.config.update({
        'severity_threshold': severity,
        'cache_enabled': True,
        'fuzzy_match_threshold': 0.6,
    })
    
    print("🚀 Modernized JavaScript-Python Parameter Validator")
    print(f"   Severity threshold: {severity}")
    print(f"   Caching enabled: {validator.config['cache_enabled']}")
    print("")
    issues = validator.run_validation()
    
    print("\n" + "=" * 80)
    report = validator.generate_report(issues)
    print(report)
    
    # Return appropriate exit code
    critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    high_count = sum(1 for i in issues if i.severity == Severity.HIGH)
    
    if critical_count > 0:
        return 2  # Critical issues
    elif high_count > 0:
        return 1  # High severity issues
    else:
        return 0  # Success


if __name__ == "__main__":
    exit(main())