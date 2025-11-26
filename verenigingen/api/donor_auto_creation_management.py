"""
Donor Auto-Creation Management API

This module provides comprehensive API endpoints for managing the automatic
creation of donor records in the Verenigingen association management system.
It handles donor registration automation, threshold management, and reporting
on donor creation activities.

Key Features:
    - Automated donor record creation based on donation thresholds
    - Comprehensive dashboard for donor auto-creation monitoring
    - Settings management for auto-creation parameters
    - Statistical reporting and analytics
    - Recent activity tracking and management
    - Integration with donation processing systems

Business Logic:
    - Automatic donor creation when donation amounts exceed thresholds
    - Configurable creation triggers and parameters
    - Duplicate prevention and validation mechanisms
    - Integration with existing donor and member systems
    - Comprehensive audit trail for auto-created records

Architecture:
    - Dashboard-driven management interface
    - Real-time statistics and reporting
    - Integration with Verenigingen Settings system
    - Performance-optimized queries for large datasets
    - Caching for frequently accessed data

Security Model:
    - Standard API security for reporting operations
    - Settings access controls for configuration management
    - Audit logging for all auto-creation activities
    - Input validation and sanitization

Integration Points:
    - Donor DocType for record creation
    - Donation processing for trigger detection
    - Verenigingen Settings for configuration
    - Member system for relationship management
    - Financial reporting and analytics systems

Performance Considerations:
    - Optimized queries for statistical aggregation
    - Efficient filtering for large donor datasets
    - Background processing for bulk operations
    - Caching for dashboard data

Author: Verenigingen Development Team
License: MIT
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.operation_result import OperationResult

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
    utility_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_auto_creation_dashboard() -> OperationResult[Dict[str, Any]]:
    """
    Get comprehensive dashboard data for donor auto-creation management

    Returns:
        OperationResult: Dashboard data including settings, stats, and recent activity
    """
    try:
        # Get current settings
        settings = frappe.get_single("Verenigingen Settings")

        # Get statistics
        stats = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_auto_created,
                COALESCE(SUM(creation_trigger_amount), 0) as total_trigger_amount,
                COUNT(CASE WHEN creation >= CURDATE() - INTERVAL 7 DAY THEN 1 END) as created_this_week,
                COUNT(CASE WHEN creation >= CURDATE() - INTERVAL 30 DAY THEN 1 END) as created_this_month
            FROM `tabDonor`
            WHERE customer_sync_status = 'Auto-Created'
        """,
            as_dict=True,
        )[0]

        # Get recent creations
        recent_creations = frappe.db.sql(
            """
            SELECT
                name,
                donor_name,
                customer,
                creation_trigger_amount,
                created_from_payment,
                creation
            FROM `tabDonor`
            WHERE customer_sync_status = 'Auto-Created'
            ORDER BY creation DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get eligible customer groups summary
        eligible_groups = []
        if settings.donor_customer_groups:
            groups = [g.strip() for g in settings.donor_customer_groups.split(",")]
            for group in groups:
                count = frappe.db.count("Customer", {"customer_group": group})
                eligible_groups.append({"name": group, "customer_count": count})
        else:
            total_customers = frappe.db.count("Customer")
            eligible_groups = [{"name": "All Customer Groups", "customer_count": total_customers}]

        data = {
            "settings": {
                "enabled": bool(settings.auto_create_donors),
                "donations_gl_account": settings.donations_gl_account,
                "donations_gl_account_name": (
                    frappe.db.get_value("Account", settings.donations_gl_account, "account_name")
                    if settings.donations_gl_account
                    else None
                ),
                "eligible_customer_groups": settings.donor_customer_groups,
                "minimum_amount": settings.minimum_donation_amount,
            },
            "statistics": stats,
            "recent_creations": recent_creations,
            "eligible_groups": eligible_groups,
        }

        return OperationResult.ok(data, message=_("Auto-creation dashboard data retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting auto-creation dashboard: {str(e)}\n{traceback.format_exc()}",
            "Auto-Creation Dashboard Error",
        )
        return OperationResult.fail(
            _("Failed to retrieve auto-creation dashboard data"),
            errors=[str(e)],
            context={"operation": "get_auto_creation_dashboard"},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def update_auto_creation_settings(
    enabled, donations_gl_account=None, eligible_customer_groups=None, minimum_amount=0
) -> OperationResult[Dict[str, Any]]:
    """
    Update donor auto-creation settings

    Args:
        enabled: Boolean to enable/disable auto-creation
        donations_gl_account: GL Account for donations
        eligible_customer_groups: Comma-separated customer groups
        minimum_amount: Minimum donation amount threshold

    Returns:
        OperationResult: Updated settings
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")

        # Update settings
        settings.auto_create_donors = int(enabled)
        if donations_gl_account:
            settings.donations_gl_account = donations_gl_account
        if eligible_customer_groups is not None:
            settings.donor_customer_groups = eligible_customer_groups
        if minimum_amount is not None:
            settings.minimum_donation_amount = flt(minimum_amount)

        settings.save()

        data = {
            "enabled": bool(settings.auto_create_donors),
            "donations_gl_account": settings.donations_gl_account,
            "eligible_customer_groups": settings.donor_customer_groups,
            "minimum_amount": settings.minimum_donation_amount,
        }

        return OperationResult.ok(data, message=_("Auto-creation settings updated successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error updating auto-creation settings: {str(e)}\n{traceback.format_exc()}",
            "Auto-Creation Settings Error",
        )
        return OperationResult.fail(
            _("Failed to update auto-creation settings"),
            errors=[str(e)],
            context={"operation": "update_auto_creation_settings"},
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def test_customer_eligibility(customer_name, amount) -> OperationResult[Dict[str, Any]]:
    """
    Test if a customer would be eligible for donor auto-creation

    Args:
        customer_name: Customer to test
        amount: Donation amount to test

    Returns:
        OperationResult: Eligibility test results
    """
    from verenigingen.utils.donor_auto_creation import test_auto_creation_conditions

    try:
        result = test_auto_creation_conditions(customer_name, flt(amount))
        return OperationResult.ok(result, message=_("Customer eligibility test completed"))

    except Exception as e:
        frappe.log_error(
            f"Error testing customer eligibility: {str(e)}\n{traceback.format_exc()}",
            "Customer Eligibility Test Error",
        )
        return OperationResult.fail(
            _("Failed to test customer eligibility"),
            errors=[str(e)],
            context={"operation": "test_customer_eligibility", "customer_name": customer_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_donations_gl_accounts() -> OperationResult[Dict[str, Any]]:
    """
    Get available GL accounts suitable for donations

    Returns:
        OperationResult: Available donation GL accounts
    """
    try:
        # Get income accounts that could be used for donations
        accounts = frappe.db.get_all(
            "Account",
            filters={"account_type": "Income", "is_group": 0, "disabled": 0},
            fields=["name", "account_name", "account_number", "company"],
            order_by="account_name",
        )

        return OperationResult.ok({"accounts": accounts}, message=_("GL accounts retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting donations GL accounts: {str(e)}\n{traceback.format_exc()}", "GL Accounts Error"
        )
        return OperationResult.fail(
            _("Failed to retrieve GL accounts"),
            errors=[str(e)],
            context={"operation": "get_donations_gl_accounts"},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_customer_groups() -> OperationResult[Dict[str, Any]]:
    """
    Get available customer groups for eligibility configuration

    Returns:
        OperationResult: Available customer groups
    """
    try:
        groups = frappe.db.get_all(
            "Customer Group",
            filters={"is_group": 0},
            fields=["name", "customer_group_name"],
            order_by="customer_group_name",
        )

        # Add customer counts
        for group in groups:
            group["customer_count"] = frappe.db.count("Customer", {"customer_group": group.name})

        return OperationResult.ok({"groups": groups}, message=_("Customer groups retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting customer groups: {str(e)}\n{traceback.format_exc()}", "Customer Groups Error"
        )
        return OperationResult.fail(
            _("Failed to retrieve customer groups"),
            errors=[str(e)],
            context={"operation": "get_customer_groups"},
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def simulate_auto_creation(customer_name, amount, donations_account=None) -> OperationResult[Dict[str, Any]]:
    """
    Simulate donor auto-creation without actually creating records

    Args:
        customer_name: Customer to simulate for
        amount: Donation amount
        donations_account: GL account to use (optional)

    Returns:
        OperationResult: Simulation results
    """
    from verenigingen.utils.donor_auto_creation import has_existing_donor, is_customer_group_eligible

    try:
        settings = frappe.get_single("Verenigingen Settings")

        # Use provided account or settings account
        account = donations_account or settings.donations_gl_account

        simulation = {
            "would_create": False,
            "customer_data": {},
            "donor_data": {},
            "conditions": {},
            "messages": [],
        }

        # Check if customer exists
        if not frappe.db.exists("Customer", customer_name):
            simulation["conditions"]["customer_exists"] = False
            simulation["messages"].append(f"Customer '{customer_name}' does not exist")
            return OperationResult.ok(simulation, message=_("Simulation completed - customer not found"))

        customer_doc = frappe.get_doc("Customer", customer_name)
        simulation["customer_data"] = {
            "name": customer_doc.name,
            "customer_name": customer_doc.customer_name,
            "customer_group": customer_doc.customer_group,
            "email_id": customer_doc.email_id,
        }

        # Check all conditions
        simulation["conditions"]["auto_creation_enabled"] = bool(settings.auto_create_donors)
        if not settings.auto_create_donors:
            simulation["messages"].append("Auto-creation is disabled")
            return OperationResult.ok(simulation, message=_("Simulation completed - auto-creation disabled"))

        simulation["conditions"]["donations_account_configured"] = bool(account)
        if not account:
            simulation["messages"].append("No donations GL account configured")
            return OperationResult.ok(
                simulation, message=_("Simulation completed - no donations account configured")
            )

        simulation["conditions"]["customer_group_eligible"] = is_customer_group_eligible(
            customer_doc.customer_group, settings
        )
        if not simulation["conditions"]["customer_group_eligible"]:
            simulation["messages"].append(f"Customer group '{customer_doc.customer_group}' not eligible")
            return OperationResult.ok(
                simulation, message=_("Simulation completed - customer group not eligible")
            )

        simulation["conditions"]["amount_sufficient"] = flt(amount) >= flt(settings.minimum_donation_amount)
        if not simulation["conditions"]["amount_sufficient"]:
            simulation["messages"].append(f"Amount {amount} below minimum {settings.minimum_donation_amount}")
            return OperationResult.ok(simulation, message=_("Simulation completed - amount below minimum"))

        simulation["conditions"]["donor_already_exists"] = has_existing_donor(customer_name)
        if simulation["conditions"]["donor_already_exists"]:
            simulation["messages"].append("Donor already exists for this customer")
            return OperationResult.ok(simulation, message=_("Simulation completed - donor already exists"))

        # All conditions met - simulate donor creation
        simulation["would_create"] = True
        simulation["donor_data"] = {
            "donor_name": customer_doc.customer_name,
            "donor_type": "Organization" if customer_doc.customer_type == "Company" else "Individual",
            "donor_email": customer_doc.email_id,
            "customer": customer_doc.name,
            "creation_trigger_amount": flt(amount),
            "customer_sync_status": "Auto-Created",
        }
        simulation["messages"].append("All conditions met - donor would be created")

        return OperationResult.ok(simulation, message=_("Simulation completed - donor would be created"))

    except Exception as e:
        frappe.log_error(
            f"Error in donor creation simulation: {str(e)}\n{traceback.format_exc()}",
            "Auto-Creation Simulation Error",
        )
        return OperationResult.fail(
            _("Failed to simulate donor creation"),
            errors=[str(e)],
            context={"operation": "simulate_auto_creation", "customer_name": customer_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_recent_error_logs() -> OperationResult[Dict[str, Any]]:
    """
    Get recent error logs for debugging

    Returns:
        OperationResult: Recent error logs
    """
    try:
        recent_errors = frappe.db.get_all(
            "Error Log",
            filters={"creation": [">", frappe.utils.add_days(frappe.utils.now(), -1)]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=3,
        )

        detailed_errors = []
        for error_info in recent_errors:
            error_doc = frappe.get_doc("Error Log", error_info.name)
            detailed_errors.append(
                {"name": error_info.name, "creation": error_info.creation, "error": error_doc.error}
            )

        return OperationResult.ok(
            {"errors": detailed_errors}, message=_("Recent error logs retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(
            f"Error getting recent error logs: {str(e)}\n{traceback.format_exc()}",
            "Error Logs Retrieval Error",
        )
        return OperationResult.fail(
            _("Failed to retrieve error logs"),
            errors=[str(e)],
            context={"operation": "get_recent_error_logs"},
        )


@frappe.whitelist()
@utility_api(operation_type=OperationType.UTILITY)
def check_test_accounts() -> OperationResult[Dict[str, Any]]:
    """
    Check available accounts for testing purposes

    Returns:
        OperationResult: Available test accounts information
    """
    try:
        # Check income accounts
        income_accounts = frappe.db.get_all(
            "Account",
            filters={"account_type": "Income", "is_group": 0},
            fields=["name", "account_name", "disabled"],
            limit=10,
        )

        # Check receivable accounts
        receivable_accounts = frappe.db.get_all(
            "Account",
            filters={"account_type": "Receivable", "is_group": 0, "disabled": 0},
            fields=["name", "account_name"],
            limit=5,
        )

        # Check customer groups
        customer_groups = frappe.db.get_all(
            "Customer Group", filters={"is_group": 0}, fields=["name"], limit=5
        )

        # Check all account types available
        all_account_types = frappe.db.sql(
            """
            SELECT DISTINCT account_type, COUNT(*) as count
            FROM `tabAccount`
            WHERE is_group = 0
            GROUP BY account_type
            ORDER BY account_type
        """,
            as_dict=True,
        )

        data = {
            "income_accounts": income_accounts,
            "receivable_accounts": receivable_accounts,
            "customer_groups": customer_groups,
            "all_account_types": all_account_types,
        }

        return OperationResult.ok(data, message=_("Test accounts information retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error checking test accounts: {str(e)}\n{traceback.format_exc()}", "Test Accounts Check Error"
        )
        return OperationResult.fail(
            _("Failed to check test accounts"),
            errors=[str(e)],
            context={"operation": "check_test_accounts"},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_process_pending_payments(
    donations_account=None, date_from=None, date_to=None
) -> OperationResult[Dict[str, Any]]:
    """
    Process existing payments retroactively for donor creation

    Args:
        donations_account: GL account to check (optional)
        date_from: Start date for processing (optional)
        date_to: End date for processing (optional)

    Returns:
        OperationResult: Processing results
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        account = donations_account or settings.donations_gl_account

        if not account:
            return OperationResult.fail(
                _("No donations GL account specified"),
                errors=["Missing donations account"],
                context={"operation": "bulk_process_pending_payments"},
            )

        # Build filters for Payment Entries
        filters = {"payment_type": "Receive", "party_type": "Customer", "docstatus": 1}  # Submitted only

        if date_from:
            filters["posting_date"] = [">=", date_from]
        if date_to:
            if "posting_date" in filters:
                filters["posting_date"] = ["between", [date_from, date_to]]
            else:
                filters["posting_date"] = ["<=", date_to]

        # Get eligible payments
        payments = frappe.get_all(
            "Payment Entry", filters=filters, fields=["name", "party", "paid_amount", "posting_date"]
        )

        results = {"processed": 0, "created": 0, "skipped": 0, "errors": 0, "details": []}

        for payment in payments:
            try:
                results["processed"] += 1

                # Check if payment involves donations account
                payment_doc = frappe.get_doc("Payment Entry", payment.name)

                # Simple check - if paid_to matches donations account
                if payment_doc.paid_to == account:
                    # Check if customer is eligible for donor creation
                    from verenigingen.utils.donor_auto_creation import (
                        create_donor_from_customer,
                        has_existing_donor,
                        is_customer_group_eligible,
                    )

                    if has_existing_donor(payment.party):
                        results["skipped"] += 1
                        results["details"].append(
                            {
                                "payment": payment.name,
                                "customer": payment.party,
                                "status": "skipped",
                                "reason": "Donor already exists",
                            }
                        )
                        continue

                    customer_doc = frappe.get_doc("Customer", payment.party)

                    if not is_customer_group_eligible(customer_doc.customer_group, settings):
                        results["skipped"] += 1
                        results["details"].append(
                            {
                                "payment": payment.name,
                                "customer": payment.party,
                                "status": "skipped",
                                "reason": f"Customer group {customer_doc.customer_group} not eligible",
                            }
                        )
                        continue

                    if flt(payment.paid_amount) < flt(settings.minimum_donation_amount):
                        results["skipped"] += 1
                        results["details"].append(
                            {
                                "payment": payment.name,
                                "customer": payment.party,
                                "status": "skipped",
                                "reason": f"Amount {payment.paid_amount} below minimum",
                            }
                        )
                        continue

                    # Create donor
                    donor_name = create_donor_from_customer(customer_doc, payment.paid_amount, payment.name)

                    if donor_name:
                        results["created"] += 1
                        results["details"].append(
                            {
                                "payment": payment.name,
                                "customer": payment.party,
                                "donor": donor_name,
                                "status": "created",
                                "amount": payment.paid_amount,
                            }
                        )
                    else:
                        results["errors"] += 1
                        results["details"].append(
                            {
                                "payment": payment.name,
                                "customer": payment.party,
                                "status": "error",
                                "reason": "Failed to create donor",
                            }
                        )
                else:
                    results["skipped"] += 1

            except Exception as e:
                results["errors"] += 1
                results["details"].append({"payment": payment.name, "status": "error", "reason": str(e)})

        return OperationResult.ok(
            results,
            message=_(
                "Bulk processing completed: {0} created, {1} skipped, {2} errors".format(
                    results["created"], results["skipped"], results["errors"]
                )
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error in bulk processing: {str(e)}\n{traceback.format_exc()}", "Bulk Processing Error"
        )
        return OperationResult.fail(
            _("Failed to process pending payments"),
            errors=[str(e)],
            context={"operation": "bulk_process_pending_payments"},
        )
