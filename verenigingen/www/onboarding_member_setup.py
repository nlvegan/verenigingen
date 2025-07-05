"""
Member Setup Onboarding Page
"""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
    """Provide context for member setup onboarding page"""
    context.no_cache = 1
    context.show_sidebar = False

    # Check permissions
    if not frappe.has_permission("Member", "create"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Get member count
    context.member_count = frappe.db.count("Member")

    # Get test members
    test_members = frappe.get_all(
        "Member", filters={"email": ["like", "%@email.nl"]}, fields=["name", "full_name", "status"], limit=10
    )

    context.test_members = test_members
    context.test_members_count = len(test_members)
    context.has_test_members = len(test_members) > 0

    # Get membership types
    membership_types = frappe.get_all("Membership Type", fields=["name", "membership_type_name"], limit=5)

    context.membership_types = membership_types
    context.membership_types_count = len(membership_types)
    context.has_membership_types = len(membership_types) > 0

    return context


@frappe.whitelist()
def generate_test_members_from_onboarding():
    """Generate test members from the onboarding page"""
    # Use the new method that properly creates Pending members
    from verenigingen.utils.create_test_pending_members import create_test_pending_members

    result = create_test_pending_members()

    # Mark onboarding step as complete if successful
    if result.get("success") and result.get("created", 0) > 0:
        try:
            frappe.db.set_value("Onboarding Step", "Verenigingen-Create-Member", "is_complete", 1)
            frappe.db.commit()
        except Exception:
            pass  # Ignore if onboarding step doesn't exist

    return result


@frappe.whitelist()
def cleanup_test_data():
    """Clean up test members"""
    # Import the cleanup function from templates/pages
    from verenigingen.templates.pages.onboarding_member_setup import cleanup_test_data as cleanup_impl

    return cleanup_impl()
