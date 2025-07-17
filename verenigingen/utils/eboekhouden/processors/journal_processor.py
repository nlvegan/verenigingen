"""
Journal Entry Transaction Processor for eBoekhouden Integration

This module wraps the existing journal entry creation function from the main migration file,
providing a clean interface for modular processing.
"""

from typing import Any, Dict, Optional

import frappe

from .base_processor import BaseTransactionProcessor


class JournalProcessor(BaseTransactionProcessor):
    """Processor for creating Journal Entries from mutations"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is a journal entry mutation"""
        mutation_type = mutation.get("type", 0)

        # Journal entry types:
        # 0 = Opening balance
        # 5 = Money transfer (could be journal)
        # 6 = Money transfer (could be journal)
        # 7 = Memorial booking
        # 8 = Bank import
        # 9 = Manual entry
        # 10 = Stock mutation
        journal_types = [0, 5, 6, 7, 8, 9, 10]

        # Also check if it's not already handled by invoice or payment processors
        has_invoice = bool(mutation.get("invoiceNumber"))
        is_payment = mutation_type in [3, 4]

        return mutation_type in journal_types and not has_invoice and not is_payment

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process the mutation and create journal entry"""
        # Import the existing function from the main file
        from ..eboekhouden_rest_full_migration import _create_journal_entry

        return _create_journal_entry(mutation, self.company, self.cost_center, self.debug_info)

    def get_journal_type_name(self, mutation_type: int) -> str:
        """Get descriptive name for journal type"""
        type_names = {
            0: "Opening Balance",
            5: "Money Received",
            6: "Money Paid",
            7: "Memorial Booking",
            8: "Bank Import",
            9: "Manual Entry",
            10: "Stock Mutation",
        }
        return type_names.get(mutation_type, f"Type {mutation_type}")

    def is_memorial_booking(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is a memorial booking"""
        return mutation.get("type", 0) == 7

    def has_multiple_lines(self, mutation: Dict[str, Any]) -> bool:
        """Check if mutation has multiple line items"""
        rows = mutation.get("rows", [])
        return len(rows) > 0
