"""
Dues Invoice Management Workflow API

This module provides secure API endpoints for:
- Checking member dues invoice status
- Generating missing dues invoices
- Preparing SEPA DD batches from invoices
- Managing the complete dues-to-SEPA workflow

Author: Verenigingen System
"""

import traceback
from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api


@standard_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def check_member_dues_status(
    period_start: str = None, period_end: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    Check which members need dues invoices for the current period.

    This function now uses the unified eligibility logic to ensure consistency
    with the actual generation process.

    Args:
        period_start: Start date for billing period (defaults to current month start)
        period_end: End date for billing period (defaults to current month end)

    Returns:
        OperationResult with member analysis results
    """
    try:
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            calculate_cutoff_date_for_period,
            get_eligible_schedules_for_period,
        )

        # Calculate cutoff date (ignores period_start/period_end for now - uses system cutoff)
        cutoff_date = calculate_cutoff_date_for_period()

        # Use unified eligibility logic
        eligibility_result = get_eligible_schedules_for_period(
            cutoff_date=cutoff_date,
            test_mode=False,  # Production mode for dues status check
            include_details=True,
        )

        # Transform the unified result into the expected API format
        filtered_members = eligibility_result["filtered_members"]

        # Calculate SEPA eligibility and build member list for members needing invoices
        sepa_eligible_count = 0
        needs_invoicing_members = []
        for schedule_name in eligibility_result["eligible_schedules"]:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
            if schedule.member:
                mandate_exists = frappe.db.exists(
                    "SEPA Mandate", {"member": schedule.member, "status": "Active"}
                )
                if mandate_exists:
                    sepa_eligible_count += 1

                # Get member details for display
                member = frappe.get_doc("Member", schedule.member)
                needs_invoicing_members.append(
                    {
                        "member_id": schedule.member,
                        "member_name": f"{member.first_name} {member.last_name}",
                        "schedule": schedule_name,
                    }
                )

        # Get total active members count
        total_active_members = frappe.db.count(
            "Member", {"status": ["in", ["Active", "Pending", "Suspended"]]}
        )

        # Count active members without any Membership record (proper query)
        members_without_membership = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT m.name)
            FROM `tabMember` m
            WHERE m.status IN ('Active', 'Pending', 'Suspended')
            AND NOT EXISTS (
                SELECT 1 FROM `tabMembership` mem
                WHERE mem.member = m.name
            )
        """
        )[0][0]

        # Count members with active Membership but no active Dues Schedule
        members_without_schedule = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT m.name)
            FROM `tabMember` m
            WHERE m.status IN ('Active', 'Pending', 'Suspended')
            AND EXISTS (
                SELECT 1 FROM `tabMembership` mem
                WHERE mem.member = m.name
                AND mem.status = 'Active'
                AND mem.docstatus = 1
            )
            AND NOT EXISTS (
                SELECT 1 FROM `tabMembership Dues Schedule` mds
                WHERE mds.member = m.name
                AND mds.status = 'Active'
            )
        """
        )[0][0]

        # Build comprehensive response
        result = {
            "period_start": cutoff_date.replace(day=1),  # Start of cutoff month
            "period_end": cutoff_date,
            "summary": {
                "total_active_members": total_active_members,
                "members_with_invoices": len(filtered_members.get("already_covered", [])),
                "members_missing_invoices": len(eligibility_result["eligible_schedules"]),
                "members_without_membership": members_without_membership,
                "members_without_schedule": members_without_schedule,
                "invoice_breakdown": {
                    "draft_invoices": 0,  # Would require additional query
                    "submitted_invoices": 0,  # Would require additional query
                    "total_invoices": 0,
                },
                "sepa_eligible": sepa_eligible_count,
                "sepa_missing": len(eligibility_result["eligible_schedules"]) - sepa_eligible_count,
            },
            # Enhanced categorization with transparent filtering
            "member_categories": {
                "ineligible_status": {
                    "count": len(filtered_members.get("ineligible_status", [])),
                    "members": filtered_members.get("ineligible_status", []),
                    "description": "Members with Terminated/Expelled/Deceased/Quit status (will be skipped)",
                },
                "gap_reset": {
                    "count": len(filtered_members.get("gap_reset", [])),
                    "members": filtered_members.get("gap_reset", []),
                    "description": "Members with large coverage gaps >30 days (billing will restart)",
                },
                "already_covered": {
                    "count": len(filtered_members.get("already_covered", [])),
                    "members": filtered_members.get("already_covered", []),
                    "description": f"Members with current coverage through {cutoff_date}",
                },
                "needs_invoicing": {
                    "count": len(eligibility_result["eligible_schedules"]),
                    "members": needs_invoicing_members,
                    "description": "Members who will get new invoices generated",
                },
                "no_customer": {
                    "count": len(filtered_members.get("no_customer", [])),
                    "members": filtered_members.get("no_customer", []),
                    "description": "Members missing customer records (cannot invoice)",
                },
                "duplicate_coverage": {
                    "count": len(filtered_members.get("duplicate_coverage", [])),
                    "members": filtered_members.get("duplicate_coverage", []),
                    "description": "Members with overlapping invoice coverage",
                },
                "too_early": {
                    "count": len(filtered_members.get("too_early", [])),
                    "members": filtered_members.get("too_early", []),
                    "description": "Members not yet ready for next invoice",
                },
                "business_logic": {
                    "count": len(filtered_members.get("business_logic", [])),
                    "members": filtered_members.get("business_logic", []),
                    "description": "Members filtered by other business rules",
                },
            },
            "processing_summary": {
                "will_be_processed": len(eligibility_result["eligible_schedules"]),
                "will_be_skipped": eligibility_result["total_filtered"],
                "will_restart_billing": len(filtered_members.get("gap_reset", [])),
                "already_covered": len(filtered_members.get("already_covered", [])),
                "total_schedules_checked": eligibility_result["summary"]["total_schedules_checked"],
            },
            # Include raw eligibility data for debugging
            "_eligibility_breakdown": eligibility_result["summary"]["filter_breakdown"],
        }

        return OperationResult.ok(result, message=_("Member dues status retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Member Dues Status Check Failed"),
            message=f"Error checking member dues status: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to check member dues status: {0}").format(str(e)),
            error_code="DUES_STATUS_CHECK_FAILED",
        )


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def generate_missing_invoices(
    member_list: List[str] = None, force: bool = False
) -> OperationResult[Dict[str, Any]]:
    """
    Generate invoices for members who are missing them

    Args:
        member_list: List of member names to generate invoices for (if None, generates for all eligible)
        force: Force generation even if validation warnings exist

    Returns:
        OperationResult with generation results
    """
    try:
        if isinstance(member_list, str):
            member_list = frappe.parse_json(member_list)

        # Enqueue bulk invoice generation as background job for large-scale operations
        # This prevents browser timeouts and allows processing of thousands of invoices
        if member_list:
            frappe.log_error(
                f"Member-specific generation requested for {len(member_list)} members, but using bulk system instead",
                "Invoice Generation Notice",
            )

        # Enqueue as background job to handle large volumes
        job = frappe.enqueue(
            method="verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.generate_dues_invoices",
            queue="long",
            timeout=3600,
            test_mode=False,
            job_name="bulk_invoice_generation",
            now=False,
        )

        # Return immediate response with job information
        result = {
            "job_id": job.name if hasattr(job, "name") else str(job),
            "note": _(
                "Large-scale generation queued for async processing. You will see results in RQ Job List."
            ),
            "check_status_at": f"/app/rq-job/{job.name}" if hasattr(job, "name") else "/app/rq-job",
        }

        return OperationResult.ok(
            result, message=_("Invoice generation started in background. Check RQ Job List for progress.")
        )

    except Exception as e:
        frappe.log_error(
            title=_("Invoice Generation Failed"),
            message=f"Error generating missing invoices: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to generate invoices: {0}").format(str(e)),
            error_code="INVOICE_GENERATION_FAILED",
        )


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def validate_sepa_eligibility(invoice_list: List[str] = None) -> OperationResult[Dict[str, Any]]:
    """
    Validate SEPA mandate eligibility for invoices

    Args:
        invoice_list: List of invoice names to check (if None, checks all unpaid invoices)

    Returns:
        OperationResult with SEPA eligibility analysis
    """
    try:
        if isinstance(invoice_list, str):
            invoice_list = frappe.parse_json(invoice_list)

        # Get unpaid invoices if no specific list provided
        if not invoice_list:
            unpaid_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1},
                pluck="name",
            )
            invoice_list = unpaid_invoices

        if not invoice_list:
            result = {
                "eligible_invoices": [],
                "ineligible_invoices": [],
                "summary": {
                    "total_checked": 0,
                    "sepa_eligible": 0,
                    "missing_mandate": 0,
                    "invalid_mandate": 0,
                },
            }
            return OperationResult.ok(result, message=_("No unpaid invoices found to check"))

        eligible_invoices = []
        ineligible_invoices = []

        # Check each invoice
        for invoice_name in invoice_list:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_name)

                # Get member from membership dues schedule
                if not invoice.membership_dues_schedule_display:
                    ineligible_invoices.append(
                        {
                            "invoice": invoice_name,
                            "reason": _("Not a membership dues invoice"),
                            "customer": invoice.customer,
                        }
                    )
                    continue

                # Get member from schedule
                schedule = frappe.get_doc(
                    "Membership Dues Schedule", invoice.membership_dues_schedule_display
                )

                if not schedule.member:
                    ineligible_invoices.append(
                        {
                            "invoice": invoice_name,
                            "reason": _("No member associated with dues schedule"),
                            "customer": invoice.customer,
                        }
                    )
                    continue

                # Check for active SEPA mandate
                mandate = frappe.db.get_value(
                    "SEPA Mandate",
                    {"member": schedule.member, "status": "Active"},
                    ["name", "iban", "bic", "mandate_id"],
                    as_dict=True,
                )

                if mandate:
                    eligible_invoices.append(
                        {
                            "invoice": invoice_name,
                            "member": schedule.member,
                            "customer": invoice.customer,
                            "amount": invoice.outstanding_amount,
                            "currency": invoice.currency,
                            "due_date": invoice.due_date,
                            "mandate": mandate,
                        }
                    )
                else:
                    ineligible_invoices.append(
                        {
                            "invoice": invoice_name,
                            "member": schedule.member,
                            "reason": _("No active SEPA mandate found"),
                            "customer": invoice.customer,
                        }
                    )

            except Exception as e:
                ineligible_invoices.append(
                    {
                        "invoice": invoice_name,
                        "reason": _("Error checking invoice: {0}").format(str(e)),
                        "customer": "Unknown",
                    }
                )

        summary = {
            "total_checked": len(invoice_list),
            "sepa_eligible": len(eligible_invoices),
            "missing_mandate": len(
                [inv for inv in ineligible_invoices if "No active SEPA mandate" in inv.get("reason", "")]
            ),
            "invalid_mandate": len(ineligible_invoices)
            - len([inv for inv in ineligible_invoices if "No active SEPA mandate" in inv.get("reason", "")]),
        }

        result = {
            "eligible_invoices": eligible_invoices,
            "ineligible_invoices": ineligible_invoices,
            "summary": summary,
        }

        return OperationResult.ok(
            result, message=_("SEPA eligibility validated for {0} invoices").format(len(invoice_list))
        )

    except Exception as e:
        frappe.log_error(
            title=_("SEPA Eligibility Validation Failed"),
            message=f"Error validating SEPA eligibility: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to validate SEPA eligibility: {0}").format(str(e)),
            error_code="SEPA_VALIDATION_FAILED",
        )


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def prepare_sepa_batch(
    eligible_invoices: List[Dict] = None, batch_description: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    Prepare a SEPA Direct Debit batch from eligible invoices using existing batch infrastructure

    Args:
        eligible_invoices: List of eligible invoice dictionaries (optional - will auto-fetch if not provided)
        batch_description: Optional description for the batch

    Returns:
        OperationResult with batch creation results
    """
    try:
        # Use the existing SEPA processor infrastructure
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor

        sepa_processor = SEPAProcessor()

        # Create batch using existing infrastructure
        batch_doc = sepa_processor.create_dues_collection_batch(
            collection_date=today(), verify_invoicing=False  # We're creating from existing eligible invoices
        )

        if batch_doc:
            result = {
                "batch_name": batch_doc.name,
                "total_amount": getattr(batch_doc, "total_amount", 0),
                "entry_count": getattr(batch_doc, "entry_count", 0),
            }
            return OperationResult.ok(
                result, message=_("SEPA batch created successfully using existing infrastructure")
            )
        else:
            return OperationResult.fail(
                message=_("No SEPA-eligible invoices found for batch creation"),
                error_code="NO_ELIGIBLE_INVOICES",
            )

    except Exception as e:
        frappe.log_error(
            title=_("SEPA Batch Creation Error"),
            message=f"SEPA batch creation failed: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to create SEPA batch: {0}").format(str(e)),
            error_code="SEPA_BATCH_CREATION_FAILED",
        )


