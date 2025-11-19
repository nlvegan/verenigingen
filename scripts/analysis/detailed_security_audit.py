#!/usr/bin/env python3
"""
Detailed Security Coverage Audit

This script provides a granular analysis of security coverage claims,
examining each financial API and its protection status.
"""

import os
import re
from typing import Dict, List, Tuple


def detailed_security_audit():
    """Perform detailed security coverage audit"""
    
    print("🔒 Detailed Security Coverage Audit")
    print("=" * 60)
    
    api_dir = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api'
    
    # Define financial/critical API patterns
    high_risk_patterns = [
        'payment', 'sepa', 'invoice', 'financial', 'donor', 'batch', 
        'mandate', 'reconciliation', 'processing', 'termination'
    ]
    
    # Analyze each API file
    api_analysis = analyze_api_files(api_dir, high_risk_patterns)
    
    # Generate detailed report
    generate_detailed_security_report(api_analysis)
    
    return api_analysis


def analyze_api_files(api_dir: str, risk_patterns: List[str]) -> Dict:
    """Analyze each API file for security coverage"""
    
    analysis = {
        'total_files': 0,
        'high_risk_files': [],
        'medium_risk_files': [],
        'low_risk_files': [],
        'protected_files': [],
        'unprotected_files': [],
        'security_details': {}
    }
    
    if not os.path.exists(api_dir):
        return analysis
    
    api_files = [f for f in os.listdir(api_dir) if f.endswith('.py') and f != '__init__.py']
    analysis['total_files'] = len(api_files)
    
    for filename in api_files:
        file_path = os.path.join(api_dir, filename)
        
        # Determine risk level
        risk_level = determine_risk_level(filename, risk_patterns)
        
        # Analyze security implementation
        security_status = analyze_file_security(file_path)
        
        # Categorize file
        file_info = {
            'filename': filename,
            'risk_level': risk_level,
            'security_status': security_status,
            'path': file_path
        }
        
        analysis['security_details'][filename] = file_info
        
        # Add to appropriate category
        if risk_level == 'HIGH':
            analysis['high_risk_files'].append(file_info)
        elif risk_level == 'MEDIUM':
            analysis['medium_risk_files'].append(file_info)
        else:
            analysis['low_risk_files'].append(file_info)
        
        # Track protection status - use broader security framework detection
        if security_status['has_security_decorator'] or security_status['has_other_protection']:
            analysis['protected_files'].append(file_info)
        else:
            analysis['unprotected_files'].append(file_info)
    
    return analysis


def determine_risk_level(filename: str, risk_patterns: List[str]) -> str:
    """Determine the security risk level of an API file"""
    
    filename_lower = filename.lower()
    
    # High risk indicators
    high_risk_indicators = [
        'payment', 'sepa', 'invoice', 'financial', 'termination',
        'mandate', 'batch', 'processing'
    ]
    
    # Medium risk indicators
    medium_risk_indicators = [
        'member', 'donor', 'reconciliation', 'suspension',
        'customer', 'management', 'dashboard'
    ]
    
    if any(indicator in filename_lower for indicator in high_risk_indicators):
        return 'HIGH'
    elif any(indicator in filename_lower for indicator in medium_risk_indicators):
        return 'MEDIUM'
    else:
        return 'LOW'


def analyze_file_security(file_path: str) -> Dict:
    """Analyze security implementation in a specific file"""
    
    security_status = {
        'has_critical_api': False,
        'critical_api_count': 0,
        'has_whitelist': False,
        'whitelist_count': 0,
        'has_permission_checks': False,
        'has_role_checks': False,
        'has_other_protection': False,
        'unprotected_whitelisted_functions': [],
        'protected_functions': [],
        'security_patterns': []
    }
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        security_status['error'] = str(e)
        return security_status
    
    # Count all security framework decorators
    security_decorators = [
        '@critical_api', '@standard_api', '@high_security_api',
        '@development_only_api', '@public_api'
    ]
    security_status['security_decorator_count'] = sum(content.count(decorator) for decorator in security_decorators)
    security_status['has_security_decorator'] = security_status['security_decorator_count'] > 0

    # For backward compatibility, also track critical_api specifically
    security_status['critical_api_count'] = content.count('@critical_api')
    security_status['has_critical_api'] = security_status['critical_api_count'] > 0
    
    # Count @frappe.whitelist() decorators
    security_status['whitelist_count'] = content.count('@frappe.whitelist()')
    security_status['has_whitelist'] = security_status['whitelist_count'] > 0
    
    # Check for permission patterns
    permission_patterns = [
        r'frappe\.has_permission\(',
        r'frappe\.only_for\(',
        r'check_permission\(',
        r'validate_permission\('
    ]
    
    for pattern in permission_patterns:
        if re.search(pattern, content):
            security_status['has_permission_checks'] = True
            security_status['security_patterns'].append(pattern)
    
    # Check for role validation patterns
    role_patterns = [
        r'frappe\.get_roles\(',
        r'has_role\(',
        r'check_role\(',
        r'validate_role\('
    ]
    
    for pattern in role_patterns:
        if re.search(pattern, content):
            security_status['has_role_checks'] = True
            security_status['security_patterns'].append(pattern)
    
    # Check for other protection mechanisms
    if security_status['has_permission_checks'] or security_status['has_role_checks'] or security_status['has_security_decorator']:
        security_status['has_other_protection'] = True
    
    # Find unprotected whitelisted functions
    analyze_function_protection(lines, security_status)
    
    return security_status


