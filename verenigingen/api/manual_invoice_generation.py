#!/usr/bin/env python3
"""
Manual Invoice Generation API

This module provides secure API endpoints for generating manual invoices for member
dues and payments in the Verenigingen association management system. It handles
critical financial operations with comprehensive validation and security controls.

Key Features:
    - Manual invoice generation for member dues schedules
    - Critical security validation for financial operations
    - Integration with customer records and billing systems
    - Comprehensive error handling and validation
    - Audit logging for financial operations

Business Process:
    1. Validate member existence and customer linkage
    2. Locate active dues schedule for the member
    3. Generate invoice using schedule configuration
    4. Return invoice details for processing

Security Model:
    - Critical API security level for financial operations
    - Comprehensive input validation and sanitization
    - Audit logging for all invoice generation activities
    - Permission-based access control

Integration Points:
    - Member and Customer DocTypes
    - Membership Dues Schedule system
    - Sales Invoice generation
    - Financial reporting and tracking

Compliance:
    - Financial audit trail requirements
    - Data protection (GDPR) compliance
    - Accounting standards compliance
    - Payment processing regulations

Author: Verenigingen Development Team
License: MIT
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def generate_manual_invoice(member_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Generate a manual invoice for a member's current active dues schedule.

    This critical API function creates invoices outside the normal automated
    billing cycle, typically used for special circumstances, billing corrections,
    or immediate payment requirements. It ensures proper validation and
    integration with the existing billing infrastructure.

    Args:
        member_name (str): The unique identifier/name of the Member record
                          for which to generate the invoice. Must be a valid
                          Member document name with an active dues schedule.

    Returns:
        OperationResult[Dict[str, Any]]: Invoice generation result with data:
            {
                'invoice_name': 'INV-2024-001',
                'amount': 25.00,
                'customer': 'CUST-001',
                'dues_schedule': 'MDS-2024-001'
            }

    Raises:
        frappe.ValidationError: If member data is invalid or inconsistent
        frappe.PermissionError: If user lacks invoice generation permissions

    Security:
        - Uses critical API security level for financial operations
        - Validates user permissions for invoice generation
        - Comprehensive audit logging for financial operations
        - Input sanitization and validation

    Business Logic:
        - Validates member existence and customer linkage
        - Requires active dues schedule for invoice generation
        - Uses force=True to bypass normal billing cycle checks
        - Integrates with existing invoice numbering and tracking

    Prerequisites:
        - Member must exist and be active
        - Member must have linked Customer record
        - Member must have active (non-template) dues schedule
        - User must have appropriate financial permissions

    Database Access:
        - Reads from: tabMember, tabMembership Dues Schedule
        - Creates: Sales Invoice documents
        - Updates: Invoice tracking and audit logs

    Integration Points:
        - Sales Invoice DocType for billing
        - Customer management system
        - Financial reporting and analytics
        - Payment tracking and reconciliation
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return OperationResult.fail(
                _("Member {0} not found").format(member_name), error_code="MEMBER_NOT_FOUND"
            )

        member = frappe.get_doc("Member", member_name)

        # Check if member has a customer record
        if not member.customer:
            return OperationResult.fail(
                _(
                    "Member must have a customer record to generate invoices. Please create a customer record first."
                ),
                error_code="NO_CUSTOMER_RECORD",
            )

        # Find the member's active dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            ["name", "dues_rate", "billing_frequency", "member_name"],
            as_dict=True,
        )

        if not dues_schedule:
            return OperationResult.fail(
                _("No active dues schedule found for this member. Please create a dues schedule first."),
                error_code="NO_ACTIVE_DUES_SCHEDULE",
            )

        schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule.name)

        # Generate the invoice using the schedule's method
        try:
            # generate_invoice returns the Sales Invoice document (or None), not
            # its name — take .name for the response payload and message.
            invoice = schedule_doc.generate_invoice(force=True)  # Force generation for manual invoices

            if invoice:
                invoice_name = invoice.name
                data = {
                    "invoice_name": invoice_name,
                    "amount": flt(dues_schedule.dues_rate, 2),
                    "customer": member.customer,
                    "dues_schedule": dues_schedule.name,
                }
                return OperationResult.ok(
                    data, message=_("Invoice {0} generated successfully").format(invoice_name)
                )
            else:
                return OperationResult.fail(
                    _("Failed to generate invoice - no invoice created"),
                    error_code="INVOICE_GENERATION_FAILED",
                )

        except Exception as invoice_error:
            frappe.log_error(
                f"Invoice generation error for member {member_name}: {str(invoice_error)}\n{traceback.format_exc()}",
                "Manual Invoice Generation Error",
            )
            return OperationResult.fail(
                _("Error generating invoice: {0}").format(str(invoice_error)),
                error_code="INVOICE_GENERATION_ERROR",
            )

    except Exception as e:
        frappe.log_error(
            f"Error in manual invoice generation for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Manual Invoice Generation Error",
        )
        return OperationResult.fail(_("Unexpected error: {0}").format(str(e)), error_code="UNEXPECTED_ERROR")


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def get_member_invoice_info(member_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Get information about member's dues schedule and recent invoices for UI display

    Args:
        member_name: Name of the Member record

    Returns:
        OperationResult[Dict[str, Any]]: Member invoice information
    """
    try:
        if not frappe.db.exists("Member", member_name):
            return OperationResult.fail(
                _("Member {0} not found").format(member_name), error_code="MEMBER_NOT_FOUND"
            )

        member = frappe.get_doc("Member", member_name)

        # Get dues schedule info
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            ["name", "dues_rate", "billing_frequency", "next_invoice_date", "last_invoice_date"],
            as_dict=True,
        )

        data = {
            "member_name": member.full_name,
            "has_customer": bool(member.customer),
            "customer": member.customer,
            "has_dues_schedule": bool(dues_schedule),
        }

        if dues_schedule:
            data.update(
                {
                    "dues_schedule_name": dues_schedule.name,
                    "current_rate": flt(dues_schedule.dues_rate, 2),
                    "billing_frequency": dues_schedule.billing_frequency,
                    "next_invoice_date": dues_schedule.next_invoice_date,
                    "last_invoice_date": dues_schedule.last_invoice_date,
                }
            )

            # Get recent invoices for this member
            if member.customer:
                recent_invoices = frappe.get_all(
                    "Sales Invoice",
                    filters={"customer": member.customer, "docstatus": ["!=", 2]},  # Not cancelled
                    fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
                    order_by="posting_date desc",
                    limit=5,
                )
                data["recent_invoices"] = recent_invoices

        return OperationResult.ok(data, message=_("Member invoice information retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting invoice info for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Get Member Invoice Info Error",
        )
        return OperationResult.fail(
            _("Error retrieving information: {0}").format(str(e)), error_code="RETRIEVAL_ERROR"
        )
