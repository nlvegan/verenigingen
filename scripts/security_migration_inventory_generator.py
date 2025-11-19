#!/usr/bin/env python3
"""
Security Migration Inventory Generator

Generates comprehensive inventory of functions requiring migration to
the API Security Framework. Categorizes by priority and migration complexity.

Usage: python scripts/security_migration_inventory_generator.py
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import defaultdict


class SecurityMigrationInventory:
    """Generate inventory of functions needing security framework migration"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        
        # Patterns for categorization
        self.security_framework_patterns = [
            r'@(critical_api|high_security_api|standard_api|utility_api|public_api)',
            r'@api_security_framework'
        ]
        
        self.test_debug_patterns = [
            r'test_|debug_|create_test|cleanup_test|_test_|testing_',
            r'def.*test|def.*debug|def.*create_test'
        ]
        
        self.financial_patterns = [
            r'payment|invoice|financial|sepa|mollie|subscription|billing|dues'
        ]
        
        self.admin_patterns = [
            r'admin|manage|bulk_|batch_|create_|delete_|update_|setup_'
        ]
        
        self.member_data_patterns = [
            r'member|volunteer|donor|chapter|personal_'
        ]
        
    def scan_codebase(self) -> Dict[str, any]:
        """Scan codebase and categorize all whitelisted functions"""
        results = {
            'total_files': 0,
            'files_with_whitelist': 0,
            'total_whitelist_functions': 0,
            'functions_with_security': 0,
            'functions_needing_migration': 0,
            'categories': {
                'critical_financial': [],
                'high_admin': [],
                'medium_member_data': [],
                'low_reporting': [],
                'test_debug': [],
                'already_secured': []
            },
            'migration_complexity': {
                'simple': 0,
                'moderate': 0,
                'complex': 0
            },
            'environment_risks': {
                'production_exposed_tests': [],
                'no_environment_controls': []
            }
        }
        
        # Scan all Python files
        for py_file in self.base_path.rglob("*.py"):
            if not py_file.exists() or self._should_skip_file(py_file):
                continue
                
            results['total_files'] += 1
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                functions = self._extract_whitelisted_functions(content, py_file)
                if functions:
                    results['files_with_whitelist'] += 1
                    
                    for func_info in functions:
                        results['total_whitelist_functions'] += 1
                        
                        # Categorize function
                        category = self._categorize_function(func_info)
                        results['categories'][category].append(func_info)
                        
                        if func_info['has_security_framework']:
                            results['functions_with_security'] += 1
                        else:
                            results['functions_needing_migration'] += 1
                            
                            # Assess migration complexity
                            complexity = self._assess_migration_complexity(func_info)
                            results['migration_complexity'][complexity] += 1
                        
                        # Check environment risks
                        if self._is_test_debug_function(func_info) and not func_info['has_development_only']:
                            results['environment_risks']['production_exposed_tests'].append({
                                'file': str(py_file),
                                'function': func_info['name'],
                                'line': func_info['line_number']
                            })
                            
            except Exception as e:
                print(f"Error processing {py_file}: {e}")
                continue
                
        return results
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped"""
        skip_patterns = [
            '.git', '__pycache__', 'node_modules', '.pytest_cache',
            'archived/', '/build/', '/dist/'
        ]
        
        path_str = str(file_path)
        return any(pattern in path_str for pattern in skip_patterns)
    
    def _extract_whitelisted_functions(self, content: str, file_path: Path) -> List[Dict]:
        """Extract all whitelisted functions from file content"""
        functions = []
        
        # Find @frappe.whitelist() decorators
        whitelist_pattern = re.compile(r'^@frappe\.whitelist\([^)]*\)\s*\n\s*def\s+(\w+)', re.MULTILINE)
        
        for match in whitelist_pattern.finditer(content):
            start_pos = match.start()
            line_number = content[:start_pos].count('\n') + 1
            function_name = match.group(1)
            
            # Get function context (50 lines around function)
            lines = content.split('\n')
            context_start = max(0, line_number - 10)
            context_end = min(len(lines), line_number + 40)
            function_context = '\n'.join(lines[context_start:context_end])
            
            # Check for security framework usage
            has_security = self._has_security_framework(function_context)
            has_dev_only = self._has_development_only(function_context)
            
            function_info = {
                'name': function_name,
                'file': str(file_path),
                'line_number': line_number,
                'context': function_context,
                'has_security_framework': has_security,
                'has_development_only': has_dev_only,
                'is_test_debug': self._is_test_debug_function({'name': function_name, 'context': function_context}),
                'estimated_complexity': self._estimate_function_complexity(function_context)
            }
            
            functions.append(function_info)
            
        return functions
    
    def _has_security_framework(self, context: str) -> bool:
        """Check if function uses security framework"""
        for pattern in self.security_framework_patterns:
            if re.search(pattern, context, re.IGNORECASE):
                return True
        return False
    
    def _has_development_only(self, context: str) -> bool:
        """Check if function has development_only decorator"""
        return '@development_only' in context
    
    def _is_test_debug_function(self, func_info: Dict) -> bool:
        """Check if function is test/debug utility"""
        name = func_info['name'].lower()
        context = func_info.get('context', '').lower()
        
        for pattern in self.test_debug_patterns:
            if re.search(pattern, name) or re.search(pattern, context):
                return True
        return False
    
    def _categorize_function(self, func_info: Dict) -> str:
        """Categorize function by security priority"""
        if func_info['has_security_framework']:
            return 'already_secured'
        
        if func_info['is_test_debug']:
            return 'test_debug'
            
        name = func_info['name'].lower()
        context = func_info.get('context', '').lower()
        combined = name + ' ' + context
        
        # Check patterns
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in self.financial_patterns):
            return 'critical_financial'
        elif any(re.search(pattern, combined, re.IGNORECASE) for pattern in self.admin_patterns):
            return 'high_admin'
        elif any(re.search(pattern, combined, re.IGNORECASE) for pattern in self.member_data_patterns):
            return 'medium_member_data'
        else:
            return 'low_reporting'
    
    def _estimate_function_complexity(self, context: str) -> int:
        """Estimate function complexity (lines of code)"""
        return len([line for line in context.split('\n') if line.strip() and not line.strip().startswith('#')])
    
    def _assess_migration_complexity(self, func_info: Dict) -> str:
        """Assess migration complexity"""
        complexity = func_info['estimated_complexity']
        
        if complexity < 10:
            return 'simple'
        elif complexity < 30:
            return 'moderate'
        else:
            return 'complex'
    
    def generate_inventory_report(self) -> str:
        """Generate comprehensive inventory report"""
        results = self.scan_codebase()
        
        report = []
        report.append("=" * 80)
        report.append("SECURITY FRAMEWORK MIGRATION INVENTORY")
        report.append("=" * 80)
        report.append("")
        
        # Executive Summary
        total = results['total_whitelist_functions']
        secured = results['functions_with_security']
        needing_migration = results['functions_needing_migration']
        
        report.append("EXECUTIVE SUMMARY")
        report.append("-" * 40)
        report.append(f"Total Files Scanned: {results['total_files']:,}")
        report.append(f"Files with Whitelisted Functions: {results['files_with_whitelist']:,}")
        report.append(f"Total Whitelisted Functions: {total:,}")
        report.append(f"Functions Using Security Framework: {secured:,} ({secured/total*100:.1f}%)")
        report.append(f"Functions Needing Migration: {needing_migration:,} ({needing_migration/total*100:.1f}%)")
        report.append("")
        
        # Priority Categories
        categories = results['categories']
        report.append("MIGRATION PRIORITY BREAKDOWN")
        report.append("-" * 45)
        
        priorities = [
            ('🚨 CRITICAL: Financial Operations', 'critical_financial', 'Immediate migration required'),
            ('⚠️  HIGH: Administrative Functions', 'high_admin', 'Migrate within 2 weeks'),
            ('📊 MEDIUM: Member Data Operations', 'medium_member_data', 'Migrate within 1 month'),
            ('📋 LOW: Reporting/Utility Functions', 'low_reporting', 'Migrate within 3 months'),
            ('🧪 TEST: Debug/Test Utilities', 'test_debug', 'Apply @development_only immediately'),
            ('✅ SECURED: Already Protected', 'already_secured', 'No action needed')
        ]
        
        for title, key, timeline in priorities:
            count = len(categories[key])
            report.append(f"{title}: {count:,} functions")
            if key != 'already_secured' and count > 0:
                report.append(f"   Timeline: {timeline}")
            report.append("")
        
        # Migration Complexity
        complexity = results['migration_complexity']
        report.append("MIGRATION COMPLEXITY ANALYSIS")
        report.append("-" * 35)
        report.append(f"Simple (<10 lines): {complexity['simple']:,} functions")
        report.append(f"Moderate (10-30 lines): {complexity['moderate']:,} functions") 
        report.append(f"Complex (30+ lines): {complexity['complex']:,} functions")
        report.append("")
        
        # Environment Risks
        env_risks = results['environment_risks']
        report.append("🚨 CRITICAL ENVIRONMENT RISKS")
        report.append("-" * 35)
        
        exposed_tests = env_risks['production_exposed_tests']
        if exposed_tests:
            report.append(f"Production-Exposed Test Utilities: {len(exposed_tests):,}")
            report.append("IMMEDIATE ACTION REQUIRED for Frappe Cloud deployments")
            report.append("")
            
            for i, func in enumerate(exposed_tests[:10]):  # Show top 10
                report.append(f"{i+1:2d}. {func['function']}() in {func['file']}:{func['line']}")
            
            if len(exposed_tests) > 10:
                report.append(f"    ... and {len(exposed_tests) - 10} more")
            report.append("")
        
        # Sample Migration Examples
        report.append("SAMPLE MIGRATION EXAMPLES")
        report.append("-" * 30)
        report.append("")
        
        # Show examples from each category
        for category_name, functions in categories.items():
            if category_name == 'already_secured' or not functions:
                continue
                
            sample = functions[0]  # First function as example
            report.append(f"**{category_name.upper()} Example:**")
            report.append(f"File: {sample['file']}:{sample['line_number']}")
            report.append(f"Function: {sample['name']}()")
            
            # Show recommended migration
            if category_name == 'critical_financial':
                report.append("Recommended Migration:")
                report.append("```python")
                report.append("@frappe.whitelist()")
                report.append("@critical_api(operation_type=OperationType.FINANCIAL)")
                report.append(f"def {sample['name']}():")
                report.append("    # Existing function logic")
                report.append("```")
            elif category_name == 'test_debug':
                report.append("Recommended Migration:")
                report.append("```python")
                report.append("@frappe.whitelist()")
                report.append("@development_only()")
                report.append(f"def {sample['name']}():")
                report.append("    # Test/debug logic")
                report.append("```")
            
            report.append("")
        
        # Recommended Action Plan
        report.append("RECOMMENDED ACTION PLAN")
        report.append("-" * 30)
        report.append("")
        
        report.append("**Phase 1: Environment Security (Week 1)**")
        report.append(f"- Apply @development_only() to {len(exposed_tests)} test utilities")
        report.append("- Add environment controls to security framework")
        report.append("- Test Frappe Cloud deployment filtering")
        report.append("")
        
        report.append("**Phase 2: Critical Functions (Weeks 2-3)**") 
        critical_count = len(categories['critical_financial'])
        report.append(f"- Migrate {critical_count} financial operations to @critical_api")
        report.append("- Focus on payment processing, SEPA, invoicing")
        report.append("- Test rate limiting and audit logging")
        report.append("")
        
        report.append("**Phase 3: Administrative Functions (Month 2)**")
        admin_count = len(categories['high_admin']) 
        report.append(f"- Migrate {admin_count} administrative functions to @high_security_api")
        report.append("- Focus on bulk operations, member management")
        report.append("- Implement role-based access controls")
        report.append("")
        
        report.append("**Phase 4: Comprehensive Migration (Months 3-4)**")
        remaining = len(categories['medium_member_data']) + len(categories['low_reporting'])
        report.append(f"- Migrate remaining {remaining} functions")
        report.append("- Create migration tooling for bulk application")
        report.append("- Implement enforcement policies")
        report.append("")
        
        return "\n".join(report)
    
    def save_detailed_inventory(self):
        """Save detailed function inventory to JSON file"""
        results = self.scan_codebase()
        
        # Save to JSON file
        output_file = self.base_path / "scripts" / "security_migration_inventory.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        print(f"Detailed inventory saved to: {output_file}")
        return output_file


def main():
    """Generate and display security migration inventory"""
    inventory = SecurityMigrationInventory()
    
    # Generate and print report
    report = inventory.generate_inventory_report()
    print(report)
    
    # Save detailed inventory
    json_file = inventory.save_detailed_inventory()
    
    print("\n" + "="*80)
    print("INVENTORY GENERATION COMPLETE")
    print("="*80)
    print(f"Report displayed above")
    print(f"Detailed data: {json_file}")


if __name__ == "__main__":
    main()