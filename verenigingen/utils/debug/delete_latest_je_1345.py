#!/usr/bin/env python3
"""
Delete the latest Journal Entry for mutation 1345
"""

import frappe


@frappe.whitelist()
def delete_latest_je_1345():
    """Delete the latest Journal Entry for mutation 1345"""
    try:
        # Find the latest Journal Entry for mutation 1345
        je_entries = frappe.db.sql(
            """SELECT name FROM `tabJournal Entry`
               WHERE eboekhouden_mutation_nr = %s
               ORDER BY creation DESC
               LIMIT 1""",
            "1345",
            as_dict=True,
        )

        if not je_entries:
            return {"success": False, "message": "No Journal Entry found for mutation 1345"}

        je_name = je_entries[0]["name"]

        # Get the document
        je = frappe.get_doc("Journal Entry", je_name)

        # Cancel if submitted
        if je.docstatus == 1:
            je.cancel()
            frappe.db.commit()

        # Delete
        frappe.delete_doc("Journal Entry", je_name, force=True)
        frappe.db.commit()

        return {"success": True, "message": "Journal Entry {je_name} deleted successfully"}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
