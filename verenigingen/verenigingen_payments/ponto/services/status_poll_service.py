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

Submitted rows (#1907): Ponto rows are SUBMITTED documents. ``refresh_status`` is
``@as_system_update_from_db``, so the poll changes a submitted row's status under the
system flag the ``before_update_after_submit`` guard requires.

Cancelled rows (#1931, maintainer ruling 2026-11-01): a locally cancelled (docstatus 2)
row can still be paid at Ponto, and since no webhooks arrive for outgoing payments (#1921)
the poll is the only thing that can notice. A SECOND, separately bounded pass reads the
status of cancelled rows that still carry an open status and, ONLY when Ponto says
``executed``, raises the #1848 alert. It never calls ``refresh_status`` on such a row and
never writes to it: no save, no ``db_set``, no status. See ``_check_cancelled_one``.

Limits of the cancelled pass, by design: it depends on #1918 (``on_cancel`` sets "Cancelled" in
memory only, so a cancelled row keeps its open status in the table; if that is ever fixed the
selection finds nothing, and the ``_cancel`` fixture assertion in
``TestPollOnReallySubmittedAndCancelledRows`` trips). It runs AFTER the open rows and shares
their wall-clock budget, so it has no progress guarantee if open rows use the whole
RUN_BUDGET_SECONDS every run. A row that was already alerted, or that Ponto answers 404 for, is
read again every hour until it leaves the window: a poll cannot write to the row to mark it done.

Transactions: nothing here commits. Frappe's scheduler commits after the job, as
for every other entry in ``hooks/scheduler.py``. Each row runs in its own
savepoint so one failure rolls back only that row.
"""

import time

import frappe
import requests
from frappe.utils import add_to_date, now_datetime
from rq.timeouts import JobTimeoutException

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)
from verenigingen.verenigingen_payments.ponto.core.status_maps import map_link_status, map_request_status
from verenigingen.verenigingen_payments.ponto.core.submitted_rows import (
    alert_executed_on_cancelled_row,
    mark_retried,
    owed_alerts,
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

# The cancelled-row pass is its own pass with its own cap and cursor, so it can neither use
# up the open rows' batch nor be starved by it. A cancelled row costs one read call per run
# until it ages out of the window, so the cap is smaller than the open rows'.
CANCELLED_BATCH_LIMIT = 50

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
    batches, cancelled_batches = {}, {}
    for doctype, statuses, id_field in _POLLED:
        open_count = _open_count(doctype, statuses, id_field)
        cancelled_count = _open_count(doctype, statuses, id_field, cancelled=True)
        if not (open_count or cancelled_count):
            continue
        if not _configured_for(doctype):
            _log_once_a_day(
                f"unconfigured:{doctype}",
                title=f"Ponto status poll skipped: {doctype} not configured",
                message=f"There are open {doctype} rows but Ponto Settings is not configured for their "
                "client (credentials; for links also mTLS and an enabled bank account mapping).",
            )
            continue
        if open_count:
            batches[doctype] = _next_batch(doctype, statuses, id_field)
        if open_count > BATCH_LIMIT:
            _log_once_a_day(
                f"truncated:{doctype}",
                title=f"Ponto status poll batch truncated: {doctype}",
                message=f"{open_count} open rows, {BATCH_LIMIT} polled per run; the rest are polled on "
                "later runs (rotating cursor).",
            )
        if cancelled_count:
            cancelled_batches[doctype] = _next_batch(
                doctype, statuses, id_field, cancelled=True, limit=CANCELLED_BATCH_LIMIT
            )
        if cancelled_count > CANCELLED_BATCH_LIMIT:
            _log_once_a_day(
                f"truncated-cancelled:{doctype}",
                title=f"Ponto status poll batch truncated: cancelled {doctype}",
                message=f"{cancelled_count} cancelled rows still open at Ponto, {CANCELLED_BATCH_LIMIT} "
                "checked per run; the rest are checked on later runs (rotating cursor).",
            )
    # Open rows first: the cancelled pass shares the outage stop and the wall-clock budget but
    # runs after them, so it can never use up the budget the open rows need.
    plan = [(dt, False, rows) for dt, rows in _rotated(batches).items()]
    plan += [(dt, True, rows) for dt, rows in cancelled_batches.items()]
    _refresh_batches(plan)
    _retry_owed_alerts()


# Raw SQL rather than frappe.qb on purpose: the cursor (a stored row name) must reach the
# database as a BOUND parameter, and pypika splices values in as literals without escaping
# backslashes.
def _open_where(doctype, statuses, id_field, cancelled=False):
    """(FROM/WHERE sql, params) for the open rows, or with ``cancelled`` for the docstatus-2 rows
    that still carry an open status (``on_cancel`` sets "Cancelled" in memory only, #1918).
    ``doctype`` and ``id_field`` come from the module's own ``_POLLED`` constants, never from a
    caller; every VALUE is a bound parameter."""
    docstatus = "= 2" if cancelled else "!= 2"
    sql = (
        f"FROM `tab{doctype}` WHERE docstatus {docstatus} AND status IN %(statuses)s "
        f"AND `{id_field}` IS NOT NULL AND `{id_field}` != '' AND creation >= %(since)s"
    )
    params = {
        "statuses": tuple(statuses),
        "since": add_to_date(now_datetime(), days=-STALENESS_WINDOW_DAYS),
    }
    return sql, params


def _open_count(doctype, statuses, id_field, cancelled=False):
    sql, params = _open_where(doctype, statuses, id_field, cancelled)
    return frappe.db.sql(f"SELECT COUNT(*) {sql}", params)[0][0]


def _cursor_cache_key(doctype, cancelled=False):
    return f"ponto_status_poll_cursor:{'cancelled:' if cancelled else ''}{doctype}"


def _open_rows_page(doctype, statuses, id_field, cursor_condition, cursor, limit, cancelled=False):
    """Open rows ordered by (creation, name). ``cursor_condition`` is one of the fixed SQL
    fragments below; the cursor's values are bound parameters (a name containing a quote or a
    backslash must not reach the SQL text)."""
    sql, params = _open_where(doctype, statuses, id_field, cancelled)
    if cursor is not None:
        sql += f" AND {cursor_condition}"
        params.update(cursor_creation=cursor.creation, cursor_name=cursor.name)
    params["limit"] = int(limit)
    rows = frappe.db.sql(
        f"SELECT name, creation {sql} ORDER BY creation ASC, name ASC LIMIT %(limit)s", params
    )
    return [frappe._dict(name=name, creation=creation) for name, creation in rows]


_AFTER_CURSOR = (
    "(creation > %(cursor_creation)s OR (creation = %(cursor_creation)s AND name > %(cursor_name)s))"
)
_UP_TO_CURSOR = (
    "(creation < %(cursor_creation)s OR (creation = %(cursor_creation)s AND name <= %(cursor_name)s))"
)


def _next_batch(doctype, statuses, id_field, cancelled=False, limit=None):
    """The next ``limit`` (default BATCH_LIMIT) rows after the stored cursor, wrapping round to the head.

    A cursor in the cache rather than "oldest first" or ``modified asc``: oldest-first
    starved every row past the cap behind abandoned ones, and ``modified asc`` only
    rotates for doctypes that save on every refresh (Links do, Requests only on a
    change). The cursor writes nothing to the rows (no schema field, no Version row)
    and is applied in SQL, so there is no fixed listing cap. A lost cache just restarts
    the rotation.
    """
    limit = limit or BATCH_LIMIT
    cursor = frappe.cache().get_value(_cursor_cache_key(doctype, cancelled))
    if not cursor:
        return _open_rows_page(doctype, statuses, id_field, None, None, limit, cancelled)
    after = _open_rows_page(doctype, statuses, id_field, _AFTER_CURSOR, cursor, limit, cancelled)
    if len(after) >= limit:
        return after
    head = _open_rows_page(doctype, statuses, id_field, _UP_TO_CURSOR, cursor, limit - len(after), cancelled)
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


def _refresh_batches(plan):
    """``plan`` is a list of ``(doctype, cancelled, rows)``, run in order."""
    deadline = _monotonic() + RUN_BUDGET_SECONDS
    consecutive_outages = attempted = 0
    last_attempted = {}
    stop_reason = None
    for doctype, cancelled, rows in plan:
        for row in rows:
            if consecutive_outages >= MAX_CONSECUTIVE_OUTAGE_FAILURES:
                stop_reason = f"{consecutive_outages} consecutive Ponto outage-type failures"
            elif _monotonic() >= deadline:
                stop_reason = f"the {RUN_BUDGET_SECONDS} s run budget was used up"
            if stop_reason:
                break
            last_attempted[(doctype, cancelled)] = row
            attempted += 1
            outcome = _refresh_one(doctype, row.name, cancelled=cancelled)
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
    for (doctype, cancelled), row in last_attempted.items():
        frappe.cache().set_value(_cursor_cache_key(doctype, cancelled), row)
    if stop_reason:
        total = sum(len(rows) for _doctype, _cancelled, rows in plan)
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

    Classified on exception CLASSES, never message text, and from the ROOT CAUSE outward:
    the first decisive exception wins. The client wrappers (``get_payment``,
    ``get_payment_request``) catch everything and re-raise a fresh ``PontoAPIError`` WITHOUT
    ``status_code`` (#1924), so the outermost exception always looks status-less; only the
    root still says 404 or 503. This stays correct whether or not #1924 is ever fixed.

    * outage: ``PontoRateLimitError`` (429), ``PontoAuthenticationError`` (401, the token is
      shared by every row; maintainer ruling), ``requests.RequestException`` (transport, and
      also a body that is not JSON, ``InvalidJSONError``: a proxy or maintenance page is an
      incident shape, from the API or the token endpoint alike; coordinator decision, and
      three consecutive ones are needed to stop a run), ``ConnectionError``/``TimeoutError``,
      and a ``PontoAPIError`` with status >= 500;
    * data: a ``PontoAPIError`` with a lower status (404, 400, 422 ...) and anything
      unrecognised, including a status-less ``PontoAPIError`` with nothing deeper (a parse
      failure such as "Missing 'id'").

    Root-first matters: a handler that re-raises a different error while handling the first
    (the usual wrapper shape) leaves the root as the only honest witness.
    """
    for e in reversed(list(_causes(exc))):
        if isinstance(e, (PontoRateLimitError, PontoAuthenticationError, requests.RequestException)):
            return True
        if isinstance(e, (ConnectionError, TimeoutError)):
            return True
        if isinstance(e, PontoAPIError) and e.status_code is not None:
            return e.status_code >= 500
    return False


def _is_not_found(exc):
    """True when the root cause is a Ponto 404. Root-first, like ``_is_outage``: the client
    wrappers re-raise a status-less ``PontoAPIError``, so only the root still knows the status."""
    for e in reversed(list(_causes(exc))):
        if isinstance(e, PontoAPIError) and e.status_code is not None:
            return e.status_code == 404
    return False


OK, OUTAGE, DATA_ERROR, GONE = "ok", "outage", "data_error", "gone"


def _ponto_status_of(doc):
    """(Ponto's local-mapped status, Ponto id) for ``doc``, READ ONLY: one GET through the same
    client ``refresh_status`` builds, then the same shared map. Nothing is written."""
    if doc.doctype == "Ponto Payment Request":
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import get_payment_client

        payment = get_payment_client().get_payment(
            account_id=doc.ponto_account, payment_id=doc.ponto_payment_id
        )
        return map_request_status(payment.status), doc.ponto_payment_id
    from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
        get_betaalverzoek_client,
    )

    request = get_betaalverzoek_client().get_payment_request(doc.ponto_request_id)
    return map_link_status((request.status or "").lower()), doc.ponto_request_id


# Per run. No Ponto call is made, so there is no wall-clock concern; the cap only bounds the work.
OWED_ALERT_RETRY_LIMIT = 50


def _retry_owed_alerts():
    """#1931 (ruling 2026-11-01): an executed-on-cancelled-row alert keeps being sent until it is
    delivered, however old the row. The cancelled pass above stops checking a row when it leaves
    its window; this does not depend on the window. Ponto is NOT asked again: "executed" is
    already known and recorded as an OWED marker on the row (``submitted_rows.owed_alerts``)."""
    id_fields = {doctype: id_field for doctype, _statuses, id_field in _POLLED}
    for owed in owed_alerts(OWED_ALERT_RETRY_LIMIT):
        savepoint = f"ponto_owed_{frappe.generate_hash(length=10)}"
        frappe.db.savepoint(savepoint)
        try:
            doc = frappe.get_doc(owed.doctype, owed.name)
            alert_executed_on_cancelled_row(doc, doc.get(id_fields[owed.doctype]))
            mark_retried(owed.comment)
        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as e:
            rollback_to_savepoint(savepoint)
            frappe.log_error(
                title=f"Ponto owed alert retry failed: {owed.doctype} {owed.name}",
                message=f"{type(e).__name__}: {e}",
            )
        else:
            release_savepoint_if_present(savepoint)


def _check_cancelled_one(doctype, name):
    """#1931: ask Ponto about a CANCELLED row and alert (#1848) only if it was paid.

    Never ``refresh_status``: that would save the cancelled document on any other status, and
    ``self.save()`` at the end of the Link's. The only write is the alert's own Notification Log
    and Error Log rows; the row itself is read, never changed. ``closed`` (the Link client's
    marker, #1840) is unmapped and so never counts as executed here either. The selection is a
    SELECT, not a lock, but the alert itself refuses a row that is not (or no longer) cancelled.
    """
    doc = frappe.get_doc(doctype, name)
    mapped, ponto_id = _ponto_status_of(doc)
    if mapped == "Executed":
        alert_executed_on_cancelled_row(doc, ponto_id)


def _refresh_one(doctype, name, cancelled=False):
    """Refresh one row (or, for a cancelled row, only check it) in its own savepoint.
    Returns OK, OUTAGE, DATA_ERROR or GONE (Ponto 404 on a cancelled row)."""
    savepoint = f"ponto_poll_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        if cancelled:
            _check_cancelled_one(doctype, name)
        else:
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
        if cancelled and _is_not_found(e):
            # Expected, not a fault: cancelling a Pending row deletes the payment at Ponto, so
            # Ponto no longer knows it. A 404 on a cancelled SIGNED row (not deleted at Ponto,
            # so it should still exist) is abnormal but silenced the same way, by design: the
            # poll cannot tell the two apart from the row alone. Nothing to alert about (a payment that is gone cannot
            # have executed), and no Error Log row every hour until the row ages out of the window.
            return GONE
        frappe.log_error(
            title=f"Ponto status poll failed: {doctype} {name}", message=f"{type(e).__name__}: {e}"
        )
        return OUTAGE if _is_outage(e) else DATA_ERROR
    release_savepoint_if_present(savepoint)
    return OK
