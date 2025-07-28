#!/usr/bin/env python3
"""
High-Risk API Identification Script

This script analyzes the codebase to identify APIs that require security hardening,
focusing on financial operations, bulk operations, and sensitive data access.
"""

import os
import re
import ast
from typing import Dict, List, Any, Set
import frappe


def identify_high_risk_apis() -> Dict[str, Any]:
    """Identify all high-risk APIs in the codebase"""
    print("Identifying High-Risk APIs")
    print("=" * 60)
    
    results = {
        'timestamp': frappe.utils.now(),
        'analysis_summary': {},
        'high_risk_apis': [],
        'medium_risk_apis': [],
        'low_risk_apis': [],
        'recommendations': []
    }
    
    # Analyze API directory
    api_dir = 'verenigingen/api/'
    
    if not os.path.exists(api_dir):
        results['error'] = f'API directory not found: {api_dir}'
        return results
    
    analyzed_files = 0
    total_apis = 0
    
    for filename in os.listdir(api_dir):
        if filename.endswith('.py') and not filename.startswith('__'):
            file_path = os.path.join(api_dir, filename)
            analyzed_files += 1
            
            print(f"\nAnalyzing: {filename}")
            
            # Analyze file for API endpoints
            file_apis = analyze_api_file(file_path)
            total_apis += len(file_apis)
            
            # Categorize APIs by risk level
            for api in file_apis:
                risk_level = assess_risk_level(api)
                api['risk_level'] = risk_level
                
                if risk_level == 'HIGH' or risk_level == 'CRITICAL':
                    results['high_risk_apis'].append(api)
                elif risk_level == 'MEDIUM':
                    results['medium_risk_apis'].append(api)
                else:
                    results['low_risk_apis'].append(api)
                
                print(f"  - {api['function_name']}: {risk_level}")
    
    # Generate analysis summary
    results['analysis_summary'] = {
        'files_analyzed': analyzed_files,
        'total_apis': total_apis,
        'high_risk_count': len(results['high_risk_apis']),
        'medium_risk_count': len(results['medium_risk_apis']),
        'low_risk_count': len(results['low_risk_apis'])
    }
    
    # Generate recommendations
    results['recommendations'] = generate_security_recommendations(results)
    
    # Save results
    save_analysis_results(results)
    
    # Print summary
    print_analysis_summary(results)
    
    return results


def analyze_api_file(file_path: str) -> List[Dict[str, Any]]:
    """Analyze a single API file for endpoints and risk factors"""
    apis = []
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Parse the AST to find functions with @frappe.whitelist()
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check if function has @frappe.whitelist() decorator
                if has_whitelist_decorator(node):
                    api_info = extract_api_info(node, file_path, content)
                    apis.append(api_info)
    
    except Exception as e:
        print(f"    Error analyzing {file_path}: {e}")
    
    return apis


def has_whitelist_decorator(func_node: ast.FunctionDef) -> bool:
    """Check if function has @frappe.whitelist() decorator"""
    for decorator in func_node.decorator_list:
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Attribute):
                if (isinstance(decorator.func.value, ast.Name) and 
                    decorator.func.value.id == 'frappe' and 
                    decorator.func.attr == 'whitelist'):
                    return True
        elif isinstance(decorator, ast.Attribute):
            if (isinstance(decorator.value, ast.Name) and
                decorator.value.id == 'frappe' and
                decorator.attr == 'whitelist'):
                return True
    return False


def extract_api_info(func_node: ast.FunctionDef, file_path: str, content: str) -> Dict[str, Any]:
    """Extract detailed information about an API function"""
    
    # Get function source code
    lines = content.split('\n')
    func_start = func_node.lineno - 1
    func_end = func_node.end_lineno if hasattr(func_node, 'end_lineno') else func_start + 10
    
    func_source = '\n'.join(lines[func_start:func_end])
    
    # Extract docstring
    docstring = ast.get_docstring(func_node) or ''
    
    # Get function parameters
    params = [arg.arg for arg in func_node.args.args]
    
    api_info = {
        'file_path': file_path,
        'function_name': func_node.name,
        'line_number': func_node.lineno,
        'parameters': params,
        'docstring': docstring,
        'source_preview': func_source[:500] + '...' if len(func_source) > 500 else func_source,
        'risk_factors': identify_risk_factors(func_source, func_node.name, docstring),
        'existing_security': check_existing_security(func_source),
        'database_access': analyze_database_access(func_source),
        'file_operations': analyze_file_operations(func_source)
    }
    
    return api_info


