"""
Payment Processing Module for E-Boekhouden Integration

This module handles all payment-related imports from E-Boekhouden, including:
- Payment Entry creation for customer and supplier payments (mutation types 3 & 4)
- Bank account determination from ledger mappings
- Multi-invoice payment reconciliation
- Money transfers (mutation types 5 & 6) - future enhancement
"""

from .payment_entry_handler import PaymentEntryHandler

__all__ = ["PaymentEntryHandler"]

# Version info for tracking changes
__version__ = "1.0.0"
__author__ = "E-Boekhouden Integration Team"
