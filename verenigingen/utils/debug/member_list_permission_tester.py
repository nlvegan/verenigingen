import frappe
from frappe import _


@frappe.whitelist()
def test_member_list_permissions():
    """Test what members Foppe can see in a list view"""

    foppe_email = "foppe@veganisme.org"

    # Clear cache first
    frappe.clear_cache(user=foppe_email)

    # Set user to Foppe
    frappe.set_user(foppe_email)

    # Try to get list of members
    try:
        # This should respect permission query
        members = frappe.get_list("Member", fields=["name", "first_name", "last_name", "owner"], limit=10)

        result = {"user": frappe.session.user, "total_members_visible": len(members), "members": []}

        for member in members:
            result["members"].append(
                {
                    "name": member.name,
                    "full_name": f"{member.first_name} {member.last_name}",
                    "owner": member.owner,
                    "is_own_record": member.owner == foppe_email,
                }
            )

        return result

    except Exception as e:
        return {"user": frappe.session.user, "error": str(e)}
