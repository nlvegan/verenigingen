#!/usr/bin/env python3
"""
Error Handling Pattern Analysis for Verenigingen

Analyzes error handling patterns across the codebase to identify:
1. Inconsistent exception handling
2. Missing error context and user feedback
3. Insufficient logging and debugging information
4. Silent failures and missing validation
5. Opportunities for standardized error responses

Based on patterns observed during account creation investigation where proper
error handling was critical for debugging test failures.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple


class ErrorHandlingAnalyzer:
    """Analyze error handling patterns across the codebase"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.error_patterns = self._define_error_patterns()
        
    def _define_error_patterns(self) -> Dict[str, re.Pattern]:
        """Define regex patterns for different error handling constructs"""
        return {
            'try_except': re.compile(r'try\s*:', re.MULTILINE),
            'except_bare': re.compile(r'except\s*:', re.MULTILINE),
            'except_generic': re.compile(r'except\s+Exception\s*:', re.MULTILINE),
            'except_specific': re.compile(r'except\s+\w+Error\s*:', re.MULTILINE),
            'frappe_throw': re.compile(r'frappe\.throw\(', re.MULTILINE),
            'frappe_msgprint': re.compile(r'frappe\.msgprint\(', re.MULTILINE),
            'frappe_log_error': re.compile(r'frappe\.log_error\(', re.MULTILINE),
            'pass_silently': re.compile(r'except[^:]*:\s*\n\s*pass\s*$', re.MULTILINE),
            'print_debug': re.compile(r'print\s*\(', re.MULTILINE),
            'raise_without_context': re.compile(r'^\s*raise\s*$', re.MULTILINE),
            'validation_error': re.compile(r'frappe\.ValidationError', re.MULTILINE),
            'permission_error': re.compile(r'frappe\.PermissionError', re.MULTILINE)
        }
    
    def analyze_file_error_handling(self, file_path: Path) -> Dict[str, any]:
        """Analyze error handling patterns in a single file"""
        if not file_path.exists() or not file_path.suffix == '.py':
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {'error': f"Could not read file: {e}"}
        
        analysis = {
            'file_path': str(file_path),
            'line_count': len(content.split('\n')),
            'error_patterns': {},
            'issues': [],
            'score': 0
        }
        
        # Count pattern occurrences
        for pattern_name, pattern in self.error_patterns.items():
            matches = list(pattern.finditer(content))
            analysis['error_patterns'][pattern_name] = len(matches)
            
            # Store line numbers for specific issues
            if matches:
                lines = content.split('\n')
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    line_content = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    
                    # Identify specific issues
                    if pattern_name == 'except_bare':
                        analysis['issues'].append({
                            'type': 'bare_except',
                            'line': line_num,
                            'content': line_content,
                            'severity': 'high',
                            'message': 'Bare except clause can hide errors'
                        })
                    elif pattern_name == 'pass_silently':
                        analysis['issues'].append({
                            'type': 'silent_failure',
                            'line': line_num,
                            'content': line_content,
                            'severity': 'medium',
                            'message': 'Silent exception handling may hide issues'
                        })
                    elif pattern_name == 'print_debug':
                        analysis['issues'].append({
                            'type': 'debug_print',
                            'line': line_num,
                            'content': line_content,
                            'severity': 'low',
                            'message': 'Use logging instead of print for debugging'
                        })
        
        # Calculate error handling score
        analysis['score'] = self._calculate_error_handling_score(analysis)
        
        return analysis
    
    def _calculate_error_handling_score(self, analysis: Dict) -> int:
        """Calculate error handling quality score (0-100)"""
        patterns = analysis['error_patterns']
        
        # Start with base score
        score = 50
        
        # Positive indicators
        if patterns.get('frappe_throw', 0) > 0:
            score += 10  # Good user feedback
        if patterns.get('frappe_log_error', 0) > 0:
            score += 10  # Good error logging
        if patterns.get('except_specific', 0) > 0:
            score += 15  # Specific exception handling
        if patterns.get('validation_error', 0) > 0:
            score += 5   # Proper error types
        
        # Negative indicators
        if patterns.get('except_bare', 0) > 0:
            score -= 20  # Bare except is bad
        if patterns.get('pass_silently', 0) > 0:
            score -= 15  # Silent failures are problematic
        if patterns.get('print_debug', 0) > patterns.get('frappe_log_error', 0) * 2:
            score -= 10  # Too much debug printing vs logging
        
        # Try/except ratio - good if we have proper exception handling
        try_count = patterns.get('try_except', 0)
        except_total = (patterns.get('except_bare', 0) + 
                       patterns.get('except_generic', 0) + 
                       patterns.get('except_specific', 0))
        
        if try_count > 0 and except_total == 0:
            score -= 25  # Try without except is bad
        
        return max(0, min(100, score))
    
    def analyze_codebase_error_handling(self) -> Dict[str, any]:
        """Analyze error handling patterns across the entire codebase"""
        results = {
            'total_files': 0,
            'files_analyzed': 0,
            'overall_patterns': {},
            'file_analyses': [],
            'summary': {},
            'recommendations': []
        }
        
        # Initialize pattern counters
        for pattern_name in self.error_patterns.keys():
            results['overall_patterns'][pattern_name] = 0
        
        # Analyze all Python files
        for py_file in self.base_path.rglob("*.py"):
            results['total_files'] += 1
            
            # Skip certain directories
            if any(skip_dir in str(py_file) for skip_dir in ['.git', '__pycache__', 'node_modules']):
                continue
            
            file_analysis = self.analyze_file_error_handling(py_file)
            if 'error' not in file_analysis:
                results['files_analyzed'] += 1
                results['file_analyses'].append(file_analysis)
                
                # Add to overall patterns
                for pattern_name, count in file_analysis.get('error_patterns', {}).items():
                    results['overall_patterns'][pattern_name] += count
        
        # Generate summary and recommendations
        results['summary'] = self._generate_summary(results)
        results['recommendations'] = self._generate_recommendations(results)
        
        return results
    
    def _generate_summary(self, results: Dict) -> Dict:
        """Generate summary statistics"""
        file_analyses = results['file_analyses']
        patterns = results['overall_patterns']
        
        if not file_analyses:
            return {}
        
        # Calculate statistics
        scores = [f['score'] for f in file_analyses]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Count issues by severity
        issue_counts = {'high': 0, 'medium': 0, 'low': 0}
        for analysis in file_analyses:
            for issue in analysis.get('issues', []):
                severity = issue.get('severity', 'low')
                issue_counts[severity] += 1
        
        # Identify problematic files
        low_scoring_files = [
            f for f in file_analyses 
            if f['score'] < 40
        ]
        
        return {
            'average_score': round(avg_score, 2),
            'total_issues': sum(issue_counts.values()),
            'issue_breakdown': issue_counts,
            'files_with_low_scores': len(low_scoring_files),
            'try_except_ratio': patterns.get('try_except', 0) / max(1, results['files_analyzed']),
            'bare_except_files': len([f for f in file_analyses if f['error_patterns'].get('except_bare', 0) > 0]),
            'silent_failure_files': len([f for f in file_analyses if f['error_patterns'].get('pass_silently', 0) > 0])
        }
    
    def _generate_recommendations(self, results: Dict) -> List[str]:
        """Generate actionable recommendations"""
        patterns = results['overall_patterns']
        summary = results['summary']
        recommendations = []
        
        # High priority recommendations
        if patterns.get('except_bare', 0) > 0:
            recommendations.append(
                f"🚨 HIGH PRIORITY: Replace {patterns['except_bare']} bare except clauses with specific exception types"
            )
        
        if patterns.get('pass_silently', 0) > 0:
            recommendations.append(
                f"⚠️  MEDIUM PRIORITY: Review {patterns['pass_silently']} silent exception handlers - add logging or user feedback"
            )
        
        # Logging improvements
        if patterns.get('print_debug', 0) > patterns.get('frappe_log_error', 0) * 2:
            recommendations.append(
                f"📝 Replace debug print() statements with frappe.log_error() for better debugging"
            )
        
        # Error communication
        if patterns.get('frappe_throw', 0) < patterns.get('try_except', 0) * 0.5:
            recommendations.append(
                f"💬 Consider adding more user-friendly error messages with frappe.throw()"
            )
        
        # Error handling coverage
        if summary.get('try_except_ratio', 0) < 1.0:
            recommendations.append(
                f"🛡️  Add error handling to critical operations - only {summary.get('try_except_ratio', 0):.1f} try blocks per file on average"
            )
        
        return recommendations
    
    def generate_error_handling_report(self) -> str:
        """Generate comprehensive error handling report"""
        analysis = self.analyze_codebase_error_handling()
        
        report = []
        report.append("=" * 80)
        report.append("ERROR HANDLING ANALYSIS REPORT - Verenigingen")
        report.append("=" * 80)
        report.append("")
        
        # Executive summary
        summary = analysis.get('summary', {})
        report.append("EXECUTIVE SUMMARY")
        report.append("-" * 40)
        report.append(f"Files Analyzed: {analysis['files_analyzed']}")
        report.append(f"Average Error Handling Score: {summary.get('average_score', 0)}/100")
        report.append(f"Total Issues Found: {summary.get('total_issues', 0)}")
        report.append(f"Files with Poor Error Handling: {summary.get('files_with_low_scores', 0)}")
        report.append("")
        
        # Issue breakdown
        issue_counts = summary.get('issue_breakdown', {})
        if any(issue_counts.values()):
            report.append("ISSUE SEVERITY BREAKDOWN")
            report.append("-" * 30)
            report.append(f"🚨 High Severity Issues: {issue_counts.get('high', 0)}")
            report.append(f"⚠️  Medium Severity Issues: {issue_counts.get('medium', 0)}")
            report.append(f"ℹ️  Low Severity Issues: {issue_counts.get('low', 0)}")
            report.append("")
        
        # Pattern analysis
        patterns = analysis.get('overall_patterns', {})
        report.append("ERROR HANDLING PATTERNS")
        report.append("-" * 30)
        report.append(f"Try/Except Blocks: {patterns.get('try_except', 0)}")
        report.append(f"Bare Except Clauses: {patterns.get('except_bare', 0)} ❌")
        report.append(f"Specific Exception Handling: {patterns.get('except_specific', 0)} ✅")
        report.append(f"Silent Failures: {patterns.get('pass_silently', 0)} ❌")
        report.append(f"Proper Error Logging: {patterns.get('frappe_log_error', 0)} ✅")
        report.append(f"User Error Feedback: {patterns.get('frappe_throw', 0)} ✅")
        report.append("")
        
        # Top problematic files
        low_scoring_files = [
            f for f in analysis.get('file_analyses', []) 
            if f['score'] < 40
        ][:10]
        
        if low_scoring_files:
            report.append("FILES NEEDING ATTENTION")
            report.append("-" * 30)
            for file_info in low_scoring_files:
                report.append(f"📁 {file_info['file_path']} (Score: {file_info['score']}/100)")
                high_issues = [i for i in file_info.get('issues', []) if i.get('severity') == 'high']
                if high_issues:
                    for issue in high_issues[:2]:  # Show top 2 issues
                        report.append(f"   • Line {issue['line']}: {issue['message']}")
            report.append("")
        
        # Recommendations
        recommendations = analysis.get('recommendations', [])
        if recommendations:
            report.append("RECOMMENDED ACTIONS")
            report.append("-" * 25)
            for i, rec in enumerate(recommendations, 1):
                report.append(f"{i}. {rec}")
            report.append("")
        
        # Standardized patterns
        report.append("RECOMMENDED ERROR HANDLING PATTERNS")
        report.append("-" * 45)
        report.append("")
        
        report.append("1. API Endpoint Error Handling:")
        report.append("```python")
        report.append("@frappe.whitelist()")
        report.append("def api_function():")
        report.append("    try:")
        report.append("        # Business logic")
        report.append("        result = perform_operation()")
        report.append("        return {'success': True, 'data': result}")
        report.append("    except frappe.ValidationError as e:")
        report.append("        frappe.log_error(f'Validation error in api_function: {str(e)}')")
        report.append("        frappe.throw(_(f'Invalid data: {str(e)}'), frappe.ValidationError)")
        report.append("    except Exception as e:")
        report.append("        frappe.log_error(f'Unexpected error in api_function: {str(e)}')")
        report.append("        frappe.throw(_('An unexpected error occurred. Please try again.'), frappe.ValidationError)")
        report.append("```")
        report.append("")
        
        report.append("2. Background Job Error Handling:")
        report.append("```python")
        report.append("def background_task():")
        report.append("    try:")
        report.append("        # Heavy operation")
        report.append("        process_data()")
        report.append("        return {'success': True}")
        report.append("    except SpecificBusinessError as e:")
        report.append("        # Handle specific business logic errors")
        report.append("        frappe.log_error(f'Business logic error: {str(e)}', 'Background Task')")
        report.append("        return {'success': False, 'error': str(e)}")
        report.append("    except Exception as e:")
        report.append("        # Log unexpected errors with full traceback")
        report.append("        frappe.log_error(frappe.get_traceback(), 'Background Task Critical Error')")
        report.append("        return {'success': False, 'error': 'System error occurred'}")
        report.append("```")
        report.append("")
        
        return "\n".join(report)


def main():
    analyzer = ErrorHandlingAnalyzer()
    report = analyzer.generate_error_handling_report()
    print(report)
    
    # Save detailed analysis
    analysis = analyzer.analyze_codebase_error_handling()
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/scripts/error_handling_analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print("\n" + "="*80)
    print("Detailed analysis saved to: scripts/error_handling_analysis.json")
    print("="*80)


if __name__ == "__main__":
    main()