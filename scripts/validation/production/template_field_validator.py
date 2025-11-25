#!/usr/bin/env python3
"""
JavaScript Validation Scanner (Updated January 2025)
====================================================

Scans HTML template files and JavaScript files for common issues that can cause runtime errors.

IMPORTANT: This validator distinguishes between legitimate and problematic Jinja2 usage:
- ✅ LEGITIMATE: Jinja2 syntax in HTML templates ({{ }} processed server-side)
- ❌ PROBLEMATIC: Jinja2 syntax in standalone .js files (not processed by server)

Issues detected:
- Server-side function calls in client-side JavaScript
- Jinja2 template syntax in standalone JavaScript files
- Invalid field references in API calls
- Undefined JavaScript variables in non-template contexts
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Set


# Import unified DocType loader
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from doctype_loader import load_doctypes_simple


def load_doctype_fields() -> Dict[str, Set[str]]:
    """Load all valid fields for each doctype using unified loader"""
    # Use current app path to derive the unified loader
    current_app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    return load_doctypes_simple(current_app_path, verbose=False)


# Legacy function for backward compatibility (now redirects to unified loader)
def load_doctypes_from_app(app_path: str) -> Dict[str, Set[str]]:
    """Load doctypes from a specific app (legacy compatibility)"""
    # This now uses the unified loader but filters to specific app if needed
    # For now, return full multi-app results since most validators expect this
    current_app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    return load_doctypes_simple(current_app_path, verbose=False)


def scan_all_files(base_path: str, doctypes: Dict[str, Set[str]]) -> Dict[str, List[Dict]]:
    """Scan both HTML and JavaScript files for issues"""
    
    results = {"files_scanned": 0, "issues_found": [], "clean_files": []}
    
    # Find all HTML and JS files
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith(('.html', '.js')):
                file_path = os.path.join(root, file)
                results["files_scanned"] += 1
                
                if file.endswith('.html'):
                    # Skip Jinja2 validation for HTML files - they're processed server-side
                    issues = scan_html_file_for_serious_issues(file_path, doctypes)
                else:
                    # Only scan .js files for Jinja2 mixing - this is where it's problematic
                    issues = scan_js_file(file_path, doctypes)
                    
                if issues:
                    results["issues_found"].append({
                        "file": os.path.relpath(file_path, base_path),
                        "issues": issues
                    })
                else:
                    results["clean_files"].append(os.path.relpath(file_path, base_path))
    
    return results


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


def scan_html_file_for_serious_issues(file_path: str, doctypes: Dict[str, Set[str]]) -> List[Dict]:
    """Scan HTML file for serious JavaScript issues, excluding legitimate Jinja2 server-side templating"""
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
            
            # Only check for serious issues in JavaScript contexts
            if in_javascript:
                # Check for server-side function calls that won't work client-side
                server_functions = ['frappe.format_value', 'frappe.format_currency', 'frappe.format_date']
                for func in server_functions:
                    if func in line and '${' in line:  # Template literal context
                        issues.append({
                            "line": i,
                            "type": "server_side_call",
                            "description": f"Server-side function '{func}' called in client-side JavaScript template literal",
                            "severity": "error",
                            "suggestion": f"Use client-side formatting instead of {func}"
                        })
                
                # Check for problematic undefined references (excluding legitimate Jinja2)
                # Only flag if it's NOT within Jinja2 template context
                if 'frappe.db' in line and '{{' not in line:
                    issues.append({
                        "line": i,
                        "type": "undefined_reference",
                        "description": "Database calls not available in client-side JavaScript",
                        "severity": "warning",
                        "suggestion": "Use frappe.call() for database operations"
                    })
    
    except Exception as e:
        issues.append({
            "line": 0,
            "type": "file_error",
            "description": f"Could not read file: {e}",
            "severity": "error"
        })
    
    return issues

def scan_html_file(file_path: str, doctypes: Dict[str, Set[str]]) -> List[Dict]:
    """Scan a single HTML file for JavaScript issues (updated to use doctypes)"""
    return scan_single_file(file_path)  # Use existing logic for HTML


def scan_js_file(file_path: str, doctypes: Dict[str, Set[str]]) -> List[Dict]:
    """Scan a JavaScript file for field reference issues and problematic Jinja2 usage"""
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return [{
            "line": 0,
            "type": "file_error",
            "description": f"Could not read file: {e}",
            "severity": "error"
        }]
    
    # Check each line for issues
    for line_num, line in enumerate(lines, 1):
        # Check for field references in API calls
        issues.extend(check_field_references(line, line_num, content, doctypes))
        
        # Check for problematic Jinja2 in standalone JS files
        # Only flag files in the app directory, not node_modules or third-party libraries
        is_app_file = 'verenigingen/' in file_path and 'node_modules' not in file_path
        
        if is_app_file and '{{' in line and '}}' in line:
            # Check if it's actual Jinja2 syntax (not Vue templates, regex, etc.)
            if is_likely_jinja2_syntax(line):
                issues.append({
                    "line": line_num,
                    "type": "jinja_in_js_file",
                    "description": "Jinja2 template syntax found in standalone JavaScript file",
                    "severity": "error",
                    "suggestion": "Move server-side data injection to HTML template or use frappe.boot/frappe.call()"
                })
    
    return issues


def is_likely_jinja2_syntax(line: str) -> bool:
    """Check if {{ }} syntax is likely Jinja2 template syntax vs other uses"""
    
    # Common Jinja2 patterns
    jinja2_patterns = [
        r'\{\{\s*_\(',           # Translation function: {{ _("text") }}
        r'\{\{\s*\w+\s*\|\s*\w+', # Filters: {{ var|filter }}
        r'\{\{\s*\w+\s*\}\}',     # Simple variables: {{ variable }}
        r'\{\{\s*\w+\.\w+',       # Dot notation: {{ obj.prop }}
    ]
    
    # Check if any Jinja2 patterns match
    for pattern in jinja2_patterns:
        if re.search(pattern, line):
            return True
    
    # Exclude common non-Jinja2 uses
    non_jinja2_patterns = [
        r'\{\{\s*[#/]',          # Vue template comments: {{# or {{/
        r'template\s*:\s*`.*\{\{', # Template literals with Vue syntax
        r'regex.*\{\{',           # Regex patterns
        r'RegExp.*\{\{',          # RegExp patterns
        r'/.*\{\{.*/',            # Regex literals
    ]
    
    for pattern in non_jinja2_patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return False
    
    return False  # Default to false for ambiguous cases


def check_field_references(line: str, line_num: int, full_content: str, doctypes: Dict[str, Set[str]]) -> List[Dict]:
    """Check for invalid field references in JavaScript API calls"""
    issues = []
    
    # Pattern 1: fields array on the same line
    fields_match = re.search(r'fields\s*:\s*\[(.*?)\]', line, re.IGNORECASE)
    if fields_match:
        doctype = extract_doctype_from_get_list(full_content, line_num)
        if doctype and doctype in doctypes:
            fields_str = fields_match.group(1)
            fields = extract_fields_from_array(fields_str)
            for field in fields:
                if field not in doctypes[doctype] and not is_system_field(field) and not is_sql_expression(field):
                    issues.append({
                        "line": line_num,
                        "type": "invalid_field_reference",
                        "description": f"Field '{field}' not found in {doctype} doctype",
                        "severity": "error",
                        "suggestion": f"Check {doctype} doctype fields or use correct field name"
                    })
    
    # Pattern 2: frappe.client.get_list with fields on same line (fallback)
    get_list_match = re.search(r'frappe\.client\.get_list.*?fields\s*:\s*\[(.*?)\]', line, re.IGNORECASE)
    if get_list_match and not fields_match:  # Avoid duplicates
        doctype = extract_doctype_from_get_list(full_content, line_num)
        if doctype and doctype in doctypes:
            fields_str = get_list_match.group(1)
            fields = extract_fields_from_array(fields_str)
            for field in fields:
                if field not in doctypes[doctype] and not is_system_field(field) and not is_sql_expression(field):
                    issues.append({
                        "line": line_num,
                        "type": "invalid_field_reference",
                        "description": f"Field '{field}' not found in {doctype} doctype",
                        "severity": "error",
                        "suggestion": f"Check {doctype} doctype fields or use correct field name"
                    })
    
    return issues


def extract_doctype_from_get_list(content: str, current_line: int) -> str:
    """Extract doctype from frappe.client.get_list call context"""
    lines = content.split('\n')
    
    # First, look for the specific frappe.db.get_list pattern (highest priority)
    # This should match patterns like: frappe.db.get_list('DocType', {
    for i in range(max(0, current_line - 10), current_line + 1):
        if i < len(lines):
            line = lines[i]
            
            # Pattern 1 (HIGHEST PRIORITY): frappe.db.get_list('DocType', ...)
            frappe_db_match = re.search(r'frappe\.db\.get_list\s*\(\s*[\'"]([^\'"]+)[\'"]', line)
            if frappe_db_match:
                return frappe_db_match.group(1)
            
            # Pattern 2: frappe.client.get_list with explicit DocType
            client_match = re.search(r'frappe\.client\.get_list\s*\(\s*[\'"]([^\'"]+)[\'"]', line)
            if client_match:
                return client_match.group(1)
            
            # Pattern 3: getList('SomeType', ...) or get_list('SomeType', ...)  
            getlist_match = re.search(r'(?:getList|get_list)\s*\(\s*[\'"]([^\'"]+)[\'"]', line)
            if getlist_match:
                return getlist_match.group(1)
    
    # Second pass: look for other patterns (lower priority)
    for i in range(max(0, current_line - 10), current_line + 1):
        if i < len(lines):
            line = lines[i]
            
            # Pattern 4: frappe.client.get_list with doctype on same line
            combined_match = re.search(r'frappe\.client\.get_list.*?doctype\s*:\s*[\'"]([^\'"]+)[\'"]', line)
            if combined_match:
                return combined_match.group(1)
            
            # Pattern 5 (LOWEST PRIORITY): generic doctype: 'SomeType' 
            # Only use this if no specific get_list patterns found
            doctype_match = re.search(r'doctype\s*:\s*[\'"]([^\'"]+)[\'"]', line)
            if doctype_match:
                # Check if this line also contains get_list - if so, skip it
                # This prevents false matches from frappe.client.get_list contexts
                if 'get_list' not in line:
                    return doctype_match.group(1)
    
    return None


def extract_fields_from_array(fields_str: str) -> List[str]:
    """Extract field names from JavaScript array string"""
    # Remove quotes and brackets, split by comma
    cleaned = re.sub(r'[\[\]\'\"]', '', fields_str)
    parts = [p.strip() for p in cleaned.split(',')]
    
    fields = []
    for part in parts:
        if part and not part.startswith('//'):  # Skip comments
            fields.append(part)
    
    return fields


def is_system_field(field: str) -> bool:
    """Check if field is a system field that exists on all doctypes"""
    system_fields = {
        'name', 'creation', 'modified', 'modified_by', 'owner', 
        'docstatus', 'idx', '__islocal', '__unsaved', 'parent', 'parentfield', 'parenttype'
    }
    return field in system_fields


def is_sql_expression(field: str) -> bool:
    """Check if field is a SQL expression rather than a field name"""
    # Common SQL aggregate functions and expressions
    sql_patterns = [
        r'count\(',
        r'sum\(',
        r'avg\(',
        r'max\(',
        r'min\(',
        r'distinct\s+',
        r'\s+as\s+',
        r'case\s+when',
        r'ifnull\(',
        r'coalesce\(',
    ]
    
    field_lower = field.lower().strip()
    for pattern in sql_patterns:
        if re.search(pattern, field_lower):
            return True
    return False


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
        report.append("🎉 All templates and JavaScript files are compliant!")
        report.append("")
        report.append("ℹ️  Note: Jinja2 syntax in HTML templates is legitimate and expected.")
        report.append("   This validator only flags problematic usage in standalone .js files.")
        return "\n".join(report)
    
    # Group issues by severity and type
    error_count = sum(len([i for i in file['issues'] if i['severity'] == 'error']) 
                     for file in results['issues_found'])
    warning_count = sum(len([i for i in file['issues'] if i['severity'] == 'warning']) 
                       for file in results['issues_found'])
    field_errors = sum(len([i for i in file['issues'] if i['type'] == 'invalid_field_reference'])
                      for file in results['issues_found'])
    jinja_js_errors = sum(len([i for i in file['issues'] if i['type'] == 'jinja_in_js_file'])
                         for file in results['issues_found'])
    server_call_errors = sum(len([i for i in file['issues'] if i['type'] == 'server_side_call'])
                            for file in results['issues_found'])
    
    report.append(f"❌ Critical Errors: {error_count}")
    report.append(f"   🔗 Field Reference Errors: {field_errors}")
    report.append(f"   🔀 Jinja2 in JS Files: {jinja_js_errors}")
    report.append(f"   🚫 Server-side Calls in Client JS: {server_call_errors}")
    report.append(f"⚠️  Warnings: {warning_count}")
    report.append("")
    
    # Show critical errors first (field references)
    critical_files = []
    warning_files = []
    
    for file_result in results['issues_found']:
        has_errors = any(i['severity'] == 'error' for i in file_result['issues'])
        if has_errors:
            critical_files.append(file_result)
        else:
            warning_files.append(file_result)
    
    # Report critical errors prominently
    if critical_files:
        report.append("🚨 CRITICAL ERRORS (Field References)")
        report.append("=" * 50)
        for file_result in critical_files:
            report.append(f"📄 {file_result['file']}:")
            for issue in file_result['issues']:
                if issue['severity'] == 'error':
                    report.append(f"  ❌ Line {issue['line']}: {issue['description']}")
                    if 'suggestion' in issue:
                        report.append(f"     💡 {issue['suggestion']}")
            report.append("")
    
    # Report warnings less prominently (show count but not details unless < 10)
    if warning_files:
        report.append("⚠️  Warnings Summary")
        report.append("=" * 30)
        
        # Count Jinja2 warnings
        jinja_warnings = sum(len([i for i in file['issues'] if i['type'] == 'jinja_in_js_file'])
                           for file in warning_files)
        
        if jinja_warnings > 10:
            report.append(f"📊 Found {jinja_warnings} Jinja2-in-JavaScript warnings across {len(warning_files)} files")
            report.append("💡 Consider using frappe.render_template or JSON data passing")
            report.append("   Run with --show-all-warnings to see details")
        else:
            # Show details for fewer warnings
            for file_result in warning_files[:5]:  # Limit to first 5 files
                report.append(f"📄 {file_result['file']}:")
                for issue in file_result['issues'][:3]:  # Limit to first 3 issues per file
                    if issue['severity'] == 'warning':
                        report.append(f"  ⚠️ Line {issue['line']}: {issue['description']}")
                report.append("")
    
    # Summary recommendations
    if error_count > 0:
        report.append("🚨 CRITICAL: Fix field reference errors to prevent runtime crashes")
    if warning_count > 0:
        report.append("⚠️  RECOMMENDED: Address Jinja2-in-JS warnings for better practices")
    
    return "\n".join(report)


def main():
    """Main JavaScript validation function"""
    
    # Determine the base directory
    current_dir = Path(__file__).parent
    base_dir = current_dir.parent.parent
    
    print("🔍 Loading doctype definitions...")
    doctypes = load_doctype_fields()
    print(f"Loaded {len(doctypes)} doctypes")
    
    print("🔍 Scanning HTML and JavaScript files for issues...")
    
    # Scan both templates and JavaScript files
    results = scan_all_files(str(base_dir), doctypes)
    report = generate_report(results)
    
    print(report)
    
    # Return appropriate exit code
    error_count = sum(len([i for i in file['issues'] if i['severity'] == 'error']) 
                     for file in results['issues_found'])
    
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    exit(main())