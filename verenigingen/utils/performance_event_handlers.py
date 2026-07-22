#!/usr/bin/env python3
"""
Performance Optimization Event Handlers
=======================================

This module provides event-driven performance optimization handlers that replace
the dangerous monkey patching approach with safe, Frappe-native event hooks.

Instead of replacing existing methods, this module provides handlers that can be
called from document event hooks to trigger optimized operations when appropriate.
"""

import frappe

from verenigingen.utils.optimized_queries import (
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    validate_member_names,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    utility_api,
)


class PerformanceEventHandlers:
    """
    Event handlers for performance optimization using proper Frappe patterns

    This class provides event handlers that can be called from document hooks
    instead of monkey patching existing methods.
    """

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


# Module-level functions for hooks (required by Frappe hooks validator)
def on_volunteer_assignment_change(doc, method=None):
    """Module-level wrapper for PerformanceEventHandlers.on_volunteer_assignment_change"""
    return PerformanceEventHandlers.on_volunteer_assignment_change(doc, method)


def on_sepa_mandate_change(doc, method=None):
    """Module-level wrapper for PerformanceEventHandlers.on_sepa_mandate_change"""
    return PerformanceEventHandlers.on_sepa_mandate_change(doc, method)


@frappe.whitelist()
@utility_api(operation_type=OperationType.UTILITY)
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
            "Volunteer assignment bulk loading",
            "SEPA mandate bulk loading",
        ],
    }
