#!/usr/bin/env python3
"""
Fix test files after the membership type field removal
"""

import os
import re


def fix_test_enhanced_membership_portal():
    """Fix test_enhanced_membership_portal.py"""
    
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/test_enhanced_membership_portal.py"
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Fix the tier-based test function
    tier_based_fixed = '''def test_create_tier_based_membership():
    """Create a membership type with predefined tiers"""

    # Create a test membership type with tier system
    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Tier-Based Test Membership"
    membership_type.description = "Test membership type with predefined contribution tiers"
    membership_type.amount = 25.0
    membership_type.billing_frequency = "Annual"
    membership_type.is_active = 1

    try:
        membership_type.save()
        
        # Create dues schedule template with contribution settings
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = "Annual"
        template.contribution_mode = "Tier"  # Changed from "Tiers"
        template.minimum_amount = 10.0
        template.suggested_amount = 25.0
        template.maximum_amount = 100.0
        template.fee_slider_max_multiplier = 4.0
        template.allow_custom_amounts = 1
        template.enable_income_calculator = 0
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.amount = template.suggested_amount
        
        # Add predefined tiers to template
        student_tier = template.append("predefined_tiers", {})
        student_tier.tier_name = "Student"
        student_tier.display_name = "Student Membership"
        student_tier.amount = 15.0
        student_tier.description = "Discounted rate for students with valid student ID"
        student_tier.requires_verification = 1
        student_tier.is_default = 0
        student_tier.display_order = 1

        standard_tier = template.append("predefined_tiers", {})
        standard_tier.tier_name = "Standard"
        standard_tier.display_name = "Standard Membership"
        standard_tier.amount = 25.0
        standard_tier.description = "Standard membership rate"
        standard_tier.requires_verification = 0
        standard_tier.is_default = 1
        standard_tier.display_order = 2

        supporter_tier = template.append("predefined_tiers", {})
        supporter_tier.tier_name = "Supporter"
        supporter_tier.display_name = "Supporter Membership"
        supporter_tier.amount = 50.0
        supporter_tier.description = "Higher contribution to support our mission"
        supporter_tier.requires_verification = 0
        supporter_tier.is_default = 0
        supporter_tier.display_order = 3

        patron_tier = template.append("predefined_tiers", {})
        patron_tier.tier_name = "Patron"
        patron_tier.display_name = "Patron Membership"
        patron_tier.amount = 100.0
        patron_tier.description = "Premium membership with exclusive benefits"
        patron_tier.requires_verification = 0
        patron_tier.is_default = 0
        patron_tier.display_order = 4
        
        template.insert()
        
        # Link template to membership type
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        
        print(f"✓ Created tier-based membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Number of tiers: {len(options.get('tiers', []))}")

        for tier in options.get("tiers", []):
            default_mark = " (DEFAULT)" if tier["is_default"] else ""
            verification_mark = " (REQUIRES VERIFICATION)" if tier["requires_verification"] else ""
            print(f"  - {tier['display_name']}: €{tier['amount']}{default_mark}{verification_mark}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating tier-based membership type: {e}")
        return None'''
    
    # Find and replace the entire function
    pattern = r'def test_create_tier_based_membership\(\):.*?(?=\n\ndef|\Z)'
    content = re.sub(pattern, tier_based_fixed, content, flags=re.DOTALL)
    
    # Fix the calculator-based test function
    calculator_based_fixed = '''def test_create_calculator_based_membership():
    """Create a membership type with income calculator"""

    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Calculator-Based Test Membership"
    membership_type.description = "Test membership type with income-based calculator"
    membership_type.amount = 15.0
    membership_type.billing_frequency = "Monthly"
    membership_type.is_active = 1

    try:
        membership_type.save()
        
        # Create dues schedule template with contribution settings
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = "Monthly"
        template.contribution_mode = "Calculator"
        template.minimum_amount = 5.0
        template.suggested_amount = 15.0
        template.maximum_amount = 150.0
        template.fee_slider_max_multiplier = 10.0
        template.allow_custom_amounts = 1
        template.enable_income_calculator = 1
        template.income_percentage_rate = 0.75
        template.calculator_description = "We suggest 0.75% of your monthly net income as a fair contribution"
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.amount = template.suggested_amount
        template.insert()
        
        # Link template to membership type
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        
        print(f"✓ Created calculator-based membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Calculator enabled: {options['calculator']['enabled']}")
        print(f"✓ Income percentage: {options['calculator']['percentage']}%")
        print(f"✓ Number of quick amounts: {len(options.get('quick_amounts', []))}")

        for amount in options.get("quick_amounts", []):
            default_mark = " (DEFAULT)" if amount["is_default"] else ""
            print(f"  - {amount['label']}: €{amount['amount']:.2f}{default_mark}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating calculator-based membership type: {e}")
        return None'''
    
    pattern = r'def test_create_calculator_based_membership\(\):.*?(?=\n\ndef|\Z)'
    content = re.sub(pattern, calculator_based_fixed, content, flags=re.DOTALL)
    
    # Fix the flexible membership test function
    flexible_fixed = '''def test_create_flexible_membership():
    """Create a membership type that supports both tiers and calculator"""

    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Flexible Test Membership"
    membership_type.description = "Test membership type with both tiers and calculator options"
    membership_type.amount = 20.0
    membership_type.billing_frequency = "Monthly"
    membership_type.is_active = 1

    try:
        membership_type.save()
        
        # Create dues schedule template with contribution settings
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = "Monthly"
        template.contribution_mode = "Calculator"  # Changed from "Both"
        template.minimum_amount = 8.0
        template.suggested_amount = 20.0
        template.maximum_amount = 200.0
        template.fee_slider_max_multiplier = 10.0
        template.allow_custom_amounts = 1
        template.enable_income_calculator = 1
        template.income_percentage_rate = 0.6
        template.calculator_description = "Calculate 0.6% of monthly income or choose from predefined tiers"
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.amount = template.suggested_amount
        
        # Add a few tiers
        basic_tier = template.append("predefined_tiers", {})
        basic_tier.tier_name = "Basic"
        basic_tier.display_name = "Basic Membership"
        basic_tier.amount = 15.0
        basic_tier.description = "Basic membership level"
        basic_tier.requires_verification = 0
        basic_tier.is_default = 0
        basic_tier.display_order = 1

        plus_tier = template.append("predefined_tiers", {})
        plus_tier.tier_name = "Plus"
        plus_tier.display_name = "Plus Membership"
        plus_tier.amount = 20.0
        plus_tier.description = "Standard membership level"
        plus_tier.requires_verification = 0
        plus_tier.is_default = 1
        plus_tier.display_order = 2

        premium_tier = template.append("predefined_tiers", {})
        premium_tier.tier_name = "Premium"
        premium_tier.display_name = "Premium Membership"
        premium_tier.amount = 35.0
        premium_tier.description = "Premium membership with extra benefits"
        premium_tier.requires_verification = 0
        premium_tier.is_default = 0
        premium_tier.display_order = 3
        
        template.insert()
        
        # Link template to membership type
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        
        print(f"✓ Created flexible membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Has tiers: {len(options.get('tiers', [])) > 0}")
        print(f"✓ Has calculator: {options['calculator']['enabled']}")
        print(f"✓ Has quick amounts: {len(options.get('quick_amounts', [])) > 0}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating flexible membership type: {e}")
        return None'''
    
    pattern = r'def test_create_flexible_membership\(\):.*?(?=\n\ndef|\Z)'
    content = re.sub(pattern, flexible_fixed, content, flags=re.DOTALL)
    
    # Write the fixed content
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"✓ Fixed {filepath}")


