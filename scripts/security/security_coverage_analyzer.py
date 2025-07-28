#!/usr/bin/env python3
"""
Security Coverage Analyzer Script
Phase 0 Infrastructure - Comprehensive Architectural Refactoring Plan v2.0

This script analyzes the current security implementation coverage
and maps existing security patterns vs required coverage.
"""

import os
import re
import json
from typing import Dict, List, Set
import frappe

def analyze_security_coverage() -> Dict[str, any]:
    """
    Analyze current security implementation coverage across the app
    
    Returns:
        Comprehensive security coverage analysis
    """
    
    coverage_analysis = {
        'existing_critical_api_usage': {},
        'unprotected_apis': {},
        'security_patterns': {},
        'coverage_statistics': {},
        'recommendations': []
    }
    
    # Analyze existing @critical_api usage
    coverage_analysis['existing_critical_api_usage'] = analyze_existing_critical_api()
    
    # Find unprotected APIs
    coverage_analysis['unprotected_apis'] = find_unprotected_apis()
    
    # Analyze security patterns
    coverage_analysis['security_patterns'] = analyze_security_patterns()
    
    # Calculate coverage statistics
    coverage_analysis['coverage_statistics'] = calculate_coverage_statistics(
        coverage_analysis['existing_critical_api_usage'],
        coverage_analysis['unprotected_apis']
    )
    
    # Generate recommendations
    coverage_analysis['recommendations'] = generate_security_recommendations(coverage_analysis)
    
    return coverage_analysis

def analyze_existing_critical_api() -> Dict[str, List[Dict]]:
    """
    Analyze existing @critical_api decorator usage
    
    Returns:
        Dictionary mapping files to their @critical_api implementations
    """
    
    existing_usage = {}
    
    # Search for @critical_api usage across the app
    search_directories = [
        '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api',
        '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils',
        '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/doctype'
    ]
    
    for directory in search_directories:
        if os.path.exists(directory):
            scan_directory_for_critical_api(directory, existing_usage)
    
    return existing_usage

def scan_directory_for_critical_api(directory: str, usage_dict: Dict[str, List[Dict]]):
    """Recursively scan directory for @critical_api usage"""
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, '/home/frappe/frappe-bench/apps/verenigingen')
                
                critical_apis = find_critical_api_in_file(file_path)
                if critical_apis:
                    usage_dict[relative_path] = critical_apis

def find_critical_api_in_file(file_path: str) -> List[Dict]:
    """Find @critical_api decorators in a specific file"""
    
    critical_apis = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@critical_api' in line:
                # Extract decorator parameters
                decorator_info = parse_critical_api_decorator(line)
                
                # Find associated function
                function_name = None
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip().startswith('def '):
                        function_name = extract_function_name(lines[j])
                        break
                
                if function_name:
                    critical_apis.append({
                        'function_name': function_name,
                        'line_number': i + 1,
                        'decorator_params': decorator_info,
                        'implementation_status': 'IMPLEMENTED'
                    })
    
    except Exception as e:
        print(f"Error analyzing file {file_path}: {e}")
    
    return critical_apis

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

def find_unprotected_apis() -> Dict[str, List[Dict]]:
    """
    Find APIs with @frappe.whitelist() but without @critical_api
    
    Returns:
        Dictionary mapping files to unprotected API functions
    """
    
    unprotected_apis = {}
    
    api_directory = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if not os.path.exists(api_directory):
        return unprotected_apis
    
    for filename in os.listdir(api_directory):
        if filename.endswith('.py') and filename != '__init__.py':
            file_path = os.path.join(api_directory, filename)
            unprotected_functions = find_unprotected_functions_in_file(file_path)
            
            if unprotected_functions:
                relative_path = f"verenigingen/api/{filename}"
                unprotected_apis[relative_path] = unprotected_functions
    
    return unprotected_apis

def find_unprotected_functions_in_file(file_path: str) -> List[Dict]:
    """Find unprotected @frappe.whitelist() functions in a file"""
    
    unprotected_functions = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if '@frappe.whitelist()' in line:
                # Check if @critical_api is present in surrounding lines
                has_critical_api = False
                for j in range(max(0, i - 3), min(len(lines), i + 3)):
                    if '@critical_api' in lines[j]:
                        has_critical_api = True
                        break
                
                if not has_critical_api:
                    # Find the function definition
                    function_name = None
                    function_line = None
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j].strip().startswith('def '):
                            function_name = extract_function_name(lines[j])
                            function_line = j + 1
                            break
                    
                    if function_name:
                        unprotected_functions.append({
                            'function_name': function_name,
                            'line_number': function_line,
                            'whitelist_line': i + 1,
                            'protection_status': 'UNPROTECTED'
                        })
            
            i += 1
    
    except Exception as e:
        print(f"Error analyzing file {file_path}: {e}")
    
    return unprotected_functions

