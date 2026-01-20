#!/usr/bin/env python3
"""
Whitelist Type Safety Validator

Validates that @frappe.whitelist() decorated functions follow Frappe v15+ security
best practices:

1. Type annotations on all parameters (prevents type confusion attacks)
2. Document-level permission checks via check_permission() after get_doc()

Security Context:
- In Frappe v15+, type annotations are automatically enforced on whitelisted methods
- Without annotations, malicious users can pass unexpected types like filter objects
  (e.g., ["is", "set"]) instead of strings, changing query behavior
- Document permission checks ensure users can only access documents they're authorized for

References:
- https://frappeframework.com/docs/user/en/api/whitelist
- Frappe Security Best Practices

Usage:
    python scripts/validation/security/whitelist_type_safety_validator.py
    python scripts/validation/security/whitelist_type_safety_validator.py --file verenigingen/api/member_management.py
    python scripts/validation/security/whitelist_type_safety_validator.py --fix-suggestions
    python scripts/validation/security/whitelist_type_safety_validator.py --strict
"""

import argparse
import ast
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class Severity(Enum):
    """Issue severity levels"""
    ERROR = "error"      # Must fix - security vulnerability
    WARNING = "warning"  # Should fix - potential issue
    INFO = "info"        # Suggestion for improvement


@dataclass
class TypeSafetyIssue:
    """Represents a type safety issue found in a whitelisted function"""
    file_path: str
    function_name: str
    line_number: int
    severity: Severity
    issue_type: str
    message: str
    parameter_name: Optional[str] = None
    suggested_fix: Optional[str] = None


@dataclass
class FunctionAnalysis:
    """Analysis result for a single function"""
    file_path: str
    function_name: str
    line_number: int
    is_whitelisted: bool
    has_allow_guest: bool
    parameters: List[Dict]  # name, has_annotation, annotation_str
    has_get_doc_calls: bool
    has_check_permission_calls: bool
    get_doc_locations: List[int]  # line numbers where get_doc is called
    check_permission_locations: List[int]  # line numbers where check_permission is called
    issues: List[TypeSafetyIssue] = field(default_factory=list)


