"""
Member DocType Performance Analysis Tool

This script provides comprehensive analysis of query patterns during Member creation
to identify specific optimization opportunities without compromising business logic.
"""

import frappe
from frappe.utils import now_datetime
import time


class MemberPerformanceAnalyzer:
    """Analyze Member DocType query patterns and performance bottlenecks."""
    
    def __init__(self):
        self.query_log = []
        self.timing_data = {}
    
    def analyze_member_creation(self, test_data=None):
        """Comprehensive analysis of Member creation performance."""
        
        if not test_data:
            test_data = self._get_test_member_data()
        
        # Start query logging
        frappe.db.sql("SET SESSION query_cache_type = OFF")  # Disable query cache
        
        start_time = time.time()
        
        with frappe.query_log_context():
            try:
                # Create member with full validation
                member_doc = frappe.new_doc("Member")
                
                # Set test data
                for field, value in test_data.items():
                    member_doc.set(field, value)
                
                # Track validation time
                validate_start = time.time()
                member_doc.validate()
                self.timing_data['validation_time'] = time.time() - validate_start
                
                # Track save time  
                save_start = time.time()
                member_doc.insert()
                self.timing_data['save_time'] = time.time() - save_start
                
                # Capture query log
                self.query_log = frappe.get_query_log()
                
                # Clean up
                member_doc.delete()
                
            except Exception as e:
                frappe.log_error(f"Member creation analysis failed: {str(e)}")
                raise
        
        self.timing_data['total_time'] = time.time() - start_time
        
        return self._generate_analysis_report()
    
    def _get_test_member_data(self):
        """Generate realistic test data for Member creation."""
        return {
            'first_name': 'Test',
            'last_name': 'Analyzer',
            'email': f'test.analyzer.{frappe.utils.random_string(8)}@example.com',
            'birth_date': '1990-01-01',
            'payment_method': 'Bank Transfer',
            'application_status': 'Approved'
        }
    
    def _generate_analysis_report(self):
        """Generate comprehensive performance analysis report."""
        
        # Categorize queries
        query_categories = self._categorize_queries()
        
        # Identify patterns
        patterns = self._identify_query_patterns()
        
        # Generate recommendations
        recommendations = self._generate_recommendations(query_categories, patterns)
        
        report = {
            'summary': {
                'total_queries': len(self.query_log),
                'total_time': self.timing_data['total_time'],
                'validation_time': self.timing_data.get('validation_time', 0),
                'save_time': self.timing_data.get('save_time', 0),
                'queries_per_second': len(self.query_log) / max(self.timing_data['total_time'], 0.001)
            },
            'query_categories': query_categories,
            'patterns': patterns,
            'recommendations': recommendations,
            'detailed_queries': self.query_log[:50]  # First 50 queries for inspection
        }
        
        return report
    
    def _categorize_queries(self):
        """Categorize queries by type and purpose."""
        categories = {
            'metadata_queries': [],
            'validation_queries': [],
            'link_field_queries': [],
            'permission_queries': [],
            'insert_queries': [],
            'update_queries': [],
            'other_queries': []
        }
        
        for query in self.query_log:
            query_lower = query.lower()
            
            if 'information_schema' in query_lower or 'show' in query_lower:
                categories['metadata_queries'].append(query)
            elif 'select' in query_lower and ('count' in query_lower or 'exists' in query_lower):
                categories['validation_queries'].append(query)
            elif 'select' in query_lower and any(table in query_lower for table in ['tab', 'link']):
                categories['link_field_queries'].append(query)
            elif 'has_permission' in query_lower or 'role' in query_lower:
                categories['permission_queries'].append(query)
            elif 'insert' in query_lower:
                categories['insert_queries'].append(query)
            elif 'update' in query_lower:
                categories['update_queries'].append(query)
            else:
                categories['other_queries'].append(query)
        
        return {k: len(v) for k, v in categories.items()}
    
    def _identify_query_patterns(self):
        """Identify problematic query patterns."""
        patterns = {
            'n_plus_one': 0,
            'redundant_existence_checks': 0,
            'metadata_overhead': 0,
            'permission_overhead': 0
        }
        
        # Look for N+1 patterns (similar queries with different parameters)
        query_templates = {}
        for query in self.query_log:
            # Normalize query by removing specific values
            template = self._normalize_query_template(query)
            if template not in query_templates:
                query_templates[template] = 0
            query_templates[template] += 1
        
        # Count potential N+1 issues
        patterns['n_plus_one'] = sum(1 for count in query_templates.values() if count > 3)
        
        # Count metadata queries
        patterns['metadata_overhead'] = len([q for q in self.query_log 
                                           if 'information_schema' in q.lower() or 'show' in q.lower()])
        
        return patterns
    
    def _normalize_query_template(self, query):
        """Normalize a query to identify templates (remove specific values)."""
        import re
        
        # Remove string literals
        normalized = re.sub(r"'[^']*'", "'?'", query)
        
        # Remove numeric literals
        normalized = re.sub(r'\b\d+\b', '?', normalized)
        
        # Remove common patterns
        normalized = re.sub(r'= \?', '= ?', normalized)
        normalized = re.sub(r'IN \([^)]*\)', 'IN (?)', normalized)
        
        return normalized.strip()
    
    def _generate_recommendations(self, categories, patterns):
        """Generate specific optimization recommendations."""
        recommendations = []
        
        if categories['metadata_queries'] > 20:
            recommendations.append({
                'priority': 'high',
                'type': 'caching',
                'description': 'Implement DocType metadata caching to reduce information_schema queries',
                'potential_impact': f"Could reduce {categories['metadata_queries']} queries"
            })
        
        if categories['validation_queries'] > 15:
            recommendations.append({
                'priority': 'medium',
                'type': 'batching',
                'description': 'Batch validation queries using UNION or subqueries',
                'potential_impact': f"Could reduce {categories['validation_queries']} queries by 60-80%"
            })
        
        if patterns['n_plus_one'] > 5:
            recommendations.append({
                'priority': 'high',
                'type': 'prefetching',
                'description': 'Implement selective prefetching for repeated queries',
                'potential_impact': f"Could eliminate {patterns['n_plus_one']} N+1 query patterns"
            })
        
        if categories['link_field_queries'] > 25:
            recommendations.append({
                'priority': 'low',
                'type': 'lazy_loading',
                'description': 'Consider lazy loading for non-critical Link fields',
                'potential_impact': f"Could defer {categories['link_field_queries']} queries"
            })
        
        return recommendations


# Utility function for easy execution
@frappe.whitelist()
def analyze_member_performance():
    """API endpoint for Member performance analysis."""
    analyzer = MemberPerformanceAnalyzer()
    return analyzer.analyze_member_creation()


if __name__ == "__main__":
    # Command line execution
    analyzer = MemberPerformanceAnalyzer()
    report = analyzer.analyze_member_creation()
    
    print("=== Member DocType Performance Analysis ===")
    print(f"Total Queries: {report['summary']['total_queries']}")
    print(f"Total Time: {report['summary']['total_time']:.3f}s")
    print(f"Queries/Second: {report['summary']['queries_per_second']:.1f}")
    
    print("\nQuery Categories:")
    for category, count in report['query_categories'].items():
        print(f"  {category}: {count}")
    
    print("\nRecommendations:")
    for rec in report['recommendations']:
        print(f"  [{rec['priority'].upper()}] {rec['description']}")
        print(f"    Impact: {rec['potential_impact']}")