def analyze_security_patterns() -> Dict[str, any]:
    """Analyze existing security patterns in the codebase"""
    
    patterns = {
        'permission_checks': find_permission_check_patterns(),
        'role_validations': find_role_validation_patterns(),
        'data_isolation': find_data_isolation_patterns(),
        'input_validation': find_input_validation_patterns()
    }
    
    return patterns

def find_permission_check_patterns() -> List[Dict]:
    """Find existing permission check patterns"""
    
    permission_patterns = []
    
    # Common permission check patterns
    patterns_to_find = [
        r'frappe\.has_permission\(',
        r'frappe\.only_for\(',
        r'frappe\.permissions\.',
        r'check_permission\(',
        r'validate_permission\('
    ]
    
    api_directory = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if os.path.exists(api_directory):
        for filename in os.listdir(api_directory):
            if filename.endswith('.py'):
                file_path = os.path.join(api_directory, filename)
                patterns_in_file = find_patterns_in_file(file_path, patterns_to_find)
                
                if patterns_in_file:
                    permission_patterns.extend([{
                        'file': f"verenigingen/api/{filename}",
                        'pattern': pattern,
                        'count': count
                    } for pattern, count in patterns_in_file.items() if count > 0])
    
    return permission_patterns

def find_role_validation_patterns() -> List[Dict]:
    """Find existing role validation patterns"""
    
    role_patterns = []
    
    role_check_patterns = [
        r'frappe\.session\.user',
        r'frappe\.get_roles\(',
        r'has_role\(',
        r'check_role\(',
        r'validate_role\('
    ]
    
    api_directory = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if os.path.exists(api_directory):
        for filename in os.listdir(api_directory):
            if filename.endswith('.py'):
                file_path = os.path.join(api_directory, filename)
                patterns_in_file = find_patterns_in_file(file_path, role_check_patterns)
                
                if patterns_in_file:
                    role_patterns.extend([{
                        'file': f"verenigingen/api/{filename}",
                        'pattern': pattern,
                        'count': count
                    } for pattern, count in patterns_in_file.items() if count > 0])
    
    return role_patterns

def find_data_isolation_patterns() -> List[Dict]:
    """Find existing data isolation patterns"""
    
    isolation_patterns = []
    
    isolation_check_patterns = [
        r'filters\s*=.*user',
        r'filters\s*=.*session',
        r'user_specific',
        r'member_specific',
        r'chapter_specific'
    ]
    
    api_directory = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if os.path.exists(api_directory):
        for filename in os.listdir(api_directory):
            if filename.endswith('.py'):
                file_path = os.path.join(api_directory, filename)
                patterns_in_file = find_patterns_in_file(file_path, isolation_check_patterns)
                
                if patterns_in_file:
                    isolation_patterns.extend([{
                        'file': f"verenigingen/api/{filename}",
                        'pattern': pattern,
                        'count': count
                    } for pattern, count in patterns_in_file.items() if count > 0])
    
    return isolation_patterns

def find_input_validation_patterns() -> List[Dict]:
    """Find existing input validation patterns"""
    
    validation_patterns = []
    
    validation_check_patterns = [
        r'frappe\.validate\(',
        r'validate_\w+\(',
        r'frappe\.throw\(',
        r'if not.*throw',
        r'ValidationError'
    ]
    
    api_directory = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    if os.path.exists(api_directory):
        for filename in os.listdir(api_directory):
            if filename.endswith('.py'):
                file_path = os.path.join(api_directory, filename)
                patterns_in_file = find_patterns_in_file(file_path, validation_check_patterns)
                
                if patterns_in_file:
                    validation_patterns.extend([{
                        'file': f"verenigingen/api/{filename}",
                        'pattern': pattern,
                        'count': count
                    } for pattern, count in patterns_in_file.items() if count > 0])
    
    return validation_patterns

def find_patterns_in_file(file_path: str, patterns: List[str]) -> Dict[str, int]:
    """Find specified patterns in a file and count occurrences"""
    
    pattern_counts = {pattern: 0 for pattern in patterns}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            pattern_counts[pattern] = len(matches)
    
    except Exception as e:
        print(f"Error analyzing patterns in file {file_path}: {e}")
    
    return pattern_counts

def calculate_coverage_statistics(existing_usage: Dict, unprotected_apis: Dict) -> Dict[str, any]:
    """Calculate security coverage statistics"""
    
    total_protected = sum(len(apis) for apis in existing_usage.values())
    total_unprotected = sum(len(apis) for apis in unprotected_apis.values())
    total_apis = total_protected + total_unprotected
    
    coverage_percentage = (total_protected / total_apis * 100) if total_apis > 0 else 0
    
    statistics = {
        'total_apis': total_apis,
        'protected_apis': total_protected,
        'unprotected_apis': total_unprotected,
        'coverage_percentage': round(coverage_percentage, 2),
        'files_with_protection': len(existing_usage),
        'files_needing_protection': len(unprotected_apis)
    }
    
    return statistics

