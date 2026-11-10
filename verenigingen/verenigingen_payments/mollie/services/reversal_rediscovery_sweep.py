"""Recovery sweep for Mollie refunds and chargebacks no delivered webhook booked (#2140).

Refund and chargeback discovery (``UnifiedIdempotencyManager``) only ran inside a
payment-webhook delivery. Since #1806 a refund is booked only once Mollie reports it
``refunded``, so if the delivery carrying that status is lost (Mollie gives up after
about 26 hours) nothing ever looked at the payment again.

This sweep lists the account's refunds and chargebacks at Mollie, and for every
payment of ours that has a reversal not yet booked it runs the SAME discovery
(``check_payment_processing_state``) and the SAME booking
(``UnifiedWebhookWrapperService.book_pending_reversals`` ->
``process_reversal_webhook``) a delivered webhook uses. No booking logic lives here;
exactly-once rests on ``process_reversal_webhook``'s per-reversal key.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

import frappe

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    rollback_to_savepoint,
)
from verenigingen.verenigingen_payments.core.resilience.job_timeout import reraise_if_job_timeout

from ..core.client import MollieClient
from ..utils.common_helpers import read_payment_field
from ..utils.reversal_idempotency import build_reversal_key, find_booked_payment, find_booked_reversal
from .unified_idempotency_manager import UnifiedIdempotencyManager
from .webhook_wrapper_service_unified import UnifiedWebhookWrapperService

# Mollie's own maximum page size for a list endpoint.
_PAGE_LIMIT = 250

# The account-level lists are newest-first with no auto-pagination (same SDK
# behaviour recurring_donation_charge_sweep documents), so every page is followed
# via get_next(). Bounded so an account with a very long history cannot stall the
# job; 20 pages is 5000 of the most recent reversals, far past the 26 hour window
# this sweep exists to cover.
_MAX_PAGES = 20

# Only reversals Mollie created within this many days are considered. The issue is
# about deliveries lost inside Mollie's ~26 hour retry window, so a week is generous.
# Anything older was either already seen by a delivery or settled some other way
# (staff booking it by hand, a credit note): booking those on the first run would
# restore an invoice's outstanding amount a second time. Deliberately a constant, not
# a setting. The list is newest-first, so paging stops at the first older item.
_LOOKBACK_DAYS = 7

# Candidate payments handled per run; the rest drain on later runs. Keeps the job
# inside the default queue's 300 s timeout.
_MAX_PAYMENTS_PER_RUN = 100


def sweep_missed_reversals() -> Dict[str, Any]:
    """Scheduled entry point (see hooks/scheduler.py, "daily").

    Never raises: a payment that cannot be checked or booked is recorded in the
    summary and swept past, so one bad payment cannot stop the others.
    """
    summary = {
        "payments_checked": 0,
        "reversals_booked": 0,
        "payments_not_ours": 0,
        "errors": [],
    }

    try:
        wanted = _payments_with_unbooked_reversals(MollieClient().sdk_client, summary)
    except Exception as e:
        reraise_if_job_timeout(e)
        summary["errors"].append({"error": f"could not list reversals at Mollie: {e}"})
        wanted = {}

    wrapper = UnifiedWebhookWrapperService()
    manager = UnifiedIdempotencyManager()
    for payment_id, reversal_ids in wanted.items():
        summary["payments_checked"] += 1
        savepoint = f"reversal_sweep_{summary['payments_checked']}"
        frappe.db.savepoint(savepoint)
        try:
            # No release_savepoint on success: the booking path commits internally
            # (reconcile_bank_transaction_with_journal_entry), and a commit destroys
            # every savepoint, so releasing it raises 1305 on a healthy booking.
            _book_for_payment(payment_id, reversal_ids, wrapper, manager, summary)
        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as e:
            # A job timeout must end the job, not be recorded as one more failure (#1919).
            # Limit: a JobTimeoutException or 1213 deadlock raised INSIDE a booking never
            # gets here, because process_reversal_webhook's own blanket ``except Exception``
            # (webhook_wrapper_service_unified.py ~2150) swallows it first. That is a
            # pre-existing shared-path limit tracked on #2235. This re-raise covers the
            # listing and the state check (the long Mollie HTTP calls); the
            # NON_RESUMABLE_DB_ERRORS clause above is untested for the same reason.
            reraise_if_job_timeout(e)
            _undo_partial_writes(savepoint)
            summary["errors"].append({"payment_id": payment_id, "error": str(e)})

    if summary["errors"]:
        frappe.log_error(
            title="Mollie reversal rediscovery sweep: problem(s)",
            message=f"{len(summary['errors'])} problem(s): {summary['errors']}",
        )

    return summary


def _undo_partial_writes(savepoint: str) -> None:
    """Drop what a failed payment wrote, so the job's final commit does not keep it.

    A savepoint is enough unless the payment's own booking committed (which destroys it);
    then everything since that commit is the failed payment's uncommitted tail, and a
    full rollback discards exactly that. Safe because a reversal that did not commit is
    not booked, and the next run rediscovers it through the same key.

    The full ``frappe.db.rollback()`` fallback is DEFENSIVE. It is reachable only if the
    sweep's own code raises after a booking commit, because ``process_reversal_webhook``
    swallows its own errors. A commit by the failing payment also persists earlier
    payments' writes, so the full rollback discards only the failed payment's
    post-commit tail (measured by the round-2 reviewer).
    """
    if not rollback_to_savepoint(savepoint):
        frappe.db.rollback()


def _payments_with_unbooked_reversals(sdk_client: Any, summary: Dict[str, Any]) -> Dict[str, set]:
    """``{payment_id: {reversal ids}}`` of ours with a paid-out refund or any chargeback not yet booked.

    Cheap, local pre-filter only (a key lookup per reversal): the authoritative
    decision is still the idempotency manager's, per payment, afterwards.
    """
    wanted: Dict[str, set] = {}
    seen = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)

    for reversal_type, resource in (("refund", sdk_client.refunds), ("chargeback", sdk_client.chargebacks)):
        for reversal in _iter_recent(resource, cutoff):
            # #1806: only a refund Mollie reports as paid out is bookable; the delivery
            # sent when a queued/pending/processing one changes status finds it later.
            if reversal_type == "refund" and read_payment_field(reversal, "status") != "refunded":
                continue

            payment_id = read_payment_field(reversal, "payment_id", "paymentId")
            reversal_id = read_payment_field(reversal, "id")
            if not payment_id or not reversal_id:
                continue
            if find_booked_reversal(build_reversal_key(payment_id, reversal_type, reversal_id)):
                continue
            if payment_id not in seen:
                seen.add(payment_id)
                if not find_booked_payment(payment_id):
                    # Not a payment this site booked (or booked on another site sharing the
                    # Mollie account): there is nothing to reverse here.
                    summary["payments_not_ours"] += 1
                    continue
                if len(wanted) >= _MAX_PAYMENTS_PER_RUN:
                    return wanted
                wanted[payment_id] = set()
            if payment_id in wanted:
                wanted[payment_id].add(reversal_id)

    return wanted


def _created_at(reversal: Any) -> Optional[datetime]:
    raw = read_payment_field(reversal, "created_at", "createdAt")
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return created if created.tzinfo else created.replace(tzinfo=timezone.utc)


def _iter_recent(resource: Any, cutoff: datetime) -> Iterator[Any]:
    """Yield reversals created at or after ``cutoff``, stopping at the first older one.

    The lists are newest-first. An item with no readable createdAt cannot be shown to
    be recent, so it is skipped (not booked) rather than ending the scan.
    """
    for reversal in _iter_pages(resource):
        created = _created_at(reversal)
        if created is None:
            continue
        if created < cutoff:
            return
        yield reversal


def _iter_pages(resource: Any) -> Iterator[Any]:
    page = resource.list(limit=_PAGE_LIMIT)
    pages_read = 1
    while True:
        yield from page
        if not page.has_next() or pages_read >= _MAX_PAGES:
            break
        page = page.get_next()
        pages_read += 1


def _book_for_payment(
    payment_id: str,
    reversal_ids: set,
    wrapper: UnifiedWebhookWrapperService,
    manager: UnifiedIdempotencyManager,
    summary: Dict[str, Any],
) -> None:
    state = manager.check_payment_processing_state(payment_id, include_mollie_api=True)
    if state.refund_check_failed or state.chargeback_check_failed:
        summary["errors"].append({"payment_id": payment_id, "error": "Mollie refund/chargeback check failed"})
        return

    # The manager reports EVERY unbooked reversal of the payment, including ones older than
    # the lookback (possibly settled by hand). Book only what the lookback selected.
    state.pending_refunds = [r for r in state.pending_refunds if r["refund_id"] in reversal_ids]
    state.pending_chargebacks = [c for c in state.pending_chargebacks if c["chargeback_id"] in reversal_ids]

    for outcome in wrapper.book_pending_reversals(payment_id, state):
        if outcome.get("status") == "success" and not outcome.get("idempotent"):
            summary["reversals_booked"] += 1
        elif outcome.get("status") not in ("success",):
            summary["errors"].append(
                {"payment_id": payment_id, "status": outcome.get("status"), "message": outcome.get("message")}
            )
