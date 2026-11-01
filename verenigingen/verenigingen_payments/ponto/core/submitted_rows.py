# Copyright (c) 2026, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Rules for Ponto Payment Request / Link rows AFTER they were submitted (#1907, #1920, #1848).

Three things live here because both doctypes need the same ones:

1. ``refuse_unless_system_update`` -- ``allow_on_submit`` lets a submitted row change, but
   it cannot say WHO may change it. Without this guard anyone holding write permission
   (Accounts Manager) could set ``status = Executed``, repoint ``payment_entry`` or change
   ``sales_invoice``/``debtor_iban`` through ``frappe.client.set_value``. A change to the
   guarded fields is refused unless the writer set ``doc.flags.ponto_system_update``,
   which only system code does, through ``system_update(doc)``. A caller cannot set it:
   the flag lives on the in-memory document and an API request builds a fresh one.
   A WHITELISTED writer is the exception: ``run_doc_method`` builds the document from the
   client's dict, so such a writer must use ``as_system_update_from_db``, which re-reads the
   row before the flag is taken (``refresh_status`` on both doctypes).

   CONTRACT for any new system writer (the token-proved callback cancel on #1896 is one):
   ``with system_update(doc): doc.status = ...; doc.save(ignore_permissions=True)``. Both
   halves are needed. The flag satisfies this guard; ``ignore_permissions`` is for the
   webhook user, who holds no ``submit`` right, which a docstatus 1 -> 1 save checks (#1920).

2. ``alert_executed_on_cancelled_row`` -- a locally cancelled (docstatus 2) row can still
   be paid at Ponto. The cancelled document is left unchanged; staff are told, once.
"""

import functools
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cstr, escape_html, flt

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
UNDELIVERED_TITLE = "Ponto executed-on-cancelled-row alert was NOT DELIVERED to anyone"
# Registered in notification_registry.py; recipients are set in Verenigingen Email Configuration.
# The call below repeats the literal because "Sync Registry" discovers keys by grepping for it.
ALERT_KEY = "ponto_executed_on_cancelled_row"
# Starts every alert's Notification Log subject and Error Log message; the dedupe keys on it.
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


@contextmanager
def system_update(doc):
    """Mark ``doc`` as being written by system code for the length of the block, then restore it.

    Restores the PREVIOUS value rather than clearing, so a nested writer (the webhook method
    calling create_payment_entry) does not drop the outer writer's flag. Afterwards the
    in-memory document no longer carries the flag, so a later hand edit through the same
    object is refused.
    """
    previous = doc.flags.get(SYSTEM_UPDATE_FLAG)
    doc.flags[SYSTEM_UPDATE_FLAG] = True
    try:
        yield doc
    finally:
        if previous is None:
            doc.flags.pop(SYSTEM_UPDATE_FLAG, None)
        else:
            doc.flags[SYSTEM_UPDATE_FLAG] = previous


def as_system_update(writer):
    """Run a writer (a method, or a function whose first argument is the document) under ``system_update``."""

    @functools.wraps(writer)
    def wrapper(doc, *args, **kwargs):
        with system_update(doc):
            return writer(doc, *args, **kwargs)

    return wrapper


def as_system_update_from_db(writer):
    """Like ``as_system_update``, for a WHITELISTED writer: re-read the document from the database first.

    ``frappe.handler.run_doc_method`` builds the document from the CLIENT's dict, so a client can put
    any value in a guarded field. Taking the flag over that object would persist those values. Reloading
    before the flag is taken drops every client-supplied value; nothing unsaved survives, which is right
    for an action that reads its truth from Ponto.
    """

    @functools.wraps(writer)
    def wrapper(doc, *args, **kwargs):
        if not doc.is_new():
            doc.reload()
        with system_update(doc):
            return writer(doc, *args, **kwargs)

    return wrapper


def alert_executed_on_cancelled_row(doc, ponto_id):
    """Tell staff that Ponto reports a cancelled row as executed. Returns True if ``doc`` is cancelled.

    The caller must then leave the document alone: a docstatus-2 row cannot be saved, and
    booking money against it is a human decision (#1848).

    A cancelled row whose ``payment_entry`` is still live (docstatus 1) was booked before it
    was cancelled. That is already handled, and an alert would send someone to book it again.

    Delivery: ``notify_administrators`` with the registered key ``ponto_executed_on_cancelled_row``,
    so recipients are configurable in Verenigingen Email Configuration and fall back to the
    admin roles. An Error Log row with a distinctive title is the audit trail.

    Once per row, and safe against two deliveries at once: the row is locked first, and the
    two markers (a Notification Log for the document, an Error Log row for it) are read with
    locking reads, so a second delivery sees what the first committed.
    """
    if doc.docstatus != 2:
        return False

    if doc.payment_entry and frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus") == 1:
        return True

    frappe.db.get_value(doc.doctype, doc.name, "name", for_update=True)
    subject = f"{ALERT_MARKER}: {doc.doctype} {doc.name} was paid at Ponto but is cancelled here"
    notified = frappe.db.get_value(
        "Notification Log",
        {"document_type": doc.doctype, "document_name": doc.name, "subject": ["like", f"{ALERT_MARKER}%"]},
        "name",
        for_update=True,
    )
    logged = frappe.db.exists(
        "Error Log", {"method": ALERT_TITLE, "error": ["like", f"{ALERT_MARKER}: {doc.doctype} {doc.name} %"]}
    )
    if notified and logged:
        return True

    details = (
        f"{ALERT_MARKER}: {doc.doctype} {doc.name} reported EXECUTED by Ponto, but it was cancelled here. "
        f"The cancelled document has NOT been changed and no Payment Entry was made. "
        f"Amount: EUR {flt(doc.amount):,.2f}. Ponto id: {ponto_id}. "
        f"Action required: check the bank, and book the payment by hand if the money moved."
    )
    delivery = {"skipped": "already notified"}
    if not notified:
        from verenigingen.utils.notification_helpers import notify_administrators

        delivery = notify_administrators(
            subject=subject,
            message=f"<p>{escape_html(details)}</p>",
            notification_key="ponto_executed_on_cancelled_row",  # literal: key discovery greps for it
            document_type=doc.doctype,
            document_name=doc.name,
            exclude_users=["Administrator"],  # ruling 2026-11-01: staff alerts never go to Administrator
        )
        # No notification created: key unseeded or disabled (skipped), no recipient left, or failed.
        # Delivery is retried on every call (the key may be seeded later), but the loud row is
        # written ONCE per document: the poll calls this hourly for a cancelled row (#1931).
        if not delivery.get("notifications_created") and not _undelivered_logged(doc):
            _log_undelivered(details, delivery)
    if not logged:
        frappe.log_error(title=ALERT_TITLE, message=f"{details}\nNotification: {delivery}")
    return True


def _undelivered_logged(doc):
    return frappe.db.exists(
        "Error Log",
        {"method": UNDELIVERED_TITLE, "error": ["like", f"{ALERT_MARKER}: {doc.doctype} {doc.name} %"]},
    )


def _log_undelivered(details, delivery):
    """Say loudly that the alert reached nobody (key not seeded, disabled, no recipient, delivery failed).

    Fresh installs do not run patches, so the key can have no row and then counts as disabled; the
    Error Log row above would be the only trace and nobody reads it for this. #1848 asks for a loud alert.
    """
    frappe.log_error(
        title=UNDELIVERED_TITLE,
        message=f"{details}\nNOBODY WAS NOTIFIED ({delivery}). Check Verenigingen Email Configuration "
        f"for the notification type '{ALERT_KEY}': it must exist, be enabled and have recipients.",
    )
