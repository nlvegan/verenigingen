"""Record which import record created or updated a Member (#1777)."""

import frappe


def mark_member_imported(member_doc, import_doctype, import_name):
    """Set Member.import_source_type / import_source to the import record, on the in-memory doc.

    The one place every importer (Mijnrood CSV, Member Import, VIP Import, ...) records
    provenance. Only a record that exists is stored: the MijnRood event sync passes a label
    ("MijnRood Sync: <event>") rather than a record name, and a dangling Dynamic Link would
    fail the Member's link validation. Returns whether the fields were set.
    """
    if not import_name or not frappe.db.exists(import_doctype, import_name):
        return False
    member_doc.import_source_type = import_doctype
    member_doc.import_source = import_name
    return True
