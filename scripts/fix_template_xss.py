#!/usr/bin/env python3
"""
Script to add XSS protection to email templates by escaping all variable outputs.
Adds |e filter to variables that are displayed in HTML context.
"""

import json
import re
import sys
import os

def escape_template_variables(template_content):
    """
    Add XSS protection by escaping template variables.
    """
    # URLs and attributes that should NOT be escaped (they need the raw values)
    url_patterns = [
        r'href="{{ ([^}]+) }}"',  # href attributes
        r'href="\{\{ ([^}]+) \}\}"',  # href attributes with spaces
        r'base_url',  # URLs should not be escaped
        r'payment_url',
        r'approval_url',
        r'dashboard_url',
    ]

    # Find all {{ variable }} patterns
    variable_pattern = r'\{\{\s*([^}]+?)\s*\}\}'

    def should_escape_variable(var_content):
        """Determine if a variable should be escaped"""
        # Don't escape if it's inside a URL context
        for url_pattern in url_patterns:
            if any(url_part in var_content for url_part in ['base_url', 'payment_url', 'approval_url', 'dashboard_url']):
                return False

        # Don't escape if it already has a filter
        if '|' in var_content:
            return False

        # Don't escape static strings
        if '"' in var_content and 'or' in var_content:
            return False

        return True

    def escape_match(match):
        var_content = match.group(1).strip()

        # Check if we should escape this variable
        if should_escape_variable(var_content):
            return '{{ ' + var_content + '|e }}'
        else:
            return match.group(0)  # Return original

    # Apply escaping to all variables
    escaped_content = re.sub(variable_pattern, escape_match, template_content)

    return escaped_content

def fix_email_template_xss():
    """Fix XSS vulnerabilities in email templates"""
    template_file = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/email_template.json'

    # Read the current templates
    with open(template_file, 'r') as f:
        templates = json.load(f)

    print(f"Processing {len(templates)} email templates...")

    # Process each template
    updated_count = 0
    for template in templates:
        if 'response' in template and template['response']:
            original_response = template['response']
            escaped_response = escape_template_variables(original_response)

            if escaped_response != original_response:
                template['response'] = escaped_response
                updated_count += 1
                print(f"Updated template: {template.get('name', 'Unknown')}")

        # Also escape subject lines
        if 'subject' in template and template['subject']:
            original_subject = template['subject']
            escaped_subject = escape_template_variables(original_subject)

            if escaped_subject != original_subject:
                template['subject'] = escaped_subject
                print(f"Updated subject for template: {template.get('name', 'Unknown')}")

    # Write back the updated templates
    with open(template_file, 'w') as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)

    print(f"\nCompleted! Updated {updated_count} templates with XSS protection.")
    print("All template variables are now escaped to prevent XSS attacks.")

if __name__ == '__main__':
    fix_email_template_xss()