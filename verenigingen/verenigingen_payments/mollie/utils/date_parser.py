"""
Centralized date parsing utilities for Mollie API responses.

Handles the inconsistency where Mollie API sometimes returns datetime objects
and sometimes returns ISO date strings, providing null-safe parsing.
"""

from datetime import datetime
from typing import Optional, Union

import frappe
from frappe.utils import getdate


class MollieDateParser:
    """Centralized date parsing for Mollie API responses."""

    @staticmethod
    def parse_mollie_date(date_value: Union[str, datetime, None], default_date: Optional[str] = None) -> str:
        """
        Parse Mollie date value to ISO string format.

        Args:
            date_value: Date from Mollie API (string, datetime, or None)
            default_date: Default date string if parsing fails (defaults to current date)

        Returns:
            ISO date string (YYYY-MM-DD format)
        """
        try:
            if date_value is None:
                return default_date or getdate().isoformat()

            if isinstance(date_value, str):
                # Handle ISO datetime strings from Mollie
                if "T" in date_value:
                    # Parse ISO datetime string and extract date
                    dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                    return dt.date().isoformat()
                else:
                    # Already a date string
                    return date_value

            elif isinstance(date_value, datetime):
                # Handle datetime objects
                return date_value.date().isoformat()

            else:
                # Unknown type, use default
                frappe.log_error(
                    f"Unknown date type in MollieDateParser: {type(date_value)} - {date_value}",
                    "Mollie Date Parsing",
                )
                return default_date or getdate().isoformat()

        except Exception as e:
            frappe.log_error(f"Failed to parse Mollie date: {date_value} - {str(e)}", "Mollie Date Parsing")
            return default_date or getdate().isoformat()

    @staticmethod
    def parse_mollie_datetime(
        date_value: Union[str, datetime, None], default_date: Optional[str] = None
    ) -> str:
        """
        Parse Mollie date value to ISO datetime string format.

        Args:
            date_value: Date from Mollie API (string, datetime, or None)
            default_date: Default datetime string if parsing fails

        Returns:
            ISO datetime string (YYYY-MM-DDTHH:MM:SS format)
        """
        try:
            if date_value is None:
                return default_date or datetime.now().isoformat()

            if isinstance(date_value, str):
                # Handle ISO datetime strings from Mollie
                if "T" in date_value:
                    # Clean up timezone info for consistent format
                    cleaned = date_value.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(cleaned)
                    return dt.isoformat()
                else:
                    # Date string only, add default time
                    dt = datetime.fromisoformat(f"{date_value}T00:00:00")
                    return dt.isoformat()

            elif isinstance(date_value, datetime):
                return date_value.isoformat()

            else:
                frappe.log_error(
                    f"Unknown datetime type in MollieDateParser: {type(date_value)} - {date_value}",
                    "Mollie Date Parsing",
                )
                return default_date or datetime.now().isoformat()

        except Exception as e:
            frappe.log_error(
                f"Failed to parse Mollie datetime: {date_value} - {str(e)}", "Mollie Date Parsing"
            )
            return default_date or datetime.now().isoformat()


# Convenience functions for backward compatibility
def parse_mollie_date(date_value: Union[str, datetime, None], default_date: Optional[str] = None) -> str:
    """Parse Mollie date to ISO date string."""
    return MollieDateParser.parse_mollie_date(date_value, default_date)


def parse_mollie_datetime(date_value: Union[str, datetime, None], default_date: Optional[str] = None) -> str:
    """Parse Mollie date to ISO datetime string."""
    return MollieDateParser.parse_mollie_datetime(date_value, default_date)
