"""
Volunteer Role Profile Hooks

Hooks for Volunteer DocType events that trigger role profile recalculation.

Author: Verenigingen Development Team
Last Updated: 2025-10-09
"""

import frappe


def on_volunteer_status_change(doc, method):
    """
    Hook called when Volunteer is updated.

    Triggers role profile recalculation when volunteer status changes.

    Args:
        doc: Volunteer document
        method: Hook method name
    """
    # Only recalculate if status or other role-affecting fields changed
    if doc.has_value_changed("status"):
        # Get user from member
        if doc.member:
            member_doc = frappe.get_doc("Member", doc.member)
            if member_doc.user:
                from verenigingen.services.member.account.user_role_profile_calculator import (
                    auto_sync_on_role_change,
                )

                auto_sync_on_role_change(member_doc.user)
