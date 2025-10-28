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
from .stock_processor import StockProcessor


class TransactionCoordinator:
    """
    Coordinates transaction processing by routing mutations to appropriate processors.

    This class acts as a facade that simplifies the interaction with the complex
    eboekhouden_rest_full_migration.py file by providing a clean interface.
    """

    def __init__(self, company: str, cost_center: Optional[str] = None, mutation_type: Optional[int] = None):
        """
        Initialize the coordinator with company context.

        Args:
            company: The ERPNext company name
            cost_center: Optional default cost center
            mutation_type: Optional mutation type to filter processors (for batch imports)
        """
        self.company = company
        self.cost_center = cost_center or self._get_default_cost_center()
        self.mutation_type = mutation_type

        # Define which processor classes handle which mutation types
        # This allows filtering processors when processing type-specific batches
        self.processor_type_map = {
            0: [
                OpeningBalanceProcessor,
                StockProcessor,
                JournalProcessor,
            ],  # Opening balances (can include stock)
            1: [InvoiceProcessor],  # Purchase invoices
            2: [InvoiceProcessor],  # Sales invoices
            3: [PaymentProcessor, JournalProcessor],  # Customer payments (normal + refunds)
            4: [PaymentProcessor, JournalProcessor],  # Supplier payments (normal + refunds)
            5: [PaymentProcessor],  # Money received (transfers)
            6: [PaymentProcessor],  # Money paid (transfers)
            7: [StockProcessor, JournalProcessor],  # Memorial bookings (stock adjustments or regular)
            8: [JournalProcessor],  # Bank import
            9: [JournalProcessor],  # Manual entry
            10: [StockProcessor, JournalProcessor],  # Stock mutations
        }

        # Initialize processors (filtered by mutation_type if provided)
        self.processors = self._initialize_processors()

        # Track processing statistics
        self.stats = {"processed": 0, "created": 0, "skipped": 0, "failed": 0, "errors": []}

        # Store debug info from last processed mutation for caller access
        self.last_processor_debug_info = []

    def _get_default_cost_center(self) -> Optional[str]:
        """Get the default cost center for the company"""
        from ..eboekhouden_rest_full_migration import get_default_cost_center

        return get_default_cost_center(self.company)

    def _initialize_processors(self) -> List[BaseTransactionProcessor]:
        """
        Initialize processors, optionally filtered by mutation type.

        When mutation_type is specified, only processors relevant to that type
        are initialized, improving performance and clarity for batch imports.

        Returns:
            List of initialized processors
        """
        # Create all possible processors
        all_processors = [
            InvoiceProcessor(self.company, self.cost_center),
            PaymentProcessor(self.company, self.cost_center),
            StockProcessor(self.company, self.cost_center),
            JournalProcessor(self.company, self.cost_center),
            OpeningBalanceProcessor(self.company, self.cost_center),
        ]

        # If mutation_type specified, filter to relevant processors only
        if self.mutation_type is not None:
            allowed_classes = self.processor_type_map.get(self.mutation_type, [])

            # Filter processors based on allowed classes
            filtered = [p for p in all_processors if type(p) in allowed_classes]

            # If we have a mapping but no processors matched, log a warning
            if self.mutation_type in self.processor_type_map and not filtered:
                frappe.logger().warning(
                    f"No processors found for mutation type {self.mutation_type}, "
                    f"expected: {[c.__name__ for c in allowed_classes]}"
                )

            # If mutation type has no mapping, use all processors as fallback
            if self.mutation_type not in self.processor_type_map:
                frappe.logger().warning(f"Unknown mutation type {self.mutation_type}, using all processors")
                return all_processors

            return filtered

        # No mutation_type specified, return all processors
        return all_processors

    def process_mutation(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """
        Process a single mutation by routing it to the appropriate processor.

        Args:
            mutation: The eBoekhouden mutation data

        Returns:
            The created document or None if skipped/failed
        """
        self.stats["processed"] += 1
        self.last_processor_debug_info = []  # Reset for this mutation

        # Find the appropriate processor
        # Accumulate debug info from all processors that were checked
        accumulated_debug_info = []

        for processor in self.processors:
            # Clear debug info before checking can_process
            processor.clear_debug_info()

            can_process = processor.can_process(mutation)

            # Capture debug info from can_process() check
            processor_debug = processor.get_debug_info()
            if processor_debug:
                accumulated_debug_info.extend(processor_debug)

            if can_process:
                try:
                    # Process the mutation
                    result = processor.process(mutation)

                    # Capture updated debug info from processor for caller access
                    accumulated_debug_info.extend(processor.get_debug_info())
                    self.last_processor_debug_info = accumulated_debug_info

                    if result:
                        self.stats["created"] += 1
                        # Log debug info if available
                        if self.last_processor_debug_info:
                            self._log_debug_info(mutation, self.last_processor_debug_info)
                    else:
                        self.stats["skipped"] += 1

                    return result

                except Exception as e:
                    self.stats["failed"] += 1
                    error_info = processor.format_error(mutation, e)
                    self.stats["errors"].append(error_info)

                    # Capture debug info from error for caller access
                    accumulated_debug_info.extend(error_info.get("debug_info", []))
                    self.last_processor_debug_info = accumulated_debug_info

                    # Log the error
                    frappe.log_error(
                        message=str(error_info),
                        title=f"eBoekhouden Processing Error - Mutation {mutation.get('id', 'Unknown')}",
                    )

                    return None

            # Processor cannot handle this mutation, continue to next processor

        # No processor found for this mutation type
        self.stats["skipped"] += 1
        self.last_processor_debug_info = accumulated_debug_info  # Capture all checks
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
            "Stock Reconciliation": ["eboekhouden_mutation_nr"],
        }

        for doctype, fields in required_fields.items():
            for field in fields:
                if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": field}):
                    issues.append(f"Missing custom field '{field}' in {doctype}")

        return {"valid": len(issues) == 0, "issues": issues}
