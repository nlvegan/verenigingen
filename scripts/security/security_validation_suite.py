#!/usr/bin/env python3
"""
Security Validation Suite
Validates that all secured API files are functioning correctly with proper decorators
"""

import os
import ast
import re
import sys
import importlib.util
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
import json

@dataclass
class SecurityValidationResult:
    file_path: str
    functions_analyzed: int
    security_decorators_found: List[str]
    issues_found: List[str]
    validation_status: str  # "PASS", "FAIL", "WARNING"
    suggestions: List[str]

class SecurityValidationSuite:
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.valid_decorators = [
            'critical_api',
            'high_security_api', 
            'standard_api',
            'ultra_critical_api'
        ]
        self.required_imports = [
            'from verenigingen.utils.security.api_security_framework import',
            'from verenigingen.utils.security.decorators import'
        ]
        
    def validate_all_secured_files(self, secured_files: List[str]) -> Dict[str, SecurityValidationResult]:
        """Validate all secured files for proper implementation"""
        results = {}
        
        print("🔍 Validating Security Implementation...")
        print("=" * 50)
        
        for file_path in secured_files:
            if Path(file_path).exists():
                result = self._validate_file(file_path)
                results[file_path] = result
                self._print_file_result(result)
            else:
                print(f"⚠️  File not found: {file_path}")
                
        return results
    
    def _validate_file(self, file_path: str) -> SecurityValidationResult:
        """Validate individual file for security implementation"""
        issues = []
        suggestions = []
        decorators_found = []
        functions_analyzed = 0
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Check for required imports
            has_required_imports = self._check_imports(content, issues)
            
            # Parse AST to analyze functions
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    has_whitelist = self._has_frappe_whitelist(node)
                    if has_whitelist:
                        functions_analyzed += 1
                        security_decorator = self._get_security_decorator(node)
                        
                        if security_decorator:
                            decorators_found.append(security_decorator)
                        else:
                            issues.append(f"Function '{node.name}' has @frappe.whitelist() but no security decorator")
            
            # Determine validation status
            if not issues:
                status = "PASS"
            elif len(issues) <= 2:
                status = "WARNING"
            else:
                status = "FAIL"
                
            # Generate suggestions
            if not has_required_imports:
                suggestions.append("Add security framework imports")
            if functions_analyzed > len(decorators_found):
                suggestions.append("Add security decorators to all whitelisted functions")
                
        except Exception as e:
            issues.append(f"File parsing error: {str(e)}")
            status = "FAIL"
            
        return SecurityValidationResult(
            file_path=file_path,
            functions_analyzed=functions_analyzed,
            security_decorators_found=decorators_found,
            issues_found=issues,
            validation_status=status,
            suggestions=suggestions
        )
    
    def _check_imports(self, content: str, issues: List[str]) -> bool:
        """Check if file has required security imports"""
        has_imports = False
        
        for required_import in self.required_imports:
            if required_import in content:
                has_imports = True
                break
                
        if not has_imports and '@' in content and 'frappe.whitelist' in content:
            issues.append("Missing security framework imports")
            
        return has_imports
    
    def _has_frappe_whitelist(self, node: ast.FunctionDef) -> bool:
        """Check if function has @frappe.whitelist() decorator"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute):
                if (hasattr(decorator.value, 'id') and 
                    decorator.value.id == 'frappe' and 
                    decorator.attr == 'whitelist'):
                    return True
        return False
    
    def _get_security_decorator(self, node: ast.FunctionDef) -> str:
        """Get the security decorator for the function"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                if decorator.id in self.valid_decorators:
                    return decorator.id
            elif isinstance(decorator, ast.Call):
                if hasattr(decorator.func, 'id') and decorator.func.id in self.valid_decorators:
                    return decorator.func.id
        return None
    
    def _print_file_result(self, result: SecurityValidationResult):
        """Print validation result for a file"""
        status_emoji = {
            "PASS": "✅",
            "WARNING": "⚠️",
            "FAIL": "❌"
        }
        
        file_name = Path(result.file_path).name
        emoji = status_emoji.get(result.validation_status, "❓")
        
        print(f"{emoji} {file_name} - {result.validation_status}")
        print(f"   Functions: {result.functions_analyzed}, Decorators: {len(result.security_decorators_found)}")
        
        if result.issues_found:
            print(f"   Issues: {len(result.issues_found)}")
            for issue in result.issues_found[:2]:  # Show first 2 issues
                print(f"     • {issue}")
                
        if result.suggestions:
            print(f"   Suggestions: {', '.join(result.suggestions)}")
            
        print()
    
    def generate_security_report(self, validation_results: Dict[str, SecurityValidationResult]) -> Dict:
        """Generate comprehensive security validation report"""
        total_files = len(validation_results)
        passed_files = sum(1 for r in validation_results.values() if r.validation_status == "PASS")
        warning_files = sum(1 for r in validation_results.values() if r.validation_status == "WARNING")
        failed_files = sum(1 for r in validation_results.values() if r.validation_status == "FAIL")
        
        total_functions = sum(r.functions_analyzed for r in validation_results.values())
        total_decorators = sum(len(r.security_decorators_found) for r in validation_results.values())
        
        decorator_usage = {}
        for result in validation_results.values():
            for decorator in result.security_decorators_found:
                decorator_usage[decorator] = decorator_usage.get(decorator, 0) + 1
        
        report = {
            'validation_summary': {
                'total_files_validated': total_files,
                'files_passed': passed_files,
                'files_with_warnings': warning_files,
                'files_failed': failed_files,
                'success_rate': f"{(passed_files / total_files * 100):.1f}%" if total_files > 0 else "0%",
                'total_functions_analyzed': total_functions,
                'total_security_decorators': total_decorators,
                'decoration_coverage': f"{(total_decorators / total_functions * 100):.1f}%" if total_functions > 0 else "0%"
            },
            'decorator_usage_stats': decorator_usage,
            'files_needing_attention': [
                {
                    'file': result.file_path,
                    'status': result.validation_status,
                    'issues': result.issues_found,
                    'suggestions': result.suggestions
                }
                for result in validation_results.values()
                if result.validation_status in ["WARNING", "FAIL"]
            ],
            'security_compliance_score': self._calculate_compliance_score(validation_results)
        }
        
        return report
    
    def _calculate_compliance_score(self, validation_results: Dict[str, SecurityValidationResult]) -> Dict:
        """Calculate overall security compliance score"""
        if not validation_results:
            return {"score": 0, "grade": "F", "description": "No files validated"}
            
        total_files = len(validation_results)
        passed_files = sum(1 for r in validation_results.values() if r.validation_status == "PASS")
        warning_files = sum(1 for r in validation_results.values() if r.validation_status == "WARNING")
        
        # Scoring: PASS = 100%, WARNING = 75%, FAIL = 0%
        total_score = (passed_files * 100 + warning_files * 75) / total_files
        
        if total_score >= 95:
            grade = "A+"
            description = "Excellent security implementation"
        elif total_score >= 90:
            grade = "A"
            description = "Very good security implementation"
        elif total_score >= 80:
            grade = "B"
            description = "Good security implementation"
        elif total_score >= 70:
            grade = "C"
            description = "Adequate security implementation"
        elif total_score >= 60:
            grade = "D"
            description = "Poor security implementation"
        else:
            grade = "F"
            description = "Inadequate security implementation"
            
        return {
            "score": round(total_score, 1),
            "grade": grade,
            "description": description
        }

