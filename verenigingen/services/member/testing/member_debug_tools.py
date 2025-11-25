"""
Member Debug Tools - Debugging utilities for Member functionality.

This module contains debugging utilities extracted from member.py to maintain clean
separation between production code and debugging/diagnostic tools.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All API methods return OperationResult[Dict] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- debug_button_conditions: Returns OperationResult[Dict] (button visibility debug info)
- debug_member_id_assignment: Returns OperationResult[Dict] (member ID assignment debug info)
- debug_member_status: Returns OperationResult[Dict] (member status debug info)

Migration Status: ✅ COMPLETE (2025-11-25)
- All API methods migrated from dict-based to OperationResult pattern
- Consistent error handling with comprehensive metadata
- Type-safe error handling preserved across all debug utilities

See: docs/patterns/OPERATION_RESULT_PATTERN.md

Functions:
    - debug_button_conditions(): Debug what buttons should appear for a member
    - debug_member_sepa_mandate(): Debug SEPA mandate status and requirements
    - debug_member_address_lookup(): Debug address optimization functionality
    - debug_member_other_addresses(): Debug address duplicate detection
    - debug_member_role_assignments(): Debug member role assignment logic
    - debug_membership_dues_calculation(): Debug dues calculation and schedules
"""

from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.operation_result import OperationResult


@frappe.whitelist()
def debug_button_conditions(member_name) -> OperationResult[Dict[str, Any]]:
    """Debug what buttons should appear for a member.

    Extracted from member.py without modification. Tests various conditions
    that determine which action buttons are shown in the Member form.

    Args:
        member_name (str): Name of member to debug

    Returns:
        OperationResult[Dict]: Debug information about button visibility conditions
    """
    try:
        member = frappe.get_doc("Member", member_name)

        # Check various conditions
        has_customer = bool(getattr(member, "customer", None))
        has_user = bool(getattr(member, "user", None))
        has_email = bool(getattr(member, "email", None))

        # Check for volunteer
        has_volunteer = bool(frappe.db.exists("Volunteer", {"member": member_name}))

        # Check for active membership
        has_active_membership = bool(
            frappe.db.exists(
                "Membership",
                {"member": member_name, "status": ["in", ["Active", "Pending"]], "docstatus": ["!=", 2]},
            )
        )

        # Check for donor
        has_donor = bool(frappe.db.exists("Donor", {"linked_member": member_name}))

        debug_data = {
            "member_name": member_name,
            "status": member.status,
            "docstatus": member.docstatus,
            "has_customer": has_customer,
            "has_user": has_user,
            "has_email": has_email,
            "has_volunteer": has_volunteer,
            "has_active_membership": has_active_membership,
            "has_donor": has_donor,
            "debug_completed": True,
        }

        return OperationResult.ok(debug_data, message=f"Button conditions debug complete for {member_name}")

    except frappe.DoesNotExistError:
        return OperationResult.fail(
            _("Member not found"),
            errors=[f"Member {member_name} does not exist"],
            error=f"Member not found: {member_name}",
            member_name=member_name,
            debug_completed=False,
            context={"operation": "button_conditions_debug", "params": {"member_name": member_name}},
        )
    except Exception as e:
        frappe.log_error(f"Error in debug_button_conditions: {str(e)}", "Member Debug Tools Error")
        return OperationResult.fail(
            _("An error occurred while debugging button conditions. Please contact support."),
            errors=[str(e)],
            error=str(e),
            member_name=member_name,
            debug_completed=False,
            context={"operation": "button_conditions_debug", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
def debug_member_id_assignment(member_name) -> OperationResult[Dict[str, Any]]:
    """Debug why member ID assignment is failing.

    Extracted from member.py without modification. Diagnoses issues
    with member ID assignment logic and requirements.

    Args:
        member_name (str): Name of member to debug

    Returns:
        OperationResult[Dict]: Debug information about member ID assignment
    """
    try:
        member = frappe.get_doc("Member", member_name)

        debug_info = {
            "member_name": member.name,
            "current_member_id": getattr(member, "member_id", None),
            "has_member_id": bool(getattr(member, "member_id", None)),
            "is_application_member": member.is_application_member(),
            "application_id": getattr(member, "application_id", None),
            "application_status": getattr(member, "application_status", None),
            "status": getattr(member, "status", None),
            "should_have_member_id": member.should_have_member_id(),
            "can_assign_id": not member.member_id and member.should_have_member_id(),
        }

        return OperationResult.ok(
            debug_info, message=f"Member ID assignment debug complete for {member_name}"
        )

    except frappe.DoesNotExistError:
        return OperationResult.fail(
            _("Member not found"),
            errors=[f"Member {member_name} does not exist"],
            error=f"Member not found: {member_name}",
            context={"operation": "member_id_debug", "params": {"member_name": member_name}},
        )
    except AttributeError as e:
        # Handle cases where member methods don't exist
        frappe.log_error(
            f"AttributeError in debug_member_id_assignment: {str(e)}", "Member Debug Tools Error"
        )
        return OperationResult.fail(
            _("Member object missing required methods"),
            errors=[str(e)],
            error=f"AttributeError: {str(e)}",
            context={"operation": "member_id_debug", "params": {"member_name": member_name}},
        )
    except Exception as e:
        frappe.log_error(f"Error in debug_member_id_assignment: {str(e)}", "Member Debug Tools Error")
        return OperationResult.fail(
            _("An error occurred while debugging member ID assignment. Please contact support."),
            errors=[str(e)],
            error=str(e),
            context={"operation": "member_id_debug", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
def debug_member_status(member_name) -> OperationResult[Dict[str, Any]]:
    """Debug member status for button investigation.

    Extracted from member.py without modification. Provides comprehensive
    status information for debugging form button visibility.

    Args:
        member_name (str): Name of member to debug

    Returns:
        OperationResult[Dict]: Status debug information
    """
    try:
        member = frappe.get_doc("Member", member_name)

        status_data = {
            "name": member.name,
            "status": member.status,
            "application_status": getattr(member, "application_status", None),
            "customer": getattr(member, "customer", None),
            "user": getattr(member, "user", None),
            "docstatus": member.docstatus,
            "payment_method": getattr(member, "payment_method", None),
        }

        return OperationResult.ok(status_data, message=f"Member status debug complete for {member_name}")

    except frappe.DoesNotExistError:
        return OperationResult.fail(
            _("Member not found"),
            errors=[f"Member {member_name} does not exist"],
            error=f"Member not found: {member_name}",
            context={"operation": "member_status_debug", "params": {"member_name": member_name}},
        )
    except Exception as e:
        frappe.log_error(f"Error in debug_member_status: {str(e)}", "Member Debug Tools Error")
        return OperationResult.fail(
            _("An error occurred while debugging member status. Please contact support."),
            errors=[str(e)],
            error=str(e),
            context={"operation": "member_status_debug", "params": {"member_name": member_name}},
        )
