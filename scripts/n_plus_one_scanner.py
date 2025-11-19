#!/usr/bin/env python3
"""
N+1 Query Pattern Scanner for Verenigingen Codebase

This script identifies N+1 query patterns in Python code that can cause performance issues.
It scans for common anti-patterns and provides actionable optimization suggestions.

Usage:
    python scripts/n_plus_one_scanner.py
    
Or from bench environment:
    bench --site dev.veganisme.net execute verenigingen.scripts.n_plus_one_scanner.run_scan
"""

import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
import json


@dataclass
class N1Pattern:
    """Represents a detected N+1 query pattern"""
    file_path: str
    line_number: int
    pattern_type: str
    severity: str  # 'high', 'medium', 'low'
    code_snippet: str
    description: str
    suggested_fix: str
    context: str  # surrounding function/class context


class N1QueryScanner(ast.NodeVisitor):
    """AST visitor to detect N+1 query patterns"""
    
    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_code = source_code
        self.source_lines = source_code.split('\n')
        self.patterns = []
        self.current_function = None
        self.current_class = None
        self.loop_depth = 0
        self.in_loop_contexts = []
        
        # Common Frappe query methods that can cause N+1
        self.query_methods = {
            'frappe.get_doc': 'Document fetch',
            'frappe.get_all': 'Query all records',
            'frappe.get_list': 'List query',
            'frappe.db.get_value': 'Single value fetch',
            'frappe.db.get_values': 'Multiple values fetch',
            'frappe.db.get_all': 'Database query all',
            'frappe.db.get_list': 'Database list query',
            'frappe.db.sql': 'Raw SQL query',
            'frappe.db.count': 'Count query'
        }
        
        # High-impact code locations
        self.high_impact_indicators = {
            'api_method', 'whitelist', 'report', 'scheduler', 'webhook',
            'validate', 'on_submit', 'on_cancel', 'before_save'
        }

    def visit_FunctionDef(self, node):
        prev_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev_function

    def visit_ClassDef(self, node):
        prev_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_For(self, node):
        self._enter_loop('for', node)
        self.generic_visit(node)
        self._exit_loop()

    def visit_While(self, node):
        self._enter_loop('while', node)
        self.generic_visit(node)
        self._exit_loop()

    def visit_ListComp(self, node):
        # List comprehensions can also cause N+1 patterns
        self._enter_loop('list_comp', node)
        self.generic_visit(node)
        self._exit_loop()

    def visit_Call(self, node):
        if self.loop_depth > 0:
            self._check_query_in_loop(node)
        self.generic_visit(node)

    def _enter_loop(self, loop_type: str, node):
        self.loop_depth += 1
        self.in_loop_contexts.append({
            'type': loop_type,
            'line': node.lineno,
            'queries': []
        })

    def _exit_loop(self):
        if self.loop_depth > 0:
            loop_context = self.in_loop_contexts.pop()
            self.loop_depth -= 1
            
            # Analyze queries found in this loop
            if loop_context['queries']:
                self._analyze_loop_queries(loop_context)

    def _check_query_in_loop(self, node):
        """Check if a function call is a database query within a loop"""
        call_str = self._get_call_string(node)
        
        for query_method, description in self.query_methods.items():
            if query_method in call_str:
                if self.in_loop_contexts:
                    self.in_loop_contexts[-1]['queries'].append({
                        'method': query_method,
                        'description': description,
                        'line': node.lineno,
                        'call': call_str
                    })

    def _get_call_string(self, node) -> str:
        """Convert call node to string representation"""
        try:
            if hasattr(node.func, 'attr'):
                if hasattr(node.func.value, 'attr'):
                    # frappe.db.get_value
                    return f"{ast.unparse(node.func.value)}.{node.func.attr}"
                elif hasattr(node.func.value, 'id'):
                    # frappe.get_doc
                    return f"{node.func.value.id}.{node.func.attr}"
            return ast.unparse(node.func) if hasattr(ast, 'unparse') else str(node.func)
        except:
            return "unknown_call"

    def _analyze_loop_queries(self, loop_context):
        """Analyze queries found in a loop and create N+1 patterns"""
        queries = loop_context['queries']
        
        for query in queries:
            severity = self._assess_severity(query['method'])
            pattern_type = self._get_pattern_type(query['method'], loop_context['type'])
            
            pattern = N1Pattern(
                file_path=self.file_path,
                line_number=query['line'],
                pattern_type=pattern_type,
                severity=severity,
                code_snippet=self._get_code_snippet(query['line']),
                description=f"{query['description']} inside {loop_context['type']} loop",
                suggested_fix=self._get_suggested_fix(query['method']),
                context=self._get_context()
            )
            
            self.patterns.append(pattern)

    def _assess_severity(self, method: str) -> str:
        """Assess the severity of the N+1 pattern"""
        # Check if we're in a high-impact function
        context = self._get_context().lower()
        is_high_impact = any(indicator in context for indicator in self.high_impact_indicators)
        
        # frappe.get_doc is typically the most expensive
        if 'get_doc' in method:
            return 'high' if is_high_impact else 'medium'
        
        # Raw SQL and db operations
        if any(x in method for x in ['sql', 'db.get_value', 'db.get_all']):
            return 'high' if is_high_impact else 'medium'
        
        # Other query methods
        return 'medium' if is_high_impact else 'low'

    def _get_pattern_type(self, method: str, loop_type: str) -> str:
        """Get a descriptive pattern type"""
        if 'get_doc' in method:
            return f"Document fetch in {loop_type} loop"
        elif 'get_value' in method:
            return f"Value fetch in {loop_type} loop"
        elif 'get_all' in method or 'get_list' in method:
            return f"List query in {loop_type} loop"
        elif 'sql' in method:
            return f"Raw SQL in {loop_type} loop"
        else:
            return f"Query in {loop_type} loop"

    def _get_suggested_fix(self, method: str) -> str:
        """Provide optimization suggestions"""
        if 'get_doc' in method:
            return "Consider using frappe.get_all() with fields parameter to fetch multiple records at once, then access by name"
        elif 'get_value' in method:
            return "Use frappe.db.get_all() with fields parameter to fetch all needed values in one query"
        elif 'get_all' in method or 'get_list' in method:
            return "Move query outside loop and filter results in memory, or use 'filters' parameter with IN operator"
        elif 'sql' in method:
            return "Consider using JOINs or IN clauses to fetch all data in single query"
        else:
            return "Batch the queries or move outside the loop if possible"

    def _get_code_snippet(self, line_number: int, context_lines: int = 3) -> str:
        """Extract code snippet around the line"""
        start = max(0, line_number - context_lines - 1)
        end = min(len(self.source_lines), line_number + context_lines)
        
        snippet_lines = []
        for i in range(start, end):
            marker = ">>> " if i == line_number - 1 else "    "
            snippet_lines.append(f"{marker}{i+1:4d}: {self.source_lines[i]}")
        
        return "\n".join(snippet_lines)

    def _get_context(self) -> str:
        """Get current context (class.method)"""
        parts = []
        if self.current_class:
            parts.append(self.current_class)
        if self.current_function:
            parts.append(self.current_function)
        return ".".join(parts) if parts else "global"


