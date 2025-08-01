#!/usr/bin/env python3
"""
Fast Method Call Validator

A lightweight validator focused on catching the most common method call issues
without building a comprehensive method database.

Features:
- Fast execution (< 30 seconds)
- Targeted validation for deprecated methods
- Pattern-based validation
- Pre-commit hook friendly
"""

import ast
import re
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass


@dataclass
class CallIssue:
    """Represents a method call issue"""
    file_path: str
    line_number: int
    call_name: str
    issue_type: str
    message: str
    context: str
    suggestion: Optional[str] = None


class FastMethodValidator:
    """Fast method call validator focused on common issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        
        # Known deprecated methods to check for
        self.deprecated_methods = {
            # Methods we've seen cause issues
            'calculate_next_billing_date': 'calculate_next_invoice_date',
            
            # Common typos in our codebase
            'frappe.get_docs': 'frappe.get_doc',
            'frappe.get_values': 'frappe.get_value',
            'frappe.set_values': 'frappe.set_value',
            
            # Removed Frappe methods
            'frappe.boot': 'Use frappe.cache instead',
            'frappe.local.form_dict': 'Use frappe.form_dict',
        }
        
        # Methods that are likely typos of common methods
        self.typo_patterns = {
            'get_all_docs': 'get_all',
            'get_list_docs': 'get_list',
            'save_doc': 'save',
            'insert_doc': 'insert',
            'delete_doc': 'delete',
            'update_doc': 'update',
        }
        
        # Suspicious method call patterns
        self.suspicious_patterns = [
            r'frappe\.get_doc\(\)\.save\(\)',  # Should check if doc exists first
            r'frappe\.db\.sql\([^)]*DELETE[^)]*\)',  # Direct DELETE in SQL
            r'\.insert\(ignore_permissions=True\)',  # Bypassing permissions
            r'\.save\(ignore_validate=True\)',  # Bypassing validation
        ]

    def validate_directory(self, directory: str = None) -> List[CallIssue]:
        """Validate all Python files in directory"""
        issues = []
        search_path = Path(directory) if directory else self.app_path
        
        print(f"🔍 Running fast method validation on {search_path}...")
        
        file_count = 0
        for py_file in search_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
                
            file_issues = self._validate_file(py_file)
            issues.extend(file_issues)
            file_count += 1
            
            if file_count % 100 == 0:
                print(f"   Processed {file_count} files...")
        
        print(f"✅ Validated {file_count} files")
        
        # Also validate hooks.py if we're validating the main app directory
        if search_path == self.app_path:
            print("🔗 Validating hooks.py references...")
            hooks_issues = self._validate_hooks()
            issues.extend(hooks_issues)
        
        return issues
    
    def _validate_hooks(self) -> List[CallIssue]:
        """Validate hooks.py method references"""
        import sys
        import os
        
        # Add the validation directory to path for import
        validation_dir = os.path.dirname(os.path.abspath(__file__))
        if validation_dir not in sys.path:
            sys.path.insert(0, validation_dir)
        
        from simple_hooks_validator import SimpleHooksValidator
        
        hooks_validator = SimpleHooksValidator(str(self.app_path))
        hook_issues = hooks_validator.validate()
        
        # Convert hook issues to call issues
        call_issues = []
        for issue in hook_issues:
            call_issues.append(CallIssue(
                file_path="hooks.py",
                line_number=0,
                call_name=issue.method_path,
                issue_type="NONEXISTENT METHOD" if issue.issue_type == "missing_method" else "MISSING MODULE",
                message=issue.message,
                context=f"Hook: {issue.hook_name}"
            ))
        
        if hook_issues:
            print(f"   Found {len(hook_issues)} hooks.py issues")
        
        return call_issues

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped"""
        skip_patterns = [
            '__pycache__', '.git', 'node_modules', '.pyc',
            'test_field_validation_gaps.py',  # Our own test file
            'method_call_validator.py',  # The comprehensive validator
        ]
        
        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)

    def _validate_file(self, file_path: Path) -> List[CallIssue]:
        """Validate method calls in a single file"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # 1. Check for deprecated method calls
            issues.extend(self._check_deprecated_methods(file_path, content, lines))
            
            # 2. Check for common typos
            issues.extend(self._check_typos(file_path, content, lines))
            
            # 3. Check for suspicious patterns
            issues.extend(self._check_suspicious_patterns(file_path, content, lines))
            
            # 4. AST-based validation for specific patterns
            try:
                tree = ast.parse(content, filename=str(file_path))
                issues.extend(self._check_ast_patterns(tree, file_path, lines))
            except SyntaxError:
                # Skip files with syntax errors
                pass
                
        except Exception:
            # Don't fail on file read errors
            pass
            
        return issues

    def _check_deprecated_methods(self, file_path: Path, content: str, lines: List[str]) -> List[CallIssue]:
        """Check for deprecated method calls"""
        issues = []
        
        for deprecated_method, suggestion in self.deprecated_methods.items():
            # Look for method calls
            patterns = [
                rf'\b{re.escape(deprecated_method)}\s*\(',  # function call
                rf'\.{re.escape(deprecated_method)}\s*\(',  # method call
            ]
            
            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count('\n') + 1
                    context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    
                    issues.append(CallIssue(
                        file_path=str(file_path.relative_to(self.app_path)),
                        line_number=line_num,
                        call_name=deprecated_method,
                        issue_type="deprecated_method",
                        message=f"Deprecated method '{deprecated_method}' should not be used",
                        context=context,
                        suggestion=suggestion
                    ))
        
        return issues

    def _check_typos(self, file_path: Path, content: str, lines: List[str]) -> List[CallIssue]:
        """Check for common method name typos"""
        issues = []
        
        for typo, correction in self.typo_patterns.items():
            pattern = rf'\b{re.escape(typo)}\s*\('
            
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count('\n') + 1
                context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                issues.append(CallIssue(
                    file_path=str(file_path.relative_to(self.app_path)),
                    line_number=line_num,
                    call_name=typo,
                    issue_type="likely_typo",
                    message=f"Possible typo in method name '{typo}'",
                    context=context,
                    suggestion=f"Did you mean '{correction}'?"
                ))
        
        return issues

    def _check_suspicious_patterns(self, file_path: Path, content: str, lines: List[str]) -> List[CallIssue]:
        """Check for suspicious method call patterns"""
        issues = []
        
        for pattern in self.suspicious_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1
                context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                issues.append(CallIssue(
                    file_path=str(file_path.relative_to(self.app_path)),
                    line_number=line_num,
                    call_name=match.group(0),
                    issue_type="suspicious_pattern",
                    message=f"Suspicious method call pattern detected",
                    context=context,
                    suggestion="Review for security and best practices"
                ))
        
        return issues

    def _check_ast_patterns(self, tree: ast.AST, file_path: Path, lines: List[str]) -> List[CallIssue]:
        """Check AST for specific problematic patterns"""
        issues = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for specific AST patterns
                
                # 1. Calls to methods that don't exist in our codebase
                if isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    
                    # Check for non-existent methods we know about
                    nonexistent_methods = [
                        'calculate_next_billing_date',  # This was renamed
                        'refresh_billing_schedule',     # Doesn't exist
                        'update_membership_status',     # Check if this exists
                    ]
                    
                    if method_name in nonexistent_methods:
                        line_num = node.lineno
                        context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                        
                        issues.append(CallIssue(
                            file_path=str(file_path.relative_to(self.app_path)),
                            line_number=line_num,
                            call_name=method_name,
                            issue_type="nonexistent_method",
                            message=f"Method '{method_name}' does not exist",
                            context=context,
                            suggestion="Check method name spelling and availability"
                        ))
        
        return issues

    def print_report(self, issues: List[CallIssue]) -> None:
        """Print validation report"""
        if not issues:
            print("✅ No method call issues found!")
            return
        
        # Group by issue type
        by_type = {}
        for issue in issues:
            if issue.issue_type not in by_type:
                by_type[issue.issue_type] = []
            by_type[issue.issue_type].append(issue)
        
        print(f"🚨 Found {len(issues)} method call issues:")
        
        for issue_type, type_issues in by_type.items():
            print(f"\n📋 {issue_type.upper().replace('_', ' ')} ({len(type_issues)} issues):")
            
            for issue in type_issues[:10]:  # Limit output
                print(f"   {issue.file_path}:{issue.line_number} - {issue.call_name}")
                print(f"      {issue.message}")
                if issue.suggestion:
                    print(f"      💡 {issue.suggestion}")
            
            if len(type_issues) > 10:
                print(f"   ... and {len(type_issues) - 10} more")

    def get_stats(self, issues: List[CallIssue]) -> Dict[str, int]:
        """Get statistics about issues found"""
        stats = {
            'total': len(issues),
            'deprecated_methods': 0,
            'likely_typos': 0,
            'suspicious_patterns': 0,
            'nonexistent_methods': 0,
        }
        
        for issue in issues:
            if issue.issue_type in stats:
                stats[issue.issue_type] += 1
        
        return stats


def main():
    """Main function"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = FastMethodValidator(app_path)
    
    # Validate files
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        # Validate specific file
        file_path = Path(sys.argv[1])
        issues = validator._validate_file(file_path)
    else:
        # Validate all files
        issues = validator.validate_directory()
    
    # Print report
    validator.print_report(issues)
    
    # Print stats
    stats = validator.get_stats(issues)
    print(f"\n📊 SUMMARY:")
    print(f"   Total issues: {stats['total']}")
    print(f"   Deprecated methods: {stats['deprecated_methods']}")
    print(f"   Likely typos: {stats['likely_typos']}")
    print(f"   Suspicious patterns: {stats['suspicious_patterns']}")
    print(f"   Nonexistent methods: {stats['nonexistent_methods']}")
    
    # Exit with error code if critical issues found
    critical_issues = stats['deprecated_methods'] + stats['nonexistent_methods']
    if critical_issues > 0:
        print(f"\n❌ Validation failed: {critical_issues} critical issues found")
        sys.exit(1)
    else:
        print(f"\n✅ Fast method validation passed")
        sys.exit(0)


if __name__ == "__main__":
    main()