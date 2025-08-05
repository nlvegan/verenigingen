import frappe


@frappe.whitelist()
def grant_verenigingen_admin_customer_access():
    """Grant Verenigingen Administrator read access to Customer DocType"""

    try:
        # Check if permission already exists
        existing = frappe.db.exists(
            "Custom DocPerm", {"parent": "Customer", "role": "Verenigingen Administrator"}
        )

        if existing:
            return {
                "success": True,
                "message": "Verenigingen Administrator already has Customer permissions",
                "existing_permission": existing,
            }

        # Create new Custom DocPerm for Customer
        custom_perm = frappe.new_doc("Custom DocPerm")
        custom_perm.parent = "Customer"
        custom_perm.parenttype = "DocType"
        custom_perm.parentfield = "permissions"
        custom_perm.role = "Verenigingen Administrator"
        custom_perm.read = 1
        custom_perm.write = 0  # Read-only access
        custom_perm.create = 0
        custom_perm.delete = 0
        custom_perm.submit = 0
        custom_perm.cancel = 0
        custom_perm.amend = 0
        custom_perm.report = 1  # Allow in reports
        custom_perm.export = 0
        setattr(custom_perm, "import", 0)  # import is a reserved keyword
        custom_perm.share = 0
        custom_perm.print = 0
        custom_perm.email = 0

        custom_perm.save()

        # Clear the cache to ensure permission changes take effect
        frappe.clear_cache(doctype="Customer")
        frappe.cache().delete_value("app_hooks")

        return {
            "success": True,
            "message": "Successfully granted Verenigingen Administrator read access to Customer DocType",
            "permission_name": custom_perm.name,
            "details": {
                "role": "Verenigingen Administrator",
                "doctype": "Customer",
                "permissions": "Read + Report access only",
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def verify_customer_access_fix():
    """Verify that the Customer access fix worked"""

    try:
        # Check if permission exists
        perm_exists = frappe.db.exists(
            "Custom DocPerm", {"parent": "Customer", "role": "Verenigingen Administrator", "read": 1}
        )

        # Try to access Customer data as current user
        try:
            customer_count = frappe.db.count("Customer")
            can_access = True
            access_error = None
        except Exception as e:
            can_access = False
            access_error = str(e)
            customer_count = None

        return {
            "success": True,
            "permission_exists": bool(perm_exists),
            "can_access_customer": can_access,
            "customer_count": customer_count,
            "access_error": access_error,
            "current_user": frappe.session.user,
            "current_roles": frappe.get_roles(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
