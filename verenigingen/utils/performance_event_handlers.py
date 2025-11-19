#!/usr/bin/env python3
"""
Performance Optimization Event Handlers
=======================================

This module provides event-driven performance optimization handlers that replace
the dangerous monkey patching approach with safe, Frappe-native event hooks.

Instead of replacing existing methods, this module provides handlers that can be
called from document event hooks to trigger optimized operations when appropriate.
"""

import json
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from verenigingen.utils.optimized_queries import (
    OptimizedMemberQueries,
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    validate_member_names,
)


class PerformanceEventHandlers:
    """
    Event handlers for performance optimization using proper Frappe patterns

    This class provides event handlers that can be called from document hooks
    instead of monkey patching existing methods.
    """

    @staticmethod
    def on_member_payment_update(doc, method=None):
        """
        Optimized member payment history update triggered by document events

        This handler is designed to be called from Payment Entry and Sales Invoice
        document hooks instead of monkey patching member_utils functions.

        Args:
            doc: The document that triggered the event
            method: The event method name
        """
        try:
            # Determine members that need payment history updates
            member_names = []

            if doc.doctype == "Payment Entry":
                # Get members from payment entry references
                for reference in doc.references:
                    if reference.reference_doctype == "Sales Invoice":
                        # Get customer from sales invoice, then member from customer
                        si = frappe.get_cached_doc("Sales Invoice", reference.reference_name)
                        if si.customer:
                            member = frappe.db.get_value("Member", {"customer": si.customer}, "name")
                            if member and member not in member_names:
                                member_names.append(member)

            elif doc.doctype == "Sales Invoice":
                # Get member directly from customer
                if doc.customer:
                    member = frappe.db.get_value("Member", {"customer": doc.customer}, "name")
                    if member and member not in member_names:
                        member_names.append(member)

            # Use optimized bulk update for affected members
            if member_names:
                validate_member_names(member_names)
                result = OptimizedMemberQueries.bulk_update_payment_history(member_names)

                if not result.get("success"):
                    frappe.log_error(
                        f"Failed to update payment history for members: {member_names}",
                        "Performance Event Handler Error",
                    )

        except Exception as e:
            # Don't let performance optimization errors block document operations
            frappe.log_error(
                f"Performance optimization error in on_member_payment_update: {str(e)}",
                "Performance Event Handler Error",
            )

    @staticmethod
    def on_volunteer_assignment_change(doc, method=None):
        """
        Optimized volunteer assignment loading triggered by document events

        This handler can be called from Volunteer, Team Member, and Board Member
        document hooks to trigger optimized assignment loading.

        Args:
            doc: The document that triggered the event
            method: The event method name
        """
        try:
            volunteer_names = []

            # Determine volunteers that need assignment updates
            if doc.doctype == "Verenigingen Volunteer":
                volunteer_names.append(doc.name)

            elif doc.doctype == "Team Member":
                if doc.volunteer:
                    volunteer_names.append(doc.volunteer)

            elif doc.doctype == "Verenigingen Chapter Board Member":
                if doc.volunteer:
                    volunteer_names.append(doc.volunteer)

            # Preload assignments for affected volunteers
            if volunteer_names:
                validate_member_names(volunteer_names)
                OptimizedVolunteerQueries.get_volunteer_assignments_bulk(volunteer_names)

                frappe.logger().info(f"Preloaded assignments for volunteers: {volunteer_names}")

        except Exception as e:
            # Don't let performance optimization errors block document operations
            frappe.log_error(
                f"Performance optimization error in on_volunteer_assignment_change: {str(e)}",
                "Performance Event Handler Error",
            )

    @staticmethod
    def on_sepa_mandate_change(doc, method=None):
        """
        Optimized SEPA mandate loading triggered by document events

        This handler can be called from SEPA Mandate document hooks to trigger
        optimized mandate loading for related members.

        Args:
            doc: The document that triggered the event
            method: The event method name
        """
        try:
            member_names = []

            if doc.doctype == "SEPA Mandate" and doc.member:
                member_names.append(doc.member)

            # Preload mandates for affected members
            if member_names:
                validate_member_names(member_names)
                OptimizedSEPAQueries.get_active_mandates_for_members(member_names)

                frappe.logger().info(f"Preloaded SEPA mandates for members: {member_names}")

        except Exception as e:
            # Don't let performance optimization errors block document operations
            frappe.log_error(
                f"Performance optimization error in on_sepa_mandate_change: {str(e)}",
                "Performance Event Handler Error",
            )

    @staticmethod
    def bulk_optimize_member_data(member_names: List[str]) -> Dict[str, Any]:
        """
        Comprehensive bulk optimization for multiple members

        This method can be called from scheduled tasks or bulk operations
        to optimize data loading for multiple members at once.

        Args:
            member_names: List of member names to optimize

        Returns:
            Dict with optimization results and statistics
        """
        if not member_names:
            return {"success": True, "message": "No members to optimize"}

        try:
            # Validate input
            validate_member_names(member_names)

            results = {
                "success": True,
                "member_count": len(member_names),
                "operations": {},
                "start_time": now_datetime(),
            }

            # Bulk load member payment data
            payment_result = OptimizedMemberQueries.bulk_update_payment_history(member_names)
            results["operations"]["payment_history"] = payment_result

            # Bulk load financial summaries
            financial_data = OptimizedMemberQueries.get_member_financial_summary(member_names)
            results["operations"]["financial_summary"] = {
                "success": True,
                "loaded_count": len(financial_data),
            }

            # Bulk load SEPA mandates
            mandate_data = OptimizedSEPAQueries.get_active_mandates_for_members(member_names)
            results["operations"]["sepa_mandates"] = {"success": True, "loaded_count": len(mandate_data)}

            # Get volunteer names for members who are volunteers
            volunteer_members = frappe.db.sql(
                """
                SELECT v.name
                FROM `tabVolunteer` v
                INNER JOIN `tabMember` m ON v.member = m.name
                WHERE m.name IN ({})
            """.format(
                    ",".join(["%s"] * len(member_names))
                ),
                member_names,
                as_list=True,
            )

            volunteer_names = [v[0] for v in volunteer_members]

            if volunteer_names:
                # Bulk load volunteer assignments
                assignment_data = OptimizedVolunteerQueries.get_volunteer_assignments_bulk(volunteer_names)
                results["operations"]["volunteer_assignments"] = {
                    "success": True,
                    "loaded_count": len(assignment_data),
                }

            results["end_time"] = now_datetime()
            results["duration_seconds"] = (results["end_time"] - results["start_time"]).total_seconds()

            frappe.logger().info(
                f"Bulk optimization completed for {len(member_names)} members in "
                f"{results['duration_seconds']:.2f} seconds"
            )

            return results

        except Exception as e:
            frappe.log_error(
                f"Bulk optimization failed for members {member_names}: {str(e)}",
                "Performance Bulk Optimization Error",
            )
            return {"success": False, "error": str(e), "member_count": len(member_names)}


