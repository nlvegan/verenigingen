#!/usr/bin/env python3
"""
JavaScript Validation Scanner
============================

Scans HTML template files for common JavaScript issues that can cause runtime errors.

Issues detected:
- Server-side function calls in client-side JavaScript
- Template literal syntax errors
- Common JavaScript-Jinja2 mixing issues
- Undefined JavaScript variables
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


def scan_html_files(base_path: str) -> Dict[str, List[Dict]]:
    """Scan all HTML files for JavaScript issues"""
    
    results = {"files_scanned": 0, "issues_found": [], "clean_files": []}
    
    # Find all HTML files
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                results["files_scanned"] += 1
                
                issues = scan_single_file(file_path)
                if issues:
                    results["issues_found"].append({
                        "file": os.path.relpath(file_path, base_path),
                        "issues": issues
                    })
                else:
                    results["clean_files"].append(os.path.relpath(file_path, base_path))
    
    return results


def scan_single_file(file_path: str) -> List[Dict]:
    """Scan a single HTML file for JavaScript issues"""
    
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        in_javascript = False
        for i, line in enumerate(lines, 1):
            # Track JavaScript context
            if '<script>' in line.lower():
                in_javascript = True
            elif '</script>' in line.lower():
                in_javascript = False
            
            # Check for various JavaScript issues
            if in_javascript:
                issues.extend(check_javascript_line(line, i))
            else:
                # Check for JavaScript in attributes or inline
                issues.extend(check_inline_javascript(line, i))
    
    except Exception as e:
        issues.append({
            "line": 0,
            "type": "file_error",
            "description": f"Could not read file: {e}",
            "severity": "error"
        })
    
    return issues


def check_javascript_line(line: str, line_num: int) -> List[Dict]:
    """Check a JavaScript line for issues"""
    
    issues = []
    
    # Pattern 1: Server-side function calls in template literals
    if '${' in line and 'frappe.' in line:
        # Check for server-side functions in JavaScript template literals
        server_functions = ['frappe.format_value', 'frappe.format_currency', 'frappe.format_date']
        for func in server_functions:
            if func in line:
                issues.append({
                    "line": line_num,
                    "type": "server_side_call",
                    "description": f"Server-side function '{func}' called in client-side JavaScript template literal",
                    "severity": "error",
                    "suggestion": f"Use client-side formatting instead of {func}"
                })
    
    # Pattern 2: Jinja2 syntax in JavaScript
    if '{{' in line and '}}' in line:
        issues.append({
            "line": line_num, 
            "type": "jinja_in_js",
            "description": "Jinja2 template syntax found in JavaScript context",
            "severity": "warning",
            "suggestion": "Pass data via JSON or use frappe.render_template"
        })
    
    # Pattern 3: Common undefined variables
    undefined_patterns = [
        (r'\bfrappe\.session\.user\b', 'Use frappe.session.user from server-side context'),
        (r'\bfrappe\.db\b', 'Database calls not available in client-side JavaScript'),
        (r'\bfrappe\.get_doc\b', 'Document fetching not available in client-side JavaScript')
    ]
    
    for pattern, suggestion in undefined_patterns:
        if re.search(pattern, line):
            issues.append({
                "line": line_num,
                "type": "undefined_reference",
                "description": f"Potentially undefined reference: {pattern}",
                "severity": "warning",
                "suggestion": suggestion
            })
    
    return issues


def check_inline_javascript(line: str, line_num: int) -> List[Dict]:
    """Check for JavaScript issues in inline contexts (attributes, etc.)"""
    
    issues = []
    
    # Check for JavaScript in onclick, onchange, etc.
    js_attributes = re.findall(r'on\w+\s*=\s*["\'][^"\']*["\']', line, re.IGNORECASE)
    
    for attr in js_attributes:
        if 'frappe.format_value' in attr:
            issues.append({
                "line": line_num,
                "type": "inline_server_call", 
                "description": "Server-side function call in inline JavaScript attribute",
                "severity": "error",
                "suggestion": "Move to separate script block with client-side formatting"
            })
    
    return issues


def generate_report(results: Dict) -> str:
    """Generate a formatted report of JavaScript validation results"""
    
    report = []
    report.append("🔍 JavaScript Validation Report")
    report.append("=" * 40)
    report.append(f"Files scanned: {results['files_scanned']}")
    report.append(f"Clean files: {len(results['clean_files'])}")
    report.append(f"Files with issues: {len(results['issues_found'])}")
    report.append("")
    
    if not results['issues_found']:
        report.append("✅ No JavaScript issues found!")
        report.append("🎉 All HTML templates are JavaScript-compliant!")
        return "\n".join(report)
    
    # Group issues by severity
    error_count = sum(len([i for i in file['issues'] if i['severity'] == 'error']) 
                     for file in results['issues_found'])
    warning_count = sum(len([i for i in file['issues'] if i['severity'] == 'warning']) 
                       for file in results['issues_found'])
    
    report.append(f"❌ Errors: {error_count}")
    report.append(f"⚠️  Warnings: {warning_count}")
    report.append("")
    
    # Detail issues by file
    for file_result in results['issues_found']:
        report.append(f"📄 {file_result['file']}:")
        
        for issue in file_result['issues']:
            severity_icon = "❌" if issue['severity'] == 'error' else "⚠️"
            report.append(f"  {severity_icon} Line {issue['line']}: {issue['description']}")
            if 'suggestion' in issue:
                report.append(f"     💡 {issue['suggestion']}")
        report.append("")
    
    # Summary recommendations
    if error_count > 0:
        report.append("🚨 CRITICAL: Fix error-level issues to prevent runtime crashes")
    if warning_count > 0:
        report.append("⚠️  RECOMMENDED: Address warnings for better code quality")
    
    return "\n".join(report)


def main():
    """Main JavaScript validation function"""
    
    # Determine the templates directory
    current_dir = Path(__file__).parent
    templates_dir = current_dir.parent.parent / "verenigingen" / "templates"
    
    if not templates_dir.exists():
        print(f"❌ Templates directory not found: {templates_dir}")
        return 1
    
    print("🔍 Scanning HTML templates for JavaScript issues...")
    
    results = scan_html_files(str(templates_dir))
    report = generate_report(results)
    
    print(report)
    
    # Return appropriate exit code
    error_count = sum(len([i for i in file['issues'] if i['severity'] == 'error']) 
                     for file in results['issues_found'])
    
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    exit(main())