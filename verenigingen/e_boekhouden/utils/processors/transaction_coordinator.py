"""
Transaction Processing Coordinator for eBoekhouden Integration

This module coordinates the processing of different transaction types by routing
them to the appropriate processors and leveraging existing helper functions.
It provides a clean, modular interface while reusing the battle-tested
implementation from eboekhouden_rest_full_migration.py.
"""

from typing import Any, Dict, List, Optional

import frappe

from .base_processor import BaseTransactionProcessor
from .invoice_processor import InvoiceProcessor
from .journal_processor import JournalProcessor
from .opening_balance_processor import OpeningBalanceProcessor
from .payment_processor import PaymentProcessor


class TransactionCoordinator:
    """
    Coordinates transaction processing by routing mutations to appropriate processors.

    This class acts as a facade that simplifies the interaction with the complex
    eboekhouden_rest_full_migration.py file by providing a clean interface.
    """

    def __init__(self, company: str, cost_center: Optional[str] = None):
        """
        Initialize the coordinator with company context.

        Args:
            company: The ERPNext company name
            cost_center: Optional default cost center
        """
        self.company = company
        self.cost_center = cost_center or self._get_default_cost_center()

        # Initialize all processors
        self.processors = [
            InvoiceProcessor(company, self.cost_center),
            PaymentProcessor(company, self.cost_center),
            JournalProcessor(company, self.cost_center),
            OpeningBalanceProcessor(company, self.cost_center),
        ]

        # Track processing statistics
        self.stats = {"processed": 0, "created": 0, "skipped": 0, "failed": 0, "errors": []}

    def _get_default_cost_center(self) -> Optional[str]:
        """Get the default cost center for the company"""
        from ..eboekhouden_rest_full_migration import get_default_cost_center

        return get_default_cost_center(self.company)

    def process_mutation(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """
        Process a single mutation by routing it to the appropriate processor.

        Args:
            mutation: The eBoekhouden mutation data

        Returns:
            The created document or None if skipped/failed
        """
        self.stats["processed"] += 1

        # Find the appropriate processor
        for processor in self.processors:
            if processor.can_process(mutation):
                try:
                    # Clear debug info for fresh processing
                    processor.clear_debug_info()

                    # Process the mutation
                    result = processor.process(mutation)

                    if result:
                        self.stats["created"] += 1
                        # Log debug info if available
                        debug_info = processor.get_debug_info()
                        if debug_info:
                            self._log_debug_info(mutation, debug_info)
                    else:
                        self.stats["skipped"] += 1

                    return result

                except Exception as e:
                    self.stats["failed"] += 1
                    error_info = processor.format_error(mutation, e)
                    self.stats["errors"].append(error_info)

                    # Log the error
                    frappe.log_error(
                        message=str(error_info),
                        title=f"eBoekhouden Processing Error - Mutation {mutation.get('id', 'Unknown')}",
                    )

                    return None

        # No processor found for this mutation type
        self.stats["skipped"] += 1
        self._log_unhandled_mutation(mutation)
        return None

    def process_batch(
        self, mutations: List[Dict[str, Any]], progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Process a batch of mutations.

        Args:
            mutations: List of mutations to process
            progress_callback: Optional callback for progress updates

        Returns:
            Processing statistics
        """
        total = len(mutations)

        for i, mutation in enumerate(mutations):
            # Process the mutation
            self.process_mutation(mutation)

            # Call progress callback if provided
            if progress_callback and i % 10 == 0:  # Update every 10 mutations
                progress_callback(i + 1, total)

        return self.get_statistics()

    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            "total_processed": self.stats["processed"],
            "successfully_created": self.stats["created"],
            "skipped": self.stats["skipped"],
            "failed": self.stats["failed"],
            "error_count": len(self.stats["errors"]),
            "errors": self.stats["errors"][:10],  # Return first 10 errors
        }

    def reset_statistics(self) -> None:
        """Reset processing statistics"""
        self.stats = {"processed": 0, "created": 0, "skipped": 0, "failed": 0, "errors": []}

    def _log_debug_info(self, mutation: Dict[str, Any], debug_info: List[str]) -> None:
        """Log debug information for successful processing"""
        if frappe.conf.developer_mode:
            frappe.logger().debug(
                f"Processed mutation {mutation.get('id', 'Unknown')}: "
                f"{'; '.join(debug_info[:3])}"  # Log first 3 debug messages
            )

    def _log_unhandled_mutation(self, mutation: Dict[str, Any]) -> None:
        """Log information about unhandled mutations"""
        frappe.logger().warning(
            f"No processor found for mutation type {mutation.get('type', 'Unknown')} "
            f"(ID: {mutation.get('id', 'Unknown')})"
        )

    def validate_prerequisites(self) -> Dict[str, Any]:
        """
        Validate that all prerequisites are met for processing.

        Returns:
            Dictionary with validation status and any issues found
        """
        issues = []

        # Check if company exists
        if not frappe.db.exists("Company", self.company):
            issues.append(f"Company '{self.company}' does not exist")

        # Check if cost center exists
        if self.cost_center and not frappe.db.exists("Cost Center", self.cost_center):
            issues.append(f"Cost Center '{self.cost_center}' does not exist")

        # Check if required DocTypes have necessary custom fields
        required_fields = {
            "Sales Invoice": ["eboekhouden_mutation_nr"],
            "Purchase Invoice": ["eboekhouden_mutation_nr"],
            "Payment Entry": ["eboekhouden_mutation_nr"],
            "Journal Entry": ["eboekhouden_mutation_nr"],
        }

        for doctype, fields in required_fields.items():
            for field in fields:
                if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": field}):
                    issues.append(f"Missing custom field '{field}' in {doctype}")

        return {"valid": len(issues) == 0, "issues": issues}
