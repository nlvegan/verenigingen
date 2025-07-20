"""
Payment Transaction Processor for eBoekhouden Integration

This module wraps the existing payment entry creation function from the main migration file,
providing a clean interface for modular processing.
"""

from typing import Any, Dict, Optional

import frappe

from .base_processor import BaseTransactionProcessor


class PaymentProcessor(BaseTransactionProcessor):
    """Processor for creating Payment Entries from mutations"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is a payment mutation"""
        mutation_type = mutation.get("type", 0)

        # Type 3 = Money received, Type 4 = Money paid
        return mutation_type in [3, 4]

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process the mutation and create payment entry"""
        # Import the existing function from the main file
        from ..eboekhouden_rest_full_migration import _create_payment_entry

        return _create_payment_entry(mutation, self.company, self.cost_center, self.debug_info)

    def get_payment_type(self, mutation: Dict[str, Any]) -> str:
        """Determine payment type from mutation"""
        mutation_type = mutation.get("type", 0)

        # Type 3 = Money received (Receive)
        # Type 4 = Money paid (Pay)
        return "Receive" if mutation_type == 3 else "Pay"

    def is_enhanced_processing_enabled(self) -> bool:
        """Enhanced payment processing is always enabled for data quality"""
        return True
