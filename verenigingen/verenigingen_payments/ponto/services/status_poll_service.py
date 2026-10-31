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

KNOWN LIMITATION (#1907, fixed in a separate prerequisite PR): the fields a poll
writes are not ``allow_on_submit`` on the two doctypes, so a real SUBMITTED Ponto
document cannot change status through ``refresh_status`` yet. The tests here use
docstatus-0 rows; a submitted-document test follows once this branch is rebased
onto the #1907 fix.

Transactions: nothing here commits. Frappe's scheduler commits after the job, as
for every other entry in ``hooks/scheduler.py``. Each row runs in its own
savepoint so one failure rolls back only that row.
"""

import time

import frappe
from frappe.utils import add_to_date, now_datetime
from rq.timeouts import JobTimeoutException

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)

# Rows created longer ago than this stop being polled (no local status change).
STALENESS_WINDOW_DAYS = 30

# Per doctype, per run. Ponto's rate limits are unverified, so the batch stays small.
# Selection is a rotating cursor (below), so rows beyond the cap are polled on later
# runs instead of never.
BATCH_LIMIT = 100

# Safety bound on the cheap (name, creation) listing the cursor rotates over.
QUERY_LIMIT = 1000

# Outage budget. PontoClient retries 3x (about 3 s) per failing call and there is no
# circuit breaker, so a dead Ponto would cost every row. Stop after this many
# consecutive failed rows, or when the run has used this much wall clock. The hourly
# job runs on the default queue (300 s timeout), hence well under it.
MAX_CONSECUTIVE_FAILURES = 3
RUN_BUDGET_SECONDS = 200

UNCONFIGURED_LOG_TTL_SECONDS = 24 * 60 * 60

_monotonic = time.monotonic  # replaced by a fake clock in tests

# (doctype, open statuses, Ponto id field)
_POLLED = (
    ("Ponto Payment Request", ["Pending", "Signed"], "ponto_payment_id"),
    ("Ponto Payment Link", ["Pending Authorization", "Authorized"], "ponto_request_id"),
)


def poll_open_ponto_payment_statuses():
    """Scheduler entry: refresh the open, recent Ponto Requests and Links."""
    batches, truncated = {}, []
    for doctype, statuses, id_field in _POLLED:
        rows = _open_rows(doctype, statuses, id_field)
        if rows and not _configured_for(doctype):
            _log_unconfigured_once_a_day(doctype)
            continue
        if rows:
            batches[doctype] = _next_batch(doctype, rows)
            if len(rows) > BATCH_LIMIT:
                truncated.append(f"{doctype}: {len(rows)} open, {BATCH_LIMIT} polled")
    if truncated:
        frappe.log_error(
            title="Ponto status poll batch truncated",
            message="; ".join(truncated) + ". The rest are polled on later runs (rotating cursor).",
        )
    _refresh_batches(batches)


def _open_rows(doctype, statuses, id_field):
    return frappe.get_all(
        doctype,
        filters={
            "docstatus": ["!=", 2],  # a cancelled doc cannot be saved
            "status": ["in", statuses],
            id_field: ["is", "set"],
            "creation": [">=", add_to_date(now_datetime(), days=-STALENESS_WINDOW_DAYS)],
        },
        fields=["name", "creation"],
        order_by="creation asc, name asc",
        limit_page_length=QUERY_LIMIT,
    )


def _row_key(row):
    return f"{row.creation.isoformat(sep=' ', timespec='microseconds')}|{row.name}"


def _cursor_cache_key(doctype):
    return f"ponto_status_poll_cursor:{doctype}"


def _next_batch(doctype, rows):
    """The next BATCH_LIMIT rows after the stored cursor, wrapping round at the end.

    A cursor in the cache rather than "oldest first" or ``modified asc``: oldest-first
    starved every row past the cap behind abandoned ones, and ``modified asc`` only
    rotates for doctypes that save on every refresh (Links do, Requests only on a
    change). The cursor writes nothing to the rows (no schema field, no Version row).
    A lost cache just restarts the rotation.
    """
    cursor = frappe.cache().get_value(_cursor_cache_key(doctype))
    start = next((i for i, row in enumerate(rows) if cursor and _row_key(row) > cursor), 0)
    return (rows[start:] + rows[:start])[:BATCH_LIMIT]


def _refresh_batches(batches):
    deadline = _monotonic() + RUN_BUDGET_SECONDS
    consecutive_failures = attempted = 0
    last_attempted = {}
    stop_reason = None
    try:
        for doctype, rows in batches.items():
            for row in rows:
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    stop_reason = f"{consecutive_failures} consecutive failures"
                elif _monotonic() >= deadline:
                    stop_reason = f"the {RUN_BUDGET_SECONDS} s run budget was used up"
                if stop_reason:
                    break
                last_attempted[doctype] = row
                attempted += 1
                consecutive_failures = 0 if _refresh_one(doctype, row.name) else consecutive_failures + 1
            if stop_reason:
                break
    finally:
        for doctype, row in last_attempted.items():
            frappe.cache().set_value(_cursor_cache_key(doctype), _row_key(row))
    if stop_reason:
        total = sum(len(rows) for rows in batches.values())
        frappe.log_error(
            title="Ponto status poll stopped early",
            message=f"Stopped after {attempted} of {total} selected rows: {stop_reason}. "
            "The remaining rows are polled on later runs.",
        )


def _configured_for(doctype):
    """True when the CLIENT this doctype's poll builds would not refuse to start.

    Request: PontoPaymentClient -> PontoClient needs OAuth credentials. Link:
    PaymentInitiationRequest's client additionally needs mTLS and an enabled bank
    account mapping (its ``_verify_pis_enabled``); without them every link fails.
    """
    settings = frappe.get_single("Ponto Settings")
    if settings.use_ibanity_mtls:
        has_credentials = bool(
            settings.ibanity_client_id
            and settings.get_password("ibanity_client_secret", raise_exception=False)
        )
    else:
        has_credentials = bool(settings.get_active_client_id() and settings.get_active_client_secret())
    if doctype == "Ponto Payment Link":
        enabled_mapping = any(m.enabled for m in settings.get("bank_account_mappings", []))
        return bool(settings.use_ibanity_mtls and has_credentials and enabled_mapping)
    return has_credentials


def _log_unconfigured_once_a_day(doctype):
    key = f"ponto_status_poll_unconfigured:{doctype}"
    if frappe.cache().get_value(key):
        return
    frappe.cache().set_value(key, 1, expires_in_sec=UNCONFIGURED_LOG_TTL_SECONDS)
    frappe.log_error(
        title=f"Ponto status poll skipped: {doctype} not configured",
        message=f"There are open {doctype} rows but Ponto Settings is not configured for their client "
        "(credentials; for links also mTLS and an enabled bank account mapping). Logged once a day.",
    )


def _fatal_in_chain(exc):
    """A deadlock/lock-timeout or an RQ job timeout hiding inside ``exc``'s cause chain.

    ``refresh_status`` catches everything and ``frappe.throw``s, so these never reach
    this module as themselves; the original is still on ``__cause__``/``__context__``.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, NON_RESUMABLE_DB_ERRORS + (JobTimeoutException,)):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def _refresh_one(doctype, name):
    """Refresh one row in its own savepoint. True on success, False on a row failure."""
    savepoint = f"ponto_poll_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        frappe.get_doc(doctype, name).refresh_status()
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        fatal = _fatal_in_chain(e)
        if fatal is not None:
            # 1205/1213 destroy or half-apply the whole transaction and a job timeout is
            # not a row problem: abandon the run rather than carry on against lost state.
            raise fatal
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title=f"Ponto status poll failed: {doctype} {name}", message=f"{type(e).__name__}: {e}"
        )
        return False
    release_savepoint_if_present(savepoint)
    return True
