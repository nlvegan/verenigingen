#!/usr/bin/env python3
"""
SQL Usage Categorization Script
Phase 3.1: Data Access Pattern Assessment

Analyzes all raw SQL usage across the codebase and categorizes by:
- SIMPLE: Basic SELECT queries, simple filters (migrate to ORM)
- COMPLEX: JOIN operations, aggregations (keep as SQL but improve)
- PERFORMANCE_CRITICAL: Batch operations, large datasets (keep as SQL, optimize)
- UNSAFE: Dynamic queries, user input (migrate immediately)
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime


class SQLUsageAnalyzer:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.sql_patterns = {
            'unsafe': [
                r'frappe\.db\.sql\([^"\']*f["\']',  # f-string interpolation
                r'frappe\.db\.sql\([^"\']*%.*format',  # string formatting
                r'frappe\.db\.sql\([^"\']*\+',  # string concatenation
                r'\.format\([^)]*\).*frappe\.db\.sql',  # format then sql
            ],
            'complex': [
                r'JOIN\s+',  # JOIN operations
                r'LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|OUTER\s+JOIN',  # Specific joins
                r'GROUP\s+BY',  # Aggregations
                r'HAVING\s+',  # Having clauses
                r'UNION\s+',  # Union operations
                r'CASE\s+WHEN',  # Case statements
                r'WITH\s+.*AS',  # CTEs
                r'ROW_NUMBER\(\)|RANK\(\)',  # Window functions
            ],
            'performance_critical': [
                r'LIMIT\s+\d{3,}',  # Large limits (100+)
                r'COUNT\(\*\).*FROM.*WHERE',  # Count operations
                r'INSERT\s+INTO.*VALUES.*\(',  # Batch inserts
                r'UPDATE.*SET.*WHERE.*IN\s*\(',  # Batch updates
                r'DELETE.*WHERE.*IN\s*\(',  # Batch deletes
            ],
            'simple': [
                r'SELECT.*FROM.*WHERE.*=\s*%s',  # Simple parameterized selects
                r'SELECT.*FROM.*tabMember.*WHERE',  # Basic member queries
                r'SELECT.*FROM.*ORDER\s+BY',  # Simple ordering
                r'INSERT\s+INTO.*VALUES\s*\(',  # Single inserts
            ]
        }
        
        self.results = {
            'unsafe': [],
            'complex': [],
            'performance_critical': [],
            'simple': [],
            'uncategorized': []
        }
        
        self.migration_strategies = {
            'unsafe': 'IMMEDIATE_MIGRATION_REQUIRED',
            'complex': 'SECURE_WITH_PARAMETERS',
            'performance_critical': 'OPTIMIZE_AND_SECURE',
            'simple': 'MIGRATE_TO_ORM'
        }

    def analyze_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Analyze SQL usage in a single file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return []

        sql_calls = []
        
        # Find all frappe.db.sql calls
        sql_pattern = r'frappe\.db\.sql\s*\([^)]*\)'
        matches = re.finditer(sql_pattern, content, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            sql_call = match.group(0)
            line_number = content[:match.start()].count('\n') + 1
            
            # Get surrounding context
            lines = content.split('\n')
            start_line = max(0, line_number - 3)
            end_line = min(len(lines), line_number + 3)
            context = '\n'.join(lines[start_line:end_line])
            
            # Categorize the SQL call
            category = self.categorize_sql_call(sql_call, context)
            
            sql_info = {
                'file': str(file_path.relative_to(self.base_path)),
                'line': line_number,
                'sql_call': sql_call,
                'context': context,
                'category': category,
                'migration_strategy': self.migration_strategies.get(category, 'REVIEW_REQUIRED')
            }
            
            sql_calls.append(sql_info)
            
        return sql_calls

    def categorize_sql_call(self, sql_call: str, context: str) -> str:
        """Categorize a SQL call based on patterns"""
        full_text = sql_call + ' ' + context
        
        # Check for unsafe patterns first (highest priority)
        for pattern in self.sql_patterns['unsafe']:
            if re.search(pattern, full_text, re.IGNORECASE):
                return 'unsafe'
        
        # Check for complex patterns
        for pattern in self.sql_patterns['complex']:
            if re.search(pattern, full_text, re.IGNORECASE):
                return 'complex'
        
        # Check for performance critical patterns
        for pattern in self.sql_patterns['performance_critical']:
            if re.search(pattern, full_text, re.IGNORECASE):
                return 'performance_critical'
        
        # Check for simple patterns
        for pattern in self.sql_patterns['simple']:
            if re.search(pattern, full_text, re.IGNORECASE):
                return 'simple'
        
        return 'uncategorized'

    def analyze_codebase(self) -> Dict[str, Any]:
        """Analyze entire codebase for SQL usage"""
        python_files = list(self.base_path.rglob('*.py'))
        
        total_files = 0
        files_with_sql = 0
        
        for file_path in python_files:
            # Skip test files and archived files for now
            if '/test' in str(file_path) or '/archived' in str(file_path):
                continue
                
            total_files += 1
            sql_calls = self.analyze_file(file_path)
            
            if sql_calls:
                files_with_sql += 1
                for sql_info in sql_calls:
                    category = sql_info['category']
                    if category in self.results:
                        self.results[category].append(sql_info)
                    else:
                        self.results['uncategorized'].append(sql_info)

        # Generate summary statistics
        summary = {
            'analysis_date': datetime.now().isoformat(),
            'total_files_analyzed': total_files,
            'files_with_sql': files_with_sql,
            'total_sql_calls': sum(len(calls) for calls in self.results.values()),
            'categorized_counts': {
                category: len(calls) for category, calls in self.results.items()
            },
            'migration_priorities': {
                '1_CRITICAL_UNSAFE': len(self.results['unsafe']),
                '2_HIGH_SIMPLE': len(self.results['simple']),
                '3_MEDIUM_COMPLEX': len(self.results['complex']),
                '4_LOW_PERFORMANCE': len(self.results['performance_critical']),
                '5_REVIEW_UNCAT': len(self.results['uncategorized'])
            }
        }
        
        return {
            'summary': summary,
            'detailed_results': self.results
        }

    def generate_migration_plan(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate specific migration plan based on analysis"""
        migration_plan = {
            'phase_3_2_priority_1_unsafe': {
                'description': 'IMMEDIATE: Migrate unsafe SQL queries with user input',
                'count': len(self.results['unsafe']),
                'estimated_effort_hours': len(self.results['unsafe']) * 2,  # 2 hours per unsafe query
                'files': list(set(sql['file'] for sql in self.results['unsafe'])),
                'specific_queries': self.results['unsafe'][:10]  # Top 10 for review
            },
            'phase_3_2_priority_2_simple': {
                'description': 'HIGH: Migrate simple SQL queries to Frappe ORM',
                'count': len(self.results['simple']),
                'estimated_effort_hours': len(self.results['simple']) * 0.5,  # 30 min per simple query
                'files': list(set(sql['file'] for sql in self.results['simple'])),
                'specific_queries': self.results['simple'][:10]
            },
            'phase_3_2_secure_complex': {
                'description': 'MEDIUM: Secure complex SQL with parameterized queries',
                'count': len(self.results['complex']),
                'estimated_effort_hours': len(self.results['complex']) * 1,  # 1 hour per complex query
                'files': list(set(sql['file'] for sql in self.results['complex'])),
                'specific_queries': self.results['complex'][:10]
            },
            'phase_3_2_optimize_performance': {
                'description': 'LOW: Optimize performance-critical SQL',
                'count': len(self.results['performance_critical']),
                'estimated_effort_hours': len(self.results['performance_critical']) * 1.5,  # 1.5 hours per perf query
                'files': list(set(sql['file'] for sql in self.results['performance_critical'])),
                'specific_queries': self.results['performance_critical'][:10]
            },
            'total_estimated_effort': (
                len(self.results['unsafe']) * 2 +
                len(self.results['simple']) * 0.5 +
                len(self.results['complex']) * 1 +
                len(self.results['performance_critical']) * 1.5
            )
        }
        
        return migration_plan

    def save_results(self, results: Dict[str, Any], output_path: Path):
        """Save analysis results to JSON file"""
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)