def main():
    """Main execution function"""
    # Load the security scan report to get secured files list
    scanner_report_path = "/home/frappe/frappe-bench/apps/verenigingen/security_scan_report.json"
    
    if not Path(scanner_report_path).exists():
        print("❌ Security scan report not found. Please run automated_security_scanner.py first.")
        return
        
    with open(scanner_report_path, 'r') as f:
        scan_report = json.load(f)
        
    secured_files = scan_report.get('secured_files', [])
    
    if not secured_files:
        print("⚠️  No secured files found in scan report.")
        return
        
    print("🚀 Starting Security Validation Suite")
    print("=" * 50)
    print(f"📊 Validating {len(secured_files)} secured files...")
    print()
    
    # Initialize validator and run validation
    validator = SecurityValidationSuite()
    validation_results = validator.validate_all_secured_files(secured_files)
    
    # Generate comprehensive report
    security_report = validator.generate_security_report(validation_results)
    
    # Save validation report
    report_path = "/home/frappe/frappe-bench/apps/verenigingen/security_validation_report.json"
    with open(report_path, 'w') as f:
        json.dump(security_report, f, indent=2, default=str)
    
    # Print summary
    summary = security_report['validation_summary']
    compliance = security_report['security_compliance_score']
    
    print("📊 VALIDATION SUMMARY")
    print("=" * 30)
    print(f"Files Validated: {summary['total_files_validated']}")
    print(f"Files Passed: {summary['files_passed']} ✅")
    print(f"Files with Warnings: {summary['files_with_warnings']} ⚠️")
    print(f"Files Failed: {summary['files_failed']} ❌")
    print(f"Success Rate: {summary['success_rate']}")
    print(f"Functions Analyzed: {summary['total_functions_analyzed']}")
    print(f"Security Decorators: {summary['total_security_decorators']}")
    print(f"Decoration Coverage: {summary['decoration_coverage']}")
    
    print(f"\n🏆 SECURITY COMPLIANCE SCORE")
    print("=" * 30)
    print(f"Score: {compliance['score']}/100")
    print(f"Grade: {compliance['grade']}")
    print(f"Status: {compliance['description']}")
    
    print(f"\n📈 DECORATOR USAGE STATISTICS")
    print("=" * 30)
    for decorator, count in security_report['decorator_usage_stats'].items():
        print(f"{decorator}: {count} functions")
    
    if security_report['files_needing_attention']:
        print(f"\n🔧 FILES NEEDING ATTENTION")
        print("=" * 30)
        for file_info in security_report['files_needing_attention'][:5]:  # Show first 5
            file_name = Path(file_info['file']).name
            print(f"📁 {file_name} - {file_info['status']}")
            for issue in file_info['issues'][:2]:  # Show first 2 issues
                print(f"   • {issue}")
    
    print(f"\n📋 Full validation report saved to: {report_path}")
    
    return validator, security_report

if __name__ == "__main__":
    validator, report = main()