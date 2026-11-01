"""Put stock Email Templates back to what verenigingen/fixtures/email_template.json ships.

Tests that force-delete or overwrite fixture-shipped Email Templates must not leave
the table different for the next module in the shard (#1981, #1982): a missing row
gets recreated by setup code from a different body, and a test-authored row replaces
the shipped one. Restoring from the FIXTURE (not from a snapshot of the current DB)
means a site that is already polluted when the class starts is still healed.
"""

import json

import frappe

from verenigingen.tests.utils.paths import APP_ROOT

FIXTURE_PATH = APP_ROOT / "verenigingen" / "fixtures" / "email_template.json"


def _load_fixture_rows():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return {row["name"]: row for row in json.load(f)}


def _cleanup_stock_email_templates(names):
    """For each name: delete whatever is there; re-create it from the fixture if the
    fixture ships it. Names the fixture does not ship are left deleted, so a
    test-created template cannot survive. Commits (the deletes it undoes were
    committed by the tests too, and a rollback would resurrect the pollution)."""
    fixture = _load_fixture_rows()
    for name in names:
        if frappe.db.exists("Email Template", name):
            frappe.delete_doc("Email Template", name, force=True)
        if name in fixture:
            row = {k: v for k, v in fixture[name].items() if k != "modified"}
            doc = frappe.get_doc(row)
            # Fixture import does not validate links either; some shipped rows point
            # reference_doctype at a name that is not a DocType here.
            doc.flags.ignore_links = True
            doc.insert()
    frappe.db.commit()
