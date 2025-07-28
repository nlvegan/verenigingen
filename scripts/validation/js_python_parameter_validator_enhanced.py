#!/usr/bin/env python3
"""
Enhanced JavaScript-Python Parameter Validation System

This enhanced validator addresses key issues found in the original validator:
1. Path Resolution Problems - Better fuzzy matching and path patterns
2. Framework Method False Positives - Comprehensive framework method detection  
3. Module Discovery Issues - Function name indexing and better app structure support
4. Poor Issue Categorization - Improved severity classification and ignore patterns

Key Improvements:
- Enhanced path resolution with fuzzy matching
- Framework method detection to reduce false positives
- Function name indexing for better method discovery
- Configurable validation rules and severity levels
- Support for Frappe app structure patterns
"""

import os
import re
import ast
import json
import inspect
import importlib.util
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
from difflib import SequenceMatcher

# Load configuration
def load_config():
    """Load configuration from JSON file"""
    config_path = Path(__file__).parent / "validator_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}

CONFIG = load_config()

# Common Frappe patterns for JavaScript-Python communication
JS_PYTHON_PATTERNS = [
    # frappe.call() patterns
    r'frappe\.call\(\s*\{\s*method:\s*[\'"]([^\'"]+)[\'"]',
    r'frappe\.call\(\s*\{\s*[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]',
    
    # frm.call() patterns  
    r'frm\.call\(\s*\{\s*method:\s*[\'"]([^\'"]+)[\'"]',
    r'frm\.call\(\s*\{\s*[\'"]method[\'"]:\s*[\'"]([^\'"]+)[\'"]',
    
    # Direct API service calls
    r'this\.call\(\s*[\'"]([^\'"]+)[\'"]',
    r'api\.call\(\s*[\'"]([^\'"]+)[\'"]',
    
    # Custom button handlers
    r'method:\s*[\'"]([^\'"]+)[\'"]',
]

# Parameter extraction patterns
ARGS_PATTERNS = [
    r'args:\s*\{([^}]+)\}',
    r'[\'"]args[\'"]:\s*\{([^}]+)\}',
]

@dataclass
class JSCall:
    """Represents a JavaScript call to a Python method"""
    file_path: str
    line_number: int
    method_name: str
    args: Dict[str, Any] = field(default_factory=dict)
    context: str = ""  # Surrounding code context
    call_type: str = ""  # frappe.call, frm.call, etc.

@dataclass
class PythonFunction:
    """Represents a Python function with @frappe.whitelist() decorator"""
    file_path: str
    line_number: int
    function_name: str
    full_method_path: str
    parameters: List[str] = field(default_factory=list)
    required_params: List[str] = field(default_factory=list)
    optional_params: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    has_kwargs: bool = False
    has_args: bool = False

@dataclass
class ValidationIssue:
    """Represents a parameter validation issue"""
    js_call: JSCall
    python_function: Optional[PythonFunction]
    issue_type: str  # missing_param, extra_param, type_mismatch, method_not_found, framework_method
    description: str
    severity: str = "medium"  # low, medium, high, critical, ignore
    suggestion: str = ""
    resolution_action: str = ""  # fix, remove, ignore, review