def analyze_function_protection(lines: List[str], security_status: Dict):
    """Analyze individual function protection status"""
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if '@frappe.whitelist()' in line:
            # Check if this function has any security framework protection
            has_security_protection = False
            function_name = None

            # Look for any security decorator in surrounding lines
            security_decorators = ['@critical_api', '@standard_api', '@high_security_api', '@development_only_api', '@public_api']
            for j in range(max(0, i - 3), min(len(lines), i + 3)):
                if any(decorator in lines[j] for decorator in security_decorators):
                    has_security_protection = True
                    break
            
            # Find the function name
            for j in range(i + 1, min(i + 5, len(lines))):
                func_match = re.search(r'def\s+(\w+)', lines[j])
                if func_match:
                    function_name = func_match.group(1)
                    break
            
            if function_name:
                if has_security_protection:
                    security_status['protected_functions'].append(function_name)
                else:
                    security_status['unprotected_whitelisted_functions'].append(function_name)
        
        i += 1


def generate_detailed_security_report(analysis: Dict):
    """Generate detailed security audit report"""
    
    report = []
    report.append("# Detailed Security Coverage Audit Report")
    report.append("=" * 60)
    report.append("")
    
    # Summary statistics
    total_files = analysis['total_files']
    high_risk_count = len(analysis['high_risk_files'])
    protected_count = len(analysis['protected_files'])
    unprotected_count = len(analysis['unprotected_files'])
    
    report.append("## Executive Summary")
    report.append(f"- **Total API Files**: {total_files}")
    report.append(f"- **High Risk Files**: {high_risk_count}")
    report.append(f"- **Protected Files**: {protected_count}")
    report.append(f"- **Unprotected Files**: {unprotected_count}")
    
    if high_risk_count > 0:
        high_risk_protection_rate = sum(1 for f in analysis['high_risk_files']
                                      if f['security_status']['has_security_decorator'] or f['security_status']['has_other_protection'])
        high_risk_percentage = (high_risk_protection_rate / high_risk_count) * 100
        report.append(f"- **High Risk Protection Rate**: {high_risk_protection_rate}/{high_risk_count} ({high_risk_percentage:.1f}%)")
    
    report.append("")
    
    # High Risk Files Analysis
    report.append("## High Risk Files Analysis")
    report.append("These files handle critical financial/administrative operations:")
    report.append("")
    
    for file_info in analysis['high_risk_files']:
        filename = file_info['filename']
        security = file_info['security_status']
        
        status_emoji = "🔒" if (security['has_security_decorator'] or security['has_other_protection']) else "⚠️"
        report.append(f"### {status_emoji} {filename}")

        report.append(f"- **Security decorators**: {security['security_decorator_count']}")
        report.append(f"- **@critical_api decorators**: {security['critical_api_count']}")
        report.append(f"- **@frappe.whitelist() functions**: {security['whitelist_count']}")
        report.append(f"- **Permission checks**: {'Yes' if security['has_permission_checks'] else 'No'}")
        report.append(f"- **Role validation**: {'Yes' if security['has_role_checks'] else 'No'}")
        
        if security['protected_functions']:
            report.append(f"- **Protected functions**: {', '.join(security['protected_functions'])}")
        
        if security['unprotected_whitelisted_functions']:
            report.append(f"- **⚠️ UNPROTECTED functions**: {', '.join(security['unprotected_whitelisted_functions'])}")
        
        report.append("")
    
    # Critical Security Gaps
    report.append("## Critical Security Gaps")
    
    critical_gaps = []
    for file_info in analysis['high_risk_files']:
        if not file_info['security_status']['has_security_decorator'] and not file_info['security_status']['has_other_protection']:
            critical_gaps.append(file_info)
    
    if critical_gaps:
        report.append("The following high-risk files lack adequate protection:")
        report.append("")
        for gap in critical_gaps:
            report.append(f"- **{gap['filename']}**: {gap['security_status']['whitelist_count']} unprotected whitelist functions")
    else:
        report.append("✅ No critical security gaps identified in high-risk files.")
    
    report.append("")
    
    # Medium Risk Files
    report.append("## Medium Risk Files Summary")
    medium_protected = sum(1 for f in analysis['medium_risk_files']
                         if f['security_status']['has_security_decorator'] or f['security_status']['has_other_protection'])
    medium_total = len(analysis['medium_risk_files'])
    
    if medium_total > 0:
        medium_percentage = (medium_protected / medium_total) * 100
        report.append(f"- **Protected**: {medium_protected}/{medium_total} ({medium_percentage:.1f}%)")
    
    report.append("")
    
    # Recommendations
    report.append("## Security Recommendations")
    report.append("")
    
    # Priority 1: Critical gaps
    if critical_gaps:
        report.append("### 🚨 Priority 1: Critical Security Gaps")
        for gap in critical_gaps:
            report.append(f"- Add @critical_api protection to **{gap['filename']}**")
        report.append("")
    
    # Priority 2: Medium risk improvements
    medium_gaps = [f for f in analysis['medium_risk_files']
                   if not f['security_status']['has_security_decorator'] and not f['security_status']['has_other_protection']]
    
    if medium_gaps:
        report.append("### ⚠️ Priority 2: Medium Risk Improvements")
        for gap in medium_gaps[:5]:  # Show first 5
            report.append(f"- Consider protection for **{gap['filename']}**")
        if len(medium_gaps) > 5:
            report.append(f"- ... and {len(medium_gaps) - 5} other medium-risk files")
        report.append("")
    
    # Coverage improvement plan
    report.append("### 📈 Coverage Improvement Plan")
    
    current_high_risk_coverage = (high_risk_protection_rate / high_risk_count) * 100 if high_risk_count > 0 else 100
    target_coverage = 95
    
    if current_high_risk_coverage < target_coverage:
        files_needed = int((target_coverage / 100 * high_risk_count) - high_risk_protection_rate)
        report.append(f"- **Current high-risk coverage**: {current_high_risk_coverage:.1f}%")
        report.append(f"- **Target coverage**: {target_coverage}%")
        report.append(f"- **Files needing protection**: {files_needed}")
    else:
        report.append("✅ High-risk coverage already exceeds 95% target")
    
    report.append("")
    
    # List all unprotected files
    report.append("## All Unprotected Files")
    if analysis['unprotected_files']:
        report.append("The following files lack security framework protection:")
        report.append("")
        for file_info in analysis['unprotected_files']:
            filename = file_info['filename']
            risk_level = file_info['risk_level']
            whitelist_count = file_info['security_status']['whitelist_count']
            report.append(f"- **{filename}** ({risk_level} risk) - {whitelist_count} whitelist functions")
    else:
        report.append("✅ All files are protected!")

    report.append("")

    # Corrected Coverage Calculation
    report.append("## Corrected Coverage Metrics")
    report.append("")

    if high_risk_count > 0:
        accurate_coverage = (high_risk_protection_rate / high_risk_count) * 100
        report.append(f"**Accurate High-Risk API Coverage: {accurate_coverage:.1f}%**")
        report.append(f"*(Based on {high_risk_protection_rate} protected out of {high_risk_count} high-risk APIs)*")

    overall_protection_rate = (protected_count / total_files) * 100 if total_files > 0 else 0
    report.append(f"**Overall API Protection Rate: {overall_protection_rate:.1f}%**")
    report.append(f"*(Based on {protected_count} protected out of {total_files} total APIs)*")
    
    # Save report
    report_text = "\n".join(report)
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/detailed_security_audit_report.md', 'w') as f:
        f.write(report_text)
    
    print("\n" + "🔒 DETAILED SECURITY AUDIT SUMMARY")
    print("=" * 50)
    print(f"Total API Files: {total_files}")
    print(f"High Risk Files: {high_risk_count}")
    print(f"High Risk Protected: {high_risk_protection_rate}/{high_risk_count} ({high_risk_percentage:.1f}%)")
    print(f"Critical Gaps: {len(critical_gaps)} high-risk files need protection")
    print("=" * 50)
    print("📄 Detailed report saved to: detailed_security_audit_report.md")


if __name__ == "__main__":
    detailed_security_audit()