class N1CodebaseScanner:
    """Main scanner for the entire codebase"""
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.all_patterns = []
        self.stats = defaultdict(int)
        self.file_stats = defaultdict(list)
        
    def scan_codebase(self, exclude_tests: bool = True) -> List[N1Pattern]:
        """Scan the entire codebase for N+1 patterns"""
        print("🔍 Scanning Vereinigingen codebase for N+1 query patterns...")
        
        python_files = self._find_python_files(exclude_tests)
        total_files = len(python_files)
        
        for i, file_path in enumerate(python_files, 1):
            print(f"📁 Scanning {i}/{total_files}: {file_path.relative_to(self.base_path)}")
            patterns = self._scan_file(file_path)
            self.all_patterns.extend(patterns)
            
            if patterns:
                self.file_stats[str(file_path)] = patterns
                
        self._calculate_stats()
        return self.all_patterns
    
    def _find_python_files(self, exclude_tests: bool) -> List[Path]:
        """Find all Python files in the codebase"""
        python_files = []
        
        # Core application directories
        for pattern in ['**/*.py']:
            python_files.extend(self.base_path.glob(pattern))
        
        # Filter out unwanted files
        filtered_files = []
        for file_path in python_files:
            relative_path = str(file_path.relative_to(self.base_path))
            
            # Skip test files if requested
            if exclude_tests and ('test_' in relative_path or '/tests/' in relative_path):
                continue
                
            # Skip other non-relevant files
            if any(skip in relative_path for skip in [
                '__pycache__', '.git', 'node_modules', '.pytest_cache',
                'migrations/', 'patches/', 'setup.py', '__init__.py'
            ]):
                continue
                
            filtered_files.append(file_path)
        
        return sorted(filtered_files)
    
    def _scan_file(self, file_path: Path) -> List[N1Pattern]:
        """Scan a single file for N+1 patterns"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            # Skip empty files
            if not source_code.strip():
                return []
            
            # Parse AST
            tree = ast.parse(source_code)
            
            # Scan for patterns
            scanner = N1QueryScanner(str(file_path), source_code)
            scanner.visit(tree)
            
            return scanner.patterns
            
        except Exception as e:
            print(f"⚠️  Error scanning {file_path}: {e}")
            return []
    
    def _calculate_stats(self):
        """Calculate summary statistics"""
        for pattern in self.all_patterns:
            self.stats[f"total_{pattern.severity}"] += 1
            self.stats[f"pattern_{pattern.pattern_type}"] += 1
            self.stats["total_patterns"] += 1
            
        self.stats["files_with_issues"] = len(self.file_stats)
    
    def generate_report(self) -> str:
        """Generate a comprehensive report"""
        report = []
        report.append("=" * 80)
        report.append("🔍 N+1 QUERY PATTERN SCAN REPORT")
        report.append("=" * 80)
        report.append("")
        
        # Summary statistics
        report.append("📊 SUMMARY STATISTICS")
        report.append("-" * 40)
        report.append(f"Total patterns found: {self.stats['total_patterns']}")
        report.append(f"Files with issues: {self.stats['files_with_issues']}")
        report.append(f"High severity: {self.stats.get('total_high', 0)}")
        report.append(f"Medium severity: {self.stats.get('total_medium', 0)}")
        report.append(f"Low severity: {self.stats.get('total_low', 0)}")
        report.append("")
        
        # Group patterns by severity
        high_patterns = [p for p in self.all_patterns if p.severity == 'high']
        medium_patterns = [p for p in self.all_patterns if p.severity == 'medium']
        low_patterns = [p for p in self.all_patterns if p.severity == 'low']
        
        # High severity patterns first
        if high_patterns:
            report.append("🚨 HIGH SEVERITY PATTERNS (Fix First!)")
            report.append("=" * 50)
            for pattern in high_patterns:
                report.extend(self._format_pattern(pattern))
                report.append("")
        
        # Medium severity patterns
        if medium_patterns:
            report.append("⚠️  MEDIUM SEVERITY PATTERNS")
            report.append("=" * 50)
            for pattern in medium_patterns:
                report.extend(self._format_pattern(pattern))
                report.append("")
        
        # Low severity patterns
        if low_patterns:
            report.append("ℹ️  LOW SEVERITY PATTERNS")
            report.append("=" * 50)
            for pattern in low_patterns:
                report.extend(self._format_pattern(pattern))
                report.append("")
        
        # Files summary
        report.append("📁 FILES WITH MOST ISSUES")
        report.append("-" * 40)
        file_counts = [(file, len(patterns)) for file, patterns in self.file_stats.items()]
        file_counts.sort(key=lambda x: x[1], reverse=True)
        
        for file_path, count in file_counts[:10]:  # Top 10
            relative_path = str(Path(file_path).relative_to(self.base_path))
            report.append(f"{count:3d} issues: {relative_path}")
        
        report.append("")
        report.append("🔧 OPTIMIZATION RECOMMENDATIONS")
        report.append("-" * 40)
        report.append("1. Focus on HIGH severity patterns first")
        report.append("2. Look for patterns in API endpoints and reports")
        report.append("3. Consider implementing query caching for repeated operations")
        report.append("4. Use frappe.get_all() with specific fields instead of get_doc() in loops")
        report.append("5. Batch database operations where possible")
        report.append("6. Consider using Frappe's built-in caching mechanisms")
        
        return "\n".join(report)
    
    def _format_pattern(self, pattern: N1Pattern) -> List[str]:
        """Format a pattern for the report"""
        lines = []
        relative_path = str(Path(pattern.file_path).relative_to(self.base_path))
        
        lines.append(f"📍 {relative_path}:{pattern.line_number}")
        lines.append(f"🔧 Context: {pattern.context}")
        lines.append(f"📝 Pattern: {pattern.pattern_type}")
        lines.append(f"💡 Suggestion: {pattern.suggested_fix}")
        lines.append("")
        lines.append("Code:")
        lines.append(pattern.code_snippet)
        
        return lines
    
    def save_json_report(self, output_path: str):
        """Save detailed report as JSON for programmatic analysis"""
        data = {
            'summary': dict(self.stats),
            'patterns': [
                {
                    'file_path': str(Path(p.file_path).relative_to(self.base_path)),
                    'line_number': p.line_number,
                    'pattern_type': p.pattern_type,
                    'severity': p.severity,
                    'description': p.description,
                    'suggested_fix': p.suggested_fix,
                    'context': p.context
                }
                for p in self.all_patterns
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)


def run_scan():
    """Entry point for running the scan"""
    import frappe
    
    # Get the app path
    app_path = frappe.get_app_path('verenigingen')
    
    # Create scanner
    scanner = N1CodebaseScanner(app_path)
    
    # Scan codebase
    patterns = scanner.scan_codebase(exclude_tests=True)
    
    # Generate report
    report = scanner.generate_report()
    print(report)
    
    # Save reports
    output_dir = Path(app_path) / 'docs' / 'performance'
    output_dir.mkdir(exist_ok=True)
    
    # Text report
    with open(output_dir / 'n_plus_one_report.txt', 'w') as f:
        f.write(report)
    
    # JSON report
    scanner.save_json_report(str(output_dir / 'n_plus_one_report.json'))
    
    print(f"\n📄 Reports saved to:")
    print(f"   - {output_dir / 'n_plus_one_report.txt'}")
    print(f"   - {output_dir / 'n_plus_one_report.json'}")
    
    return patterns


if __name__ == '__main__':
    # For standalone execution
    import sys
    
    if len(sys.argv) > 1:
        app_path = sys.argv[1]
    else:
        # Default to current directory
        app_path = os.getcwd()
    
    scanner = N1CodebaseScanner(app_path)
    patterns = scanner.scan_codebase(exclude_tests=True)
    
    report = scanner.generate_report()
    print(report)
    
    # Save reports
    with open('n_plus_one_report.txt', 'w') as f:
        f.write(report)
    
    scanner.save_json_report('n_plus_one_report.json')
    
    print(f"\n📄 Reports saved to:")
    print(f"   - n_plus_one_report.txt")
    print(f"   - n_plus_one_report.json")