class EnhancedJSPythonParameterValidator:
    """Enhanced validator class with improved path resolution and framework detection"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.js_calls: List[JSCall] = []
        self.python_functions: Dict[str, PythonFunction] = {}
        self.function_name_index: Dict[str, List[PythonFunction]] = defaultdict(list)
        self.issues: List[ValidationIssue] = []
        self.config = CONFIG
        self.stats = {
            'js_files_scanned': 0,
            'py_files_scanned': 0,
            'js_calls_found': 0,
            'python_functions_found': 0,
            'issues_found': 0,
            'framework_methods_detected': 0,
            'fuzzy_matches_found': 0,
        }
    
    def is_framework_method(self, method_name: str) -> bool:
        """Check if method is a Frappe framework method"""
        framework_methods = self.config.get('framework_methods', [])
        return method_name in framework_methods
    
    def is_excluded_path(self, file_path: Path) -> bool:
        """Check if file path should be excluded from validation"""
        exclude_patterns = self.config.get('exclude_patterns', [])
        path_str = str(file_path).lower()
        
        for pattern in exclude_patterns:
            # More precise pattern matching
            pattern_parts = [p for p in pattern.replace('**', '').replace('*', '').split('/') if p]
            if any(part and part in path_str for part in pattern_parts):
                # Only exclude if it's a clear match (e.g., 'test' in path for test files)
                if pattern.startswith('**/test') and 'test' in path_str:
                    return True
                elif pattern.startswith('**/debug') and 'debug' in path_str:
                    return True
                elif pattern.endswith('.js') and path_str.endswith('.js'):
                    return True
        return False
    
    def get_method_severity(self, method_name: str, js_call: JSCall) -> str:
        """Determine severity based on method type and context"""
        severity_rules = self.config.get('severity_rules', {})
        
        # Framework methods should be ignored
        if self.is_framework_method(method_name):
            return "ignore"
        
        # Test and debug methods are lower priority
        if any(keyword in method_name.lower() for keyword in ['test', 'debug']):
            return severity_rules.get('test_methods', 'low')
        
        # API methods
        if 'api.' in method_name:
            return severity_rules.get('api_methods', 'medium')
        
        # Core application methods
        return severity_rules.get('core_methods', 'high')
    
    def fuzzy_match_function(self, method_name: str) -> Optional[PythonFunction]:
        """Use fuzzy matching to find similar function names"""
        if not self.config.get('path_resolution', {}).get('enable_fuzzy_matching', True):
            return None
        
        threshold = self.config.get('path_resolution', {}).get('fuzzy_threshold', 0.8)
        
        # Extract just the function name from the full method path
        target_func_name = method_name.split('.')[-1]
        best_match = None
        best_score = 0
        
        # Search through function name index
        for func_name, functions in self.function_name_index.items():
            score = SequenceMatcher(None, target_func_name, func_name).ratio()
            if score > threshold and score > best_score:
                best_score = score
                best_match = functions[0]  # Return first match
        
        if best_match:
            self.stats['fuzzy_matches_found'] += 1
            
        return best_match
    
    def resolve_method_path(self, method_name: str) -> Optional[PythonFunction]:
        """Enhanced method path resolution with multiple strategies"""
        
        # 1. Direct path match
        if method_name in self.python_functions:
            return self.python_functions[method_name]
        
        # 2. Function name only match (for cases where path differs)
        func_name = method_name.split('.')[-1]
        if func_name in self.function_name_index:
            # If multiple matches, prefer the most likely one
            matches = self.function_name_index[func_name]
            if len(matches) == 1:
                return matches[0]
            else:
                # Return best match based on path similarity
                best_match = None
                best_score = 0
                for match in matches:
                    score = SequenceMatcher(None, method_name, match.full_method_path).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = match
                return best_match
        
        # 3. Fuzzy matching for typos and variations
        fuzzy_match = self.fuzzy_match_function(method_name)
        if fuzzy_match:
            return fuzzy_match
        
        # 4. Search for partial path matches
        for full_path, func in self.python_functions.items():
            if method_name.endswith(full_path.split('.')[-1]):
                return func
        
        return None
    
    def scan_javascript_files(self) -> None:
        """Scan JavaScript files for calls to Python methods"""
        js_patterns = [
            "**/*.js",
            "**/*.ts", 
            "**/*.vue",  # Vue components may have JS
        ]
        
        total_files = 0
        excluded_files = 0
        
        for pattern in js_patterns:
            for js_file in self.project_root.glob(pattern):
                total_files += 1
                
                # Skip excluded directories and files
                if self.is_excluded_path(js_file):
                    excluded_files += 1
                    continue
                if any(part in str(js_file) for part in ['node_modules', 'dist', 'build', '.git']):
                    excluded_files += 1
                    continue
                    
                self._analyze_js_file(js_file)
                self.stats['js_files_scanned'] += 1
        
        print(f"JavaScript files: {total_files} found, {excluded_files} excluded, {self.stats['js_files_scanned']} scanned")
    
    def _analyze_js_file(self, file_path: Path) -> None:
        """Analyze a single JavaScript file for Python method calls"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for line_num, line in enumerate(lines, 1):
                for pattern in JS_PYTHON_PATTERNS:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        method_name = match.group(1)
                        
                        # Extract context (current line + next few lines for args)
                        context_lines = lines[max(0, line_num-1):min(len(lines), line_num+5)]
                        context = '\n'.join(context_lines)
                        
                        # Extract arguments
                        args = self._extract_args_from_context(context)
                        
                        # Determine call type
                        call_type = self._determine_call_type(line)
                        
                        js_call = JSCall(
                            file_path=str(file_path),
                            line_number=line_num,
                            method_name=method_name,
                            args=args,
                            context=context,
                            call_type=call_type
                        )
                        
                        self.js_calls.append(js_call)
                        self.stats['js_calls_found'] += 1
                        
        except Exception as e:
            print(f"Error analyzing JS file {file_path}: {e}")
    
    def _extract_args_from_context(self, context: str) -> Dict[str, Any]:
        """Extract arguments from JavaScript context"""
        args = {}
        
        for pattern in ARGS_PATTERNS:
            match = re.search(pattern, context, re.DOTALL)
            if match:
                args_str = match.group(1)
                
                # Simple parsing - look for key: value pairs
                # This could be enhanced with a proper JS parser
                key_value_pattern = r'[\'"]?(\w+)[\'"]?\s*:\s*([^,}]+)'
                for kv_match in re.finditer(key_value_pattern, args_str):
                    key = kv_match.group(1).strip('\'"')
                    value = kv_match.group(2).strip().rstrip(',')
                    args[key] = value
                break
        
        return args
    
    def _determine_call_type(self, line: str) -> str:
        """Determine the type of JavaScript call"""
        if 'frappe.call(' in line:
            return 'frappe.call'
        elif 'frm.call(' in line:
            return 'frm.call'
        elif 'this.call(' in line:
            return 'this.call'
        elif 'api.call(' in line:
            return 'api.call'
        else:
            return 'unknown'
    
    def scan_python_files(self) -> None:
        """Scan Python files for @frappe.whitelist() decorated functions"""
        total_files = 0
        excluded_files = 0
        
        for py_file in self.project_root.glob("**/*.py"):
            total_files += 1
            
            # Skip certain directories
            if any(part in str(py_file) for part in ['.git', '__pycache__', 'node_modules']):
                excluded_files += 1
                continue
            if self.is_excluded_path(py_file):
                excluded_files += 1
                continue
                
            self._analyze_py_file(py_file)
            self.stats['py_files_scanned'] += 1
        
        print(f"Python files: {total_files} found, {excluded_files} excluded, {self.stats['py_files_scanned']} scanned")
    
    def _analyze_py_file(self, file_path: Path) -> None:
        """Analyze a single Python file for whitelisted functions"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            # Parse AST for more accurate analysis
            try:
                tree = ast.parse(content)
            except SyntaxError:
                # If AST parsing fails, fall back to regex
                self._analyze_py_file_regex(file_path, lines)
                return
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function has @frappe.whitelist() decorator
                    is_whitelisted = False
                    for decorator in node.decorator_list:
                        if self._is_whitelist_decorator(decorator):
                            is_whitelisted = True
                            break
                    
                    if is_whitelisted:
                        python_func = self._create_python_function(file_path, node, lines)
                        if python_func:
                            self.python_functions[python_func.full_method_path] = python_func
                            # Index by function name for better lookup
                            self.function_name_index[python_func.function_name].append(python_func)
                            self.stats['python_functions_found'] += 1
                            
        except Exception as e:
            print(f"Error analyzing Python file {file_path}: {e}")
    
    def _is_whitelist_decorator(self, decorator) -> bool:
        """Check if a decorator is @frappe.whitelist()"""
        if isinstance(decorator, ast.Name) and decorator.id == 'whitelist':
            return True
        elif isinstance(decorator, ast.Attribute):
            if (isinstance(decorator.value, ast.Name) and 
                decorator.value.id == 'frappe' and 
                decorator.attr == 'whitelist'):
                return True
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name) and decorator.func.id == 'whitelist':
                return True
            elif isinstance(decorator.func, ast.Attribute):
                if (isinstance(decorator.func.value, ast.Name) and 
                    decorator.func.value.id == 'frappe' and 
                    decorator.func.attr == 'whitelist'):
                    return True
        return False
    
    def _create_python_function(self, file_path: Path, node: ast.FunctionDef, lines: List[str]) -> Optional[PythonFunction]:
        """Create a PythonFunction object from AST node"""
        try:
            # Build full method path
            relative_path = file_path.relative_to(self.project_root)
            module_path = str(relative_path).replace('/', '.').replace('\\', '.').replace('.py', '')
            full_method_path = f"{module_path}.{node.name}"
            
            # Extract parameters
            parameters = []
            required_params = []
            optional_params = []
            has_kwargs = False
            has_args = False
            
            for arg in node.args.args:
                if arg.arg != 'self':  # Skip self parameter
                    parameters.append(arg.arg)
            
            # Check for *args and **kwargs
            if node.args.vararg:
                has_args = True
                parameters.append(f"*{node.args.vararg.arg}")
            
            if node.args.kwarg:
                has_kwargs = True
                parameters.append(f"**{node.args.kwarg.arg}")
            
            # Determine required vs optional parameters
            defaults_count = len(node.args.defaults)
            if defaults_count > 0:
                required_params = parameters[:-defaults_count] if defaults_count < len(parameters) else []
                optional_params = parameters[-defaults_count:] if defaults_count > 0 else []
            else:
                required_params = parameters[:]
                optional_params = []
            
            # Extract docstring
            docstring = None
            if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Constant) and 
                isinstance(node.body[0].value.value, str)):
                docstring = node.body[0].value.value
            
            return PythonFunction(
                file_path=str(file_path),
                line_number=node.lineno,
                function_name=node.name,
                full_method_path=full_method_path,
                parameters=parameters,
                required_params=required_params,
                optional_params=optional_params,
                docstring=docstring,
                has_kwargs=has_kwargs,
                has_args=has_args
            )
            
        except Exception as e:
            print(f"Error creating Python function for {node.name}: {e}")
            return None
    
    def _analyze_py_file_regex(self, file_path: Path, lines: List[str]) -> None:
        """Fallback regex-based analysis for Python files"""
        whitelist_pattern = r'@frappe\.whitelist\(\)'
        function_pattern = r'def\s+(\w+)\s*\(([^)]*)\):'
        
        for i, line in enumerate(lines):
            if re.search(whitelist_pattern, line):
                # Look for function definition in next few lines
                for j in range(i+1, min(i+5, len(lines))):
                    func_match = re.search(function_pattern, lines[j])
                    if func_match:
                        func_name = func_match.group(1)
                        params_str = func_match.group(2)
                        
                        # Parse parameters
                        parameters = []
                        if params_str.strip():
                            for param in params_str.split(','):
                                param = param.strip()
                                if '=' in param:
                                    param = param.split('=')[0].strip()
                                if param and param != 'self':
                                    parameters.append(param)
                        
                        # Build method path
                        relative_path = file_path.relative_to(self.project_root)
                        module_path = str(relative_path).replace('/', '.').replace('\\', '.').replace('.py', '')
                        full_method_path = f"{module_path}.{func_name}"
                        
                        python_func = PythonFunction(
                            file_path=str(file_path),
                            line_number=j+1,
                            function_name=func_name,
                            full_method_path=full_method_path,
                            parameters=parameters,
                            required_params=parameters,  # Conservative assumption
                            optional_params=[],
                            has_kwargs=False,
                            has_args=False
                        )
                        
                        self.python_functions[full_method_path] = python_func
                        self.function_name_index[func_name].append(python_func)
                        self.stats['python_functions_found'] += 1
                        break
    
    def validate_parameters(self) -> None:
        """Cross-reference JavaScript calls with Python function signatures"""
        for js_call in self.js_calls:
            # Check if it's a framework method first
            if self.is_framework_method(js_call.method_name):
                self.stats['framework_methods_detected'] += 1
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=None,
                    issue_type="framework_method",
                    description=f"Framework method '{js_call.method_name}' - automatically handled by Frappe",
                    severity="ignore",
                    suggestion="No action needed - this is a valid framework method",
                    resolution_action="ignore"
                )
                self.issues.append(issue)
                continue
            
            # Try enhanced method resolution
            python_func = self.resolve_method_path(js_call.method_name)
            
            if not python_func:
                # Method not found
                severity = self.get_method_severity(js_call.method_name, js_call)
                
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=None,
                    issue_type="method_not_found",
                    description=f"Python method '{js_call.method_name}' not found or not whitelisted",
                    severity=severity,
                    suggestion=self._get_method_not_found_suggestion(js_call.method_name),
                    resolution_action=self._get_resolution_action(js_call.method_name)
                )
                self.issues.append(issue)
                continue
            
            # Validate parameters
            self._validate_call_parameters(js_call, python_func)
    
    def _get_method_not_found_suggestion(self, method_name: str) -> str:
        """Generate helpful suggestions for missing methods"""
        suggestions = []
        
        # Check if we have similar methods
        func_name = method_name.split('.')[-1]
        similar_methods = []
        
        for indexed_name in self.function_name_index.keys():
            score = SequenceMatcher(None, func_name, indexed_name).ratio()
            if score > 0.6:  # Lower threshold for suggestions
                similar_methods.append(indexed_name)
        
        if similar_methods:
            suggestions.append(f"Similar methods found: {', '.join(similar_methods[:3])}")
        
        if 'test' in method_name.lower() or 'debug' in method_name.lower():
            suggestions.append("Consider removing if this is a temporary test/debug method")
        else:
            suggestions.append("Check if method exists and has @frappe.whitelist() decorator")
        
        return "; ".join(suggestions)
    
    def _get_resolution_action(self, method_name: str) -> str:
        """Determine recommended resolution action"""
        if self.is_framework_method(method_name):
            return "ignore"
        elif any(keyword in method_name.lower() for keyword in ['test', 'debug']):
            return "review"
        else:
            return "fix"
    
    def _validate_call_parameters(self, js_call: JSCall, python_func: PythonFunction) -> None:
        """Validate parameters for a specific call"""
        js_params = set(js_call.args.keys())
        
        # Skip validation if function accepts **kwargs
        if python_func.has_kwargs:
            return
        
        # Check for missing required parameters
        for required_param in python_func.required_params:
            if required_param not in js_params:
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=python_func,
                    issue_type="missing_param",
                    description=f"Missing required parameter '{required_param}'",
                    severity="high",
                    suggestion=f"Add '{required_param}' to args in JavaScript call",
                    resolution_action="fix"
                )
                self.issues.append(issue)
        
        # Check for extra parameters (if function doesn't accept *args or **kwargs)
        if not python_func.has_args and not python_func.has_kwargs:
            all_valid_params = set(python_func.parameters)
            for js_param in js_params:
                if js_param not in all_valid_params:
                    issue = ValidationIssue(
                        js_call=js_call,
                        python_function=python_func,
                        issue_type="extra_param",
                        description=f"Extra parameter '{js_param}' not accepted by Python function",
                        severity="medium",
                        suggestion=f"Remove '{js_param}' from JavaScript call or add it to Python function signature",
                        resolution_action="fix"
                    )
                    self.issues.append(issue)
        
        self.stats['issues_found'] = len(self.issues)
    
    def generate_report(self, output_format: str = "text") -> str:
        """Generate validation report"""
        if output_format == "json":
            return self._generate_json_report()
        elif output_format == "html":
            return self._generate_html_report()
        else:
            return self._generate_text_report()
    
    def _generate_text_report(self) -> str:
        """Generate enhanced text-based validation report"""
        report = []
        report.append("Enhanced JavaScript-Python Parameter Validation Report")
        report.append("=" * 60)
        report.append("")
        
        # Statistics
        report.append("Statistics:")
        for key, value in self.stats.items():
            report.append(f"  {key.replace('_', ' ').title()}: {value}")
        report.append("")
        
        # Filter out ignored issues for main report
        actionable_issues = [issue for issue in self.issues if issue.severity != "ignore"]
        
        # Group issues by resolution action
        issues_by_action = defaultdict(list)
        for issue in actionable_issues:
            issues_by_action[issue.resolution_action].append(issue)
        
        # Report issues by action priority
        for action in ['fix', 'review', 'remove']:
            if action not in issues_by_action:
                continue
                
            issues = issues_by_action[action]
            report.append(f"{action.upper()} Priority Issues ({len(issues)}):")
            report.append("-" * 40)
            
            # Group by severity within action
            severity_groups = defaultdict(list)
            for issue in issues:
                severity_groups[issue.severity].append(issue)
            
            for severity in ['critical', 'high', 'medium', 'low']:
                if severity not in severity_groups:
                    continue
                
                severity_issues = severity_groups[severity]
                report.append(f"\n{severity.upper()} Severity ({len(severity_issues)} issues):")
                
                for issue in severity_issues:
                    report.append(f"\nFile: {issue.js_call.file_path}:{issue.js_call.line_number}")
                    report.append(f"Method: {issue.js_call.method_name}")
                    report.append(f"Issue: {issue.description}")
                    if issue.suggestion:
                        report.append(f"Suggestion: {issue.suggestion}")
        
        # Summary of framework methods (ignored)
        framework_issues = [issue for issue in self.issues if issue.severity == "ignore"]
        if framework_issues:
            report.append(f"\nFramework Methods Detected ({len(framework_issues)}):")
            report.append("-" * 40)
            for issue in framework_issues[:10]:  # Show first 10
                report.append(f"  {issue.js_call.method_name}")
            if len(framework_issues) > 10:
                report.append(f"  ... and {len(framework_issues) - 10} more")
        
        # Summary of found methods
        report.append(f"\nPython Methods Found ({len(self.python_functions)}):")
        report.append("-" * 35)
        for method_path, func in sorted(list(self.python_functions.items())[:20]):  # Show first 20
            param_str = ", ".join(func.parameters) if func.parameters else "no parameters"
            report.append(f"  {method_path}({param_str})")
        if len(self.python_functions) > 20:
            report.append(f"  ... and {len(self.python_functions) - 20} more")
        
        return "\n".join(report)
    
    def _generate_json_report(self) -> str:
        """Generate enhanced JSON validation report"""
        report_data = {
            "stats": self.stats,
            "config": self.config,
            "issues": [
                {
                    "file": issue.js_call.file_path,
                    "line": issue.js_call.line_number,
                    "method": issue.js_call.method_name,
                    "type": issue.issue_type,
                    "severity": issue.severity,
                    "description": issue.description,
                    "suggestion": issue.suggestion,
                    "resolution_action": issue.resolution_action,
                    "js_args": issue.js_call.args,
                    "python_params": issue.python_function.parameters if issue.python_function else []
                }
                for issue in self.issues
            ],
            "methods": {
                path: {
                    "file": func.file_path,
                    "line": func.line_number,
                    "function_name": func.function_name,
                    "parameters": func.parameters,
                    "required": func.required_params,
                    "optional": func.optional_params,
                    "has_kwargs": func.has_kwargs,
                    "has_args": func.has_args
                }
                for path, func in self.python_functions.items()
            },
            "function_index": {
                name: [func.full_method_path for func in functions]
                for name, functions in self.function_name_index.items()
            }
        }
        
        return json.dumps(report_data, indent=2)
    
    def _generate_html_report(self) -> str:
        """Generate enhanced HTML validation report"""
        # Filter actionable issues
        actionable_issues = [issue for issue in self.issues if issue.severity != "ignore"]
        framework_issues = [issue for issue in self.issues if issue.severity == "ignore"]
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Enhanced JS-Python Parameter Validation Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
                .stats {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                .section {{ margin: 20px 0; }}
                .issue {{ margin: 15px 0; padding: 15px; border-left: 4px solid; border-radius: 4px; }}
                .critical {{ border-color: #d32f2f; background: #ffebee; }}
                .high {{ border-color: #f57c00; background: #fff3e0; }}
                .medium {{ border-color: #fbc02d; background: #fffde7; }}
                .low {{ border-color: #388e3c; background: #e8f5e9; }}
                .ignore {{ border-color: #757575; background: #fafafa; }}
                .method-list {{ font-family: monospace; }}
                .code {{ font-family: monospace; background: #f5f5f5; padding: 2px 4px; border-radius: 2px; }}
                .badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; }}
                .badge-fix {{ background: #ffcdd2; color: #c62828; }}
                .badge-review {{ background: #fff3e0; color: #ef6c00; }}
                .badge-ignore {{ background: #f3e5f5; color: #7b1fa2; }}
                .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
                .summary-card {{ background: white; border: 1px solid #ddd; padding: 15px; border-radius: 5px; flex: 1; }}
                .toggle {{ cursor: pointer; user-select: none; }}
                .collapsible {{ display: none; }}
                h3.toggle:before {{ content: "▶ "; }}
                h3.toggle.active:before {{ content: "▼ "; }}
            </style>
            <script>
                function toggleSection(element) {{
                    element.classList.toggle('active');
                    const content = element.nextElementSibling;
                    content.style.display = content.style.display === 'block' ? 'none' : 'block';
                }}
            </script>
        </head>
        <body>
            <h1>Enhanced JavaScript-Python Parameter Validation Report</h1>
            
            <div class="stats">
                <h2>Validation Statistics</h2>
                <div class="summary">
                    <div class="summary-card">
                        <h4>Files Scanned</h4>
                        <p>JavaScript: {self.stats['js_files_scanned']}</p>
                        <p>Python: {self.stats['py_files_scanned']}</p>
                    </div>
                    <div class="summary-card">
                        <h4>Methods Found</h4>
                        <p>JS Calls: {self.stats['js_calls_found']}</p>
                        <p>Python Functions: {self.stats['python_functions_found']}</p>
                    </div>
                    <div class="summary-card">
                        <h4>Validation Results</h4>
                        <p>Issues: {len(actionable_issues)}</p>
                        <p>Framework Methods: {len(framework_issues)}</p>
                        <p>Fuzzy Matches: {self.stats['fuzzy_matches_found']}</p>
                    </div>
                </div>
            </div>
        """
        
        # Group actionable issues by resolution action
        issues_by_action = defaultdict(list)
        for issue in actionable_issues:
            issues_by_action[issue.resolution_action].append(issue)
        
        # Display issues by action
        for action in ['fix', 'review', 'remove']:
            if action not in issues_by_action:
                continue
                
            issues = issues_by_action[action]
            html += f"""
            <div class="section">
                <h2>{action.upper()} Priority Issues ({len(issues)})</h2>
            """
            
            # Group by severity
            severity_groups = defaultdict(list)
            for issue in issues:
                severity_groups[issue.severity].append(issue)
            
            for severity in ['critical', 'high', 'medium', 'low']:
                if severity not in severity_groups:
                    continue
                    
                severity_issues = severity_groups[severity]
                html += f"""
                <h3 class="toggle" onclick="toggleSection(this)">{severity.upper()} Severity ({len(severity_issues)} issues)</h3>
                <div class="collapsible">
                """
                
                for issue in severity_issues:
                    html += f"""
                    <div class="issue {severity}">
                        <div style="float: right;">
                            <span class="badge badge-{action}">{action.upper()}</span>
                        </div>
                        <strong>File:</strong> {issue.js_call.file_path}:{issue.js_call.line_number}<br>
                        <strong>Method:</strong> <span class="code">{issue.js_call.method_name}</span><br>
                        <strong>Issue:</strong> {issue.description}<br>
                        {f'<strong>Suggestion:</strong> {issue.suggestion}<br>' if issue.suggestion else ''}
                        <strong>JS Args:</strong> <span class="code">{list(issue.js_call.args.keys())}</span><br>
                        {f'<strong>Python Params:</strong> <span class="code">{issue.python_function.parameters}</span>' if issue.python_function else ''}
                    </div>
                    """
                
                html += "</div>"
            
            html += "</div>"
        
        # Framework methods section
        if framework_issues:
            html += f"""
            <div class="section">
                <h3 class="toggle" onclick="toggleSection(this)">Framework Methods Detected ({len(framework_issues)})</h3>
                <div class="collapsible">
                    <p>These methods are automatically handled by the Frappe framework and do not require action:</p>
            """
            
            for issue in framework_issues[:20]:  # Show first 20
                html += f"""
                <div class="issue ignore">
                    <span class="code">{issue.js_call.method_name}</span> - {issue.js_call.file_path}:{issue.js_call.line_number}
                </div>
                """
            
            if len(framework_issues) > 20:
                html += f"<p>... and {len(framework_issues) - 20} more framework methods</p>"
            
            html += "</div></div>"
        
        # Python methods summary
        html += f"""
            <div class="section">
                <h3 class="toggle" onclick="toggleSection(this)">Python Methods Found ({len(self.python_functions)})</h3>
                <div class="collapsible method-list">
        """
        
        for method_path, func in sorted(list(self.python_functions.items())[:50]):  # Show first 50
            param_str = ", ".join(func.parameters) if func.parameters else "no parameters"
            html += f"<div><strong>{method_path}</strong>({param_str}) - {func.file_path}:{func.line_number}</div>"
        
        if len(self.python_functions) > 50:
            html += f"<p>... and {len(self.python_functions) - 50} more methods</p>"
        
        html += """
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def run_validation(self) -> Dict[str, Any]:
        """Run complete enhanced validation process"""
        print("Enhanced JS-Python Parameter Validation Starting...")
        print(f"Configuration loaded: {len(self.config)} settings")
        
        print("Scanning JavaScript files...")
        self.scan_javascript_files()
        
        print("Scanning Python files...")
        self.scan_python_files()
        
        print("Building function index...")
        print(f"Indexed {len(self.function_name_index)} unique function names")
        
        print("Validating parameters...")
        self.validate_parameters()
        
        actionable_issues = len([i for i in self.issues if i.severity != "ignore"])
        
        return {
            'stats': self.stats,
            'total_issues': len(self.issues),
            'actionable_issues': actionable_issues,
            'framework_methods': len([i for i in self.issues if i.severity == "ignore"]),
            'critical_issues': len([i for i in self.issues if i.severity == 'critical']),
            'high_issues': len([i for i in self.issues if i.severity == 'high']),
        }

def main():
    """Main function for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced JavaScript-Python Parameter Validator")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--output-format", choices=["text", "json", "html"], default="text", help="Output format")
    parser.add_argument("--output-file", help="Output file (default: stdout)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--test-methods", help="Test specific methods (comma-separated)")
    
    args = parser.parse_args()
    
    validator = EnhancedJSPythonParameterValidator(args.project_root)
    
    if args.verbose:
        print("Starting enhanced validation...")
    
    results = validator.run_validation()
    
    if args.verbose:
        print(f"Validation complete. Found {results['actionable_issues']} actionable issues "
              f"({results['framework_methods']} framework methods ignored).")
    
    # Test specific methods if requested
    if args.test_methods:
        test_methods = [m.strip() for m in args.test_methods.split(',')]
        print(f"\nTesting resolution of specific methods: {test_methods}")
        for method in test_methods:
            resolved = validator.resolve_method_path(method)
            if resolved:
                print(f"✓ {method} -> {resolved.full_method_path} ({resolved.file_path})")
            else:
                print(f"✗ {method} -> Not found")
    
    report = validator.generate_report(args.output_format)
    
    if args.output_file:
        with open(args.output_file, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output_file}")
    else:
        print(report)
    
    # Return appropriate exit code
    if results['critical_issues'] > 0:
        return 2
    elif results['high_issues'] > 0:
        return 1
    else:
        return 0

if __name__ == "__main__":
    exit(main())