import frappe


@frappe.whitelist()
def check_user_details(email):
    """Check user details and roles"""

    try:
        # Check if user exists
        if not frappe.db.exists("User", email):
            return {"error": f"User {email} does not exist"}

        # Get user details
        user_doc = frappe.get_doc("User", email)
        user_roles = frappe.get_roles(email)

        # Check if user is linked to a Member record
        member_record = frappe.db.get_value("Member", {"user": email}, ["name", "full_name"], as_dict=True)

        # Check how many membership dues schedules exist in total
        total_schedules = frappe.db.count("Membership Dues Schedule")
        template_schedules = frappe.db.count("Membership Dues Schedule", {"is_template": 1})
        non_template_schedules = total_schedules - template_schedules

        return {
            "user_email": email,
            "user_enabled": user_doc.enabled,
            "user_roles": user_roles,
            "member_record": member_record,
            "total_schedules": total_schedules,
            "template_schedules": template_schedules,
            "non_template_schedules": non_template_schedules,
        }

    except Exception as e:
        return {"error": str(e)}
