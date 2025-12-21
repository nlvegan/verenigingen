# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Payment hooks module - Universal payment integration for Verenigingen.

This module provides a unified interface for payment processing across
different forms (donations, memberships, events) using the PaymentHook
service pattern.
"""

from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook

__all__ = ["PaymentHook"]
