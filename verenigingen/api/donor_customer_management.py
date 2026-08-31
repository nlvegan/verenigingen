"""
API endpoints for Donor-Customer management and integration

This module provides RESTful endpoints for managing the relationship
between Donor and Customer records.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_donor_customer_info(donor_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Get comprehensive information about donor and its customer integration

    Args:
        donor_name: Name of the donor record

    Returns:
        OperationResult: Donor and customer information
    """
    try:
        # Get donor document
        if not frappe.db.exists("Donor", donor_name):
            return OperationResult.fail(message=_("Donor not found"), error_code="DONOR_NOT_FOUND")

        donor_doc = frappe.get_doc("Donor", donor_name)

        # Get customer information if linked
        customer_info = donor_doc.get_customer_info()

        # Get donation summary
        donation_summary = get_donor_donation_summary(donor_name)

        data = {
            "donor": {
                "name": donor_doc.name,
                "donor_name": donor_doc.donor_name,
                "email": getattr(donor_doc, "donor_email", ""),
                "phone": getattr(donor_doc, "phone", ""),
                "donor_type": donor_doc.donor_type,
                "customer": donor_doc.customer,
                "customer_sync_status": getattr(donor_doc, "customer_sync_status", ""),
                "last_customer_sync": getattr(donor_doc, "last_customer_sync", ""),
            },
            "customer": customer_info,
            "donations": donation_summary,
            "integration_status": {
                "has_customer": bool(donor_doc.customer),
                "sync_status": getattr(donor_doc, "customer_sync_status", "Unknown"),
                "can_create_customer": not bool(donor_doc.customer),
                "needs_sync": getattr(donor_doc, "customer_sync_status", "") != "Synced",
            },
        }

        return OperationResult.ok(data=data, message=_("Donor-customer information retrieved successfully"))

    except Exception as e:
        error_msg = _("Error getting donor-customer info: {0}").format(str(e))
        frappe.log_error(
            title=_("Donor Customer Info Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=error_msg, error_code="DONOR_CUSTOMER_INFO_ERROR")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def force_donor_customer_sync(donor_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Force synchronization of donor with customer record

    Args:
        donor_name: Name of the donor record

    Returns:
        OperationResult: Result of sync operation
    """
    try:
        if not frappe.db.exists("Donor", donor_name):
            return OperationResult.fail(message=_("Donor not found"), error_code="DONOR_NOT_FOUND")

        donor_doc = frappe.get_doc("Donor", donor_name)

        # Force sync
        donor_doc.flags.ignore_customer_sync = False
        original_customer = donor_doc.customer

        donor_doc.sync_with_customer()
        donor_doc.save()

        # Determine what happened
        if not original_customer and donor_doc.customer:
            action = _("created")
        elif original_customer != donor_doc.customer:
            action = _("updated")
        else:
            action = _("synced")

        data = {
            "customer": donor_doc.customer,
            "sync_status": donor_doc.customer_sync_status,
            "last_sync": donor_doc.last_customer_sync,
            "action": action,
        }

        return OperationResult.ok(data=data, message=_("Customer {0} successfully").format(action))

    except NON_RESUMABLE_DB_ERRORS:
        # The handler below logs and returns a 200 "sync failed"; both are writes on a
        # transaction the server has already discarded. Reachable only since
        # sync_with_customer stopped swallowing (#666).
        raise
    except Exception as e:
        error_msg = _("Error forcing donor-customer sync: {0}").format(str(e))
        frappe.log_error(
            title=_("Donor Customer Sync Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=error_msg, error_code="DONOR_CUSTOMER_SYNC_ERROR")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def unlink_donor_customer(donor_name: str, remove_customer=False) -> OperationResult[Dict[str, Any]]:
    """
    Unlink donor from customer record

    Args:
        donor_name: Name of the donor record
        remove_customer: Whether to also delete the customer record

    Returns:
        OperationResult: Result of unlink operation
    """
    try:
        if not frappe.db.exists("Donor", donor_name):
            return OperationResult.fail(message=_("Donor not found"), error_code="DONOR_NOT_FOUND")

        donor_doc = frappe.get_doc("Donor", donor_name)

        if not donor_doc.customer:
            return OperationResult.fail(
                message=_("No customer linked to this donor"), error_code="NO_CUSTOMER_LINKED"
            )

        customer_name = donor_doc.customer

        # Remove customer reference from donor
        donor_doc.customer = ""
        donor_doc.customer_sync_status = ""
        donor_doc.last_customer_sync = ""
        donor_doc.flags.ignore_customer_sync = True
        donor_doc.save()

        # Remove donor reference from customer
        if frappe.db.exists("Customer", customer_name):
            frappe.db.set_value("Customer", customer_name, "donor", "")

            # Delete customer if requested and it has no transactions
            if remove_customer:
                customer_doc = frappe.get_doc("Customer", customer_name)

                # Check for existing transactions
                has_transactions = frappe.db.exists("Sales Invoice", {"customer": customer_name})

                if not has_transactions:
                    customer_doc.delete()
                    data = {"customer_deleted": True, "customer_name": customer_name}
                    return OperationResult.ok(
                        data=data, message=_("Donor unlinked and customer deleted successfully")
                    )
                else:
                    data = {
                        "customer_deleted": False,
                        "customer_name": customer_name,
                        "warning": _("Customer has existing transactions and cannot be deleted"),
                    }
                    return OperationResult.ok(
                        data=data,
                        message=_("Donor unlinked but customer retained due to existing transactions"),
                    )

        data = {"customer_unlinked": True, "customer_name": customer_name}
        return OperationResult.ok(data=data, message=_("Donor unlinked from customer successfully"))

    except Exception as e:
        error_msg = _("Error unlinking donor-customer: {0}").format(str(e))
        frappe.log_error(
            title=_("Donor Customer Unlink Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=error_msg, error_code="DONOR_CUSTOMER_UNLINK_ERROR")


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_donor_sync_dashboard() -> OperationResult[Dict[str, Any]]:
    """
    Get dashboard data for donor-customer synchronization management

    Returns:
        OperationResult: Dashboard statistics and data
    """
    try:
        from verenigingen.utils.donor_customer_sync import get_sync_status_summary

        # Get sync status summary
        sync_summary = get_sync_status_summary()

        # Get recent sync activities
        recent_syncs = frappe.db.sql(
            """
            SELECT
                name,
                donor_name,
                customer,
                customer_sync_status,
                last_customer_sync,
                modified
            FROM `tabDonor`
            WHERE last_customer_sync IS NOT NULL
            ORDER BY last_customer_sync DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get donors needing sync
        needs_sync = frappe.db.sql(
            """
            SELECT
                name,
                donor_name,
                customer_sync_status,
                modified
            FROM `tabDonor`
            WHERE (customer_sync_status IS NULL OR customer_sync_status != 'Synced')
            AND customer IS NOT NULL
            ORDER BY modified DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get donors without customers
        no_customers = frappe.db.sql(
            """
            SELECT
                name,
                donor_name,
                donor_email,
                modified
            FROM `tabDonor`
            WHERE (customer IS NULL OR customer = '')
            ORDER BY modified DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        data = {
            "summary": sync_summary,
            "recent_syncs": recent_syncs,
            "needs_sync": needs_sync,
            "no_customers": no_customers,
            "dashboard_updated": frappe.utils.now(),
        }

        return OperationResult.ok(data=data, message=_("Donor sync dashboard data retrieved successfully"))

    except Exception as e:
        error_msg = _("Error getting sync dashboard: {0}").format(str(e))
        frappe.log_error(
            title=_("Donor Sync Dashboard Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=error_msg, error_code="DONOR_SYNC_DASHBOARD_ERROR")


def get_donor_donation_summary(donor_name):
    """
    Get donation summary for a donor

    Args:
        donor_name: Name of the donor record

    Returns:
        dict: Donation statistics
    """
    try:
        # Get donation statistics
        donation_stats = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_donations,
                COALESCE(SUM(amount), 0) as total_amount,
                COALESCE(SUM(CASE WHEN paid = 1 THEN amount ELSE 0 END), 0) as paid_amount,
                COUNT(CASE WHEN paid = 1 THEN 1 END) as paid_donations,
                MAX(donation_date) as last_donation_date
            FROM `tabDonation`
            WHERE donor = %s AND docstatus < 2
        """,
            (donor_name,),
            as_dict=True,
        )

        stats = donation_stats[0] if donation_stats else {}

        # Get recent donations
        recent_donations = frappe.db.sql(
            """
            SELECT
                name,
                amount,
                donation_date,
                paid,
                status
            FROM `tabDonation`
            WHERE donor = %s AND docstatus < 2
            ORDER BY donation_date DESC
            LIMIT 5
        """,
            (donor_name,),
            as_dict=True,
        )

        return {"statistics": stats, "recent_donations": recent_donations}

    except Exception as e:
        frappe.log_error(f"Error getting donation summary for donor {donor_name}: {str(e)}")
        return {"error": str(e)}
