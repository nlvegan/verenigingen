#!/usr/bin/env python3
"""
Pre-Phase 1 Validator

This script validates that all prerequisites are met before starting Phase 1
security implementation. It checks for existing security framework, required
permissions, and monitoring setup.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
import frappe


@dataclass
class ValidationIssue:
    """Represents a validation issue"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: str
    issue_type: str
    suggested_fix: str


class PrePhase1Validator:
    """Pre-Phase 1 security prerequisites validator"""
    
    def __init__(self):
        self.app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
        self.doctypes = self._load_available_doctypes()
    
    def _load_available_doctypes(self) -> Dict[str, Any]:
        """Load available DocTypes for first-layer validation"""
        doctypes = {}
        doctype_dir = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        
        if not doctype_dir.exists():
            return doctypes
        
        for doctype_path in doctype_dir.iterdir():
            if doctype_path.is_dir():
                json_file = doctype_path / f"{doctype_path.name}.json"
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        doctypes[data.get('name', '')] = data
                    except Exception:
                        pass
        
        return doctypes
    
    def validate_doctype_api_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """FIRST-LAYER CHECK: Validate DocType existence in API calls"""
        violations = []
        
        # Patterns for Frappe API calls that use DocType names
        api_patterns = [
            r'frappe\.get_all\(\s*["\']([^"\']+)["\']',
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.delete_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.get_value\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.exists\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.count\(\s*["\']([^"\']+)["\']',
            r'DocType\(\s*["\']([^"\']+)["\']',
        ]
        
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, 1):
            for pattern in api_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    doctype_name = match.group(1)
                    
                    # FIRST-LAYER CHECK: Does this DocType actually exist?
                    if doctype_name not in self.doctypes:
                        # Suggest similar DocType names
                        suggestions = self._suggest_similar_doctype(doctype_name)
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field="<doctype_reference>",
                            doctype=doctype_name,
                            reference=line.strip(),
                            message=f"DocType '{doctype_name}' does not exist. {suggestions}",
                            context=line.strip(),
                            confidence="high",
                            issue_type="missing_doctype",
                            suggested_fix=suggestions
                        ))
        
        return violations
    
    def _suggest_similar_doctype(self, invalid_name: str) -> str:
        """Suggest similar DocType names for typos"""
        available = list(self.doctypes.keys())
        
        # Look for exact substring matches first
        exact_matches = [dt for dt in available if invalid_name.replace('Verenigingen ', '') in dt]
        if exact_matches:
            return f"Did you mean '{exact_matches[0]}'?"
        
        # Look for partial matches
        partial_matches = [dt for dt in available if any(word in dt for word in invalid_name.split())]
        if partial_matches:
            return f"Similar: {', '.join(partial_matches[:3])}"
        
        return f"Check {len(available)} available DocTypes"


def validate_security_prerequisites() -> Dict[str, Any]:
    """Validate security framework is ready for Phase 1"""
    print("Pre-Phase 1 Security Validation")
    print("=" * 60)
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'checks': {},
        'ready_for_phase1': True,
        'missing_requirements': [],
        'warnings': []
    }
    
    # Run all checks
    checks = {
        'critical_api_decorator_exists': check_critical_api_decorator(),
        'security_framework_imported': check_security_imports(),
        'test_users_exist': check_test_users(),
        'monitoring_active': check_monitoring_setup(),
        'high_risk_apis_identified': check_high_risk_apis(),
        'rollback_procedures_ready': check_rollback_procedures(),
        'performance_baselines_exist': check_performance_baselines(),
        'git_repository_clean': check_git_status()
    }
    
    results['checks'] = checks
    
    # Determine if ready for Phase 1
    for check_name, check_result in checks.items():
        if not check_result['passed']:
            results['ready_for_phase1'] = False
            results['missing_requirements'].append({
                'check': check_name,
                'reason': check_result['message']
            })
        
        if check_result.get('warning'):
            results['warnings'].append({
                'check': check_name,
                'warning': check_result['warning']
            })
    
    # Generate report
    generate_prerequisite_report(results)
    
    return results


