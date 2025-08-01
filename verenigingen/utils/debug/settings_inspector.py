import frappe


@frappe.whitelist()
def check_creation_user_setting():
    """Check the current creation user setting"""
    settings = frappe.get_single("Verenigingen Settings")

    result = {"creation_user": settings.creation_user, "user_exists": False, "user_details": None}

    if settings.creation_user:
        result["user_exists"] = frappe.db.exists("User", settings.creation_user)

        if result["user_exists"]:
            user = frappe.get_doc("User", settings.creation_user)
            result["user_details"] = {
                "full_name": user.full_name,
                "roles": [r.role for r in user.roles],
                "enabled": user.enabled,
            }

    return result
