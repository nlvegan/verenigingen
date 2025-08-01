import frappe
from frappe import _


@frappe.whitelist()
def check_and_fix_member_ownership():
    """Check and fix member ownership issues"""

    # Get Foppe's details
    foppe_email = "foppe@devnull.test"

    # Find member by email
    member = frappe.db.get_value(
        "Member", {"email": foppe_email}, ["name", "user", "email", "first_name", "last_name"], as_dict=True
    )

    if not member:
        return {"error": f"No member found with email {foppe_email}"}

    result = {
        "member_id": member.name,
        "member_name": f"{member.first_name} {member.last_name}",
        "email": member.email,
        "current_user_field": member.user,
        "expected_user_field": foppe_email,
    }

    # Check if user field is correctly set
    if member.user != foppe_email:
        # Fix the user field
        frappe.db.set_value("Member", member.name, "user", foppe_email)
        frappe.db.commit()
        result["fixed"] = True
        result["message"] = f"Fixed: Updated member.user from '{member.user}' to '{foppe_email}'"
    else:
        result["fixed"] = False
        result["message"] = "Member.user field is already correctly set"

    return result
