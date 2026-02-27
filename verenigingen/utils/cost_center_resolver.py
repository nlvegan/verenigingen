"""
Cost Center Resolution Utilities

Handles cost center resolution for volunteer expenses based on organization type.
Extracted from volunteer expense templates to avoid circular imports and provide
a reusable utility for cost center lookups.

Author: Verenigingen Development Team
License: MIT
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.services.volunteer.volunteer_expense_setup import (
    create_default_cost_center,
    get_fallback_cost_center,
)


def get_organization_cost_center(
    organization_type: str,
    chapter: Optional[str] = None,
    team: Optional[str] = None,
) -> str:
    """Get cost center based on organization with enhanced fallback logic.

    Resolves cost center in priority order:
    1. Direct organization cost center (chapter/team)
    2. Team's parent chapter cost center
    3. National cost center from settings
    4. Company default cost center
    5. Auto-created default cost center

    Args:
        organization_type: 'Chapter', 'Team', or 'National'
        chapter: Chapter name (required if organization_type='Chapter')
        team: Team name (required if organization_type='Team')

    Returns:
        Cost center name

    Raises:
        frappe.ValidationError: If no cost center can be determined and
            company is not configured
    """
    try:
        cost_center = None

        if organization_type == "Chapter" and chapter:
            chapter_doc = frappe.get_doc("Chapter", chapter)
            cost_center = getattr(chapter_doc, "cost_center", None)

        elif organization_type == "Team" and team:
            team_doc = frappe.get_doc("Team", team)
            cost_center = getattr(team_doc, "cost_center", None)

            # If team doesn't have cost center, try to get from chapter
            if not cost_center and hasattr(team_doc, "chapter") and team_doc.chapter:
                try:
                    chapter_doc = frappe.get_doc("Chapter", team_doc.chapter)
                    cost_center = getattr(chapter_doc, "cost_center", None)
                    if cost_center:
                        frappe.logger().debug(
                            f"Using chapter cost center for team {team_doc.name}: {cost_center}"
                        )
                except Exception as e:
                    frappe.logger().warning(f"Error getting chapter cost center: {str(e)}")

        elif organization_type == "National":
            # Get national cost center from settings
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "national_cost_center") and settings.national_cost_center:
                cost_center = settings.national_cost_center

        # Enhanced fallback logic
        if not cost_center:
            frappe.logger().warning(f"No direct cost center found for organization type: {organization_type}")
            cost_center = _get_fallback_cost_center()

        return cost_center

    except Exception as e:
        frappe.log_error(f"Error getting cost center: {str(e)}", "Cost Center Error")
        # Return a default cost center as last resort
        return get_fallback_cost_center()


def _get_fallback_cost_center() -> str:
    """Get fallback cost center from company settings.

    Returns:
        Cost center name

    Raises:
        frappe.ValidationError: If company not configured
    """
    settings = frappe.get_single("Verenigingen Settings")
    default_company = settings.company

    if not default_company:
        frappe.throw(_("Company not configured in Verenigingen Settings"))

    # Get main cost center for the company
    main_cost_centers = frappe.get_all(
        "Cost Center",
        filters={"company": default_company, "is_group": 0},
        fields=["name"],
        limit=1,
    )

    if main_cost_centers:
        cost_center = main_cost_centers[0].name
        frappe.logger().debug(f"Using company fallback cost center: {cost_center}")
        return cost_center

    # Create a default cost center if none exists
    return create_default_cost_center(default_company)


def get_organization_cost_center_from_dict(expense_data: dict) -> str:
    """Wrapper for dict-based expense data (backward compatibility).

    Args:
        expense_data: Dictionary with organization_type, chapter, team keys

    Returns:
        Cost center name
    """
    return get_organization_cost_center(
        organization_type=expense_data.get("organization_type", ""),
        chapter=expense_data.get("chapter"),
        team=expense_data.get("team"),
    )
