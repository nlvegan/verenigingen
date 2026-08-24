"""Whitelisted helpers that outlive their page.

The /membership_application template was removed: it posted to
`submit_enhanced_application`, which has never existed in this module — the
template was written pointing at the wrong one and the module it meant was later
deleted. The page could not submit an application on any day of its life.

This module survives the template because `get_dues_schedules_for_membership_type`
below is `allow_guest` and is called by the LIVE form,
templates/pages/apply_for_membership.html, by dotted path. Moving these helpers to
`api/` would change that path, so they stay here until a change that updates the
caller too. `get_context` was deleted with the template.
"""

import frappe

from verenigingen.services.member.application.membership_application_service import (
    get_membership_application_service,
)
from verenigingen.utils.security.api_security_framework import public_api


@frappe.whitelist()
@public_api
def get_membership_type_details(membership_type_name: str):
    """Get detailed contribution options for a specific membership type."""
    if not membership_type_name:
        return {"error": "Membership type name is required"}

    try:
        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        info = get_membership_type_fee_info(membership_type_name)
        if not info.get("success"):
            return {"error": info.get("error", "Unknown error")}

        mt_doc = frappe.get_doc("Membership Type", membership_type_name)
        return {
            "success": True,
            "membership_type": {
                "name": info["membership_type"],
                "membership_type_name": info["membership_type_name"],
                "description": info["description"],
                "amount": info["amount"],
                "billing_frequency": info["billing_frequency"],
                "contribution_options": (
                    mt_doc.get_contribution_options() if hasattr(mt_doc, "get_contribution_options") else {}
                ),
            },
        }
    except frappe.DoesNotExistError:
        return {"error": f"Membership type '{membership_type_name}' not found"}
    except Exception as e:
        frappe.log_error(f"Error getting membership type details: {str(e)}")
        return {"error": "An error occurred while retrieving membership type details"}


@frappe.whitelist(allow_guest=True)
@public_api
def get_dues_schedules_for_membership_type(membership_type_name: str):
    """Get all dues schedule templates for a specific membership type.

    This is used in the two-phase membership selection where:
    1. User first selects a membership type
    2. Then sees available payment plans (dues schedules) for that type

    Args:
        membership_type_name: The name of the membership type

    Returns:
        dict with success status and list of dues schedules
    """
    # Input validation for guest-accessible endpoint
    if not membership_type_name:
        return {"success": False, "error": "Membership type name is required"}

    # Sanitize input - membership type names should be reasonable length and format
    membership_type_name = str(membership_type_name).strip()
    if len(membership_type_name) > 140:
        return {"success": False, "error": "Invalid membership type name"}

    # Verify the membership type actually exists before proceeding
    if not frappe.db.exists("Membership Type", membership_type_name):
        return {"success": False, "error": f"Membership type '{membership_type_name}' not found"}

    service = get_membership_application_service()
    return service.get_dues_schedules(membership_type_name)


@frappe.whitelist()
@public_api
def validate_contribution_amount(
    membership_type_name: str, amount, contribution_mode=None, selected_tier=None, base_multiplier=None
):
    """Validate a contribution amount against membership type constraints"""
    if not membership_type_name or not amount:
        return {"valid": False, "error": "Membership type and amount are required"}

    service = get_membership_application_service()
    return service.validate_contribution(
        membership_type_name,
        amount,
        contribution_mode=contribution_mode,
        selected_tier=selected_tier,
        base_multiplier=base_multiplier,
    )
