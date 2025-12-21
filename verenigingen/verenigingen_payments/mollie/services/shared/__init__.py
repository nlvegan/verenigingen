"""
Shared Services Layer for Mollie Integration

This module provides shared services used by all Mollie event handlers and processors.
All financial entry creation (Payment Entry, Bank Transaction, Journal Entry) should
use these shared services to ensure consistency and avoid code duplication.

Key Services:
- CostCenterResolver: Determines appropriate cost center for payments
- PaymentEntryFactory: Creates Payment Entry documents
- BankTransactionCreator: Creates Bank Transaction documents (re-exported from verenigingen_payments)
"""

# Re-export BankTransactionCreator from verenigingen_payments for convenience
# This service is already centralized and well-designed, so we reference it
# rather than duplicating it here.
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
    get_bank_transaction_creator,
)

from .cost_center_resolver import (
    CostCenterResolver,
    get_cost_center_for_context,
    get_cost_center_for_donation,
)
from .payment_entry_factory import PaymentEntryFactory

__all__ = [
    # Cost Center Resolution
    "CostCenterResolver",
    "get_cost_center_for_donation",
    "get_cost_center_for_context",
    # Payment Entry Creation
    "PaymentEntryFactory",
    # Bank Transaction Creation (from verenigingen_payments)
    "BankTransactionCreator",
    "get_bank_transaction_creator",
]
