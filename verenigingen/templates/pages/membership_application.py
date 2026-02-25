"""
Enhanced context for membership application page with flexible contribution system
"""

import frappe
from frappe import _

from verenigingen.services.member.application.membership_application_service import (
    get_membership_application_service,
)
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.security.api_security_framework import public_api
from verenigingen.utils.settings_utils import populate_income_calculator_context


def get_context(context):
    """Get context for enhanced membership application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Apply for Membership")

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = get_current_user_member_name()
        if existing_member:
            context.already_member = True
            context.member_name = existing_member
            return context

    # Get verenigingen settings
    settings = frappe.get_single("Verenigingen Settings")
    context.settings = {
        "enable_chapter_management": settings.enable_chapter_management,
        "company_name": frappe.get_value("Company", settings.company, "company_name"),
    }

    # Get organization logo from Brand Settings
    from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_organization_logo

    context.organization_logo = get_organization_logo()

    # Get all active membership types with contribution options
    service = get_membership_application_service()
    context.membership_types = service.get_membership_types_with_contributions()

    # Add income calculator settings (global defaults)
    populate_income_calculator_context(context, settings)

    # Basic context setup
    context.already_member = False

    return context


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


@frappe.whitelist()
@public_api
def calculate_suggested_contribution(
    membership_type_name: str, monthly_income, payment_interval: str = "monthly"
):
    """Calculate suggested contribution based on income"""
    if not membership_type_name or not monthly_income:
        return {"error": "Membership type and monthly income are required"}

    service = get_membership_application_service()
    return service.calculate_income_contribution(
        membership_type_name,
        monthly_income,
        interval=payment_interval,
    )


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