def fix_test_new_membership_system():
    """Fix test_new_membership_system.py"""
    
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/test_new_membership_system.py"
    
    if not os.path.exists(filepath):
        print(f"- File not found: {filepath}")
        return
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Find all membership type creation patterns and fix them
    # Replace contribution field assignments with template creation
    
    # Pattern to find membership type creation blocks
    pattern = r'(membership_type = frappe\.new_doc\("Membership Type"\)[\s\S]*?)(?:membership_type\.save\(\)|membership_type\.insert\(\))'
    
    def replace_membership_creation(match):
        """Replace membership type creation with proper template setup"""
        block = match.group(1)
        save_method = match.group(0).split('.')[-1]  # save() or insert()
        
        # Extract key values from the block
        contribution_mode = "Calculator"  # Default
        if "contribution_mode" in block:
            mode_match = re.search(r'contribution_mode\s*=\s*["\'](\w+)["\']', block)
            if mode_match:
                mode = mode_match.group(1)
                if mode == "Tiers":
                    contribution_mode = "Tier"
                elif mode == "Both":
                    contribution_mode = "Calculator"
                else:
                    contribution_mode = mode
        
        # Remove contribution field assignments
        cleaned_block = re.sub(r'membership_type\.contribution_mode\s*=.*\n', '', block)
        cleaned_block = re.sub(r'membership_type\.minimum_contribution\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.suggested_contribution\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.maximum_contribution\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.enable_income_calculator\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.income_percentage_rate\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.calculator_description\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.fee_slider_max_multiplier\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.allow_custom_amounts\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.custom_amount_requires_approval\s*=.*\n', '', cleaned_block)
        cleaned_block = re.sub(r'membership_type\.currency\s*=.*\n', '', cleaned_block)
        
        # Remove tier appends
        cleaned_block = re.sub(r'.*membership_type\.append\("predefined_tiers".*\n', '', cleaned_block)
        
        return cleaned_block + f"membership_type.{save_method}"
    
    content = re.sub(pattern, replace_membership_creation, content)
    
    # Add template creation after membership type save
    pattern = r'(membership_type\.(?:save|insert)\(\))'
    
    template_creation = '''
        
        # Create dues schedule template
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = getattr(membership_type, "billing_frequency", "Annual")
        template.contribution_mode = "Calculator"
        template.minimum_amount = 5.0
        template.suggested_amount = membership_type.amount or 15.0
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.amount = template.suggested_amount
        template.insert()
        
        # Link template to membership type
        membership_type.dues_schedule_template = template.name
        membership_type.save()'''
    
    content = re.sub(pattern, r'\1' + template_creation, content)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"✓ Fixed {filepath}")


