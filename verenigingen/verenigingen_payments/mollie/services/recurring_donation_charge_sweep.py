"""Recovery sweep for recurring donation charges Mollie never got a delivered
webhook for (issue #872, part B of #345).

Mollie retries a failing webhook delivery for up to 26 hours and then gives
up. Until this sweep existed, a charge no delivery ever reached had no
automatic path back to a booked Donation: `ensure_donation_for_recurring_charge`
(#345 part A) only runs from a delivered webhook. See the design doc's F5:
"no record today. Part B's sweep is the fix."

This module lists each active donation subscription's payments directly at
Mollie and books any charge that has no Donation yet, via
`DonationProcessor` -- the same pipeline
(`UnifiedWebhookWrapperService.process_payment_webhook`) a delivered webhook
uses. No booking logic is duplicated here.
"""

from typing import Any, Dict, List

import frappe

from ...services.journal_entry_booking_support import find_journal_entry_by_reference
from ..core.client import MollieClient
from ..utils.common_helpers import read_payment_field
from .donation_processor import DonationProcessor

# Mollie's own maximum page size for a list endpoint.
_PAYMENTS_PAGE_LIMIT = 250

# A donation subscription is NOT "at most monthly" -- Donation.recurring_frequency
# offers Daily/Weekly/Bi-weekly too, and convert_frequency_to_mollie_interval
# (mollie/utils/common_helpers.py) maps them to real Mollie intervals ("1 day",
# "1 week", "2 weeks") precisely because Daily/Weekly donations were found to be
# silently under-billed when treated as monthly. A Daily subscription reaches
# 250 charges in well under a year, so a single page is not a safe assumption.
#
# Mollie's List Subscription Payments endpoint returns newest-first and only
# this class's own page, with no auto-pagination -- confirmed against the
# installed mollie-api-python 4.0.0 (PaginationList.__iter__ walks only the
# current page's embedded data; has_next()/get_next() exist precisely because
# nothing else advances the scan). Reading one page and stopping is therefore
# a SLIDING WINDOW, not an advancing scan: a charge that ages past this many
# positions while unbooked would never be revisited by a later run, silently,
# forever -- the exact failure mode this sweep exists to close. So every page
# is followed via get_next(), bounded only by _MAX_PAGES_PER_SUBSCRIPTION
# below so one subscription with an unusually long history cannot stall the
# whole sweep.
_MAX_PAGES_PER_SUBSCRIPTION = 40


def sweep_recurring_donation_charges() -> Dict[str, Any]:
    """Scheduled entry point (see hooks/scheduler.py, "daily").

    Never raises: a subscription whose payments cannot be listed, or a charge
    that fails to book, is recorded in the summary and swept past, so one bad
    row cannot stop every other subscription from being checked.
    """
    summary = {
        "subscriptions_checked": 0,
        "charges_booked": 0,
        "charges_already_booked": 0,
        "charges_booking_cancelled": 0,
        "charges_not_paid": 0,
        "errors": [],
    }

    client = MollieClient()
    donation_processor = DonationProcessor()

    for origin in _active_donation_subscriptions():
        summary["subscriptions_checked"] += 1
        try:
            for payment in _iter_subscription_payments(client, origin):
                _sweep_one_payment(payment, donation_processor, summary)
        except Exception as e:
            summary["errors"].append(
                {
                    "donation": origin.name,
                    "subscription_id": origin.mollie_subscription_id,
                    "error": str(e),
                }
            )
            continue

    if summary["errors"]:
        # frappe.log_error, not frappe.logger(): a bare logger writes only to
        # logs/frappe.log, which nobody reads, and this sweep is the last line
        # of defence for money (#945).
        frappe.log_error(
            title="Recurring Donation Charge Sweep Problems",
            message=f"{len(summary['errors'])} problem(s) -- {summary['errors']}",
        )

    return summary


def _iter_subscription_payments(client: MollieClient, origin: Any):
    """Yield every payment for one subscription, following every `next` link.

    Mollie returns newest-first, so the FIRST page is exactly the payments
    most likely to still be within their booking window -- reading only it
    and stopping would silently and permanently drop any charge that ages
    past position _PAYMENTS_PAGE_LIMIT while unbooked. See the module-level
    comment on _MAX_PAGES_PER_SUBSCRIPTION.
    """
    page = client.get_subscription(origin.mollie_customer_id, origin.mollie_subscription_id).payments.list(
        limit=_PAYMENTS_PAGE_LIMIT
    )
    pages_read = 1
    while True:
        yield from page
        if not page.has_next() or pages_read >= _MAX_PAGES_PER_SUBSCRIPTION:
            break
        page = page.get_next()
        pages_read += 1


def _sweep_one_payment(payment: Any, donation_processor: DonationProcessor, summary: Dict[str, Any]) -> None:
    if read_payment_field(payment, "status") != "paid":
        summary["charges_not_paid"] += 1
        return

    payment_id = read_payment_field(payment, "id")
    # "Booked" means the charge reached the ledger, not that a Donation row
    # exists: ensure_donation_for_recurring_charge inserts the row BEFORE
    # booking runs, so a charge whose booking failed has a row and no Journal
    # Entry, and keying on the row skipped it forever (#945). A live entry
    # (draft included: work in flight) is the same key the booking itself uses
    # for idempotency, so a booked charge is never sent through again.
    if find_journal_entry_by_reference(payment_id):
        summary["charges_already_booked"] += 1
        return

    # A Journal Entry that exists only as docstatus 2 was cancelled -- by staff
    # undoing the booking, or by the creator discarding a submit that did not
    # post -- and the two cannot be told apart here. No ruling covers a
    # staff-cancelled donation booking, so leave it for staff rather than
    # re-book it automatically (cf. #2406 for forward Payment Entries).
    if frappe.db.exists("Journal Entry", {"cheque_no": payment_id}):
        summary["charges_booking_cancelled"] += 1
        return

    try:
        result = donation_processor.process_donation_payment(payment_id, payment)
    except Exception as e:
        summary["errors"].append({"payment_id": payment_id, "error": str(e)})
        return

    if result.get("status") == "success":
        summary["charges_booked"] += 1
    else:
        summary["errors"].append(
            {
                "payment_id": payment_id,
                "status": result.get("status"),
                "message": result.get("message"),
            }
        )


def _active_donation_subscriptions() -> List[Any]:
    """Origin donations still carrying a Mollie subscription.

    Only origins (`recurring_origin_donation` unset): a charge Donation
    carries the same `mollie_subscription_id` as its origin (see
    `_charge_values` in recurring_donation_charge.py), so without this filter
    every already-booked charge would resweep its own subscription again.
    Not filtered on `recurring_cancelled_date`: a charge that was paid before
    the donor cancelled can still be missing its Donation, and recovering
    that money does not depend on the subscription still being active today.
    """
    return frappe.get_all(
        "Donation",
        filters={
            "status": "Recurring",
            "mollie_subscription_id": ["is", "set"],
            "mollie_customer_id": ["is", "set"],
            "recurring_origin_donation": ["is", "not set"],
        },
        fields=["name", "mollie_subscription_id", "mollie_customer_id"],
    )
