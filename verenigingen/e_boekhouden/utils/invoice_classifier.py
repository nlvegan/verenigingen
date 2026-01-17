"""
Invoice Classification Service for E-Boekhouden Integration

This module provides the single source of truth for classifying invoice types
and determining how they should be processed. It eliminates duplication between
credit note detection, mixed invoice handling, and consolidation logic.

Design Principles:
- Single Responsibility: Only classification, no processing
- Immutable Analysis: Returns classification result, doesn't modify data
- Clear Semantics: Explicit types instead of boolean flags
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe

from verenigingen.e_boekhouden.utils.data_integrity import safe_log_mutation_error


class InvoiceType(Enum):
    """Classification of invoice types based on line item analysis"""

    NORMAL = "normal"  # All positive amounts, standard invoice
    PURE_CREDIT_NOTE = "pure_credit_note"  # All negative amounts, pure return
    MIXED = "mixed"  # Both positive and negative amounts
    ZERO_AMOUNT = "zero_amount"  # Edge case: no significant amounts


class ProcessingStrategy(Enum):
    """How the invoice should be processed in ERPNext"""

    STANDARD = "standard"  # Normal processing, preserve signs
    CREDIT_NOTE = "credit_note"  # Set is_return=1, convert amounts to positive
    CONSOLIDATE = "consolidate"  # Merge items into single line with net amount


@dataclass(frozen=True)
class InvoiceClassification:
    """
    Immutable result of invoice classification analysis.

    Attributes:
        invoice_type: The type of invoice (NORMAL, PURE_CREDIT_NOTE, MIXED, ZERO_AMOUNT)
        processing_strategy: How to process it (STANDARD, CREDIT_NOTE, CONSOLIDATE)
        net_amount: Calculated net total from line items
        positive_item_count: Number of line items with positive amounts
        negative_item_count: Number of line items with negative amounts
        total_item_count: Total number of line items analyzed
        should_set_is_return: Whether ERPNext is_return flag should be set
        requires_consolidation: Whether items need to be consolidated
        reasoning: Human-readable explanation of the classification
    """

    invoice_type: InvoiceType
    processing_strategy: ProcessingStrategy
    net_amount: float
    positive_item_count: int
    negative_item_count: int
    total_item_count: int
    should_set_is_return: bool
    requires_consolidation: bool
    reasoning: str


class InvoiceClassifier:
    """
    Single source of truth for invoice classification.

    Analyzes mutation data and line items to determine:
    1. What type of invoice this is (normal, credit note, mixed)
    2. How it should be processed (standard, as credit note, or consolidated)
    3. Whether ERPNext is_return flag should be set

    This eliminates duplication between:
    - _detect_credit_note_improved()
    - Consolidation logic checks (has_positive_qty/has_negative_qty)
    - process_line_items() is_return checks
    """

    def __init__(self, tolerance: float = 0.01):
        """
        Initialize classifier.

        Args:
            tolerance: Amounts below this are considered zero (default 0.01 = 1 cent)
        """
        self.tolerance = tolerance

    def classify(
        self, mutation_detail: Dict[str, Any], debug_info: Optional[List[str]] = None
    ) -> InvoiceClassification:
        """
        Classify an invoice based on its line items.

        This is the main entry point. It analyzes the mutation data and returns
        a complete classification with processing instructions.

        Args:
            mutation_detail: The E-Boekhouden mutation data (must include rows/Regels)
            debug_info: Optional list to append debug messages to

        Returns:
            InvoiceClassification with complete analysis

        Raises:
            ValueError: If mutation_detail lacks required data
        """
        if debug_info is None:
            debug_info = []

        # Extract line items (handle both REST "rows" and SOAP "Regels" field names)
        rows = mutation_detail.get("rows", []) or mutation_detail.get("Regels", [])

        if not rows:
            debug_info.append("InvoiceClassifier: No line items found")
            return self._classify_no_items(mutation_detail, debug_info)

        # Analyze line items
        analysis = self._analyze_line_items(rows, debug_info)

        # Determine classification based on analysis
        return self._determine_classification(analysis, debug_info)

    def _analyze_line_items(self, rows: List[Dict[str, Any]], debug_info: List[str]) -> Dict[str, Any]:
        """
        Analyze line items to count positive/negative amounts and calculate totals.

        Args:
            rows: List of line item dictionaries
            debug_info: Debug message accumulator

        Returns:
            Dictionary with analysis results:
            - net_amount: Sum of all amounts (signed)
            - positive_items: Count of items with positive amounts
            - negative_items: Count of items with negative amounts
            - zero_items: Count of items with amounts near zero
            - all_amounts: List of all amounts for detailed analysis
        """
        net_amount = 0.0
        positive_items = 0
        negative_items = 0
        zero_items = 0

        for idx, row in enumerate(rows):
            # Handle both Dutch (SOAP) and English (REST) field names
            amount_field = "amount" if "amount" in row else "Prijs"
            quantity_field = "quantity" if "quantity" in row else "Aantal"

            item_amount = frappe.utils.flt(row.get(amount_field, 0))
            item_quantity = frappe.utils.flt(row.get(quantity_field, 1))

            # Calculate total amount for this line item
            total_item_amount = item_amount * item_quantity
            net_amount += total_item_amount

            # Classify this item
            if abs(total_item_amount) < self.tolerance:
                zero_items += 1
            elif total_item_amount > 0:
                positive_items += 1
            else:  # total_item_amount < 0
                negative_items += 1

        debug_info.append(
            f"InvoiceClassifier: Analyzed {len(rows)} items - "
            f"positive={positive_items}, negative={negative_items}, zero={zero_items}, "
            f"net={net_amount:.2f}"
        )

        return {
            "net_amount": net_amount,
            "positive_items": positive_items,
            "negative_items": negative_items,
            "zero_items": zero_items,
            "total_items": len(rows),
        }

    def _determine_classification(
        self, analysis: Dict[str, Any], debug_info: List[str]
    ) -> InvoiceClassification:
        """
        Determine the invoice type and processing strategy based on analysis.

        Decision Logic:
        1. All items negative → PURE_CREDIT_NOTE → Process as credit note
        2. Mixed (positive + negative) → MIXED → Consolidate if net < 0
        3. All items positive → NORMAL → Standard processing
        4. All items zero → ZERO_AMOUNT → Standard processing

        Args:
            analysis: Results from _analyze_line_items()
            debug_info: Debug message accumulator

        Returns:
            InvoiceClassification with complete decision
        """
        pos = analysis["positive_items"]
        neg = analysis["negative_items"]
        net = analysis["net_amount"]
        total = analysis["total_items"]

        # Case 1: Pure credit note (all items negative)
        if neg > 0 and pos == 0:
            reasoning = (
                f"Pure credit note: all {neg} line items are negative (net: {net:.2f}). "
                f"Will set is_return=1 and convert amounts to positive for ERPNext."
            )
            debug_info.append(f"InvoiceClassifier: {reasoning}")

            return InvoiceClassification(
                invoice_type=InvoiceType.PURE_CREDIT_NOTE,
                processing_strategy=ProcessingStrategy.CREDIT_NOTE,
                net_amount=net,
                positive_item_count=pos,
                negative_item_count=neg,
                total_item_count=total,
                should_set_is_return=True,
                requires_consolidation=False,
                reasoning=reasoning,
            )

        # Case 2: Mixed invoice (both positive and negative)
        elif pos > 0 and neg > 0:
            # ERPNext CANNOT handle mixed positive/negative items in a single invoice
            # ALL mixed invoices must be consolidated, regardless of net total
            reasoning = (
                f"Mixed invoice: {pos} positive items, {neg} negative items, net={net:.2f}. "
                f"ERPNext does not support mixed positive/negative line items - consolidating into single line."
            )
            debug_info.append(f"InvoiceClassifier: {reasoning}")

            return InvoiceClassification(
                invoice_type=InvoiceType.MIXED,
                processing_strategy=ProcessingStrategy.CONSOLIDATE,
                net_amount=net,
                positive_item_count=pos,
                negative_item_count=neg,
                total_item_count=total,
                should_set_is_return=False,  # Set AFTER consolidation, not before
                requires_consolidation=True,
                reasoning=reasoning,
            )

        # Case 3: Normal invoice (all positive or all zero)
        else:
            if abs(net) < self.tolerance:
                invoice_type = InvoiceType.ZERO_AMOUNT
                reasoning = f"Zero-amount invoice: net total is {net:.2f} (near zero). Standard processing."
            else:
                invoice_type = InvoiceType.NORMAL
                reasoning = f"Normal invoice: {pos} positive items, net={net:.2f}. Standard processing."

            debug_info.append(f"InvoiceClassifier: {reasoning}")

            return InvoiceClassification(
                invoice_type=invoice_type,
                processing_strategy=ProcessingStrategy.STANDARD,
                net_amount=net,
                positive_item_count=pos,
                negative_item_count=neg,
                total_item_count=total,
                should_set_is_return=False,
                requires_consolidation=False,
                reasoning=reasoning,
            )

    def _classify_no_items(
        self, mutation_detail: Dict[str, Any], debug_info: List[str]
    ) -> InvoiceClassification:
        """
        Handle edge case where no line items are present.

        This is an error condition - we cannot reliably classify without line items.
        The top-level amount field is unreliable (may be copied from summary API).

        Args:
            mutation_detail: The mutation data
            debug_info: Debug message accumulator

        Raises:
            ValueError: Always - invoices without line items cannot be classified

        Returns:
            Never returns - always raises
        """
        mutation_id = mutation_detail.get("id", "unknown")
        error_msg = (
            f"Cannot classify invoice without line items. "
            f"Mutation ID: {mutation_id}. "
            f"Line items are required for accurate classification."
        )

        debug_info.append(f"InvoiceClassifier ERROR: {error_msg}")
        safe_log_mutation_error(
            title="Invoice Classification Failed - No Line Items",
            mutation=mutation_detail,
            additional_context=error_msg,
        )

        raise ValueError(error_msg)


# Singleton instance for convenience
_classifier_instance = None


def get_invoice_classifier() -> InvoiceClassifier:
    """
    Get the singleton InvoiceClassifier instance.

    Returns:
        Shared InvoiceClassifier instance
    """
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = InvoiceClassifier()
    return _classifier_instance
