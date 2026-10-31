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
import requests
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import add_to_date, get_datetime, now_datetime
from rq.timeouts import JobTimeoutException

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAPIError,
    PontoAuthenticationError,
    PontoRateLimitError,
)

# Rows created longer ago than this stop being polled (no local status change).
STALENESS_WINDOW_DAYS = 30

# Per doctype, per run. Ponto's rate limits are unverified, so the batch stays small.
# Selection is a rotating cursor (below), so rows beyond the cap are polled on later
# runs instead of never.
BATCH_LIMIT = 100

# Outage budget. PontoClient retries and there is no circuit breaker, so a dead Ponto
# would cost every row. Stop after this many consecutive OUTAGE-shaped row failures
# (see _is_outage), or when the run has used RUN_BUDGET_SECONDS of wall clock.
MAX_CONSECUTIVE_OUTAGE_FAILURES = 3
RUN_BUDGET_SECONDS = 120

# The hourly job runs on the default queue with a 300 s timeout, and the budget is only
# checked BETWEEN rows. Longest one row can take: PontoClient.get has timeout=30 and
# with_retry(max_attempts=3, base_delay=1, max_delay=30) -> 3 x 30 s + backoff, about
# 94 s, plus a token fetch (its own 30 s timeout) when the cached token has expired,
# about 125 s. Rounded up. A row that starts just inside the budget must still end
# before the queue timeout; test_run_budget_leaves_room_for_the_slowest_row pins it.
MAX_ROW_SECONDS = 130
QUEUE_TIMEOUT_SECONDS = 300

ONCE_A_DAY_SECONDS = 24 * 60 * 60

_monotonic = time.monotonic  # replaced by a fake clock in tests

# (doctype, open statuses, Ponto id field)
_POLLED = (
    ("Ponto Payment Request", ["Pending", "Signed"], "ponto_payment_id"),
    ("Ponto Payment Link", ["Pending Authorization", "Authorized"], "ponto_request_id"),
)


def poll_open_ponto_payment_statuses():
    """Scheduler entry: refresh the open, recent Ponto Requests and Links."""
    batches = {}
    for doctype, statuses, id_field in _POLLED:
        open_count = _open_count(doctype, statuses, id_field)
        if not open_count:
            continue
        if not _configured_for(doctype):
            _log_once_a_day(
                f"unconfigured:{doctype}",
                title=f"Ponto status poll skipped: {doctype} not configured",
                message=f"There are open {doctype} rows but Ponto Settings is not configured for their "
                "client (credentials; for links also mTLS and an enabled bank account mapping).",
            )
            continue
        batches[doctype] = _next_batch(doctype, statuses, id_field)
        if open_count > BATCH_LIMIT:
            _log_once_a_day(
                f"truncated:{doctype}",
                title=f"Ponto status poll batch truncated: {doctype}",
                message=f"{open_count} open rows, {BATCH_LIMIT} polled per run; the rest are polled on "
                "later runs (rotating cursor).",
            )
    _refresh_batches(_rotated(batches))


def _open_query(doctype, statuses, id_field):
    table = frappe.qb.DocType(doctype)
    ponto_id = table[id_field]
    return table, (
        frappe.qb.from_(table)
        .where(table.docstatus != 2)  # a cancelled doc cannot be saved
        .where(table.status.isin(statuses))
        .where(ponto_id.isnotnull() & (ponto_id != ""))
        .where(table.creation >= add_to_date(now_datetime(), days=-STALENESS_WINDOW_DAYS))
    )


def _open_count(doctype, statuses, id_field):
    _table, query = _open_query(doctype, statuses, id_field)
    return query.select(Count("*")).run()[0][0]


def _cursor_cache_key(doctype):
    return f"ponto_status_poll_cursor:{doctype}"


def _open_rows_page(doctype, statuses, id_field, where, limit):
    """Open rows ordered by (creation, name); ``where(table)`` adds the cursor condition."""
    table, query = _open_query(doctype, statuses, id_field)
    query = query.select(table.name, table.creation).orderby(table.creation, order=Order.asc)
    query = query.orderby(table.name, order=Order.asc).limit(limit)
    if where is not None:
        query = query.where(where(table))
    return [frappe._dict(name=name, creation=creation) for name, creation in query.run()]


