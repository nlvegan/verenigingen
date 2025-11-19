"""
SEPA Mandate Identity Service

This service handles SEPA mandate identity generation and management.
Extracted from SEPA Mandate controller for better separation of concerns.
"""

import re
from typing import Optional

import frappe
from frappe.utils import now_datetime


class SEPAMandateIdentityService:
    """Service for SEPA mandate identity generation and management"""

    def __init__(self):
        self._settings_cache = None

    def generate_mandate_id(self, mandate_doc=None) -> str:
        """
        Generate unique mandate ID using configurable pattern.

        Args:
            mandate_doc: Optional mandate document for context

        Returns:
            Generated mandate ID

        Raises:
            Exception: If ID generation fails
        """
        try:
            # Get the naming pattern and starting counter from settings
            settings = self._get_settings()
            naming_pattern = (
                settings.sepa_mandate_naming_pattern
                if settings.sepa_mandate_naming_pattern
                else "MANDATE-.YY.-.MM.-.####"
            )
            # Handle invalid starting counter values by defaulting to 1
            starting_counter = 1
            if settings.sepa_mandate_starting_counter:
                try:
                    starting_counter = int(settings.sepa_mandate_starting_counter)
                except (ValueError, TypeError):
                    starting_counter = 1

            # Generate mandate_id with custom counter logic
            return self._generate_mandate_id_with_counter(naming_pattern, starting_counter)

        except Exception as e:
            # Log the error and fallback to default pattern
            frappe.log_error(f"Error in generate_mandate_id: {str(e)}", "SEPA Mandate ID Generation")
            from frappe.model.naming import make_autoname

            return make_autoname("MANDATE-.YY.-.MM.-.####")

    def _generate_mandate_id_with_counter(self, pattern: str, starting_counter: int) -> str:
        """
        Generate mandate_id with custom starting counter support.

        Args:
            pattern: Naming pattern with date and counter tokens
            starting_counter: Starting counter value

        Returns:
            Generated mandate ID with proper counter
        """
        # Replace date tokens
        now = now_datetime()
        result = pattern

        # Handle brace format {TOKEN}
        result = result.replace("{YYYY}", str(now.year))
        result = result.replace("{YY}", str(now.year)[-2:])
        result = result.replace("{MM}", f"{now.month:02d}")
        result = result.replace("{DD}", f"{now.day:02d}")

        # Handle complex patterns like "TEST.YYYY..MM..DD.####" with comprehensive regex
        # Pattern: .YYYY..MM..DD. should become -2024-09-18-
        result = re.sub(r"\.YYYY\.\.MM\.\.DD\.", f"-{now.year}-{now.month:02d}-{now.day:02d}-", result)
        result = re.sub(
            r"\.YY\.\.MM\.\.DD\.", f"-{str(now.year)[-2:]}-{now.month:02d}-{now.day:02d}-", result
        )

        # Handle other overlapping patterns
        result = re.sub(r"\.YYYY\.\.", f"-{now.year}-", result)
        result = re.sub(r"\.YY\.\.", f"-{str(now.year)[-2:]}-", result)
        result = re.sub(r"\.MM\.\.", f"-{now.month:02d}-", result)
        result = re.sub(r"\.DD\.\.", f"-{now.day:02d}-", result)

        # Handle remaining single-dot patterns
        result = re.sub(r"\.YYYY\.", str(now.year), result)
        result = re.sub(r"\.YY\.", str(now.year)[-2:], result)
        result = re.sub(r"\.MM\.", f"{now.month:02d}", result)
        result = re.sub(r"\.DD\.", f"{now.day:02d}", result)

        # Clean up any remaining dot-counter patterns like "-.####" to "-####"
        result = re.sub(r"-\.(#+)", r"-\1", result)

        # Find counter pattern (#### or .####)
        counter_pattern = re.search(r"(#+)", result)
        if counter_pattern:
            counter_digits = len(counter_pattern.group(1))

            # Check if we need to insert a dash before the counter
            # This handles cases like "{YYYY}{MM}{DD}####" -> "20240918-0001"
            counter_start = counter_pattern.start()
            if counter_start > 0 and result[counter_start - 1].isdigit():
                # Insert dash before counter if preceded by a digit
                result = result[:counter_start] + "-" + result[counter_start:]
                # Re-search for counter pattern after insertion
                counter_pattern = re.search(r"(#+)", result)

            # Get the base pattern without counter for finding existing mandates
            base_pattern = re.sub(r"(#+)", "", result)

            # Find existing mandates with this base pattern to determine next counter
            existing_mandates = frappe.db.sql(
                """
                SELECT mandate_id FROM `tabSEPA Mandate`
                WHERE mandate_id LIKE %s
                ORDER BY mandate_id DESC
                LIMIT 1
            """,
                (base_pattern + "%",),
            )

            if existing_mandates:
                # Extract counter from last mandate and increment
                last_mandate = existing_mandates[0][0]
                last_counter_match = re.search(r"(\d+)$", last_mandate)
                if last_counter_match:
                    next_counter = int(last_counter_match.group(1)) + 1
                else:
                    next_counter = starting_counter
            else:
                # No existing mandates, use starting counter
                next_counter = starting_counter

            # Format counter with proper padding
            counter_str = str(next_counter).zfill(counter_digits)

            # Replace counter pattern in result
            result = re.sub(r"(#+)", counter_str, result)

        return result

    def validate_mandate_reference(self, mandate_id: str) -> bool:
        """
        Validate mandate reference format and uniqueness.

        Args:
            mandate_id: Mandate ID to validate

        Returns:
            True if valid, False otherwise
        """
        if not mandate_id:
            return False

        # Check basic format (not empty, reasonable length)
        if len(mandate_id) < 3 or len(mandate_id) > 35:  # SEPA mandate ID limits
            return False

        # Check for invalid characters (SEPA allows alphanumeric and limited special chars)
        if not re.match(r"^[A-Za-z0-9\-._/]+$", mandate_id):
            return False

        return True

    def ensure_mandate_uniqueness(self, mandate_id: str, exclude_name: Optional[str] = None) -> bool:
        """
        Ensure mandate ID is unique in the system.

        Args:
            mandate_id: Mandate ID to check
            exclude_name: Optional mandate name to exclude from check

        Returns:
            True if unique, False if duplicate exists
        """
        filters = {"mandate_id": mandate_id}
        if exclude_name:
            filters["name"] = ["!=", exclude_name]

        existing = frappe.db.exists("SEPA Mandate", filters)
        return not existing

    def _get_settings(self):
        """Get cached settings to avoid repeated DB calls"""
        if self._settings_cache is None:
            self._settings_cache = frappe.get_single("Verenigingen Settings")
        return self._settings_cache

    def clear_settings_cache(self):
        """Clear settings cache when settings are updated"""
        self._settings_cache = None


# Singleton instance for global use
sepa_mandate_identity_service = SEPAMandateIdentityService()