def check_critical_api_decorator() -> Dict[str, Any]:
    """Verify @critical_api decorator is available"""
    print("\nChecking @critical_api decorator availability...")
    
    try:
        from verenigingen.utils.security.api_security_framework import critical_api, OperationType
        
        # Check if decorator is actually functional
        @critical_api(operation_type=OperationType.FINANCIAL)
        def test_function():
            return True
        
        return {
            'passed': True,
            'message': '@critical_api decorator is available and functional',
            'details': {
                'module': 'verenigingen.utils.security.api_security_framework',
                'decorator_found': True,
                'operation_types_available': True
            }
        }
    except ImportError as e:
        return {
            'passed': False,
            'message': f'Security framework not found: {str(e)}',
            'details': {
                'error': str(e),
                'module_missing': True
            }
        }
    except Exception as e:
        return {
            'passed': False,
            'message': f'Security framework error: {str(e)}',
            'details': {
                'error': str(e),
                'decorator_error': True
            }
        }


def check_security_imports() -> Dict[str, Any]:
    """Check existing security import patterns"""
    print("Checking existing security implementations...")
    
    try:
        # Count existing @critical_api usage
        api_dir = 'verenigingen/api/'
        files_with_security = []
        files_without_security = []
        
        for filename in os.listdir(api_dir):
            if filename.endswith('.py') and not filename.startswith('__'):
                file_path = os.path.join(api_dir, filename)
                
                with open(file_path, 'r') as f:
                    content = f.read()
                
                if '@critical_api' in content:
                    files_with_security.append(filename)
                elif '@frappe.whitelist()' in content:
                    files_without_security.append(filename)
        
        return {
            'passed': True,
            'message': f'Found {len(files_with_security)} files with security, {len(files_without_security)} without',
            'details': {
                'files_with_security': len(files_with_security),
                'files_without_security': len(files_without_security),
                'total_api_files': len(files_with_security) + len(files_without_security)
            },
            'warning': f'{len(files_without_security)} API files still need security implementation' if files_without_security else None
        }
        
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to check security imports: {str(e)}',
            'details': {'error': str(e)}
        }


def check_test_users() -> Dict[str, Any]:
    """Check if test users exist for security testing"""
    print("Checking test user setup...")
    
    try:
        required_test_users = [
            {'email': 'test_admin@example.com', 'roles': ['System Manager']},
            {'email': 'test_member@example.com', 'roles': ['Member']},
            {'email': 'test_guest@example.com', 'roles': []}
        ]
        
        missing_users = []
        existing_users = []
        
        for test_user in required_test_users:
            if not frappe.db.exists('User', test_user['email']):
                missing_users.append(test_user['email'])
            else:
                existing_users.append(test_user['email'])
        
        if missing_users:
            return {
                'passed': False,
                'message': f'Missing test users: {", ".join(missing_users)}',
                'details': {
                    'required_users': len(required_test_users),
                    'existing_users': len(existing_users),
                    'missing_users': missing_users
                }
            }
        else:
            return {
                'passed': True,
                'message': 'All test users exist',
                'details': {
                    'test_users': existing_users
                }
            }
            
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to check test users: {str(e)}',
            'details': {'error': str(e)}
        }


def check_monitoring_setup() -> Dict[str, Any]:
    """Check if monitoring is active"""
    print("Checking monitoring setup...")
    
    try:
        # Check if monitoring scripts exist
        monitoring_scripts = [
            'scripts/monitoring/automated_rollback.py',
            'scripts/monitoring/monitor_api_health.py'
        ]
        
        missing_scripts = []
        for script in monitoring_scripts:
            if not os.path.exists(script):
                missing_scripts.append(script)
        
        # Check if error logging is enabled
        error_log_count = frappe.db.count('Error Log', filters={'creation': ['>', 'NOW() - INTERVAL 1 DAY']})
        
        passed = len(missing_scripts) == 0
        
        return {
            'passed': passed,
            'message': 'Monitoring infrastructure ready' if passed else f'Missing monitoring scripts: {missing_scripts}',
            'details': {
                'error_logging_active': error_log_count > 0,
                'recent_error_logs': error_log_count,
                'missing_scripts': missing_scripts
            },
            'warning': 'No recent error logs found' if error_log_count == 0 else None
        }
        
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to check monitoring: {str(e)}',
            'details': {'error': str(e)}
        }


