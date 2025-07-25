"""
Base Transaction Processor for eBoekhouden Integration

This module provides the base class for all transaction processors,
defining the common interface and shared functionality.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import frappe


class BaseTransactionProcessor(ABC):
    """Abstract base class for processing different types of eBoekhouden transactions"""

    def __init__(self, company: str, cost_center: Optional[str] = None):
        """
        Initialize the processor with company context

        Args:
            company: The ERPNext company name
            cost_center: Optional default cost center
        """
        self.company = company
        self.cost_center = cost_center or self._get_default_cost_center()
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
        Extract and format the posting date from mutation

        Args:
            mutation: The mutation data

        Returns:
            The posting date in YYYY-MM-DD format
        """
        date_str = mutation.get("Datum", "")

        # Handle eBoekhouden date format (YYYYMMDD)
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # Return as-is if already in correct format
        return date_str

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
