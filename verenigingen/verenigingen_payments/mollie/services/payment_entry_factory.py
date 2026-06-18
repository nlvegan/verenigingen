"""
Generic Payment Entry Factory

DEPRECATED: This module has been moved to the shared services layer.
Import from verenigingen.verenigingen_payments.mollie.services.shared instead.

This file is kept for backward compatibility and re-exports from the new location.
"""

import warnings

from .payment_context_resolver import PaymentContext

# Re-export from shared location for backward compatibility
from .shared.cost_center_resolver import get_cost_center_for_context as _get_cost_center_for_context
from .shared.payment_entry_factory import PaymentEntryFactory as _SharedPaymentEntryFactory


def get_appropriate_cost_center_for_context(context: PaymentContext, company: str) -> str:
    """
    Get appropriate cost center based on payment context instead of random selection.

    DEPRECATED: Use verenigingen.verenigingen_payments.mollie.services.shared.get_cost_center_for_context instead.

    Args:
        context: PaymentContext with payment details
        company: Company name

    Returns:
        str: Cost center name
    """
    warnings.warn(
        "get_appropriate_cost_center_for_context is deprecated. "
        "Use verenigingen.verenigingen_payments.mollie.services.shared.get_cost_center_for_context instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_cost_center_for_context(context, company)


class PaymentEntryFactory(_SharedPaymentEntryFactory):
    """
    Generic factory for creating Payment Entries for any payment type.

    DEPRECATED: This class has been moved to the shared services layer.
    Import from verenigingen.verenigingen_payments.mollie.services.shared instead.

    This class inherits from the shared implementation for backward compatibility.
    """

    def __init__(self):
        warnings.warn(
            "PaymentEntryFactory from payment_entry_factory is deprecated. "
            "Use verenigingen.verenigingen_payments.mollie.services.shared.PaymentEntryFactory instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__()
