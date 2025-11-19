#!/usr/bin/env python3
"""
Single API Security Validation Script
Phase 0 Infrastructure - Comprehensive Architectural Refactoring Plan v2.0

This script validates security implementation for a single API endpoint
to ensure proper @critical_api decorator application and functionality.
"""

import os
import re
import sys
import json
import argparse
from typing import Dict, List, Bool
import frappe

def validate_single_api(api_file: str, function_name: str = None) -> Dict[str, any]:
    """
    Validate security implementation for a single API
    
    Args:
        api_file: API file to validate (e.g., 'sepa_mandate_management.py')
        function_name: Specific function to validate (optional)
        
    Returns:
        Validation results dictionary
    """
    
    validation_results = {
        'api_file': api_file,
        'function_name': function_name,
        'validation_status': 'UNKNOWN',
        'checks_performed': {},
        'security_issues': [],
        'recommendations': [],
        'overall_score': 0
    }
    
    # Resolve full file path
    api_file_path = resolve_api_file_path(api_file)
    if not api_file_path:
        validation_results['validation_status'] = 'FILE_NOT_FOUND'
        validation_results['security_issues'].append(f"API file not found: {api_file}")
        return validation_results
    
    # Perform validation checks
    validation_results['checks_performed']['decorator_check'] = check_critical_api_decorator(
        api_file_path, function_name, validation_results
    )
    
    validation_results['checks_performed']['permission_check'] = check_permission_validation(
        api_file_path, function_name, validation_results
    )
    
    validation_results['checks_performed']['input_validation'] = check_input_validation(
        api_file_path, function_name, validation_results
    )
    
    validation_results['checks_performed']['error_handling'] = check_error_handling(
        api_file_path, function_name, validation_results
    )
    
    validation_results['checks_performed']['audit_logging'] = check_audit_logging(
        api_file_path, function_name, validation_results
    )
    
    # Calculate overall score and status
    validation_results['overall_score'] = calculate_validation_score(validation_results['checks_performed'])
    validation_results['validation_status'] = determine_validation_status(validation_results['overall_score'])
    
    # Generate recommendations
    validation_results['recommendations'] = generate_validation_recommendations(validation_results)
    
    return validation_results

def resolve_api_file_path(api_file: str) -> str:
    """Resolve the full path to the API file"""
    
    # Handle different input formats
    if api_file.startswith('verenigingen/api/'):
        relative_path = api_file
    elif api_file.startswith('api/'):
        relative_path = f"verenigingen/{api_file}"
    elif '/' not in api_file:
        relative_path = f"verenigingen/api/{api_file}"
    else:
        relative_path = api_file
    
    full_path = f"/home/frappe/frappe-bench/apps/verenigingen/{relative_path}"
    
    return full_path if os.path.exists(full_path) else None