def generate_security_recommendations(analysis: Dict) -> List[Dict]:
    """Generate security recommendations based on analysis"""
    
    recommendations = []
    
    coverage_stats = analysis.get('coverage_statistics', {})
    coverage_percentage = coverage_stats.get('coverage_percentage', 0)
    
    # Coverage-based recommendations
    if coverage_percentage < 50:
        recommendations.append({
            'priority': 'CRITICAL',
            'category': 'Coverage',
            'recommendation': 'Less than 50% API coverage. Immediate security audit required.',
            'action': 'Implement @critical_api decorators for all high-risk APIs'
        })
    elif coverage_percentage < 80:
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Coverage',
            'recommendation': f'Current coverage at {coverage_percentage}%. Target 90%+ coverage.',
            'action': 'Prioritize financial and administrative API protection'
        })
    
    # Pattern-based recommendations
    security_patterns = analysis.get('security_patterns', {})
    
    permission_checks = len(security_patterns.get('permission_checks', []))
    if permission_checks < 5:
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Permissions',
            'recommendation': 'Limited permission checking patterns found.',
            'action': 'Implement comprehensive permission validation framework'
        })
    
    role_validations = len(security_patterns.get('role_validations', []))
    if role_validations < 10:
        recommendations.append({
            'priority': 'MEDIUM',
            'category': 'Role Validation',
            'recommendation': 'Insufficient role-based access control.',
            'action': 'Enhance role validation in sensitive operations'
        })
    
    data_isolation = len(security_patterns.get('data_isolation', []))
    if data_isolation < 5:
        recommendations.append({
            'priority': 'HIGH',
            'category': 'Data Isolation',
            'recommendation': 'Limited data isolation patterns detected.',
            'action': 'Implement user-specific and chapter-specific data filtering'
        })
    
    return recommendations

def extract_function_name(function_line: str) -> str:
    """Extract function name from a function definition line"""
    match = re.search(r'def\s+(\w+)', function_line)
    return match.group(1) if match else None

def generate_coverage_report(analysis: Dict) -> str:
    """Generate a formatted security coverage report"""
    
    report = []
    report.append("# Security Coverage Analysis Report")
    report.append(f"Generated: {frappe.utils.now()}")
    report.append("")
    
    # Statistics summary
    stats = analysis.get('coverage_statistics', {})
    report.append("## Coverage Statistics")
    report.append(f"- **Total APIs**: {stats.get('total_apis', 0)}")
    report.append(f"- **Protected APIs**: {stats.get('protected_apis', 0)}")
    report.append(f"- **Unprotected APIs**: {stats.get('unprotected_apis', 0)}")
    report.append(f"- **Coverage Percentage**: {stats.get('coverage_percentage', 0)}%")
    report.append("")
    
    # Existing protection
    existing_usage = analysis.get('existing_critical_api_usage', {})
    if existing_usage:
        report.append("## Existing @critical_api Implementation")
        for file_path, apis in existing_usage.items():
            report.append(f"### {file_path}")
            for api in apis:
                params = api.get('decorator_params', {})
                param_str = ', '.join([f"{k}={v}" for k, v in params.items()])
                report.append(f"- `{api['function_name']}` (Line {api['line_number']}) - {param_str}")
            report.append("")
    
    # Unprotected APIs
    unprotected = analysis.get('unprotected_apis', {})
    if unprotected:
        report.append("## Unprotected APIs Requiring Attention")
        for file_path, apis in unprotected.items():
            report.append(f"### {file_path}")
            for api in apis:
                report.append(f"- `{api['function_name']}` (Line {api['line_number']}) - **NEEDS PROTECTION**")
            report.append("")
    
    # Recommendations
    recommendations = analysis.get('recommendations', [])
    if recommendations:
        report.append("## Security Recommendations")
        for rec in recommendations:
            report.append(f"### {rec['priority']}: {rec['category']}")
            report.append(f"- **Issue**: {rec['recommendation']}")
            report.append(f"- **Action**: {rec['action']}")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution function"""
    
    print("🔒 Analyzing Security Coverage...")
    
    try:
        analysis = analyze_security_coverage()
        
        # Generate report
        report = generate_coverage_report(analysis)
        
        # Save report
        report_path = '/home/frappe/frappe-bench/apps/verenigingen/security_coverage_analysis.md'
        with open(report_path, 'w') as f:
            f.write(report)
        
        # Save JSON data
        json_path = '/home/frappe/frappe-bench/apps/verenigingen/security_coverage_analysis.json'
        with open(json_path, 'w') as f:
            json.dump(analysis, f, indent=2)
        
        print(f"✅ Security coverage analysis complete!")
        print(f"📄 Report saved to: {report_path}")
        print(f"📊 Data saved to: {json_path}")
        
        # Print summary
        stats = analysis.get('coverage_statistics', {})
        print(f"📈 Coverage: {stats.get('coverage_percentage', 0)}% ({stats.get('protected_apis', 0)}/{stats.get('total_apis', 0)} APIs)")
        
    except Exception as e:
        print(f"❌ Error during security coverage analysis: {e}")
        raise

if __name__ == '__main__':
    main()