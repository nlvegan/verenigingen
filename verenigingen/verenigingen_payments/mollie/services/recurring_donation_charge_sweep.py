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

from ..core.client import MollieClient
from ..utils.common_helpers import read_payment_field
from .donation_processor import DonationProcessor

# One page per subscription is enough at this scale: a donation subscription
# charges at most monthly, so 100 payments covers 8+ years of one
# subscription. The sweep runs on a schedule, so a subscription with more
# unswept history than that gets the rest on the next run rather than this
# one blocking on pagination.
_PAYMENTS_PAGE_LIMIT = 100


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
        "charges_not_paid": 0,
        "errors": [],
    }

    client = MollieClient()
    donation_processor = DonationProcessor()

    for origin in _active_donation_subscriptions():
        summary["subscriptions_checked"] += 1
        try:
            payments = client.get_subscription(
                origin.mollie_customer_id, origin.mollie_subscription_id
            ).payments.list(limit=_PAYMENTS_PAGE_LIMIT)
        except Exception as e:
            summary["errors"].append(
                {
                    "donation": origin.name,
                    "subscription_id": origin.mollie_subscription_id,
                    "error": str(e),
                }
            )
            continue

        for payment in payments:
            _sweep_one_payment(payment, donation_processor, summary)

    if summary["errors"]:
        frappe.logger().warning(
            f"Recurring donation charge sweep: {len(summary['errors'])} problem(s) -- {summary['errors']}"
        )

    return summary


def _sweep_one_payment(payment: Any, donation_processor: DonationProcessor, summary: Dict[str, Any]) -> None:
    if read_payment_field(payment, "status") != "paid":
        summary["charges_not_paid"] += 1
        return

    payment_id = read_payment_field(payment, "id")
    if frappe.db.exists("Donation", {"payment_id": payment_id}):
        summary["charges_already_booked"] += 1
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
