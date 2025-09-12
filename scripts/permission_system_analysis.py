#!/usr/bin/env python3
"""
Permission System Analysis and Remediation Plan
Addresses the inconsistencies identified between test and production permission handling.

Categories of Issues Identified:
1. Administrative/System Operations - Legitimate bypass needs proper authorization checks
2. Test Utilities - Development functions need proper security controls
3. Data Import/Cleanup - Bulk operations need controlled permission bypass
4. API Endpoints - Missing permission validation on whitelisted functions
5. Test Context Leakage - Improper user context switching in tests

This analysis provides recommendations for each category based on enterprise security patterns.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Set


class PermissionSystemAnalyzer:
    """Analyze and categorize permission system inconsistencies"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        
    def analyze_permission_bypasses(self) -> Dict[str, List[Dict]]:
        """Categorize permission bypass usage patterns"""
        categories = {
            "administrative_operations": [],
            "test_utilities": [],
            "data_operations": [],
            "system_operations": [],
            "questionable_bypasses": []
        }
        
        # Scan for permission bypasses
        bypass_pattern = re.compile(r'ignore_permissions\s*=\s*True')
        
        for py_file in self.base_path.rglob("*.py"):
            if not py_file.exists():
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                matches = bypass_pattern.finditer(content)
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    lines = content.split('\n')
                    actual_line = lines[line_num-1] if line_num <= len(lines) else ""
                    
                    # Get context
                    context_start = max(0, line_num - 5)
                    context_end = min(len(lines), line_num + 5)
                    context_lines = lines[context_start:context_end]
                    
                    bypass_info = {
                        'file': str(py_file),
                        'line': line_num,
                        'content': actual_line.strip(),
                        'context': context_lines,
                        'category': self._categorize_bypass(py_file, actual_line, context_lines)
                    }
                    
                    categories[bypass_info['category']].append(bypass_info)
                    
            except Exception as e:
                print(f"Error processing {py_file}: {e}")
                continue
                
        return categories
    
    def _categorize_bypass(self, file_path: Path, line: str, context: List[str]) -> str:
        """Categorize a permission bypass based on context"""
        file_str = str(file_path).lower()
        line_lower = line.lower()
        context_str = '\n'.join(context).lower()
        
        # Test utilities
        if ('test' in file_str or 'fixture' in file_str or 
            'debug' in file_str or 'create_test' in file_str):
            return "test_utilities"
        
        # Administrative operations
        if ('cleanup' in file_str or 'migration' in file_str or 
            'import' in file_str or 'export' in file_str):
            return "administrative_operations"
        
        # System operations (status tracking, audit logging)
        if any(keyword in context_str for keyword in [
            'status tracking', 'system operation', 'audit', 
            'logging', 'mark_', 'tracking'
        ]):
            return "system_operations"
        
        # Data operations
        if any(keyword in context_str for keyword in [
            'bulk', 'batch', 'mass', 'migration', 'import',
            'cleanup', 'maintenance'
        ]):
            return "data_operations"
        
        # Default to questionable
        return "questionable_bypasses"
    
    def analyze_whitelist_security(self) -> Dict[str, List[Dict]]:
        """Analyze whitelisted functions for missing permission validation"""
        issues = {
            "missing_permission_checks": [],
            "test_utilities_exposed": [],
            "admin_functions_unprotected": [],
            "proper_validation": []
        }
        
        whitelist_pattern = re.compile(r'@frappe\.whitelist\(\)')
        
        for py_file in self.base_path.rglob("*.py"):
            if not py_file.exists():
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                matches = whitelist_pattern.finditer(content)
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    lines = content.split('\n')
                    
                    # Get function context (next 20 lines)
                    function_lines = lines[line_num:line_num+20]
                    
                    # Check for permission validation
                    has_permission_check = self._has_permission_validation(function_lines)
                    function_name = self._extract_function_name(function_lines)
                    
                    issue_info = {
                        'file': str(py_file),
                        'line': line_num,
                        'function': function_name,
                        'has_validation': has_permission_check,
                        'category': self._categorize_whitelist_function(py_file, function_name, function_lines)
                    }
                    
                    if has_permission_check:
                        issues["proper_validation"].append(issue_info)
                    else:
                        issues[issue_info['category']].append(issue_info)
                        
            except Exception as e:
                continue
                
        return issues
    
    def _has_permission_validation(self, function_lines: List[str]) -> bool:
        """Check if function has proper permission validation"""
        context = '\n'.join(function_lines[:15]).lower()
        
        permission_checks = [
            'frappe.has_permission',
            'frappe.throw.*permission',
            'permissionerror',
            'validate_permissions',
            'check_permission',
            'frappe.only_for',
            'role_required'
        ]
        
        return any(re.search(check, context) for check in permission_checks)
    
    def _extract_function_name(self, function_lines: List[str]) -> str:
        """Extract function name from code lines"""
        for line in function_lines[:5]:
            if line.strip().startswith('def '):
                match = re.search(r'def\s+(\w+)', line)
                if match:
                    return match.group(1)
        return "unknown_function"
    
    def _categorize_whitelist_function(self, file_path: Path, function_name: str, lines: List[str]) -> str:
        """Categorize whitelisted function by risk level"""
        file_str = str(file_path).lower()
        func_str = function_name.lower()
        context = '\n'.join(lines).lower()
        
        # Test utilities should not be whitelisted in production
        if ('test' in file_str or 'debug' in func_str or 
            'create_test' in func_str or 'fixture' in file_str):
            return "test_utilities_exposed"
        
        # Administrative functions
        if any(keyword in func_str for keyword in [
            'admin', 'manage', 'delete', 'create', 'update',
            'import', 'export', 'cleanup', 'migration'
        ]):
            return "admin_functions_unprotected"
        
        return "missing_permission_checks"
    
    def generate_remediation_plan(self) -> str:
        """Generate comprehensive remediation plan"""
        bypass_analysis = self.analyze_permission_bypasses()
        whitelist_analysis = self.analyze_whitelist_security()
        
        plan = []
        plan.append("=" * 80)
        plan.append("PERMISSION SYSTEM REMEDIATION PLAN")
        plan.append("=" * 80)
        plan.append("")
        
        # Executive Summary
        total_bypasses = sum(len(issues) for issues in bypass_analysis.values())
        total_whitelist_issues = sum(len(issues) for k, issues in whitelist_analysis.items() 
                                   if k != "proper_validation")
        
        plan.append("EXECUTIVE SUMMARY")
        plan.append("-" * 40)
        plan.append(f"• {total_bypasses} permission bypasses found")
        plan.append(f"• {total_whitelist_issues} API security issues identified")
        plan.append(f"• {len(whitelist_analysis['proper_validation'])} properly secured endpoints")
        plan.append("")
        
        # Priority 1: Security Vulnerabilities
        plan.append("PRIORITY 1: CRITICAL SECURITY VULNERABILITIES")
        plan.append("-" * 50)
        
        # Questionable bypasses
        questionable = bypass_analysis.get("questionable_bypasses", [])
        if questionable:
            plan.append(f"🚨 {len(questionable)} UNAUTHORIZED PERMISSION BYPASSES")
            plan.append("   Immediate action required - no business justification found")
            for issue in questionable[:5]:  # Show top 5
                plan.append(f"   • {issue['file']}:{issue['line']} - {issue['content']}")
            if len(questionable) > 5:
                plan.append(f"   ... and {len(questionable) - 5} more")
            plan.append("")
        
        # Exposed test utilities
        exposed_tests = whitelist_analysis.get("test_utilities_exposed", [])
        if exposed_tests:
            plan.append(f"🚨 {len(exposed_tests)} TEST UTILITIES EXPOSED TO PRODUCTION")
            plan.append("   Remove @frappe.whitelist() or add proper access controls")
            for issue in exposed_tests[:5]:
                plan.append(f"   • {issue['file']}:{issue['line']} - {issue['function']}()")
            if len(exposed_tests) > 5:
                plan.append(f"   ... and {len(exposed_tests) - 5} more")
            plan.append("")
        
        # Priority 2: Administrative Security
        plan.append("PRIORITY 2: ADMINISTRATIVE SECURITY HARDENING")
        plan.append("-" * 50)
        
        admin_functions = whitelist_analysis.get("admin_functions_unprotected", [])
        if admin_functions:
            plan.append(f"⚠️  {len(admin_functions)} ADMINISTRATIVE FUNCTIONS WITHOUT PERMISSION CHECKS")
            plan.append("   Add role-based access control validation")
            for issue in admin_functions[:5]:
                plan.append(f"   • {issue['file']}:{issue['line']} - {issue['function']}()")
            if len(admin_functions) > 5:
                plan.append(f"   ... and {len(admin_functions) - 5} more")
            plan.append("")
        
        # Priority 3: System Operations Review
        plan.append("PRIORITY 3: SYSTEM OPERATIONS REVIEW")
        plan.append("-" * 45)
        
        system_ops = bypass_analysis.get("system_operations", [])
        if system_ops:
            plan.append(f"📋 {len(system_ops)} SYSTEM OPERATIONS WITH PERMISSION BYPASSES")
            plan.append("   Review and validate business justification")
            for issue in system_ops[:3]:
                plan.append(f"   • {issue['file']}:{issue['line']} - System operation")
            plan.append("")
        
        # Priority 4: Bulk Operations
        plan.append("PRIORITY 4: BULK OPERATIONS SECURITY")
        plan.append("-" * 40)
        
        admin_ops = bypass_analysis.get("administrative_operations", [])
        data_ops = bypass_analysis.get("data_operations", [])
        total_bulk = len(admin_ops) + len(data_ops)
        
        if total_bulk > 0:
            plan.append(f"📊 {total_bulk} BULK/ADMINISTRATIVE OPERATIONS")
            plan.append("   Implement controlled permission bypass with authorization checks")
            plan.append("   Example pattern:")
            plan.append("   ```python")
            plan.append("   def bulk_operation():")
            plan.append("       if not is_system_operation_authorized():")
            plan.append("           frappe.throw('Insufficient permissions for bulk operation')")
            plan.append("       # Proceed with ignore_permissions=True for system operation")
            plan.append("   ```")
            plan.append("")
        
        # Recommended Implementation Patterns
        plan.append("RECOMMENDED SECURITY PATTERNS")
        plan.append("-" * 35)
        plan.append("")
        
        plan.append("1. API Endpoint Security Pattern:")
        plan.append("```python")
        plan.append("@frappe.whitelist()")
        plan.append("def secure_api_endpoint():")
        plan.append("    # Validate user permissions")
        plan.append("    if not frappe.has_permission('DocType', 'read'):")
        plan.append("        frappe.throw('Insufficient permissions', frappe.PermissionError)")
        plan.append("    ")
        plan.append("    # Business logic here")
        plan.append("```")
        plan.append("")
        
        plan.append("2. System Operation Pattern:")
        plan.append("```python")
        plan.append("def system_operation():")
        plan.append("    # Check authorization for system operations")
        plan.append("    if not is_system_operation_authorized():")
        plan.append("        frappe.throw('Unauthorized system operation')")
        plan.append("    ")
        plan.append("    # Use ignore_permissions=True only for system status tracking")
        plan.append("    doc.save(ignore_permissions=True)  # Status tracking only")
        plan.append("```")
        plan.append("")
        
        plan.append("3. Test Environment Control:")
        plan.append("```python")
        plan.append("@frappe.whitelist()")
        plan.append("def debug_function():")
        plan.append("    # Restrict to development environment")
        plan.append("    if not frappe.conf.developer_mode:")
        plan.append("        frappe.throw('Debug functions not available in production')")
        plan.append("    # Debug logic here")
        plan.append("```")
        plan.append("")
        
        return "\n".join(plan)


def main():
    analyzer = PermissionSystemAnalyzer()
    plan = analyzer.generate_remediation_plan()
    print(plan)
    
    # Save detailed analysis
    bypass_analysis = analyzer.analyze_permission_bypasses()
    whitelist_analysis = analyzer.analyze_whitelist_security()
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/scripts/permission_analysis_details.json', 'w') as f:
        json.dump({
            'permission_bypasses': bypass_analysis,
            'whitelist_security': whitelist_analysis
        }, f, indent=2, default=str)
    
    print("\n" + "="*80)
    print("Detailed analysis saved to: scripts/permission_analysis_details.json")
    print("="*80)


if __name__ == "__main__":
    main()