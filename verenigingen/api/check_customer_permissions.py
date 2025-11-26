import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def check_customer_permissions() -> OperationResult[Dict[str, Any]]:
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
            frappe.db.get_value("Customer", {}, "name", limit=1, order_by="name")
            user_can_access = True
        except frappe.PermissionError:
            user_can_access = False
        except Exception:
            user_can_access = False

        data = {
            "roles_with_customer_read": roles_with_read,
            "verenigingen_admin_has_access": has_verenigingen_admin,
            "current_user_can_access": user_can_access,
            "current_user": frappe.session.user,
            "current_user_roles": frappe.get_roles(),
        }

        return OperationResult.ok(data, message=_("Customer permissions retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Customer Permissions Check Failed"),
            message=f"{_('Error checking Customer permissions')}: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(_("Failed to check Customer permissions: {0}").format(str(e)))
