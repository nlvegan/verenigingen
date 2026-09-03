"""A stub Procurios import doc, shared by the mandate- and membership-import suites.

Both `test_procurios_mandate_import.py` and
`test_procurios_membership_import_row_atomicity.py` need an inserted import doc
with a placeholder CSV file (its content is never read by the per-row unit
tests, which build their mapped rows by hand) -- only the doctype name
differs. Consolidated here after the duplicate-helper ratchet flagged the two
copies as near-identical (#698 review).
"""

import frappe


def _create_stub_import_doc(doctype: str):
    """Insert `doctype` with a placeholder private CSV file attached."""
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": "stub.csv",
            "is_private": 1,
            "content": b"stub",
        }
    )
    file_doc.flags.ignore_permissions = True
    file_doc.insert()

    doc = frappe.get_doc(
        {
            "doctype": doctype,
            "csv_file": file_doc.file_url,
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc
