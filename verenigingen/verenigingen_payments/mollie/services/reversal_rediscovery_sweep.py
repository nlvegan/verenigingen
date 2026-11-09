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

from typing import Any, Dict, Iterator, List

import frappe

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
        payment_ids = _payments_with_unbooked_reversals(MollieClient().sdk_client, summary)
    except Exception as e:
        summary["errors"].append({"error": f"could not list reversals at Mollie: {e}"})
        payment_ids = []

    wrapper = UnifiedWebhookWrapperService()
    manager = UnifiedIdempotencyManager()
    for payment_id in payment_ids:
        summary["payments_checked"] += 1
        try:
            _book_for_payment(payment_id, wrapper, manager, summary)
        except Exception as e:
            summary["errors"].append({"payment_id": payment_id, "error": str(e)})

    if summary["errors"]:
        frappe.log_error(
            title="Mollie reversal rediscovery sweep: problem(s)",
            message=f"{len(summary['errors'])} problem(s): {summary['errors']}",
        )

    return summary


def _payments_with_unbooked_reversals(sdk_client: Any, summary: Dict[str, Any]) -> List[str]:
    """Payment ids of ours with a paid-out refund or any chargeback not yet booked.

    Cheap, local pre-filter only (a key lookup per reversal): the authoritative
    decision is still the idempotency manager's, per payment, afterwards.
    """
    payment_ids: List[str] = []
    seen = set()

    candidates = [
        (reversal_type, reversal)
        for reversal_type, resource in (
            ("refund", sdk_client.refunds),
            ("chargeback", sdk_client.chargebacks),
        )
        for reversal in _iter_pages(resource)
    ]
    for reversal_type, reversal in candidates:
        # #1806: only a refund Mollie reports as paid out is bookable; the delivery
        # sent when a queued/pending/processing one changes status finds it later.
        if reversal_type == "refund" and read_payment_field(reversal, "status") != "refunded":
            continue

        payment_id = read_payment_field(reversal, "payment_id", "paymentId")
        reversal_id = read_payment_field(reversal, "id")
        if not payment_id or not reversal_id or payment_id in seen:
            continue
        if find_booked_reversal(build_reversal_key(payment_id, reversal_type, reversal_id)):
            continue
        if not find_booked_payment(payment_id):
            # Not a payment this site booked (or booked on another site sharing the
            # Mollie account): there is nothing to reverse here.
            summary["payments_not_ours"] += 1
            seen.add(payment_id)
            continue

        seen.add(payment_id)
        payment_ids.append(payment_id)

    return payment_ids


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
    wrapper: UnifiedWebhookWrapperService,
    manager: UnifiedIdempotencyManager,
    summary: Dict[str, Any],
) -> None:
    state = manager.check_payment_processing_state(payment_id, include_mollie_api=True)
    if state.refund_check_failed or state.chargeback_check_failed:
        summary["errors"].append({"payment_id": payment_id, "error": "Mollie refund/chargeback check failed"})
        return

    for outcome in wrapper.book_pending_reversals(payment_id, state):
        if outcome.get("status") == "success" and not outcome.get("idempotent"):
            summary["reversals_booked"] += 1
        elif outcome.get("status") not in ("success",):
            summary["errors"].append(
                {"payment_id": payment_id, "status": outcome.get("status"), "message": outcome.get("message")}
            )
