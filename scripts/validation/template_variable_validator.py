#!/usr/bin/env python3
"""
Modernized Template Variable Validator
Enhanced critical issue detection for Jinja template variables with sophisticated context matching
"""

import ast
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import difflib

class Severity(Enum):
    """Severity levels for template issues"""
    CRITICAL = "critical"  # Will break page rendering
    HIGH = "high"         # Will cause functionality issues
    MEDIUM = "medium"     # May cause display issues
    LOW = "low"           # Minor issues
    INFO = "info"         # Informational

class IssueCategory(Enum):
    """Categories of template issues"""
    MISSING_VARIABLE = "missing_variable"
    TYPE_MISMATCH = "type_mismatch"
    NULL_REFERENCE = "null_reference"
    SECURITY_RISK = "security_risk"
    PERFORMANCE = "performance"
    BEST_PRACTICE = "best_practice"

@dataclass
class TemplateIssue:
    """Represents a template validation issue"""
    severity: Severity
    category: IssueCategory
    template_file: str
    context_file: Optional[str]
    line_number: Optional[int]
    variable_name: Optional[str]
    message: str
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = None
    confidence: float = 0.8  # 0.0 to 1.0

@dataclass
class TemplateContext:
    """Enhanced context information for templates"""
    template_path: Path
    template_type: str  # portal, email, print, web
    variables_used: Set[str]
    filters_used: Set[str]
    includes: Set[str]
    extends: Optional[str] = None
    blocks: Set[str] = field(default_factory=set)
    macros: Set[str] = field(default_factory=set)
    is_base_template: bool = False

