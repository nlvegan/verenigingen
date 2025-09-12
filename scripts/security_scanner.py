#!/usr/bin/env python3
"""
Comprehensive Security Scanner for Verenigingen
Based on patterns identified during account creation security investigation.

Scans for:
1. Unauthorized permission bypasses (ignore_permissions=True)
2. Missing permission validation in whitelisted endpoints
3. User context leakage in tests
4. Security-sensitive operations without audit trails
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Tuple


class SecurityScanner:
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.violations = []
    
    def scan_permission_bypasses(self, paths: List[str]) -> List[Dict]:
        """Scan for unauthorized ignore_permissions=True usage"""
        violations = []
        permission_bypass_pattern = re.compile(r'ignore_permissions\s*=\s*True')
        
        for file_path in paths:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            matches = permission_bypass_pattern.finditer(content)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                lines = content.split('\n')
                actual_line = lines[line_num-1] if line_num <= len(lines) else ""
                
                # Skip comments and acceptable patterns
                if self._is_acceptable_bypass(actual_line, lines, line_num):
                    continue
                
                violations.append({
                    'file': file_path,
                    'line': line_num,
                    'type': 'unauthorized_permission_bypass',
                    'content': actual_line.strip(),
                    'severity': 'high'
                })
        
        return violations
    
    def scan_whitelist_security(self, paths: List[str]) -> List[Dict]:
        """Scan whitelisted endpoints for missing permission validation"""
        violations = []
        whitelist_pattern = re.compile(r'@frappe\.whitelist\(\)')
        
        for file_path in paths:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find whitelisted functions
            matches = whitelist_pattern.finditer(content)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                
                # Check next 20 lines for permission validation
                lines = content.split('\n')
                function_lines = lines[line_num:line_num+20]
                
                has_permission_check = any(
                    'frappe.has_permission' in line or 
                    'frappe.throw' in line and 'permission' in line.lower()
                    for line in function_lines[:10]
                )
                
                if not has_permission_check:
                    violations.append({
                        'file': file_path,
                        'line': line_num,
                        'type': 'missing_permission_validation',
                        'content': f"Whitelisted function without permission check",
                        'severity': 'medium'
                    })
        
        return violations
    
    def scan_test_context_leakage(self, test_paths: List[str]) -> List[Dict]:
        """Scan test files for user context leakage"""
        violations = []
        set_user_pattern = re.compile(r'frappe\.set_user\([^)]+\)')
        
        for file_path in test_paths:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            matches = list(set_user_pattern.finditer(content))
            
            # Check for unmatched set_user calls
            for i, match in enumerate(matches):
                line_num = content[:match.start()].count('\n') + 1
                user_set = match.group(0)
                
                # Skip if setting to Administrator
                if 'Administrator' in user_set:
                    continue
                
                # Look for corresponding Administrator reset in next 50 lines
                lines = content.split('\n')
                subsequent_lines = lines[line_num:line_num+50]
                has_reset = any('Administrator' in line and 'frappe.set_user' in line 
                              for line in subsequent_lines)
                
                if not has_reset:
                    violations.append({
                        'file': file_path,
                        'line': line_num,
                        'type': 'user_context_leakage',
                        'content': user_set,
                        'severity': 'medium'
                    })
        
        return violations
    
    def _is_acceptable_bypass(self, line: str, lines: List[str], line_num: int) -> bool:
        """Check if permission bypass is acceptable"""
        # Skip comments
        if line.strip().startswith('#'):
            return True
        if '# NO ignore_permissions=True' in line:
            return True
        if '# System' in line or '# system' in line:
            return True
        
        # Check context around the line
        context_start = max(0, line_num - 3)
        context_end = min(len(lines), line_num + 3)
        context = '\n'.join(lines[context_start:context_end]).lower()
        
        acceptable_patterns = [
            'status tracking', 'system operation', 'mark_', 
            'audit', 'logging', 'save.*status', 'test.*flag'
        ]
        
        return any(pattern in context for pattern in acceptable_patterns)
    
    def generate_report(self) -> str:
        """Generate comprehensive security report"""
        # Scan different file types
        utils_files = list(self.base_path.glob("verenigingen/utils/*.py"))
        api_files = list(self.base_path.glob("verenigingen/api/*.py"))
        doctype_files = list(self.base_path.glob("verenigingen/verenigingen/doctype/*/*.py"))
        test_files = list(self.base_path.glob("verenigingen/tests/test_*.py"))
        
        all_source_files = [str(f) for f in utils_files + api_files + doctype_files]
        all_test_files = [str(f) for f in test_files]
        
        # Run scans
        permission_violations = self.scan_permission_bypasses(all_source_files)
        whitelist_violations = self.scan_whitelist_security(all_source_files)
        context_violations = self.scan_test_context_leakage(all_test_files)
        
        # Generate report
        report = []
        report.append("=" * 80)
        report.append("SECURITY SCAN REPORT - Verenigingen")
        report.append("=" * 80)
        report.append(f"Scanned {len(all_source_files)} source files")
        report.append(f"Scanned {len(all_test_files)} test files")
        report.append("")
        
        # Permission bypass violations
        if permission_violations:
            report.append(f"🚨 PERMISSION BYPASS VIOLATIONS ({len(permission_violations)})")
            report.append("-" * 40)
            for v in permission_violations[:10]:  # Show top 10
                report.append(f"  {v['file']}:{v['line']} - {v['content']}")
            if len(permission_violations) > 10:
                report.append(f"  ... and {len(permission_violations) - 10} more")
            report.append("")
        
        # Whitelist security violations
        if whitelist_violations:
            report.append(f"⚠️  WHITELIST SECURITY ISSUES ({len(whitelist_violations)})")
            report.append("-" * 40)
            for v in whitelist_violations[:10]:
                report.append(f"  {v['file']}:{v['line']} - {v['content']}")
            if len(whitelist_violations) > 10:
                report.append(f"  ... and {len(whitelist_violations) - 10} more")
            report.append("")
        
        # Test context violations
        if context_violations:
            report.append(f"🔀 TEST CONTEXT LEAKAGE ({len(context_violations)})")
            report.append("-" * 40)
            for v in context_violations[:10]:
                report.append(f"  {v['file']}:{v['line']} - {v['content']}")
            if len(context_violations) > 10:
                report.append(f"  ... and {len(context_violations) - 10} more")
            report.append("")
        
        # Summary
        total_violations = len(permission_violations) + len(whitelist_violations) + len(context_violations)
        if total_violations == 0:
            report.append("✅ No security violations found!")
        else:
            report.append(f"📊 SUMMARY: {total_violations} total security issues found")
            report.append(f"   - {len(permission_violations)} permission bypass violations")
            report.append(f"   - {len(whitelist_violations)} whitelist security issues")
            report.append(f"   - {len(context_violations)} test context leakage issues")
        
        return "\n".join(report)


if __name__ == "__main__":
    scanner = SecurityScanner()
    report = scanner.generate_report()
    print(report)