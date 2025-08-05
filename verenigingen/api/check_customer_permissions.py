import frappe


@frappe.whitelist()
def check_customer_permissions():
    """Check Customer DocType permissions"""

    try:
        # Check roles with Customer read access (both standard and custom permissions)
        standard_roles = frappe.db.sql(
            """
            SELECT DISTINCT role
            FROM `tabDocPerm`
            WHERE parent = 'Customer' AND `read` = 1
            ORDER BY role
        """
        )

        custom_roles = frappe.db.sql(
            """
            SELECT DISTINCT role
            FROM `tabCustom DocPerm`
            WHERE parent = 'Customer' AND `read` = 1
            ORDER BY role
        """
        )

        all_roles = set([role[0] for role in standard_roles] + [role[0] for role in custom_roles])
        roles_with_read = sorted(list(all_roles))

        # Check if Verenigingen Administrator has access
        has_verenigingen_admin = "Verenigingen Administrator" in roles_with_read

        # Check if the current user can access Customer
        try:
            # Try to get a Customer record - will fail if no permission
            frappe.db.get_value("Customer", {}, "name", limit=1)
            user_can_access = True
        except frappe.PermissionError:
            user_can_access = False
        except Exception:
            user_can_access = False

        return {
            "success": True,
            "roles_with_customer_read": roles_with_read,
            "verenigingen_admin_has_access": has_verenigingen_admin,
            "current_user_can_access": user_can_access,
            "current_user": frappe.session.user,
            "current_user_roles": frappe.get_roles(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
