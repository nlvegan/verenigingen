# Copyright (c) 2026, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Rules for Ponto Payment Request / Link rows AFTER they were submitted (#1907, #1920, #1848).

Three things live here because both doctypes need the same ones:

1. ``refuse_unless_system_update`` -- ``allow_on_submit`` lets a submitted row change, but
   it cannot say WHO may change it. Without this guard anyone holding write permission
   (Accounts Manager) could set ``status = Executed``, repoint ``payment_entry`` or change
   ``sales_invoice``/``debtor_iban`` through ``frappe.client.set_value``. A change to the
   guarded fields is refused unless the writer set ``doc.flags.ponto_system_update``.
   Only system code (webhook, refresh/poll, Payment Entry creation, invoice matcher, the
   callbacks' proved cancel) sets it; a caller cannot, because the flag lives on the
   in-memory document and an API request builds a fresh one.

2. ``alert_executed_on_cancelled_row`` -- a locally cancelled (docstatus 2) row can still
   be paid at Ponto. The cancelled document is left unchanged; finance is told, once.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt

SYSTEM_UPDATE_FLAG = "ponto_system_update"

REQUEST_GUARDED_FIELDS = ("status", "payment_entry")
LINK_GUARDED_FIELDS = (
    "status",
    "payment_entry",
    "sales_invoice",
    "debtor_name",
    "debtor_iban",
    "debtor_bank",
)

ALERT_TITLE = "Ponto payment reported executed for a CANCELLED row"
# Marker the ToDo dedupe keys on; also the first line of the ToDo text.
ALERT_MARKER = "PONTO-EXECUTED-ON-CANCELLED-ROW"


def refuse_unless_system_update(doc, guarded_fields):
    """Refuse a change to ``guarded_fields`` on a submitted row unless a system writer set the flag.

    Fails closed: the stored values are read from the database, not from
    ``get_doc_before_save()``, so a missing snapshot cannot let a change through.
    """
    if doc.flags.get(SYSTEM_UPDATE_FLAG):
        return

    stored = frappe.db.get_value(doc.doctype, doc.name, list(guarded_fields), as_dict=True) or {}
    changed = [f for f in guarded_fields if cstr(stored.get(f)) != cstr(doc.get(f))]
    if changed:
        labels = ", ".join(_(doc.meta.get_label(f)) for f in changed)
        frappe.throw(
            _("{0} can only be changed by the Ponto status updates, not edited by hand: {1}").format(
                doc.doctype, labels
            ),
            frappe.PermissionError,
        )


def alert_executed_on_cancelled_row(doc, ponto_id):
    """Tell finance that Ponto reports a cancelled row as executed. Returns True if ``doc`` is cancelled.

    The caller must then leave the document alone: a docstatus-2 row cannot be saved, and
    booking money against it is a human decision (#1848).

    Mechanism: a ToDo on the row (the same "manual review task" shape as
    ``sepa_reconciliation.handle_partial_sepa_batch``) plus an Error Log row with a
    distinctive title. Once per row: an existing ToDo with the marker, open or closed, stops
    a repeat from the next poll tick or webhook redelivery.
    """
    if doc.docstatus != 2:
        return False

    if frappe.db.exists(
        "ToDo",
        {
            "reference_type": doc.doctype,
            "reference_name": doc.name,
            "description": ["like", f"{ALERT_MARKER}%"],
        },
    ):
        return True

    text = (
        f"{ALERT_MARKER}\n"
        f"Ponto reports {doc.doctype} {doc.name} as EXECUTED, but it was cancelled here. "
        f"The cancelled document has NOT been changed and no Payment Entry was made.\n"
        f"Amount: EUR {flt(doc.amount):,.2f}\n"
        f"Ponto id: {ponto_id}\n"
        f"Action required: check the bank, and book the payment by hand if the money moved."
    )
    todo = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": text,
            "priority": "High",
            "status": "Open",
            "reference_type": doc.doctype,
            "reference_name": doc.name,
            "allocated_to": "Administrator",
        }
    )
    # Security: system alert raised from a verified webhook / refresh; the acting user
    # (webhook user or Guest) has no ToDo permission, and the alert must not be lost.
    todo.insert(ignore_permissions=True)
    frappe.log_error(title=ALERT_TITLE, message=text)
    return True
