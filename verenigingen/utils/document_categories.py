# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Utility functions for managing board document categories
"""

import frappe


@frappe.whitelist()
def get_document_category_options():
    """
    Get all available document categories for select fields.
    Returns newline-separated options for Frappe Select fields.
    """
    # Default categories
    options = ["Policy", "Meeting Minutes", "Financial Report", "Other"]

    # Add custom categories from settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and hasattr(settings, "board_document_categories"):
            for custom_cat in settings.board_document_categories:
                if custom_cat.category_name and custom_cat.category_name not in options:
                    options.append(custom_cat.category_name)
    except Exception as e:
        frappe.log_error(f"Error loading custom document categories: {str(e)}")

    return "\n".join(options)


def get_category_icon(category_name: str) -> str:
    """Get the icon for a specific category"""
    # Default icons
    default_icons = {"Policy": "📋", "Meeting Minutes": "📝", "Financial Report": "💰", "Other": "📎"}

    # Check default first
    if category_name in default_icons:
        return default_icons[category_name]

    # Check custom categories
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and hasattr(settings, "board_document_categories"):
            for custom_cat in settings.board_document_categories:
                if custom_cat.category_name == category_name:
                    return custom_cat.category_icon or "📎"
    except Exception as e:
        frappe.log_error(f"Error getting category icon: {str(e)}")

    return "📎"  # Default fallback
