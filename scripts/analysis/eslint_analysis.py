#!/usr/bin/env python3
"""
ESLint Analysis Script for Verenigingen JavaScript Codebase
Analyzes JavaScript code quality and generates comprehensive reports
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict, Counter
import datetime

class ESLintAnalyzer:
    def __init__(self, base_path=None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.parent.parent
        self.results = {
            'summary': {},
            'files_analyzed': [],
            'errors_by_rule': defaultdict(int),
            'errors_by_file': defaultdict(list),
            'warnings_by_rule': defaultdict(int),
            'security_issues': [],
            'frappe_specific_issues': [],
            'recommendations': []
        }
        
    def run_eslint_analysis(self, fix_issues=False):
        """Run ESLint analysis on the codebase"""
        print("🔍 Running ESLint analysis on JavaScript codebase...")
        
        # Ensure we're in the right directory
        os.chdir(self.base_path)
        
        # Build ESLint command
        cmd = [
            'npx', 'eslint',
            'verenigingen',
            '--ext', '.js',
            '--format', 'json'
        ]
        
        if fix_issues:
            cmd.append('--fix')
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            # ESLint returns non-zero exit code when issues are found
            if result.returncode != 0 and result.returncode != 1:
                print(f"❌ ESLint failed with exit code {result.returncode}")
                print(f"Error: {result.stderr}")
                return False
                
            # Parse JSON output
            if result.stdout.strip():
                eslint_results = json.loads(result.stdout)
                self._process_eslint_results(eslint_results)
            else:
                print("✅ No ESLint output - either no issues or no files processed")
                
            return True
            
        except subprocess.TimeoutExpired:
            print("⏰ ESLint analysis timed out after 5 minutes")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse ESLint JSON output: {e}")
            print(f"Raw output: {result.stdout[:500]}...")
            return False
        except Exception as e:
            print(f"❌ Error running ESLint: {e}")
            return False
            
    def _process_eslint_results(self, eslint_results):
        """Process ESLint results and categorize issues"""
        total_errors = 0
        total_warnings = 0
        
        for file_result in eslint_results:
            file_path = file_result['filePath']
            messages = file_result['messages']
            
            if messages:
                self.results['files_analyzed'].append({
                    'path': file_path,
                    'error_count': file_result.get('errorCount', 0),
                    'warning_count': file_result.get('warningCount', 0),
                    'fixable_error_count': file_result.get('fixableErrorCount', 0),
                    'fixable_warning_count': file_result.get('fixableWarningCount', 0)
                })
                
            for message in messages:
                rule_id = message.get('ruleId', 'unknown')
                severity = message.get('severity', 1)  # 1 = warning, 2 = error
                
                if severity == 2:
                    total_errors += 1
                    self.results['errors_by_rule'][rule_id] += 1
                else:
                    total_warnings += 1
                    self.results['warnings_by_rule'][rule_id] += 1
                    
                self.results['errors_by_file'][file_path].append({
                    'rule': rule_id,
                    'severity': 'error' if severity == 2 else 'warning',
                    'message': message.get('message', ''),
                    'line': message.get('line', 0),
                    'column': message.get('column', 0)
                })
                
                # Categorize security and Frappe-specific issues
                if rule_id and 'security' in rule_id:
                    self.results['security_issues'].append({
                        'file': file_path,
                        'rule': rule_id,
                        'message': message.get('message', ''),
                        'line': message.get('line', 0)
                    })
                elif rule_id and 'frappe' in rule_id:
                    self.results['frappe_specific_issues'].append({
                        'file': file_path,
                        'rule': rule_id,
                        'message': message.get('message', ''),
                        'line': message.get('line', 0)
                    })
                    
        self.results['summary'] = {
            'total_files_analyzed': len([f for f in eslint_results if f['messages']]),
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'files_with_issues': len(self.results['errors_by_file']),
            'analysis_date': datetime.datetime.now().isoformat()
        }
        
    def generate_recommendations(self):
        """Generate recommendations based on analysis results"""
        recommendations = []
        
        # Top error rules
        top_errors = sorted(self.results['errors_by_rule'].items(), 
                          key=lambda x: x[1], reverse=True)[:5]
        
        if top_errors:
            recommendations.append({
                'category': 'High Priority Fixes',
                'description': 'Most common error rules that should be addressed first',
                'items': [f"{rule}: {count} occurrences" for rule, count in top_errors]
            })
            
        # Security issues
        if self.results['security_issues']:
            recommendations.append({
                'category': 'Security Issues',
                'description': 'Security-related issues that require immediate attention',
                'items': [f"{issue['rule']}: {issue['message']}" 
                         for issue in self.results['security_issues'][:3]]
            })
            
        # Frappe-specific issues
        if self.results['frappe_specific_issues']:
            recommendations.append({
                'category': 'Frappe Best Practices',
                'description': 'Frappe framework specific improvements',
                'items': [f"{issue['rule']}: {issue['message']}" 
                         for issue in self.results['frappe_specific_issues'][:3]]
            })
            
        # Files with most issues
        files_by_issue_count = sorted(
            [(path, len(issues)) for path, issues in self.results['errors_by_file'].items()],
            key=lambda x: x[1], reverse=True
        )[:5]
        
        if files_by_issue_count:
            recommendations.append({
                'category': 'Files Needing Attention',
                'description': 'Files with the most ESLint issues',
                'items': [f"{Path(path).name}: {count} issues" 
                         for path, count in files_by_issue_count]
            })
            
        self.results['recommendations'] = recommendations
        
    def generate_report(self, output_file=None):
        """Generate comprehensive analysis report"""
        self.generate_recommendations()
        
        report_lines = [
            "# ESLint Analysis Report for Verenigingen JavaScript Codebase",
            f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n",
            "## Summary",
            f"- **Files Analyzed**: {self.results['summary'].get('total_files_analyzed', 0)}",
            f"- **Total Errors**: {self.results['summary'].get('total_errors', 0)}",
            f"- **Total Warnings**: {self.results['summary'].get('total_warnings', 0)}",
            f"- **Files with Issues**: {self.results['summary'].get('files_with_issues', 0)}\\n"
        ]
        
        # Top error rules
        if self.results['errors_by_rule']:
            report_lines.extend([
                "## Most Common Error Rules",
                "| Rule | Count | Description |",
                "|------|-------|-------------|"
            ])
            
            top_errors = sorted(self.results['errors_by_rule'].items(), 
                              key=lambda x: x[1], reverse=True)[:10]
            
            for rule, count in top_errors:
                description = self._get_rule_description(rule)
                report_lines.append(f"| `{rule}` | {count} | {description} |")
            report_lines.append("")
            
        # Security issues
        if self.results['security_issues']:
            report_lines.extend([
                "## Security Issues",
                f"Found {len(self.results['security_issues'])} security-related issues:\\n"
            ])
            
            for issue in self.results['security_issues'][:10]:
                file_name = Path(issue['file']).name
                report_lines.append(f"- **{file_name}:{issue['line']}**: {issue['message']} (`{issue['rule']}`)")
            report_lines.append("")
            
        # Frappe-specific issues
        if self.results['frappe_specific_issues']:
            report_lines.extend([
                "## Frappe Framework Issues",
                f"Found {len(self.results['frappe_specific_issues'])} Frappe-specific issues:\\n"
            ])
            
            for issue in self.results['frappe_specific_issues'][:10]:
                file_name = Path(issue['file']).name
                report_lines.append(f"- **{file_name}:{issue['line']}**: {issue['message']} (`{issue['rule']}`)")
            report_lines.append("")
            
        # Recommendations
        if self.results['recommendations']:
            report_lines.extend([
                "## Recommendations"
            ])
            
            for rec in self.results['recommendations']:
                report_lines.extend([
                    f"### {rec['category']}",
                    rec['description'] + "\\n"
                ])
                
                for item in rec['items']:
                    report_lines.append(f"- {item}")
                report_lines.append("")
                
        # Files needing attention
        if self.results['errors_by_file']:
            report_lines.extend([
                "## Files with Most Issues",
                "| File | Errors | Warnings | Total |",
                "|------|--------|----------|-------|"
            ])
            
            files_by_issue = []
            for file_info in self.results['files_analyzed']:
                path = file_info['path']
                error_count = file_info['error_count']
                warning_count = file_info['warning_count']
                total = error_count + warning_count
                files_by_issue.append((path, error_count, warning_count, total))
                
            files_by_issue.sort(key=lambda x: x[3], reverse=True)
            
            for path, errors, warnings, total in files_by_issue[:15]:
                file_name = Path(path).name
                report_lines.append(f"| {file_name} | {errors} | {warnings} | {total} |")
                
        report_content = "\\n".join(report_lines)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report_content)
            print(f"📄 Report saved to: {output_file}")
        else:
            print("\\n" + report_content)
            
    def _get_rule_description(self, rule):
        """Get human-readable description for ESLint rules"""
        descriptions = {
            'no-unused-vars': 'Variables declared but never used',
            'no-undef': 'Variables used but not defined',
            'no-console': 'Use of console.log and similar methods',
            'eqeqeq': 'Use of == instead of ===',
            'curly': 'Missing curly braces in control structures',
            'indent': 'Incorrect indentation',
            'quotes': 'Inconsistent quote usage',
            'semi': 'Missing or extra semicolons',
            'frappe/require-frappe-call-error-handling': 'frappe.call() missing error handling',
            'frappe/no-direct-html-injection': 'Direct HTML injection vulnerability',
            'frappe/doctype-field-validation': 'Invalid DocType field reference',
            'security/detect-eval-with-expression': 'Use of eval() with expressions',
            'security/detect-non-literal-regexp': 'Non-literal regular expressions',
            'no-unsanitized/method': 'Unsanitized method calls',
            'no-unsanitized/property': 'Unsanitized property assignments'
        }
        
        return descriptions.get(rule, 'ESLint rule violation')
        
    def save_results(self, output_file):
        """Save raw results as JSON"""
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"💾 Raw results saved to: {output_file}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze JavaScript code with ESLint')
    parser.add_argument('--fix', action='store_true', help='Automatically fix fixable issues')
    parser.add_argument('--report', help='Generate report file')
    parser.add_argument('--json', help='Save raw results as JSON')
    parser.add_argument('--base-path', help='Base path for analysis')
    
    args = parser.parse_args()
    
    analyzer = ESLintAnalyzer(args.base_path)
    
    print("🚀 Starting ESLint analysis...")
    
    if not analyzer.run_eslint_analysis(fix_issues=args.fix):
        sys.exit(1)
        
    # Generate report
    report_file = args.report or 'eslint_analysis_report.md'
    analyzer.generate_report(report_file)
    
    # Save raw results if requested
    if args.json:
        analyzer.save_results(args.json)
        
    # Print summary
    summary = analyzer.results['summary']
    print(f"\\n✅ Analysis complete!")
    print(f"📊 Analyzed {summary.get('total_files_analyzed', 0)} files")
    print(f"❌ Found {summary.get('total_errors', 0)} errors")
    print(f"⚠️  Found {summary.get('total_warnings', 0)} warnings")
    
    if summary.get('total_errors', 0) > 0:
        print("\\n💡 Run with --fix flag to automatically fix some issues")
        
    return 0 if summary.get('total_errors', 0) == 0 else 1

if __name__ == '__main__':
    sys.exit(main())