def check_high_risk_apis() -> Dict[str, Any]:
    """Check if high-risk APIs have been identified"""
    print("Checking high-risk API identification...")
    
    try:
        # Import the high-risk API checklist
        from scripts.security.high_risk_api_checklist import get_high_risk_api_list
        
        api_list = get_high_risk_api_list()
        
        if not api_list:
            return {
                'passed': False,
                'message': 'No high-risk APIs identified',
                'details': {'api_count': 0}
            }
        
        # Verify the APIs actually exist
        missing_apis = []
        for api in api_list:
            if not os.path.exists(api['file_path']):
                missing_apis.append(api['file_path'])
        
        if missing_apis:
            return {
                'passed': False,
                'message': f'Some high-risk API files not found: {missing_apis}',
                'details': {
                    'total_apis': len(api_list),
                    'missing_files': missing_apis
                }
            }
        
        return {
            'passed': True,
            'message': f'Identified {len(api_list)} high-risk APIs',
            'details': {
                'api_count': len(api_list),
                'critical_count': len([a for a in api_list if a['risk_level'] == 'CRITICAL']),
                'high_count': len([a for a in api_list if a['risk_level'] == 'HIGH'])
            }
        }
        
    except ImportError:
        return {
            'passed': False,
            'message': 'High-risk API checklist not found',
            'details': {'error': 'Cannot import high_risk_api_checklist'}
        }
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to check high-risk APIs: {str(e)}',
            'details': {'error': str(e)}
        }


def check_rollback_procedures() -> Dict[str, Any]:
    """Check if rollback procedures are ready"""
    print("Checking rollback procedures...")
    
    try:
        rollback_script = 'scripts/rollback/rollback_manager.py'
        
        if not os.path.exists(rollback_script):
            return {
                'passed': False,
                'message': 'Rollback manager script not found',
                'details': {'script_path': rollback_script}
            }
        
        # Try to import and instantiate
        from scripts.rollback.rollback_manager import RollbackManager
        
        rollback = RollbackManager('phase1')
        steps = rollback.rollback_steps
        
        return {
            'passed': True,
            'message': f'Rollback procedures ready with {len(steps)} steps',
            'details': {
                'rollback_steps': len(steps),
                'script_found': True
            }
        }
        
    except Exception as e:
        return {
            'passed': False,
            'message': f'Rollback procedures not ready: {str(e)}',
            'details': {'error': str(e)}
        }


def check_performance_baselines() -> Dict[str, Any]:
    """Check if performance baselines exist"""
    print("Checking performance baselines...")
    
    baseline_file = 'performance_baselines.json'
    
    if not os.path.exists(baseline_file):
        return {
            'passed': False,
            'message': 'Performance baselines not established',
            'details': {
                'baseline_file': baseline_file,
                'exists': False
            }
        }
    
    try:
        with open(baseline_file, 'r') as f:
            baselines = json.load(f)
        
        # Check if baselines are recent (within 7 days)
        from datetime import datetime, timedelta
        baseline_date = datetime.fromisoformat(baselines['timestamp'])
        age_days = (datetime.now() - baseline_date).days
        
        if age_days > 7:
            return {
                'passed': True,
                'message': f'Performance baselines exist but are {age_days} days old',
                'details': {
                    'baseline_date': baselines['timestamp'],
                    'age_days': age_days,
                    'measurements': list(baselines.get('measurements', {}).keys())
                },
                'warning': 'Consider re-establishing baselines for accurate comparison'
            }
        
        return {
            'passed': True,
            'message': 'Performance baselines are current',
            'details': {
                'baseline_date': baselines['timestamp'],
                'age_days': age_days,
                'measurements': list(baselines.get('measurements', {}).keys())
            }
        }
        
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to read performance baselines: {str(e)}',
            'details': {'error': str(e)}
        }


