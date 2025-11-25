#!/usr/bin/env python3
"""
JavaScript Field Validator Integration
======================================

Integration script that replaces the old regex-based JavaScript validation
with the new context-aware advanced validator.

This script provides backward compatibility while delivering vastly improved
accuracy and zero false positives.
"""

import os
import sys
from pathlib import Path

# Add the current directory to Python path so we can import the validator
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from advanced_javascript_field_validator import AdvancedJavaScriptFieldValidator


def validate_javascript_files_new(base_path: str = None) -> dict:
    """
    New JavaScript validation function that replaces the old one
    
    Args:
        base_path: Base path to validate (defaults to verenigingen app root)
        
    Returns:
        Validation results dictionary
    """
    if not base_path:
        current_file = Path(__file__)
        base_path = str(current_file.parent.parent.parent)  # verenigingen app root
    
    # Create advanced validator
    validator = AdvancedJavaScriptFieldValidator()
    
    # Validate directory
    file_results = validator.validate_directory(base_path)
    
    # Convert to old format for backward compatibility
    results = {
        "files_scanned": 0,
        "issues_found": [],
        "clean_files": []
    }
    
    # Count total JavaScript files
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith('.js') and 'node_modules' not in root:
                results["files_scanned"] += 1
    
    # Convert file results to old format
    for file_path, issues in file_results.items():
        issue_list = []
        for issue in issues:
            issue_list.append({
                "line": issue.line_number,
                "type": "invalid_field_reference",
                "description": issue.description,
                "severity": issue.severity,
                "suggestion": issue.suggestion,
                "expression": issue.expression
            })
        
        results["issues_found"].append({
            "file": file_path,
            "issues": issue_list
        })
    
    # Calculate clean files
    files_with_issues = len(file_results)
    clean_files_count = results["files_scanned"] - files_with_issues
    
    # We don't track individual clean file names in the new validator,
    # so we'll just provide the count
    results["clean_files"] = [f"({clean_files_count} clean files)"]
    
    return results


def generate_report_new(results: dict) -> str:
    """
    Generate report using the new validator format
    
    Args:
        results: Validation results from validate_javascript_files_new
        
    Returns:
        Formatted report string
    """
    report = []
    report.append("🔍 Advanced JavaScript Field Validation Report")
    report.append("=" * 55)
    report.append(f"Files scanned: {results['files_scanned']}")
    
    files_with_issues = len(results['issues_found'])
    clean_files_count = results['files_scanned'] - files_with_issues
    
    report.append(f"Clean files: {clean_files_count}")
    report.append(f"Files with issues: {files_with_issues}")
    report.append("")
    
    if not results['issues_found']:
        report.append("✅ No JavaScript field reference issues found!")
        report.append("🎉 All JavaScript files pass advanced validation!")
        report.append("")
        report.append("ℹ️  Note: This validator uses context-aware analysis to eliminate false positives.")
        report.append("   API response property access and callback parameters are correctly ignored.")
        return "\n".join(report)
    
    # Count issues by severity
    total_issues = sum(len(file_data['issues']) for file_data in results['issues_found'])
    error_count = sum(len([i for i in file_data['issues'] if i['severity'] == 'error']) 
                     for file_data in results['issues_found'])
    warning_count = total_issues - error_count
    
    report.append(f"❌ Errors: {error_count}")
    report.append(f"⚠️  Warnings: {warning_count}")
    report.append("")
    
    # Show detailed issues
    for file_result in results['issues_found']:
        report.append(f"📄 {file_result['file']}:")
        
        for issue in file_result['issues']:
            severity_icon = "❌" if issue['severity'] == "error" else "⚠️"
            report.append(f"  {severity_icon} Line {issue['line']}: {issue['description']}")
            if 'expression' in issue and issue['expression']:
                report.append(f"     Expression: {issue['expression']}")
            if 'suggestion' in issue:
                report.append(f"     💡 {issue['suggestion']}")
            report.append("")
    
    # Summary
    if error_count > 0:
        report.append("🚨 CRITICAL: Fix field reference errors to prevent runtime crashes")
    else:
        report.append("✅ No critical errors found!")
    
    return "\n".join(report)


def main():
    """Main function that demonstrates the new validator"""
    print("🔍 Advanced JavaScript Field Validator Integration")
    print("=" * 55)
    print()
    
    # Get directory to validate
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        current_dir = Path(__file__).parent
        directory = str(current_dir.parent.parent)  # verenigingen app root
    
    print(f"Validating directory: {directory}")
    print()
    
    # Run new validation
    results = validate_javascript_files_new(directory)
    
    # Generate and display report
    report = generate_report_new(results)
    print(report)
    
    # Return appropriate exit code
    error_count = sum(len([i for i in file_data['issues'] if i['severity'] == 'error']) 
                     for file_data in results['issues_found'])
    
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    exit(main())