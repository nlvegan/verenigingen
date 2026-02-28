"""Enable desk UI settings for existing users with volunteer-level+ role profiles.

Users with qualifying role profiles (Volunteer and above) need all desk settings
enabled so they can use the awesomebar and other desk features. This patch
back-fills any users whose settings were previously left disabled.
"""

import frappe

from verenigingen.utils.user_desk_settings import DESK_ENABLED_PROFILES, DESK_PROPERTIES


def execute():
    """Enable desk settings for all users with volunteer+ role profiles."""
    users = frappe.get_all(
        "User",
        filters={"role_profile_name": ["in", list(DESK_ENABLED_PROFILES)]},
        fields=["name", "role_profile_name"] + list(DESK_PROPERTIES),
    )

    updated = 0
    for user in users:
        needs_update = any(not user.get(prop) for prop in DESK_PROPERTIES)
        if not needs_update:
            continue

        for prop in DESK_PROPERTIES:
            if not user.get(prop):
                frappe.db.set_value("User", user.name, prop, 1, update_modified=False)
        updated += 1

    if updated:
        frappe.db.commit()

    frappe.logger().info(
        "enable_desk_settings_for_volunteers: updated %d of %d qualifying users",
        updated,
        len(users),
    )