class ModernTemplateValidator:
    """Modernized template variable validator with enhanced detection"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.verbose = verbose
        self.template_contexts = {}  # {template_path: TemplateContext}
        self.context_providers = {}  # {py_file: {variables, methods}}
        self.issues = []
        
        # Enhanced tracking statistics
        self.stats = {
            'templates_scanned': 0,
            'context_matches_found': 0,
            'context_match_strategies': {
                'direct_mapping': 0,
                'parent_directory': 0,  
                'get_pattern': 0,
                'init_py': 0,
                'portal_pattern': 0,
                'doctype_pattern': 0,
                'email_pattern': 0,
                'fuzzy_matching': 0
            },
            'python_files_analyzed': 0,
            'critical_issues_found': 0,
            'security_issues_found': 0
        }
        
        # Critical variables that must be present for portal pages
        self.critical_portal_vars = {
            'user', 'member', 'support_email', 'site_name', 
            'navbar', 'footer', 'csrf_token'
        }
        
        # Critical variables for email templates
        self.critical_email_vars = {
            'recipient_name', 'site_name', 'support_email',
            'unsubscribe_link', 'sender_name'
        }
        
        # Important short variable names that shouldn't be filtered
        self.important_short_vars = {'id', 'me', 'db', 'to'}
        
        # Template keywords to exclude
        self.template_keywords = {'not', 'and', 'or', 'is', 'in', 'as', 'by'}
        
        # Known template variable patterns
        self.builtin_vars = self._build_builtin_vars()
        self.frappe_methods = self._build_frappe_methods()
        
    def _build_builtin_vars(self) -> Set[str]:
        """Build set of built-in Jinja and Frappe variables"""
        return {
            # Jinja built-ins
            '_', 'loop', 'super', 'self', 'varargs', 'kwargs',
            'range', 'dict', 'list', 'tuple', 'set', 'bool', 'int', 'float', 'str',
            'abs', 'all', 'any', 'attr', 'batch', 'capitalize', 'center',
            
            # Frappe built-ins
            'frappe', 'request', 'session', 'user', 'lang', 'direction',
            'base_template_path', 'csrf_token', 'boot', 'site_name',
            'developer_mode', 'main_content', 'page_container', 'page_content',
            'head_include', 'body_include', 'navbar', 'sidebar', 'footer',
            'no_cache', 'sitemap', 'route', 'website_settings', 'theme',
            
            # Common utility functions
            'get_url', 'get_formatted_html', 'scrub_urls', 'guess_mimetype',
            'now', 'today', 'nowdate', 'nowtime', 'get_datetime', 'format_date',
            'format_datetime', 'format_time', 'format_duration', 'format_currency',
            'flt', 'cint', 'cstr', 'encode', 'decode', 'strip_html'
        }
    
    def _build_frappe_methods(self) -> Set[str]:
        """Build set of Frappe methods available in templates"""
        return {
            'get_all', 'get_list', 'get_doc', 'get_value', 'get_single_value',
            'db', 'session', 'utils', 'throw', 'msgprint', 'get_hooks',
            'get_meta', 'get_field', 'has_permission', 'get_roles',
            'get_user', 'get_fullname', 'get_user_info', 'get_system_settings'
        }
    
    def detect_template_type(self, template_path: Path) -> str:
        """Detect the type of template based on path and content"""
        path_str = str(template_path)
        
        if 'email' in path_str or 'notification' in path_str:
            return 'email'
        elif 'print' in path_str or 'format' in path_str:
            return 'print'
        elif 'portal' in path_str or 'member' in path_str:
            return 'portal'
        elif 'www' in path_str or 'web' in path_str:
            return 'web'
        else:
            # Check content for hints
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    content = f.read(500)  # Read first 500 chars
                    
                if 'email-template' in content or 'message-body' in content:
                    return 'email'
                elif 'print-format' in content or 'page-break' in content:
                    return 'print'
                elif 'portal' in content or 'member-' in content:
                    return 'portal'
            except:
                pass
            
            return 'web'
    
    def extract_template_context(self, template_file: Path) -> TemplateContext:
        """Extract comprehensive context from template file"""
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return None
        
        context = TemplateContext(
            template_path=template_file,
            template_type=self.detect_template_type(template_file),
            variables_used=set(),
            filters_used=set(),
            includes=set()
        )
        
        # Extract extends
        extends_match = re.search(r'\{\%\s*extends\s+["\']([^"\']+)["\']', content)
        if extends_match:
            context.extends = extends_match.group(1)
            context.is_base_template = False
        
        # Extract blocks
        block_pattern = r'\{\%\s*block\s+([a-zA-Z_][a-zA-Z0-9_]*)'
        context.blocks = set(re.findall(block_pattern, content))
        if context.blocks and not context.extends:
            context.is_base_template = True
        
        # Extract macros
        macro_pattern = r'\{\%\s*macro\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
        context.macros = set(re.findall(macro_pattern, content))
        
        # Extract includes
        include_pattern = r'\{\%\s*include\s+["\']([^"\']+)["\']'
        context.includes = set(re.findall(include_pattern, content))
        
        # Extract variables with improved patterns
        variables = self._extract_variables_advanced(content)
        context.variables_used = variables
        
        # Extract filters
        filter_pattern = r'\|\s*([a-zA-Z_][a-zA-Z0-9_]*)'
        context.filters_used = set(re.findall(filter_pattern, content))
        
        return context
    
    def _extract_variables_advanced(self, content: str) -> Set[str]:
        """Advanced variable extraction with better accuracy"""
        variables = set()
        
        # Remove comments first
        content = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
        
        # Track loop variables and set variables to exclude them
        local_vars = set()
        
        # Extract for loop variables
        for_pattern = r'\{\%\s*for\s+([a-zA-Z_][a-zA-Z0-9_,\s]*)\s+in\s+([^%]+)\s*\%\}'
        for match in re.finditer(for_pattern, content):
            loop_vars = match.group(1)
            source_expr = match.group(2).strip()
            
            # Handle tuple unpacking: for key, value in items
            for var in loop_vars.split(','):
                var = var.strip()
                if var:
                    local_vars.add(var)
            
            # Extract source variable
            source_var = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*)', source_expr)
            if source_var:
                variables.add(source_var.group(1))
        
        # Extract set variables
        set_pattern = r'\{\%\s*set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*='
        local_vars.update(re.findall(set_pattern, content))
        
        # Extract with variables
        with_pattern = r'\{\%\s*with\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*='
        local_vars.update(re.findall(with_pattern, content))
        
        # Extract macro parameters
        macro_pattern = r'\{\%\s*macro\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(([^)]*)\)'
        for match in re.finditer(macro_pattern, content):
            params = match.group(1)
            for param in params.split(','):
                param = param.strip().split('=')[0].strip()
                if param:
                    local_vars.add(param)
        
        # Main variable extraction patterns
        patterns = [
            # {{ variable }}
            r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}',
            # {{ variable.property }} - capture base variable
            r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\.',
            # {{ variable|filter }}
            r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\|',
            # {{ variable[key] }}
            r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\[',
            # {% if variable %}
            r'\{\%\s*if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[%\s!=<>]',
            # {% elif variable %}
            r'\{\%\s*elif\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[%\s!=<>]',
            # {{ func(variable) }}
            r'\{\{[^}]*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[,)]',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            variables.update(matches)
        
        # Remove local variables and built-ins
        variables = variables - local_vars - self.builtin_vars
        
        # Filter out method calls (variables followed by parentheses)
        filtered_vars = set()
        for var in variables:
            # Check if it's a method call
            if not re.search(rf'\b{var}\s*\(', content):
                filtered_vars.add(var)
            elif re.search(rf'\b{var}\s*\[', content):  # Array access is valid
                filtered_vars.add(var)
        
        return filtered_vars
    
    def extract_python_context(self, py_file: Path) -> Dict[str, Any]:
        """Extract context variables from Python files with AST analysis"""
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return {}
        
        context_data = {
            'variables': set(),
            'methods': set(),
            'dynamic_vars': False,
            'has_get_context': False
        }
        
        try:
            tree = ast.parse(content)
            
            # Find get_context function
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name == 'get_context':
                        context_data['has_get_context'] = True
                        context_data['variables'].update(
                            self._extract_context_from_function(node)
                        )
                    elif node.name.startswith('get_'):
                        context_data['methods'].add(node.name)
            
        except SyntaxError:
            # Fallback to regex if AST parsing fails
            context_data['variables'].update(self._extract_context_regex(content))
        
        return context_data
    
    def _extract_context_from_function(self, func_node: ast.FunctionDef) -> Set[str]:
        """Extract context variables from a function AST node"""
        variables = set()
        
        for node in ast.walk(func_node):
            # context["key"] = value
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.Name) and node.value.id == 'context':
                    if isinstance(node.slice, ast.Constant):
                        variables.add(node.slice.value)
            
            # context.key = value
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == 'context':
                    variables.add(node.attr)
            
            # context.update({...})
            elif isinstance(node, ast.Call):
                if (hasattr(node.func, 'attr') and node.func.attr == 'update' and
                    hasattr(node.func, 'value') and 
                    isinstance(node.func.value, ast.Name) and 
                    node.func.value.id == 'context'):
                    
                    for arg in node.args:
                        if isinstance(arg, ast.Dict):
                            for key in arg.keys:
                                if isinstance(key, ast.Constant):
                                    variables.add(key.value)
            
            # return {...}
            elif isinstance(node, ast.Return):
                if isinstance(node.value, ast.Dict):
                    for key in node.value.keys:
                        if isinstance(key, ast.Constant):
                            variables.add(key.value)
        
        return variables
    
    def _extract_context_regex(self, content: str) -> Set[str]:
        """Fallback regex extraction for context variables"""
        variables = set()
        
        patterns = [
            r'context\[["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']]\s*=',
            r'context\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=',
            r'return\s*\{[^}]*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:\s*',
            r'context\.update\s*\([^)]*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:\s*'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            variables.update(matches)
        
        return variables
    
    def validate_critical_variables(self, context: TemplateContext, 
                                   provided_vars: Set[str]) -> List[TemplateIssue]:
        """Check for critical missing variables based on template type"""
        issues = []
        
        if context.template_type == 'portal':
            missing_critical = self.critical_portal_vars - provided_vars
            for var in missing_critical:
                if var in context.variables_used:
                    issues.append(TemplateIssue(
                        severity=Severity.CRITICAL,
                        category=IssueCategory.MISSING_VARIABLE,
                        template_file=str(context.template_path.relative_to(self.app_path)),
                        context_file=None,
                        line_number=None,
                        variable_name=var,
                        message=f"Critical portal variable '{var}' is not provided",
                        suggestion=f"Add 'context[\"{var}\"] = ...' in get_context()",
                        confidence=0.95
                    ))
        
        elif context.template_type == 'email':
            missing_critical = self.critical_email_vars - provided_vars
            for var in missing_critical:
                if var in context.variables_used:
                    issues.append(TemplateIssue(
                        severity=Severity.HIGH,
                        category=IssueCategory.MISSING_VARIABLE,
                        template_file=str(context.template_path.relative_to(self.app_path)),
                        context_file=None,
                        line_number=None,
                        variable_name=var,
                        message=f"Critical email variable '{var}' is not provided",
                        suggestion=f"Ensure '{var}' is set in email context",
                        confidence=0.9
                    ))
        
        return issues
    
    def check_null_reference_risks(self, template_path: Path) -> List[TemplateIssue]:
        """Check for potential null reference issues in templates - selective approach"""
        issues = []
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
        except Exception:
            return issues
        
        # Patterns that commonly cause actual runtime errors
        risky_patterns = [
            # Deep object chaining (3+ levels) without safety
            (r'{{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\.[a-zA-Z_][a-zA-Z0-9_]*){2,}(?![^}]*(?:\||default|or\s))', 
             'Deep object property access without null safety', Severity.MEDIUM),
            # Array index access on potentially null variables
            (r'{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\[\d+\](?![^}]*(?:\||default|or\s))',
             'Array index access without bounds checking', Severity.LOW),
            # Method calls on potentially null objects (2+ levels)
            (r'{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\.\w+\.\w+\([^)]*\)(?![^}]*(?:\||default|or\s))',
             'Method call on nested object without null check', Severity.MEDIUM),
        ]
        
        for line_num, line in enumerate(lines, 1):
            for pattern, risk_desc, severity in risky_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    var_name = match.group(1)
                    
                    # Skip if variable is protected by better context detection
                    if self._is_variable_context_protected(var_name, line_num, content, lines):
                        continue
                    
                    # Only report if variable is not a known safe built-in
                    if var_name not in self.builtin_vars and var_name not in {'member', 'doc', 'data'}:
                        issues.append(TemplateIssue(
                            severity=severity,
                            category=IssueCategory.NULL_REFERENCE,
                            template_file=str(template_path.relative_to(self.app_path)),
                            context_file=None,
                            line_number=line_num,
                            variable_name=var_name,
                            message=f"{risk_desc}: '{var_name}' may cause runtime error",
                            suggestion=f"Add safety check: '{{% if {var_name} %}}' or use '{{{{ {var_name} | default(...) }}}}'",
                            code_snippet=line.strip()[:100],
                            confidence=0.75
                        ))
        
        return issues
    
    def _is_variable_context_protected(self, var_name: str, line_num: int, 
                                     content: str, lines: List[str]) -> bool:
        """Check if variable is protected by broader template context"""
        
        # Look for immediate protection on the same line or previous line
        check_lines = []
        if line_num > 1:
            check_lines.append(lines[line_num - 2])  # Previous line
        check_lines.append(lines[line_num - 1])  # Current line
        
        for check_line in check_lines:
            # Direct conditional protection
            if f'if {var_name}' in check_line and '%}' in check_line:
                return True
            # Conditional with additional checks
            if f'if {var_name} and not {var_name}.error' in check_line:
                return True
            # Property conditional
            if re.search(f'{var_name}\\.[a-zA-Z_][a-zA-Z0-9_]*', check_line) and 'if' in check_line:
                return True
        
        # Look for broader context - search backwards for protective blocks
        search_start = max(0, line_num - 50)  # Look back up to 50 lines
        context_section = '\n'.join(lines[search_start:line_num])
        
        # Check for conditional blocks that protect this variable
        if_patterns = [
            f'{{% if {var_name} %}}',
            f'{{% if {var_name} and not {var_name}\\.error %}}',
            f'{{% if {var_name} and {var_name}\\.[a-zA-Z_][a-zA-Z0-9_]* %}}'
        ]
        
        for pattern in if_patterns:
            if re.search(pattern.replace('{%', r'\{%').replace('%}', r'%\}'), context_section):
                # Found opening if, check if we haven't hit an endif yet
                if not self._has_matching_endif_before_line(context_section, line_num - search_start):
                    return True
        
        # Check for loop context protection
        for_pattern = f'{{% for [a-zA-Z_][a-zA-Z0-9_]* in {var_name} %}}'
        if re.search(for_pattern.replace('{%', r'\{%').replace('%}', r'%\}'), context_section):
            return True
        
        # Check if variable is defined in a loop (making it safe within the loop)
        loop_var_pattern = f'{{% for {var_name} in [a-zA-Z_][a-zA-Z0-9_]* %}}'
        if re.search(loop_var_pattern.replace('{%', r'\{%').replace('%}', r'%\}'), context_section):
            return True
        
        return False
    
    def _has_matching_endif_before_line(self, context_section: str, relative_line: int) -> bool:
        """Check if there's a matching endif before the target line"""
        lines = context_section.split('\n')
        if relative_line >= len(lines):
            return False
            
        # Simple check - count if/endif pairs
        if_count = 0
        for i in range(relative_line):
            line = lines[i]
            if re.search(r'\\{%\\s*if\\s+', line):
                if_count += 1
            elif re.search(r'\\{%\\s*endif\\s*%\\}', line):
                if_count -= 1
        
        # If if_count is 0, all if blocks were closed
        return if_count == 0
    
    def check_security_issues(self, template_path: Path) -> List[TemplateIssue]:
        """Check for security issues in templates with context awareness"""
        issues = []
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
        except Exception:
            return issues
        
        for line_num, line in enumerate(lines, 1):
            # Check for |safe filter usage
            safe_match = re.search(r'{{([^}]*?)\|\s*safe(?:\s|}})', line)
            if safe_match:
                context = safe_match.group(1).strip()
                
                # Determine if this is a legitimate use of |safe
                if 'tojson' in context:
                    # JSON serialization is generally safe
                    severity = Severity.LOW
                    message = "JSON serialization with |safe - verify data is trusted"
                    suggestion = "Ensure JSON data doesn't contain user input or is properly sanitized"
                    confidence = 0.6
                elif any(x in context for x in ['_html', 'enhanced_menu', 'address_display']):
                    # HTML content needs careful review
                    severity = Severity.HIGH
                    message = "HTML content with |safe filter - high XSS risk"
                    suggestion = "Ensure HTML is sanitized server-side before rendering"
                    confidence = 0.9
                else:
                    # Generic |safe usage
                    severity = Severity.MEDIUM
                    message = "Using |safe filter disables HTML escaping"
                    suggestion = "Verify this content is trusted and doesn't contain user input"
                    confidence = 0.75
                
                issues.append(TemplateIssue(
                    severity=severity,
                    category=IssueCategory.SECURITY_RISK,
                    template_file=str(template_path.relative_to(self.app_path)),
                    context_file=None,
                    line_number=line_num,
                    variable_name=None,
                    message=message,
                    suggestion=suggestion,
                    code_snippet=line.strip()[:100],
                    confidence=confidence
                ))
            
            # Check for autoescape disabled
            if re.search(r'{%\s*autoescape\s+false', line):
                issues.append(TemplateIssue(
                    severity=Severity.CRITICAL,
                    category=IssueCategory.SECURITY_RISK,
                    template_file=str(template_path.relative_to(self.app_path)),
                    context_file=None,
                    line_number=line_num,
                    variable_name=None,
                    message="Autoescape disabled - severe XSS vulnerability risk",
                    suggestion="Remove autoescape false unless absolutely necessary and data is fully trusted",
                    code_snippet=line.strip()[:100],
                    confidence=0.95
                ))
            
            # Check for direct request.args usage
            if re.search(r'{{[^}]*?request\.args[^}]*?}}', line):
                issues.append(TemplateIssue(
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY_RISK,
                    template_file=str(template_path.relative_to(self.app_path)),
                    context_file=None,
                    line_number=line_num,
                    variable_name=None,
                    message="Direct use of request.args without validation",
                    suggestion="Validate and sanitize request parameters server-side before template rendering",
                    code_snippet=line.strip()[:100],
                    confidence=0.85
                ))
        
        return issues
    
    def match_template_to_context(self, template_path: Path) -> Optional[Path]:
        """Intelligently match template to its context provider with 8 sophisticated strategies"""
        candidates = []
        
        # Strategy 1: Direct mapping (template.html -> template.py)
        py_path = template_path.with_suffix('.py')
        if py_path.exists():
            candidates.append((py_path, 10, 'direct_mapping'))  # High priority
        
        # Strategy 2: Check parent directory
        parent_py = template_path.parent / f"{template_path.stem}.py"
        if parent_py.exists():
            candidates.append((parent_py, 9, 'parent_directory'))
        
        # Strategy 3: Look for get_[name].py pattern
        get_py = template_path.parent / f"get_{template_path.stem}.py"
        if get_py.exists():
            candidates.append((get_py, 8, 'get_pattern'))
        
        # Strategy 4: Check __init__.py in same directory
        init_py = template_path.parent / "__init__.py"
        if init_py.exists():
            try:
                with open(init_py, 'r') as f:
                    if 'get_context' in f.read():
                        candidates.append((init_py, 7, 'init_py'))
            except (IOError, UnicodeDecodeError):
                pass
        
        # Strategy 5: Portal page pattern (pages/name.html -> web_form/name.py or page/name.py)
        if 'pages' in template_path.parts:
            web_form_py = self.app_path / "web_form" / f"{template_path.stem}.py"
            if web_form_py.exists():
                candidates.append((web_form_py, 9, 'portal_pattern'))
            
            page_py = self.app_path / "page" / f"{template_path.stem}.py"  
            if page_py.exists():
                candidates.append((page_py, 8, 'portal_pattern'))
        
        # Strategy 6: DocType template pattern (doctype/name/name.py)
        if template_path.stem != 'list':  # Avoid generic list templates
            try:
                doctype_path = self.app_path / "doctype"
                if doctype_path.exists():
                    for doctype_dir in doctype_path.glob("*"):
                        if doctype_dir.is_dir():
                            doctype_py = doctype_dir / f"{doctype_dir.name}.py"
                            if doctype_py.exists() and template_path.stem.lower() in doctype_dir.name.lower():
                                candidates.append((doctype_py, 6, 'doctype_pattern'))
            except (OSError, IOError):
                pass
        
        # Strategy 7: Email template pattern (emails/name.html -> doctype/.../name.py)
        if 'email' in template_path.parts:
            try:
                # Search for Python files that might generate this email
                for py_file in self.app_path.rglob("*.py"):
                    if py_file.is_file() and template_path.stem.lower() in py_file.stem.lower():
                        candidates.append((py_file, 5, 'email_pattern'))
                        if len(candidates) > 20:  # Limit search to prevent performance issues
                            break
            except (OSError, IOError):
                pass
        
        # Strategy 8: Fuzzy name matching within same directory tree  
        try:
            template_name_parts = set(template_path.stem.lower().split('_'))
            for py_file in template_path.parent.rglob("*.py"):
                if py_file.is_file():
                    py_name_parts = set(py_file.stem.lower().split('_'))
                    # Check for significant overlap in name parts
                    overlap = len(template_name_parts.intersection(py_name_parts))
                    if overlap >= 2:  # At least 2 matching word parts
                        candidates.append((py_file, 3 + overlap, 'fuzzy_matching'))
        except (OSError, IOError):
            pass
        
        # Return highest priority candidate and track strategy used
        if candidates:
            best_match = sorted(candidates, key=lambda x: x[1], reverse=True)[0]
            py_file, priority, strategy = best_match
            self.stats['context_matches_found'] += 1
            self.stats['context_match_strategies'][strategy] += 1
            
            if self.verbose:
                print(f"  🎯 Context match: {template_path.name} -> {py_file.name} (strategy: {strategy})")
            
            return py_file
        
        return None
    
    def validate_template(self, template_path: Path) -> List[TemplateIssue]:
        """Comprehensive validation of a single template"""
        issues = []
        
        # Extract template context
        context = self.extract_template_context(template_path)
        if not context:
            return issues
        
        # Find matching Python context provider
        py_file = self.match_template_to_context(template_path)
        provided_vars = set()
        
        if py_file:
            self.stats['python_files_analyzed'] += 1
            py_context = self.extract_python_context(py_file)
            provided_vars = py_context.get('variables', set())
            
            # Check for missing variables - only report critical ones to reduce noise
            missing_vars = context.variables_used - provided_vars - self.builtin_vars
            
            # Filter to only critical/high-impact missing variables
            critical_missing = []
            for var in missing_vars:
                # Skip template keywords but keep important short variables
                if var in self.template_keywords:
                    continue
                    
                # Skip very short vars unless they're important
                if len(var) <= 2 and var not in self.important_short_vars:
                    continue
                
                # Determine if variable is critical based on patterns and context
                is_critical = (
                    var in self.critical_portal_vars or 
                    var in self.critical_email_vars or
                    var.endswith(('_email', '_url', '_link', '_name', '_date', '_time')) or
                    var.startswith(('has_', 'is_', 'can_', 'show_')) or
                    any(keyword in var for keyword in ['support', 'payment', 'member', 'user', 'csrf'])
                )
                
                if is_critical:
                    critical_missing.append(var)
            
            for var in critical_missing:
                # Try to find similar variable names
                similar = difflib.get_close_matches(var, provided_vars, n=2, cutoff=0.7)
                suggestion = f"Did you mean: {', '.join(similar)}?" if similar else None
                
                issues.append(TemplateIssue(
                    severity=Severity.HIGH if var in self.critical_portal_vars else Severity.MEDIUM,
                    category=IssueCategory.MISSING_VARIABLE,
                    template_file=str(template_path.relative_to(self.app_path)),
                    context_file=str(py_file.relative_to(self.app_path)) if py_file else None,
                    line_number=None,
                    variable_name=var,
                    message=f"Critical variable '{var}' used in template but not provided in context",
                    suggestion=suggestion,
                    confidence=0.8
                ))
        
        # Check critical variables
        issues.extend(self.validate_critical_variables(context, provided_vars))
        
        # Check security issues with context awareness
        issues.extend(self.check_security_issues(template_path))
        
        # Selectively check null reference risks for high-impact patterns
        null_ref_issues = self.check_null_reference_risks(template_path)
        # Only include null reference issues with higher confidence
        issues.extend([issue for issue in null_ref_issues if issue.confidence >= 0.7])
        
        return issues
    
    def run_validation(self) -> Tuple[List[TemplateIssue], bool]:
        """Run comprehensive template validation"""
        print("🔍 Running Modernized Template Variable Validation...")
        
        # Find all templates
        template_patterns = [
            "templates/**/*.html",
            "www/**/*.html",
            "email/**/*.html",
            "print_format/**/*.html"
        ]
        
        all_templates = []
        for pattern in template_patterns:
            all_templates.extend(self.app_path.rglob(pattern))
        
        print(f"📋 Found {len(all_templates)} templates to validate")
        
        # Validate each template
        all_issues = []
        for template in all_templates:
            self.stats['templates_scanned'] += 1
            issues = self.validate_template(template)
            all_issues.extend(issues)
            
            # Track issue types
            for issue in issues:
                if issue.severity in [Severity.CRITICAL, Severity.HIGH]:
                    self.stats['critical_issues_found'] += 1
                if issue.category == IssueCategory.SECURITY_RISK:
                    self.stats['security_issues_found'] += 1
        
        # Sort issues by severity
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4
        }
        
        all_issues.sort(key=lambda x: (severity_order[x.severity], x.template_file))
        
        return all_issues, len(all_issues) == 0
    
    def generate_report(self, issues: List[TemplateIssue]) -> str:
        """Generate detailed validation report"""
        if not issues:
            return "✅ No template validation issues found!"
        
        report = []
        report.append("📊 Template Validation Report")
        report.append("=" * 80)
        report.append(f"Total issues: {len(issues)}\n")
        
        # Group by severity
        by_severity = {}
        for issue in issues:
            by_severity.setdefault(issue.severity, []).append(issue)
        
        # Report by severity
        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, 
                        Severity.LOW, Severity.INFO]:
            if severity in by_severity:
                severity_issues = by_severity[severity]
                
                icon = {
                    Severity.CRITICAL: "🔴",
                    Severity.HIGH: "🟠",
                    Severity.MEDIUM: "🟡",
                    Severity.LOW: "🔵",
                    Severity.INFO: "⚪"
                }[severity]
                
                report.append(f"\n{icon} {severity.value.upper()} ({len(severity_issues)} issues)")
                report.append("-" * 60)
                
                # Group by template file
                by_template = {}
                for issue in severity_issues:
                    by_template.setdefault(issue.template_file, []).append(issue)
                
                for template_file, template_issues in by_template.items():
                    report.append(f"\n  📄 {template_file}")
                    
                    for issue in template_issues[:5]:  # Show first 5 issues per file
                        if issue.line_number:
                            report.append(f"     Line {issue.line_number}: {issue.message}")
                        else:
                            report.append(f"     {issue.message}")
                        
                        if issue.variable_name:
                            report.append(f"     Variable: {issue.variable_name}")
                        
                        if issue.suggestion:
                            report.append(f"     💡 {issue.suggestion}")
                        
                        if issue.code_snippet:
                            report.append(f"     Code: {issue.code_snippet[:80]}...")
                        
                        report.append("")
                    
                    if len(template_issues) > 5:
                        report.append(f"     ... and {len(template_issues) - 5} more issues")
        
        # Summary statistics
        report.append("\n" + "=" * 80)
        report.append("📈 Summary:")
        
        critical_count = len(by_severity.get(Severity.CRITICAL, []))
        high_count = len(by_severity.get(Severity.HIGH, []))
        
        if critical_count > 0:
            report.append(f"⚠️  {critical_count} CRITICAL issues require immediate attention!")
        if high_count > 0:
            report.append(f"⚠️  {high_count} HIGH severity issues should be fixed soon")
        
        # Most affected templates
        template_counts = {}
        for issue in issues:
            template_counts[issue.template_file] = template_counts.get(issue.template_file, 0) + 1
        
        top_templates = sorted(template_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_templates:
            report.append("\n🎯 Most affected templates:")
            for template, count in top_templates:
                report.append(f"   - {template}: {count} issues")
        
        return '\n'.join(report)


def main():
    """Main entry point with modern validation"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Parse arguments
    verbose = '--verbose' in sys.argv
    
    print("🚀 Modernized Template Variable Validator")
    print("   Enhanced critical issue detection")
    print("   Security and null-reference checking")
    print("")
    
    validator = ModernTemplateValidator(app_path, verbose=verbose)
    issues, success = validator.run_validation()
    
    print("\n" + "=" * 80)
    report = validator.generate_report(issues)
    print(report)
    
    # Enhanced statistics reporting
    if verbose:
        print(f"\n🔧 Enhanced Validation Statistics:")
        print(f"   Templates processed: {validator.stats['templates_scanned']}")
        print(f"   Context matches found: {validator.stats['context_matches_found']}")
        print(f"   Python files analyzed: {validator.stats['python_files_analyzed']}")
        
        print(f"\n📊 Context Matching Strategy Performance:")
        for strategy, count in validator.stats['context_match_strategies'].items():
            if count > 0:
                percentage = (count / validator.stats['context_matches_found'] * 100) if validator.stats['context_matches_found'] > 0 else 0
                print(f"   {strategy.replace('_', ' ').title()}: {count} ({percentage:.1f}%)")
    
    # Return appropriate exit code
    critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    high_count = sum(1 for i in issues if i.severity == Severity.HIGH)
    
    if critical_count > 0:
        return 2  # Critical issues
    elif high_count > 0:
        return 1  # High severity issues
    else:
        return 0  # Success or only minor issues


if __name__ == "__main__":
    exit(main())