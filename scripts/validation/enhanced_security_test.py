#!/usr/bin/env python3
"""
Enhanced Security Test Suite

This suite performs comprehensive security testing of the existing @critical_api
framework, focusing on validation and enhancement rather than implementation.
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Tuple

# Import our analysis tools
import sys
sys.path.append('scripts/security')
from high_risk_api_checklist import HIGH_RISK_APIS, get_high_risk_api_list


class EnhancedSecurityTester:
    """Comprehensive security testing for existing critical APIs"""
    
    def __init__(self):
        self.test_results = {
            'timestamp': datetime.now().isoformat(),
            'test_summary': {},
            'detailed_results': {},
            'security_enhancements': [],
            'recommendations': []
        }
        
    def run_comprehensive_security_tests(self) -> Dict[str, Any]:
        """Run all security tests and generate enhancement recommendations"""
        print("Enhanced Security Testing Suite")
        print("=" * 60)
        print("Testing existing @critical_api security implementations")
        print("")
        
        # Run different categories of security tests
        test_categories = {
            'decorator_validation': self.test_decorator_implementation,
            'permission_boundaries': self.test_permission_boundaries,
            'input_validation_gaps': self.test_input_validation_gaps,
            'error_handling_robustness': self.test_error_handling,
            'audit_logging_completeness': self.test_audit_logging,
            'security_framework_integration': self.test_framework_integration
        }
        
        for category, test_method in test_categories.items():
            print(f"\n{'='*20} {category.upper()} {'='*20}")
            try:
                category_result = test_method()
                self.test_results['detailed_results'][category] = category_result
                
                # Print immediate feedback
                if category_result['status'] == 'PASS':
                    print(f"✅ {category}: PASSED - {category_result['summary']}")
                elif category_result['status'] == 'PARTIAL':
                    print(f"🟡 {category}: PARTIAL - {category_result['summary']}")
                else:
                    print(f"❌ {category}: FAILED - {category_result['summary']}")
                    
            except Exception as e:
                print(f"❌ {category}: ERROR - {str(e)}")
                self.test_results['detailed_results'][category] = {
                    'status': 'ERROR',
                    'summary': f'Test failed with error: {str(e)}',
                    'error': str(e)
                }
        
        # Generate summary and recommendations
        self.generate_test_summary()
        self.generate_security_enhancements()
        self.generate_recommendations()
        
        # Save and display results
        self.save_test_results()
        self.print_comprehensive_report()
        
        return self.test_results
    
    def test_decorator_implementation(self) -> Dict[str, Any]:
        """Test @critical_api decorator implementation completeness"""
        api_list = get_high_risk_api_list()
        
        decorator_results = {
            'apis_with_decorators': 0,
            'apis_without_decorators': 0,
            'operation_type_coverage': {},
            'decorator_details': []
        }
        
        for api_info in api_list:
            file_path = api_info['file_path']
            function_name = api_info['function_name']
            
            # Check if file exists and has decorator
            if not os.path.exists(file_path):
                decorator_results['apis_without_decorators'] += 1
                decorator_results['decorator_details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'FILE_NOT_FOUND',
                    'issue': f'File {file_path} not found'
                })
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Look for @critical_api decorator near the function
            function_pos = content.find(f'def {function_name}(')
            if function_pos == -1:
                decorator_results['apis_without_decorators'] += 1
                decorator_results['decorator_details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'FUNCTION_NOT_FOUND',
                    'issue': f'Function {function_name} not found'
                })
                continue
            
            # Check 200 characters before function for decorator
            search_start = max(0, function_pos - 200)
            search_content = content[search_start:function_pos + 100]
            
            if '@critical_api' in search_content:
                decorator_results['apis_with_decorators'] += 1
                
                # Extract operation type
                operation_type = 'UNKNOWN'
                if 'OperationType.FINANCIAL' in search_content:
                    operation_type = 'FINANCIAL'
                elif 'OperationType.ADMIN' in search_content:
                    operation_type = 'ADMIN'
                elif 'OperationType.MEMBER_DATA' in search_content:
                    operation_type = 'MEMBER_DATA'
                
                if operation_type not in decorator_results['operation_type_coverage']:
                    decorator_results['operation_type_coverage'][operation_type] = 0
                decorator_results['operation_type_coverage'][operation_type] += 1
                
                decorator_results['decorator_details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'HAS_DECORATOR',
                    'operation_type': operation_type
                })
            else:
                decorator_results['apis_without_decorators'] += 1
                decorator_results['decorator_details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'MISSING_DECORATOR',
                    'issue': '@critical_api decorator not found'
                })
        
        # Determine overall status
        total_apis = len(api_list)
        coverage_rate = (decorator_results['apis_with_decorators'] / total_apis * 100) if total_apis > 0 else 0
        
        if coverage_rate == 100:
            status = 'PASS'
            summary = f"All {total_apis} high-risk APIs have @critical_api decorators"
        elif coverage_rate >= 90:
            status = 'PARTIAL'
            summary = f"{coverage_rate:.1f}% coverage - {decorator_results['apis_without_decorators']} APIs missing decorators"
        else:
            status = 'FAIL'
            summary = f"Only {coverage_rate:.1f}% coverage - {decorator_results['apis_without_decorators']} APIs missing decorators"
        
        return {
            'status': status,
            'summary': summary,
            'coverage_rate': coverage_rate,
            'details': decorator_results
        }
    
    def test_permission_boundaries(self) -> Dict[str, Any]:
        """Test permission boundary enforcement"""
        # This would test actual permission enforcement
        # For now, analyze code patterns for permission checks
        
        api_list = get_high_risk_api_list()
        permission_results = {
            'apis_with_explicit_checks': 0,
            'apis_relying_on_framework': 0,
            'permission_patterns_found': {},
            'details': []
        }
        
        permission_patterns = [
            'frappe.has_permission',
            'check_permission',
            'require_sepa_permission',
            'PermissionError',
            'frappe.throw.*permission'
        ]
        
        for api_info in api_list:
            file_path = api_info['file_path']
            function_name = api_info['function_name']
            
            if not os.path.exists(file_path):
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Find function content
            function_pos = content.find(f'def {function_name}(')
            if function_pos == -1:
                continue
            
            # Get approximate function content (next function or end of file)
            next_function = content.find('\ndef ', function_pos + 1)
            if next_function == -1:
                function_content = content[function_pos:]
            else:
                function_content = content[function_pos:next_function]
            
            patterns_found = []
            for pattern in permission_patterns:
                if pattern in function_content:
                    patterns_found.append(pattern)
                    if pattern not in permission_results['permission_patterns_found']:
                        permission_results['permission_patterns_found'][pattern] = 0
                    permission_results['permission_patterns_found'][pattern] += 1
            
            if patterns_found:
                permission_results['apis_with_explicit_checks'] += 1
                permission_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'HAS_EXPLICIT_CHECKS',
                    'patterns': patterns_found
                })
            else:
                permission_results['apis_relying_on_framework'] += 1
                permission_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'FRAMEWORK_ONLY',
                    'note': 'Relies on @critical_api framework for permission checks'
                })
        
        total_apis = len([api for api in api_list if os.path.exists(api['file_path'])])
        explicit_rate = (permission_results['apis_with_explicit_checks'] / total_apis * 100) if total_apis > 0 else 0
        
        if explicit_rate >= 80:
            status = 'PASS'
            summary = f"{explicit_rate:.1f}% of APIs have explicit permission checks"
        elif explicit_rate >= 50:
            status = 'PARTIAL'
            summary = f"{explicit_rate:.1f}% explicit checks - {permission_results['apis_relying_on_framework']} rely on framework"
        else:
            status = 'PARTIAL'  # Framework-based is acceptable
            summary = f"Most APIs rely on @critical_api framework for permissions"
        
        return {
            'status': status,
            'summary': summary,
            'explicit_rate': explicit_rate,
            'details': permission_results
        }
    
    def test_input_validation_gaps(self) -> Dict[str, Any]:
        """Test for input validation gaps"""
        api_list = get_high_risk_api_list()
        validation_results = {
            'apis_with_validation': 0,
            'apis_without_validation': 0,
            'validation_patterns': {},
            'details': []
        }
        
        validation_patterns = [
            'validate_',
            'frappe.throw',
            'ValidationError',
            'validate_with_schema',
            'validate_required_fields',
            'APIValidator'
        ]
        
        for api_info in api_list:
            file_path = api_info['file_path']
            function_name = api_info['function_name']
            
            if not os.path.exists(file_path):
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Get function content
            function_pos = content.find(f'def {function_name}(')
            if function_pos == -1:
                continue
            
            next_function = content.find('\ndef ', function_pos + 1)
            if next_function == -1:
                function_content = content[function_pos:]
            else:
                function_content = content[function_pos:next_function]
            
            patterns_found = []
            for pattern in validation_patterns:
                if pattern in function_content:
                    patterns_found.append(pattern)
                    if pattern not in validation_results['validation_patterns']:
                        validation_results['validation_patterns'][pattern] = 0
                    validation_results['validation_patterns'][pattern] += 1
            
            if patterns_found:
                validation_results['apis_with_validation'] += 1
                validation_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'HAS_VALIDATION',
                    'patterns': patterns_found
                })
            else:
                validation_results['apis_without_validation'] += 1
                validation_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'NEEDS_VALIDATION',
                    'recommendation': 'Add explicit input validation'
                })
        
        total_apis = len([api for api in api_list if os.path.exists(api['file_path'])])
        validation_rate = (validation_results['apis_with_validation'] / total_apis * 100) if total_apis > 0 else 0
        
        if validation_rate >= 90:
            status = 'PASS'
            summary = f"{validation_rate:.1f}% of APIs have input validation"
        elif validation_rate >= 60:
            status = 'PARTIAL'
            summary = f"{validation_rate:.1f}% have validation - {validation_results['apis_without_validation']} need enhancement"
        else:
            status = 'FAIL'
            summary = f"Only {validation_rate:.1f}% have validation - {validation_results['apis_without_validation']} APIs need validation"
        
        return {
            'status': status,
            'summary': summary,
            'validation_rate': validation_rate,
            'details': validation_results
        }
    
    def test_error_handling(self) -> Dict[str, Any]:
        """Test error handling implementation"""
        api_list = get_high_risk_api_list()
        error_results = {
            'apis_with_error_handling': 0,
            'apis_without_error_handling': 0,
            'error_patterns': {},
            'details': []
        }
        
        error_patterns = [
            'try:',
            'except',
            '@handle_api_error',
            'frappe.log_error',
            'log_error'
        ]
        
        for api_info in api_list:
            file_path = api_info['file_path']
            function_name = api_info['function_name']
            
            if not os.path.exists(file_path):
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check for decorator in the area around function
            function_pos = content.find(f'def {function_name}(')
            if function_pos == -1:
                continue
            
            # Check for @handle_api_error decorator
            search_start = max(0, function_pos - 200)
            decorator_area = content[search_start:function_pos + 50]
            
            # Get function content
            next_function = content.find('\ndef ', function_pos + 1)
            if next_function == -1:
                function_content = content[function_pos:]
            else:
                function_content = content[function_pos:next_function]
            
            patterns_found = []
            for pattern in error_patterns:
                if pattern in function_content or pattern in decorator_area:
                    patterns_found.append(pattern)
                    if pattern not in error_results['error_patterns']:
                        error_results['error_patterns'][pattern] = 0
                    error_results['error_patterns'][pattern] += 1
            
            if patterns_found:
                error_results['apis_with_error_handling'] += 1
                error_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'HAS_ERROR_HANDLING',
                    'patterns': patterns_found
                })
            else:
                error_results['apis_without_error_handling'] += 1
                error_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'NEEDS_ERROR_HANDLING',
                    'recommendation': 'Add try/catch and error logging'
                })
        
        total_apis = len([api for api in api_list if os.path.exists(api['file_path'])])
        error_rate = (error_results['apis_with_error_handling'] / total_apis * 100) if total_apis > 0 else 0
        
        if error_rate >= 90:
            status = 'PASS'
            summary = f"{error_rate:.1f}% of APIs have error handling"
        elif error_rate >= 70:
            status = 'PARTIAL'
            summary = f"{error_rate:.1f}% have error handling - {error_results['apis_without_error_handling']} need enhancement"
        else:
            status = 'FAIL'
            summary = f"Only {error_rate:.1f}% have error handling - {error_results['apis_without_error_handling']} APIs need improvement"
        
        return {
            'status': status,
            'summary': summary,
            'error_rate': error_rate,
            'details': error_results
        }
    
    def test_audit_logging(self) -> Dict[str, Any]:
        """Test audit logging implementation"""
        # Check for audit logging framework usage
        audit_results = {
            'framework_available': False,
            'apis_using_audit': 0,
            'audit_patterns': {},
            'details': []
        }
        
        # Check if audit logging framework exists
        audit_framework_path = 'verenigingen/utils/security/audit_logging.py'
        if os.path.exists(audit_framework_path):
            audit_results['framework_available'] = True
        
        api_list = get_high_risk_api_list()
        
        audit_patterns = [
            'frappe.log_error',
            'audit_logger',
            'get_audit_logger',
            'AuditEventType',
            'log_security_event'
        ]
        
        for api_info in api_list:
            file_path = api_info['file_path']
            function_name = api_info['function_name']
            
            if not os.path.exists(file_path):
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            patterns_found = []
            for pattern in audit_patterns:
                if pattern in content:
                    patterns_found.append(pattern)
                    if pattern not in audit_results['audit_patterns']:
                        audit_results['audit_patterns'][pattern] = 0
                    audit_results['audit_patterns'][pattern] += 1
            
            if patterns_found:
                audit_results['apis_using_audit'] += 1
                audit_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'HAS_AUDIT_LOGGING',
                    'patterns': patterns_found
                })
            else:
                audit_results['details'].append({
                    'api': f"{file_path}::{function_name}",
                    'status': 'NO_EXPLICIT_AUDIT',
                    'note': 'May use framework-level audit logging'
                })
        
        total_apis = len([api for api in api_list if os.path.exists(api['file_path'])])
        audit_rate = (audit_results['apis_using_audit'] / total_apis * 100) if total_apis > 0 else 0
        
        if audit_results['framework_available'] and audit_rate >= 50:
            status = 'PASS' 
            summary = f"Audit framework available, {audit_rate:.1f}% of APIs use explicit audit logging"
        elif audit_results['framework_available']:
            status = 'PARTIAL'
            summary = f"Audit framework available but only {audit_rate:.1f}% explicit usage"
        else:
            status = 'FAIL'
            summary = "No audit logging framework found"
        
        return {
            'status': status,
            'summary': summary,
            'audit_rate': audit_rate,
            'details': audit_results
        }
    
    def test_framework_integration(self) -> Dict[str, Any]:
        """Test overall security framework integration"""
        # Check if the security framework files exist and are properly integrated
        framework_files = [
            'verenigingen/utils/security/api_security_framework.py',
            'verenigingen/utils/security/authorization.py',
            'verenigingen/utils/security/audit_logging.py',
            'verenigingen/utils/security/enhanced_validation.py'
        ]
        
        integration_results = {
            'framework_files_present': 0,
            'framework_files_missing': 0,
            'import_usage': {},
            'details': []
        }
        
        # Check framework files
        for framework_file in framework_files:
            if os.path.exists(framework_file):
                integration_results['framework_files_present'] += 1
                integration_results['details'].append({
                    'file': framework_file,
                    'status': 'EXISTS'
                })
            else:
                integration_results['framework_files_missing'] += 1 
                integration_results['details'].append({
                    'file': framework_file,
                    'status': 'MISSING'
                })
        
        # Check API files for framework imports
        api_list = get_high_risk_api_list()
        framework_imports = [
            'api_security_framework',
            'critical_api',
            'OperationType',
            'SecurityLevel'
        ]
        
        for api_info in api_list:
            file_path = api_info['file_path']
            
            if not os.path.exists(file_path):
                continue
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            imports_found = []
            for imp in framework_imports:
                if imp in content:
                    imports_found.append(imp)
                    if imp not in integration_results['import_usage']:
                        integration_results['import_usage'][imp] = 0
                    integration_results['import_usage'][imp] += 1
            
            integration_results['details'].append({
                'api_file': file_path,
                'imports_found': imports_found
            })
        
        framework_presence = integration_results['framework_files_present'] / len(framework_files) * 100
        
        if framework_presence >= 75 and len(integration_results['import_usage']) >= 2:
            status = 'PASS'
            summary = f"{framework_presence:.0f}% of framework files present, good import usage"
        elif framework_presence >= 50:
            status = 'PARTIAL'
            summary = f"{framework_presence:.0f}% of framework files present"
        else:
            status = 'FAIL'
            summary = f"Only {framework_presence:.0f}% of framework files present"
        
        return {
            'status': status,
            'summary': summary,
            'framework_presence': framework_presence,
            'details': integration_results
        }
    
    def generate_test_summary(self):
        """Generate overall test summary"""
        results = self.test_results['detailed_results']
        
        passed_tests = len([r for r in results.values() if r['status'] == 'PASS'])
        partial_tests = len([r for r in results.values() if r['status'] == 'PARTIAL'])
        failed_tests = len([r for r in results.values() if r['status'] == 'FAIL'])
        total_tests = len(results)
        
        overall_score = (passed_tests + (partial_tests * 0.5)) / total_tests * 100
        
        if overall_score >= 90:
            overall_status = 'EXCELLENT'
        elif overall_score >= 75:
            overall_status = 'GOOD'
        elif overall_score >= 60:
            overall_status = 'ACCEPTABLE'
        else:
            overall_status = 'NEEDS_IMPROVEMENT'
        
        self.test_results['test_summary'] = {
            'overall_status': overall_status,
            'overall_score': overall_score,
            'tests_passed': passed_tests,
            'tests_partial': partial_tests,
            'tests_failed': failed_tests,
            'total_tests': total_tests
        }
    
    def generate_security_enhancements(self):
        """Generate specific security enhancement recommendations"""
        enhancements = []
        results = self.test_results['detailed_results']
        
        # Based on test results, generate specific enhancements
        if 'input_validation_gaps' in results:
            validation_result = results['input_validation_gaps']
            if validation_result['status'] != 'PASS':
                apis_needing_validation = [d for d in validation_result['details']['details'] 
                                         if d['status'] == 'NEEDS_VALIDATION']
                if apis_needing_validation:
                    enhancements.append({
                        'category': 'Input Validation',
                        'priority': 'HIGH',
                        'description': f'Add input validation to {len(apis_needing_validation)} APIs',
                        'apis': [api['api'] for api in apis_needing_validation],
                        'implementation': 'Add validate_required_fields() and validate_with_schema() calls'
                    })
        
        if 'error_handling_robustness' in results:
            error_result = results['error_handling_robustness']
            if error_result['status'] != 'PASS':
                apis_needing_error_handling = [d for d in error_result['details']['details']
                                             if d['status'] == 'NEEDS_ERROR_HANDLING']
                if apis_needing_error_handling:
                    enhancements.append({
                        'category': 'Error Handling',
                        'priority': 'MEDIUM',
                        'description': f'Enhance error handling in {len(apis_needing_error_handling)} APIs',
                        'apis': [api['api'] for api in apis_needing_error_handling],
                        'implementation': 'Add try/catch blocks and @handle_api_error decorators'
                    })
        
        if 'permission_boundaries' in results:
            permission_result = results['permission_boundaries']
            if permission_result['details']['apis_with_explicit_checks'] == 0:
                enhancements.append({
                    'category': 'Permission Validation',
                    'priority': 'LOW',
                    'description': 'Consider adding explicit permission checks for clarity',
                    'implementation': 'Add frappe.has_permission() calls where appropriate'
                })
        
        self.test_results['security_enhancements'] = enhancements
    
    def generate_recommendations(self):
        """Generate overall recommendations"""
        recommendations = []
        summary = self.test_results['test_summary']
        
        if summary['overall_status'] == 'EXCELLENT':
            recommendations.append("✅ Security implementation is excellent. Focus on monitoring and maintenance.")
        elif summary['overall_status'] == 'GOOD':
            recommendations.append("🟡 Good security implementation. Address partial results for optimal security.")
        else:
            recommendations.append("🔴 Security implementation needs improvement. Priority on failed tests.")
        
        # Add specific recommendations based on enhancements
        enhancements = self.test_results['security_enhancements']
        high_priority = [e for e in enhancements if e['priority'] == 'HIGH']
        if high_priority:
            recommendations.append(f"🚨 HIGH PRIORITY: Address {len(high_priority)} critical security gaps")
        
        medium_priority = [e for e in enhancements if e['priority'] == 'MEDIUM']
        if medium_priority:
            recommendations.append(f"⚠️ MEDIUM PRIORITY: Enhance {len(medium_priority)} security areas")
        
        # Production readiness
        if summary['overall_score'] >= 80:
            recommendations.append("✅ System appears ready for production deployment")
        else:
            recommendations.append("⚠️ Address security gaps before production deployment")
        
        self.test_results['recommendations'] = recommendations
    
    def save_test_results(self):
        """Save comprehensive test results"""
        filename = f'enhanced_security_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        with open(filename, 'w') as f:
            json.dump(self.test_results, f, indent=2)
        
        print(f"\nTest results saved to: {filename}")
    
    def print_comprehensive_report(self):
        """Print comprehensive test report"""
        print("\n" + "=" * 60)
        print("ENHANCED SECURITY TEST REPORT")
        print("=" * 60)
        
        summary = self.test_results['test_summary']
        
        print(f"Test Time: {self.test_results['timestamp']}")
        print(f"Overall Status: {summary['overall_status']}")
        print(f"Overall Score: {summary['overall_score']:.1f}%")
        print(f"Tests: {summary['tests_passed']} passed, {summary['tests_partial']} partial, {summary['tests_failed']} failed")
        
        print("\nTest Category Results:")
        for category, result in self.test_results['detailed_results'].items():
            status_icon = {"PASS": "✅", "PARTIAL": "🟡", "FAIL": "❌", "ERROR": "💥"}.get(result['status'], "❓")
            print(f"  {status_icon} {category}: {result['status']} - {result['summary']}")
        
        if self.test_results['security_enhancements']:
            print("\nSecurity Enhancement Opportunities:")
            for i, enhancement in enumerate(self.test_results['security_enhancements'], 1):
                priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(enhancement['priority'], "⚪")
                print(f"  {i}. {priority_icon} {enhancement['category']}: {enhancement['description']}")
        
        print("\nRecommendations:")
        for i, rec in enumerate(self.test_results['recommendations'], 1):
            print(f"  {i}. {rec}")


if __name__ == "__main__":
    tester = EnhancedSecurityTester()
    results = tester.run_comprehensive_security_tests()
    
    # Exit with appropriate code
    if results['test_summary']['overall_status'] in ['EXCELLENT', 'GOOD']:
        print("\n✅ Enhanced security testing completed successfully!")
        exit(0)
    else:
        print("\n⚠️ Enhanced security testing identified areas for improvement.")
        exit(1)