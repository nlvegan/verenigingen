#!/usr/bin/env python3
"""
High-Risk API Migration Checklist for Phase 1 Security Implementation

This file contains the specific high-risk APIs that need security enhancements
with exact file paths, line numbers, and required decorators.
"""

from typing import Dict, List, Any

HIGH_RISK_APIS = {
    'verenigingen/api/sepa_mandate_management.py': {
        'file_path': 'verenigingen/api/sepa_mandate_management.py',
        'risk_level': 'CRITICAL',
        'status': 'SECURED',  # Already has @critical_api decorators
        'functions': [
            {
                'name': 'create_missing_sepa_mandates',
                'line': 17,
                'applied_decorator': '@critical_api(operation_type=OperationType.FINANCIAL)',
                'decorator_required': False,
                'decorator_status': 'already_secured',
                'risk_level': 'CRITICAL',
                'reason': 'Creates financial instruments - already secured',
                'validation_requirements': [
                    '✅ Has financial permissions check',
                    '✅ Has audit logging',
                    '✅ Has IBAN/BIC validation',
                    '✅ Has duplicate prevention'
                ]
            },
            {
                'name': 'fix_specific_member_sepa_mandate', 
                'line': 152,
                'applied_decorator': '@critical_api(operation_type=OperationType.FINANCIAL)',
                'decorator_required': False,
                'decorator_status': 'already_secured',
                'risk_level': 'HIGH',
                'reason': 'Individual mandate creation - already secured',
                'validation_requirements': [
                    '✅ Has critical API decorator',
                    '✅ Has error handling',
                    '✅ Has validation checks'
                ]
            }
        ]
    },
    'verenigingen/api/payment_processing.py': {
        'file_path': 'verenigingen/api/payment_processing.py',
        'risk_level': 'CRITICAL',
        'status': 'SECURED',  # Already has @critical_api decorators
        'functions': [
            {
                'name': 'send_overdue_payment_reminders',
                'line': 43,
                'applied_decorator': '@critical_api(operation_type=OperationType.FINANCIAL)',
                'decorator_required': False,
                'decorator_status': 'already_secured',
                'risk_level': 'CRITICAL',
                'reason': 'Financial communication operations - already secured',
                'validation_requirements': [
                    '✅ Has critical API decorator',
                    '✅ Has error handling',
                    '✅ Has performance monitoring',
                    '✅ Has input validation'
                ]
            }
        ]
    },
    'verenigingen/api/dd_batch_scheduler.py': {
        'file_path': 'verenigingen/api/dd_batch_scheduler.py',
        'risk_level': 'HIGH',
        'status': 'SECURED',  # Already has @critical_api decorators
        'functions': [
            {
                'name': 'toggle_auto_batch_creation',
                'line': 463,
                'applied_decorator': '@critical_api(operation_type=OperationType.ADMIN)',
                'decorator_required': False,
                'decorator_status': 'already_secured',
                'risk_level': 'HIGH',
                'reason': 'Administrative batch toggle operations - already secured',
                'validation_requirements': [
                    '✅ Has critical API decorator',
                    '✅ Has SEPA permission checks',
                    '✅ Has admin-level validation'
                ]
            },
            {
                'name': 'run_batch_creation_now',
                'line': 480,
                'applied_decorator': '@critical_api(operation_type=OperationType.FINANCIAL)',
                'decorator_required': False,
                'decorator_status': 'already_secured', 
                'risk_level': 'CRITICAL',
                'reason': 'Manual batch creation operations - already secured',
                'validation_requirements': [
                    '✅ Has critical API decorator',
                    '✅ Has SEPA permission checks',
                    '✅ Has financial operation validation'
                ]
            }
        ]
    },
    'verenigingen/api/member_management.py': {
        'file_path': 'verenigingen/api/member_management.py',
        'risk_level': 'HIGH',
        'status': 'SECURED',  # Already has @critical_api decorators
        'functions': [
            {
                'name': 'assign_member_to_chapter',
                'line': 33,
                'applied_decorator': '@critical_api(operation_type=OperationType.MEMBER_DATA)',
                'decorator_required': False,
                'decorator_status': 'already_secured',
                'risk_level': 'HIGH',
                'reason': 'Member data operations - already secured',
                'validation_requirements': [
                    '✅ Has critical API decorator',
                    '✅ Has comprehensive validation',
                    '✅ Has error handling',
                    '✅ Has performance monitoring'
                ]
            }
        ]
    }
}

def get_high_risk_api_list() -> List[Dict[str, Any]]:
    """Get flattened list of all high-risk API functions"""
    api_list = []
    for file_path, file_info in HIGH_RISK_APIS.items():
        for func in file_info['functions']:
            api_list.append({
                'file_path': file_path,
                'function_name': func['name'],
                'line_number': func['line'],
                'risk_level': func['risk_level'],
                'applied_decorator': func['applied_decorator'],
                'decorator_required': func['decorator_required'],
                'decorator_status': func['decorator_status'],
                'reason': func['reason']
            })
    return api_list

def get_apis_by_risk_level(risk_level: str) -> List[Dict[str, Any]]:
    """Get APIs filtered by risk level"""
    return [api for api in get_high_risk_api_list() if api['risk_level'] == risk_level]

def get_api_validation_requirements(file_path: str, function_name: str) -> List[str]:
    """Get validation requirements for a specific API function"""
    if file_path in HIGH_RISK_APIS:
        for func in HIGH_RISK_APIS[file_path]['functions']:
            if func['name'] == function_name:
                return func['validation_requirements']
    return []

if __name__ == "__main__":
    # Print summary when run directly
    print("High-Risk API Security Status Checklist")
    print("=" * 60)
    
    critical_apis = get_apis_by_risk_level('CRITICAL')
    high_apis = get_apis_by_risk_level('HIGH')
    
    # Count secured vs unsecured
    secured_files = [f for f, info in HIGH_RISK_APIS.items() if info.get('status') == 'SECURED']
    
    print(f"\n✅ SECURED APIs: {len(secured_files)} files")
    for file_path in secured_files:
        print(f"  - {file_path} - {HIGH_RISK_APIS[file_path]['status']}")
    
    print(f"\nCRITICAL Risk APIs: {len(critical_apis)}")
    for api in critical_apis:
        status = "✅ SECURED" if api.get('applied_decorator', '').startswith('@critical_api') else "⚠️ NEEDS SECURITY"
        print(f"  {status} - {api['file_path']}::{api['function_name']} (line {api['line_number']})")
    
    print(f"\nHIGH Risk APIs: {len(high_apis)}")
    for api in high_apis:
        status = "✅ SECURED" if api.get('applied_decorator', '').startswith('@critical_api') else "⚠️ NEEDS SECURITY"
        print(f"  {status} - {api['file_path']}::{api['function_name']} (line {api['line_number']})")
    
    print(f"\nSECURITY STATUS:")
    print(f"  ✅ Total secured APIs: {len([a for a in get_high_risk_api_list() if a.get('applied_decorator', '').startswith('@critical_api')])}")
    print(f"  ⚠️  APIs needing security: {len([a for a in get_high_risk_api_list() if not a.get('applied_decorator', '').startswith('@critical_api')])}")
    print(f"\n🎉 CONCLUSION: Most high-risk APIs are already secured with @critical_api decorators!")