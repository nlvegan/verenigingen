"""Delete the Web Form row left behind by the removed donation form (#813).

The dead donation Web Form (route ``donate``, unpublished, no caller of its ``process_donation_form``
endpoint) was deleted from the app. A standard Web Form's row outlives its files on an existing site,
so remove it. The live /donate page is a template page, not this form. Idempotent.
"""

import frappe

WEB_FORM = "donation-form"


def execute():
    if frappe.db.exists("Web Form", WEB_FORM):
        frappe.delete_doc("Web Form", WEB_FORM, force=True, ignore_permissions=True)
