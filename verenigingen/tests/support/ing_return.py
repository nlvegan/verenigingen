"""Helpers for tests of the ING Checkout return page (#2038).

Only the Pay.nl HTTP client is stubbed (``get_client``). The page, its token check and the
internal status lookup all run for real, so a test cannot pass by replacing the very function
that used to refuse a Guest (the old tests patched ``get_payment_status`` itself).
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

_GET_CLIENT = "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client"


def ing_return_token(reference_doctype, reference_name):
    """The proof create_ideal_order mints into the return URL for this reference."""
    from verenigingen.verenigingen_payments.ing_checkout.api.payment import ING_RETURN_TOKEN_PURPOSE

    return generate_guest_return_token(ING_RETURN_TOKEN_PURPOSE, f"{reference_doctype}:{reference_name}")


@contextmanager
def stub_paynl_order_status(status_code, action="PAID"):
    """Pay.nl answers `get_order` with this status code. Yields the client mock."""
    client = MagicMock()
    client.get_order.return_value = {"status": {"code": status_code, "action": action}, "payments": []}
    with patch(_GET_CLIENT, return_value=client):
        yield client


_SETTINGS_PATH = (
    "verenigingen.verenigingen_payments.doctype.ing_checkout_settings."
    "ing_checkout_settings.get_ing_checkout_settings"
)


def create_ing_order(test_case, settings_return_url=None, explicit_return_url=None):
    """Run the real create_ideal_order against a stubbed Pay.nl client.

    Returns (reference ToDo name, the returnUrl handed to Pay.nl). Rows are tracked on `test_case`.
    """
    from verenigingen.verenigingen_payments.ing_checkout.api import payment

    client = MagicMock()
    order_id = f"EX-{frappe.generate_hash(length=4)}-5678-9012"
    client.create_order.return_value = {
        "id": order_id,
        "links": {"redirect": "https://connect.pay.nl/checkout/abc"},
    }
    settings = SimpleNamespace(default_return_url=settings_return_url, service_id="SL-1234-5678")
    doc = frappe.get_doc({"doctype": "ToDo", "description": "ing return url probe"}).insert()
    test_case.track_doc("ToDo", doc.name)
    with patch(_SETTINGS_PATH, return_value=settings), patch.object(payment, "get_client", return_value=client):
        payment.create_ideal_order("ToDo", doc.name, 10.0, "probe", explicit_return_url)
    txn = frappe.db.get_value("ING Checkout Transaction", {"transaction_id": order_id}, "name")
    if txn:
        test_case.track_doc("ING Checkout Transaction", txn)
    return doc.name, client.create_order.call_args[0][0]["returnUrl"]
