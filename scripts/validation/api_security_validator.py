#!/usr/bin/env python3
"""
API Security Validation Script

This script validates that the security implementations for high-risk APIs
are working correctly and meet the required security standards.
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any

# Import from high-risk API checklist
import sys
sys.path.append('scripts/security')
from high_risk_api_checklist import HIGH_RISK_APIS, get_high_risk_api_list


def validate_api_security_implementation() -> Dict[str, Any]:
    """Validate specific API security implementations"""
    print("Validating API Security Implementation")
    print("=" * 60)
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'validation_summary': {},
        'api_validations': {},
        'security_compliance': {},
        'recommendations': []
    }
    
    # Test each high-risk API
    api_list = get_high_risk_api_list()
    
    for api_info in api_list:
        print(f"\nValidating: {api_info['function_name']}")
        
        validation_result = test_api_security(api_info)
        results['api_validations'][f"{api_info['file_path']}::{api_info['function_name']}"] = validation_result
        
        # Print immediate feedback
        if validation_result['overall_pass']:
            print(f"  ✅ PASSED - Security validation successful")
        else:
            print(f"  ❌ FAILED - {len(validation_result['failed_checks'])} checks failed")
            for failed_check in validation_result['failed_checks']:
                print(f"    - {failed_check}")
    
    # Generate summary
    results['validation_summary'] = generate_validation_summary(results)
    results['security_compliance'] = assess_security_compliance(results)
    results['recommendations'] = generate_security_recommendations(results)
    
    # Save results
    save_validation_results(results)
    
    # Print final report
    print_validation_report(results)
    
    return results


def test_api_security(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Test security implementation for specific API function"""
    test_results = {
        'api_info': api_info,
        'checks': {},
        'overall_pass': True,
        'failed_checks': [],
        'warnings': []
    }
    
    # Security checks to perform
    security_checks = {
        'decorator_applied': check_decorator_applied,
        'security_imports': check_security_imports,
        'permission_validation': check_permission_validation,
        'input_validation': check_input_validation,
        'error_handling': check_error_handling,
        'audit_logging': check_audit_logging
    }
    
    for check_name, check_function in security_checks.items():
        try:
            check_result = check_function(api_info)
            
            # Process warnings at API level and remove from check result to avoid duplication
            if check_result.get('warning'):
                test_results['warnings'].append(f"{check_name}: {check_result['warning']}")
                # Remove warning from individual check result to avoid duplication
                del check_result['warning']
            
            test_results['checks'][check_name] = check_result
            
            if not check_result['passed']:
                test_results['overall_pass'] = False
                test_results['failed_checks'].append(f"{check_name}: {check_result['message']}")
                
        except Exception as e:
            test_results['checks'][check_name] = {
                'passed': False,
                'message': f'Check failed with error: {str(e)}',
                'error': str(e)
            }
            test_results['overall_pass'] = False
            test_results['failed_checks'].append(f"{check_name}: Check failed with error")
    
    return test_results


def check_decorator_applied(api_info: Dict[str, Any]) -> Dict[str, bool]:
    """Check if @critical_api decorator is applied"""
    file_path = api_info['file_path']
    function_name = api_info['function_name']
    
    try:
        if not os.path.exists(file_path):
            return {
                'passed': False,
                'message': f'API file not found: {file_path}'
            }
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for the function and its decorators
        lines = content.split('\n')
        function_found = False
        has_critical_api = False
        
        for i, line in enumerate(lines):
            if f'def {function_name}(' in line:
                function_found = True
                # Check previous lines for decorators
                for j in range(max(0, i-5), i):
                    if '@critical_api' in lines[j]:
                        has_critical_api = True
                        break
                break
        
        if not function_found:
            return {
                'passed': False,
                'message': f'Function {function_name} not found in {file_path}'
            }
        
        if has_critical_api:
            return {
                'passed': True,
                'message': '@critical_api decorator is properly applied'
            }
        else:
            return {
                'passed': False,
                'message': '@critical_api decorator is missing'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking decorator: {str(e)}'
        }


