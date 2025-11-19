# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EBoekhoudenImportLog(Document):
    pass


def create_import_log(
    migration_name,
    import_type,
    eb_reference,
    erpnext_doctype=None,
    erpnext_name=None,
    import_status="Success",
    eb_data=None,
    error_message=None,
):
    """Helper function to create import log entries"""
    try:
        log = frappe.new_doc("E-Boekhouden Import Log")
        log.migration = migration_name
        log.import_type = import_type
        log.eb_reference = eb_reference
        log.erpnext_doctype = erpnext_doctype
        log.erpnext_name = erpnext_name
        log.import_status = import_status
        log.eb_data = str(eb_data) if eb_data else None
        log.error_message = error_message
        log.insert(ignore_permissions=True)
        return log.name
    except Exception as e:
        frappe.log_error(f"Failed to create import log: {str(e)}")
        return None
