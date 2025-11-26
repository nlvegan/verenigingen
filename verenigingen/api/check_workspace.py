import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_workspace() -> OperationResult[Dict[str, Any]]:
    """Check Verenigingen workspace configuration"""
    try:
        if not frappe.db.exists("Workspace", "Verenigingen"):
            return OperationResult.fail(
                _("Workspace not found"),
                errors=[_("Verenigingen workspace does not exist")],
                context={"workspace": "Verenigingen"},
            )

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check links
        newsletter_links = [
            link
            for link in workspace.links
            if "Newsletter" in link.label or "Communication" in link.label or "Email" in link.label
        ]

        # Check content for Communication card
        has_comm_card = "CommunicationCard" in workspace.content or "CommunicationHeader" in workspace.content

        # Force refresh
        frappe.clear_cache()

        data = {
            "newsletter_links": len(newsletter_links),
            "has_communication_card": has_comm_card,
            "link_details": [
                {"label": link.label, "link_to": link.link_to, "link_type": link.link_type}
                for link in newsletter_links
            ],
        }

        message = _("Workspace checked successfully. Refresh browser (Ctrl+F5) to see changes")
        if newsletter_links:
            message = _("Found {0} communication-related links. Refresh browser to see changes").format(
                len(newsletter_links)
            )

        return OperationResult.ok(data, message=message)

    except Exception as e:
        frappe.log_error(
            title=_("Workspace Check Failed"),
            message=traceback.format_exc(),
        )
        return OperationResult.fail(
            _("Failed to check workspace configuration"),
            errors=[str(e)],
            context={"traceback": traceback.format_exc()},
        )