def check_git_status() -> Dict[str, Any]:
    """Check if git repository is clean"""
    print("Checking git repository status...")
    
    try:
        import subprocess
        
        # Check for uncommitted changes
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            return {
                'passed': False,
                'message': 'Failed to check git status',
                'details': {'error': result.stderr}
            }
        
        uncommitted_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        uncommitted_count = len([f for f in uncommitted_files if f])
        
        if uncommitted_count > 0:
            return {
                'passed': True,
                'message': f'{uncommitted_count} uncommitted files found',
                'details': {
                    'uncommitted_count': uncommitted_count,
                    'files': uncommitted_files[:10]  # Show first 10
                },
                'warning': 'Consider committing changes before starting implementation'
            }
        
        return {
            'passed': True,
            'message': 'Git repository is clean',
            'details': {
                'uncommitted_count': 0
            }
        }
        
    except Exception as e:
        return {
            'passed': False,
            'message': f'Failed to check git status: {str(e)}',
            'details': {'error': str(e)}
        }


def get_high_risk_apis() -> List[Tuple[str, str]]:
    """Return specific high-risk API functions to migrate"""
    return [
        ('verenigingen/api/sepa_mandate_management.py', 'create_missing_sepa_mandates'),
        ('verenigingen/api/sepa_mandate_management.py', 'bulk_create_mandates'),
        ('verenigingen/api/payment_processing.py', 'process_payment_batch'),
        ('verenigingen/api/member_management.py', 'bulk_update_members'),
        ('verenigingen/api/dd_batch_creation.py', 'create_direct_debit_batch')
    ]


def generate_prerequisite_report(results: Dict[str, Any]):
    """Generate a human-readable prerequisite report"""
    report = []
    report.append("\nPre-Phase 1 Validation Report")
    report.append("=" * 60)
    report.append(f"Validation Time: {results['timestamp']}")
    report.append(f"Ready for Phase 1: {'YES' if results['ready_for_phase1'] else 'NO'}")
    report.append("")
    
    # Check results
    report.append("Prerequisite Checks:")
    report.append("-" * 60)
    
    for check_name, check_result in results['checks'].items():
        status = "✅ PASS" if check_result['passed'] else "❌ FAIL"
        report.append(f"{status} | {check_name.replace('_', ' ').title()}")
        report.append(f"     {check_result['message']}")
        
        if check_result.get('warning'):
            report.append(f"     ⚠️  {check_result['warning']}")
        
        report.append("")
    
    # Missing requirements
    if results['missing_requirements']:
        report.append("Missing Requirements:")
        report.append("-" * 60)
        for req in results['missing_requirements']:
            report.append(f"  - {req['check']}: {req['reason']}")
        report.append("")
    
    # Warnings
    if results['warnings']:
        report.append("Warnings:")
        report.append("-" * 60)
        for warning in results['warnings']:
            report.append(f"  - {warning['check']}: {warning['warning']}")
        report.append("")
    
    # Next steps
    report.append("Next Steps:")
    report.append("-" * 60)
    if results['ready_for_phase1']:
        report.append("  ✅ All prerequisites met. Ready to start Phase 1 implementation.")
        report.append("  1. Create a git commit to mark the starting point")
        report.append("  2. Run performance baselines if older than 7 days")
        report.append("  3. Begin with CRITICAL risk APIs first")
    else:
        report.append("  ❌ Prerequisites not met. Please address the following:")
        for req in results['missing_requirements']:
            report.append(f"     - Fix: {req['reason']}")
    
    report_text = "\n".join(report)
    print(report_text)
    
    # Save report
    with open('pre_phase1_validation_report.txt', 'w') as f:
        f.write(report_text)
    
    # Save JSON results
    with open('pre_phase1_validation_results.json', 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    # Initialize frappe if needed
    if not frappe.db:
        import sys
        sys.path.insert(0, '/home/frappe/frappe-bench/sites')
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        results = validate_security_prerequisites()
        
        if not results['ready_for_phase1']:
            print("\n⚠️  System is not ready for Phase 1 implementation.")
            print("Please address the missing requirements listed above.")
            sys.exit(1)
        else:
            print("\n✅ System is ready for Phase 1 implementation!")
            
    finally:
        if frappe.db:
            frappe.db.close()