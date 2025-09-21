"""
Member Debug Tools - Debugging utilities for Member functionality.

This module contains debugging utilities extracted from member.py to maintain clean
separation between production code and debugging/diagnostic tools.

Functions:
    - debug_button_conditions(): Debug what buttons should appear for a member
    - debug_member_sepa_mandate(): Debug SEPA mandate status and requirements
    - debug_member_address_lookup(): Debug address optimization functionality
    - debug_member_other_addresses(): Debug address duplicate detection
    - debug_member_role_assignments(): Debug member role assignment logic
    - debug_membership_dues_calculation(): Debug dues calculation and schedules
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today


@frappe.whitelist()
def debug_button_conditions(member_name):
    """Debug what buttons should appear for a member.

    Extracted from member.py without modification. Tests various conditions
    that determine which action buttons are shown in the Member form.

    Args:
        member_name (str): Name of member to debug

    Returns:
        dict: Debug information about button visibility conditions
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

        return {
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

    except Exception as e:
        return {
            "error": str(e),
            "member_name": member_name,
            "debug_completed": False,
        }


@frappe.whitelist()
def debug_member_id_assignment(member_name):
    """Debug why member ID assignment is failing.

    Extracted from member.py without modification. Diagnoses issues
    with member ID assignment logic and requirements.

    Args:
        member_name (str): Name of member to debug

    Returns:
        dict: Debug information about member ID assignment
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

        return debug_info

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_member_status(member_name):
    """Debug member status for button investigation.

    Extracted from member.py without modification. Provides comprehensive
    status information for debugging form button visibility.

    Args:
        member_name (str): Name of member to debug

    Returns:
        dict: Status debug information
    """
    try:
        member = frappe.get_doc("Member", member_name)
        return {
            "name": member.name,
            "status": member.status,
            "application_status": getattr(member, "application_status", None),
            "customer": getattr(member, "customer", None),
            "user": getattr(member, "user", None),
            "docstatus": member.docstatus,
            "payment_method": getattr(member, "payment_method", None),
        }
    except Exception as e:
        return {"error": str(e)}
