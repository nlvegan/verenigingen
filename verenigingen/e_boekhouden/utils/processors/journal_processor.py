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
        # 7 = Memorial booking
        # 8 = Bank import
        # 9 = Manual entry
        # 10 = Stock mutation
        # Note: Type 5/6 (Money Received/Paid) are handled by PaymentProcessor
        journal_types = [0, 7, 8, 9, 10]

        # Check for Type 3/4 payments in opposite direction WITHOUT invoice references
        # Type 3 (Customer Payment) normally positive - if negative WITHOUT invoice = generic refund → Journal Entry
        # Type 4 (Supplier Payment) normally negative - if positive WITHOUT invoice = generic refund → Journal Entry
        # Note: If they HAVE invoice references, they go to PaymentProcessor for proper reconciliation
        if mutation_type == 3:
            raw_amount = mutation.get("amount", 0) or 0
            has_rows = bool(mutation.get("rows"))
            row_amount = mutation["rows"][0].get("amount", 0) if has_rows else 0
            is_negative = (raw_amount < 0) or (row_amount < 0)
            has_invoice_ref = bool(mutation.get("invoiceNumber"))

            # Type 3 with negative amount AND no invoice ref = generic refund to customer
            if is_negative and not has_invoice_ref:
                return True

        elif mutation_type == 4:
            raw_amount = mutation.get("amount", 0) or 0
            has_rows = bool(mutation.get("rows"))
            row_amount = mutation["rows"][0].get("amount", 0) if has_rows else 0
            is_positive = (raw_amount > 0) or (row_amount > 0)

            # Type 4 with positive amount = refund from supplier → Journal Entry
            # Examples: Mollie compensation, deposit returns, supplier credits
            # Note: These often reference invoices that are already paid, so Payment Entry would fail
            if is_positive:
                return True

        # Standard journal types
        # Note: We don't check for invoiceNumber here because:
        # - Type 1/2 (actual invoices) are handled by InvoiceProcessor
        # - Type 7 (memorial bookings) can have invoice references and still need Journal Entry
        # - Type 3/4 (payments) are handled above with special refund logic
        return mutation_type in journal_types

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
