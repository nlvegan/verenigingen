#!/usr/bin/env python3
"""
Process JS-Python validation results into reviewable format

This script takes the JSON output from js_python_parameter_validator.py and creates
comprehensive, reviewable lists organized by category and priority.
"""

import json
import csv
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any

def categorize_issue(issue: Dict[str, Any]) -> str:
    """Categorize an issue based on method name and context"""
    method = issue["method"]
    file_path = issue["file"]
    
    # Framework methods (usually should be IGNORE)
    if method.startswith("frappe."):
        if method in ["frappe.client.get", "frappe.client.get_list", "frappe.client.get_value"]:
            return "Framework Client Methods"
        elif method.startswith("frappe.call"):
            return "Framework Call Methods"
        else:
            return "Other Framework Methods"
    
    # Test-related methods
    if "test" in method.lower() or "mock" in method.lower():
        return "Test Methods"
    
    # API methods by module pattern
    if "." in method:
        parts = method.split(".")
        if len(parts) >= 2:
            module = parts[0]
            if module in ["verenigingen"]:
                return "Verenigingen API Methods"
            elif module in ["eboekhouden", "e_boekhouden"]:
                return "E-Boekhouden Integration"
            elif module in ["sepa", "payment"]:
                return "Payment/SEPA Methods"
            elif module in ["member", "membership"]:
                return "Member Management"
            elif module in ["volunteer"]:
                return "Volunteer Management"
            else:
                return "Other API Methods"
    
    # Simple method names (likely missing module prefix)
    if method in ["get_billing_amount", "get_impact_preview", "approve_amendment", "reject_amendment"]:
        return "Amendment/Approval Methods"
    elif method.startswith("get_"):
        return "Getter Methods"
    elif method.startswith("create_"):
        return "Creator Methods"
    elif method.startswith("update_"):
        return "Update Methods"
    else:
        return "Other Methods"

def get_file_category(file_path: str) -> str:
    """Categorize file by path"""
    if "archived" in file_path or "unused" in file_path:
        return "Archived/Unused"
    elif "test" in file_path.lower() or "cypress" in file_path:
        return "Test Files"
    elif "verenigingen/doctype" in file_path:
        return "DocType JavaScript"
    elif "verenigingen/public" in file_path:
        return "Public Assets"
    elif "verenigingen/page" in file_path:
        return "Custom Pages"
    elif "verenigingen/report" in file_path:
        return "Reports"
    else:
        return "Core Application"

def format_code_snippet(issue: Dict[str, Any]) -> str:
    """Format the JS code snippet for review"""
    method = issue["method"]
    args = issue["js_args"]
    
    if args:
        args_str = ", ".join([f"{k}: {v}" for k, v in args.items()])
        return f"frappe.call({{ method: '{method}', args: {{ {args_str} }} }})"
    else:
        return f"frappe.call({{ method: '{method}' }})"

def determine_likely_action(issue: Dict[str, Any]) -> str:
    """Suggest likely action based on issue analysis"""
    method = issue["method"]
    file_path = issue["file"]
    
    # Framework methods should usually be ignored
    if method.startswith("frappe.client."):
        return "IGNORE (Framework method)"
    
    # Archived files - likely REMOVE
    if "archived" in file_path or "unused" in file_path:
        return "REMOVE (Archived code)"
    
    # Test files - might be test helper methods that need whitelisting
    if "test" in file_path.lower() or "cypress" in file_path:
        return "FIX (Test helper method)"
    
    # API methods with full path - likely just missing @frappe.whitelist()
    if "verenigingen." in method and len(method.split(".")) >= 3:
        return "FIX (Add whitelist decorator)"
    
    # Simple method names - might be missing or need full path
    if "." not in method:
        return "REVIEW (Check if method exists)"
    
    return "REVIEW (Manual check needed)"

def process_validation_results(json_file: str, output_dir: str):
    """Process validation results and generate review files"""
    
    # Load JSON data
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    issues = data["issues"]
    stats = data["stats"]
    
    print(f"Processing {len(issues)} issues from {stats['js_files_scanned']} JS files...")
    
    # Group issues by various categories
    by_category = defaultdict(list)
    by_file_type = defaultdict(list)
    by_severity = defaultdict(list)
    by_action = defaultdict(list)
    
    # Categorize all issues
    for issue in issues:
        category = categorize_issue(issue)
        file_type = get_file_category(issue["file"])
        action = determine_likely_action(issue)
        
        by_category[category].append(issue)
        by_file_type[file_type].append(issue)
        by_severity[issue["severity"]].append(issue)
        by_action[action].append(issue)
    
    # Generate markdown review file
    markdown_content = generate_markdown_review(
        issues, stats, by_category, by_file_type, by_severity, by_action
    )
    
    # Generate CSV file for spreadsheet review
    csv_content = generate_csv_review(issues)
    
    # Write files
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    md_file = output_path / "broken-js-calls-review.md"
    csv_file = output_path / "broken-js-calls-review.csv"
    
    with open(md_file, 'w') as f:
        f.write(markdown_content)
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(csv_content)
    
    print(f"Generated review files:")
    print(f"  Markdown: {md_file}")
    print(f"  CSV: {csv_file}")
    
    # Print summary
    print(f"\nSummary by file type:")
    for file_type, issues_list in sorted(by_file_type.items()):
        print(f"  {file_type}: {len(issues_list)} issues")
    
    print(f"\nSummary by suggested action:")
    for action, issues_list in sorted(by_action.items()):
        print(f"  {action}: {len(issues_list)} issues")

