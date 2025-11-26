"""
Get onboarding information
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_onboarding_info() -> OperationResult[Dict[str, Any]]:
    """Get detailed onboarding information"""

    try:
        # Check if Verenigingen onboarding exists
        if not frappe.db.exists("Module Onboarding", "Verenigingen"):
            frappe.log_error(
                title=_("Verenigingen Module Onboarding Not Found"),
                message=_("The Verenigingen Module Onboarding document does not exist in the database"),
            )
            return OperationResult.fail(
                error_code="ONBOARDING_NOT_FOUND", error_message=_("Verenigingen Module Onboarding not found")
            )

        # Get the onboarding document
        onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")

        # Get onboarding steps - check what fields exist first
        try:
            steps = frappe.get_all(
                "Onboarding Step",
                filters={"reference_document": "Verenigingen"},
                fields=["name", "title", "action", "is_complete"],
                order_by="idx",
            )
        except Exception:
            # Try different filter
            try:
                steps = frappe.get_all(
                    "Onboarding Step", fields=["name", "title", "action", "is_complete"], order_by="idx"
                )
                # Filter manually
                steps = [s for s in steps if "Verenigingen" in s.name]
            except Exception as e:
                steps = []
                str(e)

        data = {
            "onboarding": {
                "name": onboarding.name,
                "title": onboarding.title,
                "is_complete": onboarding.is_complete,
                "module": getattr(onboarding, "module", ""),
                "subtitle": getattr(onboarding, "subtitle", ""),
                "success_message": getattr(onboarding, "success_message", ""),
            },
            "steps": steps,
            "steps_count": len(steps),
            "direct_url": f"/app/module-onboarding/{onboarding.name}",
            "workspace_url": "/app/Verenigingen",
        }

        return OperationResult.ok(data, message=_("Onboarding information retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error Retrieving Onboarding Information"),
            message=f"{str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            error_code="ONBOARDING_RETRIEVAL_ERROR",
            error_message=_("Failed to retrieve onboarding information: {0}").format(str(e)),
        )


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_direct_onboarding_link() -> OperationResult[Dict[str, Any]]:
    """Get the direct link to access Verenigingen onboarding"""

    try:
        base_url = frappe.utils.get_url()

        # Check if onboarding exists
        if frappe.db.exists("Module Onboarding", "Verenigingen"):
            data = {
                "links": {
                    "direct_onboarding": f"{base_url}/app/module-onboarding/Verenigingen",
                    "onboarding_list": f"{base_url}/app/module-onboarding",
                    "workspace": f"{base_url}/app/Verenigingen",
                },
                "instructions": [
                    _("Click on the direct onboarding link above"),
                    _("OR go to your Verenigingen workspace and look for setup guides"),
                    _("OR search for 'Module Onboarding' in ERPNext search bar"),
                ],
            }
            return OperationResult.ok(data, message=_("Verenigingen onboarding is available"))
        else:
            frappe.log_error(
                title=_("Verenigingen Module Onboarding Not Found"),
                message=_("The Verenigingen Module Onboarding document does not exist in the database"),
            )
            return OperationResult.fail(
                error_code="ONBOARDING_NOT_FOUND", error_message=_("Verenigingen Module Onboarding not found")
            )

    except Exception as e:
        frappe.log_error(
            title=_("Error Getting Onboarding Link"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(
            error_code="ONBOARDING_LINK_ERROR",
            error_message=_("Failed to get onboarding link: {0}").format(str(e)),
        )
