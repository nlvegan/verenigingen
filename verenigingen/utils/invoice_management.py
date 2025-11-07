#!/usr/bin/env python3
"""
Invoice Management Utility for Verenigingen Administrators

Provides comprehensive invoice generation and management capabilities
with proper error handling and orphaned schedule detection.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def bulk_generate_dues_invoices(filter_criteria=None, dry_run=True, max_invoices=50):
    """
    Generate invoices for multiple dues schedules with comprehensive filtering and validation

    Args:
        filter_criteria (dict): Optional filters for schedule selection
        dry_run (bool): If True, only shows what would be processed without generating invoices
        max_invoices (int): Maximum number of invoices to generate in one run

    Returns:
        dict: Results of bulk invoice generation
    """

    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("Insufficient permissions for bulk invoice generation"))

    try:
        results = {
            "success": True,
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
            "filter_criteria": filter_criteria or {},
            "schedules_found": 0,
            "eligible_schedules": 0,
            "invoices_generated": 0,
            "orphaned_schedules": 0,
            "errors": [],
            "processed_schedules": [],
            "orphaned_details": [],
            # Frontend-expected fields
            "total_active_schedules": 0,
            "due_now": 0,
            "upcoming_schedules_sample": [],
            "generated_invoices": [],  # Track which invoices were actually generated
        }

        # Build filter criteria for dues schedules
        base_filters = {"status": "Active", "auto_generate": 1, "is_template": 0}

        # Add custom filters if provided
        if filter_criteria:
            base_filters.update(filter_criteria)

        # Add date-based filtering (due now or within specified days)
        days_ahead = filter_criteria.get("days_ahead", 7) if filter_criteria else 7
        cutoff_date = add_days(today(), days_ahead)
        base_filters["next_invoice_date"] = ["<=", cutoff_date]

        # Get dues schedules that need invoice generation
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=base_filters,
            fields=[
                "name",
                "member",
                "member_name",
                "next_invoice_date",
                "billing_frequency",
                "dues_rate",
                "status",
            ],
            order_by="next_invoice_date",
            limit=max_invoices * 2,  # Get more than needed to account for filtering
        )

        results["schedules_found"] = len(schedules)
        results["total_active_schedules"] = len(schedules)  # Frontend expects this field

        # Count schedules due now (today or past due)
        due_now_count = 0
        upcoming_sample = []

        for schedule_data in schedules:
            if schedule_data.next_invoice_date and DateRangeValidator.is_date_today_or_past(
                schedule_data.next_invoice_date
            ):
                due_now_count += 1

            # Add to upcoming sample (first 10 for display)
            if len(upcoming_sample) < 10:
                upcoming_sample.append(
                    {
                        "name": schedule_data.name,
                        "member_name": schedule_data.member_name or "Unknown",
                        "next_invoice_date": schedule_data.next_invoice_date,
                        "dues_rate": schedule_data.dues_rate or 0,
                    }
                )

        results["due_now"] = due_now_count
        results["upcoming_schedules_sample"] = upcoming_sample

        if not schedules:
            results["message"] = "No dues schedules found matching the criteria"
            return results

        # Process each schedule
        processed = 0
        for schedule_data in schedules:
            if processed >= max_invoices:
                break

            try:
                schedule = frappe.get_doc(
                    "Membership Dues Schedule", schedule_data.name, ignore_validate=True
                )

                # Check if schedule is orphaned
                if schedule.is_orphaned():
                    results["orphaned_schedules"] += 1
                    results["orphaned_details"].append(
                        {
                            "schedule": schedule_data.name,
                            "member": schedule_data.member,
                            "member_name": schedule_data.member_name,
                            "issue": "References non-existent member",
                        }
                    )
                    continue

                # Check if invoice can be generated
                can_generate, reason = schedule.can_generate_invoice()

                schedule_result = {
                    "schedule": schedule_data.name,
                    "member": schedule_data.member,
                    "member_name": schedule_data.member_name,
                    "next_invoice_date": schedule_data.next_invoice_date,
                    "amount": flt(schedule_data.dues_rate, 2),
                    "can_generate": can_generate,
                    "reason": reason,
                }

                if can_generate:
                    results["eligible_schedules"] += 1

                    if not dry_run:
                        try:
                            # Generate the invoice
                            invoice = schedule.generate_invoice(force=False)
                            if invoice:
                                schedule_result["success"] = True
                                invoice_name = invoice.name if hasattr(invoice, "name") else str(invoice)
                                schedule_result["invoice"] = invoice_name
                                results["invoices_generated"] += 1
                                # Track generated invoice for frontend display
                                results["generated_invoices"].append(
                                    {
                                        "invoice": invoice_name,
                                        "member_name": schedule_data.member_name or "Unknown",
                                        "amount": schedule_data.dues_rate or 0,
                                        "schedule": schedule_data.name,
                                    }
                                )
                            else:
                                schedule_result["success"] = False
                                schedule_result["error"] = "Invoice generation returned None"
                        except Exception as e:
                            schedule_result["success"] = False
                            schedule_result["error"] = str(e)
                            results["errors"].append(f"Schedule {schedule_data.name}: {str(e)}")
                    else:
                        schedule_result["would_generate"] = True

                results["processed_schedules"].append(schedule_result)
                processed += 1

            except Exception as e:
                error_msg = f"Error processing schedule {schedule_data.name}: {str(e)}"
                results["errors"].append(error_msg)
                continue

        # Commit changes if not dry run and invoices were generated
        if not dry_run and results["invoices_generated"] > 0:
            frappe.db.commit()

        # Generate summary message
        if dry_run:
            results["message"] = (
                f"Dry run complete: Found {results['schedules_found']} schedules, "
                f"{results['eligible_schedules']} eligible for invoice generation, "
                f"{results['orphaned_schedules']} orphaned schedules detected"
            )
        else:
            results["message"] = (
                f"Bulk generation complete: {results['invoices_generated']} invoices generated "
                f"from {results['eligible_schedules']} eligible schedules. "
                f"{len(results['errors'])} errors occurred."
            )

        return results

    except Exception as e:
        # Rollback any uncommitted changes in case of error
        if not dry_run:
            frappe.db.rollback()
        frappe.log_error(f"Bulk invoice generation failed: {str(e)}", "Bulk Invoice Generation")
        return {"success": False, "error": str(e), "message": f"Bulk invoice generation failed: {str(e)}"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_dues_schedules_summary(include_orphaned=True, days_ahead=30):
    """
    Get a comprehensive summary of dues schedules for admin dashboard

    Args:
        include_orphaned (bool): Whether to include orphaned schedule detection
        days_ahead (int): Number of days ahead to look for upcoming invoices

    Returns:
        dict: Summary of dues schedules status
    """

    try:
        summary = {
            "success": True,
            "timestamp": frappe.utils.now(),
            "total_active_schedules": 0,
            "due_now": 0,
            "due_next_7_days": 0,
            "due_next_30_days": 0,
            "auto_generate_enabled": 0,
            "orphaned_schedules": 0,
            "recent_invoices": 0,
        }

        # Get basic counts
        summary["total_active_schedules"] = frappe.db.count(
            "Membership Dues Schedule", {"status": "Active", "is_template": 0}
        )

        # Get dues schedules due now
        summary["due_now"] = frappe.db.count(
            "Membership Dues Schedule",
            {"status": "Active", "is_template": 0, "next_invoice_date": ["<=", today()]},
        )

        # Get dues schedules due in next 7 days
        summary["due_next_7_days"] = frappe.db.count(
            "Membership Dues Schedule",
            {"status": "Active", "is_template": 0, "next_invoice_date": ["<=", add_days(today(), 7)]},
        )

        # Get dues schedules due in specified days ahead
        summary["due_next_30_days"] = frappe.db.count(
            "Membership Dues Schedule",
            {
                "status": "Active",
                "is_template": 0,
                "next_invoice_date": ["<=", add_days(today(), days_ahead)],
            },
        )

        # Get schedules with auto-generate enabled
        summary["auto_generate_enabled"] = frappe.db.count(
            "Membership Dues Schedule", {"status": "Active", "is_template": 0, "auto_generate": 1}
        )

        # Check for orphaned schedules if requested
        if include_orphaned:
            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                MembershipDuesSchedule,
            )

            orphaned = MembershipDuesSchedule.find_orphaned_schedules(limit=100)
            summary["orphaned_schedules"] = len(orphaned)

            if orphaned:
                summary["orphaned_details"] = orphaned[:10]  # Show first 10 for admin review

        # Get recent invoice count (last 7 days)
        week_ago = add_days(today(), -7)
        summary["recent_invoices"] = frappe.db.count(
            "Sales Invoice", {"creation": [">=", week_ago], "docstatus": ["!=", 2]}  # Not cancelled
        )

        # Get upcoming schedules sample
        upcoming_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0, "next_invoice_date": ["<=", add_days(today(), 7)]},
            fields=["name", "member_name", "next_invoice_date", "dues_rate"],
            order_by="next_invoice_date",
            limit=10,
        )
        summary["upcoming_schedules_sample"] = upcoming_schedules

        return summary

    except Exception as e:
        frappe.log_error(f"Error getting dues schedules summary: {str(e)}", "Dues Schedule Summary")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_schedules(dry_run=True, max_cleanup=20):
    """
    Clean up orphaned dues schedules that reference non-existent members

    Args:
        dry_run (bool): If True, only reports what would be cleaned up
        max_cleanup (int): Maximum number of schedules to clean up in one run

    Returns:
        dict: Results of cleanup operation
    """

    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("Insufficient permissions for schedule cleanup"))

    try:
        results = {
            "success": True,
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
            "orphaned_found": 0,
            "orphaned_schedules": 0,  # For frontend compatibility
            "cleaned_up": 0,
            "skipped_templates": 0,
            "errors": [],
            "processed_schedules": [],
            "orphaned_details": [],  # For frontend compatibility
        }

        # Find orphaned schedules using the same logic as the Invoice Generation Dashboard
        # Get all non-template active schedules and check each one individually
        all_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 0},
            fields=["name", "member", "status"],
            limit=max_cleanup * 3,  # Get more to account for filtering
        )

        orphaned_schedules = []
        for schedule_data in all_schedules:
            try:
                schedule = frappe.get_doc(
                    "Membership Dues Schedule", schedule_data.name, ignore_validate=True
                )
                if schedule.is_orphaned():
                    orphaned_schedules.append(schedule_data)
                    if len(orphaned_schedules) >= max_cleanup * 2:
                        break
            except Exception:
                continue  # Skip problematic schedules

        results["orphaned_found"] = len(orphaned_schedules)
        results["orphaned_schedules"] = len(orphaned_schedules)  # For frontend compatibility

        if not orphaned_schedules:
            results["message"] = "No orphaned dues schedules found"
            return results

        # Process orphaned schedules
        processed = 0
        for schedule_data in orphaned_schedules:
            if processed >= max_cleanup:
                break

            try:
                # Skip templates
                if schedule_data.get("is_template"):
                    results["skipped_templates"] += 1
                    continue

                schedule_result = {
                    "schedule": schedule_data["name"],
                    "member": schedule_data["member"],
                    "status": schedule_data["status"],
                }

                if not dry_run:
                    try:
                        # Use direct DB deletion to bypass validation rules entirely
                        frappe.db.delete("Membership Dues Schedule", {"name": schedule_data["name"]})
                        schedule_result["action"] = "deleted"
                        results["cleaned_up"] += 1
                    except Exception as e:
                        schedule_result["action"] = "delete_failed"
                        schedule_result["error"] = str(e)
                        results["errors"].append(f"Failed to delete {schedule_data['name']}: {str(e)}")
                else:
                    schedule_result["action"] = "would_delete"

                results["processed_schedules"].append(schedule_result)

                # Also add to orphaned_details for frontend compatibility
                results["orphaned_details"].append(
                    {
                        "name": schedule_data["name"],
                        "member": schedule_data["member"],
                        "status": schedule_data["status"],
                        "action": schedule_result.get("action", "would_delete"),
                    }
                )

                processed += 1

            except Exception as e:
                error_msg = f"Error processing orphaned schedule {schedule_data['name']}: {str(e)}"
                results["errors"].append(error_msg)
                continue

        # Commit changes if not dry run
        if not dry_run and results["cleaned_up"] > 0:
            frappe.db.commit()

        # Generate summary message
        if dry_run:
            results["message"] = (
                f"Dry run complete: Found {results['orphaned_found']} orphaned schedules, "
                f"would clean up {processed} (skipped {results['skipped_templates']} templates)"
            )
        else:
            results["message"] = (
                f"Cleanup complete: Deleted {results['cleaned_up']} orphaned schedules. "
                f"{len(results['errors'])} errors occurred."
            )

        return results

    except Exception as e:
        frappe.log_error(f"Orphaned schedule cleanup failed: {str(e)}", "Schedule Cleanup")
        return {"success": False, "error": str(e), "message": f"Cleanup failed: {str(e)}"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def validate_invoice_generation_readiness():
    """
    Validate system readiness for invoice generation and identify potential issues

    Returns:
        dict: System validation results
    """

    try:
        validation = {
            "success": True,
            "timestamp": frappe.utils.now(),
            "issues": [],
            "warnings": [],
            "info": [],
            "system_ready": True,
            # Frontend-expected fields
            "total_active_schedules": 0,
            "due_now": 0,
            "upcoming_schedules_sample": [],
        }

        # Get system statistics for frontend display
        try:
            # Count total active schedules
            total_schedules = frappe.db.count(
                "Membership Dues Schedule", {"status": "Active", "is_template": 0}
            )
            validation["total_active_schedules"] = total_schedules

            # Count schedules due now
            due_now_count = frappe.db.count(
                "Membership Dues Schedule",
                {
                    "status": "Active",
                    "auto_generate": 1,
                    "next_invoice_date": ["<=", today()],
                    "is_template": 0,
                },
            )
            validation["due_now"] = due_now_count

            # Get sample of upcoming schedules
            upcoming_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "status": "Active",
                    "auto_generate": 1,
                    "next_invoice_date": [">", today()],
                    "is_template": 0,
                },
                fields=["name", "member_name", "next_invoice_date", "dues_rate"],
                order_by="next_invoice_date",
                limit=10,
            )

            validation["upcoming_schedules_sample"] = [
                {
                    "name": s.name,
                    "member_name": s.member_name or "Unknown",
                    "next_invoice_date": s.next_invoice_date,
                    "dues_rate": s.dues_rate or 0,
                }
                for s in upcoming_schedules
            ]

        except Exception as e:
            validation["warnings"].append(f"Could not gather system statistics: {str(e)}")

        # Check auto-submit setting
        try:
            auto_submit = frappe.db.get_single_value(
                "Verenigingen Settings", "auto_submit_membership_invoices"
            )
            if auto_submit:
                validation["info"].append("Auto-submit is enabled for membership invoices")
            else:
                validation["warnings"].append("Auto-submit is disabled - invoices will remain in draft")
        except Exception:
            validation["warnings"].append("Cannot access auto-submit setting in Verenigingen Settings")

        # Check for orphaned schedules
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        orphaned = MembershipDuesSchedule.find_orphaned_schedules(limit=10)
        if orphaned:
            validation["issues"].append(
                f"Found {len(orphaned)} orphaned dues schedules that may cause errors"
            )
            validation["system_ready"] = False

        # Check for overdue schedules
        overdue_count = frappe.db.count(
            "Membership Dues Schedule",
            {"status": "Active", "auto_generate": 1, "next_invoice_date": ["<", today()], "is_template": 0},
        )
        if overdue_count > 0:
            validation["warnings"].append(f"{overdue_count} schedules are overdue for invoice generation")

        # Check for schedules without customer records
        schedules_without_customers = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMember` m ON mds.member = m.name
            WHERE mds.status = 'Active'
                AND mds.is_template = 0
                AND (m.customer IS NULL OR m.customer = '')
        """,
            as_dict=True,
        )

        if schedules_without_customers and schedules_without_customers[0].count > 0:
            count = schedules_without_customers[0].count
            validation["issues"].append(f"{count} active schedules have members without customer records")
            validation["system_ready"] = False

        # Check database permissions
        try:
            frappe.db.sql("SELECT 1 FROM `tabMembership Dues Schedule` LIMIT 1")
            validation["info"].append("Database access confirmed")
        except Exception as e:
            validation["issues"].append(f"Database access issue: {str(e)}")
            validation["system_ready"] = False

        # Generate overall status
        if validation["system_ready"]:
            validation["message"] = "System is ready for invoice generation"
        else:
            validation["message"] = (
                f"System has {len(validation['issues'])} critical issues that need resolution"
            )

        return validation

    except Exception as e:
        frappe.log_error(f"Invoice generation validation failed: {str(e)}", "Invoice Validation")
        return {"success": False, "error": str(e), "system_ready": False}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_member_references(dry_run=True, max_cleanup=50):
    """
    Clean up orphaned member references in schedules without deleting the schedules themselves.
    This is useful when you want to preserve the schedules but remove invalid member links.

    Args:
        dry_run (bool): If True, only reports what would be cleaned up
        max_cleanup (int): Maximum number of references to clean up in one run

    Returns:
        dict: Results of reference cleanup operation
    """

    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("Insufficient permissions for member reference cleanup"))

    try:
        results = {
            "success": True,
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
            "orphaned_references_found": 0,
            "references_cleared": 0,
            "errors": [],
            "processed_schedules": [],
        }

        # Find schedules with orphaned member references
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        orphaned_schedules = MembershipDuesSchedule.find_orphaned_schedules(limit=max_cleanup)
        results["orphaned_references_found"] = len(orphaned_schedules)

        if not orphaned_schedules:
            results["message"] = "No orphaned member references found"
            return results

        # Process orphaned references
        processed = 0
        for schedule_data in orphaned_schedules:
            if processed >= max_cleanup:
                break

            try:
                schedule_result = {
                    "schedule": schedule_data["name"],
                    "member": schedule_data["member"],
                    "status": schedule_data["status"],
                }

                if not dry_run:
                    try:
                        # Clear the member reference but keep the schedule
                        schedule_doc = frappe.get_doc(
                            "Membership Dues Schedule", schedule_data["name"], ignore_validate=True
                        )
                        schedule_doc.member = None
                        schedule_doc.member_name = None
                        schedule_doc.save(ignore_permissions=True, ignore_validate=True)
                        schedule_result["action"] = "reference_cleared"
                        results["references_cleared"] += 1
                    except Exception as e:
                        schedule_result["action"] = "clear_failed"
                        schedule_result["error"] = str(e)
                        results["errors"].append(
                            f"Failed to clear reference in {schedule_data['name']}: {str(e)}"
                        )
                else:
                    schedule_result["action"] = "would_clear_reference"

                results["processed_schedules"].append(schedule_result)
                processed += 1

            except Exception as e:
                error_msg = f"Error processing schedule {schedule_data['name']}: {str(e)}"
                results["errors"].append(error_msg)
                continue

        # Commit changes if not dry run
        if not dry_run and results["references_cleared"] > 0:
            frappe.db.commit()

        # Generate summary message
        if dry_run:
            results["message"] = (
                f"Dry run complete: Found {results['orphaned_references_found']} orphaned member references, "
                f"would clear {processed}"
            )
        else:
            results["message"] = (
                f"Reference cleanup complete: Cleared {results['references_cleared']} orphaned member references. "
                f"{len(results['errors'])} errors occurred."
            )

        return results

    except Exception as e:
        frappe.log_error(f"Member reference cleanup failed: {str(e)}", "Reference Cleanup")
        return {"success": False, "error": str(e), "message": f"Reference cleanup failed: {str(e)}"}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_membership_data(dry_run=True, max_cleanup=20):
    """
    Enhanced cleanup for orphaned membership-related data including:
    - Orphaned dues schedules (existing functionality)
    - Memberships with invalid membership types
    - Amendment requests with non-existent members
    - Other orphaned membership data

    Args:
        dry_run (bool): If True, only reports what would be cleaned up
        max_cleanup (int): Maximum number of items to clean up in one run

    Returns:
        dict: Results of comprehensive cleanup operation
    """

    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("Insufficient permissions for membership data cleanup"))

    try:
        # Start transaction for non-dry-run operations
        if not dry_run:
            frappe.db.begin()

        results = {
            "success": True,
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
            "orphaned_schedules": {"found": 0, "cleaned": 0},
            "invalid_memberships": {"found": 0, "cleaned": 0},
            "orphaned_amendments": {"found": 0, "cleaned": 0},
            "errors": [],
            "processed_items": [],
        }

        # Get list of valid membership types for comparison
        valid_membership_types = set(frappe.db.get_list("Membership Type", pluck="name"))

        # 1. Clean up orphaned dues schedules (existing functionality)
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        orphaned_schedules = MembershipDuesSchedule.find_orphaned_schedules(limit=max_cleanup)
        results["orphaned_schedules"]["found"] = len(orphaned_schedules)

        processed_schedules = 0
        for schedule_data in orphaned_schedules:
            if processed_schedules >= max_cleanup:
                break

            schedule_info = {
                "type": "orphaned_schedule",
                "name": schedule_data["name"],
                "member": schedule_data["member"],
                "status": schedule_data["status"],
            }

            if not dry_run:
                try:
                    # Use direct DB deletion to bypass validation rules entirely
                    # This is safe for orphaned schedules since the member no longer exists
                    frappe.db.delete("Membership Dues Schedule", {"name": schedule_data["name"]})
                    schedule_info["action"] = "deleted"
                    results["orphaned_schedules"]["cleaned"] += 1
                except Exception as e:
                    schedule_info["action"] = "delete_failed"
                    schedule_info["error"] = str(e)
                    results["errors"].append(f"Failed to delete schedule {schedule_data['name']}: {str(e)}")
            else:
                schedule_info["action"] = "would_delete"

            results["processed_items"].append(schedule_info)
            processed_schedules += 1

        # 2. Find and clean up memberships with invalid membership types
        invalid_memberships = frappe.db.sql(
            """
            SELECT name, member, membership_type, start_date, status
            FROM `tabMembership`
            WHERE membership_type NOT IN ({})
            AND membership_type IS NOT NULL
            AND membership_type != ''
            LIMIT %s
        """.format(
                ",".join(["%s"] * len(valid_membership_types))
            ),
            list(valid_membership_types) + [max_cleanup],
            as_dict=True,
        )

        results["invalid_memberships"]["found"] = len(invalid_memberships)

        processed_memberships = 0
        for membership_data in invalid_memberships:
            if processed_memberships >= max_cleanup:
                break

            membership_info = {
                "type": "invalid_membership",
                "name": membership_data["name"],
                "member": membership_data["member"],
                "invalid_type": membership_data["membership_type"],
                "status": membership_data["status"],
            }

            if not dry_run:
                try:
                    # Check if member still exists before deletion
                    if frappe.db.exists("Member", membership_data["member"]):
                        membership_info["action"] = "member_exists_skipped"
                        membership_info["note"] = (
                            f"Member {membership_data['member']} exists - manual review needed"
                        )
                    else:
                        # Check for dependent records before deletion
                        dependent_records = frappe.db.sql(
                            """
                            SELECT 'Dues Schedule' as type, COUNT(*) as count
                            FROM `tabMembership Dues Schedule`
                            WHERE membership = %s
                            UNION ALL
                            SELECT 'Sales Invoice' as type, COUNT(*) as count
                            FROM `tabSales Invoice`
                            WHERE membership = %s
                        """,
                            (membership_data["name"], membership_data["name"]),
                            as_dict=True,
                        )

                        has_dependencies = any(
                            record.count > 0 for record in dependent_records if record.count
                        )

                        if has_dependencies:
                            membership_info["action"] = "skipped_has_dependencies"
                            membership_info["note"] = (
                                f"Membership has dependent records: {', '.join(f'{r.type}({r.count})' for r in dependent_records if r.count > 0)}"
                            )
                        else:
                            # Safe to delete if member doesn't exist and no dependencies
                            frappe.delete_doc("Membership", membership_data["name"], ignore_permissions=True)
                            membership_info["action"] = "deleted"
                            results["invalid_memberships"]["cleaned"] += 1
                except Exception as e:
                    membership_info["action"] = "delete_failed"
                    membership_info["error"] = str(e)
                    results["errors"].append(
                        f"Failed to delete membership {membership_data['name']}: {str(e)}"
                    )
            else:
                membership_info["action"] = "would_delete"

            results["processed_items"].append(membership_info)
            processed_memberships += 1

        # 3. Find and clean up orphaned amendment requests
        orphaned_amendments = frappe.db.sql(
            """
            SELECT ar.name, ar.member, ar.status, ar.amendment_type, ar.requested_membership_type
            FROM `tabContribution Amendment Request` ar
            LEFT JOIN `tabMember` m ON ar.member = m.name
            WHERE m.name IS NULL
            AND ar.member IS NOT NULL
            AND ar.status = 'Approved'
            LIMIT %s
        """,
            (max_cleanup,),
            as_dict=True,
        )

        results["orphaned_amendments"]["found"] = len(orphaned_amendments)

        processed_amendments = 0
        for amendment_data in orphaned_amendments:
            if processed_amendments >= max_cleanup:
                break

            amendment_info = {
                "type": "orphaned_amendment",
                "name": amendment_data["name"],
                "member": amendment_data["member"],
                "status": amendment_data["status"],
                "amendment_type": amendment_data["amendment_type"],
                "requested_type": amendment_data["requested_membership_type"],
            }

            if not dry_run:
                try:
                    # Use direct DB deletion to bypass link validation for orphaned amendments
                    # This is safe since the member no longer exists
                    frappe.db.delete("Contribution Amendment Request", {"name": amendment_data["name"]})
                    amendment_info["action"] = "deleted"
                    results["orphaned_amendments"]["cleaned"] += 1
                except Exception as e:
                    amendment_info["action"] = "delete_failed"
                    amendment_info["error"] = str(e)
                    results["errors"].append(f"Failed to delete amendment {amendment_data['name']}: {str(e)}")
            else:
                amendment_info["action"] = "would_delete"

            results["processed_items"].append(amendment_info)
            processed_amendments += 1

        # Transaction management - commit or rollback based on success
        if not dry_run:
            total_cleaned = (
                results["orphaned_schedules"]["cleaned"]
                + results["invalid_memberships"]["cleaned"]
                + results["orphaned_amendments"]["cleaned"]
            )
            if total_cleaned > 0 and len(results["errors"]) == 0:
                # Only commit if we cleaned something AND had no errors
                frappe.db.commit()
            elif len(results["errors"]) > 0:
                # Rollback if there were any errors to maintain consistency
                frappe.db.rollback()
                results["message"] = (
                    f"Cleanup rolled back due to {len(results['errors'])} errors. No changes were made."
                )
                results["success"] = False

        # Generate summary message
        total_found = (
            results["orphaned_schedules"]["found"]
            + results["invalid_memberships"]["found"]
            + results["orphaned_amendments"]["found"]
        )
        total_cleaned = (
            results["orphaned_schedules"]["cleaned"]
            + results["invalid_memberships"]["cleaned"]
            + results["orphaned_amendments"]["cleaned"]
        )

        if dry_run:
            results["message"] = (
                f"Found {total_found} orphaned items: "
                f"{results['orphaned_schedules']['found']} schedules, "
                f"{results['invalid_memberships']['found']} invalid memberships, "
                f"{results['orphaned_amendments']['found']} orphaned amendments"
            )
        else:
            results["message"] = (
                f"Cleaned up {total_cleaned} of {total_found} orphaned items. "
                f"{len(results['errors'])} errors occurred."
            )

        return results

    except Exception as e:
        # Rollback transaction on any unexpected error
        if not dry_run:
            frappe.db.rollback()

        frappe.log_error(f"Enhanced membership data cleanup failed: {str(e)}", "Membership Cleanup")
        return {"success": False, "error": str(e), "message": f"Cleanup failed: {str(e)}"}