def main():
    """Main execution function"""
    base_path = Path('/home/frappe/frappe-bench/apps/verenigingen')
    analyzer = SQLUsageAnalyzer(str(base_path))
    
    print("🔍 Starting SQL Usage Analysis for Phase 3.1...")
    print(f"📁 Analyzing codebase at: {base_path}")
    
    # Perform analysis
    analysis_results = analyzer.analyze_codebase()
    
    # Generate migration plan
    migration_plan = analyzer.generate_migration_plan(analysis_results)
    
    # Combine results
    complete_results = {
        'analysis_results': analysis_results,
        'migration_plan': migration_plan
    }
    
    # Save results
    output_path = base_path / 'docs' / 'architecture' / 'sql_usage_analysis_phase3.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    analyzer.save_results(complete_results, output_path)
    
    # Print summary
    summary = analysis_results['summary']
    print(f"\n📊 SQL Usage Analysis Complete!")
    print(f"📄 Total files analyzed: {summary['total_files_analyzed']}")
    print(f"🔍 Files with SQL: {summary['files_with_sql']}")
    print(f"⚡ Total SQL calls found: {summary['total_sql_calls']}")
    print(f"\n🚨 Priority Breakdown:")
    for priority, count in summary['migration_priorities'].items():
        print(f"   {priority}: {count} queries")
    
    print(f"\n⏱️  Estimated Migration Effort: {migration_plan['total_estimated_effort']:.1f} hours")
    print(f"💾 Detailed results saved to: {output_path}")
    
    return complete_results


if __name__ == "__main__":
    main()