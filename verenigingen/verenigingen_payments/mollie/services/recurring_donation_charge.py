"""Turn a Mollie subscription charge into a Donation of its own.

Mollie charges a recurring donor every period and posts the subscription's
webhookUrl with a NEW payment id. The webhook resolved donations by
``Donation.payment_id``, which holds the FIRST payment's id, so no charge after
the first matched anything: no Bank Transaction, no Journal Entry, no record.
Issue #345.

This module creates a document and nothing else. Once the charge has a Donation
carrying ``payment_id = <charge id>``, the existing webhook pipeline books it --
financial entries, payment history, donor history, refunds and chargebacks --
with no changes at all. That is the whole reason a charge gets its own Donation
rather than a payment row on the original.

Measured against the Mollie API: a subscription-generated charge carries
``sequenceType: "recurring"``, ``subscriptionId``, ``customerId``, ``mandateId``,
``method: "directdebit"``, and the subscription's metadata copied verbatim --
where ``metadata.payment_id`` is the FIRST payment's id, not the charge's.
Charges are created ``pending`` and settle days later.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from ..utils.common_helpers import read_payment_field
from .handlers.donation_lookup import DonationLookup

# Mollie's method for a subscription charge, mapped to a Mode of Payment that
# exists. Copying the origin's method would misreport the charge: the donor
# signed up with iDEAL or a card, but the recurring charge is always a debit.
_METHOD_TO_MODE_OF_PAYMENT = {"directdebit": "SEPA Direct Debit"}

# Copied from the origin donation onto every charge. Designation and ANBI facts
# belong to the standing arrangement, not to one period's payment.
_INHERITED_FIELDS = (
    "donor",
    "donor_email",
    "donation_purpose_type",
    "campaign",
    "chapter_reference",
    "specific_goal_description",
    "fund_designation",
    # Read by donation_history_manager._update_entry_fields / _build_entry_dict,
    # which copy it into the donor's history entry. Left out, every charge shows
    # a blank purpose beside an origin that has one.
    "donation_purpose",
    # Load-bearing, not cosmetic: validate_donation_purpose accepts
    # purpose_type "Campaign" without a campaign link only when "Campaign:"
    # appears here.
    "donation_notes",
    "anbi_agreement_number",
    "anbi_agreement_date",
    "belastingdienst_reportable",
    "recurring_frequency",
)

_UNBOOKABLE_STATUSES = ("failed", "expired", "canceled")


class RecurringChargeOriginMissing(frappe.ValidationError):
    """No donation could be found for a charge's subscription.

    Raised rather than returned so the webhook fails and Mollie re-delivers: a
    charge we cannot attribute is money we have received and not recorded, and
    it must not be swallowed into a 200.
    """


def ensure_donation_for_recurring_charge(payment: Any) -> Optional[str]:
    """Return the Donation for this subscription charge, creating it if needed.

    Returns None when the payment is not a bookable recurring charge -- a first
    payment, a payment with no subscription, or a charge that has not been paid.
    Raises RecurringChargeOriginMissing when it is one but cannot be attributed.
    """
    if read_payment_field(payment, "sequence_type", "sequenceType") != "recurring":
        return None

    subscription_id = read_payment_field(payment, "subscription_id", "subscriptionId")
    if not subscription_id:
        return None

    payment_id = read_payment_field(payment, "id")
    status = read_payment_field(payment, "status")
    if status != "paid":
        if status in _UNBOOKABLE_STATUSES:
            _audit(
                payment_id,
                "recurring_charge_not_paid",
                f"Charge on subscription {subscription_id} arrived '{status}' and was not booked",
                {"subscription_id": subscription_id, "charge_status": status},
                severity="warning",
            )
        return None

    existing = _donation_for_charge(payment_id)
    if existing:
        # Not an unconditional short-circuit: a link that failed on an earlier
        # delivery is repaired here or never. See _repair_agreement_link.
        _repair_agreement_link(existing, payment_id)
        return existing

    origin = DonationLookup().find_for_subscription_payment(payment_id, payment=payment)
    if not origin:
        _audit(
            payment_id,
            "recurring_charge_origin_missing_error",
            f"No donation found for subscription {subscription_id}; charge not booked",
            {"subscription_id": subscription_id},
            severity="error",
        )
        raise RecurringChargeOriginMissing(
            _("No donation found for Mollie subscription {0}").format(subscription_id)
        )

    return _insert_charge_donation(payment, origin, payment_id, subscription_id)


def _donation_for_charge(payment_id: str) -> Optional[str]:
    """The pre-insert existence check: has this charge already been booked?"""
    return frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")


def _repair_agreement_link(charge_name: str, payment_id: str) -> None:
    """Re-attempt an agreement link that failed on an earlier delivery.

    ``_link_to_agreement`` records a failure rather than raising -- correctly,
    since the money is already booked. But the charge Donation exists by then,
    so every redelivery finds it and returns, and one transient failure (the
    webhook user lacking write, a deadlock, a rate limit) would leave the
    agreement's ``total_donated`` permanently short with only an audit row.
    ``total_donated`` staying correct is the entire reason a charge gets its own
    Donation instead of a payment child row, so the repair belongs on the path
    Mollie already re-drives.

    Only runs when the charge carries no agreement while its origin does, so an
    ordinary redelivery still short-circuits. ``add_donation_link`` throws
    "Donation is already linked" on a charge that IS in the child table, which
    would be recorded as a link error -- hence the narrow condition rather than
    relying on that throw.
    """
    charge = frappe.db.get_value(
        "Donation",
        charge_name,
        ["periodic_donation_agreement", "recurring_origin_donation"],
        as_dict=True,
    )
    if not charge or charge.periodic_donation_agreement or not charge.recurring_origin_donation:
        return

    origin = frappe.db.get_value(
        "Donation", charge.recurring_origin_donation, ["name", "periodic_donation_agreement"], as_dict=True
    )
    if not origin or not origin.periodic_donation_agreement:
        return

    _link_to_agreement(charge_name, origin, payment_id)


def _insert_charge_donation(payment, origin, payment_id: str, subscription_id: str) -> str:
    charge = frappe.new_doc("Donation")
    charge.update(_charge_values(payment, origin, payment_id, subscription_id))

    try:
        # Runs from the Mollie webhook, authenticated before this is reached.
        # NOT as Guest -- webhook_security.py:93 calls
        # frappe.set_user(webhook_user), so this executes as the configured
        # service user (see add_donation_link's docstring, which relies on the
        # same fact). Every field written here comes from the verified payment
        # or from the origin donation, never from a request body.
        #
        # Security: ignore_permissions because nothing guarantees that service
        # user holds Donation:create, and refusing to record a charge Mollie
        # has already collected is the failure this issue is about.
        charge.insert(ignore_permissions=True)
    except Exception as e:
        # The unique constraint on payment_id is the real concurrency guard, which
        # is why no lock is taken: another worker inserting between the check
        # above and this line is a duplicate-key error, not a duplicate donation.
        #
        # frappe.db.is_duplicate_entry() alone is NOT enough here, measured
        # against a real 1062: base_document.db_insert() catches the driver's
        # IntegrityError and re-raises frappe.UniqueValidationError(doctype,
        # name, original), whose args[0] is the doctype string -- so
        # is_duplicate_entry() returns False for everything Document.insert()
        # can raise. Both are checked so this survives either layer changing.
        if not (isinstance(e, frappe.UniqueValidationError) or frappe.db.is_duplicate_entry(e)):
            raise
        # Read the winner directly rather than through _donation_for_charge().
        # This is the post-failure read and it has to stay independent of the
        # pre-insert check -- the race test disables that check to hold the
        # window open, and an adoption that went through it would be disabled
        # along with it and prove nothing.
        winner = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
        if not winner:
            raise
        frappe.logger().info(f"Charge {payment_id} was booked concurrently as {winner}; adopting it")
        return winner

    _link_to_agreement(charge.name, origin, payment_id)

    frappe.logger().info(
        f"Created donation {charge.name} for recurring charge {payment_id} "
        f"on subscription {subscription_id}"
    )
    return charge.name


def _charge_values(payment, origin, payment_id: str, subscription_id: str) -> Dict[str, Any]:
    amount = read_payment_field(payment, "amount") or {}
    values = {
        "payment_id": payment_id,
        "recurring_origin_donation": origin.name,
        "mollie_subscription_id": subscription_id,
        "mollie_customer_id": read_payment_field(payment, "customer_id", "customerId"),
        "mollie_mandate_id": read_payment_field(payment, "mandate_id", "mandateId"),
        "amount": frappe.utils.flt(amount.get("value")),
        "donation_date": frappe.utils.getdate(
            read_payment_field(payment, "paid_at", "paidAt")
            or read_payment_field(payment, "created_at", "createdAt")
        ),
        "paid": 1,
        "status": "Recurring",
        "mode_of_payment": _mode_of_payment(payment, origin, payment_id),
    }
    for fieldname in _INHERITED_FIELDS:
        values[fieldname] = origin.get(fieldname)

    # periodic_donation_agreement is deliberately NOT set here.
    # add_donation_link() sets it, and doing it that way is what keeps the
    # agreement's total_donated correct -- see _link_to_agreement.
    return values


def _link_to_agreement(charge_name: str, origin, payment_id: str) -> None:
    """Register the charge with the origin's periodic agreement, if it has one.

    This call is load-bearing, not bookkeeping. ``update_donation_tracking``
    sums the agreement's ``donations`` child table, and appending to that table
    is the only thing that moves it -- setting
    ``Donation.periodic_donation_agreement`` directly does not. Without this
    call the agreement's ``total_donated`` stays at whatever it was, and
    Donation-per-charge buys nothing over a payment child row.

    ``add_donation_link``, not ``link_donation``: the whitelisted spelling
    carries ``@high_security_api(FINANCIAL)``, whose Critical Operation Rule
    caps it at 100 calls / 3600s ``per_user``. A billing run of more than 100
    charges in an hour arrives here as one service user and would start being
    refused partway through -- silently, because the except below records
    rather than raises. See ``add_donation_link``'s docstring.

    Never fatal. The money is already booked by the time this runs; a linkage
    problem is reported, not thrown.
    """
    agreement = origin.get("periodic_donation_agreement")
    if not agreement:
        return

    # link_donation() itself does not check the agreement's status, and it sets
    # the link with db_set(), which skips Donation.validate() -- measured: it
    # links a Cancelled agreement without complaint. The damage is deferred, not
    # avoided: validate_periodic_donation_agreement() throws "Cannot link
    # donation to {status} agreement" on every LATER save of that donation, and
    # the booking pipeline saves it. A donor who cancels the agreement while the
    # Mollie subscription keeps charging would then turn every subsequent charge
    # into a hard failure -- Mollie retries, charge unbooked, which is the exact
    # state this issue exists to prevent. So the status is checked here instead.
    status = frappe.db.get_value("Periodic Donation Agreement", agreement, "status")
    if status not in ("Active", "Completed"):
        _audit(
            payment_id,
            "recurring_charge_agreement_inactive",
            f"Agreement {agreement} is '{status}'; charge booked without the link",
            {"agreement": agreement, "agreement_status": status},
            severity="warning",
        )
        return

    try:
        frappe.get_doc("Periodic Donation Agreement", agreement).add_donation_link(charge_name)
    except Exception as e:
        _audit(
            payment_id,
            "recurring_charge_agreement_link_error",
            f"Charge booked as {charge_name} but linking it to agreement {agreement} failed: {e}",
            {"agreement": agreement, "donation": charge_name},
            severity="error",
        )


def _mode_of_payment(payment, origin, payment_id: str) -> str:
    """A Mode of Payment that exists, for a Donation field that is mandatory."""
    method = read_payment_field(payment, "method")
    mapped = _METHOD_TO_MODE_OF_PAYMENT.get(method)
    if mapped and frappe.db.exists("Mode of Payment", mapped):
        return mapped

    # Both routes here mislabel the charge: it gets recorded with the mode the
    # donor first paid by -- iDEAL, a card -- rather than the mode Mollie
    # actually charged. Booking anyway beats refusing money already collected,
    # but doing it silently on every charge is how the mislabelling survives.
    #
    # The unmapped route is the likelier of the two and used to be the silent
    # one: a card mandate charges `creditcard`, not `directdebit`, so it never
    # reaches the mapping at all.
    fallback = origin.get("mode_of_payment")
    reason = (
        f"Mode of Payment '{mapped}' does not exist on this site"
        if mapped
        else f"Mollie method '{method}' has no Mode of Payment mapping"
    )
    _audit(
        payment_id,
        "recurring_charge_mode_of_payment_missing",
        f"{reason}; charge labelled '{fallback}' from the origin",
        {"mollie_method": method, "expected_mode_of_payment": mapped, "used": fallback},
        severity="warning",
    )
    # Deliberately not donation.create_mode_of_payment(), which would insert a
    # Mode of Payment literally named "directdebit" as a side effect of a webhook.
    return fallback


def _audit(payment_id, event_type, description, details, severity="info"):
    """Record on the Mollie Audit Log; never let logging break the booking."""
    try:
        from ..utils.audit import MollieAuditLogger

        MollieAuditLogger()._create_audit_log(
            event_type=event_type,
            event_category="webhook_processing",
            description=f"[{payment_id}] {description}",
            data={"payment_id": payment_id, **details},
            severity=severity,
        )
    except Exception as e:
        # .error(), not .warning(): a bare logger's level is ERROR under
        # bench run-tests, so a warning here would be discarded entirely.
        frappe.logger().error(f"Failed to write Mollie audit log for {payment_id}: {e}")