def generate_markdown_review(issues, stats, by_category, by_file_type, by_severity, by_action):
    """Generate comprehensive markdown review"""
    
    md = []
    md.append("# Broken JavaScript Calls Review")
    md.append("")
    md.append("Comprehensive review of JavaScript calls to missing or non-whitelisted Python methods.")
    md.append("")
    
    # Statistics
    md.append("## Summary Statistics")
    md.append("")
    md.append(f"- **JavaScript files scanned:** {stats['js_files_scanned']}")
    md.append(f"- **Python files scanned:** {stats['py_files_scanned']}")
    md.append(f"- **JS calls found:** {stats['js_calls_found']}")
    md.append(f"- **Python functions found:** {stats['python_functions_found']}")
    md.append(f"- **Issues found:** {stats['issues_found']}")
    md.append("")
    
    # Action priorities
    md.append("## Review Actions Priority")
    md.append("")
    md.append("For each issue, choose one of:")
    md.append("- **FIX** - Add the missing Python method or @frappe.whitelist() decorator")
    md.append("- **REMOVE** - Remove the dead JavaScript call")
    md.append("- **IGNORE** - Keep as-is (framework method, intentional, etc.)")
    md.append("- **REVIEW** - Needs manual investigation")
    md.append("")
    
    # Summary by file type
    md.append("## Issues by File Type")
    md.append("")
    for file_type in ["Core Application", "DocType JavaScript", "Custom Pages", "Reports", "Public Assets", "Test Files", "Archived/Unused"]:
        if file_type in by_file_type:
            issues_list = by_file_type[file_type]
            md.append(f"### {file_type} ({len(issues_list)} issues)")
            md.append("")
            
            for issue in sorted(issues_list, key=lambda x: (x["file"], x["line"])):
                action = determine_likely_action(issue)
                snippet = format_code_snippet(issue)
                
                md.append(f"- [ ] **{action}** - `{issue['method']}`")
                md.append(f"  - **File:** `{issue['file']}:{issue['line']}`")
                md.append(f"  - **Code:** `{snippet}`")
                md.append(f"  - **Issue:** {issue['description']}")
                md.append("")
    
    # Detailed breakdown by method category
    md.append("## Issues by Method Category")
    md.append("")
    
    for category, issues_list in sorted(by_category.items()):
        md.append(f"### {category} ({len(issues_list)} issues)")
        md.append("")
        
        for issue in sorted(issues_list, key=lambda x: (x["file"], x["line"])):
            action = determine_likely_action(issue)
            snippet = format_code_snippet(issue)
            
            md.append(f"- [ ] **{action}** - `{issue['method']}`")
            md.append(f"  - **File:** `{issue['file']}:{issue['line']}`")
            md.append(f"  - **Code:** `{snippet}`")
            md.append(f"  - **Args:** `{list(issue['js_args'].keys()) if issue['js_args'] else 'None'}`")
            md.append("")
    
    # Quick action lists
    md.append("## Quick Action Lists")
    md.append("")
    
    for action in ["FIX (Add whitelist decorator)", "REMOVE (Archived code)", "FIX (Test helper method)", "IGNORE (Framework method)"]:
        if action in by_action:
            issues_list = by_action[action]
            md.append(f"### {action} ({len(issues_list)} issues)")
            md.append("")
            
            for issue in issues_list:
                md.append(f"- [ ] `{issue['method']}` in `{issue['file']}:{issue['line']}`")
            md.append("")
    
    return "\n".join(md)

def generate_csv_review(issues):
    """Generate CSV for spreadsheet review"""
    
    csv_rows = []
    
    # Header
    csv_rows.append([
        "Action", "Priority", "Method", "File", "Line", "Category", "File_Type", 
        "Code_Snippet", "JS_Args", "Description", "Suggestion", "Notes"
    ])
    
    # Data rows
    for issue in issues:
        action = determine_likely_action(issue)
        category = categorize_issue(issue)
        file_type = get_file_category(issue["file"])
        snippet = format_code_snippet(issue)
        args_str = ", ".join(issue["js_args"].keys()) if issue["js_args"] else ""
        
        # Determine priority
        if "archived" in issue["file"] or "unused" in issue["file"]:
            priority = "Low"
        elif "test" in issue["file"].lower():
            priority = "Medium"
        elif issue["severity"] == "high":
            priority = "High"
        else:
            priority = "Medium"
        
        csv_rows.append([
            action.split(" ")[0],  # Just the action word
            priority,
            issue["method"],
            issue["file"],
            issue["line"],
            category,
            file_type,
            snippet,
            args_str,
            issue["description"],
            issue["suggestion"],
            ""  # Empty notes column for manual input
        ])
    
    return csv_rows

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process JS-Python validation results")
    parser.add_argument("--json-file", default="/tmp/js_validation_full.json", help="JSON file from validator")
    parser.add_argument("--output-dir", default="docs/validation", help="Output directory")
    
    args = parser.parse_args()
    
    process_validation_results(args.json_file, args.output_dir)