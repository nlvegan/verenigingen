#!/usr/bin/env python3
"""
API Security Framework Validator

This script validates that all API endpoints follow the established security
framework patterns and provides comprehensive security compliance checking.
It complements the insecure_api_detector.py by focusing on framework compliance
and security pattern validation.

Features:
- Security decorator validation
- Framework compliance checking
- Security pattern verification
- Risk assessment validation
- Performance impact analysis
- Migration status tracking

Usage:
    python scripts/validation/security/api_security_validator.py
    python scripts/validation/security/api_security_validator.py --file verenigingen/api/member_management.py
    python scripts/validation/security/api_security_validator.py --check-patterns
    python scripts/validation/security/api_security_validator.py --generate-report
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


class ComplianceLevel(Enum):
    """Security framework compliance levels"""
    FULLY_COMPLIANT = "fully_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"


class ValidationResult(Enum):
    """Validation result types"""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


@dataclass
class SecurityValidation:
    """Represents a security validation check result"""
    check_name: str
    result: ValidationResult
    message: str
    file_path: str
    function_name: str
    line_number: int
    recommendation: Optional[str] = None
    impact: str = "medium"


@dataclass
class APISecurityProfile:
    """Complete security profile for an API endpoint"""
    file_path: str
    function_name: str
    line_number: int
    
    # Framework compliance
    compliance_level: ComplianceLevel
    has_security_framework: bool
    security_decorator: Optional[str]
    framework_version: str
    
    # Security patterns
    follows_naming_conventions: bool
    has_proper_documentation: bool
    implements_input_validation: bool
    has_error_handling: bool
    uses_audit_logging: bool
    
    # Risk assessment
    handles_sensitive_data: bool
    requires_authentication: bool
    requires_authorization: bool
    has_rate_limiting: bool
    implements_csrf_protection: bool
    
    # Performance and monitoring
    has_performance_monitoring: bool
    estimated_impact: str
    monitoring_enabled: bool
    
    # Validation results
    validations: List[SecurityValidation]
    overall_score: float
    migration_needed: bool


class APISecurityValidator:
    """Comprehensive API security framework validator"""
    
    # Expected security decorators in the framework
    FRAMEWORK_DECORATORS = {
        '@critical_api', '@high_security_api', '@standard_api', 
        '@utility_api', '@public_api', '@api_security_framework'
    }
    
    # Security framework imports to look for
    FRAMEWORK_IMPORTS = {
        'api_security_framework', 'critical_api', 'high_security_api',
        'standard_api', 'utility_api', 'public_api', 'SecurityLevel',
        'OperationType'
    }
    
    # Performance monitoring decorators
    PERFORMANCE_DECORATORS = {
        '@performance_monitor', '@handle_api_error', '@validate_with_schema'
    }
    
    # Input validation patterns
    VALIDATION_PATTERNS = [
        'validate_required_fields', 'validate_with_schema', 'APIValidator',
        'sanitize_text', 'validate_input', 'check_parameters'
    ]
    
    # Error handling patterns
    ERROR_HANDLING_PATTERNS = [
        'handle_api_error', 'try:', 'except:', 'ValidationError',
        'PermissionError', 'frappe.throw', 'log_error'
    ]
    
    # Audit logging patterns
    AUDIT_PATTERNS = [
        'audit_logger', 'log_event', 'AuditEventType', 'get_audit_logger'
    ]
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.profiles: List[APISecurityProfile] = []
        self.validations: List[SecurityValidation] = []
        self.stats = {
            'total_endpoints': 0,
            'fully_compliant': 0,
            'partially_compliant': 0,
            'non_compliant': 0,
            'migration_needed': 0,
            'average_score': 0.0
        }

    def validate_files(self, file_paths: Optional[List[str]] = None) -> bool:
        """
        Validate API files for security framework compliance
        
        Args:
            file_paths: Optional list of specific files to validate
            
        Returns:
            True if all validations pass, False otherwise
        """
        start_time = time.time()
        
        if file_paths:
            files_to_validate = [Path(f) for f in file_paths if f.endswith('.py')]
        else:
            # Find all API files
            api_dir = Path('verenigingen/api')
            if not api_dir.exists():
                print(f"❌ API directory not found: {api_dir}")
                return False
            
            files_to_validate = list(api_dir.glob('*.py'))
            files_to_validate = [f for f in files_to_validate if not f.name.startswith('__')]

        if self.verbose:
            print(f"🔍 Validating {len(files_to_validate)} API files...")

        for file_path in files_to_validate:
            try:
                self._validate_file(file_path)
            except Exception as e:
                print(f"⚠️  Error validating {file_path}: {e}")

        # Calculate final statistics
        self._calculate_statistics()
        
        validation_time = time.time() - start_time
        if self.verbose:
            print(f"✅ Validation completed in {validation_time:.2f}s")

        # Check if all critical validations pass
        critical_failures = [v for v in self.validations if v.result == ValidationResult.FAIL]
        return len(critical_failures) == 0

    def _validate_file(self, file_path: Path) -> None:
        """Validate a single Python file for security compliance"""
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

        # Check file-level imports
        framework_imports = self._check_framework_imports(content)
        
        # Find all function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if self._has_frappe_whitelist(node):
                    profile = self._create_security_profile(
                        node, file_path, content, framework_imports
                    )
                    self.profiles.append(profile)
                    self.validations.extend(profile.validations)

    def _check_framework_imports(self, content: str) -> Set[str]:
        """Check which security framework components are imported"""
        imports_found = set()
        
        for import_name in self.FRAMEWORK_IMPORTS:
            if import_name in content:
                imports_found.add(import_name)
        
        return imports_found

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

    def _create_security_profile(self, node: ast.FunctionDef, file_path: Path, 
                               content: str, framework_imports: Set[str]) -> APISecurityProfile:
        """Create a comprehensive security profile for an API endpoint"""
        
        function_name = node.name
        line_number = node.lineno
        
        # Get function source
        function_source = self._get_function_source(node, content)
        
        # Analyze decorators
        decorators = self._get_all_decorators(node)
        security_decorator = self._get_security_decorator(decorators)
        
        # Run all validation checks
        validations = []
        
        # Framework compliance checks
        validations.extend(self._validate_framework_compliance(
            function_name, decorators, framework_imports, str(file_path), line_number
        ))
        
        # Security pattern checks
        validations.extend(self._validate_security_patterns(
            function_name, function_source, str(file_path), line_number
        ))
        
        # Documentation checks
        validations.extend(self._validate_documentation(
            node, function_name, str(file_path), line_number
        ))
        
        # Implementation checks
        validations.extend(self._validate_implementation_quality(
            function_source, function_name, str(file_path), line_number
        ))
        
        # Calculate compliance level and score
        compliance_level = self._calculate_compliance_level(validations)
        overall_score = self._calculate_score(validations)
        
        # Determine if migration is needed
        migration_needed = (
            compliance_level == ComplianceLevel.NON_COMPLIANT or
            security_decorator is None
        )
        
        return APISecurityProfile(
            file_path=str(file_path),
            function_name=function_name,
            line_number=line_number,
            compliance_level=compliance_level,
            has_security_framework=security_decorator is not None,
            security_decorator=security_decorator,
            framework_version="1.0",  # Current framework version
            follows_naming_conventions=self._check_naming_conventions(function_name),
            has_proper_documentation=ast.get_docstring(node) is not None,
            implements_input_validation=any(p in function_source for p in self.VALIDATION_PATTERNS),
            has_error_handling=any(p in function_source for p in self.ERROR_HANDLING_PATTERNS),
            uses_audit_logging=any(p in function_source for p in self.AUDIT_PATTERNS),
            handles_sensitive_data=self._handles_sensitive_data(function_source),
            requires_authentication=not self._allows_guest_access(node),
            requires_authorization=self._requires_authorization(function_source),
            has_rate_limiting=security_decorator is not None,
            implements_csrf_protection=security_decorator is not None,
            has_performance_monitoring=any(d in decorators for d in self.PERFORMANCE_DECORATORS),
            estimated_impact=self._estimate_performance_impact(function_source),
            monitoring_enabled=security_decorator is not None,
            validations=validations,
            overall_score=overall_score,
            migration_needed=migration_needed
        )

    def _get_all_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Get all decorators applied to the function"""
        decorators = []
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                decorators.append(f"@{decorator.id}")
            elif isinstance(decorator, ast.Attribute):
                decorators.append(f"@{decorator.attr}")
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    decorators.append(f"@{decorator.func.id}")
                elif isinstance(decorator.func, ast.Attribute):
                    decorators.append(f"@{decorator.func.attr}")
        return decorators

    def _get_security_decorator(self, decorators: List[str]) -> Optional[str]:
        """Get the security framework decorator if present"""
        for decorator in decorators:
            if any(framework_dec in decorator for framework_dec in self.FRAMEWORK_DECORATORS):
                return decorator
        return None

    def _get_function_source(self, node: ast.FunctionDef, content: str) -> str:
        """Extract function source code"""
        lines = content.split('\n')
        start_line = node.lineno - 1
        
        # Simple heuristic to find end of function
        end_line = min(start_line + 50, len(lines))  # Look ahead up to 50 lines
        
        return '\n'.join(lines[start_line:end_line])

    def _validate_framework_compliance(self, function_name: str, decorators: List[str],
                                     framework_imports: Set[str], file_path: str, 
                                     line_number: int) -> List[SecurityValidation]:
        """Validate compliance with security framework"""
        validations = []
        
        # Check for security decorator
        has_security_decorator = any(
            framework_dec in decorator 
            for decorator in decorators 
            for framework_dec in self.FRAMEWORK_DECORATORS
        )
        
        if not has_security_decorator:
            validations.append(SecurityValidation(
                check_name="security_decorator_required",
                result=ValidationResult.FAIL,
                message="Function lacks required security framework decorator",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Add appropriate security decorator (@critical_api, @high_security_api, etc.)",
                impact="high"
            ))
        else:
            validations.append(SecurityValidation(
                check_name="security_decorator_present",
                result=ValidationResult.PASS,
                message="Function has security framework decorator",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                impact="low"
            ))
        
        # Check for proper imports
        required_imports = {'api_security_framework', 'SecurityLevel', 'OperationType'}
        missing_imports = required_imports - framework_imports
        
        if missing_imports and has_security_decorator:
            validations.append(SecurityValidation(
                check_name="framework_imports_missing",
                result=ValidationResult.WARN,
                message=f"Missing framework imports: {', '.join(missing_imports)}",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Import required framework components",
                impact="medium"
            ))
        
        return validations

    def _validate_security_patterns(self, function_name: str, function_source: str,
                                  file_path: str, line_number: int) -> List[SecurityValidation]:
        """Validate security implementation patterns"""
        validations = []
        
        # Check for input validation
        has_input_validation = any(p in function_source for p in self.VALIDATION_PATTERNS)
        
        if not has_input_validation and 'create' in function_name.lower():
            validations.append(SecurityValidation(
                check_name="input_validation_missing",
                result=ValidationResult.WARN,
                message="Create/modify function should implement input validation",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Add input validation using validate_required_fields or validate_with_schema",
                impact="medium"
            ))
        
        # Check for error handling
        has_error_handling = any(p in function_source for p in self.ERROR_HANDLING_PATTERNS)
        
        if not has_error_handling:
            validations.append(SecurityValidation(
                check_name="error_handling_missing",
                result=ValidationResult.WARN,
                message="Function should implement proper error handling",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Add try/except blocks and use handle_api_error decorator",
                impact="medium"
            ))
        
        # Check for SQL injection risks
        if 'frappe.db.sql' in function_source and '%s' not in function_source:
            validations.append(SecurityValidation(
                check_name="sql_injection_risk",
                result=ValidationResult.FAIL,
                message="Potential SQL injection vulnerability detected",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Use parameterized queries with %s placeholders",
                impact="critical"
            ))
        
        return validations

    def _validate_documentation(self, node: ast.FunctionDef, function_name: str,
                              file_path: str, line_number: int) -> List[SecurityValidation]:
        """Validate function documentation"""
        validations = []
        
        docstring = ast.get_docstring(node)
        
        if not docstring:
            validations.append(SecurityValidation(
                check_name="documentation_missing",
                result=ValidationResult.WARN,
                message="Function lacks docstring documentation",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Add comprehensive docstring with parameter and return descriptions",
                impact="low"
            ))
        elif len(docstring) < 20:
            validations.append(SecurityValidation(
                check_name="documentation_insufficient",
                result=ValidationResult.WARN,
                message="Function docstring is too brief",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Expand docstring with detailed description and usage examples",
                impact="low"
            ))
        
        return validations

    def _validate_implementation_quality(self, function_source: str, function_name: str,
                                       file_path: str, line_number: int) -> List[SecurityValidation]:
        """Validate implementation quality and best practices"""
        validations = []
        
        # Check for hardcoded secrets
        secret_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
            r'key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']'
        ]
        
        for pattern in secret_patterns:
            if re.search(pattern, function_source, re.IGNORECASE):
                validations.append(SecurityValidation(
                    check_name="hardcoded_secret",
                    result=ValidationResult.FAIL,
                    message="Potential hardcoded secret detected",
                    file_path=file_path,
                    function_name=function_name,
                    line_number=line_number,
                    recommendation="Use environment variables or secure configuration for secrets",
                    impact="critical"
                ))
                break
        
        # Check for ignore_permissions usage
        if 'ignore_permissions=True' in function_source:
            validations.append(SecurityValidation(
                check_name="permission_bypass",
                result=ValidationResult.FAIL,
                message="Function bypasses permission checks",
                file_path=file_path,
                function_name=function_name,
                line_number=line_number,
                recommendation="Remove ignore_permissions and implement proper authorization",
                impact="high"
            ))
        
        return validations

    def _check_naming_conventions(self, function_name: str) -> bool:
        """Check if function follows naming conventions"""
        # API functions should be descriptive and follow snake_case
        if not function_name.islower():
            return False
        
        # Should not be too short or use abbreviations
        if len(function_name) < 3:
            return False
        
        # Should be descriptive
        vague_names = ['process', 'handle', 'do', 'run', 'execute', 'func', 'method']
        if function_name in vague_names:
            return False
        
        return True

    def _handles_sensitive_data(self, function_source: str) -> bool:
        """Check if function handles sensitive data"""
        sensitive_patterns = [
            'member', 'user', 'payment', 'financial', 'sepa', 'bank',
            'personal', 'address', 'email', 'phone', 'iban'
        ]
        
        return any(pattern in function_source.lower() for pattern in sensitive_patterns)

    def _allows_guest_access(self, node: ast.FunctionDef) -> bool:
        """Check if function allows guest access"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                for keyword in getattr(decorator, 'keywords', []):
                    if (keyword.arg == 'allow_guest' and 
                        hasattr(keyword.value, 'value')):
                        return keyword.value.value
        return False

    def _requires_authorization(self, function_source: str) -> bool:
        """Check if function requires special authorization"""
        auth_patterns = [
            'admin', 'manager', 'permission', 'role', 'access',
            'authorize', 'check_permission'
        ]
        
        return any(pattern in function_source.lower() for pattern in auth_patterns)

    def _estimate_performance_impact(self, function_source: str) -> str:
        """Estimate the performance impact of the function"""
        # Simple heuristic based on operations
        high_impact_patterns = [
            'frappe.db.sql', 'for', 'while', 'import', 'requests.'
        ]
        
        medium_impact_patterns = [
            'get_all', 'get_doc', 'frappe.get_list'
        ]
        
        if any(pattern in function_source for pattern in high_impact_patterns):
            return "high"
        elif any(pattern in function_source for pattern in medium_impact_patterns):
            return "medium"
        else:
            return "low"

    def _calculate_compliance_level(self, validations: List[SecurityValidation]) -> ComplianceLevel:
        """Calculate overall compliance level"""
        failures = [v for v in validations if v.result == ValidationResult.FAIL]
        warnings = [v for v in validations if v.result == ValidationResult.WARN]
        
        if len(failures) > 0:
            return ComplianceLevel.NON_COMPLIANT
        elif len(warnings) > 2:
            return ComplianceLevel.PARTIALLY_COMPLIANT
        elif len(warnings) > 0:
            return ComplianceLevel.PARTIALLY_COMPLIANT
        else:
            return ComplianceLevel.FULLY_COMPLIANT

    def _calculate_score(self, validations: List[SecurityValidation]) -> float:
        """Calculate overall security score (0-100)"""
        if not validations:
            return 0.0
        
        total_weight = 0
        weighted_score = 0
        
        for validation in validations:
            weight = {
                "critical": 10,
                "high": 6,
                "medium": 3,
                "low": 1
            }.get(validation.impact, 1)
            
            score = {
                ValidationResult.PASS: 100,
                ValidationResult.WARN: 50,
                ValidationResult.FAIL: 0,
                ValidationResult.INFO: 100
            }.get(validation.result, 0)
            
            total_weight += weight
            weighted_score += weight * score
        
        return weighted_score / total_weight if total_weight > 0 else 0.0

    def _calculate_statistics(self) -> None:
        """Calculate overall statistics"""
        self.stats['total_endpoints'] = len(self.profiles)
        
        for profile in self.profiles:
            if profile.compliance_level == ComplianceLevel.FULLY_COMPLIANT:
                self.stats['fully_compliant'] += 1
            elif profile.compliance_level == ComplianceLevel.PARTIALLY_COMPLIANT:
                self.stats['partially_compliant'] += 1
            elif profile.compliance_level == ComplianceLevel.NON_COMPLIANT:
                self.stats['non_compliant'] += 1
            
            if profile.migration_needed:
                self.stats['migration_needed'] += 1
        
        if self.profiles:
            self.stats['average_score'] = sum(p.overall_score for p in self.profiles) / len(self.profiles)

    def print_results(self) -> None:
        """Print validation results in a readable format"""
        
        print("\n" + "="*80)
        print("🛡️  API Security Framework Validation Results")
        print("="*80)
        
        # Print summary statistics
        print(f"\n📊 Summary:")
        print(f"   Total endpoints: {self.stats['total_endpoints']}")
        print(f"   Fully compliant: {self.stats['fully_compliant']}")
        print(f"   Partially compliant: {self.stats['partially_compliant']}")
        print(f"   Non-compliant: {self.stats['non_compliant']}")
        print(f"   Migration needed: {self.stats['migration_needed']}")
        print(f"   Average score: {self.stats['average_score']:.1f}/100")
        
        # Print validation issues
        critical_validations = [v for v in self.validations if v.result == ValidationResult.FAIL]
        warning_validations = [v for v in self.validations if v.result == ValidationResult.WARN]
        
        if critical_validations:
            print(f"\n🚨 Critical Issues ({len(critical_validations)}):")
            for validation in critical_validations:
                print(f"   ❌ {validation.function_name}: {validation.message}")
                if validation.recommendation:
                    print(f"      💡 {validation.recommendation}")
        
        if warning_validations and self.verbose:
            print(f"\n⚠️  Warnings ({len(warning_validations)}):")
            for validation in warning_validations[:5]:  # Limit to first 5
                print(f"   ⚠️  {validation.function_name}: {validation.message}")
        
        # Print top recommendations
        non_compliant_profiles = [p for p in self.profiles if p.compliance_level == ComplianceLevel.NON_COMPLIANT]
        if non_compliant_profiles:
            print(f"\n🔧 Top Migration Priorities:")
            for profile in sorted(non_compliant_profiles, key=lambda x: x.overall_score)[:5]:
                print(f"   📁 {profile.function_name} (Score: {profile.overall_score:.0f}/100)")
                print(f"      File: {profile.file_path}:{profile.line_number}")
        
        print("\n" + "="*80)

    def generate_json_report(self) -> Dict:
        """Generate a JSON report of validation results"""
        return {
            'validation_timestamp': time.time(),
            'framework_version': '1.0',
            'statistics': self.stats,
            'validations': [
                {
                    'check_name': v.check_name,
                    'result': v.result.value,
                    'message': v.message,
                    'file_path': v.file_path,
                    'function_name': v.function_name,
                    'line_number': v.line_number,
                    'recommendation': v.recommendation,
                    'impact': v.impact
                }
                for v in self.validations
            ],
            'profiles': [
                {
                    'function_name': p.function_name,
                    'file_path': p.file_path,
                    'compliance_level': p.compliance_level.value,
                    'security_decorator': p.security_decorator,
                    'overall_score': p.overall_score,
                    'migration_needed': p.migration_needed,
                    'handles_sensitive_data': p.handles_sensitive_data,
                    'estimated_impact': p.estimated_impact
                }
                for p in self.profiles
            ]
        }


def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(
        description='Validate API security framework compliance',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('files', nargs='*', help='Specific files to validate')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--json-output', '-j', help='Write JSON report to file')
    parser.add_argument('--check-patterns', action='store_true', help='Check security patterns only')
    parser.add_argument('--generate-report', action='store_true', help='Generate comprehensive report')
    
    args = parser.parse_args()
    
    try:
        validator = APISecurityValidator(verbose=args.verbose)
        
        # Run validation
        all_valid = validator.validate_files(args.files)
        
        # Print results
        validator.print_results()
        
        # Generate JSON report if requested
        if args.json_output:
            report = validator.generate_json_report()
            with open(args.json_output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"📄 JSON report written to {args.json_output}")
        
        # Exit with appropriate code
        if not all_valid:
            print(f"\n❌ Security framework validation failed")
            sys.exit(1)
        else:
            print(f"\n✅ All API endpoints pass security framework validation")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Validation interrupted by user")
        sys.exit(2)
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()