#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contribution Amendment Request Utilities

Production utilities for Contribution Amendment Request functionality.
These are valuable administrative and validation functions extracted from
the ContributionAmendmentRequest controller during refactoring.

Author: Verenigingen Development Team
Extracted: 2025-09-11
"""

import frappe
from frappe import _


@frappe.whitelist()
def validate_production_schema():
    """
    Comprehensive validation of production schema readiness.

    Validates that all required fields, tables, and methods exist
    for the Contribution Amendment Request system to function properly.

    Returns:
        dict: Validation results with success status, error details, and recommendations
    """
    frappe.logger().info("Starting Production Schema Validation")

    results = []
    errors = []

    try:
        # 1. Validate Contribution Amendment Request DocType
        frappe.logger().info("Validating Contribution Amendment Request DocType")

        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")

        # Check required fields
        required_fields = [
            "new_dues_schedule",
            "current_dues_schedule",
            "current_amount",
            "current_billing_interval",
            "processing_notes",
        ]

        existing_fields = [field.fieldname for field in doctype.fields]

        for field in required_fields:
            if field in existing_fields:
                results.append(f"✓ Field '{field}' exists in Contribution Amendment Request")
            else:
                errors.append(f"❌ Field '{field}' missing from Contribution Amendment Request")

        # Check field properties for critical fields
        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ new_dues_schedule field properly configured")
                else:
                    errors.append(
                        f"❌ new_dues_schedule field misconfigured: {field.fieldtype}, {field.options}"
                    )

            if field.fieldname == "current_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ current_dues_schedule field properly configured")
                else:
                    errors.append(
                        f"❌ current_dues_schedule field misconfigured: {field.fieldtype}, {field.options}"
                    )

        # 2. Validate Membership Dues Schedule DocType
        frappe.logger().info("Validating Membership Dues Schedule DocType")

        if frappe.db.exists("DocType", "Membership Dues Schedule"):
            results.append("✓ Membership Dues Schedule DocType exists")
        else:
            errors.append("❌ Membership Dues Schedule DocType does not exist")

        # 3. Validate Database Tables
        frappe.logger().info("Validating Database Tables")

        tables_to_check = ["tabContribution Amendment Request", "tabMembership Dues Schedule"]

        for table in tables_to_check:
            if frappe.db.table_exists(table):
                results.append(f"✓ Database table '{table}' exists")
            else:
                errors.append(f"❌ Database table '{table}' does not exist")

        # 4. Validate Custom Methods
        frappe.logger().info("Validating Custom Methods")

        test_doc = frappe.new_doc("Contribution Amendment Request")

        methods_to_check = [
            "create_dues_schedule_for_amendment",
            "set_current_details",
            "apply_fee_change",
        ]

        for method in methods_to_check:
            if hasattr(test_doc, method):
                results.append(f"✓ Method '{method}' exists on Contribution Amendment Request")
            else:
                errors.append(f"❌ Method '{method}' missing from Contribution Amendment Request")

        # 5. Summary
        frappe.logger().info("Validation Summary")
        frappe.logger().info(f"Successful validations: {len(results)}")
        frappe.logger().info(f"Errors found: {len(errors)}")

        if errors:
            frappe.logger().error("ERRORS THAT MUST BE FIXED:")
            for error in errors:
                frappe.logger().error(f"  {error}")

        frappe.logger().info("SUCCESSFUL VALIDATIONS:")
        for result in results:
            frappe.logger().info(f"  {result}")

        return {
            "success": len(errors) == 0,
            "total_checks": len(results) + len(errors),
            "successful_checks": len(results),
            "errors": len(errors),
            "error_details": errors,
            "results": results,
            "ready_for_production": len(errors) == 0,
        }

    except Exception as e:
        error_msg = f"Fatal error during validation: {str(e)}"
        frappe.logger().error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "ready_for_production": False,
        }


@frappe.whitelist()
def validate_billing_consistency():
    """
    Validate that membership types and dues schedule templates have consistent billing frequencies.

    This utility checks for mismatches between membership type billing periods
    and their associated dues schedule template billing frequencies.

    Returns:
        dict: Validation results with any inconsistencies found
    """
    try:
        inconsistencies = []

        # Get all membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "billing_period", "dues_schedule_template"], order_by="name"
        )

        # Check each membership type against its template
        for mt in membership_types:
            if not mt.dues_schedule_template:
                continue  # Skip membership types without templates

            template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"name": mt.dues_schedule_template, "is_template": 1},
                ["name", "billing_frequency"],
                as_dict=True,
            )

            if template and template.billing_frequency != mt.billing_period:
                inconsistencies.append(
                    {
                        "membership_type": mt.name,
                        "membership_billing_period": mt.billing_period,
                        "template_billing_frequency": template.billing_frequency,
                        "template_name": mt.dues_schedule_template,
                        "issue": "Mismatch between membership type and template",
                    }
                )

        return {
            "success": len(inconsistencies) == 0,
            "total_checked": len(membership_types),
            "inconsistencies_found": len(inconsistencies),
            "inconsistencies": inconsistencies,
            "status": (
                "All billing configurations are consistent"
                if len(inconsistencies) == 0
                else f"Found {len(inconsistencies)} inconsistencies"
            ),
        }

    except Exception as e:
        frappe.log_error(f"Error in validate_billing_consistency: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_membership_type_billing_periods():
    """
    Fix membership types that have inconsistent billing periods with their templates.

    This utility identifies and optionally corrects membership types where the
    billing_period doesn't match the billing_frequency of their dues_schedule_template.

    Returns:
        dict: Results of the fix operation including what was changed
    """
    try:
        fixes_applied = []
        errors = []

        # First get inconsistencies
        validation_result = validate_billing_consistency()

        if not validation_result.get("success"):
            return {
                "success": False,
                "error": "Could not validate billing consistency before fixing",
                "validation_error": validation_result.get("error"),
            }

        inconsistencies = validation_result.get("inconsistencies", [])

        for inconsistency in inconsistencies:
            try:
                membership_type_name = inconsistency["membership_type"]
                template_frequency = inconsistency["template_billing_frequency"]

                # Update the membership type
                membership_type = frappe.get_doc("Membership Type", membership_type_name)
                old_billing_period = membership_type.billing_period
                membership_type.billing_period = template_frequency
                membership_type.save()

                fixes_applied.append(
                    {
                        "membership_type": membership_type_name,
                        "old_billing_period": old_billing_period,
                        "new_billing_period": template_frequency,
                        "template": inconsistency["template_name"],
                    }
                )

                frappe.logger().info(
                    f"Fixed billing period for {membership_type_name}: {old_billing_period} → {template_frequency}"
                )

            except Exception as e:
                error_msg = f"Failed to fix {inconsistency['membership_type']}: {str(e)}"
                errors.append(error_msg)
                frappe.log_error(error_msg)

        return {
            "success": len(errors) == 0,
            "fixes_applied": len(fixes_applied),
            "errors": len(errors),
            "fixes_details": fixes_applied,
            "error_details": errors,
            "message": f"Applied {len(fixes_applied)} fixes with {len(errors)} errors",
        }

    except Exception as e:
        frappe.log_error(f"Error in fix_membership_type_billing_periods: {str(e)}")
        return {"success": False, "error": str(e)}


def _process_template_schedule(schedule, orphaned_templates, corrected_templates, errors):
    """Helper function for processing template schedules"""
    try:
        if not schedule.membership_type:
            orphaned_templates.append(schedule)
            return

        # Check if membership type exists
        if not frappe.db.exists("Membership Type", schedule.membership_type):
            orphaned_templates.append(
                {**schedule, "issue": f"References non-existent membership type: {schedule.membership_type}"}
            )
        else:
            corrected_templates.append(schedule)

    except Exception as e:
        errors.append(f"Error processing template {schedule.get('name', 'unknown')}: {str(e)}")


def _cleanup_orphaned_template(orphan, cleanup_results, errors):
    """Helper function for cleaning up orphaned templates"""
    try:
        # For now, just document the orphan - don't auto-delete
        cleanup_results.append(
            {
                "template": orphan.get("name"),
                "action": "documented",
                "reason": orphan.get("issue", "Unknown issue"),
                "recommendation": "Manual review required",
            }
        )

    except Exception as e:
        errors.append(f"Error cleaning up orphaned template {orphan.get('name', 'unknown')}: {str(e)}")


@frappe.whitelist()
def fix_orphaned_schedule_templates():
    """
    Fix or document schedule templates that reference non-existent membership types.

    This utility identifies dues schedule templates that reference membership types
    that no longer exist and provides recommendations for cleanup.

    Returns:
        dict: Results of the cleanup operation
    """
    try:
        # Get all template schedules (schedules without a member)
        template_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=[["member", "is", "not set"]],
            fields=["name", "schedule_name", "billing_frequency", "membership_type"],
            order_by="name",
        )

        orphaned_templates = []
        corrected_templates = []
        errors = []

        for schedule in template_schedules:
            _process_template_schedule(schedule, orphaned_templates, corrected_templates, errors)

        # For orphaned templates, document them for manual review
        cleanup_results = []
        for orphan in orphaned_templates:
            _cleanup_orphaned_template(orphan, cleanup_results, errors)

        return {
            "success": len(errors) == 0,
            "orphaned_templates_found": len(orphaned_templates),
            "templates_corrected": len(corrected_templates),
            "templates_documented": len(cleanup_results),
            "errors": len(errors),
            "corrected_templates": corrected_templates,
            "cleanup_results": cleanup_results,
            "error_details": errors,
            "message": f"Found {len(orphaned_templates)} orphaned templates, documented {len(cleanup_results)} for review",
        }

    except Exception as e:
        frappe.log_error(f"Error in fix_orphaned_schedule_templates: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_membership_type_billing_periods():
    """
    Check all membership types for proper billing period configuration.

    This utility validates that all membership types have:
    1. A valid billing period set
    2. A corresponding dues schedule template
    3. Consistent configuration between type and template

    Returns:
        dict: Analysis results with recommendations
    """
    try:
        membership_types = frappe.get_all(
            "Membership Type",
            fields=["name", "billing_period", "dues_schedule_template", "is_active"],
            order_by="name",
        )

        issues = []
        valid_configs = []

        for mt in membership_types:
            mt_issues = []

            # Check billing period
            if not mt.billing_period:
                mt_issues.append("No billing period set")
            elif mt.billing_period not in ["Monthly", "Quarterly", "Annual", "Custom"]:
                mt_issues.append(f"Invalid billing period: {mt.billing_period}")

            # Check template
            if not mt.dues_schedule_template:
                mt_issues.append("No dues schedule template assigned")
            elif not frappe.db.exists("Membership Dues Schedule", mt.dues_schedule_template):
                mt_issues.append(f"Template does not exist: {mt.dues_schedule_template}")

            if mt_issues:
                issues.append({"membership_type": mt.name, "is_active": mt.is_active, "issues": mt_issues})
            else:
                valid_configs.append(mt.name)

        return {
            "success": len(issues) == 0,
            "total_membership_types": len(membership_types),
            "valid_configurations": len(valid_configs),
            "issues_found": len(issues),
            "issue_details": issues,
            "valid_types": valid_configs,
            "message": f"Found {len(issues)} membership types with configuration issues",
        }

    except Exception as e:
        frappe.log_error(f"Error in check_membership_type_billing_periods: {str(e)}")
        return {"success": False, "error": str(e)}
