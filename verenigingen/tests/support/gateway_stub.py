# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Shared payment-gateway stub for ownership-regression tests.

Used by tests/backend/portal/test_page_mollie_checkout.py (#1032, PR #1047)
and tests/payment/test_initiate_payment_ownership.py (#1048): both patch
PaymentGatewayFactory.get_gateway with a stub that would report a
real-looking redirect if reached, so that a refused call succeeding would be
caught immediately rather than looking like a stubbed success. Extracted
here after the second copy tripped
scripts/validation/duplicate_helper_validator.py's ratchet.
"""

from unittest.mock import MagicMock


def stub_redirect_gateway(
    *,
    payment_url: str = "https://pay.example.test/checkout/xyz",
    payment_id: str = "tr_stubbed",
) -> MagicMock:
    """A gateway stub that would report a real-looking redirect if reached."""
    gateway = MagicMock()
    gateway.process_payment.return_value = {
        "status": "redirect_required",
        "payment_url": payment_url,
        "payment_id": payment_id,
    }
    return gateway
