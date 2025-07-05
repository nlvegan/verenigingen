#!/usr/bin/env python3
"""
Check the status of all email templates in the verenigingen app
This script verifies which templates exist and their content status
"""


import frappe


def check_email_template_status():
    """Check the status of all email templates expected by the verenigingen app"""

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Define all expected email templates
    expected_templates = [
        # Membership system templates
        "membership_application_approved",
        "membership_application_rejected",
        "membership_rejection_incomplete",
        "membership_rejection_ineligible",
        "membership_rejection_duplicate",
        "membership_renewal_reminder",
        "membership_expired",
        "membership_welcome",
        "membership_payment_received",
        "membership_payment_failed",
        "membership_auto_renewal_notification",
        "membership_orphaned_records_notification",
        # Termination templates
        "Termination Approval Required",
        "Termination Execution Notice",
        # Expense templates
        "expense_approval_request",
        "expense_approved",
        "expense_rejected",
        # Donation templates
        "donation_confirmation",
        "donation_payment_confirmation",
        "anbi_tax_receipt",
        # Other templates
        "termination_overdue_notification",
        "member_contact_request_received",
    ]

    print("=" * 80)
    print("EMAIL TEMPLATE STATUS CHECK")
    print("=" * 80)
    print()

    # Check each template
    existing_count = 0
    missing_count = 0
    empty_count = 0

    print("Template Name                                      | Status    | Content")
    print("-" * 80)

    for template_name in expected_templates:
        try:
            if frappe.db.exists("Email Template", template_name):
                template = frappe.get_doc("Email Template", template_name)

                # Check if template has content
                has_subject = bool(template.subject and template.subject.strip())
                has_response = bool(template.response and template.response.strip())

                if has_subject and has_response:
                    content_status = "OK"
                    existing_count += 1
                else:
                    content_status = "EMPTY"
                    empty_count += 1
                    existing_count += 1

                status = "EXISTS"
                enabled_status = " (E)" if template.enabled else " (D)"

                print(f"{template_name:<50} | {status:<9} | {content_status}{enabled_status}")
            else:
                print(f"{template_name:<50} | MISSING   | -")
                missing_count += 1

        except Exception as e:
            print(f"{template_name:<50} | ERROR     | {str(e)[:20]}")

    print("-" * 80)
    print()
    print("SUMMARY:")
    print(f"  Total Expected:     {len(expected_templates)}")
    print(f"  Existing:          {existing_count}")
    print(f"  Missing:           {missing_count}")
    print(f"  Empty Content:     {empty_count}")
    print(f"  Properly Set Up:   {existing_count - empty_count}")
    print()

    # Check for additional templates not in our list
    all_templates = frappe.get_all(
        "Email Template",
        filters=[
            ["name", "like", "%membership%"],
            "or",
            ["name", "like", "%member%"],
            "or",
            [
                "name",
                "in",
                [
                    "expense_approval_request",
                    "expense_approved",
                    "expense_rejected",
                    "donation_confirmation",
                    "donation_payment_confirmation",
                    "anbi_tax_receipt",
                    "termination_overdue_notification",
                    "Termination Approval Required",
                    "Termination Execution Notice",
                ],
            ],
        ],
        fields=["name"],
    )

    additional_templates = []
    for template in all_templates:
        if template.name not in expected_templates:
            additional_templates.append(template.name)

    if additional_templates:
        print("ADDITIONAL TEMPLATES FOUND (not in expected list):")
        for template in additional_templates:
            print(f"  - {template}")
        print()

    # Provide recommendations
    if missing_count > 0:
        print("RECOMMENDATIONS:")
        print("1. Import the email_template.json fixture file:")
        print("   bench --site dev.veganisme.net import-fixtures --app verenigingen")
        print()
        print("2. Or create templates manually:")
        print("   bench execute verenigingen.api.email_template_manager.create_comprehensive_email_templates")
        print()

    if empty_count > 0:
        print("WARNING: Some templates exist but have no content!")
        print("These templates need to be updated with proper email content.")
        print()

    frappe.destroy()

    return {
        "total": len(expected_templates),
        "existing": existing_count,
        "missing": missing_count,
        "empty": empty_count,
        "working": existing_count - empty_count,
    }


if __name__ == "__main__":
    check_email_template_status()