def check_critical_api_decorator(file_path: str, function_name: str, results: Dict) -> Bool:
    """Check if @critical_api decorator is properly applied"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        functions_to_check = []
        
        if function_name:
            # Check specific function
            functions_to_check.append(function_name)
        else:
            # Check all @frappe.whitelist() functions
            functions_to_check = find_all_whitelisted_functions(lines)
        
        decorator_issues = []
        decorator_found = False
        
        for func_name in functions_to_check:
            func_line_number = find_function_line(lines, func_name)
            if func_line_number:
                # Check for @critical_api decorator in the lines before the function
                has_critical_api = False
                decorator_params = {}
                
                for i in range(max(0, func_line_number - 5), func_line_number):
                    if '@critical_api' in lines[i]:
                        has_critical_api = True
                        decorator_found = True
                        decorator_params = parse_critical_api_decorator(lines[i])
                        break
                
                if not has_critical_api:
                    decorator_issues.append(f"Function '{func_name}' missing @critical_api decorator")
                else:
                    # Validate decorator parameters
                    param_issues = validate_decorator_parameters(func_name, decorator_params)
                    decorator_issues.extend(param_issues)
        
        if decorator_issues:
            results['security_issues'].extend(decorator_issues)
        
        return decorator_found and len(decorator_issues) == 0
        
    except Exception as e:
        results['security_issues'].append(f"Error checking @critical_api decorator: {e}")
        return False

def find_all_whitelisted_functions(lines: List[str]) -> List[str]:
    """Find all functions with @frappe.whitelist() decorator"""
    
    whitelisted_functions = []
    
    for i, line in enumerate(lines):
        if '@frappe.whitelist()' in line:
            # Look for function definition in next few lines
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip().startswith('def '):
                    func_name = extract_function_name(lines[j])
                    if func_name:
                        whitelisted_functions.append(func_name)
                    break
    
    return whitelisted_functions

def find_function_line(lines: List[str], function_name: str) -> int:
    """Find the line number where a function is defined"""
    
    for i, line in enumerate(lines):
        if line.strip().startswith(f'def {function_name}('):
            return i
    
    return None

def parse_critical_api_decorator(decorator_line: str) -> Dict[str, str]:
    """Parse @critical_api decorator parameters"""
    
    params = {}
    
    # Extract operation_type
    operation_match = re.search(r'operation_type\s*=\s*OperationType\.(\w+)', decorator_line)
    if operation_match:
        params['operation_type'] = operation_match.group(1)
    
    # Extract audit_required
    audit_match = re.search(r'audit_required\s*=\s*(True|False)', decorator_line)
    if audit_match:
        params['audit_required'] = audit_match.group(1)
    
    # Extract role_required
    role_match = re.search(r'role_required\s*=\s*["\']([^"\']+)["\']', decorator_line)
    if role_match:
        params['role_required'] = role_match.group(1)
    
    return params

def validate_decorator_parameters(function_name: str, params: Dict[str, str]) -> List[str]:
    """Validate @critical_api decorator parameters"""
    
    issues = []
    
    # Check for required operation_type
    if 'operation_type' not in params:
        issues.append(f"Function '{function_name}' @critical_api missing operation_type parameter")
    else:
        valid_operation_types = ['FINANCIAL', 'ADMINISTRATIVE', 'DATA_ACCESS', 'SYSTEM']
        if params['operation_type'] not in valid_operation_types:
            issues.append(f"Function '{function_name}' has invalid operation_type: {params['operation_type']}")
    
    # Check for audit_required for financial operations
    if params.get('operation_type') == 'FINANCIAL' and params.get('audit_required') != 'True':
        issues.append(f"Function '{function_name}' financial operation should have audit_required=True")
    
    return issues

def check_permission_validation(file_path: str, function_name: str, results: Dict) -> Bool:
    """Check if proper permission validation is implemented"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        permission_patterns = [
            r'frappe\.has_permission\(',
            r'frappe\.only_for\(',
            r'check_permission\(',
            r'validate_permission\(',
            r'frappe\.permissions\.',
            r'if not.*permission',
            r'insufficient.*permission'
        ]
        
        permission_checks_found = 0
        for pattern in permission_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            permission_checks_found += len(matches)
        
        if permission_checks_found == 0:
            results['security_issues'].append("No permission validation patterns found")
            return False
        
        return True
        
    except Exception as e:
        results['security_issues'].append(f"Error checking permission validation: {e}")
        return False

def check_input_validation(file_path: str, function_name: str, results: Dict) -> Bool:
    """Check if proper input validation is implemented"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        validation_patterns = [
            r'frappe\.validate\(',
            r'validate_\w+\(',
            r'frappe\.throw\(',
            r'if not.*throw',
            r'ValidationError',
            r'frappe\.utils\.validate\.',
            r'\.strip\(\)',
            r'\.lower\(\)',
            r'len\(.*\)\s*[<>]=?'
        ]
        
        validation_checks_found = 0
        for pattern in validation_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            validation_checks_found += len(matches)
        
        if validation_checks_found < 2:
            results['security_issues'].append("Limited input validation patterns found")
            return False
        
        return True
        
    except Exception as e:
        results['security_issues'].append(f"Error checking input validation: {e}")
        return False

def check_error_handling(file_path: str, function_name: str, results: Dict) -> Bool:
    """Check if proper error handling is implemented"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        error_handling_patterns = [
            r'try:',
            r'except\s+\w+',
            r'frappe\.log_error\(',
            r'frappe\.throw\(',
            r'SecurityException',
            r'except Exception as e:',
            r'finally:'
        ]
        
        error_handling_found = 0
        for pattern in error_handling_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            error_handling_found += len(matches)
        
        if error_handling_found < 3:
            results['security_issues'].append("Limited error handling patterns found")
            return False
        
        return True
        
    except Exception as e:
        results['security_issues'].append(f"Error checking error handling: {e}")
        return False

