#!/usr/bin/env python3
"""
Insecure API Endpoint Detection Tool - Pre-commit Security Validation

This script identifies API endpoints that lack proper security decorators and prevents
insecure APIs from being committed. It's designed to run as a pre-commit hook or
standalone validation tool to maintain high security standards.

Features:
- Comprehensive scanning of all API files
- Pattern-based security risk detection
- Automatic security level classification
- Clear remediation recommendations
- Fast execution for pre-commit usage
- Configurable whitelisting for exceptions

Usage:
    # As pre-commit hook
    python scripts/validation/security/insecure_api_detector.py

    # With specific files
    python scripts/validation/security/insecure_api_detector.py verenigingen/api/member_management.py

    # Generate report only (no failure)
    python scripts/validation/security/insecure_api_detector.py --report-only

    # Show detailed analysis
    python scripts/validation/security/insecure_api_detector.py --verbose

Exit codes:
    0: All APIs are secure or no issues found
    1: Insecure APIs detected
    2: Configuration/execution error
"""

import argparse
import ast
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class SecurityLevel(Enum):
    """API Security Classification Levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    PUBLIC = "public"


class OperationType(Enum):
    """Types of operations for security classification"""
    FINANCIAL = "financial"
    MEMBER_DATA = "member_data"
    ADMIN = "admin"
    REPORTING = "reporting"
    UTILITY = "utility"
    PUBLIC = "public"


@dataclass
class SecurityIssue:
    """Represents a security issue found in an API endpoint"""
    file_path: str
    function_name: str
    line_number: int
    issue_type: str
    severity: str
    description: str
    recommended_decorator: str
    risk_factors: List[str]
    suggested_fix: str


@dataclass
class APIEndpoint:
    """Represents an API endpoint with security analysis"""
    file_path: str
    function_name: str
    line_number: int
    has_frappe_whitelist: bool
    has_security_decorators: bool
    existing_decorators: List[str]
    allow_guest: bool
    parameters: List[str]
    recommended_security_level: SecurityLevel
    operation_type: OperationType
    risk_factors: List[str]
    database_operations: List[str]
    is_secure: bool


class InsecureAPIDetector:
    """Main detector class for identifying insecure API endpoints"""

    # Security decorator patterns to look for
    SECURITY_DECORATORS = {
        'critical_api', 'high_security_api', 'standard_api', 'utility_api', 'public_api',
        'api_security_framework', 'require_csrf_token', 'rate_limit', 'require_roles',
        'audit_log', 'require_sepa_permission'
    }

    # Operation type classification patterns
    OPERATION_PATTERNS = {
        OperationType.FINANCIAL: [
            'payment', 'invoice', 'sepa', 'batch', 'debit', 'credit', 'transaction',
            'billing', 'fee', 'amount', 'money', 'financial', 'bank', 'iban', 'mt940'
        ],
        OperationType.MEMBER_DATA: [
            'member', 'user', 'person', 'contact', 'profile', 'registration',
            'application', 'signup', 'login', 'account', 'personal'
        ],
        OperationType.ADMIN: [
            'admin', 'config', 'setting', 'system', 'manage', 'control',
            'permission', 'role', 'access', 'maintenance', 'setup'
        ],
        OperationType.REPORTING: [
            'report', 'analytics', 'dashboard', 'export', 'summary',
            'statistics', 'chart', 'graph', 'list', 'view', 'get'
        ],
        OperationType.UTILITY: [
            'health', 'status', 'ping', 'test', 'debug', 'validate',
            'check', 'verify', 'util', 'helper', 'tool'
        ]
    }

    # Security level classification patterns
    SECURITY_PATTERNS = {
        SecurityLevel.CRITICAL: [
            'delete', 'remove', 'destroy', 'cancel', 'process_batch',
            'execute', 'transfer', 'payment', 'financial', 'admin',
            'create_sepa', 'process_sepa', 'import_mt940'
        ],
        SecurityLevel.HIGH: [
            'create', 'update', 'modify', 'edit', 'save', 'insert',
            'member', 'user', 'batch', 'validate', 'assign', 'manage'
        ],
        SecurityLevel.MEDIUM: [
            'get', 'list', 'view', 'read', 'fetch', 'load',
            'report', 'analytics', 'search', 'filter'
        ],
        SecurityLevel.LOW: [
            'info', 'help', 'doc', 'version', 'ping', 'health'
        ]
    }

    # Risk factor detection patterns
    RISK_PATTERNS = {
        'sql_injection_risk': [
            'frappe.db.sql', 'execute(', 'raw_sql', 'db.sql('
        ],
        'data_export_risk': [
            'export', 'download', 'csv', 'excel', 'pdf', 'backup'
        ],
        'file_operation_risk': [
            'upload', 'file', 'attachment', 'document', 'save_file'
        ],
        'external_api_risk': [
            'requests.', 'urllib', 'http', 'api_call', 'webhook'
        ],
        'authentication_risk': [
            'login', 'logout', 'auth', 'session', 'token', 'password'
        ],
        'permission_bypass_risk': [
            'ignore_permissions', 'ignore_validate', 'as_admin'
        ],
        'financial_risk': [
            'payment', 'invoice', 'money', 'amount', 'financial',
            'sepa', 'bank', 'transaction'
        ]
    }

    # Whitelist for known secure APIs or exceptions
    WHITELIST_FUNCTIONS = {
        # Add specific functions that are intentionally excluded
        'get_security_framework_status',  # Security framework status
        'analyze_api_security_status',    # Security analysis
        'get_mt940_import_url',          # Simple URL getter
    }

    def __init__(self, verbose: bool = False, report_only: bool = False):
        self.verbose = verbose
        self.report_only = report_only
        self.issues: List[SecurityIssue] = []
        self.endpoints: List[APIEndpoint] = []
        self.stats = {
            'total_files': 0,
            'total_endpoints': 0,
            'secure_endpoints': 0,
            'insecure_endpoints': 0,
            'critical_issues': 0,
            'high_issues': 0,
            'medium_issues': 0,
            'low_issues': 0
        }

    def scan_files(self, file_paths: Optional[List[str]] = None) -> bool:
        """
        Scan API files for insecure endpoints
        
        Args:
            file_paths: Optional list of specific files to scan
            
        Returns:
            True if all APIs are secure, False if issues found
        """
        start_time = time.time()
        
        if file_paths:
            files_to_scan = [Path(f) for f in file_paths if f.endswith('.py')]
        else:
            # Find all API files
            api_dir = Path('verenigingen/api')
            if not api_dir.exists():
                print(f"❌ API directory not found: {api_dir}")
                return False
            
            files_to_scan = list(api_dir.glob('*.py'))
            files_to_scan = [f for f in files_to_scan if not f.name.startswith('__')]

        self.stats['total_files'] = len(files_to_scan)
        
        if self.verbose:
            print(f"🔍 Scanning {len(files_to_scan)} API files...")

        for file_path in files_to_scan:
            try:
                self._scan_file(file_path)
            except Exception as e:
                print(f"⚠️  Error scanning {file_path}: {e}")

        # Calculate final statistics
        self.stats['total_endpoints'] = len(self.endpoints)
        self.stats['secure_endpoints'] = len([e for e in self.endpoints if e.is_secure])
        self.stats['insecure_endpoints'] = len([e for e in self.endpoints if not e.is_secure])
        
        for issue in self.issues:
            if issue.severity == 'critical':
                self.stats['critical_issues'] += 1
            elif issue.severity == 'high':
                self.stats['high_issues'] += 1
            elif issue.severity == 'medium':
                self.stats['medium_issues'] += 1
            else:
                self.stats['low_issues'] += 1

        scan_time = time.time() - start_time
        
        if self.verbose:
            print(f"✅ Scan completed in {scan_time:.2f}s")

        return len(self.issues) == 0

    def _scan_file(self, file_path: Path) -> None:
        """Scan a single Python file for API endpoints"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Could not read {file_path}: {e}")
            return

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            if self.verbose:
                print(f"⚠️  Syntax error in {file_path}: {e}")
            return

        # Find all function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                endpoint = self._analyze_function(node, file_path, content)
                if endpoint and endpoint.has_frappe_whitelist:
                    self.endpoints.append(endpoint)
                    
                    # Check if endpoint is secure
                    if not endpoint.is_secure and endpoint.function_name not in self.WHITELIST_FUNCTIONS:
                        issue = self._create_security_issue(endpoint)
                        self.issues.append(issue)

    def _analyze_function(self, node: ast.FunctionDef, file_path: Path, content: str) -> Optional[APIEndpoint]:
        """Analyze a function definition for security compliance"""
        
        # Check if function has @frappe.whitelist decorator
        has_whitelist = self._has_frappe_whitelist(node)
        if not has_whitelist:
            return None

        # Analyze function
        has_security_decorators = self._has_security_decorators(node)
        existing_decorators = self._get_existing_decorators(node)
        allow_guest = self._get_allow_guest(node)
        parameters = self._get_parameters(node)
        
        # Get function source for analysis
        function_source = self._get_function_source(node, content)
        
        # Classify the endpoint
        operation_type = self._classify_operation_type(node.name, function_source)
        security_level = self._classify_security_level(node.name, function_source, operation_type)
        risk_factors = self._analyze_risk_factors(function_source)
        database_operations = self._analyze_database_operations(function_source)
        
        # Determine if endpoint is secure
        is_secure = self._is_endpoint_secure(
            has_security_decorators, security_level, operation_type, 
            risk_factors, allow_guest, node.name
        )

        return APIEndpoint(
            file_path=str(file_path),
            function_name=node.name,
            line_number=node.lineno,
            has_frappe_whitelist=has_whitelist,
            has_security_decorators=has_security_decorators,
            existing_decorators=existing_decorators,
            allow_guest=allow_guest,
            parameters=parameters,
            recommended_security_level=security_level,
            operation_type=operation_type,
            risk_factors=risk_factors,
            database_operations=database_operations,
            is_secure=is_secure
        )

    def _has_frappe_whitelist(self, node: ast.FunctionDef) -> bool:
        """Check if function has @frappe.whitelist decorator"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute):
                if (hasattr(decorator.value, 'id') and 
                    decorator.value.id == 'frappe' and 
                    decorator.attr == 'whitelist'):
                    return True
            elif isinstance(decorator, ast.Call):
                if (isinstance(decorator.func, ast.Attribute) and
                    hasattr(decorator.func.value, 'id') and
                    decorator.func.value.id == 'frappe' and
                    decorator.func.attr == 'whitelist'):
                    return True
        return False

    def _has_security_decorators(self, node: ast.FunctionDef) -> bool:
        """Check if function has any security decorators"""
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if decorator_name in self.SECURITY_DECORATORS:
                return True
        return False

    def _get_decorator_name(self, decorator) -> str:
        """Extract decorator name from AST node"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr
        return ""

    def _get_existing_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Get list of all decorators on the function"""
        decorators = []
        for decorator in node.decorator_list:
            name = self._get_decorator_name(decorator)
            if name:
                decorators.append(name)
        return decorators

    def _get_allow_guest(self, node: ast.FunctionDef) -> bool:
        """Check if function allows guest access"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                for keyword in getattr(decorator, 'keywords', []):
                    if (keyword.arg == 'allow_guest' and 
                        hasattr(keyword.value, 'value')):
                        return keyword.value.value
        return False

    def _get_parameters(self, node: ast.FunctionDef) -> List[str]:
        """Get function parameters"""
        return [arg.arg for arg in node.args.args]

    def _get_function_source(self, node: ast.FunctionDef, content: str) -> str:
        """Extract function source code"""
        lines = content.split('\n')
        start_line = node.lineno - 1
        
        # Simple heuristic to find end of function
        end_line = start_line + 20  # Look ahead up to 20 lines
        if end_line >= len(lines):
            end_line = len(lines)
        
        return '\n'.join(lines[start_line:end_line]).lower()

    def _classify_operation_type(self, function_name: str, source: str) -> OperationType:
        """Classify the operation type based on function name and content"""
        function_lower = function_name.lower()
        
        # Score each operation type
        scores = {}
        for op_type, patterns in self.OPERATION_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if pattern in function_lower:
                    score += 3  # Function name match is high priority
                if pattern in source:
                    score += 1  # Source content match
            scores[op_type] = score
        
        # Return highest scoring operation type
        if scores:
            max_score = max(scores.values())
            if max_score > 0:
                return max(scores, key=scores.get)
        
        return OperationType.UTILITY  # Default

    def _classify_security_level(self, function_name: str, source: str, 
                               operation_type: OperationType) -> SecurityLevel:
        """Classify the recommended security level"""
        function_lower = function_name.lower()
        
        # Base security level from operation type
        operation_security_mapping = {
            OperationType.FINANCIAL: SecurityLevel.CRITICAL,
            OperationType.MEMBER_DATA: SecurityLevel.HIGH,
            OperationType.ADMIN: SecurityLevel.CRITICAL,
            OperationType.REPORTING: SecurityLevel.MEDIUM,
            OperationType.UTILITY: SecurityLevel.LOW,
            OperationType.PUBLIC: SecurityLevel.PUBLIC,
        }
        
        base_level = operation_security_mapping.get(operation_type, SecurityLevel.MEDIUM)
        
        # Adjust based on function patterns
        for level, patterns in self.SECURITY_PATTERNS.items():
            for pattern in patterns:
                if pattern in function_lower:
                    if level == SecurityLevel.CRITICAL:
                        return SecurityLevel.CRITICAL
                    elif level == SecurityLevel.HIGH and base_level in [SecurityLevel.MEDIUM, SecurityLevel.LOW]:
                        return SecurityLevel.HIGH
        
        return base_level

    def _analyze_risk_factors(self, source: str) -> List[str]:
        """Analyze source code for security risk factors"""
        risks = []
        
        for risk_type, patterns in self.RISK_PATTERNS.items():
            for pattern in patterns:
                if pattern in source:
                    risks.append(risk_type)
                    break
        
        return risks

    def _analyze_database_operations(self, source: str) -> List[str]:
        """Identify database operations in source code"""
        operations = []
        
        if any(pattern in source for pattern in ['frappe.get_doc', 'frappe.new_doc']):
            operations.append('READ')
        if any(pattern in source for pattern in ['.save()', '.insert()']):
            operations.append('WRITE')
        if any(pattern in source for pattern in ['.delete()', 'frappe.delete_doc']):
            operations.append('DELETE')
        if 'frappe.db.sql' in source:
            operations.append('SQL')
        
        return operations

    def _is_endpoint_secure(self, has_security_decorators: bool, security_level: SecurityLevel,
                          operation_type: OperationType, risk_factors: List[str], 
                          allow_guest: bool, function_name: str) -> bool:
        """Determine if an endpoint meets security requirements"""
        
        # Check for whitelisted functions
        if function_name in self.WHITELIST_FUNCTIONS:
            return True
        
        # Public endpoints don't need security decorators
        if security_level == SecurityLevel.PUBLIC:
            return True
        
        # Utility endpoints with no risk factors and safe names can be considered secure
        if (operation_type == OperationType.UTILITY and 
            security_level == SecurityLevel.LOW and 
            not risk_factors and
            not allow_guest and
            any(safe_prefix in function_name.lower() 
                for safe_prefix in ['get_', 'check_', 'validate_', 'test_'])):
            return True
        
        # All other endpoints require security decorators
        return has_security_decorators

    def _create_security_issue(self, endpoint: APIEndpoint) -> SecurityIssue:
        """Create a security issue for an insecure endpoint"""
        
        # Determine severity based on security level and risk factors
        if endpoint.recommended_security_level == SecurityLevel.CRITICAL:
            severity = 'critical'
        elif endpoint.recommended_security_level == SecurityLevel.HIGH:
            severity = 'high'
        elif any('risk' in factor for factor in endpoint.risk_factors):
            severity = 'high'
        elif endpoint.recommended_security_level == SecurityLevel.MEDIUM:
            severity = 'medium'
        else:
            severity = 'low'
        
        # Generate recommended decorator
        decorator_map = {
            SecurityLevel.CRITICAL: '@critical_api()',
            SecurityLevel.HIGH: '@high_security_api()',
            SecurityLevel.MEDIUM: '@standard_api()',
            SecurityLevel.LOW: '@utility_api()',
            SecurityLevel.PUBLIC: '@public_api()'
        }
        
        recommended_decorator = decorator_map.get(
            endpoint.recommended_security_level, '@standard_api()'
        )
        
        # Create description
        description = (
            f"API endpoint '{endpoint.function_name}' lacks security decorators. "
            f"Classified as {endpoint.operation_type.value} operation requiring "
            f"{endpoint.recommended_security_level.value} security level."
        )
        
        if endpoint.risk_factors:
            description += f" Risk factors: {', '.join(endpoint.risk_factors)}."
        
        # Generate suggested fix
        imports_needed = [
            "from verenigingen.utils.security.api_security_framework import (",
            f"    {recommended_decorator.split('(')[0][1:]},",
            "    OperationType",
            ")"
        ]
        
        suggested_fix = f"""
Add security decorator to the function:

{chr(10).join(imports_needed)}

@frappe.whitelist()
{recommended_decorator}
def {endpoint.function_name}({', '.join(endpoint.parameters)}):
    # Your existing implementation
    pass
"""
        
        return SecurityIssue(
            file_path=endpoint.file_path,
            function_name=endpoint.function_name,
            line_number=endpoint.line_number,
            issue_type='missing_security_decorator',
            severity=severity,
            description=description,
            recommended_decorator=recommended_decorator,
            risk_factors=endpoint.risk_factors,
            suggested_fix=suggested_fix.strip()
        )

    def print_results(self) -> None:
        """Print scan results in a readable format"""
        
        print("\n" + "="*80)
        print("🔒 API Security Scan Results")
        print("="*80)
        
        # Print summary statistics
        print(f"\n📊 Summary:")
        print(f"   Files scanned: {self.stats['total_files']}")
        print(f"   API endpoints: {self.stats['total_endpoints']}")
        print(f"   Secure endpoints: {self.stats['secure_endpoints']}")
        print(f"   Insecure endpoints: {self.stats['insecure_endpoints']}")
        
        if self.stats['total_endpoints'] > 0:
            coverage = (self.stats['secure_endpoints'] / self.stats['total_endpoints']) * 100
            print(f"   Security coverage: {coverage:.1f}%")
        
        # Print issue summary
        if self.issues:
            print(f"\n⚠️  Issues Found:")
            print(f"   Critical: {self.stats['critical_issues']}")
            print(f"   High: {self.stats['high_issues']}")
            print(f"   Medium: {self.stats['medium_issues']}")
            print(f"   Low: {self.stats['low_issues']}")
            
            # Print detailed issues
            print(f"\n🚨 Detailed Issues:")
            for i, issue in enumerate(self.issues, 1):
                severity_icon = {
                    'critical': '🔴',
                    'high': '🟠', 
                    'medium': '🟡',
                    'low': '🟢'
                }.get(issue.severity, '⚪')
                
                print(f"\n{i}. {severity_icon} {issue.severity.upper()}: {issue.function_name}")
                print(f"   File: {issue.file_path}:{issue.line_number}")
                print(f"   Issue: {issue.description}")
                print(f"   Fix: Add {issue.recommended_decorator}")
                
                if self.verbose and issue.suggested_fix:
                    print(f"   Complete fix:")
                    for line in issue.suggested_fix.split('\n'):
                        print(f"   {line}")
        else:
            print(f"\n✅ All API endpoints are properly secured!")
            
        print("\n" + "="*80)

    def generate_json_report(self) -> Dict:
        """Generate a JSON report of the scan results"""
        return {
            'scan_timestamp': time.time(),
            'statistics': self.stats,
            'issues': [
                {
                    'file_path': issue.file_path,
                    'function_name': issue.function_name,
                    'line_number': issue.line_number,
                    'issue_type': issue.issue_type,
                    'severity': issue.severity,
                    'description': issue.description,
                    'recommended_decorator': issue.recommended_decorator,
                    'risk_factors': issue.risk_factors,
                    'suggested_fix': issue.suggested_fix
                }
                for issue in self.issues
            ],
            'endpoints': [
                {
                    'file_path': endpoint.file_path,
                    'function_name': endpoint.function_name,
                    'line_number': endpoint.line_number,
                    'is_secure': endpoint.is_secure,
                    'security_level': endpoint.recommended_security_level.value,
                    'operation_type': endpoint.operation_type.value,
                    'risk_factors': endpoint.risk_factors,
                    'existing_decorators': endpoint.existing_decorators
                }
                for endpoint in self.endpoints
            ]
        }


