import frappe
from frappe import _


@frappe.whitelist()
def check_foppe_roles_and_permissions():
    """Check Foppe's roles and permissions"""

    foppe_email = "foppe@veganisme.org"

    # Get user roles
    user = frappe.get_doc("User", foppe_email)
    roles = [r.role for r in user.roles]

    result = {"user": foppe_email, "roles": roles, "member_permissions": []}

    # Check Member doctype permissions for these roles
    perms = frappe.get_all(
        "DocPerm",
        filters={"parent": "Member", "parenttype": "DocType", "role": ["in", roles]},
        fields=["role", "permlevel", "read", "write", "if_owner"],
        order_by="role, permlevel",
    )

    result["member_permissions"] = perms

    # Check if there's an if_owner permission
    has_owner_perm = any(p.get("if_owner") for p in perms)
    result["has_owner_permission"] = has_owner_perm

    # Check member record
    member = frappe.db.get_value("Member", {"user": foppe_email}, ["name", "user"], as_dict=True)

    if member:
        result["member_id"] = member.name
        result["member_linked_to_user"] = member.user == foppe_email

    return result