def check_audit_logging(file_path: str, function_name: str, results: Dict) -> Bool:
    """Check if proper audit logging is implemented"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        audit_patterns = [
            r'frappe\.log_error\(',
            r'audit_log\(',
            r'log_security_event\(',
            r'SecurityException',
            r'frappe\.msgprint\(',
            r'frappe\.logger\.'
        ]
        
        audit_logging_found = 0
        for pattern in audit_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            audit_logging_found += len(matches)
        
        if audit_logging_found == 0:
            results['security_issues'].append("No audit logging patterns found")
            return False
        
        return True
        
    except Exception as e:
        results['security_issues'].append(f"Error checking audit logging: {e}")
        return False

def calculate_validation_score(checks: Dict[str, Bool]) -> int:
    """Calculate overall validation score (0-100)"""
    
    if not checks:
        return 0
    
    passed_checks = sum(1 for result in checks.values() if result)
    total_checks = len(checks)
    
    return int((passed_checks / total_checks) * 100)

def determine_validation_status(score: int) -> str:
    """Determine validation status based on score"""
    
    if score >= 90:
        return 'EXCELLENT'
    elif score >= 75:
        return 'GOOD'
    elif score >= 50:
        return 'NEEDS_IMPROVEMENT'
    elif score >= 25:
        return 'POOR'
    else:
        return 'CRITICAL'

def generate_validation_recommendations(results: Dict) -> List[Dict]:
    """Generate specific recommendations based on validation results"""
    
    recommendations = []
    checks = results.get('checks_performed', {})
    
    if not checks.get('decorator_check', False):
        recommendations.append({
            'priority': 'CRITICAL',
            'category': 'Security Decorator',
            'recommendation': 'Add @critical_api decorator with appropriate parameters',
            'action': 'Apply @critical_api(operation_type=OperationType.FINANCIAL, audit_required=True)'
        })
    
    if not checks.get('permission_check', False):
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Permission Validation',
            'recommendation': 'Implement permission checking in function logic',
            'action': 'Add frappe.has_permission() checks before sensitive operations'
        })
    
    if not checks.get('input_validation', False):
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Input Validation',
            'recommendation': 'Add comprehensive input validation',
            'action': 'Validate all parameters using frappe.validate() and custom checks'
        })
    
    if not checks.get('error_handling', False):
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Error Handling',
            'recommendation': 'Implement proper error handling with try-except blocks',
            'action': 'Add SecurityException handling and user-friendly error messages'
        })
    
    if not checks.get('audit_logging', False):
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Audit Logging',
            'recommendation': 'Add audit logging for security events',
            'action': 'Log security violations and access attempts'
        })
    
    return recommendations

def extract_function_name(function_line: str) -> str:
    """Extract function name from a function definition line"""
    match = re.search(r'def\s+(\w+)', function_line)
    return match.group(1) if match else None

def generate_validation_report(results: Dict) -> str:
    """Generate a formatted validation report"""
    
    report = []
    report.append(f"# API Security Validation Report")
    report.append(f"**API File**: {results['api_file']}")
    if results.get('function_name'):
        report.append(f"**Function**: {results['function_name']}")
    report.append(f"**Generated**: {frappe.utils.now()}")
    report.append("")
    
    # Overall status
    status = results.get('validation_status', 'UNKNOWN')
    score = results.get('overall_score', 0)
    report.append(f"## Overall Status: {status} ({score}/100)")
    report.append("")
    
    # Validation checks
    checks = results.get('checks_performed', {})
    report.append("## Validation Checks")
    for check_name, passed in checks.items():
        status_icon = "✅" if passed else "❌"
        check_display = check_name.replace('_', ' ').title()
        report.append(f"- {status_icon} {check_display}")
    report.append("")
    
    # Security issues
    issues = results.get('security_issues', [])
    if issues:
        report.append("## Security Issues Found")
        for i, issue in enumerate(issues, 1):
            report.append(f"{i}. {issue}")
        report.append("")
    
    # Recommendations
    recommendations = results.get('recommendations', [])
    if recommendations:
        report.append("## Recommendations")
        for rec in recommendations:
            report.append(f"### {rec['priority']}: {rec['category']}")
            report.append(f"- **Issue**: {rec['recommendation']}")
            report.append(f"- **Action**: {rec['action']}")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution function"""
    
    parser = argparse.ArgumentParser(description='Validate security implementation for a single API')
    parser.add_argument('--api', required=True, help='API file to validate (e.g., sepa_mandate_management.py)')
    parser.add_argument('--function', help='Specific function to validate (optional)')
    parser.add_argument('--output', help='Output file for validation report (optional)')
    
    args = parser.parse_args()
    
    print(f"🔍 Validating API security: {args.api}")
    if args.function:
        print(f"🎯 Specific function: {args.function}")
    
    try:
        validation_results = validate_single_api(args.api, args.function)
        
        # Generate report
        report = generate_validation_report(validation_results)
        
        # Save or print report
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"📄 Report saved to: {args.output}")
        else:
            print("\n" + report)
        
        # Save JSON data
        json_file = f"{args.api.replace('.py', '')}_validation_results.json"
        with open(json_file, 'w') as f:
            json.dump(validation_results, f, indent=2)
        
        # Print summary
        status = validation_results.get('validation_status', 'UNKNOWN')
        score = validation_results.get('overall_score', 0)
        print(f"\n✅ Validation complete: {status} ({score}/100)")
        
        # Exit with appropriate code
        if status in ['CRITICAL', 'POOR']:
            sys.exit(1)
        elif status == 'NEEDS_IMPROVEMENT':
            sys.exit(2)
        else:
            sys.exit(0)
        
    except Exception as e:
        print(f"❌ Error during API validation: {e}")
        sys.exit(3)

if __name__ == '__main__':
    main()