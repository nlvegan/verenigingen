"""Helpers for tests of the ING Checkout return page (#2038).

Only the Pay.nl HTTP client is stubbed (``get_client``). The page, its token check and the
internal status lookup all run for real, so a test cannot pass by replacing the very function
that used to refuse a Guest (the old tests patched ``get_payment_status`` itself).
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

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
