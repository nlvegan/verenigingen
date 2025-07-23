#!/usr/bin/env python3
"""
Template Variable Validator
Validates that Jinja template variables are properly provided by Python context
"""

import ast
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple


class TemplateVariableValidator:
    """Validates template variables across HTML templates and Python context providers"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.template_variables = {}  # {template_file: {variables}}
        self.context_providers = {}   # {py_file: {context_variables}}
        self.violations = []
        
    def extract_template_variables(self, template_file: Path) -> Set[str]:
        """Extract Jinja variables from HTML template files"""
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return set()
        
        variables = set()
        loop_variables = set()
        template_set_variables = set()
        macro_parameters = set()
        
        # First, identify loop variables that are locally defined
        # Pattern: {% for item in variable %} or {% for item in complex.expression %}
        for_loop_pattern = r'\{\%\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+([^%]+)\s*\%\}'
        for match in re.finditer(for_loop_pattern, content):
            loop_var = match.group(1)  # The iteration variable (e.g., 'payment')
            source_expr = match.group(2).strip()  # The source expression
            loop_variables.add(loop_var)
            
            # Extract the root variable from complex expressions
            # e.g., dashboard_data.member_overview.recent_members -> dashboard_data
            # e.g., payment_timeline -> payment_timeline
            root_var = source_expr.split('.')[0].split('[')[0].strip()
            if root_var and root_var.replace('_', '').isalnum():
                variables.add(root_var)
        
        # Second, identify template-set variables
        # Pattern: {% set variable = ... %}
        set_pattern = r'\{\%\s*set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*='
        for match in re.finditer(set_pattern, content):
            set_var = match.group(1)
            template_set_variables.add(set_var)
        
        # Third, identify macro parameters
        # Pattern: {% macro name(param1, param2) %}
        macro_pattern = r'\{\%\s*macro\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(([^)]*)\)'
        for match in re.finditer(macro_pattern, content):
            params = match.group(1)
            if params.strip():
                # Parse comma-separated parameters
                for param in params.split(','):
                    param = param.strip()
                    # Handle parameter with default: param=default
                    if '=' in param:
                        param = param.split('=')[0].strip()
                    # Remove quotes if it's a string default
                    param = param.strip('\'"')
                    if param and param.replace('_', '').isalnum():
                        macro_parameters.add(param)
        
        # Pattern 1: {{ variable }}
        simple_vars = re.findall(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}', content)
        variables.update(simple_vars)
        
        # Pattern 2: {{ variable.property }}
        object_vars = re.findall(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\.[a-zA-Z0-9_]+', content)
        variables.update(object_vars)
        
        # Pattern 3: {{ variable|filter }}
        filter_vars = re.findall(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\|', content)
        variables.update(filter_vars)
        
        # Pattern 4: {% if variable %}
        if_vars = re.findall(r'\{\%\s*if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\%\}', content)
        variables.update(if_vars)
        
        # Remove locally defined variables from required context variables
        locally_defined = loop_variables | template_set_variables | macro_parameters
        variables = variables - locally_defined
        
        # Filter out common Jinja/Frappe built-ins
        builtin_vars = {
            '_', 'frappe', 'request', 'session', 'user', 'lang', 'direction',
            'base_template_path', 'csrf_token', 'boot', 'site_name',
            'developer_mode', 'main_content', 'page_container', 'page_content',
            'head_include', 'body_include', 'navbar', 'sidebar', 'footer'
        }
        
        variables = variables - builtin_vars
        return variables
    
    def extract_context_variables(self, py_file: Path) -> Dict[str, List[str]]:
        """Extract context variables provided by Python files"""
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return {}
        
        context_vars = {}
        
        # Pattern 1: return {"key": value, ...}
        return_dict_pattern = r'return\s*\{([^}]+)\}'
        for match in re.finditer(return_dict_pattern, content, re.MULTILINE | re.DOTALL):
            dict_content = match.group(1)
            keys = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:', dict_content)
            context_vars['return_dict'] = keys
        
        # Pattern 2: context["key"] = value or context.key = value
        context_assign_pattern = r'context\[["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']]\s*='
        context_keys = re.findall(context_assign_pattern, content)
        
        # Pattern 2b: context.key = value
        context_dot_pattern = r'context\.([a-zA-Z_][a-zA-Z0-9_]*)\s*='
        context_dot_keys = re.findall(context_dot_pattern, content)
        
        all_context_keys = context_keys + context_dot_keys
        if all_context_keys:
            context_vars['context_assignment'] = all_context_keys
        
        # Pattern 3: context.update({"key": value})
        context_update_pattern = r'context\.update\s*\(\s*\{([^}]+)\}'
        for match in re.finditer(context_update_pattern, content, re.MULTILINE | re.DOTALL):
            dict_content = match.group(1)
            keys = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:', dict_content)
            if keys:
                context_vars['context_update'] = keys
        
        return context_vars
    
    def find_risky_patterns(self, py_file: Path) -> List[Dict]:
        """Find patterns that might cause template variable issues"""
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []
        
        risks = []
        lines = content.splitlines()
        
        for i, line in enumerate(lines, 1):
            # Pattern 1: field or 0 (risky for templates expecting string formatting)
            if re.search(r'\w+\.\w+\s+or\s+0(?!\.|[a-zA-Z])', line):
                risks.append({
                    'type': 'numeric_fallback',
                    'line': i,
                    'content': line.strip(),
                    'risk': 'Template may expect string-formattable value but gets 0'
                })
            
            # Pattern 2: template.field (without fallback)
            if re.search(r'template\.\w+(?!\s+or)', line) and '=' in line:
                risks.append({
                    'type': 'no_fallback',
                    'line': i,
                    'content': line.strip(),
                    'risk': 'Field may return None without fallback handling'
                })
            
            # Pattern 3: getattr without default
            if re.search(r'getattr\([^,]+,[^,)]+\)(?!\s*,)', line):
                risks.append({
                    'type': 'getattr_no_default',
                    'line': i,
                    'content': line.strip(),
                    'risk': 'getattr may return None without default value'
                })
        
        return risks
    
    def match_templates_to_context_providers(self) -> Dict[str, str]:
        """Match template files to their likely context provider Python files"""
        matches = {}
        
        for template_file in self.template_variables.keys():
            # Try to find corresponding Python file
            template_stem = template_file.stem
            
            # Look for exact match: template.html → template.py
            py_candidates = [
                template_file.parent / f"{template_stem}.py",
                template_file.parent / f"get_{template_stem}.py",
            ]
            
            # Look in parent directories
            current = template_file.parent
            while current != self.app_path and current.name != "templates":
                py_candidates.extend([
                    current / f"{template_stem}.py",
                    current / f"get_{template_stem}.py",
                ])
                current = current.parent
            
            # Find the first existing candidate
            for candidate in py_candidates:
                if candidate.exists() and candidate in self.context_providers:
                    matches[str(template_file)] = str(candidate)
                    break
        
        return matches
    
    def validate_template_context_match(self) -> List[Dict]:
        """Validate that templates have required variables provided by context"""
        violations = []
        template_matches = self.match_templates_to_context_providers()
        
        for template_file, py_file in template_matches.items():
            template_vars = self.template_variables[Path(template_file)]
            context_data = self.context_providers[Path(py_file)]
            
            # Get all provided context variables
            provided_vars = set()
            for var_list in context_data.values():
                provided_vars.update(var_list)
            
            # Check for missing variables
            missing_vars = template_vars - provided_vars
            
            if missing_vars:
                violations.append({
                    'type': 'missing_context_variables',
                    'template': str(Path(template_file).relative_to(self.app_path)),
                    'context_provider': str(Path(py_file).relative_to(self.app_path)),
                    'missing_variables': list(missing_vars),
                    'provided_variables': list(provided_vars),
                    'confidence': 'high' if len(missing_vars) <= 2 else 'medium'
                })
        
        return violations
    
    def scan_templates(self):
        """Scan all template files for variables"""
        template_files = []
        template_files.extend(self.app_path.rglob("templates/**/*.html"))
        template_files.extend(self.app_path.rglob("www/**/*.html"))
        
        for template_file in template_files:
            variables = self.extract_template_variables(template_file)
            if variables:
                self.template_variables[template_file] = variables
    
    def scan_context_providers(self):
        """Scan Python files that might provide template context"""
        py_files = []
        py_files.extend(self.app_path.rglob("templates/**/*.py"))
        py_files.extend(self.app_path.rglob("www/**/*.py"))
        py_files.extend(self.app_path.rglob("api/**/*.py"))
        
        for py_file in py_files:
            context_vars = self.extract_context_variables(py_file)
            if context_vars:
                self.context_providers[py_file] = context_vars
    
    def run_validation(self) -> bool:
        """Run comprehensive template variable validation"""
        print("🔍 Running Template Variable Validation...")
        
        # Scan templates and context providers
        self.scan_templates()
        self.scan_context_providers()
        
        print(f"📋 Found {len(self.template_variables)} templates with variables")
        print(f"📋 Found {len(self.context_providers)} Python context providers")
        
        # Validate template-context matching
        context_violations = self.validate_template_context_match()
        
        # Find risky patterns
        risk_violations = []
        for py_file in self.context_providers.keys():
            risks = self.find_risky_patterns(py_file)
            for risk in risks:
                risk_violations.append({
                    'file': str(py_file.relative_to(self.app_path)),
                    **risk
                })
        
        all_violations = context_violations + risk_violations
        
        if all_violations:
            print(f"\n❌ Found {len(all_violations)} template variable issues:")
            print("=" * 80)
            
            # Group by type
            by_type = {}
            for violation in all_violations:
                vtype = violation['type']
                if vtype not in by_type:
                    by_type[vtype] = []
                by_type[vtype].append(violation)
            
            for vtype, violations in by_type.items():
                print(f"\n🏷️  {vtype.replace('_', ' ').title()} ({len(violations)} issues):")
                
                for violation in violations:
                    if vtype == 'missing_context_variables':
                        confidence_icon = "🔴" if violation['confidence'] == 'high' else "🟡"
                        print(f"  {confidence_icon} {violation['template']}")
                        print(f"     Context: {violation['context_provider']}")
                        print(f"     Missing: {', '.join(violation['missing_variables'])}")
                        print(f"     Provided: {', '.join(violation['provided_variables'][:5])}{'...' if len(violation['provided_variables']) > 5 else ''}")
                    else:
                        print(f"  🟡 {violation['file']}:{violation['line']}")
                        print(f"     Risk: {violation['risk']}")
                        print(f"     Code: {violation['content']}")
                    print()
            
            print("=" * 80)
            print("💡 High confidence issues should be fixed immediately")
            print("💡 Medium confidence issues should be reviewed manually")
            return False
        else:
            print("\n✅ No template variable issues found!")
            print("✅ All template variables properly provided by context!")
            return True


def main():
    """Main entry point"""
    import sys
    
    # Get app path
    script_path = Path(__file__).resolve()
    app_path = script_path.parent.parent.parent
    
    # Verify this is the app root
    if not (app_path / 'verenigingen' / 'hooks.py').exists():
        print(f"Error: hooks.py not found at {app_path}")
        sys.exit(1)
    
    validator = TemplateVariableValidator(str(app_path))
    success = validator.run_validation()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()