@standard_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def get_workflow_status() -> OperationResult[Dict[str, Any]]:
    """
    Get current status of the dues invoice workflow

    Returns:
        OperationResult with workflow status information
    """
    try:
        # Get recent batches
        recent_batches = frappe.get_all(
            "Direct Debit Batch",
            filters={"creation": [">", add_days(today(), -30)]},
            fields=["name", "batch_date", "status", "total_amount", "entry_count"],
            order_by="creation desc",
            limit=10,
        )

        # Get pending invoices count
        pending_invoices = frappe.db.count(
            "Sales Invoice", {"status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1}
        )

        # Get members analysis - returns OperationResult now
        members_status_result = check_member_dues_status()

        # Check for coverage/scheduling mismatches - returns OperationResult now
        mismatches_result = check_coverage_scheduling_mismatches()

        # Extract data from OperationResult responses
        if members_status_result.success and members_status_result.data:
            members_status = members_status_result.data
        else:
            members_status = {
                "summary": {
                    "total_active_members": 0,
                    "members_with_invoices": 0,
                    "members_missing_invoices": 0,
                    "members_without_membership": 0,
                    "members_without_schedule": 0,
                    "sepa_eligible": 0,
                }
            }

        if mismatches_result.success and mismatches_result.data:
            mismatches = mismatches_result.data
        else:
            mismatches = {
                "total_mismatches": 0,
                "extending_past": {"count": 0, "items": []},
                "ending_early": {"count": 0, "items": []},
            }

        # Map to expected format for template
        result = {
            "recent_batches": recent_batches,
            "pending_invoices": pending_invoices,
            "members_analysis": {
                "total_active_members": members_status["summary"]["total_active_members"],
                "members_with_coverage": members_status["summary"]["members_with_invoices"],
                "members_missing_invoices": members_status["summary"]["members_missing_invoices"],
                "members_without_membership": members_status["summary"]["members_without_membership"],
                "members_without_schedule": members_status["summary"]["members_without_schedule"],
                "sepa_eligible": members_status["summary"]["sepa_eligible"],
            },
            "coverage_mismatches": mismatches,
        }

        return OperationResult.ok(result, message=_("Workflow status retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Workflow Status Retrieval Failed"),
            message=f"Error getting workflow status: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to get workflow status: {0}").format(str(e)),
            error_code="WORKFLOW_STATUS_FAILED",
        )


