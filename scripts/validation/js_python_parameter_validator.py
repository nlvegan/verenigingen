#!/usr/bin/env python3
"""
JavaScript-Python Parameter Validation System

This validator analyzes JavaScript files for calls to Python endpoints and validates
that the parameters passed from JavaScript match the expected Python function signatures.

Key Features:
- Detects frappe.call() and other JS-Python interaction patterns
- Extracts Python function signatures from @frappe.whitelist() decorated functions
- Cross-references to identify parameter mismatches
- Integrates with existing field validation infrastructure
- Generates actionable reports with specific line numbers and suggestions
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
    issue_type: str  # missing_param, extra_param, type_mismatch, method_not_found
    description: str
    severity: str = "medium"  # low, medium, high, critical
    suggestion: str = ""

class JSPythonParameterValidator:
    """Main validator class for JavaScript-Python parameter validation"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.js_calls: List[JSCall] = []
        self.python_functions: Dict[str, PythonFunction] = {}
        self.issues: List[ValidationIssue] = []
        self.stats = {
            'js_files_scanned': 0,
            'py_files_scanned': 0,
            'js_calls_found': 0,
            'python_functions_found': 0,
            'issues_found': 0,
        }
    
    def scan_javascript_files(self) -> None:
        """Scan JavaScript files for calls to Python methods"""
        js_patterns = [
            "**/*.js",
            "**/*.ts", 
            "**/*.vue",  # Vue components may have JS
        ]
        
        for pattern in js_patterns:
            for js_file in self.project_root.glob(pattern):
                # Skip node_modules and other excluded directories
                if any(part in str(js_file) for part in ['node_modules', 'dist', 'build', '.git']):
                    continue
                    
                self._analyze_js_file(js_file)
                self.stats['js_files_scanned'] += 1
    
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
        for py_file in self.project_root.glob("**/*.py"):
            # Skip certain directories
            if any(part in str(py_file) for part in ['.git', '__pycache__', 'node_modules']):
                continue
                
            self._analyze_py_file(py_file)
            self.stats['py_files_scanned'] += 1
    
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
                        self.stats['python_functions_found'] += 1
                        break
    
    def validate_parameters(self) -> None:
        """Cross-reference JavaScript calls with Python function signatures"""
        for js_call in self.js_calls:
            python_func = self.python_functions.get(js_call.method_name)
            
            if not python_func:
                # Method not found
                issue = ValidationIssue(
                    js_call=js_call,
                    python_function=None,
                    issue_type="method_not_found",
                    description=f"Python method '{js_call.method_name}' not found or not whitelisted",
                    severity="high",
                    suggestion=f"Check if method exists and has @frappe.whitelist() decorator"
                )
                self.issues.append(issue)
                continue
            
            # Validate parameters
            self._validate_call_parameters(js_call, python_func)
    
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
                    suggestion=f"Add '{required_param}' to args in JavaScript call"
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
                        suggestion=f"Remove '{js_param}' from JavaScript call or add it to Python function signature"
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
        """Generate text-based validation report"""
        report = []
        report.append("JavaScript-Python Parameter Validation Report")
        report.append("=" * 50)
        report.append("")
        
        # Statistics
        report.append("Statistics:")
        for key, value in self.stats.items():
            report.append(f"  {key.replace('_', ' ').title()}: {value}")
        report.append("")
        
        # Group issues by severity
        issues_by_severity = defaultdict(list)
        for issue in self.issues:
            issues_by_severity[issue.severity].append(issue)
        
        # Report issues by severity
        for severity in ['critical', 'high', 'medium', 'low']:
            if severity not in issues_by_severity:
                continue
                
            issues = issues_by_severity[severity]
            report.append(f"{severity.upper()} Priority Issues ({len(issues)}):")
            report.append("-" * 30)
            
            for issue in issues:
                report.append(f"File: {issue.js_call.file_path}:{issue.js_call.line_number}")
                report.append(f"Method: {issue.js_call.method_name}")
                report.append(f"Issue: {issue.description}")
                if issue.suggestion:
                    report.append(f"Suggestion: {issue.suggestion}")
                report.append("")
        
        # Summary of found methods
        report.append("Python Methods Found:")
        report.append("-" * 25)
        for method_path, func in sorted(self.python_functions.items()):
            param_str = ", ".join(func.parameters) if func.parameters else "no parameters"
            report.append(f"  {method_path}({param_str})")
        
        return "\n".join(report)
    
    def _generate_json_report(self) -> str:
        """Generate JSON validation report"""
        report_data = {
            "stats": self.stats,
            "issues": [
                {
                    "file": issue.js_call.file_path,
                    "line": issue.js_call.line_number,
                    "method": issue.js_call.method_name,
                    "type": issue.issue_type,
                    "severity": issue.severity,
                    "description": issue.description,
                    "suggestion": issue.suggestion,
                    "js_args": issue.js_call.args,
                    "python_params": issue.python_function.parameters if issue.python_function else []
                }
                for issue in self.issues
            ],
            "methods": {
                path: {
                    "file": func.file_path,
                    "line": func.line_number,
                    "parameters": func.parameters,
                    "required": func.required_params,
                    "optional": func.optional_params,
                    "has_kwargs": func.has_kwargs,
                    "has_args": func.has_args
                }
                for path, func in self.python_functions.items()
            }
        }
        
        return json.dumps(report_data, indent=2)
    
    def _generate_html_report(self) -> str:
        """Generate HTML validation report"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>JS-Python Parameter Validation Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .stats {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
                .issue {{ margin: 15px 0; padding: 15px; border-left: 4px solid; }}
                .critical {{ border-color: #d32f2f; background: #ffebee; }}
                .high {{ border-color: #f57c00; background: #fff3e0; }}
                .medium {{ border-color: #fbc02d; background: #fffde7; }}
                .low {{ border-color: #388e3c; background: #e8f5e9; }}
                .method-list {{ font-family: monospace; }}
                .code {{ font-family: monospace; background: #f5f5f5; padding: 2px 4px; }}
            </style>
        </head>
        <body>
            <h1>JavaScript-Python Parameter Validation Report</h1>
            
            <div class="stats">
                <h2>Statistics</h2>
                <ul>
        """
        
        for key, value in self.stats.items():
            html += f"<li>{key.replace('_', ' ').title()}: {value}</li>"
        
        html += """
                </ul>
            </div>
            
            <h2>Issues Found</h2>
        """
        
        # Group and display issues
        issues_by_severity = defaultdict(list)
        for issue in self.issues:
            issues_by_severity[issue.severity].append(issue)
        
        for severity in ['critical', 'high', 'medium', 'low']:
            if severity not in issues_by_severity:
                continue
                
            issues = issues_by_severity[severity]
            html += f"<h3>{severity.upper()} Priority ({len(issues)} issues)</h3>"
            
            for issue in issues:
                html += f"""
                <div class="issue {severity}">
                    <strong>File:</strong> {issue.js_call.file_path}:{issue.js_call.line_number}<br>
                    <strong>Method:</strong> <span class="code">{issue.js_call.method_name}</span><br>
                    <strong>Issue:</strong> {issue.description}<br>
                    {f'<strong>Suggestion:</strong> {issue.suggestion}<br>' if issue.suggestion else ''}
                    <strong>JS Args:</strong> <span class="code">{list(issue.js_call.args.keys())}</span><br>
                    {f'<strong>Python Params:</strong> <span class="code">{issue.python_function.parameters}</span>' if issue.python_function else ''}
                </div>
                """
        
        html += """
            <h2>Python Methods Found</h2>
            <div class="method-list">
        """
        
        for method_path, func in sorted(self.python_functions.items()):
            param_str = ", ".join(func.parameters) if func.parameters else "no parameters"
            html += f"<div><strong>{method_path}</strong>({param_str})</div>"
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return html
    
    def run_validation(self) -> Dict[str, Any]:
        """Run complete validation process"""
        print("Scanning JavaScript files...")
        self.scan_javascript_files()
        
        print("Scanning Python files...")
        self.scan_python_files()
        
        print("Validating parameters...")
        self.validate_parameters()
        
        return {
            'stats': self.stats,
            'issues_count': len(self.issues),
            'critical_issues': len([i for i in self.issues if i.severity == 'critical']),
            'high_issues': len([i for i in self.issues if i.severity == 'high']),
        }

def main():
    """Main function for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="JavaScript-Python Parameter Validator")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--output-format", choices=["text", "json", "html"], default="text", help="Output format")
    parser.add_argument("--output-file", help="Output file (default: stdout)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    validator = JSPythonParameterValidator(args.project_root)
    
    if args.verbose:
        print("Starting validation...")
    
    results = validator.run_validation()
    
    if args.verbose:
        print(f"Validation complete. Found {results['issues_count']} issues.")
    
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