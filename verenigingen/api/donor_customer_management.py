"""
API endpoints for Donor-Customer management and integration

This module provides RESTful endpoints for managing the relationship
between Donor and Customer records.
"""

import frappe
from frappe import _

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_donor_customer_info(donor_name):
    """
    Get comprehensive information about donor and its customer integration

    Args:
        donor_name: Name of the donor record

    Returns:
        dict: Donor and customer information
    """
    try:
        # Get donor document
        if not frappe.db.exists("Donor", donor_name):
            return {"error": "Donor not found"}

        donor_doc = frappe.get_doc("Donor", donor_name)

        # Get customer information if linked
        customer_info = donor_doc.get_customer_info()

        # Get donation summary
        donation_summary = get_donor_donation_summary(donor_name)

        return {
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

    except Exception as e:
        frappe.log_error(f"Error getting donor-customer info: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def force_donor_customer_sync(donor_name):
    """
    Force synchronization of donor with customer record

    Args:
        donor_name: Name of the donor record

    Returns:
        dict: Result of sync operation
    """
    try:
        if not frappe.db.exists("Donor", donor_name):
            return {"error": "Donor not found"}

        donor_doc = frappe.get_doc("Donor", donor_name)

        # Force sync
        donor_doc.flags.ignore_customer_sync = False
        original_customer = donor_doc.customer

        donor_doc.sync_with_customer()
        donor_doc.save()

        # Determine what happened
        if not original_customer and donor_doc.customer:
            action = "created"
        elif original_customer != donor_doc.customer:
            action = "updated"
        else:
            action = "synced"

        return {
            "success": True,
            "message": f"Customer {action} successfully",
            "customer": donor_doc.customer,
            "sync_status": donor_doc.customer_sync_status,
            "last_sync": donor_doc.last_customer_sync,
        }

    except Exception as e:
        frappe.log_error(f"Error forcing donor-customer sync: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def unlink_donor_customer(donor_name, remove_customer=False):
    """
    Unlink donor from customer record

    Args:
        donor_name: Name of the donor record
        remove_customer: Whether to also delete the customer record

    Returns:
        dict: Result of unlink operation
    """
    try:
        if not frappe.db.exists("Donor", donor_name):
            return {"error": "Donor not found"}

        donor_doc = frappe.get_doc("Donor", donor_name)

        if not donor_doc.customer:
            return {"error": "No customer linked to this donor"}

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
                    return {"success": True, "message": "Donor unlinked and customer deleted successfully"}
                else:
                    return {
                        "success": True,
                        "message": "Donor unlinked but customer retained due to existing transactions",
                        "warning": "Customer has existing transactions and cannot be deleted",
                    }

        return {"success": True, "message": "Donor unlinked from customer successfully"}

    except Exception as e:
        frappe.log_error(f"Error unlinking donor-customer: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_donor_sync_dashboard():
    """
    Get dashboard data for donor-customer synchronization management

    Returns:
        dict: Dashboard statistics and data
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

        return {
            "summary": sync_summary,
            "recent_syncs": recent_syncs,
            "needs_sync": needs_sync,
            "no_customers": no_customers,
            "dashboard_updated": frappe.utils.now(),
        }

    except Exception as e:
        frappe.log_error(f"Error getting sync dashboard: {str(e)}")
        return {"error": str(e)}


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
            WHERE donor = %s AND docstatus = 1
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
            WHERE donor = %s AND docstatus = 1
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
