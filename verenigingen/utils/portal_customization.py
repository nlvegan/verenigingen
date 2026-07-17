"""Portal context customization for member-facing website pages."""

import frappe


def add_portal_user_roles(context):
    """Expose the current user's roles to portal templates.

    Registered as an update_website_context hook, so this runs on every website page
    render. templates/includes/web_sidebar.html, templates/includes/portal_nav.html and
    templates/pages/chapter_dashboard.html read context["user_roles"] to decide which
    role-gated navigation entries to render. The key is left unset for Guest; those
    templates fall back via `user_roles or []`.
    """
    if frappe.session.user != "Guest":
        context["user_roles"] = frappe.get_roles(frappe.session.user)

    return context
