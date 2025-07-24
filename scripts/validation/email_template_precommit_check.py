#!/usr/bin/env python3
"""
Pre-commit hook for email template validation

This script validates email templates for syntax issues and can be run as:
1. Pre-commit hook
2. Standalone validation script
3. Part of CI/CD pipeline

Usage:
    python email_template_precommit_check.py [--fix-issues] [--verbose]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


class EmailTemplateValidator:
    """Email template validation for pre-commit hooks"""
    
    def __init__(self, verbose=False, fix_issues=False):
        self.verbose = verbose
        self.fix_issues = fix_issues
        self.issues = []
        self.fixed_issues = []
    
    def log(self, message):
        """Log message if verbose mode is enabled"""
        if self.verbose:
            print(f"[EMAIL_TEMPLATE_VALIDATOR] {message}")
    
    def validate_fixture_templates(self, fixture_path):
        """Validate email templates in JSON fixtures"""
        if not os.path.exists(fixture_path):
            self.log(f"Fixture file not found: {fixture_path}")
            return True
        
        self.log(f"Validating fixture templates: {fixture_path}")
        
        try:
            with open(fixture_path, 'r', encoding='utf-8') as f:
                templates = json.load(f)
        except Exception as e:
            self.issues.append(f"Failed to parse fixture file {fixture_path}: {e}")
            return False
        
        fixture_issues = []
        
        for template in templates:
            template_name = template.get('name', 'Unknown')
            subject = template.get('subject', '')
            response = template.get('response', '')
            
            # Validate Jinja2 syntax
            subject_issues = self._validate_jinja2_syntax(subject, f"{template_name} subject")
            response_issues = self._validate_jinja2_syntax(response, f"{template_name} response")
            
            fixture_issues.extend(subject_issues)
            fixture_issues.extend(response_issues)
            
            # Check for completeness
            if not subject.strip():
                fixture_issues.append(f"Template '{template_name}': Empty subject")
            
            if not response.strip():
                fixture_issues.append(f"Template '{template_name}': Empty response")
        
        self.issues.extend(fixture_issues)
        return len(fixture_issues) == 0
    
    def validate_python_files(self, directory):
        """Validate email templates in Python files"""
        self.log(f"Validating Python files in: {directory}")
        
        python_issues = []
        fixed_files = []
        
        for root, dirs, files in os.walk(directory):
            # Skip certain directories
            if any(skip in root for skip in ['__pycache__', '.git', 'node_modules']):
                continue
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, directory)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        original_content = content
                        file_issues, modified_content = self._validate_python_content(
                            content, relative_path
                        )
                        
                        python_issues.extend(file_issues)
                        
                        # Apply fixes if requested and content was modified
                        if self.fix_issues and modified_content != original_content:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(modified_content)
                            fixed_files.append(relative_path)
                            self.log(f"Fixed issues in: {relative_path}")
                        
                    except Exception as e:
                        python_issues.append(f"Failed to process {relative_path}: {e}")
        
        if fixed_files:
            self.fixed_issues.extend([f"Auto-fixed Python file: {f}" for f in fixed_files])
        
        self.issues.extend(python_issues)
        return len(python_issues) == 0
    
    def _validate_jinja2_syntax(self, content, context):
        """Validate Jinja2 template syntax"""
        issues = []
        
        if not content:
            return issues
        
        # Check for unmatched brackets
        open_count = content.count("{{")
        close_count = content.count("}}")
        if open_count != close_count:
            issues.append(f"{context}: Unmatched {{ }} brackets")
        
        # Check for unmatched control structures
        if_count = len(re.findall(r'{%\s*if\s+', content))
        endif_count = len(re.findall(r'{%\s*endif\s*%}', content))
        if if_count != endif_count:
            issues.append(f"{context}: Unmatched if/endif blocks")
        
        for_count = len(re.findall(r'{%\s*for\s+', content))
        endfor_count = len(re.findall(r'{%\s*endfor\s*%}', content))
        if for_count != endfor_count:
            issues.append(f"{context}: Unmatched for/endfor blocks")
        
        # Check for syntax errors
        if "{ {" in content or "} }" in content:
            issues.append(f"{context}: Spaces in Jinja2 brackets")
        
        return issues
    
    def _validate_python_content(self, content, file_path):
        """Validate and optionally fix Python email template content"""
        issues = []
        modified_content = content
        
        # Pattern 1: frappe.sendmail subject without f-string
        pattern1 = r'(\s+subject\s*=\s*)([^f])"([^"]*{[^{][^"]*)"'
        matches1 = list(re.finditer(pattern1, content, re.MULTILINE))
        
        for match in matches1:
            line_num = content[:match.start()].count('\n') + 1
            issue = f"{file_path}:{line_num}: subject line needs f-string formatting"
            
            if self.fix_issues:
                # Replace with f-string
                old_text = match.group(0)
                new_text = match.group(1) + 'f' + match.group(2) + '"' + match.group(3) + '"'
                modified_content = modified_content.replace(old_text, new_text, 1)
                self.log(f"Auto-fixed f-string in {file_path}:{line_num}")
            else:
                issues.append(issue)
        
        # Pattern 2: Variables commented out but used in templates
        pattern2 = r'#\s*(\w+_url\s*=.*)\n(.*{[^}]*\1[^}]*})'
        matches2 = list(re.finditer(pattern2, content, re.MULTILINE | re.DOTALL))
        
        for match in matches2:
            line_num = content[:match.start()].count('\n') + 1
            variable = match.group(1).split('=')[0].strip()
            issue = f"{file_path}:{line_num}: Variable '{variable}' is commented out but used in template"
            
            if self.fix_issues:
                # Uncomment the variable
                old_line = "#" + match.group(1)
                new_line = match.group(1)
                modified_content = modified_content.replace(old_line, new_line, 1)
                self.log(f"Auto-fixed commented variable in {file_path}:{line_num}")
            else:
                issues.append(issue)
        
        # Pattern 3: Only check email-related f-strings for undefined variables
        # Look for frappe.sendmail context or email template functions
        email_context_pattern = r'(frappe\.sendmail|frappe\.render_template|subject\s*=\s*f"|message\s*=\s*f")[^}]*?(f"[^"]*{[^}]+}[^"]*")'
        email_matches = re.finditer(email_context_pattern, modified_content, re.MULTILINE | re.DOTALL)
        
        for match in email_matches:
            line_num = modified_content[:match.start()].count('\n') + 1
            fstring = match.group(2)
            variables = re.findall(r'{([^}]+)}', fstring)
            
            for var in variables:
                # Skip format specifiers and complex expressions - modernized
                COMPLEX_EXPRESSION_OPERATORS = {':', '+', '-', '*', '/'}
                if any(op in var for op in COMPLEX_EXPRESSION_OPERATORS):
                    continue
                
                # Skip function calls and complex expressions
                if '(' in var and ')' in var:
                    continue
                
                # Skip array/dict access
                if '[' in var and ']' in var:
                    continue
                    
                # Skip string literals and complex expressions
                if "'" in var or '"' in var or 'str(' in var:
                    continue
                
                # Check if variable is defined in the same function  
                var_name = var.split('.')[0]  # Handle object.attribute
                if not self._is_variable_defined_in_email_context(modified_content, var_name, match.start()):
                    issues.append(f"{file_path}:{line_num}: Email template variable '{var_name}' may be undefined")
        
        return issues, modified_content
    
    def _is_variable_defined_in_email_context(self, content, var_name, position):
        """Check if variable is defined in email context before use"""
        # Look backwards from position for variable definition
        preceding_content = content[:position]
        
        # Find the function containing this position
        function_match = None
        for match in re.finditer(r'def\s+(\w+)\s*\([^)]*\):', content):
            if match.start() < position:
                function_match = match
            else:
                break
        
        if not function_match:
            return True  # Can't determine context, assume it's okay
        
        # Get function content from definition to current position
        function_start = function_match.start()
        function_content = content[function_start:position]
        
        # Check for common definition patterns in email functions
        patterns = [
            rf'\b{var_name}\s*=',  # Direct assignment
            rf'def\s+\w+\([^)]*\b{var_name}\b',  # Function parameter
            rf'for\s+{var_name}\b',  # Loop variable
            rf'import.*\b{var_name}\b',  # Import
            rf'{var_name}\s*=.*frappe\.',  # Frappe API calls
            rf'frappe\.get.*as\s+{var_name}',  # Frappe get with alias
            rf'except.*as\s+{var_name}\b',  # Exception variables
            rf'{var_name}\s*=.*\.get\(',  # Dictionary/object get calls
            rf'with.*as\s+{var_name}\b',  # Context managers
        ]
        
        for pattern in patterns:
            if re.search(pattern, function_content):
                return True
        
        # Check for common email template variables that are typically available
        common_email_vars = [
            'member', 'doc', 'invoice', 'application_id', 'company', 
            'base_url', 'payment_url', 'frappe', 'today', 'now_datetime',
            'args', 'context', 'data', 'template', 'message', 'subject',
            'recipients', 'email', 'user', 'settings', 'config',
            'expense_doc', 'volunteer', 'chapter', 'donor', 'agreement',
            'report_data', 'overdue_requests', 'applications', 'e',  # Exception variable
            'template_name', 'file_path', 'line_num', 'purpose', 'username',
            'to_email', 'count', 'duration_str', 'i', 'organization_type',
            'postal_code', 'days_remaining', 'chapter_name'  # Additional common vars
        ]
        
        if var_name in common_email_vars:
            return True
        
        return False
    
    def _is_variable_defined(self, content, var_name, position):
        """Check if variable is defined before use (legacy method)"""
        # Look backwards from position for variable definition
        preceding_content = content[:position]
        
        # Check for common definition patterns
        patterns = [
            rf'\b{var_name}\s*=',  # Direct assignment
            rf'def\s+\w+\([^)]*\b{var_name}\b',  # Function parameter
            rf'for\s+{var_name}\b',  # Loop variable
            rf'import.*\b{var_name}\b',  # Import
        ]
        
        for pattern in patterns:
            if re.search(pattern, preceding_content):
                return True
        
        return False
    
    def generate_report(self):
        """Generate validation report"""
        report = {
            "success": len(self.issues) == 0,
            "total_issues": len(self.issues),
            "issues": self.issues,
            "fixed_issues": self.fixed_issues
        }
        
        return report


def main():
    """Main function for pre-commit hook"""
    parser = argparse.ArgumentParser(description="Email template validation for pre-commit")
    parser.add_argument("--fix-issues", action="store_true", 
                       help="Attempt to automatically fix issues")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    parser.add_argument("--directory", "-d", 
                       default="/home/frappe/frappe-bench/apps/verenigingen",
                       help="Directory to scan (default: current directory)")
    
    args = parser.parse_args()
    
    # Initialize validator
    validator = EmailTemplateValidator(verbose=args.verbose, fix_issues=args.fix_issues)
    
    # Validate fixtures
    fixture_path = os.path.join(args.directory, "verenigingen/fixtures/email_template.json")
    fixture_valid = validator.validate_fixture_templates(fixture_path)
    
    # Validate Python files
    python_dir = os.path.join(args.directory, "verenigingen")
    python_valid = validator.validate_python_files(python_dir)
    
    # Generate report
    report = validator.generate_report()
    
    if args.verbose or not report["success"]:
        print("\n" + "="*60)
        print("EMAIL TEMPLATE VALIDATION REPORT")
        print("="*60)
        
        if report["success"]:
            print("✅ All email templates passed validation!")
        else:
            print(f"❌ Found {report['total_issues']} issues:")
            for issue in report["issues"]:
                print(f"  • {issue}")
        
        if report["fixed_issues"]:
            print(f"\n🔧 Auto-fixed {len(report['fixed_issues'])} issues:")
            for fix in report["fixed_issues"]:
                print(f"  • {fix}")
        
        print("\n" + "="*60)
    
    # Exit with appropriate code
    sys.exit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()