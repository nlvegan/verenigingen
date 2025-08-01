import frappe
from frappe import _


@frappe.whitelist()
def clear_permission_cache_and_test():
    """Clear permission cache and test Foppe's access"""

    # Clear all permission caches
    frappe.clear_cache()
    frappe.cache().delete_value("has_permission:Member")

    # Also clear user-specific cache
    foppe_email = "foppe@veganisme.org"
    frappe.clear_cache(user=foppe_email)

    # Now test permissions again
    frappe.set_user(foppe_email)

    results = {"cache_cleared": True, "current_user": frappe.session.user, "tests": []}

    # Test own record
    own_member = frappe.db.get_value("Member", {"user": foppe_email}, "name")
    if own_member:
        try:
            frappe.get_doc("Member", own_member)
            results["tests"].append({"member": own_member, "type": "own_record", "can_access": True})
        except frappe.PermissionError as e:
            results["tests"].append(
                {"member": own_member, "type": "own_record", "can_access": False, "error": str(e)}
            )

    # Test other records
    other_members = frappe.db.get_list("Member", filters={"user": ["!=", foppe_email]}, limit=3)

    for member in other_members:
        try:
            frappe.get_doc("Member", member.name)
            results["tests"].append(
                {"member": member.name, "type": "other_record", "can_access": True, "should_access": False}
            )
        except frappe.PermissionError:
            results["tests"].append(
                {"member": member.name, "type": "other_record", "can_access": False, "should_access": False}
            )

    return results