class WhitelistTypeSafetyValidator:
    """
    Validates type safety and permission checking in whitelisted API functions.

    Checks:
    1. All parameters have type annotations (prevents type confusion)
    2. After frappe.get_doc() calls, check_permission() should be called
    """

    # Parameters that are commonly safe without strict type checking
    SAFE_UNTYPED_PARAMS = frozenset([
        'self', 'cls', 'args', 'kwargs',
    ])

    # Parameters that MUST have type annotations (security-sensitive)
    SECURITY_SENSITIVE_PARAMS = frozenset([
        'name', 'doctype', 'doc', 'document', 'filters', 'filter',
        'member', 'member_name', 'donor', 'donor_name', 'customer', 'customer_name',
        'user', 'user_name', 'email', 'invoice', 'invoice_name',
        'payment', 'payment_name', 'schedule', 'schedule_name',
        'chapter', 'chapter_name', 'bsn', 'rsin', 'iban',
    ])

    # Common type annotations for security-sensitive parameters
    SUGGESTED_TYPES = {
        'name': 'str',
        'doctype': 'str',
        'member': 'str',
        'member_name': 'str',
        'donor': 'str',
        'donor_name': 'str',
        'customer': 'str',
        'customer_name': 'str',
        'user': 'str',
        'user_name': 'str',
        'email': 'str',
        'invoice': 'str',
        'invoice_name': 'str',
        'payment': 'str',
        'payment_name': 'str',
        'schedule': 'str',
        'schedule_name': 'str',
        'chapter': 'str',
        'chapter_name': 'str',
        'bsn': 'str',
        'rsin': 'str',
        'iban': 'str',
        'filters': 'dict | None',
        'filter': 'dict | None',
        'doc': 'dict',
        'document': 'dict',
        'force': 'bool',
        'send_email': 'bool',
        'include_': 'bool',  # prefix match for include_* params
        'from_date': 'str',
        'to_date': 'str',
    }

    def __init__(self, strict: bool = False, verbose: bool = False):
        """
        Initialize validator.

        Args:
            strict: If True, require type annotations on ALL parameters
            verbose: If True, print detailed progress information
        """
        self.strict = strict
        self.verbose = verbose
        self.analyses: List[FunctionAnalysis] = []
        self.issues: List[TypeSafetyIssue] = []

    def validate_file(self, file_path: Path) -> List[TypeSafetyIssue]:
        """Validate a single Python file for type safety issues."""
        issues = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()

            tree = ast.parse(source, filename=str(file_path))

            # Find all whitelisted functions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis = self._analyze_function(node, str(file_path), source)
                    if analysis.is_whitelisted:
                        self.analyses.append(analysis)
                        issues.extend(analysis.issues)

        except SyntaxError as e:
            if self.verbose:
                print(f"  Syntax error in {file_path}: {e}")
        except Exception as e:
            if self.verbose:
                print(f"  Error processing {file_path}: {e}")

        return issues

    def _analyze_function(self, node: ast.FunctionDef, file_path: str, source: str) -> FunctionAnalysis:
        """Analyze a function definition for security issues."""
        is_whitelisted = False
        has_allow_guest = False

        # Check decorators for @frappe.whitelist
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if 'whitelist' in decorator_name.lower():
                is_whitelisted = True
                # Check for allow_guest
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == 'allow_guest':
                            has_allow_guest = self._get_literal_value(keyword.value)

        # Analyze parameters
        parameters = []
        for arg in node.args.args:
            param_name = arg.arg
            has_annotation = arg.annotation is not None
            annotation_str = ast.unparse(arg.annotation) if arg.annotation else None
            parameters.append({
                'name': param_name,
                'has_annotation': has_annotation,
                'annotation_str': annotation_str,
            })

        # Check for defaults (kwargs with defaults)
        for arg in node.args.kwonlyargs:
            param_name = arg.arg
            has_annotation = arg.annotation is not None
            annotation_str = ast.unparse(arg.annotation) if arg.annotation else None
            parameters.append({
                'name': param_name,
                'has_annotation': has_annotation,
                'annotation_str': annotation_str,
            })

        # Analyze function body for get_doc and check_permission calls
        get_doc_locations = []
        check_permission_locations = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if 'get_doc' in call_name:
                    get_doc_locations.append(child.lineno)
                elif 'check_permission' in call_name:
                    check_permission_locations.append(child.lineno)

        analysis = FunctionAnalysis(
            file_path=file_path,
            function_name=node.name,
            line_number=node.lineno,
            is_whitelisted=is_whitelisted,
            has_allow_guest=has_allow_guest,
            parameters=parameters,
            has_get_doc_calls=len(get_doc_locations) > 0,
            has_check_permission_calls=len(check_permission_locations) > 0,
            get_doc_locations=get_doc_locations,
            check_permission_locations=check_permission_locations,
        )

        # Generate issues
        if is_whitelisted:
            analysis.issues = self._generate_issues(analysis)

        return analysis

    def _generate_issues(self, analysis: FunctionAnalysis) -> List[TypeSafetyIssue]:
        """Generate security issues for a function analysis."""
        issues = []

        # Check 1: Type annotations on parameters
        for param in analysis.parameters:
            param_name = param['name']
            has_annotation = param['has_annotation']

            # Skip safe params
            if param_name in self.SAFE_UNTYPED_PARAMS:
                continue

            # Check if it's a security-sensitive parameter
            is_sensitive = param_name in self.SECURITY_SENSITIVE_PARAMS

            # Also check prefix matches (e.g., member_* should be typed)
            if not is_sensitive:
                for sensitive in self.SECURITY_SENSITIVE_PARAMS:
                    if param_name.startswith(sensitive) or param_name.endswith('_name'):
                        is_sensitive = True
                        break

            if not has_annotation:
                # Determine severity
                if is_sensitive:
                    severity = Severity.ERROR
                    message = (
                        f"Security-sensitive parameter '{param_name}' lacks type annotation. "
                        f"This allows type confusion attacks where malicious users can pass "
                        f"filter objects like ['is', 'set'] instead of strings."
                    )
                elif self.strict:
                    severity = Severity.WARNING
                    message = f"Parameter '{param_name}' lacks type annotation."
                else:
                    # In non-strict mode, only report security-sensitive params
                    continue

                # Suggest a fix
                suggested_type = self._suggest_type(param_name)
                suggested_fix = f"{param_name}: {suggested_type}"

                issues.append(TypeSafetyIssue(
                    file_path=analysis.file_path,
                    function_name=analysis.function_name,
                    line_number=analysis.line_number,
                    severity=severity,
                    issue_type="missing_type_annotation",
                    message=message,
                    parameter_name=param_name,
                    suggested_fix=suggested_fix,
                ))

        # Check 2: get_doc without check_permission
        if analysis.has_get_doc_calls and not analysis.has_check_permission_calls:
            # This is a warning, not error, because save() does check internally
            issues.append(TypeSafetyIssue(
                file_path=analysis.file_path,
                function_name=analysis.function_name,
                line_number=analysis.get_doc_locations[0] if analysis.get_doc_locations else analysis.line_number,
                severity=Severity.WARNING,
                issue_type="missing_permission_check",
                message=(
                    f"Function calls frappe.get_doc() but never calls check_permission(). "
                    f"While save/delete have built-in checks, explicit check_permission() "
                    f"provides fail-fast behavior and clearer errors."
                ),
                suggested_fix="doc.check_permission('read')  # or 'write' before modifications",
            ))

        return issues

    def _suggest_type(self, param_name: str) -> str:
        """Suggest an appropriate type annotation for a parameter."""
        # Direct match
        if param_name in self.SUGGESTED_TYPES:
            return self.SUGGESTED_TYPES[param_name]

        # Prefix/suffix matches
        if param_name.endswith('_name') or param_name.endswith('_id'):
            return 'str'
        if param_name.startswith('is_') or param_name.startswith('has_') or param_name.startswith('include_'):
            return 'bool'
        if param_name.endswith('_date'):
            return 'str'
        if param_name.endswith('_list') or param_name.endswith('_items'):
            return 'list'
        if param_name == 'filters' or param_name.endswith('_filters'):
            return 'dict | None'

        # Default to str for document names
        return 'str'

    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract the name of a decorator."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return f"{self._get_decorator_name(decorator.value)}.{decorator.attr}"
        elif isinstance(decorator, ast.Call):
            return self._get_decorator_name(decorator.func)
        return ""

    def _get_call_name(self, call: ast.Call) -> str:
        """Extract the name of a function call."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        return ""

    def _get_literal_value(self, node: ast.expr):
        """Extract a literal value from an AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.NameConstant):  # Python 3.7 compatibility
            return node.value
        return None

    def validate_directory(self, directory: Path, pattern: str = "**/*.py") -> List[TypeSafetyIssue]:
        """Validate all Python files in a directory."""
        all_issues = []

        for file_path in directory.glob(pattern):
            # Skip test files and archived files
            if any(skip in str(file_path) for skip in ['test_', '_test.py', 'archived', 'debug_']):
                continue

            if self.verbose:
                print(f"Checking {file_path}...")

            issues = self.validate_file(file_path)
            all_issues.extend(issues)

        self.issues = all_issues
        return all_issues

    def print_report(self, issues: List[TypeSafetyIssue], show_suggestions: bool = False):
        """Print a formatted report of issues found."""
        if not issues:
            print("\n✅ No type safety issues found!")
            return

        # Group by file
        by_file: Dict[str, List[TypeSafetyIssue]] = {}
        for issue in issues:
            by_file.setdefault(issue.file_path, []).append(issue)

        error_count = sum(1 for i in issues if i.severity == Severity.ERROR)
        warning_count = sum(1 for i in issues if i.severity == Severity.WARNING)

        print(f"\n🔍 Type Safety Validation Report")
        print(f"{'=' * 60}")
        print(f"Files checked: {len(self.analyses)}")
        print(f"Issues found: {len(issues)} ({error_count} errors, {warning_count} warnings)")
        print()

        for file_path, file_issues in sorted(by_file.items()):
            rel_path = file_path.replace(str(Path.cwd()) + '/', '')
            print(f"\n📄 {rel_path}")
            print(f"   {'-' * 50}")

            for issue in sorted(file_issues, key=lambda x: x.line_number):
                icon = "❌" if issue.severity == Severity.ERROR else "⚠️"
                print(f"   {icon} Line {issue.line_number}: {issue.function_name}()")
                print(f"      {issue.message}")

                if show_suggestions and issue.suggested_fix:
                    print(f"      💡 Suggested fix: {issue.suggested_fix}")

        print(f"\n{'=' * 60}")
        if error_count > 0:
            print(f"❌ {error_count} ERROR(S) - Type annotations required for security")
        if warning_count > 0:
            print(f"⚠️  {warning_count} WARNING(S) - Consider adding permission checks")

    def get_exit_code(self, issues: List[TypeSafetyIssue]) -> int:
        """Return appropriate exit code based on issues found."""
        error_count = sum(1 for i in issues if i.severity == Severity.ERROR)
        return 1 if error_count > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate type safety in @frappe.whitelist() functions"
    )
    parser.add_argument(
        'files',
        nargs='*',
        help="Files to validate (for pre-commit integration)"
    )
    parser.add_argument(
        '--file', '-f',
        type=str,
        help="Validate a specific file (alternative to positional args)"
    )
    parser.add_argument(
        '--directory', '-d',
        type=str,
        default='verenigingen/api',
        help="Directory to validate (default: verenigingen/api)"
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help="Require type annotations on ALL parameters (not just security-sensitive ones)"
    )
    parser.add_argument(
        '--fix-suggestions',
        action='store_true',
        help="Show suggested fixes for each issue"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Show verbose output"
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help="Output results as JSON"
    )

    args = parser.parse_args()

    validator = WhitelistTypeSafetyValidator(
        strict=args.strict,
        verbose=args.verbose
    )

    # Determine what to validate
    issues = []

    # Handle files passed as positional arguments (pre-commit mode)
    if args.files:
        for file_arg in args.files:
            file_path = Path(file_arg)
            if file_path.exists() and file_path.suffix == '.py':
                # Skip test files and archived files
                if any(skip in str(file_path) for skip in ['test_', '_test.py', '/tests/', 'archived', 'debug_']):
                    continue
                issues.extend(validator.validate_file(file_path))
    # Handle --file argument
    elif args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        issues = validator.validate_file(file_path)
    # Default: validate directory
    else:
        directory = Path(args.directory)
        if not directory.exists():
            print(f"Error: Directory not found: {args.directory}")
            sys.exit(1)
        issues = validator.validate_directory(directory)

    # Output results
    if args.json:
        import json
        output = [
            {
                'file': i.file_path,
                'function': i.function_name,
                'line': i.line_number,
                'severity': i.severity.value,
                'type': i.issue_type,
                'message': i.message,
                'parameter': i.parameter_name,
                'fix': i.suggested_fix,
            }
            for i in issues
        ]
        print(json.dumps(output, indent=2))
    else:
        validator.print_report(issues, show_suggestions=args.fix_suggestions)

    sys.exit(validator.get_exit_code(issues))


if __name__ == "__main__":
    main()
