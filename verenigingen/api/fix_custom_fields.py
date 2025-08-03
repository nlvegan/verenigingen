"""
Fix custom fields: Create missing coverage fields and fix Module assignments
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_sales_invoice_coverage_fields():
    """Create custom coverage fields for Sales Invoice"""
    frappe.only_for("System Manager")

    print("Creating Sales Invoice coverage fields...")

    # Coverage Start Date field
    coverage_start_field = {
        "dt": "Sales Invoice",
        "fieldname": "custom_coverage_start_date",
        "label": "Coverage Start Date",
        "fieldtype": "Date",
        "description": "Start date of the membership dues coverage period",
        "insert_after": "due_date",
        "module": "Verenigingen",
        "read_only": 1,
        "no_copy": 1,
        "allow_on_submit": 1,
    }

    # Coverage End Date field
    coverage_end_field = {
        "dt": "Sales Invoice",
        "fieldname": "custom_coverage_end_date",
        "label": "Coverage End Date",
        "fieldtype": "Date",
        "description": "End date of the membership dues coverage period",
        "insert_after": "custom_coverage_start_date",
        "module": "Verenigingen",
        "read_only": 1,
        "no_copy": 1,
        "allow_on_submit": 1,
    }

    results = []

    try:
        # Check if fields already exist
        existing_start = frappe.db.exists(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_coverage_start_date"}
        )

        existing_end = frappe.db.exists(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_coverage_end_date"}
        )

        if not existing_start:
            create_custom_field("Sales Invoice", coverage_start_field)
            results.append("✅ Created custom_coverage_start_date field")
        else:
            results.append("ℹ️ custom_coverage_start_date field already exists")

        if not existing_end:
            create_custom_field("Sales Invoice", coverage_end_field)
            results.append("✅ Created custom_coverage_end_date field")
        else:
            results.append("ℹ️ custom_coverage_end_date field already exists")

    except Exception as e:
        error_msg = f"❌ Error creating coverage fields: {e}"
        results.append(error_msg)
        frappe.log_error(f"Error creating coverage fields: {e}")

    return results


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def fix_custom_field_modules():
    """Fix Module field assignments for existing custom fields"""
    frappe.only_for("System Manager")

    results = []
    results.append("Fixing Module field assignments for custom fields...")

    # Get all custom fields without proper module assignment
    custom_fields = frappe.get_all(
        "Custom Field", filters={"module": ["in", ["", None]]}, fields=["name", "dt", "fieldname", "label"]
    )

    results.append(f"Found {len(custom_fields)} custom fields without proper module assignment")

    # Define module mapping based on field patterns
    module_mapping = {
        # Verenigingen fields
        "custom_coverage_": "Verenigingen",
        "custom_membership_": "Verenigingen",
        "custom_dues_": "Verenigingen",
        "custom_contribution_": "Verenigingen",
        "custom_paying_for_": "Verenigingen",
        "custom_payment_relationship": "Verenigingen",
        "custom_chapter_": "Verenigingen",
        "custom_volunteer_": "Verenigingen",
        "custom_member_": "Verenigingen",
        "custom_sepa_": "Verenigingen",
        "custom_mandate_": "Verenigingen",
        # E Boekhouden fields
        "custom_ebh_": "E-Boekhouden",
        "custom_e_boekhouden_": "E-Boekhouden",
        "custom_relation_": "E-Boekhouden",
        "custom_gb_": "E-Boekhouden",
        "custom_mutatie_": "E-Boekhouden",
    }

    updated_count = 0

    for field in custom_fields:
        fieldname = field.fieldname.lower()
        module_to_assign = None

        # Check patterns to determine module
        for pattern, module in module_mapping.items():
            if fieldname.startswith(pattern):
                module_to_assign = module
                break

        # Default assignment for verenigingen app custom fields
        if not module_to_assign and fieldname.startswith("custom_"):
            # If it's on a core doctype, likely belongs to Verenigingen
            core_doctypes = [
                "Sales Invoice",
                "Customer",
                "Supplier",
                "Member",
                "Membership",
                "Volunteer",
                "Chapter",
                "Team",
                "Payment Entry",
                "Journal Entry",
            ]
            if field.dt in core_doctypes:
                module_to_assign = "Verenigingen"
            else:
                # If it's on a verenigingen doctype, assign to Verenigingen
                module_to_assign = "Verenigingen"

        if module_to_assign:
            try:
                frappe.db.set_value("Custom Field", field.name, "module", module_to_assign)
                results.append(f"✅ Fixed {field.dt}.{field.fieldname} → {module_to_assign}")
                updated_count += 1
            except Exception as e:
                results.append(f"❌ Error updating {field.name}: {e}")

    results.append(f"✅ Updated {updated_count} custom fields with proper module assignments")
    return results


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def create_other_missing_custom_fields():
    """Create other missing custom fields mentioned in documentation"""
    frappe.only_for("System Manager")

    results = []
    results.append("Creating other missing custom fields...")

    additional_fields = [
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_membership_dues_schedule",
            "label": "Membership Dues Schedule",
            "fieldtype": "Link",
            "options": "Membership Dues Schedule",
            "description": "Links invoice to specific dues schedule",
            "insert_after": "custom_coverage_end_date",
            "module": "Verenigingen",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_contribution_mode",
            "label": "Contribution Mode",
            "fieldtype": "Select",
            "options": "Tier\nCalculator\nCustom\nFixed",
            "description": "Tracks contribution type",
            "insert_after": "custom_membership_dues_schedule",
            "module": "Verenigingen",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_paying_for_member",
            "label": "Paying for Member",
            "fieldtype": "Link",
            "options": "Member",
            "description": "Links to member being paid for (parent/spouse scenarios)",
            "insert_after": "custom_contribution_mode",
            "module": "Verenigingen",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_payment_relationship",
            "label": "Payment Relationship",
            "fieldtype": "Select",
            "options": "Self\nParent\nSpouse\nGuardian\nPartner\nOther",
            "description": "Relationship type for payment",
            "insert_after": "custom_paying_for_member",
            "module": "Verenigingen",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "membership",
            "label": "Membership",
            "fieldtype": "Link",
            "options": "Membership",
            "description": "Links invoice to specific membership record",
            "insert_after": "member",
            "module": "Verenigingen",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
        },
    ]

    for field_def in additional_fields:
        try:
            existing = frappe.db.exists(
                "Custom Field", {"dt": field_def["dt"], "fieldname": field_def["fieldname"]}
            )

            if not existing:
                create_custom_field(field_def["dt"], field_def)
                results.append(f"✅ Created {field_def['fieldname']} field")
            else:
                results.append(f"ℹ️ {field_def['fieldname']} field already exists")

        except Exception as e:
            results.append(f"❌ Error creating {field_def['fieldname']}: {e}")

    return results


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_sales_invoice_membership_field():
    """Check if membership field exists in Sales Invoice"""
    frappe.only_for("System Manager")

    try:
        meta = frappe.get_meta("Sales Invoice")
        all_fields = [f.fieldname for f in meta.fields]
        membership_fields = [f for f in all_fields if "member" in f.lower()]

        # Also check if membership field specifically exists
        has_membership = "membership" in all_fields

        return {
            "success": True,
            "has_membership_field": has_membership,
            "membership_related_fields": membership_fields,
            "total_fields": len(all_fields),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_sales_invoice_custom_fields():
    """Get all custom fields for Sales Invoice to debug field validation errors"""
    frappe.only_for("System Manager")

    try:
        fields = frappe.get_all(
            "Custom Field",
            filters={"dt": "Sales Invoice"},
            fields=["fieldname", "label", "fieldtype", "options"],
            order_by="fieldname",
        )

        results = [f"Found {len(fields)} custom fields for Sales Invoice:"]
        for field in fields:
            results.append(f"  - {field.fieldname}: {field.label} ({field.fieldtype})")
            if field.options:
                results.append(f"    Options: {field.options}")

        return {"success": True, "fields": fields, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def fix_all_custom_fields():
    """Main function to execute all fixes"""
    frappe.only_for("System Manager")

    all_results = []

    try:
        all_results.append("🔧 Starting Custom Field Creation and Module Fix...")

        # Create coverage fields first
        coverage_results = create_sales_invoice_coverage_fields()
        all_results.extend(coverage_results)

        # Create other missing fields
        other_results = create_other_missing_custom_fields()
        all_results.extend(other_results)

        # Fix module assignments
        module_results = fix_custom_field_modules()
        all_results.extend(module_results)

        # Commit changes
        frappe.db.commit()

        all_results.append("🎉 All custom field operations completed successfully!")
        all_results.append("📋 Summary:")
        all_results.append("- Created missing coverage fields for Sales Invoice")
        all_results.append("- Created additional membership-related fields")
        all_results.append("- Fixed module assignments for existing custom fields")
        all_results.append("⚠️ You may need to:")
        all_results.append("1. Clear cache: bench clear-cache")
        all_results.append("2. Reload doctypes: bench reload-doc")
        all_results.append("3. Restart services: bench restart")

    except Exception as e:
        error_msg = f"❌ Error in main execution: {e}"
        all_results.append(error_msg)
        frappe.log_error(f"Custom field creation error: {e}")

    return {"success": True, "results": all_results}