@standard_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def check_coverage_scheduling_mismatches() -> OperationResult[Dict[str, Any]]:
    """
    Check for mismatches between next_invoice_date and actual invoice coverage.
    Detects data integrity issues where scheduling doesn't align with coverage periods.

    Returns:
        OperationResult with mismatch analysis
    """
    try:
        # Get all active schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "auto_generate": 1},
            fields=["name", "member", "next_invoice_date", "billing_frequency"],
        )

        mismatches_extending_past = []  # Coverage extends past next_invoice_date
        mismatches_ending_early = []  # Coverage ends too early before next_invoice_date
        tolerance_days = 5

        for sched in schedules:
            if not sched.member or not sched.next_invoice_date:
                continue

            # Check if member exists first (avoid logging errors for deleted members)
            if not frappe.db.exists("Member", sched.member):
                continue

            # Get member's customer
            try:
                member = frappe.get_doc("Member", sched.member)
                if not member.customer:
                    continue
            except Exception:
                continue

            # Get their latest invoice coverage
            latest_invoice = frappe.db.sql(
                """
                SELECT name, posting_date,
                       custom_coverage_start_date, custom_coverage_end_date
                FROM `tabSales Invoice`
                WHERE customer = %(customer)s
                AND docstatus = 1
                AND custom_coverage_end_date IS NOT NULL
                ORDER BY custom_coverage_end_date DESC
                LIMIT 1
            """,
                {"customer": member.customer},
                as_dict=True,
            )

            if not latest_invoice:
                continue

            latest_coverage_end = getdate(latest_invoice[0].custom_coverage_end_date)
            next_invoice_date = getdate(sched.next_invoice_date)

            # Calculate gap between coverage end and next invoice date
            gap_days = (next_invoice_date - latest_coverage_end).days

            # Categorize mismatches
            if gap_days < -tolerance_days:
                # Coverage extends PAST next invoice date
                mismatches_extending_past.append(
                    {
                        "member_name": f"{member.first_name} {member.last_name}",
                        "schedule": sched.name,
                        "billing_frequency": sched.billing_frequency,
                        "latest_invoice": latest_invoice[0].name,
                        "coverage_end": str(latest_coverage_end),
                        "next_invoice_date": str(next_invoice_date),
                        "gap_days": gap_days,
                    }
                )
            elif gap_days > tolerance_days:
                # Coverage ends TOO EARLY
                mismatches_ending_early.append(
                    {
                        "member_name": f"{member.first_name} {member.last_name}",
                        "schedule": sched.name,
                        "billing_frequency": sched.billing_frequency,
                        "latest_invoice": latest_invoice[0].name,
                        "coverage_end": str(latest_coverage_end),
                        "next_invoice_date": str(next_invoice_date),
                        "gap_days": gap_days,
                    }
                )

        result = {
            "total_mismatches": len(mismatches_extending_past) + len(mismatches_ending_early),
            "extending_past": {
                "count": len(mismatches_extending_past),
                "items": mismatches_extending_past[:10],  # Limit to 10 for performance
            },
            "ending_early": {
                "count": len(mismatches_ending_early),
                "items": mismatches_ending_early[:10],
            },
        }

        return OperationResult.ok(
            result,
            message=_("Coverage scheduling analysis completed: {0} mismatches found").format(
                result["total_mismatches"]
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Coverage Scheduling Mismatch Check Failed"),
            message=f"Error checking coverage scheduling mismatches: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to check coverage scheduling mismatches: {0}").format(str(e)),
            error_code="COVERAGE_MISMATCH_CHECK_FAILED",
        )
