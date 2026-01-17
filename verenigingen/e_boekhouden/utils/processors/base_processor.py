"""
Base Transaction Processor for eBoekhouden Integration

This module provides the base class for all transaction processors,
defining the common interface and shared functionality.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import frappe

from verenigingen.e_boekhouden.utils.data_integrity import (
    normalize_date,
    safe_log_mutation_error,
)


class BaseTransactionProcessor(ABC):
    """Abstract base class for processing different types of eBoekhouden transactions"""

    def __init__(self, company: str, cost_center: Optional[str] = None, overwrite_existing: bool = False):
        """
        Initialize the processor with company context

        Args:
            company: The ERPNext company name
            cost_center: Optional default cost center
            overwrite_existing: Whether to delete and recreate existing documents (default: False = update only)
        """
        self.company = company
        self.cost_center = cost_center or self._get_default_cost_center()
        self.overwrite_existing = overwrite_existing
        self.debug_info = []

    def _get_default_cost_center(self) -> Optional[str]:
        """Get the default cost center for the company"""
        return frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")

    @abstractmethod
    def can_process(self, mutation: Dict[str, Any]) -> bool:
        """
        Check if this processor can handle the given mutation

        Args:
            mutation: The eBoekhouden mutation data

        Returns:
            True if this processor can handle the mutation
        """
        pass

    @abstractmethod
    def process(self, mutation: Dict[str, Any]) -> Optional[frappe.model.document.Document]:
        """
        Process the mutation and create the appropriate ERPNext document

        Args:
            mutation: The eBoekhouden mutation data

        Returns:
            The created document or None if skipped
        """
        pass

    def add_debug_info(self, message: str) -> None:
        """Add a debug message to the info list"""
        self.debug_info.append(message)

    def get_debug_info(self) -> List[str]:
        """Get all debug messages"""
        return self.debug_info

    def clear_debug_info(self) -> None:
        """Clear debug messages"""
        self.debug_info = []

    def validate_mutation(self, mutation: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate if the mutation has required fields

        Args:
            mutation: The mutation to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        required_fields = ["MutatieNr", "Datum", "Omschrijving"]

        for field in required_fields:
            if field not in mutation or not mutation[field]:
                return False, f"Missing required field: {field}"

        return True, ""

    def check_duplicate(self, mutation_id: str, doctype: str) -> Optional[str]:
        """
        Check if a mutation has already been imported

        Args:
            mutation_id: The eBoekhouden mutation number
            doctype: The ERPNext doctype to check

        Returns:
            The name of the existing document if found, None otherwise
        """
        existing = frappe.db.get_value(doctype, {"eboekhouden_mutation_nr": mutation_id}, "name")

        if existing:
            self.add_debug_info(f"Mutation {mutation_id} already imported as {doctype} {existing}")

        return existing

    def get_posting_date(self, mutation: Dict[str, Any]) -> str:
        """
        Extract and format the posting date from mutation.

        Uses normalize_date() to handle multiple date formats:
        - YYYYMMDD (eBoekhouden format)
        - ISO datetime (2025-01-10T00:00:00)
        - YYYY-MM-DD (already correct)
        - European DD-MM-YYYY or DD/MM/YYYY

        Args:
            mutation: The mutation data

        Returns:
            The posting date in YYYY-MM-DD format
        """
        # Try multiple field names for the date
        date_value = mutation.get("Datum") or mutation.get("date") or mutation.get("Date", "")

        normalized = normalize_date(date_value)

        if normalized:
            return normalized

        # Fallback to empty string if normalization fails
        self.add_debug_info(f"⚠️ Could not normalize date: {date_value}")
        return ""

    def get_description(self, mutation: Dict[str, Any]) -> str:
        """
        Get a meaningful description from the mutation

        Args:
            mutation: The mutation data

        Returns:
            The description string
        """
        description = mutation.get("Omschrijving", "").strip()

        # Add mutation number for reference
        mutation_nr = mutation.get("MutatieNr", "")
        if mutation_nr and mutation_nr not in description:
            description = f"{description} (Mutation: {mutation_nr})"

        return description or f"eBoekhouden Import - Mutation {mutation_nr}"

    def get_amount(self, mutation: Dict[str, Any]) -> float:
        """
        Get the amount from mutation, handling different field names

        Args:
            mutation: The mutation data

        Returns:
            The amount as float
        """
        # Try different possible field names
        amount_fields = ["Bedrag", "BedragInvoer", "amount", "Amount"]

        for field in amount_fields:
            if field in mutation and mutation[field]:
                try:
                    return float(mutation[field])
                except (ValueError, TypeError):
                    continue

        self.add_debug_info("Warning: No valid amount found in mutation")
        return 0.0

    def validate_row_amounts(
        self,
        mutation: Dict[str, Any],
        rows: List[Dict[str, Any]],
        mutation_amount: float,
        tolerance: float = 0.01,
        use_net_amount: bool = False,
    ) -> Tuple[bool, str, float]:
        """
        Validate that row amounts match the mutation's total amount.

        Dutch tax authorities (Belastingdienst) require exact amounts in bookkeeping.
        This prevents data quality issues and audit compliance problems.

        Args:
            mutation: The mutation data
            rows: List of row dictionaries with 'amount' field
            mutation_amount: The mutation's total amount to validate against
            tolerance: Maximum allowed difference (default: 0.01 for 1 cent rounding tolerance)
            use_net_amount: If True, validate net sum (sum of signed amounts) instead of absolute sum
                           Used for memorial bookings where positive/negative matters

        Returns:
            Tuple of (is_valid, error_message, amount_difference)
        """
        mutation_id = mutation.get("id") or mutation.get("MutatieNr", "Unknown")

        # Calculate sum of row amounts (excluding zero/near-zero rows)
        total_row_amount = 0
        valid_rows = 0

        for idx, row in enumerate(rows):
            row_amount = frappe.utils.flt(row.get("amount", 0), 2)

            # Skip zero or near-zero amount rows (< 1 cent)
            if abs(row_amount) < 0.01:
                self.add_debug_info(f"Row {idx + 1}: Skipped zero/near-zero amount ({row_amount})")
                continue

            # Use net (signed) sum or absolute sum depending on validation type
            if use_net_amount:
                total_row_amount += row_amount  # Keep sign for net calculation
            else:
                total_row_amount += abs(row_amount)  # Use absolute for gross calculation

            valid_rows += 1

        # Calculate difference based on validation type
        if use_net_amount:
            # For net amount validation (memorial bookings): compare signed sums
            amount_diff = abs(total_row_amount - mutation_amount)
            comparison_type = "net"
        else:
            # For absolute amount validation (payments): compare absolute sums
            amount_diff = abs(total_row_amount - abs(mutation_amount))
            comparison_type = "absolute"

        # Validate within tolerance
        if amount_diff > tolerance:
            error_msg = (
                f"Amount mismatch in mutation {mutation_id} ({comparison_type} validation): "
                f"Expected mutation amount = {mutation_amount}, "
                f"Sum of row amounts = {total_row_amount}, "
                f"Difference = {amount_diff} (tolerance: {tolerance})"
            )

            # Log detailed breakdown
            self.add_debug_info(f"❌ {error_msg}")
            self.add_debug_info(f"Valid rows processed: {valid_rows}/{len(rows)}")

            # Log with PII masked for privacy compliance
            safe_log_mutation_error(
                title=f"Amount Mismatch - {mutation_id}",
                mutation=mutation,
                additional_context=f"{error_msg}\n\n"
                f"Validation type: {comparison_type}\n"
                f"Rows breakdown:\n{frappe.as_json([{'index': i + 1, 'ledger': r.get('ledgerId'), 'amount': r.get('amount')} for i, r in enumerate(rows)], indent=2)}",
            )

            return False, error_msg, amount_diff

        # Validation passed
        self.add_debug_info(
            f"✓ Amount validation passed ({comparison_type}): "
            f"expected={mutation_amount}, actual={total_row_amount}, diff={amount_diff}"
        )

        return True, "", amount_diff

    def validate_journal_entry_net_amount(
        self,
        mutation: Dict[str, Any],
        total_debit: float,
        total_credit: float,
        expected_net: float,
        tolerance: float = 0.01,
    ) -> Tuple[bool, str, float]:
        """
        Validate that a journal entry's net amount (debit - credit) matches expected value.

        Used for memorial bookings where the journal entry should produce a specific net result.

        Args:
            mutation: The mutation data
            total_debit: Sum of all debit entries
            total_credit: Sum of all credit entries
            expected_net: Expected net amount (usually mutation.amount for memorial bookings)
            tolerance: Maximum allowed difference (default: 0.01 for 1 cent rounding tolerance)

        Returns:
            Tuple of (is_valid, error_message, net_difference)
        """
        mutation_id = mutation.get("id") or mutation.get("MutatieNr", "Unknown")

        # Calculate actual net amount
        actual_net = total_debit - total_credit
        net_diff = abs(actual_net - expected_net)

        # Validate within tolerance
        if net_diff > tolerance:
            error_msg = (
                f"Journal entry net amount mismatch in mutation {mutation_id}: "
                f"Expected net = {expected_net}, "
                f"Actual net = {actual_net} (Debit {total_debit} - Credit {total_credit}), "
                f"Difference = {net_diff} (tolerance: {tolerance})"
            )

            self.add_debug_info(f"❌ {error_msg}")

            # Log with PII masked for privacy compliance
            safe_log_mutation_error(
                title=f"JE Net Mismatch - {mutation_id}",
                mutation=mutation,
                additional_context=error_msg,
            )

            return False, error_msg, net_diff

        # Validation passed
        self.add_debug_info(
            f"✓ Journal entry net amount validated: "
            f"expected={expected_net}, actual={actual_net}, diff={net_diff}"
        )

        return True, "", net_diff

    def format_error(self, mutation: Dict[str, Any], error: Exception) -> Dict[str, Any]:
        """
        Format error information for logging

        Args:
            mutation: The mutation that caused the error
            error: The exception that occurred

        Returns:
            Formatted error dictionary
        """
        return {
            "mutation_id": mutation.get("MutatieNr", "Unknown"),
            "date": mutation.get("Datum", "Unknown"),
            "description": mutation.get("Omschrijving", "Unknown"),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "debug_info": self.get_debug_info(),
        }
