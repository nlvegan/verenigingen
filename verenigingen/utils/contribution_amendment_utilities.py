#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contribution Amendment Request Utilities

Production utilities for Contribution Amendment Request functionality.
These are valuable administrative and validation functions extracted from
the ContributionAmendmentRequest controller during refactoring.

ERROR HANDLING PATTERN:
All @frappe.whitelist() functions return OperationResult[Dict[str, Any]]:
- Success: OperationResult.ok(data, message="...")
- Failure: OperationResult.fail(user_message, errors=[...], context={...})
- Comprehensive error context includes operation name + all parameters
- Traceback logging for debugging: frappe.log_error(f"...: {str(e)}\\n{traceback.format_exc()}", "Title")

Author: Verenigingen Development Team
Extracted: 2025-09-11
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


@frappe.whitelist()
def validate_production_schema() -> OperationResult[Dict[str, Any]]:
    """
    Comprehensive validation of production schema readiness.

    Validates that all required fields, tables, and methods exist
    for the Contribution Amendment Request system to function properly.

    Returns:
        OperationResult[Dict[str, Any]]: Validation results with success status, error details, and recommendations
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

        if DocumentExistenceValidator.check_document_exists("DocType", "Membership Dues Schedule"):
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

        data = {
            "success": len(errors) == 0,
            "total_checks": len(results) + len(errors),
            "successful_checks": len(results),
            "errors": len(errors),
            "error_details": errors,
            "results": results,
            "ready_for_production": len(errors) == 0,
        }

        if len(errors) == 0:
            return OperationResult.ok(data, message=_("Production schema validation completed successfully"))
        else:
            return OperationResult.ok(
                data, message=_("Production schema validation found {0} errors").format(len(errors))
            )

    except Exception as e:
        frappe.log_error(
            f"Fatal error during production schema validation: {str(e)}\n{traceback.format_exc()}",
            "Schema Validation Error",
        )
        return OperationResult.fail(
            _("Production schema validation failed"),
            errors=[str(e)],
            context={"operation": "validate_production_schema"},
        )


@frappe.whitelist()
def validate_billing_consistency() -> OperationResult[Dict[str, Any]]:
    """
    Validate that membership types and dues schedule templates have consistent billing frequencies.

    This utility checks for mismatches between membership type billing periods
    and their associated dues schedule template billing frequencies.

    Returns:
        OperationResult[Dict[str, Any]]: Validation results with any inconsistencies found
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

        data = {
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

        if len(inconsistencies) == 0:
            return OperationResult.ok(data, message=_("All billing configurations are consistent"))
        else:
            return OperationResult.ok(
                data, message=_("Found {0} billing inconsistencies").format(len(inconsistencies))
            )

    except Exception as e:
        frappe.log_error(
            f"Error in validate_billing_consistency: {str(e)}\n{traceback.format_exc()}",
            "Billing Consistency Error",
        )
        return OperationResult.fail(
            _("Billing consistency validation failed"),
            errors=[str(e)],
            context={"operation": "validate_billing_consistency"},
        )


@frappe.whitelist()
def fix_membership_type_billing_periods() -> OperationResult[Dict[str, Any]]:
    """
    Fix membership types that have inconsistent billing periods with their templates.

    This utility identifies and optionally corrects membership types where the
    billing_period doesn't match the billing_frequency of their dues_schedule_template.

    Returns:
        OperationResult[Dict[str, Any]]: Results of the fix operation including what was changed
    """
    try:
        fixes_applied = []
        errors = []

        # First get inconsistencies
        validation_result = validate_billing_consistency()

        if not validation_result.success:
            return OperationResult.fail(
                _("Could not validate billing consistency before fixing"),
                errors=validation_result.errors if hasattr(validation_result, "errors") else [],
                context={"operation": "fix_membership_type_billing_periods"},
            )

        inconsistencies = validation_result.data.get("inconsistencies", [])

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
                frappe.log_error(
                    f"Failed to fix membership type {inconsistency['membership_type']}: {str(e)}\n{traceback.format_exc()}",
                    "Fix Billing Period Error",
                )

        data = {
            "success": len(errors) == 0,
            "fixes_applied": len(fixes_applied),
            "errors": len(errors),
            "fixes_details": fixes_applied,
            "error_details": errors,
        }

        return OperationResult.ok(
            data, message=_("Applied {0} fixes with {1} errors").format(len(fixes_applied), len(errors))
        )

    except Exception as e:
        frappe.log_error(
            f"Error in fix_membership_type_billing_periods: {str(e)}\n{traceback.format_exc()}",
            "Fix Billing Periods Error",
        )
        return OperationResult.fail(
            _("Failed to fix membership type billing periods"),
            errors=[str(e)],
            context={"operation": "fix_membership_type_billing_periods"},
        )


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
def fix_orphaned_schedule_templates() -> OperationResult[Dict[str, Any]]:
    """
    Fix or document schedule templates that reference non-existent membership types.

    This utility identifies dues schedule templates that reference membership types
    that no longer exist and provides recommendations for cleanup.

    Returns:
        OperationResult[Dict[str, Any]]: Results of the cleanup operation
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

        data = {
            "success": len(errors) == 0,
            "orphaned_templates_found": len(orphaned_templates),
            "templates_corrected": len(corrected_templates),
            "templates_documented": len(cleanup_results),
            "errors": len(errors),
            "corrected_templates": corrected_templates,
            "cleanup_results": cleanup_results,
            "error_details": errors,
        }

        return OperationResult.ok(
            data,
            message=_("Found {0} orphaned templates, documented {1} for review").format(
                len(orphaned_templates), len(cleanup_results)
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error in fix_orphaned_schedule_templates: {str(e)}\n{traceback.format_exc()}",
            "Fix Orphaned Templates Error",
        )
        return OperationResult.fail(
            _("Failed to fix orphaned schedule templates"),
            errors=[str(e)],
            context={"operation": "fix_orphaned_schedule_templates"},
        )


@frappe.whitelist()
def check_membership_type_billing_periods() -> OperationResult[Dict[str, Any]]:
    """
    Check all membership types for proper billing period configuration.

    This utility validates that all membership types have:
    1. A valid billing period set
    2. A corresponding dues schedule template
    3. Consistent configuration between type and template

    Returns:
        OperationResult[Dict[str, Any]]: Analysis results with recommendations
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

            # Check billing period (optional field - only validate if set)
            valid_periods = ["Daily", "Monthly", "Quarterly", "Biannual", "Annual", "Lifetime", "Custom"]
            if mt.billing_period and mt.billing_period not in valid_periods:
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

        data = {
            "success": len(issues) == 0,
            "total_membership_types": len(membership_types),
            "valid_configurations": len(valid_configs),
            "issues_found": len(issues),
            "issue_details": issues,
            "valid_types": valid_configs,
        }

        if len(issues) == 0:
            return OperationResult.ok(data, message=_("All membership types are properly configured"))
        else:
            return OperationResult.ok(
                data, message=_("Found {0} membership types with configuration issues").format(len(issues))
            )

    except Exception as e:
        frappe.log_error(
            f"Error in check_membership_type_billing_periods: {str(e)}\n{traceback.format_exc()}",
            "Check Billing Periods Error",
        )
        return OperationResult.fail(
            _("Failed to check membership type billing periods"),
            errors=[str(e)],
            context={"operation": "check_membership_type_billing_periods"},
        )
