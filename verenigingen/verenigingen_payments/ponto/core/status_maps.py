# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto status -> local status maps, one per doctype (#1835).

Two code paths classify a Ponto status: polling (``refresh_status`` on the
doctype) and the webhook (``webhook_handlers``). They used to carry a private
copy of each map, and the copies drifted: the Request poll lacked ``cancelled``
and the Link poll lacked ``cancelled`` too, so a row Ponto had cancelled could
only ever be adopted through a webhook. Both paths now import these maps, so
they cannot disagree.

Every key is a status string that already appeared in this app as a Ponto
status: the webhook handler maps, the ``PaymentStatus`` fixture enum
(tests/fixtures/ponto_test_data_factory.py), or the doctype status-flow
docstrings. The set of statuses Ponto can actually return is NOT established
here. ``expired`` is mapped for both doctypes (maintainer ruling 2026-10-31;
the Payment Request gained an ``Expired`` Select option for it).

An unmapped status returns ``None`` and the caller keeps the current status.
"""

from typing import Optional

REQUEST_STATUS_MAP = {
    "pending": "Pending",
    "unsigned": "Pending",
    "signed": "Signed",
    "executed": "Executed",
    "rejected": "Rejected",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "expired": "Expired",
}

LINK_STATUS_MAP = {
    "pending": "Pending Authorization",
    "unsigned": "Pending Authorization",
    "signed": "Authorized",
    "authorized": "Authorized",
    "executed": "Executed",
    "rejected": "Rejected",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "expired": "Expired",
}

# Local statuses a live payment can still move away from, by what is guarded.
_FINAL = "Executed"
_NOT_YET_SIGNED = {"Draft", "Pending", "Pending Authorization"}
_CLOSED_WITHOUT_PAYMENT = {"Cancelled", "Rejected", "Failed", "Expired"}
_SIGNED = {"Signed", "Authorized"}


def map_request_status(ponto_status: Optional[str]) -> Optional[str]:
    """Local Ponto Payment Request status for a Ponto status, or None if unmapped."""
    return REQUEST_STATUS_MAP.get((ponto_status or "").lower())


def map_link_status(ponto_status: Optional[str]) -> Optional[str]:
    """Local Ponto Payment Link status for a Ponto status, or None if unmapped."""
    return LINK_STATUS_MAP.get((ponto_status or "").lower())


def is_refused_move(current: Optional[str], new: str) -> bool:
    """True when a poll or webhook must not move a row from ``current`` to ``new``.

    Maintainer rulings, 2026-10-31:

    * Executed is FINAL: it never moves to any other status.
    * Cancelled, Rejected, Failed and Expired may still move FORWARD (to
      Signed/Authorized or Executed), because the cancel is local and money may
      have moved at Ponto. They never move back to Draft, Pending or Pending
      Authorization: a late "pending" must not revive a row, which for a Link
      would make it payable again.
    * Signed/Authorized never move back to Pending/Pending Authorization.

    NOT guarded: Signed/Authorized -> Cancelled/Rejected/Failed/Expired, and moves
    between the closed statuses (e.g. Rejected -> Failed). Those are Ponto's word.
    """
    if current == _FINAL:
        return new != _FINAL
    if new in _NOT_YET_SIGNED:
        return current in _SIGNED or current in _CLOSED_WITHOUT_PAYMENT
    return False
