"""
API endpoints for E-Boekhouden migration list operations
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def mass_cancel_migrations(names: str | list):
    """Cancel multiple submitted E-Boekhouden Migration documents.

    Args:
        names: list of document names to cancel (must be docstatus=1)

    Returns:
        dict with cancelled/failed counts
    """
    if isinstance(names, str):
        import json

        names = json.loads(names)

    cancelled = 0
    failed = 0
    for name in names:
        try:
            doc = frappe.get_doc("E-Boekhouden Migration", name)
            if doc.docstatus == 1:
                doc.cancel()
                cancelled += 1
        except Exception:
            frappe.log_error(
                title=f"Mass cancel failed: {name}",
                reference_doctype="E-Boekhouden Migration",
                reference_name=name,
            )
            failed += 1

    frappe.db.commit()
    return {"cancelled": cancelled, "failed": failed}
