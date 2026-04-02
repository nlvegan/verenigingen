"""
Context for the membership application page
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.settings_utils import populate_income_calculator_context


def get_context(context):
    """Get context for membership application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False

    # Get Brand Settings for public-facing content
    brand_settings = frappe.get_single("Brand Settings")
    context.organization_logo = getattr(brand_settings, "logo", None)

    # Public page content from Brand Settings (use getattr for fields that may not exist yet)
    context.page_title = getattr(brand_settings, "application_page_title", None) or _("Become a Member")
    context.page_subtitle = getattr(brand_settings, "application_page_subtitle", None) or _(
        "Join our organization and become part of our community!"
    )
    context.success_title = getattr(brand_settings, "application_success_title", None) or _(
        "Application Submitted Successfully!"
    )
    context.success_message = getattr(brand_settings, "application_success_message", None) or _(
        "Thank you for applying to join our organization. We'll review your application and get back to you soon."
    )

    # Brand colors for gradient (derive light tints from primary/secondary)
    context.primary_color = getattr(brand_settings, "primary_color", None) or "#cf3131"
    context.secondary_color = getattr(brand_settings, "secondary_color", None) or "#01796f"

    # Set page title
    context.title = context.page_title

    # Get verenigingen settings (needed for both member and non-member paths)
    settings = frappe.get_single("Verenigingen Settings")

    # Set step-related context (always needed since template JS references them)
    enable_volunteer = getattr(settings, "enable_volunteer_signup", None)
    context.enable_volunteer_signup = enable_volunteer if enable_volunteer is not None else 1
    context.total_steps = 6 if context.enable_volunteer_signup else 5
    context.step_width = 100 / context.total_steps

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = get_current_user_member_name()
        if existing_member:
            context.already_member = True
            context.member_name = existing_member
            return context
    context.settings = {
        "enable_chapter_management": settings.enable_chapter_management,
        "company_name": frappe.get_value("Company", settings.company, "company_name"),
    }

    # Add income calculator settings
    populate_income_calculator_context(context, settings)

    # Volunteer step label (step count already set above the early-return guard)
    context.volunteer_step_label = getattr(settings, "volunteer_step_label", None) or "Volunteer"

    # Available countries (comma-separated string to list)
    countries_str = getattr(settings, "available_countries", None) or "Netherlands,Belgium,Germany,Other"
    context.available_countries = [c.strip() for c in countries_str.split(",") if c.strip()]

    # Payment methods configuration
    context.payment_methods = get_payment_methods(settings)

    # Volunteer skill categories configuration
    context.skill_categories = get_skill_categories(settings)

    # Check if Dutch installation (for tussenvoegsel field)
    from verenigingen.utils.dutch_name_utils import is_dutch_installation

    context.is_dutch_installation = is_dutch_installation()

    # Get membership types with enhanced contribution options
    from verenigingen.templates.pages.membership_application import get_membership_types_with_contributions

    context.enhanced_membership_types = get_membership_types_with_contributions()

    # Basic context setup
    context.already_member = False

    return context


def get_payment_methods(settings):
    """Get configured payment methods or defaults"""
    payment_methods = []

    if hasattr(settings, "application_payment_methods") and settings.application_payment_methods:
        for pm in settings.application_payment_methods:
            if pm.is_enabled:
                payment_methods.append(
                    {
                        "value": pm.payment_method,
                        "label": pm.label,
                        "order": pm.display_order or 0,
                    }
                )
        # Sort by display order
        payment_methods.sort(key=lambda x: x["order"])
    else:
        # Default payment methods
        payment_methods = [
            {"value": "bank_transfer", "label": _("Bank Transfer"), "order": 0},
            {"value": "sepa_direct_debit", "label": _("SEPA Direct Debit"), "order": 1},
            {"value": "mollie", "label": _("Mollie (Credit Card / iDEAL)"), "order": 2},
        ]

    return payment_methods


def get_skill_categories(settings):
    """Get configured skill categories or defaults"""
    skill_categories = []

    if hasattr(settings, "volunteer_skill_categories") and settings.volunteer_skill_categories:
        for cat in settings.volunteer_skill_categories:
            if cat.is_enabled:
                skills = [s.strip() for s in cat.skills.split(",") if s.strip()]
                skill_categories.append(
                    {
                        "name": cat.category_name,
                        "skills": skills,
                        "order": cat.display_order or 0,
                    }
                )
        # Sort by display order
        skill_categories.sort(key=lambda x: x["order"])
    else:
        # Default skill categories
        skill_categories = [
            {
                "name": _("Technical Skills"),
                "skills": [
                    _("Web Development"),
                    _("Graphic Design"),
                    _("Video Editing"),
                    _("Photography"),
                    _("Social Media Management"),
                    _("Data Analysis"),
                ],
                "order": 0,
            },
            {
                "name": _("Communication Skills"),
                "skills": [
                    _("Writing"),
                    _("Public Speaking"),
                    _("Translation"),
                    _("Teaching/Training"),
                    _("Customer Service"),
                    _("Networking"),
                ],
                "order": 1,
            },
            {
                "name": _("Organizational Skills"),
                "skills": [
                    _("Project Management"),
                    _("Event Planning"),
                    _("Logistics"),
                    _("Research"),
                    _("Administration"),
                    _("Database Management"),
                ],
                "order": 2,
            },
            {
                "name": _("Leadership Skills"),
                "skills": [
                    _("Team Leadership"),
                    _("Mentoring"),
                    _("Board Experience"),
                    _("Strategic Planning"),
                    _("Facilitation"),
                    _("Conflict Resolution"),
                ],
                "order": 3,
            },
            {
                "name": _("Financial Skills"),
                "skills": [
                    _("Accounting"),
                    _("Bookkeeping"),
                    _("Fundraising"),
                    _("Grant Writing"),
                    _("Budget Planning"),
                    _("Financial Analysis"),
                ],
                "order": 4,
            },
        ]

    return skill_categories


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
