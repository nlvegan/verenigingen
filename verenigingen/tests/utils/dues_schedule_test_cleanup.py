"""Shared teardown helper for tests that build a submitted Sales Invoice +
Membership Dues Schedule pair to exercise the #1264 link-integrity guard.

Extracted after the duplicate-helper guard flagged near-identical copies in
two test files (test_membership_application_review_coverage.py and
test_member_cleanup_service.py) -- see that guard's own advice: import the
one copy rather than letting each test file keep its own.
"""

import frappe


def cancel_and_delete_invoice_and_schedule(invoice_name, schedule_name):
    """Cancel (if still submitted) and force-delete a Sales Invoice, then
    force-delete a Membership Dues Schedule. Safe to call whether or not
    either row still exists (e.g. the schedule may have been legitimately
    deleted by the code under test).
    """
    if frappe.db.exists("Sales Invoice", invoice_name):
        doc = frappe.get_doc("Sales Invoice", invoice_name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.cancel()
        frappe.delete_doc("Sales Invoice", invoice_name, force=True, ignore_permissions=True)
    if frappe.db.exists("Membership Dues Schedule", schedule_name):
        frappe.delete_doc(
            "Membership Dues Schedule", schedule_name, force=True, ignore_permissions=True
        )
    frappe.db.commit()
