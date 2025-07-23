"""
Context for the membership application page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for membership application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Apply for Membership")

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = frappe.db.get_value("Member", {"email": frappe.session.user})
        if existing_member:
            # Redirect to member profile or show message
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

    # Add income calculator settings
    context.enable_income_calculator = getattr(settings, "enable_income_calculator", 0)
    context.income_percentage_rate = getattr(settings, "income_percentage_rate", 0.5)
    context.calculator_description = getattr(
        settings,
        "calculator_description",
        "Our suggested contribution is 0.5% of your monthly net income. This helps ensure fair and equitable contributions based on your financial capacity.",
    )

    # Get membership types with enhanced contribution options
    try:
        from verenigingen.api.membership_application import get_membership_types_for_application

        context.enhanced_membership_types = get_membership_types_for_application()
    except Exception as e:
        frappe.log_error(f"Error loading enhanced membership types: {str(e)}")
        context.enhanced_membership_types = []

    # Basic context setup
    context.already_member = False

    return context


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
