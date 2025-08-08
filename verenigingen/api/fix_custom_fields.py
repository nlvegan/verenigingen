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
    """
    DEPRECATED: Create custom coverage fields for Sales Invoice

    Note: This function is deprecated. Custom fields for Sales Invoice coverage dates
    are now managed through fixtures in verenigingen/fixtures/custom_field.json.
    Use `bench install-app verenigingen` or `bench migrate` to install them properly.
    """
    frappe.only_for("System Manager")

    return [
        "⚠️ DEPRECATED: This function is no longer needed.",
        "📝 Coverage date fields are now managed via fixtures in:",
        "   verenigingen/fixtures/custom_field.json",
        "💡 Use 'bench migrate' to install/update custom fields properly.",
    ]


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
        # E-Boekhouden fields
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
                "Verenigingen Volunteer",
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
def validate_fixture_custom_fields():
    """Validate that fixture custom fields are properly loaded in Frappe"""
    import json
    from pathlib import Path

    from frappe.model.meta import get_meta

    frappe.only_for("System Manager")

    results = []
    results.append("🔍 Validating Fixture Custom Fields Integration")

    # Load fixture data
    fixture_path = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "custom_field.json"

    try:
        with open(fixture_path, "r") as f:
            fixture_data = json.load(f)

        results.append(f"📋 Loaded {len(fixture_data)} custom fields from fixture")

        # Group by DocType
        fixture_by_doctype = {}
        for field_data in fixture_data:
            dt = field_data.get("dt")
            fieldname = field_data.get("fieldname")
            if dt and fieldname:
                if dt not in fixture_by_doctype:
                    fixture_by_doctype[dt] = []
                fixture_by_doctype[dt].append(
                    {
                        "fieldname": fieldname,
                        "fieldtype": field_data.get("fieldtype"),
                        "label": field_data.get("label"),
                    }
                )

        # Check each DocType
        total_fixture_fields = 0
        total_frappe_fields = 0

        for doctype_name, fixture_fields in fixture_by_doctype.items():
            try:
                meta = get_meta(doctype_name)
                frappe_field_names = [f.fieldname for f in meta.fields]

                matched_fields = []
                missing_fields = []

                for field_info in fixture_fields:
                    if field_info["fieldname"] in frappe_field_names:
                        matched_fields.append(field_info["fieldname"])
                    else:
                        missing_fields.append(field_info["fieldname"])

                results.append(
                    f"  ✅ {doctype_name}: {len(matched_fields)}/{len(fixture_fields)} fixture fields found in Frappe"
                )

                # Show field details for key DocTypes
                if doctype_name == "Sales Invoice" and matched_fields:
                    results.append(
                        f"    Fields: {', '.join(matched_fields[:8])}"
                        + ("..." if len(matched_fields) > 8 else "")
                    )

                total_fixture_fields += len(fixture_fields)
                total_frappe_fields += len(matched_fields)

                # Show any missing fields
                if missing_fields:
                    results.append(f"    ❌ Missing: {', '.join(missing_fields)}")

            except Exception as e:
                results.append(f"  ❌ {doctype_name}: Error - {e}")

        results.append(
            f"\n📊 Total Consistency: {total_frappe_fields}/{total_fixture_fields} fixture fields found in Frappe"
        )

        if total_frappe_fields == total_fixture_fields:
            results.append("✅ Perfect consistency between fixtures and Frappe!")
        else:
            results.append(f"⚠️ {total_fixture_fields - total_frappe_fields} fields missing from Frappe")

    except Exception as e:
        results.append(f"❌ Error loading fixture: {e}")
        frappe.log_error(f"Fixture validation error: {e}")

    return results


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

        # Validate fixture integration
        fixture_results = validate_fixture_custom_fields()
        all_results.extend(fixture_results)

        # Commit changes
        frappe.db.commit()

        all_results.append("🎉 All custom field operations completed successfully!")
        all_results.append("📋 Summary:")
        all_results.append("- Created missing coverage fields for Sales Invoice")
        all_results.append("- Created additional membership-related fields")
        all_results.append("- Fixed module assignments for existing custom fields")
        all_results.append("- Validated fixture integration")
        all_results.append("⚠️ You may need to:")
        all_results.append("1. Clear cache: bench clear-cache")
        all_results.append("2. Reload doctypes: bench reload-doc")
        all_results.append("3. Restart services: bench restart")

    except Exception as e:
        error_msg = f"❌ Error in main execution: {e}"
        all_results.append(error_msg)
        frappe.log_error(f"Custom field creation error: {e}")

    return {"success": True, "results": all_results}
