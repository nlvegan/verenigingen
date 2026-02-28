"""Auto-enable desk UI settings for users with volunteer-level+ role profiles.

When a user is assigned a role profile at or above Volunteer level, all desk
UI settings (search bar, notifications, sidebar, etc.) should be enabled so
they can use the full desk interface including the awesomebar.
"""

import frappe

# Role profiles that get full desk settings (Volunteer level and above)
DESK_ENABLED_PROFILES = {
    "Verenigingen Volunteer",
    "Verenigingen Team Leader",
    "Verenigingen Chapter Board Member",
    "Verenigingen National Board Member",
    "Verenigingen Staff",
    "Verenigingen Treasurer",
    "Verenigingen Communications Officer",
    "Verenigingen Event Coordinator",
    "Verenigingen Auditor",
    "Verenigingen Administrator",
    "Verenigingen System Administrator",
}

DESK_PROPERTIES = (
    "search_bar",
    "notifications",
    "list_sidebar",
    "bulk_actions",
    "view_switcher",
    "form_sidebar",
    "form_navigation_buttons",
    "timeline",
    "dashboard",
)


def ensure_desk_settings_for_role_profile(doc, method=None):
    """Enable all desk settings when user gets a volunteer-level+ role profile.

    Called as a User doc_event handler (on_update / after_insert).
    """
    # Only act when role_profile_name changes (or on insert)
    if method == "on_update" and not doc.has_value_changed("role_profile_name"):
        return

    if doc.role_profile_name not in DESK_ENABLED_PROFILES:
        return

    # Check if any setting is currently disabled
    needs_update = any(not doc.get(prop) for prop in DESK_PROPERTIES)
    if not needs_update:
        return

    for prop in DESK_PROPERTIES:
        doc.db_set(prop, 1, update_modified=False)
