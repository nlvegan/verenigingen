import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def check_and_fix_workspace(force_enable=False) -> OperationResult[Dict[str, Any]]:
    """Check workspace and add Communication section"""
    try:
        # SAFETY GUARD: Prevent accidental workspace corruption
        if not force_enable:
            return OperationResult.fail(
                _("Workspace auto-correction disabled for safety. Use force_enable=True to override."),
                error_code="SAFETY_GUARD_ENABLED",
            )

        if not frappe.db.exists("Workspace", "Verenigingen"):
            return OperationResult.fail(
                _("Workspace does not exist. Run bench migrate first."), error_code="WORKSPACE_NOT_FOUND"
            )

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if Communication section exists in content
        content_str = workspace.content
        has_comm_section = "CommunicationHeader" in content_str or "CommunicationCard" in content_str

        if not has_comm_section:
            # Add Communication section after Teams section
            new_content = content_str.replace(
                '}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
                '}},{"id":"CommunicationHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Communication & Newsletters</b></span>","col":12}},{"id":"CommunicationCard","type":"card","data":{"card_name":"Communication","col":4}},{"id":"zGoLYG0xRM6","type":"spacer","data":{"col":12}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
            )
            workspace.content = new_content

        # Check if Newsletter links exist
        has_newsletter = any(
            link.link_to == "Newsletter" for link in workspace.links if hasattr(link, "link_to")
        )

        if not has_newsletter:
            # Add Communication card break
            workspace.append("links", {"label": "Communication", "type": "Card Break"})

            # Newsletter links
            newsletter_links = [
                {
                    "label": "Newsletter",
                    "link_to": "Newsletter",
                    "link_type": "DocType",
                    "description": "Create and send newsletters to members",
                },
                {
                    "label": "Email Group",
                    "link_to": "Email Group",
                    "link_type": "DocType",
                    "description": "Manage email groups for targeted communication",
                },
                {
                    "label": "Email Group Member",
                    "link_to": "Email Group Member",
                    "link_type": "DocType",
                    "description": "Manage members in email groups",
                },
                {
                    "label": "Communication",
                    "link_to": "Communication",
                    "link_type": "DocType",
                    "description": "View communication history and logs",
                },
                {
                    "label": "Email Template",
                    "link_to": "Email Template",
                    "link_type": "DocType",
                    "description": "Manage email templates for automated communications",
                },
            ]

            for link in newsletter_links:
                workspace.append("links", link)

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=workspace,
            justification="Check workspace and add Communication section - workspace configuration management",
            required_permissions=["Workspace:write"],
        )

        if not result.success:
            error_msg = "; ".join(result.errors)
            frappe.log_error(f"Failed to fix workspace: {error_msg}", "Workspace Fix Failed")
            return OperationResult.fail(
                _("Failed to fix workspace: {0}").format(error_msg), error_code="WORKSPACE_SAVE_FAILED"
            )

        frappe.db.commit()
        frappe.clear_cache()

        data = {
            "has_comm_section": has_comm_section or True,
            "has_newsletter": has_newsletter or True,
            "total_links": len(workspace.links),
        }

        return OperationResult.ok(data, message=_("Workspace updated with Communication section"))

    except Exception as e:
        frappe.log_error(
            title=_("Workspace Fix Error"),
            message=f"Error fixing workspace: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            _("An error occurred while fixing workspace: {0}").format(str(e)),
            error_code="WORKSPACE_FIX_ERROR",
        )
