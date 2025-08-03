"""
Invoice Transaction Processor for eBoekhouden Integration

This module wraps the existing invoice creation functions from the main migration file,
providing a clean interface for modular processing.
"""

from typing import Any, Dict, Optional

import frappe

from .base_processor import BaseTransactionProcessor


class InvoiceProcessor(BaseTransactionProcessor):
    """Processor for creating Sales and Purchase Invoices from mutations"""

    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """Check if this is an invoice mutation"""
        mutation_type = mutation.get("type", 0)
        invoice_nr = mutation.get("invoiceNumber", "")

        # Process if it has an invoice number or is type 1 (sales) or 2 (purchase)
        return bool(invoice_nr) or mutation_type in [1, 2]

    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Process the mutation and create appropriate invoice"""
        # Import the existing functions from the main file
        from ..eboekhouden_rest_full_migration import _create_purchase_invoice, _create_sales_invoice

        # Determine invoice type based on mutation type
        mutation_type = mutation.get("type", 0)

        if mutation_type == 1:  # Purchase (Invoice received)
            return _create_purchase_invoice(mutation, self.company, self.cost_center, self.debug_info)
        elif mutation_type == 2:  # Sales (Invoice sent)
            return _create_sales_invoice(mutation, self.company, self.cost_center, self.debug_info)
        else:
            # Try to determine by other means (amount, description, etc.)
            amount = self.get_amount(mutation)
            if amount > 0:
                # Positive amount typically means sales
                return _create_sales_invoice(mutation, self.company, self.cost_center, self.debug_info)
            else:
                # Negative amount typically means purchase
                return _create_purchase_invoice(mutation, self.company, self.cost_center, self.debug_info)

    def process_sales_invoice(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Create a Sales Invoice from the mutation"""
        from ..eboekhouden_rest_full_migration import _create_sales_invoice

        return _create_sales_invoice(mutation, self.company, self.cost_center, self.debug_info)

    def process_purchase_invoice(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """Create a Purchase Invoice from the mutation"""
        from ..eboekhouden_rest_full_migration import _create_purchase_invoice

        return _create_purchase_invoice(mutation, self.company, self.cost_center, self.debug_info)
