"""
Check actual role names in the system
"""

import frappe


@frappe.whitelist()
def get_verenigingen_roles():
    """Get all roles related to verenigingen"""
    try:
        # Get all roles that contain "verenigingen" or related terms
        all_roles = frappe.get_all("Role", fields=["name"], order_by="name")

        verenigingen_roles = []
        for role in all_roles:
            role_name = role.name.lower()
            if any(
                term in role_name for term in ["verenigingen", "membership", "member", "manager", "admin"]
            ):
                verenigingen_roles.append(role.name)

        # Also get system roles that might be used
        system_roles = []
        for role in all_roles:
            role_name = role.name.lower()
            if any(term in role_name for term in ["system", "administrator"]):
                system_roles.append(role.name)

        return {
            "all_roles_count": len(all_roles),
            "verenigingen_related_roles": verenigingen_roles,
            "system_roles": system_roles,
            "roles_used_in_validation": [
                "System Manager",
                "Verenigingen Administrator",
                "Verenigingen Manager",
            ],
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def validate_role_names_in_code():
    """Validate that role names used in code actually exist"""
    try:
        # Roles used in the validation logic
        code_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]

        existing_roles = frappe.get_all("Role", pluck="name")

        validation_results = {}
        for role in code_roles:
            validation_results[role] = {
                "exists": role in existing_roles,
                "status": "✅ Valid" if role in existing_roles else "❌ Missing",
            }

        return {
            "role_validation": validation_results,
            "missing_roles": [role for role in code_roles if role not in existing_roles],
            "recommendation": "Update code to use existing role names"
            if any(role not in existing_roles for role in code_roles)
            else "All roles exist",
        }

    except Exception as e:
        return {"error": str(e)}
