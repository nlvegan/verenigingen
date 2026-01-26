"""
Consolidated cost center utilities for E-Boekhouden integration.

This module provides canonical cost center resolution with well-documented
fallback priorities. Used by migration, payment processing, and transaction handlers.
"""

from typing import List, Optional

import frappe

# Cost center names that indicate general/main cost centers
GENERAL_COST_CENTER_NAMES = ["General", "Main", "General Fund", "Operations"]

# Cost center names to exclude from automatic selection (domain-specific)
EXCLUDED_COST_CENTER_PATTERNS = ["magazine"]


def get_default_cost_center(
    company: str,
    debug_info: Optional[list] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Get the most appropriate default cost center for a company.

    This function implements a sophisticated fallback strategy to find
    the best cost center for general transactions.

    Fallback Priority:
        1. Company's configured default cost center (cost_center field)
        2. Cost center named "Main" (common convention)
        3. Cost center with same name as company
        4. First non-group cost center (excluding Magazine/specific cost centers)
        5. Any non-group cost center as last resort

    Args:
        company: Company name
        debug_info: Optional list to append debug messages
        exclude_patterns: Additional patterns to exclude (case-insensitive).
                         Default excludes "magazine" cost centers.

    Returns:
        Cost center name if found, None if no suitable cost center exists

    Example:
        >>> cc = get_default_cost_center("NVV")
        >>> print(cc)  # "Main - NVV"
    """
    if debug_info is None:
        debug_info = []

    if exclude_patterns is None:
        exclude_patterns = EXCLUDED_COST_CENTER_PATTERNS.copy()
    else:
        exclude_patterns = exclude_patterns + EXCLUDED_COST_CENTER_PATTERNS

    # PRIORITY 1: Company's configured default cost center
    company_default = _get_company_default_cost_center(company)
    if company_default:
        debug_info.append(f"Using company default cost center: {company_default}")
        return company_default

    # PRIORITY 2: Cost center named "Main" (common convention)
    main_cc = frappe.db.get_value(
        "Cost Center",
        {"company": company, "cost_center_name": "Main", "is_group": 0},
        "name",
    )
    if main_cc:
        debug_info.append(f"Using 'Main' cost center: {main_cc}")
        return main_cc

    # PRIORITY 3: Cost center with same name as company
    company_cc = frappe.db.get_value(
        "Cost Center",
        {"company": company, "cost_center_name": company, "is_group": 0},
        "name",
    )
    if company_cc:
        debug_info.append(f"Using company-named cost center: {company_cc}")
        return company_cc

    # PRIORITY 4: First non-group cost center (excluding specific patterns)
    all_cost_centers = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 0},
        fields=["name", "cost_center_name"],
        order_by="creation",
    )

    for cc in all_cost_centers:
        # Skip cost centers with excluded patterns
        cc_name_lower = cc["cost_center_name"].lower()
        if not any(pattern.lower() in cc_name_lower for pattern in exclude_patterns):
            debug_info.append(f"Using first eligible cost center: {cc['name']}")
            return cc["name"]

    # PRIORITY 5: Last resort - any non-group cost center
    fallback_cc = frappe.db.get_value(
        "Cost Center",
        {"company": company, "is_group": 0},
        "name",
    )
    if fallback_cc:
        debug_info.append(f"Using fallback cost center: {fallback_cc}")

    return fallback_cc


def get_general_cost_center(company: str, debug_info: Optional[list] = None) -> Optional[str]:
    """
    Get a general/main cost center for company.

    Looks for cost centers with names indicating general purpose:
    - General
    - Main
    - General Fund
    - Operations

    Args:
        company: Company name
        debug_info: Optional list to append debug messages

    Returns:
        Cost center name if found, None otherwise
    """
    if debug_info is None:
        debug_info = []

    result = frappe.db.get_value(
        "Cost Center",
        {
            "company": company,
            "is_group": 0,
            "cost_center_name": ["in", GENERAL_COST_CENTER_NAMES],
        },
        "name",
    )

    if result:
        debug_info.append(f"Found general cost center: {result}")

    return result


def get_chapter_cost_center(
    company: str,
    chapter_reference: str,
    debug_info: Optional[list] = None,
) -> Optional[str]:
    """
    Get chapter-specific cost center.

    Searches for a cost center containing the chapter reference in its name.

    Args:
        company: Company name
        chapter_reference: Chapter identifier to search for
        debug_info: Optional list to append debug messages

    Returns:
        Cost center name if found, None otherwise
    """
    if debug_info is None:
        debug_info = []

    result = frappe.db.get_value(
        "Cost Center",
        {
            "company": company,
            "cost_center_name": ["like", f"%{chapter_reference}%"],
            "is_group": 0,
        },
        "name",
    )

    if result:
        debug_info.append(f"Found chapter cost center for {chapter_reference}: {result}")

    return result


def get_default_cost_center_or_raise(
    company: str,
    debug_info: Optional[list] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> str:
    """
    Get the default cost center for a company, raising ValidationError if not found.

    Same as get_default_cost_center() but raises instead of returning None.
    Use this when a cost center is required and the operation cannot proceed without one.

    Args:
        company: Company name
        debug_info: Optional list to append debug messages
        exclude_patterns: Additional patterns to exclude (case-insensitive)

    Returns:
        Cost center name (guaranteed non-None)

    Raises:
        frappe.ValidationError if no cost center found for the company

    Example:
        >>> cc = get_default_cost_center_or_raise("NVV")
        >>> print(cc)  # "Main - NVV"
    """
    if debug_info is None:
        debug_info = []

    cost_center = get_default_cost_center(company, debug_info, exclude_patterns)

    if cost_center:
        return cost_center

    # Cost center not found - provide helpful error message
    available_cost_centers = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 0},
        fields=["name", "cost_center_name"],
        limit=10,
    )

    error_msg = f"No cost center found for company '{company}'.\n\n"

    if available_cost_centers:
        error_msg += "Available cost centers:\n"
        for cc in available_cost_centers:
            error_msg += f"  - {cc.name} ({cc.cost_center_name})\n"
    else:
        error_msg += "(No cost centers configured for this company)\n"

    error_msg += (
        f"\nPlease configure a default cost center for company '{company}', "
        f"or create a cost center named 'Main'."
    )

    debug_info.append(f"ERROR: {error_msg}")
    frappe.throw(error_msg, title="Cost Center Configuration Error")


def _get_company_default_cost_center(company: str) -> Optional[str]:
    """Get the company's configured default cost center."""
    try:
        company_doc = frappe.get_doc("Company", company)
        if hasattr(company_doc, "cost_center") and company_doc.cost_center:
            return company_doc.cost_center
    except frappe.DoesNotExistError:
        pass
    return None
