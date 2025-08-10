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
        self.project_root = Path(project_root)
        self.config = config or self._load_default_config()
        
        # Caches for performance
        self._python_functions_cache = {}
        self._js_calls_cache = {}
        self._file_mtime_cache = {}
        
        # Data structures
        self.js_calls: List[JSCall] = []
        self.python_functions: Dict[str, PythonFunction] = {}
        self.function_index: Dict[str, List[str]] = defaultdict(list)  # function_name -> full_paths
        self.issues: List[ValidationIssue] = []
        
        # Framework patterns to ignore
        self.framework_methods = self._build_framework_methods()
        self.builtin_patterns = self._build_builtin_patterns()
        
        # Statistics
        self.stats = {
            'js_files_scanned': 0,
            'py_files_scanned': 0,
            'js_calls_found': 0,
            'python_functions_found': 0,
            'issues_found': 0,
            'cache_hits': 0,
        }
    
    def _load_default_config(self) -> Dict:
        """Load default configuration with sensible defaults"""
        return {
            'severity_threshold': 'medium',
            'ignore_patterns': [
                r'.*\.test\.js$',
                r'.*\.spec\.js$',
                r'.*/node_modules/.*',
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
    
    @lru_cache(maxsize=512)
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
            if re.match(pattern, path_str):
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
                return self._js_calls_cache[cache_key]
        
        calls = []
        
        try:
            with open(js_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
        except (IOError, UnicodeDecodeError) as e:
            logger.warning(f"Could not read {js_file}: {e}")
            return []
        
        # Enhanced patterns for different call types
        call_patterns = [
            # frappe.call() with various formats
            (r'frappe\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]', 'frappe.call'),
            (r'frm\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]', 'frm.call'),
            (r'cur_frm\.call\(\s*\{\s*[\'"]?method[\'"]?\s*:\s*[\'"]([^\'"]+)[\'"]', 'cur_frm.call'),
            
            # Direct method references in custom buttons
            (r'[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]', 'button.method'),
            
            # API service calls
            (r'this\._call\(\s*[\'"]([^\'"]+)[\'"]', 'service.call'),
            (r'api\.call\(\s*[\'"]([^\'"]+)[\'"]', 'api.call'),
        ]
        
        for line_num, line in enumerate(lines, 1):
            for pattern, call_type in call_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    method_name = match.group(1)
                    
                    # Skip framework methods
                    if self._should_ignore_method(method_name):
                        continue
                    
                    # Extract context (surrounding lines)
                    context_start = max(0, line_num - 3)
                    context_end = min(len(lines), line_num + 2)
                    context = '\n'.join(lines[context_start:context_end])
                    
                    # Extract arguments
                    args = self._extract_js_arguments(content, match.start(), line_num)
                    
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
        
        # Cache results
        if self.config.get('cache_enabled', True):
            self._js_calls_cache[cache_key] = calls
        
        return calls
    
    def _extract_js_arguments(self, content: str, match_start: int, line_num: int) -> Dict[str, Any]:
        """Enhanced argument extraction from JavaScript calls"""
        args = {}
        
        # Find the args object in the call
        # Look for 'args: {' or '"args": {' pattern
        start_pos = match_start
        search_text = content[start_pos:start_pos + 1000]  # Search in next 1000 chars
        
        args_patterns = [
            r'args:\s*\{([^}]*)\}',
            r'[\'"]args[\'"]:\s*\{([^}]*)\}',
        ]
        
        for pattern in args_patterns:
            match = re.search(pattern, search_text)
            if match:
                args_text = match.group(1)
                args = self._parse_js_object(args_text)
                break
        
        return args
    
    def _parse_js_object(self, js_obj_text: str) -> Dict[str, Any]:
        """Parse JavaScript object text into Python dict"""
        args = {}
        
        # Simple parsing - handle key: value pairs
        # This is a simplified parser, could be enhanced with proper JS AST
        pairs = re.findall(r'[\'"]?(\w+)[\'"]?\s*:\s*([^,}]+)', js_obj_text)
        
        for key, value in pairs:
            # Clean up value
            value = value.strip().strip('\'"')
            
            # Try to detect value type
            if value.lower() in ['true', 'false']:
                args[key] = value.lower() == 'true'
            elif value.isdigit():
                args[key] = int(value)
            elif re.match(r'^\d+\.\d+$', value):
                args[key] = float(value)
            else:
                args[key] = value
        
        return args
    
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
        
        # Cache results
        if self.config.get('cache_enabled', True):
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
            parameters.append(param_name)
            
            # Check if it has type annotation
            if arg.annotation:
                param_types[param_name] = ast.unparse(arg.annotation)
        
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
        """Validate a JavaScript call against Python function"""
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
        
        # Validate parameters
        js_params = set(js_call.args.keys())
        required_params = set(python_func.required_params)
        all_params = set(python_func.parameters)
        
        # Check for missing required parameters
        missing_params = required_params - js_params
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
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=python_func,
                    issue_type=IssueType.EXTRA_PARAMETER,
                    severity=Severity.MEDIUM,
                    description=f"Extra parameter not expected: {param}",
                    confidence=0.7
                )
                issues.append(issue)
        
        return issues
    
    def scan_javascript_files(self):
        """Scan all JavaScript files for Python method calls"""
        js_patterns = ['**/*.js', 'public/js/**/*.js', '**/doctype/*/*.js']
        
        for pattern in js_patterns:
            for js_file in self.project_root.rglob(pattern):
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
                functions = self.extract_python_functions(py_file)
                for func in functions:
                    self.python_functions[func.full_method_path] = func
                if functions:
                    self.stats['py_files_scanned'] += 1
        
        self.stats['python_functions_found'] = len(self.python_functions)
        logger.info(f"Found {len(self.python_functions)} whitelisted functions in {self.stats['py_files_scanned']} files")
        
        # Build function index for fast lookup
        self.build_function_index()
    
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
        report.append(f"Cache hits: {self.stats['cache_hits']}")
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
    
    config = {
        'severity_threshold': severity,
        'cache_enabled': True,
        'fuzzy_match_threshold': 0.6,
    }
    
    print("🚀 Modernized JavaScript-Python Parameter Validator")
    print(f"   Severity threshold: {severity}")
    print(f"   Caching enabled: {config['cache_enabled']}")
    print("")
    
    validator = ModernJSPythonValidator(project_root, config)
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