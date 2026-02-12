# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Utility functions for managing board document categories.

Single source of truth: reads entirely from the board_document_categories
child table in Verenigingen Settings. Default categories are seeded there
during installation (see setup/__init__.py).
"""

import frappe

# Fallback defaults used only when Settings child table is empty
# (e.g. fresh install before after_install runs)
_FALLBACK_CATEGORIES = {
    "Policy": "📋",
    "Meeting Minutes": "📝",
    "Financial Report": "💰",
    "Other": "📎",
}


def _get_categories_from_settings() -> dict[str, str]:
    """Read categories from Verenigingen Settings child table.

    Returns dict of {category_name: icon}. Falls back to hardcoded
    defaults only if the child table is completely empty.
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and getattr(settings, "board_document_categories", None):
            categories = {}
            for row in settings.board_document_categories:
                if row.category_name:
                    categories[row.category_name] = row.category_icon or "📎"
            if categories:
                return categories
    except Exception as e:
        frappe.log_error(f"Error loading document categories from settings: {str(e)}")

    return dict(_FALLBACK_CATEGORIES)


@frappe.whitelist()
def get_document_category_options():
    """
    Get all available document categories for select fields.
    Returns newline-separated options for Frappe Select fields.
    """
    categories = _get_categories_from_settings()
    return "\n".join(categories.keys())


def get_category_icons() -> dict[str, str]:
    """Get dict of {category_name: icon} for all categories."""
    return _get_categories_from_settings()


def get_category_icon(category_name: str) -> str:
    """Get the icon for a specific category."""
    categories = _get_categories_from_settings()
    return categories.get(category_name, "📎")


def seed_default_categories():
    """Ensure default categories exist in Settings. Safe to run anytime."""
    from verenigingen.setup import _seed_default_document_categories

    settings = frappe.get_single("Verenigingen Settings")
    _seed_default_document_categories(settings)


# DocType fields whose `options` column should mirror the Settings child table.
# Format: (doctype, fieldname, leading_blank) — leading_blank adds "\n" prefix
# so the Select shows an empty first option (needed for optional fields).
_SYNCED_FIELDS = [
    ("Organization Document", "document_type", False),
    ("Chapter Board Document", "document_type", False),
    ("MijnRood Document Folder Mapping", "document_type", True),
]


def sync_category_options_to_doctypes():
    """Write current categories into tabDocField.options for all synced fields.

    This makes categories available everywhere Frappe reads field meta:
    forms, list views, bulk edit, standard filters, and Report Builder.
    Call this whenever Verenigingen Settings is saved.
    """
    options_str = get_document_category_options()

    for doctype, fieldname, leading_blank in _SYNCED_FIELDS:
        value = ("\n" + options_str) if leading_blank else options_str
        frappe.db.set_value(
            "DocField",
            {"parent": doctype, "fieldname": fieldname},
            "options",
            value,
            update_modified=False,
        )

    frappe.clear_cache()
    frappe.db.commit()
