# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Backwards-compatibility shim for payments module.

The PaymentHook has been moved to verenigingen_payments.hooks.
This module re-exports for backwards compatibility.

DEPRECATED: Import from verenigingen.verenigingen_payments.hooks instead.
"""

# Re-export from new location
from verenigingen.verenigingen_payments.hooks import PaymentHook
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentAction

__all__ = ["PaymentHook", "PaymentAction"]