def identify_risk_factors(source_code: str, func_name: str, docstring: str) -> List[str]:
    """Identify risk factors in the API function"""
    risk_factors = []
    
    # Check function name patterns
    high_risk_patterns = [
        'delete', 'remove', 'drop', 'truncate', 'destroy',
        'bulk_', 'batch_', 'mass_',
        'create_', 'update_', 'modify_',
        'payment', 'financial', 'money', 'invoice', 'billing',
        'sepa', 'mandate', 'debit', 'credit',
        'admin', 'system', 'config', 'setting'
    ]
    
    for pattern in high_risk_patterns:
        if pattern in func_name.lower():
            risk_factors.append(f'High-risk function name pattern: {pattern}')
    
    # Check source code patterns
    source_lower = source_code.lower()
    
    # Database modification patterns
    db_modify_patterns = [
        'frappe.db.sql.*insert',
        'frappe.db.sql.*update', 
        'frappe.db.sql.*delete',
        'frappe.db.delete',
        'doc.delete()',
        'frappe.delete_doc'
    ]
    
    for pattern in db_modify_patterns:
        if re.search(pattern, source_lower):
            risk_factors.append(f'Database modification detected: {pattern}')
    
    # Financial operations
    financial_keywords = [
        'payment', 'invoice', 'money', 'currency', 'amount',
        'sepa', 'mandate', 'debit', 'credit', 'bank', 'account'
    ]
    
    financial_found = [kw for kw in financial_keywords if kw in source_lower]
    if financial_found:
        risk_factors.append(f'Financial operations: {", ".join(financial_found)}')
    
    # Bulk operations
    bulk_keywords = ['bulk', 'batch', 'mass', 'all', 'multiple']
    bulk_found = [kw for kw in bulk_keywords if kw in source_lower]
    if bulk_found:
        risk_factors.append(f'Bulk operations: {", ".join(bulk_found)}')
    
    # User input handling
    if 'request.form' in source_code or 'frappe.form_dict' in source_code:
        risk_factors.append('Direct user input handling')
    
    # File operations
    file_patterns = ['open(', 'file.write', 'os.system', 'subprocess']
    file_found = [p for p in file_patterns if p in source_code]
    if file_found:
        risk_factors.append(f'File operations: {", ".join(file_found)}')
    
    # Check docstring for risk indicators
    if docstring:
        doc_lower = docstring.lower()
        if any(word in doc_lower for word in ['admin', 'system', 'dangerous', 'careful']):
            risk_factors.append('Documentation indicates high-risk operation')
    
    return risk_factors


def check_existing_security(source_code: str) -> Dict[str, bool]:
    """Check what security measures are already in place"""
    security_checks = {
        'has_critical_api_decorator': '@critical_api' in source_code,
        'has_permission_check': 'frappe.has_permission' in source_code or 'check_permission' in source_code,
        'has_user_validation': 'frappe.session.user' in source_code,
        'has_input_validation': any(pattern in source_code for pattern in ['validate_', 'frappe.throw', 'ValidationError']),
        'has_rate_limiting': '@rate_limit' in source_code or 'rate_limit' in source_code,
        'has_audit_logging': 'frappe.log_error' in source_code or 'audit' in source_code.lower(),
        'has_csrf_protection': 'csrf' in source_code.lower(),
        'has_error_handling': 'try:' in source_code and 'except:' in source_code
    }
    
    return security_checks


def analyze_database_access(source_code: str) -> Dict[str, Any]:
    """Analyze database access patterns"""
    patterns = {
        'read_operations': len(re.findall(r'frappe\.get_|frappe\.db\.get_|frappe\.db\.sql.*select', source_code, re.IGNORECASE)),
        'write_operations': len(re.findall(r'\.save\(\)|\.insert\(\)|frappe\.db\.sql.*(insert|update|delete)', source_code, re.IGNORECASE)),
        'bulk_operations': len(re.findall(r'get_all|sql.*limit\s+\d+', source_code, re.IGNORECASE)),
        'raw_sql_usage': len(re.findall(r'frappe\.db\.sql', source_code)),
        'uses_transactions': 'frappe.db.commit()' in source_code or 'frappe.db.rollback()' in source_code
    }
    
    return patterns


def analyze_file_operations(source_code: str) -> Dict[str, Any]:
    """Analyze file operation patterns"""
    patterns = {
        'file_reads': len(re.findall(r'open\(.*[\'"]r[\'"]', source_code)),
        'file_writes': len(re.findall(r'open\(.*[\'"]w[\'"]', source_code)),
        'file_uploads': 'frappe.get_doc("File"' in source_code or 'save_file' in source_code,
        'system_commands': 'os.system' in source_code or 'subprocess' in source_code,
        'temp_files': 'tempfile' in source_code or '/tmp/' in source_code
    }
    
    return patterns


