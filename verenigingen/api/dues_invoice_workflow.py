"""
Dues Invoice Management Workflow API

This module provides secure API endpoints for:
- Checking member dues invoice status
- Generating missing dues invoices
- Preparing SEPA DD batches from invoices
- Managing the complete dues-to-SEPA workflow

Author: Verenigingen System
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from verenigingen.utils.error_handling import SEPAError, handle_api_error, validate_required_fields
from verenigingen.utils.secure_operations import secure_batch_operation, secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@frappe.whitelist()
@handle_api_error
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_member_dues_status(period_start: str = None, period_end: str = None) -> Dict:
    """
    Check which members need dues invoices for the current period

    Args:
        period_start: Start date for billing period (defaults to current month start)
        period_end: End date for billing period (defaults to current month end)

    Returns:
        Dict with member analysis results
    """
    # Determine billing period
    if not period_start:
        period_start = getdate(today()).replace(day=1)  # First day of current month
    else:
        period_start = getdate(period_start) if isinstance(period_start, str) else period_start
    if not period_end:
        period_end = add_days(add_days(period_start, 32).replace(day=1), -1)  # Last day of month
    else:
        period_end = getdate(period_end) if isinstance(period_end, str) else period_end

    # Operation logged via secure operations framework

    # Get all active members (excluding banned/quit)
    active_members = frappe.db.sql(
        """
            SELECT
                name,
                full_name,
                status,
                member_since
            FROM `tabMember`
            WHERE status IN ('Active', 'Pending', 'Suspended')
            ORDER BY full_name
        """,
        as_dict=True,
    )

    # Continue with full analysis

    # Get members with existing invoices that cover this period
    # Check for invoices where coverage_end_date extends through the end of the month
    members_with_invoices = frappe.db.sql(
        """
        SELECT DISTINCT
            m.name as member,
            si.name as invoice_name,
            si.outstanding_amount,
            si.status,
            si.docstatus,
            si.custom_coverage_start_date,
            si.custom_coverage_end_date,
            CASE
                WHEN si.docstatus = 0 THEN 'Draft'
                WHEN si.docstatus = 1 THEN 'Submitted'
                WHEN si.docstatus = 2 THEN 'Cancelled'
                ELSE 'Unknown'
            END as invoice_state,
            mds.name as schedule_name
        FROM `tabMember` m
        JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name
        JOIN `tabSales Invoice` si ON si.membership_dues_schedule_display = mds.name
        WHERE si.custom_coverage_end_date >= %(period_end)s
        AND si.docstatus IN (0, 1)
        AND m.status IN ('Active', 'Pending', 'Suspended')
    """,
        {"period_end": period_end},
        as_dict=True,
    )

    # Create lookup for quick checking
    members_with_invoices_set = {inv["member"] for inv in members_with_invoices}

    # Identify members missing invoices
    members_missing_invoices = []
    members_with_valid_invoices = []

    for member in active_members:
        if member["name"] in members_with_invoices_set:
            # Get invoice details for this member
            member_invoices = [inv for inv in members_with_invoices if inv["member"] == member["name"]]
            members_with_valid_invoices.append({**member, "invoices": member_invoices})
        else:
            # Check if member has active dues schedule but is missing coverage
            schedule_info = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member["name"], "is_template": 0, "status": "Active"},
                ["name", "billing_frequency", "test_mode"],
                as_dict=True,
            )

            if schedule_info:
                # Skip all schedules in test mode to prevent inappropriate invoice generation
                if schedule_info.test_mode:
                    continue

                # Member has active schedule but no invoice covering this period
                members_missing_invoices.append(member)

    # Get SEPA mandate status for members with invoices
    sepa_eligible_count = 0
    sepa_missing_count = 0

    for member_data in members_with_valid_invoices:
        mandate_exists = frappe.db.exists("SEPA Mandate", {"member": member_data["name"], "status": "Active"})

        if mandate_exists:
            sepa_eligible_count += 1
        else:
            sepa_missing_count += 1

    # Calculate invoice status breakdown
    draft_invoices = sum(
        1
        for member in members_with_valid_invoices
        for invoice in member.get("invoices", [])
        if invoice.get("invoice_state") == "Draft"
    )
    submitted_invoices = sum(
        1
        for member in members_with_valid_invoices
        for invoice in member.get("invoices", [])
        if invoice.get("invoice_state") == "Submitted"
    )

    result = {
        "period_start": period_start,
        "period_end": period_end,
        "summary": {
            "total_active_members": len(active_members),
            "members_with_invoices": len(members_with_valid_invoices),
            "members_missing_invoices": len(members_missing_invoices),
            "invoice_breakdown": {
                "draft_invoices": draft_invoices,
                "submitted_invoices": submitted_invoices,
                "total_invoices": draft_invoices + submitted_invoices,
            },
            "sepa_eligible": sepa_eligible_count,
            "sepa_missing": sepa_missing_count,
        },
        "members_missing_invoices": members_missing_invoices,
        "members_with_invoices": members_with_valid_invoices,
    }

    # Completion logged via secure operations framework

    return result


@frappe.whitelist()
@handle_api_error
@high_security_api(operation_type=OperationType.FINANCIAL)
def generate_missing_invoices(member_list: List[str] = None, force: bool = False) -> Dict:
    """
    Generate invoices for members who are missing them

    Args:
        member_list: List of member names to generate invoices for (if None, generates for all eligible)
        force: Force generation even if validation warnings exist

    Returns:
        Dict with generation results
    """
    if isinstance(member_list, str):
        member_list = frappe.parse_json(member_list)

    # Use the existing bulk invoice generation system instead of one-by-one approach
    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
        generate_dues_invoices,
    )

    # Operation logged via secure operations framework
    # Note: The bulk system processes all eligible schedules, not just specific members
    # This is more efficient and handles thousands of invoices properly
    if member_list:
        frappe.log_error(
            f"Member-specific generation requested for {len(member_list)} members, but using bulk system instead",
            "Invoice Generation Notice",
        )

    # Call the existing bulk invoice generation system
    # This is the same function used by the scheduled task
    bulk_results = generate_dues_invoices(test_mode=False)

    # Transform results to match expected API response format
    result = {
        "success": len(bulk_results.get("errors", [])) == 0,
        "message": _("Bulk generation processed {0} schedules, generated {1} invoices").format(
            bulk_results.get("processed", 0), bulk_results.get("generated", 0)
        ),
        "bulk_results": bulk_results,
        "generated_invoices": bulk_results.get("invoices", []),
        "errors": bulk_results.get("errors", []),
        "note": _("Used bulk processing system for optimal performance with large datasets"),
    }

    # Completion logged via secure operations framework

    return result


@frappe.whitelist()
@handle_api_error
@high_security_api(operation_type=OperationType.FINANCIAL)
def validate_sepa_eligibility(invoice_list: List[str] = None) -> Dict:
    """
    Validate SEPA mandate eligibility for invoices

    Args:
        invoice_list: List of invoice names to check (if None, checks all unpaid invoices)

    Returns:
        Dict with SEPA eligibility analysis
    """
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
            return {
                "eligible_invoices": [],
                "ineligible_invoices": [],
                "summary": {
                    "total_checked": 0,
                    "sepa_eligible": 0,
                    "missing_mandate": 0,
                    "invalid_mandate": 0,
                },
            }

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

        return {
            "eligible_invoices": eligible_invoices,
            "ineligible_invoices": ineligible_invoices,
            "summary": summary,
        }


@frappe.whitelist()
@handle_api_error
@high_security_api(operation_type=OperationType.FINANCIAL)
def prepare_sepa_batch(eligible_invoices: List[Dict], batch_description: str = None) -> Dict:
    """
    Prepare a SEPA Direct Debit batch from eligible invoices

    Args:
        eligible_invoices: List of eligible invoice dictionaries
        batch_description: Optional description for the batch

    Returns:
        Dict with batch creation results
    """
    if isinstance(eligible_invoices, str):
        eligible_invoices = frappe.parse_json(eligible_invoices)

    if not eligible_invoices:
        raise SEPAError(_("No eligible invoices provided for batch creation"))

    # Operation logged via secure operations framework

    # Create Direct Debit Batch
    batch_doc = frappe.new_doc("Direct Debit Batch")
    batch_doc.batch_date = today()
    batch_doc.batch_description = batch_description or f"Dues Collection {today()}"
    batch_doc.batch_type = "RCUR"  # Recurring payments
    batch_doc.currency = "EUR"

    total_amount = 0

    # Add invoices to batch
    for invoice_data in eligible_invoices:
        batch_doc.append(
            "invoices",
            {
                "invoice": invoice_data["invoice"],
                "customer": invoice_data["customer"],
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "mandate_reference": invoice_data["mandate"]["mandate_id"],
                "iban": invoice_data["mandate"]["iban"],
                "bic": invoice_data["mandate"]["bic"],
            },
        )
        total_amount += flt(invoice_data["amount"])

    batch_doc.total_amount = total_amount
    batch_doc.entry_count = len(eligible_invoices)

    # Save the batch
    batch_doc.insert()

    # Determine risk level and approval requirements
    risk_level = "Low"
    if total_amount > 5000 or len(eligible_invoices) > 50:
        risk_level = "High"
    elif total_amount > 2000 or len(eligible_invoices) > 20:
        risk_level = "Medium"

    batch_doc.risk_level = risk_level
    batch_doc.save()

    result = {
        "success": True,
        "batch_name": batch_doc.name,
        "total_amount": total_amount,
        "entry_count": len(eligible_invoices),
        "risk_level": risk_level,
        "requires_approval": risk_level in ["Medium", "High"],
    }

    # Completion logged via secure operations framework

    return result


@frappe.whitelist()
@handle_api_error
@standard_api(operation_type=OperationType.REPORTING)
def get_workflow_status() -> Dict:
    """
    Get current status of the dues invoice workflow

    Returns:
        Dict with workflow status information
    """
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

    # Get members without recent invoices
    members_analysis = check_member_dues_status()

    return {
        "recent_batches": recent_batches,
        "pending_invoices": pending_invoices,
        "members_analysis": members_analysis["summary"],
    }
