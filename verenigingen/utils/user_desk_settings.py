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


def _held_profiles(user_doc):
    """Every role profile on the user: the child table (v16) plus the deprecated first-profile mirror."""
    held = {row.role_profile for row in (user_doc.get("role_profiles") or []) if row.role_profile}
    if user_doc.get("role_profile_name"):
        held.add(user_doc.role_profile_name)
    return held


def ensure_desk_settings_for_role_profile(doc, method=None):
    """Enable all desk settings when user gets a volunteer-level+ role profile.

    Called as a User doc_event handler (on_update / after_insert).
    """
    # Only act when a desk-enabled profile is newly held (or on insert). role_profile_name
    # mirrors only the FIRST profile, so read the whole set (#2432).
    gained = _held_profiles(doc) & DESK_ENABLED_PROFILES
    if method == "on_update":
        before = doc.get_doc_before_save()
        if before:
            gained -= _held_profiles(before)
    if not gained:
        return

    # Check if any setting is currently disabled
    needs_update = any(not doc.get(prop) for prop in DESK_PROPERTIES)
    if not needs_update:
        return

    for prop in DESK_PROPERTIES:
        doc.db_set(prop, 1, update_modified=False)
