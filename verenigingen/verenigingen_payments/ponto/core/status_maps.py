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
here. In particular ``expired`` is mapped for the Link only: the Payment
Request doctype has no ``Expired`` Select option, and adding one is a product
decision.

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

# Position in the forward chain of a payment that is still alive. A late or
# duplicated event/poll that says "pending" must not move a Signed or Executed
# row back. Rejected, Failed, Cancelled and Expired are deliberately NOT ranked:
# a request cancelled locally can still be paid at Ponto (the callback cancel is
# local only), so Executed must stay reachable from them.
_FORWARD_RANK = {
    "Draft": 0,
    "Pending": 1,
    "Pending Authorization": 1,
    "Signed": 2,
    "Authorized": 2,
    "Executed": 3,
}


def map_request_status(ponto_status: Optional[str]) -> Optional[str]:
    """Local Ponto Payment Request status for a Ponto status, or None if unmapped."""
    return REQUEST_STATUS_MAP.get((ponto_status or "").lower())


def map_link_status(ponto_status: Optional[str]) -> Optional[str]:
    """Local Ponto Payment Link status for a Ponto status, or None if unmapped."""
    return LINK_STATUS_MAP.get((ponto_status or "").lower())


def is_backward_move(current: Optional[str], new: str) -> bool:
    """True when ``new`` would move a live payment backwards along the forward chain."""
    if current not in _FORWARD_RANK or new not in _FORWARD_RANK:
        return False
    return _FORWARD_RANK[new] < _FORWARD_RANK[current]
