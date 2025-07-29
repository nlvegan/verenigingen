#!/usr/bin/env python3
"""
Automated API Security Scanner
Scans all API files for @frappe.whitelist() functions and classifies security risks
"""

import os
import ast
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from enum import Enum

class SecurityRisk(Enum):
    ULTRA_CRITICAL = "ULTRA_CRITICAL"
    CRITICAL = "CRITICAL" 
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class OperationType(Enum):
    FINANCIAL = "FINANCIAL"
    ADMIN = "ADMIN"
    MEMBER_DATA = "MEMBER_DATA"
    REPORTING = "REPORTING"
    UTILITY = "UTILITY"

@dataclass
class APIFunction:
    name: str
    file_path: str
    line_number: int
    function_code: str
    risk_level: SecurityRisk
    operation_type: OperationType
    reasons: List[str]
    has_security_decorator: bool
    current_decorator: str = None

class APISecurityScanner:
    
    # Ultra-critical patterns - direct financial/admin operations
    ULTRA_CRITICAL_PATTERNS = [
        r'sepa.*batch.*process',
        r'payment.*process',
        r'direct.*debit.*execute',
        r'financial.*transaction',
        r'admin.*override',
        r'system.*config.*change',
        r'user.*permission.*grant',
        r'database.*migrate',
        r'backup.*restore'
    ]
    
    # Critical patterns - sensitive data operations
    CRITICAL_PATTERNS = [
        r'member.*delete',
        r'volunteer.*terminate',
        r'payment.*create',
        r'mandate.*create',
        r'dues.*calculate',
        r'invoice.*generate',
        r'export.*financial',
        r'batch.*operation',
        r'mass.*update',
        r'approve.*application'
    ]
    
    # High risk patterns - important business operations
    HIGH_PATTERNS = [
        r'member.*update',
        r'volunteer.*create',
        r'chapter.*assign',
        r'expense.*approve',
        r'report.*generate',
        r'notification.*send',
        r'status.*change',
        r'application.*review'
    ]
    
    # Medium risk patterns - data access operations  
    MEDIUM_PATTERNS = [
        r'member.*get',
        r'volunteer.*lookup',
        r'payment.*history',
        r'report.*data',
        r'dashboard.*stats',
        r'validation.*check'
    ]
    
    # Financial operation keywords
    FINANCIAL_KEYWORDS = [
        'payment', 'sepa', 'mandate', 'dues', 'invoice', 'financial', 
        'transaction', 'batch', 'debit', 'money', 'amount', 'fee'
    ]
    
    # Admin operation keywords
    ADMIN_KEYWORDS = [
        'admin', 'system', 'config', 'permission', 'user', 'role',
        'migrate', 'backup', 'restore', 'override', 'force'
    ]
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.scan_directories = [
            self.base_path / "api",
            self.base_path / "verenigingen" / "api", 
            self.base_path / "verenigingen" / "utils",
            self.base_path / "verenigingen" / "verenigingen" / "doctype"
        ]
        self.results: List[APIFunction] = []
        self.secured_files: Set[str] = set()
        self.security_decorators = [
            '@critical_api',
            '@high_security_api', 
            '@standard_api',
            '@ultra_critical_api'
        ]
        
    def scan_all_files(self) -> Dict[str, List[APIFunction]]:
        """Scan all directories for API functions"""
        print("🔍 Starting comprehensive API security scan...")
        
        for directory in self.scan_directories:
            if directory.exists():
                print(f"\n📁 Scanning directory: {directory}")
                self._scan_directory(directory)
            else:
                print(f"⚠️  Directory not found: {directory}")
                
        return self._organize_results()
    
    def _scan_directory(self, directory: Path):
        """Recursively scan directory for Python files"""
        for file_path in directory.rglob("*.py"):
            if self._should_scan_file(file_path):
                self._scan_file(file_path)
                
    def _should_scan_file(self, file_path: Path) -> bool:
        """Check if file should be scanned"""
        # Skip test files, __init__.py, and backup files
        exclude_patterns = [
            'test_', '__init__.py', '.backup', '.disabled',
            '__pycache__', '.pyc'
        ]
        
        file_name = file_path.name
        return not any(pattern in file_name for pattern in exclude_patterns)
    
    def _scan_file(self, file_path: Path):
        """Scan individual file for API functions"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Check if file has security decorators already
            has_security_imports = any(decorator.replace('@', '') in content 
                                     for decorator in self.security_decorators)
            if has_security_imports:
                self.secured_files.add(str(file_path))
                
            # Parse AST to find functions
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._analyze_function(node, file_path, content)
                    
        except Exception as e:
            print(f"❌ Error scanning {file_path}: {e}")
    
    def _analyze_function(self, node: ast.FunctionDef, file_path: Path, content: str):
        """Analyze individual function for security requirements"""
        # Check if function has @frappe.whitelist() decorator
        has_whitelist = False
        has_security_decorator = False
        current_decorator = None
        
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute):
                if (hasattr(decorator.value, 'id') and 
                    decorator.value.id == 'frappe' and 
                    decorator.attr == 'whitelist'):
                    has_whitelist = True
            elif isinstance(decorator, ast.Name):
                decorator_name = f"@{decorator.id}"
                if decorator_name in self.security_decorators:
                    has_security_decorator = True
                    current_decorator = decorator_name
        
        # Only analyze whitelisted functions without security decorators
        if has_whitelist and not has_security_decorator:
            function_code = self._extract_function_code(content, node.lineno)
            risk_level, operation_type, reasons = self._classify_function_risk(
                node.name, function_code, str(file_path)
            )
            
            api_function = APIFunction(
                name=node.name,
                file_path=str(file_path),
                line_number=node.lineno,
                function_code=function_code[:500],  # First 500 chars
                risk_level=risk_level,
                operation_type=operation_type,
                reasons=reasons,
                has_security_decorator=has_security_decorator,
                current_decorator=current_decorator
            )
            
            self.results.append(api_function)
    
    def _extract_function_code(self, content: str, line_number: int) -> str:
        """Extract function code around line number"""
        lines = content.split('\n')
        start_line = max(0, line_number - 5)
        end_line = min(len(lines), line_number + 15)
        return '\n'.join(lines[start_line:end_line])
    
    def _classify_function_risk(self, function_name: str, function_code: str, file_path: str) -> Tuple[SecurityRisk, OperationType, List[str]]:
        """Classify function risk level and operation type"""
        combined_text = f"{function_name} {function_code} {file_path}".lower()
        reasons = []
        
        # Check for ultra-critical patterns
        for pattern in self.ULTRA_CRITICAL_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                reasons.append(f"Ultra-critical pattern: {pattern}")
                return SecurityRisk.ULTRA_CRITICAL, self._determine_operation_type(combined_text), reasons
        
        # Check for critical patterns
        for pattern in self.CRITICAL_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                reasons.append(f"Critical pattern: {pattern}")
                return SecurityRisk.CRITICAL, self._determine_operation_type(combined_text), reasons
        
        # Check for high risk patterns
        for pattern in self.HIGH_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                reasons.append(f"High risk pattern: {pattern}")
                return SecurityRisk.HIGH, self._determine_operation_type(combined_text), reasons
                
        # Check for medium risk patterns
        for pattern in self.MEDIUM_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                reasons.append(f"Medium risk pattern: {pattern}")
                return SecurityRisk.MEDIUM, self._determine_operation_type(combined_text), reasons
        
        # Default to low risk
        reasons.append("No specific risk patterns detected")
        return SecurityRisk.LOW, OperationType.UTILITY, reasons
    
    def _determine_operation_type(self, text: str) -> OperationType:
        """Determine operation type based on function characteristics"""
        if any(keyword in text for keyword in self.FINANCIAL_KEYWORDS):
            return OperationType.FINANCIAL
        elif any(keyword in text for keyword in self.ADMIN_KEYWORDS):
            return OperationType.ADMIN
        elif any(keyword in text for keyword in ['member', 'volunteer', 'chapter']):
            return OperationType.MEMBER_DATA
        elif any(keyword in text for keyword in ['report', 'dashboard', 'stats', 'analytics']):
            return OperationType.REPORTING
        else:
            return OperationType.UTILITY
    
    def _organize_results(self) -> Dict[str, List[APIFunction]]:
        """Organize scan results by risk level"""
        organized = {
            'ULTRA_CRITICAL': [],
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }
        
        for func in self.results:
            organized[func.risk_level.value].append(func)
            
        return organized
    
    def generate_report(self) -> Dict:
        """Generate comprehensive security report"""
        organized_results = self._organize_results()
        
        report = {
            'scan_summary': {
                'total_unsecured_functions': len(self.results),
                'total_secured_files': len(self.secured_files),
                'directories_scanned': len(self.scan_directories),
                'risk_breakdown': {
                    risk: len(functions) 
                    for risk, functions in organized_results.items()
                }
            },
            'detailed_results': organized_results,
            'secured_files': list(self.secured_files),
            'recommendations': self._generate_recommendations(organized_results)
        }
        
        return report
    
    def _generate_recommendations(self, results: Dict) -> Dict:
        """Generate security recommendations"""
        recommendations = {
            'immediate_action_required': [],
            'high_priority': [],
            'medium_priority': [],
            'suggested_decorators': {}
        }
        
        # Ultra-critical and critical functions need immediate attention
        for func in results['ULTRA_CRITICAL'] + results['CRITICAL']:
            recommendations['immediate_action_required'].append({
                'file': func.file_path,
                'function': func.name,
                'suggested_decorator': f"@critical_api(OperationType.{func.operation_type.value})",
                'reason': func.reasons[0] if func.reasons else "High risk operation"
            })
            
        # High risk functions are high priority
        for func in results['HIGH']:
            recommendations['high_priority'].append({
                'file': func.file_path,
                'function': func.name,
                'suggested_decorator': f"@high_security_api(OperationType.{func.operation_type.value})",
                'reason': func.reasons[0] if func.reasons else "High risk operation"
            })
            
        return recommendations
    
    def save_report(self, output_path: str = None):
        """Save scan report to file"""
        if not output_path:
            output_path = self.base_path / "security_scan_report.json"
            
        report = self.generate_report()
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"📊 Security scan report saved to: {output_path}")
        return output_path

def main():
    """Main execution function"""
    scanner = APISecurityScanner()
    
    print("🚀 Starting Automated API Security Scan")
    print("=" * 50)
    
    # Perform comprehensive scan
    results = scanner.scan_all_files()
    
    # Generate and save report
    report_path = scanner.save_report()
    
    # Print summary
    report = scanner.generate_report()
    summary = report['scan_summary']
    
    print("\n📊 SCAN SUMMARY")
    print("=" * 30)
    print(f"Total Unsecured Functions: {summary['total_unsecured_functions']}")
    print(f"Total Secured Files: {summary['total_secured_files']}")
    print(f"Directories Scanned: {summary['directories_scanned']}")
    
    print("\n🚨 RISK BREAKDOWN")
    print("-" * 20)
    for risk, count in summary['risk_breakdown'].items():
        if count > 0:
            print(f"{risk}: {count} functions")
    
    print("\n⚡ IMMEDIATE ACTION REQUIRED")
    print("-" * 30)
    immediate_actions = report['recommendations']['immediate_action_required']
    for action in immediate_actions[:10]:  # Show first 10
        print(f"📁 {action['file']}")
        print(f"   🔧 {action['function']} -> {action['suggested_decorator']}")
        
    if len(immediate_actions) > 10:
        print(f"   ... and {len(immediate_actions) - 10} more critical functions")
    
    print(f"\n📋 Full report available at: {report_path}")
    
    return scanner, report

if __name__ == "__main__":
    scanner, report = main()