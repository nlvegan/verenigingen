import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def find_foppe_member():
    """Find Foppe de Haan's member record"""

    # Search by name
    members = frappe.db.get_all(
        "Member",
        filters=[
            ["first_name", "like", "%Foppe%"],
        ],
        fields=["name", "first_name", "last_name", "email", "user", "status"],
        limit=10,
    )

    if not members:
        # Try by last name
        members = frappe.db.get_all(
            "Member",
            filters=[
                ["last_name", "like", "%Haan%"],
            ],
            fields=["name", "first_name", "last_name", "email", "user", "status"],
            limit=10,
        )

    result = {"found": len(members), "members": members}

    # Also check users
    users = frappe.db.get_all(
        "User", filters=[["full_name", "like", "%Foppe%"]], fields=["name", "full_name", "enabled"], limit=10
    )

    result["users"] = users

    return result
