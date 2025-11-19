#!/usr/bin/env python3
"""
Code Organization Analyzer

Analyzes test/debug functions mixed with production code and recommends
proper code organization before applying security decorators.

Identifies:
1. Files with mixed test/production functions
2. Test functions in production modules
3. Recommended file relocations
4. Safe vs unsafe functions to secure in place

Usage: python scripts/code_organization_analyzer.py
"""

import os
import re
import ast
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict


class CodeOrganizationAnalyzer:
    """Analyze and recommend code organization improvements"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        
        # Patterns for identifying test/debug functions
        self.test_patterns = [
            r'^test_',
            r'^debug_',
            r'^create_test',
            r'^cleanup_test',
            r'_test_',
            r'testing_',
            r'_debug$',
            r'mock_',
            r'simulate_'
        ]
        
        # Production module indicators
        self.production_indicators = [
            'doctype', 'api', 'utils', 'templates', 'web_form',
            'report', 'doctype', 'page', 'www'
        ]
        
        # Test module indicators  
        self.test_indicators = [
            'test', 'debug', 'testing', 'fixture', 'mock'
        ]
        
    def analyze_codebase_organization(self) -> Dict[str, any]:
        """Comprehensive analysis of code organization issues"""
        results = {
            'mixed_files': [],           # Files with both test and production functions
            'misplaced_test_functions': [], # Test functions in production modules
            'production_in_test_files': [], # Production functions in test modules
            'organization_recommendations': {},
            'safe_to_secure_in_place': [], # Functions safe to add @development_only
            'require_relocation': [],    # Functions that should be moved
            'summary_stats': {}
        }
        
        for py_file in self.base_path.rglob("*.py"):
            if not py_file.exists() or self._should_skip_file(py_file):
                continue
                
            try:
                analysis = self._analyze_file_organization(py_file)
                if analysis['has_issues']:
                    self._categorize_file_issues(analysis, results)
                    
            except Exception as e:
                print(f"Error analyzing {py_file}: {e}")
                continue
        
        # Generate recommendations
        results['organization_recommendations'] = self._generate_organization_recommendations(results)
        results['summary_stats'] = self._calculate_summary_stats(results)
        
        return results
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Skip non-relevant files"""
        skip_patterns = ['.git', '__pycache__', 'node_modules', '.pytest_cache']
        path_str = str(file_path)
        return any(pattern in path_str for pattern in skip_patterns)
    
    def _analyze_file_organization(self, file_path: Path) -> Dict[str, any]:
        """Analyze organization of a single file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST to get function definitions
            tree = ast.parse(content)
            
            functions = []
            whitelisted_functions = []
            
            # Extract all function definitions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_info = {
                        'name': node.name,
                        'line_number': node.lineno,
                        'is_test_debug': self._is_test_debug_function(node.name),
                        'is_whitelisted': self._is_function_whitelisted(content, node.name, node.lineno),
                        'has_decorators': len(node.decorator_list) > 0,
                        'estimated_complexity': self._estimate_ast_complexity(node)
                    }
                    
                    functions.append(func_info)
                    
                    if func_info['is_whitelisted']:
                        whitelisted_functions.append(func_info)
            
            # Analyze file type
            file_type = self._classify_file_type(file_path)
            
            # Check for mixed content
            test_functions = [f for f in functions if f['is_test_debug']]
            production_functions = [f for f in functions if not f['is_test_debug']]
            
            has_mixed_content = len(test_functions) > 0 and len(production_functions) > 0
            
            analysis = {
                'file_path': str(file_path),
                'file_type': file_type,
                'total_functions': len(functions),
                'test_functions': test_functions,
                'production_functions': production_functions,
                'whitelisted_functions': whitelisted_functions,
                'has_mixed_content': has_mixed_content,
                'has_issues': self._has_organization_issues(file_type, test_functions, production_functions),
                'relative_path': str(file_path.relative_to(self.base_path))
            }
            
            return analysis
            
        except Exception as e:
            return {
                'file_path': str(file_path),
                'error': str(e),
                'has_issues': False
            }
    
    def _is_test_debug_function(self, function_name: str) -> bool:
        """Check if function name indicates test/debug purpose"""
        name_lower = function_name.lower()
        return any(re.search(pattern, name_lower) for pattern in self.test_patterns)
    
    def _is_function_whitelisted(self, content: str, function_name: str, line_number: int) -> bool:
        """Check if function has @frappe.whitelist() decorator"""
        lines = content.split('\n')
        
        # Check a few lines before the function definition
        start_line = max(0, line_number - 5)
        context_lines = lines[start_line:line_number + 2]
        context = '\n'.join(context_lines)
        
        return '@frappe.whitelist' in context
    
    def _estimate_ast_complexity(self, node: ast.FunctionDef) -> int:
        """Estimate function complexity from AST"""
        complexity_score = 1  # Base complexity
        
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For)):
                complexity_score += 1
            elif isinstance(child, ast.Try):
                complexity_score += 1
            elif isinstance(child, (ast.And, ast.Or)):
                complexity_score += 1
                
        return complexity_score
    
    def _classify_file_type(self, file_path: Path) -> str:
        """Classify file as production, test, or mixed based on path"""
        path_parts = file_path.parts
        path_str = str(file_path).lower()
        
        # Check path indicators
        if any(indicator in path_str for indicator in self.test_indicators):
            return 'test_module'
        elif any(indicator in path_str for indicator in self.production_indicators):
            return 'production_module'
        else:
            return 'unclear_module'
    
    def _has_organization_issues(self, file_type: str, test_functions: List, production_functions: List) -> bool:
        """Determine if file has organization issues"""
        if file_type == 'production_module' and len(test_functions) > 0:
            return True  # Test functions in production module
        elif file_type == 'test_module' and len(production_functions) > 0:
            return True  # Production functions in test module
        elif len(test_functions) > 0 and len(production_functions) > 0:
            return True  # Mixed content
        
        return False
    
    def _categorize_file_issues(self, analysis: Dict, results: Dict):
        """Categorize file issues into appropriate result buckets"""
        file_path = analysis['file_path']
        file_type = analysis['file_type']
        
        if analysis['has_mixed_content']:
            results['mixed_files'].append({
                'file': file_path,
                'file_type': file_type,
                'test_functions': len(analysis['test_functions']),
                'production_functions': len(analysis['production_functions']),
                'whitelisted_test_functions': [
                    f for f in analysis['test_functions'] if f['is_whitelisted']
                ],
                'whitelisted_production_functions': [
                    f for f in analysis['production_functions'] if f['is_whitelisted']
                ]
            })
        
        # Test functions in production modules
        if file_type == 'production_module':
            for test_func in analysis['test_functions']:
                if test_func['is_whitelisted']:
                    results['misplaced_test_functions'].append({
                        'function': test_func['name'],
                        'file': file_path,
                        'line': test_func['line_number'],
                        'complexity': test_func['estimated_complexity'],
                        'recommendation': self._recommend_test_function_action(test_func, analysis)
                    })
        
        # Production functions in test modules
        if file_type == 'test_module':
            for prod_func in analysis['production_functions']:
                if prod_func['is_whitelisted']:
                    results['production_in_test_files'].append({
                        'function': prod_func['name'],
                        'file': file_path,
                        'line': prod_func['line_number'],
                        'complexity': prod_func['estimated_complexity'],
                        'recommendation': 'move_to_production_module'
                    })
    
    def _recommend_test_function_action(self, test_func: Dict, file_analysis: Dict) -> str:
        """Recommend action for test function in production file"""
        # Simple test utilities can be secured in place
        if test_func['estimated_complexity'] <= 3:
            return 'secure_in_place'
        
        # Complex test functions should be moved
        if test_func['estimated_complexity'] > 10:
            return 'move_to_test_module'
        
        # Medium complexity - depends on file context
        production_func_count = len(file_analysis['production_functions'])
        if production_func_count > 10:  # Heavily production-focused file
            return 'move_to_test_module'
        else:
            return 'secure_in_place'
    
    def _generate_organization_recommendations(self, results: Dict) -> Dict[str, List[str]]:
        """Generate actionable organization recommendations"""
        recommendations = {
            'immediate_actions': [],
            'structural_improvements': [],
            'best_practices': []
        }
        
        # Immediate actions
        misplaced_count = len(results['misplaced_test_functions'])
        if misplaced_count > 0:
            recommendations['immediate_actions'].append(
                f"Secure {misplaced_count} test functions in production modules with @development_only()"
            )
        
        # Structural improvements
        mixed_files_count = len(results['mixed_files'])
        if mixed_files_count > 0:
            recommendations['structural_improvements'].append(
                f"Refactor {mixed_files_count} files with mixed test/production code"
            )
            
            # Specific file recommendations
            for mixed_file in results['mixed_files'][:5]:  # Top 5 examples
                test_count = mixed_file['test_functions']
                prod_count = mixed_file['production_functions']
                
                if test_count <= 3 and prod_count > 10:
                    recommendations['structural_improvements'].append(
                        f"Consider moving {test_count} test functions from {mixed_file['file']}"
                    )
                elif test_count > 10 and prod_count <= 3:
                    recommendations['structural_improvements'].append(
                        f"Consider moving {prod_count} production functions from {mixed_file['file']}"
                    )
        
        # Best practices
        recommendations['best_practices'].extend([
            "Establish clear separation: /tests/ for test utilities, /api/ for production APIs",
            "Use @development_only() for simple debug functions that must stay in production files",
            "Create dedicated test_*.py files for complex test suites",
            "Consider /utils/debug/ directory for development utilities"
        ])
        
        return recommendations
    
    def _calculate_summary_stats(self, results: Dict) -> Dict[str, int]:
        """Calculate summary statistics"""
        return {
            'total_mixed_files': len(results['mixed_files']),
            'total_misplaced_test_functions': len(results['misplaced_test_functions']),
            'functions_safe_to_secure': len([
                f for f in results['misplaced_test_functions'] 
                if f['recommendation'] == 'secure_in_place'
            ]),
            'functions_requiring_relocation': len([
                f for f in results['misplaced_test_functions'] 
                if f['recommendation'] == 'move_to_test_module'
            ]),
            'production_functions_in_test_files': len(results['production_in_test_files'])
        }
    
    def generate_organization_report(self) -> str:
        """Generate comprehensive code organization report"""
        analysis = self.analyze_codebase_organization()
        
        report = []
        report.append("=" * 80)
        report.append("CODE ORGANIZATION ANALYSIS")
        report.append("=" * 80)
        report.append("")
        
        # Summary
        stats = analysis['summary_stats']
        report.append("ORGANIZATION ISSUES SUMMARY")
        report.append("-" * 35)
        report.append(f"Files with Mixed Content: {stats['total_mixed_files']}")
        report.append(f"Test Functions in Production Files: {stats['total_misplaced_test_functions']}")
        report.append(f"Production Functions in Test Files: {stats['production_functions_in_test_files']}")
        report.append("")
        report.append(f"Safe to Secure In-Place: {stats['functions_safe_to_secure']}")
        report.append(f"Require Relocation: {stats['functions_requiring_relocation']}")
        report.append("")
        
        # Mixed Files Detail
        if analysis['mixed_files']:
            report.append("FILES WITH MIXED CONTENT")
            report.append("-" * 30)
            
            for mixed_file in analysis['mixed_files'][:10]:  # Top 10
                report.append(f"📁 {mixed_file['file']}")
                report.append(f"   Type: {mixed_file['file_type']}")
                report.append(f"   Test functions: {mixed_file['test_functions']}")
                report.append(f"   Production functions: {mixed_file['production_functions']}")
                
                # Show whitelisted test functions (security risk)
                whitelisted_tests = mixed_file['whitelisted_test_functions']
                if whitelisted_tests:
                    report.append(f"   🚨 Exposed test functions: {len(whitelisted_tests)}")
                    for test_func in whitelisted_tests[:3]:
                        report.append(f"      - {test_func['name']}()")
                
                report.append("")
        
        # Specific Function Recommendations
        if analysis['misplaced_test_functions']:
            report.append("MISPLACED TEST FUNCTIONS")
            report.append("-" * 30)
            
            # Group by recommendation
            by_recommendation = defaultdict(list)
            for func in analysis['misplaced_test_functions']:
                by_recommendation[func['recommendation']].append(func)
            
            for recommendation, functions in by_recommendation.items():
                report.append(f"\n**{recommendation.upper().replace('_', ' ')}** ({len(functions)} functions):")
                
                for func in functions[:5]:  # Top 5 examples
                    file_name = Path(func['file']).name
                    report.append(f"  • {func['function']}() in {file_name}:{func['line']}")
                    
                if len(functions) > 5:
                    report.append(f"    ... and {len(functions) - 5} more")
                report.append("")
        
        # Recommendations
        recs = analysis['organization_recommendations']
        report.append("RECOMMENDED ACTIONS")
        report.append("-" * 25)
        
        if recs['immediate_actions']:
            report.append("\n**IMMEDIATE (This Week):**")
            for action in recs['immediate_actions']:
                report.append(f"• {action}")
        
        if recs['structural_improvements']:
            report.append("\n**STRUCTURAL IMPROVEMENTS (Next Month):**")
            for improvement in recs['structural_improvements']:
                report.append(f"• {improvement}")
        
        if recs['best_practices']:
            report.append("\n**BEST PRACTICES:**")
            for practice in recs['best_practices']:
                report.append(f"• {practice}")
        
        report.append("")
        
        # Implementation Strategy
        report.append("IMPLEMENTATION STRATEGY")
        report.append("-" * 30)
        report.append("")
        
        safe_count = stats['functions_safe_to_secure']
        relocate_count = stats['functions_requiring_relocation']
        
        report.append(f"**Phase 1: Secure Safe Functions ({safe_count} functions)**")
        report.append("Apply @development_only() to simple test functions in production files")
        report.append("• Low complexity functions (≤3 complexity score)")
        report.append("• Clear test/debug purpose from function name")
        report.append("• Minimal risk of breaking production functionality")
        report.append("")
        
        report.append(f"**Phase 2: Relocate Complex Functions ({relocate_count} functions)**")
        report.append("Move complex test functions to appropriate test modules")
        report.append("• High complexity functions (>10 complexity score)")
        report.append("• Functions with extensive test logic")
        report.append("• Functions that don't belong in production modules")
        report.append("")
        
        report.append("**Phase 3: Refactor Mixed Files**")
        report.append("Establish clear separation between test and production code")
        report.append("• Create dedicated test modules")
        report.append("• Extract test utilities to /tests/ directory")
        report.append("• Update imports and references")
        report.append("")
        
        return "\n".join(report)


def main():
    """Generate code organization analysis"""
    analyzer = CodeOrganizationAnalyzer()
    
    print("Analyzing code organization...")
    report = analyzer.generate_organization_report()
    print(report)


if __name__ == "__main__":
    main()