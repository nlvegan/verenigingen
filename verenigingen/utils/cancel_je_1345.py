#!/usr/bin/env python3
"""
Cancel and delete Journal Entry ACC-JV-2025-72016 for re-import
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def cancel_and_delete_je_1345():
    """Cancel and delete Journal Entry ACC-JV-2025-72016"""
    try:
        je_name = "ACC-JV-2025-72016"

        # Check if exists
        if not frappe.db.exists("Journal Entry", je_name):
            return {"success": False, "message": "Journal Entry {je_name} does not exist"}

        # Get the document
        je = frappe.get_doc("Journal Entry", je_name)

        # Cancel if submitted
        if je.docstatus == 1:
            je.cancel()
            frappe.db.commit()

        # Delete
        frappe.delete_doc("Journal Entry", je_name, force=True)
        frappe.db.commit()

        return {"success": True, "message": "Journal Entry {je_name} cancelled and deleted successfully"}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
