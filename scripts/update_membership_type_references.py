#!/usr/bin/env python3
"""
Script to update references to removed Membership Type fields throughout the codebase
"""

import os
import re


def get_files_to_update():
    """Get list of files that need updating"""
    files = []
    
    # Test files
    test_files = [
        "test_enhanced_membership_portal.py",
        "test_new_membership_system.py",
        "test_contribution_system.py",
        "test_membership_application_workflow.py",
        "test_enhanced_contribution_amendment_system.py",
        "test_real_world_dues_amendment_scenarios.py",
        "test_dues_fix.py"
    ]
    
    # Add other file types
    api_files = [
        "verenigingen/api/enhanced_membership_application.py",
        "verenigingen/api/membership_application_review.py"
    ]
    
    template_files = [
        "verenigingen/templates/pages/membership_fee_adjustment.py",
        "verenigingen/templates/pages/financial_dashboard.py"
    ]
    
    util_files = [
        "verenigingen/utils/membership_dues_integration.py",
        "verenigingen/utils/dues_invoice_tracking.py"
    ]
    
    return test_files + api_files + template_files + util_files


def update_membership_type_creation(content):
    """Update membership type creation code to use dues schedule template"""
    
    # Pattern to find membership type creation with contribution fields
    patterns = [
        # Direct field assignment
        (r'membership_type\.contribution_mode\s*=\s*["\'](\w+)["\']',
         '# contribution_mode moved to dues schedule template'),
        (r'membership_type\.minimum_contribution\s*=\s*([\d\.]+)',
         '# minimum_contribution moved to dues schedule template'),
        (r'membership_type\.suggested_contribution\s*=\s*([\d\.]+)',
         '# suggested_contribution moved to dues schedule template'),
        (r'membership_type\.maximum_contribution\s*=\s*([\d\.]+)',
         '# maximum_contribution moved to dues schedule template'),
        (r'membership_type\.enable_income_calculator\s*=\s*(\d+)',
         '# enable_income_calculator moved to dues schedule template'),
        (r'membership_type\.income_percentage_rate\s*=\s*([\d\.]+)',
         '# income_percentage_rate moved to dues schedule template'),
        (r'membership_type\.calculator_description\s*=\s*["\']([^"\']+)["\']',
         '# calculator_description moved to dues schedule template'),
        (r'membership_type\.fee_slider_max_multiplier\s*=\s*([\d\.]+)',
         '# fee_slider_max_multiplier moved to dues schedule template'),
        (r'membership_type\.allow_custom_amounts\s*=\s*(\d+)',
         '# allow_custom_amounts moved to dues schedule template'),
        (r'membership_type\.custom_amount_requires_approval\s*=\s*(\d+)',
         '# custom_amount_requires_approval moved to dues schedule template'),
        (r'membership_type\.currency\s*=\s*["\'](\w+)["\']',
         '# currency moved to dues schedule template'),
    ]
    
    updated_content = content
    for pattern, replacement in patterns:
        updated_content = re.sub(pattern, replacement, updated_content)
    
    # Handle predefined_tiers
    tier_pattern = r'(\w+)\s*=\s*membership_type\.append\("predefined_tiers",\s*\{\}\)'
    if re.search(tier_pattern, updated_content):
        # Add comment about tiers
        updated_content = re.sub(
            tier_pattern,
            r'# Predefined tiers moved to dues schedule template\n    # \1 = membership_type.append("predefined_tiers", {})',
            updated_content
        )
    
    return updated_content


def add_dues_schedule_template_creation(content):
    """Add code to create dues schedule template after membership type creation"""
    
    # Look for membership_type.save() or membership_type.insert()
    save_pattern = r'(membership_type\.(?:save|insert)\(\))'
    
    template_creation = '''
    
    # Create dues schedule template with contribution settings
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = f"Template-{membership_type.name}"
    template.membership_type = membership_type.name
    template.status = "Active"
    template.billing_frequency = "Annual"
    template.contribution_mode = "Calculator"  # Update as needed
    template.minimum_amount = 5.0  # Update with actual values
    template.suggested_amount = membership_type.amount or 15.0
    template.invoice_days_before = 30
    template.auto_generate = 1
    template.amount = template.suggested_amount
    template.insert()
    
    # Link template to membership type
    membership_type.dues_schedule_template = template.name
    membership_type.save()'''
    
    # Insert template creation after membership type save
    if re.search(save_pattern, content) and 'dues_schedule_template' not in content:
        content = re.sub(save_pattern, r'\1' + template_creation, content)
    
    return content


def update_field_access(content):
    """Update code that accesses removed fields"""
    
    # Pattern for getattr access
    getattr_patterns = [
        (r'getattr\(membership_type,\s*["\']contribution_mode["\']\s*,\s*[^)]+\)',
         'getattr(template, "contribution_mode", "Calculator")'),
        (r'getattr\(membership_type,\s*["\']minimum_contribution["\']\s*,\s*[^)]+\)',
         'getattr(template, "minimum_amount", 5.0)'),
        (r'getattr\(membership_type,\s*["\']suggested_contribution["\']\s*,\s*[^)]+\)',
         'getattr(template, "suggested_amount", 15.0)'),
    ]
    
    updated_content = content
    for pattern, replacement in getattr_patterns:
        updated_content = re.sub(pattern, replacement, updated_content)
    
    # Pattern for direct access
    direct_patterns = [
        (r'membership_type\.contribution_mode',
         'template.contribution_mode if template else "Calculator"'),
        (r'membership_type\.minimum_contribution',
         'template.minimum_amount if template else 5.0'),
        (r'membership_type\.suggested_contribution',
         'template.suggested_amount if template else 15.0'),
    ]
    
    for pattern, replacement in direct_patterns:
        # Only replace if not an assignment
        updated_content = re.sub(
            pattern + r'(?!\s*=)',
            replacement,
            updated_content
        )
    
    return updated_content


def process_file(filepath):
    """Process a single file to update references"""
    
    if not os.path.exists(filepath):
        return False
        
    with open(filepath, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Apply updates
    content = update_membership_type_creation(content)
    content = add_dues_schedule_template_creation(content)
    content = update_field_access(content)
    
    # Write back if changed
    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    
    return False


def main():
    """Main function to update all files"""
    
    base_path = "/home/frappe/frappe-bench/apps/verenigingen"
    files = get_files_to_update()
    
    updated_count = 0
    for file in files:
        filepath = os.path.join(base_path, file)
        if process_file(filepath):
            print(f"✓ Updated: {file}")
            updated_count += 1
        else:
            print(f"- No changes needed or file not found: {file}")
    
    print(f"\nTotal files updated: {updated_count}")


if __name__ == "__main__":
    main()