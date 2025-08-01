#!/usr/bin/env python3
"""
Add custom fields to Sales Invoice for membership dues schedule tracking
Run via: bench --site dev.veganisme.net execute verenigingen.fixtures.add_sales_invoice_fields.setup_dues_fields
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_dues_fields():
    """Add custom fields to Sales Invoice for membership dues schedule tracking"""

    # Check if fields already exist
    sales_invoice_meta = frappe.get_meta("Sales Invoice")
    existing_fields = [field.fieldname for field in sales_invoice_meta.fields]

    if "custom_membership_dues_schedule" in existing_fields and "is_membership_invoice" in existing_fields:
        print("✅ Custom fields already exist!")
        return verify_fields()

    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "membership_dues_section",
                "label": "Membership Dues Information",
                "fieldtype": "Section Break",
                "insert_after": "customer_section",
                "collapsible": 1,
                "depends_on": "eval:doc.is_membership_invoice",
            },
            {
                "fieldname": "is_membership_invoice",
                "label": "Is Membership Invoice",
                "fieldtype": "Check",
                "insert_after": "membership_dues_section",
                "default": 0,
                "module": "Verenigingen",
            },
            {
                "fieldname": "membership",
                "label": "Membership",
                "fieldtype": "Link",
                "options": "Membership",
                "insert_after": "is_membership_invoice",
                "depends_on": "eval:doc.is_membership_invoice",
                "module": "Verenigingen",
            },
            {
                "fieldname": "member",
                "label": "Member",
                "fieldtype": "Link",
                "options": "Member",
                "insert_after": "membership",
                "depends_on": "eval:doc.is_membership_invoice",
                "module": "Verenigingen",
            },
            {
                "fieldname": "custom_membership_dues_schedule",
                "label": "Membership Dues Schedule",
                "fieldtype": "Link",
                "options": "Membership Dues Schedule",
                "insert_after": "membership_dues_section",
                "read_only": 0,
                "allow_on_submit": 0,
                "module": "Verenigingen",
            },
            {
                "fieldname": "dues_schedule_column_break",
                "fieldtype": "Column Break",
                "insert_after": "custom_membership_dues_schedule",
            },
            {
                "fieldname": "custom_contribution_mode",
                "label": "Contribution Mode",
                "fieldtype": "Data",
                "insert_after": "dues_schedule_column_break",
                "read_only": 1,
                "module": "Verenigingen",
            },
            {
                "fieldname": "coverage_period_section",
                "label": "Coverage Period",
                "fieldtype": "Section Break",
                "insert_after": "custom_contribution_mode",
                "collapsible": 1,
                "depends_on": "eval:doc.custom_membership_dues_schedule",
            },
            {
                "fieldname": "custom_coverage_start_date",
                "label": "Coverage Start Date",
                "fieldtype": "Date",
                "insert_after": "coverage_period_section",
                "read_only": 0,
                "module": "Verenigingen",
            },
            {
                "fieldname": "coverage_period_column_break",
                "fieldtype": "Column Break",
                "insert_after": "custom_coverage_start_date",
            },
            {
                "fieldname": "custom_coverage_end_date",
                "label": "Coverage End Date",
                "fieldtype": "Date",
                "insert_after": "coverage_period_column_break",
                "read_only": 0,
                "module": "Verenigingen",
            },
            # Partner payment fields for cases where parent/spouse pays
            {
                "fieldname": "partner_payment_section",
                "label": "Partner Payment Information",
                "fieldtype": "Section Break",
                "insert_after": "custom_coverage_end_date",
                "collapsible": 1,
                "depends_on": "eval:doc.member && doc.customer != doc.member",
            },
            {
                "fieldname": "custom_paying_for_member",
                "label": "Paying for Member",
                "fieldtype": "Link",
                "options": "Member",
                "insert_after": "partner_payment_section",
                "read_only": 0,
                "description": "If this invoice is paid by someone other than the member (e.g., parent, spouse)",
                "module": "Verenigingen",
            },
            {
                "fieldname": "partner_payment_column_break",
                "fieldtype": "Column Break",
                "insert_after": "custom_paying_for_member",
            },
            {
                "fieldname": "custom_payment_relationship",
                "label": "Payment Relationship",
                "fieldtype": "Select",
                "options": "\nParent\nSpouse\nPartner\nGuardian\nOther Family Member\nOrganization\nOther",
                "insert_after": "partner_payment_column_break",
                "depends_on": "eval:doc.custom_paying_for_member",
                "module": "Verenigingen",
            },
        ]
    }

    try:
        # Create the custom fields
        create_custom_fields(custom_fields, update=True)

        frappe.db.commit()  # Ensure fields are saved
        frappe.clear_cache(doctype="Sales Invoice")  # Clear cache to load new fields

        print("✅ Custom fields added successfully!")

        return verify_fields()

    except Exception as e:
        frappe.db.rollback()
        print(f"❌ Error adding custom fields: {str(e)}")
        return False


def verify_fields():
    """Verify that the custom fields were added correctly"""
    # Refresh meta to get latest fields
    frappe.clear_cache(doctype="Sales Invoice")
    sales_invoice_meta = frappe.get_meta("Sales Invoice", cached=False)

    expected_fields = [
        "membership_dues_section",
        "is_membership_invoice",
        "membership",
        "member",
        "custom_membership_dues_schedule",
        "custom_contribution_mode",
        "coverage_period_section",
        "custom_coverage_start_date",
        "custom_coverage_end_date",
        "partner_payment_section",
        "custom_paying_for_member",
        "custom_payment_relationship",
    ]

    existing_fields = [field.fieldname for field in sales_invoice_meta.fields]

    print("\n📋 Verification Results:")
    all_found = True
    for field in expected_fields:
        if field in existing_fields:
            print(f"✅ {field} - Found")
        else:
            print(f"❌ {field} - Missing")
            all_found = False

    if all_found:
        print("\n🎉 All custom fields successfully added to Sales Invoice!")
        print("Enhanced SEPA Processor can now track dues schedule relationships.")

    return all_found


@frappe.whitelist()
def get_custom_field_status():
    """API to check custom field status"""
    sales_invoice_meta = frappe.get_meta("Sales Invoice", cached=False)
    existing_fields = [field.fieldname for field in sales_invoice_meta.fields]

    required_fields = [
        "is_membership_invoice",
        "membership",
        "member",
        "custom_membership_dues_schedule",
        "custom_coverage_start_date",
        "custom_coverage_end_date",
    ]

    status = {
        "all_present": all(field in existing_fields for field in required_fields),
        "existing_fields": [field for field in required_fields if field in existing_fields],
        "missing_fields": [field for field in required_fields if field not in existing_fields],
    }

    return status


if __name__ == "__main__":
    setup_dues_fields()