def fix_test_contribution_system():
    """Fix test_contribution_system.py"""
    
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/test_contribution_system.py"
    
    if not os.path.exists(filepath):
        print(f"- File not found: {filepath}")
        return
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Similar fixes as above
    # Remove direct field assignments and add template creation
    
    # Pattern to find and fix membership type blocks
    pattern = r'(membership_type = frappe\.new_doc\("Membership Type"\)[\s\S]*?)membership_type\.(?:save|insert)\(\)'
    
    def fix_block(match):
        block = match.group(1)
        
        # Remove contribution fields
        fields_to_remove = [
            'contribution_mode', 'minimum_contribution', 'suggested_contribution',
            'maximum_contribution', 'enable_income_calculator', 'income_percentage_rate',
            'calculator_description', 'fee_slider_max_multiplier', 'allow_custom_amounts',
            'custom_amount_requires_approval', 'currency'
        ]
        
        for field in fields_to_remove:
            block = re.sub(rf'membership_type\.{field}\s*=.*\n', '', block)
        
        return block + '''membership_type.save()
        
        # Create dues schedule template
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = "Annual"
        template.contribution_mode = "Calculator"
        template.minimum_amount = 5.0
        template.suggested_amount = membership_type.amount or 15.0
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.amount = template.suggested_amount
        template.insert()
        
        membership_type.dues_schedule_template = template.name
        membership_type.save()'''
    
    content = re.sub(pattern, fix_block, content, flags=re.DOTALL)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"✓ Fixed {filepath}")


def fix_test_dues_fix():
    """Fix test_dues_fix.py"""
    
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/test_dues_fix.py"
    
    if not os.path.exists(filepath):
        print(f"- File not found: {filepath}")
        return
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Apply similar fixes
    # Remove contribution field references
    fields_to_comment = [
        'contribution_mode', 'minimum_contribution', 'suggested_contribution',
        'maximum_contribution', 'enable_income_calculator', 'income_percentage_rate',
        'calculator_description', 'fee_slider_max_multiplier', 'allow_custom_amounts',
        'custom_amount_requires_approval', 'currency'
    ]
    
    for field in fields_to_comment:
        # Comment out field assignments
        content = re.sub(
            rf'^(\s*)(.*\.{field}\s*=.*)$',
            r'\1# \2  # Field moved to dues schedule template',
            content,
            flags=re.MULTILINE
        )
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"✓ Fixed {filepath}")


def main():
    """Main function to fix all test files"""
    print("Fixing test files after membership type field removal...")
    
    fix_test_enhanced_membership_portal()
    fix_test_new_membership_system()
    fix_test_contribution_system()
    fix_test_dues_fix()
    
    print("\nAll test files fixed!")


if __name__ == "__main__":
    main()