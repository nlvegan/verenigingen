import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def check_user_details(email) -> OperationResult[Dict[str, Any]]:
    """Check user details and roles"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", email):
            return OperationResult.fail(
                _("User not found"),
                errors=[_("User {0} does not exist").format(email)],
                context={"email": email},
            )

        # Get user details
        user_doc = frappe.get_doc("User", email)
        user_roles = frappe.get_roles(email)

        # Check if user is linked to a Member record
        member_record = frappe.db.get_value("Member", {"user": email}, ["name", "full_name"], as_dict=True)

        # Check how many membership dues schedules exist in total
        total_schedules = frappe.db.count("Membership Dues Schedule")
        template_schedules = frappe.db.count("Membership Dues Schedule", {"is_template": 1})
        non_template_schedules = total_schedules - template_schedules

        data = {
            "user_email": email,
            "user_enabled": user_doc.enabled,
            "user_roles": user_roles,
            "member_record": member_record,
            "total_schedules": total_schedules,
            "template_schedules": template_schedules,
            "non_template_schedules": non_template_schedules,
        }

        message = _("User details retrieved for {0}").format(email)
        if member_record:
            message = _("User {0} linked to member {1}").format(email, member_record.get("full_name"))

        return OperationResult.ok(data, message=message)

    except Exception as e:
        frappe.log_error(
            title=_("Check User Details Failed"),
            message=traceback.format_exc(),
        )
        return OperationResult.fail(
            _("Failed to retrieve user details"),
            errors=[str(e)],
            context={"email": email, "traceback": traceback.format_exc()},
        )