# Backwards compatibility helper functions
# These can be used as drop-in replacements but use the new event-driven approach
def optimized_update_member_payment_history(member_name: str):
    """
    Backwards compatible wrapper for single member payment history update

    This function provides compatibility with existing code while using
    the new optimized approach internally.
    """
    if not member_name:
        return

    try:
        validate_member_names([member_name])
        OptimizedMemberQueries.bulk_update_payment_history([member_name])
    except Exception as e:
        frappe.log_error(
            f"Failed to update payment history for member {member_name}: {str(e)}",
            "Optimized Member Payment History Update",
        )


def optimized_update_member_payment_history_from_invoice(invoice_name: str):
    """
    Backwards compatible wrapper for payment history update from invoice

    This function provides compatibility with existing code while using
    the new optimized approach internally.
    """
    if not invoice_name:
        return

    try:
        # Get customer from invoice, then member from customer
        invoice = frappe.get_cached_doc("Sales Invoice", invoice_name)
        if invoice.customer:
            member = frappe.db.get_value("Member", {"customer": invoice.customer}, "name")
            if member:
                validate_member_names([member])
                OptimizedMemberQueries.bulk_update_payment_history([member])
    except Exception as e:
        frappe.log_error(
            f"Failed to update payment history from invoice {invoice_name}: {str(e)}",
            "Optimized Invoice Payment History Update",
        )


# Module-level functions for hooks (required by Frappe hooks validator)
def on_member_payment_update(doc, method=None):
    """Module-level wrapper for PerformanceEventHandlers.on_member_payment_update"""
    return PerformanceEventHandlers.on_member_payment_update(doc, method)


def on_volunteer_assignment_change(doc, method=None):
    """Module-level wrapper for PerformanceEventHandlers.on_volunteer_assignment_change"""
    return PerformanceEventHandlers.on_volunteer_assignment_change(doc, method)


def on_sepa_mandate_change(doc, method=None):
    """Module-level wrapper for PerformanceEventHandlers.on_sepa_mandate_change"""
    return PerformanceEventHandlers.on_sepa_mandate_change(doc, method)


# API endpoints for manual optimization triggers
@frappe.whitelist()
def trigger_member_optimization(member_names):
    """
    API endpoint to manually trigger member optimization

    Args:
        member_names: JSON string containing list of member names

    Returns:
        Dict with optimization results
    """
    try:
        if isinstance(member_names, str):
            member_names = json.loads(member_names)

        if not isinstance(member_names, list):
            raise ValueError("member_names must be a list")

        return PerformanceEventHandlers.bulk_optimize_member_data(member_names)

    except Exception as e:
        frappe.throw(_("Failed to trigger member optimization: {0}").format(str(e)))


@frappe.whitelist()
def get_optimization_status():
    """
    API endpoint to get current optimization system status

    Returns:
        Dict with system status and statistics
    """
    return {
        "optimization_system_active": True,
        "event_handlers_available": True,
        "monkey_patching_disabled": True,
        "available_optimizations": [
            "Member payment history bulk updates",
            "Volunteer assignment bulk loading",
            "SEPA mandate bulk loading",
            "Financial summary bulk loading",
        ],
    }