def _next_batch(doctype, statuses, id_field):
    """The next BATCH_LIMIT rows after the stored cursor, wrapping round to the head.

    A cursor in the cache rather than "oldest first" or ``modified asc``: oldest-first
    starved every row past the cap behind abandoned ones, and ``modified asc`` only
    rotates for doctypes that save on every refresh (Links do, Requests only on a
    change). The cursor writes nothing to the rows (no schema field, no Version row)
    and is applied in SQL, so there is no fixed listing cap. A lost cache just restarts
    the rotation.
    """
    cursor = frappe.cache().get_value(_cursor_cache_key(doctype))
    if not cursor:
        return _open_rows_page(doctype, statuses, id_field, None, BATCH_LIMIT)
    after = _open_rows_page(
        doctype,
        statuses,
        id_field,
        lambda t: (t.creation > cursor.creation) | ((t.creation == cursor.creation) & (t.name > cursor.name)),
        BATCH_LIMIT,
    )
    if len(after) >= BATCH_LIMIT:
        return after
    head = _open_rows_page(
        doctype,
        statuses,
        id_field,
        lambda t: (t.creation < cursor.creation)
        | ((t.creation == cursor.creation) & (t.name <= cursor.name)),
        BATCH_LIMIT - len(after),
    )
    return after + head


def _rotated(batches):
    """Alternate which doctype goes first, so neither is structurally always first."""
    if len(batches) < 2:
        return batches
    key = "ponto_status_poll_rotation"
    turn = frappe.cache().get_value(key) or 0
    frappe.cache().set_value(key, turn + 1)
    names = list(batches)
    offset = turn % len(names)
    return {name: batches[name] for name in names[offset:] + names[:offset]}


def _refresh_batches(batches):
    deadline = _monotonic() + RUN_BUDGET_SECONDS
    consecutive_outages = attempted = 0
    last_attempted = {}
    stop_reason = None
    for doctype, rows in batches.items():
        for row in rows:
            if consecutive_outages >= MAX_CONSECUTIVE_OUTAGE_FAILURES:
                stop_reason = f"{consecutive_outages} consecutive Ponto outage-type failures"
            elif _monotonic() >= deadline:
                stop_reason = f"the {RUN_BUDGET_SECONDS} s run budget was used up"
            if stop_reason:
                break
            last_attempted[doctype] = row
            attempted += 1
            outcome = _refresh_one(doctype, row.name)
            # A data error (4xx, validation, unmapped account) says nothing about Ponto
            # being down, so it neither counts toward the stop nor resets the count.
            if outcome == OUTAGE:
                consecutive_outages += 1
            elif outcome == OK:
                consecutive_outages = 0
        if stop_reason:
            break
    # Only reached on a normal exit. A fatal exception (deadlock, job timeout) propagates
    # past this line: the transaction rolls back with it, so the cursor must not move
    # past rows whose work was lost.
    for doctype, row in last_attempted.items():
        frappe.cache().set_value(_cursor_cache_key(doctype), row)
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


def _log_once_a_day(key_suffix, title, message):
    key = f"ponto_status_poll_logged:{key_suffix}"
    if frappe.cache().get_value(key):
        return
    frappe.cache().set_value(key, 1, expires_in_sec=ONCE_A_DAY_SECONDS)
    frappe.log_error(title=title, message=f"{message} Logged once a day.")


def _causes(exc):
    """``exc`` and everything on its ``__cause__``/``__context__`` chain."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        yield exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__


def _fatal_in_chain(exc):
    """A deadlock/lock-timeout or an RQ job timeout hiding inside ``exc``'s cause chain.

    ``refresh_status`` catches everything and ``frappe.throw``s, so these never reach
    this module as themselves; the original is still on ``__cause__``/``__context__``.
    Covers a timeout raised in the code ``refresh_status`` calls, not one raised inside
    ``with_retry`` mid-HTTP: that layer swallows it (#1919).
    """
    return next(
        (e for e in _causes(exc) if isinstance(e, NON_RESUMABLE_DB_ERRORS + (JobTimeoutException,))), None
    )


def _is_outage(exc):
    """True for failures that say Ponto (or the path to it) is down or throttling.

    Classified on the exception classes the Ponto client raises, never on message text:
    transport failures (``PontoClient.get`` wraps ``requests.RequestException`` in a
    ``PontoAPIError`` with no status code), HTTP 5xx, 429 (``PontoRateLimitError``) and
    401 (``PontoAuthenticationError``: the token is shared by every row). Other 4xx and
    local validation/configuration errors are per-row data errors.
    """
    for e in _causes(exc):
        if isinstance(e, (PontoRateLimitError, PontoAuthenticationError, requests.RequestException)):
            return True
        if isinstance(e, (ConnectionError, TimeoutError)):
            return True
        if isinstance(e, PontoAPIError) and (e.status_code is None or e.status_code >= 500):
            return True
    return False


OK, OUTAGE, DATA_ERROR = "ok", "outage", "data_error"


def _refresh_one(doctype, name):
    """Refresh one row in its own savepoint. Returns OK, OUTAGE or DATA_ERROR."""
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
        return OUTAGE if _is_outage(e) else DATA_ERROR
    release_savepoint_if_present(savepoint)
    return OK
