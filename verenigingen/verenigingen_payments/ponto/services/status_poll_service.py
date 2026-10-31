# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Scheduled Ponto status poll (#1885).

Since #1834 the guest callbacks no longer ask Ponto for status, so status reaches
us only through the signed webhook. A missed or failed delivery would leave a row
Pending/Signed forever. This hourly job is the safety net: it asks Ponto about
each OPEN row through the doctype's own ``refresh_status()``, which already owns
the shared status map, the refused-move guard (#1835: Executed is final, closed
rows never revert) and the atomic status + Payment Entry unit (#1323/#1362).

Transactions: nothing here commits. Frappe's scheduler commits after the job, as
for every other entry in ``hooks/scheduler.py``. Each row runs in its own
savepoint so one failure rolls back only that row.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)

# Rows created longer ago than this stop being polled (no local status change).
STALENESS_WINDOW_DAYS = 30

# Per doctype, per run. Ponto's rate limits are unverified (see PR notes), so the
# batch stays small; oldest open rows first, since those are the likeliest to have
# missed a webhook.
BATCH_LIMIT = 100

# (doctype, open statuses, Ponto id field)
_POLLED = (
    ("Ponto Payment Request", ["Pending", "Signed"], "ponto_payment_id"),
    ("Ponto Payment Link", ["Pending Authorization", "Authorized"], "ponto_request_id"),
)

# Flag read by PontoPaymentLink.refresh_status: do not adopt the betaalverzoek
# client's own ``closed`` marker (closedAt without a status) as Executed. A manual
# refresh still does; an unattended poll must not book a Payment Entry on it (#1840).
SKIP_CLOSED_MARKER_FLAG = "ponto_poll_skip_closed"


def poll_open_ponto_payment_statuses():
    """Scheduler entry: refresh every open, recent Ponto Request and Link."""
    open_rows = {doctype: _open_rows(doctype, statuses, id_field) for doctype, statuses, id_field in _POLLED}
    if not any(open_rows.values()) or not _ponto_configured():
        return

    for doctype, rows in open_rows.items():
        for row in rows:
            _refresh_one(doctype, row.name)


def _open_rows(doctype, statuses, id_field):
    return frappe.get_all(
        doctype,
        filters={
            "docstatus": ["!=", 2],  # a cancelled doc cannot be saved
            "status": ["in", statuses],
            id_field: ["is", "set"],
            "creation": [">=", add_to_date(now_datetime(), days=-STALENESS_WINDOW_DAYS)],
        },
        fields=["name"],
        order_by="creation asc",
        limit_page_length=BATCH_LIMIT,
    )


def _ponto_configured():
    """True when Ponto Settings holds the credentials the token manager would use."""
    settings = frappe.get_single("Ponto Settings")
    if settings.use_ibanity_mtls:
        return bool(
            settings.ibanity_client_id
            and settings.get_password("ibanity_client_secret", raise_exception=False)
        )
    return bool(settings.get_active_client_id() and settings.get_active_client_secret())


def _refresh_one(doctype, name):
    savepoint = f"ponto_poll_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        doc = frappe.get_doc(doctype, name)
        doc.flags[SKIP_CLOSED_MARKER_FLAG] = True
        doc.refresh_status()
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title=f"Ponto status poll failed: {doctype} {name}", message=f"{type(e).__name__}: {e}"
        )
    else:
        release_savepoint_if_present(savepoint)