def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(
        description='Detect insecure API endpoints in Verenigingen application',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan all API files
  python scripts/validation/security/insecure_api_detector.py

  # Scan specific files
  python scripts/validation/security/insecure_api_detector.py verenigingen/api/member_management.py

  # Generate report only (no failure)
  python scripts/validation/security/insecure_api_detector.py --report-only

  # Verbose output with detailed fixes
  python scripts/validation/security/insecure_api_detector.py --verbose

  # Generate JSON report
  python scripts/validation/security/insecure_api_detector.py --json-output security_report.json
        """
    )
    
    parser.add_argument(
        'files', 
        nargs='*', 
        help='Specific files to scan (default: all API files)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output with detailed recommendations'
    )
    parser.add_argument(
        '--report-only', '-r',
        action='store_true',
        help='Generate report only, do not fail on issues'
    )
    parser.add_argument(
        '--json-output', '-j',
        help='Write JSON report to specified file'
    )
    parser.add_argument(
        '--config',
        help='Path to configuration file (JSON)'
    )
    
    args = parser.parse_args()
    
    try:
        # Load configuration if provided
        if args.config and os.path.exists(args.config):
            with open(args.config, 'r') as f:
                config = json.load(f)
            # Apply configuration overrides here if needed
            
        # Initialize detector
        detector = InsecureAPIDetector(
            verbose=args.verbose,
            report_only=args.report_only
        )
        
        # Scan files
        is_secure = detector.scan_files(args.files)
        
        # Print results
        detector.print_results()
        
        # Generate JSON report if requested
        if args.json_output:
            report = detector.generate_json_report()
            with open(args.json_output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"📄 JSON report written to {args.json_output}")
        
        # Exit with appropriate code
        if args.report_only:
            sys.exit(0)
        elif not is_secure:
            print(f"\n❌ Insecure API endpoints detected. Please fix the issues above.")
            sys.exit(1)
        else:
            print(f"\n✅ All API endpoints are secure!")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Scan interrupted by user")
        sys.exit(2)
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()