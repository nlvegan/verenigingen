#!/usr/bin/env python3
"""
Script to fix remaining XSS vulnerabilities in email templates.
Specifically targets complex or expressions that need proper escaping.
"""

import json
import re
import sys
import os

def fix_remaining_xss_issues(template_content):
    """
    Fix remaining XSS issues, specifically complex expressions with 'or' operators.
    """

    # Pattern for expressions like {{ company or "Our Organization" }}
    # These need to be {{ (company or "Our Organization")|e }}
    or_pattern = r'\{\{\s*([^}]+?\s+or\s+[^}]+?)\s*\}\}'

    def fix_or_expression(match):
        expr_content = match.group(1).strip()
        # Don't escape if already has a filter
        if '|' in expr_content:
            return match.group(0)
        # Don't escape URLs
        if any(url_part in expr_content for url_part in ['base_url', 'payment_url', 'approval_url', 'dashboard_url']):
            return match.group(0)

        return '{{ (' + expr_content + ')|e }}'

    # Fix OR expressions
    fixed_content = re.sub(or_pattern, fix_or_expression, template_content)

    # Fix specific unescaped patterns that were missed
    patterns_to_fix = [
        (r'\{\{\s*payment_amount\s+or\s+"[^"]*"\s*\}\}', r'{{ (payment_amount or "Please see invoice")|e }}'),
        (r'\{\{\s*member\.first_name\s+or\s+"[^"]*"\s*\}\}', r'{{ (member.first_name or "Member")|e }}'),
        (r'\{\{\s*member\.full_name\s+or\s+member\.first_name\s*\}\}', r'{{ (member.full_name or member.first_name)|e }}'),
    ]

    for pattern, replacement in patterns_to_fix:
        fixed_content = re.sub(pattern, replacement, fixed_content)

    return fixed_content

def fix_remaining_email_template_xss():
    """Fix remaining XSS vulnerabilities in email templates"""
    template_file = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/email_template.json'

    # Read the current templates
    with open(template_file, 'r') as f:
        templates = json.load(f)

    print(f"Checking {len(templates)} email templates for remaining XSS issues...")

    # Process each template
    updated_count = 0
    for template in templates:
        if 'response' in template and template['response']:
            original_response = template['response']
            fixed_response = fix_remaining_xss_issues(original_response)

            if fixed_response != original_response:
                template['response'] = fixed_response
                updated_count += 1
                print(f"Fixed remaining XSS in template: {template.get('name', 'Unknown')}")

        # Also check subject lines
        if 'subject' in template and template['subject']:
            original_subject = template['subject']
            fixed_subject = fix_remaining_xss_issues(original_subject)

            if fixed_subject != original_subject:
                template['subject'] = fixed_subject
                print(f"Fixed remaining XSS in subject for template: {template.get('name', 'Unknown')}")

    # Write back the updated templates
    with open(template_file, 'w') as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)

    print(f"\nCompleted! Fixed remaining XSS issues in {updated_count} templates.")
    print("All remaining XSS vulnerabilities should now be resolved.")

if __name__ == '__main__':
    fix_remaining_email_template_xss()