def assess_risk_level(api_info: Dict[str, Any]) -> str:
    """Assess the risk level of an API based on various factors"""
    risk_score = 0
    
    # Risk factors contribute to score
    risk_factors = api_info.get('risk_factors', [])
    
    # High-impact risk factors
    high_impact_factors = [
        'financial operations', 'bulk operations', 'database modification',
        'file operations', 'system commands', 'admin functions'
    ]
    
    for factor in risk_factors:
        factor_lower = factor.lower()
        if any(high_impact in factor_lower for high_impact in high_impact_factors):
            risk_score += 3
        else:
            risk_score += 1
    
    # Database access patterns
    db_access = api_info.get('database_access', {})
    if db_access.get('write_operations', 0) > 0:
        risk_score += 2
    if db_access.get('raw_sql_usage', 0) > 0:
        risk_score += 1
    if db_access.get('bulk_operations', 0) > 2:
        risk_score += 2
    
    # File operations
    file_ops = api_info.get('file_operations', {})
    if file_ops.get('file_writes', 0) > 0:
        risk_score += 2
    if file_ops.get('system_commands', False):
        risk_score += 3
    
    # Existing security measures reduce risk
    security = api_info.get('existing_security', {})
    security_count = sum(1 for v in security.values() if v)
    risk_score -= security_count
    
    # Determine risk level
    if risk_score >= 8:
        return 'CRITICAL'
    elif risk_score >= 5:
        return 'HIGH'
    elif risk_score >= 2:
        return 'MEDIUM'
    else:
        return 'LOW'


def generate_security_recommendations(results: Dict[str, Any]) -> List[str]:
    """Generate security recommendations based on analysis"""
    recommendations = []
    
    high_risk_count = results['analysis_summary']['high_risk_count']
    total_apis = results['analysis_summary']['total_apis']
    
    if high_risk_count > 0:
        recommendations.append(f"Prioritize securing {high_risk_count} high-risk APIs immediately")
        recommendations.append("Implement @critical_api decorators for all financial operations")
        recommendations.append("Add comprehensive input validation and sanitization")
    
    # Check for common security gaps
    apis_without_security = []
    for api in results['high_risk_apis']:
        security = api.get('existing_security', {})
        if not security.get('has_critical_api_decorator', False):
            apis_without_security.append(api['function_name'])
    
    if apis_without_security:
        recommendations.append(f"Add security decorators to: {', '.join(apis_without_security[:5])}")
    
    # Rate limiting recommendations
    bulk_apis = [api for api in results['high_risk_apis'] if 'bulk' in str(api.get('risk_factors', [])).lower()]
    if bulk_apis:
        recommendations.append("Implement rate limiting for bulk operations")
    
    # Audit logging recommendations
    financial_apis = [api for api in results['high_risk_apis'] if 'financial' in str(api.get('risk_factors', [])).lower()]
    if financial_apis:
        recommendations.append("Enable comprehensive audit logging for financial operations")
    
    if not recommendations:
        recommendations.append("Security posture looks good, continue regular reviews")
    
    return recommendations


def save_analysis_results(results: Dict[str, Any]):
    """Save analysis results to file"""
    import json
    from datetime import datetime
    
    filename = f'high_risk_api_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nAnalysis results saved to: {filename}")


def print_analysis_summary(results: Dict[str, Any]):
    """Print analysis summary"""
    print("\n" + "=" * 60)
    print("HIGH-RISK API ANALYSIS SUMMARY")
    print("=" * 60)
    
    summary = results['analysis_summary']
    print(f"Files analyzed: {summary['files_analyzed']}")
    print(f"Total APIs found: {summary['total_apis']}")
    print(f"High/Critical risk: {summary['high_risk_count']}")
    print(f"Medium risk: {summary['medium_risk_count']}")
    print(f"Low risk: {summary['low_risk_count']}")
    
    print("\nTop High-Risk APIs:")
    for i, api in enumerate(results['high_risk_apis'][:10], 1):
        print(f"{i:2d}. {api['function_name']} ({api['file_path']})")
        print(f"     Risk Level: {api['risk_level']}")
        if api.get('risk_factors'):
            print(f"     Factors: {', '.join(api['risk_factors'][:2])}")
    
    print("\nRecommendations:")
    for i, rec in enumerate(results['recommendations'], 1):
        print(f"{i:2d}. {rec}")


if __name__ == "__main__":
    # Initialize frappe if needed
    if not frappe.db:
        import sys
        sys.path.insert(0, '/home/frappe/frappe-bench/sites')
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        results = identify_high_risk_apis()
        
        if results['analysis_summary']['high_risk_count'] > 10:
            print("\n⚠️  Many high-risk APIs found. Prioritize security implementation.")
        
    finally:
        if frappe.db:
            frappe.db.close()