def check_security_imports(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if security framework imports are present"""
    file_path = api_info['file_path']
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        required_imports = [
            'api_security_framework',
            'critical_api',
            'OperationType'
        ]
        
        missing_imports = []
        for imp in required_imports:
            if imp not in content:
                missing_imports.append(imp)
        
        if missing_imports:
            return {
                'passed': False,
                'message': f'Missing imports: {", ".join(missing_imports)}'
            }
        else:
            return {
                'passed': True,
                'message': 'All required security imports are present'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking imports: {str(e)}'
        }


def check_permission_validation(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if proper permission validation is implemented"""
    file_path = api_info['file_path']
    function_name = api_info['function_name']
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for permission checking patterns
        permission_patterns = [
            'frappe.has_permission',
            'check_permission',
            'require_sepa_permission',
            'frappe.throw.*permission',
            'PermissionError'
        ]
        
        function_start = content.find(f'def {function_name}(')
        if function_start == -1:
            return {
                'passed': False,
                'message': f'Function {function_name} not found'
            }
        
        # Get function content (rough estimate)
        function_end = content.find('\ndef ', function_start + 1)
        if function_end == -1:
            function_end = len(content)
        
        function_content = content[function_start:function_end]
        
        permission_checks_found = []
        for pattern in permission_patterns:
            if pattern in function_content:
                permission_checks_found.append(pattern)
        
        if permission_checks_found:
            return {
                'passed': True,
                'message': f'Permission validation found: {", ".join(permission_checks_found)}'
            }
        else:
            return {
                'passed': False,
                'message': 'No explicit permission validation found',
                'warning': 'Permission validation may be handled by @critical_api decorator'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking permissions: {str(e)}'
        }


def check_input_validation(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if input validation is implemented"""
    file_path = api_info['file_path']
    function_name = api_info['function_name']
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for validation patterns
        validation_patterns = [
            'validate_',
            'frappe.throw',
            'ValidationError',
            'validate_with_schema',
            'validate_required_fields'
        ]
        
        function_start = content.find(f'def {function_name}(')
        if function_start == -1:
            return {
                'passed': False,
                'message': f'Function {function_name} not found'
            }
        
        function_end = content.find('\ndef ', function_start + 1)
        if function_end == -1:
            function_end = len(content)
        
        function_content = content[function_start:function_end]
        
        validation_found = []
        for pattern in validation_patterns:
            if pattern in function_content:
                validation_found.append(pattern)
        
        if validation_found:
            return {
                'passed': True,
                'message': f'Input validation found: {", ".join(validation_found)}'
            }
        else:
            return {
                'passed': False,
                'message': 'No explicit input validation found',
                'warning': 'Basic validation may be handled by Frappe framework'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking input validation: {str(e)}'
        }


def check_error_handling(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if proper error handling is implemented"""
    file_path = api_info['file_path']
    function_name = api_info['function_name']
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        function_start = content.find(f'def {function_name}(')
        if function_start == -1:
            return {
                'passed': False,
                'message': f'Function {function_name} not found'
            }
        
        function_end = content.find('\ndef ', function_start + 1)
        if function_end == -1:
            function_end = len(content)
        
        function_content = content[function_start:function_end]
        
        # Check for error handling patterns
        has_try_except = 'try:' in function_content and 'except' in function_content
        has_error_logging = 'frappe.log_error' in function_content or 'log_error' in function_content
        has_handle_api_error = '@handle_api_error' in content[:function_start + 200]
        
        error_handling_score = 0
        features = []
        
        if has_try_except:
            error_handling_score += 1
            features.append('try/except blocks')
        
        if has_error_logging:
            error_handling_score += 1
            features.append('error logging')
        
        if has_handle_api_error:
            error_handling_score += 1
            features.append('@handle_api_error decorator')
        
        if error_handling_score >= 2:
            return {
                'passed': True,
                'message': f'Good error handling: {", ".join(features)}'
            }
        elif error_handling_score == 1:
            return {
                'passed': True,
                'message': f'Basic error handling: {", ".join(features)}',
                'warning': 'Consider adding more comprehensive error handling'
            }
        else:
            return {
                'passed': False,
                'message': 'No explicit error handling found'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking error handling: {str(e)}'
        }


def check_audit_logging(api_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if audit logging is implemented"""
    file_path = api_info['file_path']
    function_name = api_info['function_name']
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for audit logging patterns
        audit_patterns = [
            'frappe.log_error',
            'audit_logger',
            'get_audit_logger',
            'AuditEventType',
            'log_security_event'
        ]
        
        function_start = content.find(f'def {function_name}(')
        if function_start == -1:
            return {
                'passed': False,
                'message': f'Function {function_name} not found'
            }
        
        # Check entire file for audit imports and function for usage
        audit_found = []
        for pattern in audit_patterns:
            if pattern in content:
                audit_found.append(pattern)
        
        if audit_found:
            return {
                'passed': True,
                'message': f'Audit logging available: {", ".join(audit_found)}'
            }
        else:
            return {
                'passed': False,
                'message': 'No audit logging found',
                'warning': 'Audit logging may be handled by security framework'
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Error checking audit logging: {str(e)}'
        }


def generate_validation_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate validation summary statistics"""
    total_apis = len(results['api_validations'])
    passed_apis = len([v for v in results['api_validations'].values() if v['overall_pass']])
    failed_apis = total_apis - passed_apis
    
    # Count check types
    check_stats = {}
    for api_result in results['api_validations'].values():
        for check_name, check_result in api_result['checks'].items():
            if check_name not in check_stats:
                check_stats[check_name] = {'passed': 0, 'failed': 0}
            
            if check_result['passed']:
                check_stats[check_name]['passed'] += 1
            else:
                check_stats[check_name]['failed'] += 1
    
    return {
        'total_apis_tested': total_apis,
        'apis_passed': passed_apis,
        'apis_failed': failed_apis,
        'pass_rate': (passed_apis / total_apis * 100) if total_apis > 0 else 0,
        'check_statistics': check_stats
    }


def assess_security_compliance(results: Dict[str, Any]) -> Dict[str, Any]:
    """Assess overall security compliance"""
    summary = results['validation_summary']
    
    # Count critical API failures specifically
    critical_api_failures = 0
    for api_result in results['api_validations'].values():
        if not api_result['overall_pass'] and api_result['api_info']['risk_level'] == 'CRITICAL':
            critical_api_failures += 1
    
    # Determine compliance level based on pass rate
    compliance_level = 'UNKNOWN'
    if summary['pass_rate'] >= 90:
        compliance_level = 'EXCELLENT'
    elif summary['pass_rate'] >= 75:
        compliance_level = 'GOOD'
    elif summary['pass_rate'] >= 50:
        compliance_level = 'ACCEPTABLE'
    else:
        compliance_level = 'POOR'
    
    # Downgrade compliance if there are critical API failures
    if critical_api_failures > 0:
        if compliance_level in ['EXCELLENT', 'GOOD']:
            compliance_level = 'ACCEPTABLE'
        elif compliance_level == 'ACCEPTABLE':
            compliance_level = 'POOR'
    
    # Gate readiness: fail if ANY of these conditions are true:
    # 1. Pass rate < 75%
    # 2. Any critical API failures
    # 3. Any API failures at all (apis_failed > 0)
    ready_for_production = (
        summary['pass_rate'] >= 75 and 
        critical_api_failures == 0 and 
        summary['apis_failed'] == 0
    )
    
    return {
        'compliance_level': compliance_level,
        'ready_for_production': ready_for_production,
        'critical_api_failures': critical_api_failures,
        'total_api_failures': summary['apis_failed'],
        'total_warnings': sum(len(v.get('warnings', [])) for v in results['api_validations'].values())
    }


def generate_security_recommendations(results: Dict[str, Any]) -> List[str]:
    """Generate security recommendations based on validation results"""
    recommendations = []
    
    compliance = results['security_compliance']
    summary = results['validation_summary']
    
    # Priority recommendations for critical issues
    if compliance.get('critical_api_failures', 0) > 0:
        recommendations.append(f"🚨 CRITICAL: {compliance['critical_api_failures']} critical-risk APIs failed validation - immediate action required!")
    
    if compliance['compliance_level'] == 'EXCELLENT':
        recommendations.append("✅ Security compliance is excellent. Continue regular security reviews.")
    elif compliance['compliance_level'] == 'GOOD':
        recommendations.append("🟡 Good security compliance. Address remaining issues for optimal security.")
    else:
        recommendations.append("🔴 Security compliance needs improvement. Address failed validations immediately.")
    
    # Specific recommendations based on failed checks
    check_stats = summary.get('check_statistics', {})
    
    for check_name, stats in check_stats.items():
        if stats['failed'] > 0:
            if check_name == 'decorator_applied':
                recommendations.append(f"Add @critical_api decorators to {stats['failed']} APIs")
            elif check_name == 'permission_validation':
                recommendations.append(f"Implement explicit permission checks in {stats['failed']} APIs")
            elif check_name == 'input_validation':
                recommendations.append(f"Add input validation to {stats['failed']} APIs")
            elif check_name == 'error_handling':
                recommendations.append(f"Improve error handling in {stats['failed']} APIs")
            elif check_name == 'audit_logging':
                recommendations.append(f"Add audit logging to {stats['failed']} APIs")
    
    if compliance['total_warnings'] > 0:
        recommendations.append(f"Review {compliance['total_warnings']} warnings for potential improvements")
    
    return recommendations


def save_validation_results(results: Dict[str, Any]):
    """Save validation results to file"""
    filename = f'api_security_validation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nValidation results saved to: {filename}")


def print_validation_report(results: Dict[str, Any]):
    """Print comprehensive validation report"""
    print("\n" + "=" * 60)
    print("API SECURITY VALIDATION REPORT")
    print("=" * 60)
    
    summary = results['validation_summary']
    compliance = results['security_compliance']
    
    print(f"Validation Time: {results['timestamp']}")
    print(f"APIs Tested: {summary['total_apis_tested']}")
    print(f"Pass Rate: {summary['pass_rate']:.1f}%")
    print(f"Compliance Level: {compliance['compliance_level']}")
    print(f"Production Ready: {'YES' if compliance['ready_for_production'] else 'NO'}")
    
    print(f"\nResults Summary:")
    print(f"  ✅ APIs Passed: {summary['apis_passed']}")
    print(f"  ❌ APIs Failed: {summary['apis_failed']}")
    print(f"  ⚠️  Total Warnings: {compliance['total_warnings']}")
    
    print(f"\nCheck Statistics:")
    for check_name, stats in summary.get('check_statistics', {}).items():
        total = stats['passed'] + stats['failed']
        pass_rate = (stats['passed'] / total * 100) if total > 0 else 0
        print(f"  {check_name}: {stats['passed']}/{total} ({pass_rate:.1f}%)")
    
    print(f"\nRecommendations:")
    for i, rec in enumerate(results['recommendations'], 1):
        print(f"  {i}. {rec}")


if __name__ == "__main__":
    import os
    
    try:
        results = validate_api_security_implementation()
        
        if not results['security_compliance']['ready_for_production']:
            print("\n⚠️  Security validation indicates system is not production-ready.")
            print("Please address the failed validations before proceeding.")
            exit(1)
        else:
            print("\n✅ Security validation passed! System is production-ready.")
            
    except Exception as e:
        print(f"\n❌ Security validation failed with error: {e}")
        exit(1)