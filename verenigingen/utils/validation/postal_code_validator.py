"""
Postal Code Validation Utility - Centralized postal code validation.

This utility consolidates all postal code validation logic that was previously
scattered across multiple files. Uses the most robust validation patterns
from application_validators.py as the foundation.

Functions:
    - validate_dutch_postal_code(): Primary Dutch postal code validation
    - validate_postal_code(): Multi-country postal code validation
    - get_postal_code_pattern(): Get regex patterns for different countries
"""

import re

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import create_service_result, handle_service_error


def validate_dutch_postal_code(postal_code):
    """Validate Dutch postal code format with robust pattern matching.

    Uses the most comprehensive pattern that excludes invalid 0000 prefixes
    and handles flexible spacing. Consolidated from multiple validators.

    Args:
        postal_code (str): Postal code to validate

    Returns:
        dict: Validation result with valid/message structure
            - valid (bool): True if postal code is valid
            - message (str): Error message if validation fails
    """
    if not postal_code:
        return {"valid": False, "message": _("Postal code is required")}

    # Most robust Dutch pattern: excludes 0000 prefix, flexible spacing
    # Pattern from application_validators.py (most comprehensive)
    dutch_pattern = r"^[1-9][0-9]{3}\s?[A-Z]{2}$"

    if not re.match(dutch_pattern, postal_code.upper().strip()):
        return {
            "valid": False,
            "message": _("Invalid Dutch postal code format. Expected format: 1234 AB or 1234AB"),
        }

    return {"valid": True}


def validate_postal_code(postal_code, country="Netherlands"):
    """Validate postal code format for multiple countries.

    Expanded from application_validators.py to support multiple European countries
    with their specific postal code requirements.

    Args:
        postal_code (str): Postal code to validate
        country (str): Country name for format validation

    Returns:
        dict: Validation result with valid/message structure
    """
    if not postal_code:
        return {"valid": False, "message": _("Postal code is required")}

    # Comprehensive postal code patterns for European countries
    postal_patterns = {
        "Netherlands": r"^[1-9][0-9]{3}\s?[A-Z]{2}$",  # Most robust Dutch pattern
        "Germany": r"^[0-9]{5}$",
        "Belgium": r"^[1-9][0-9]{3}$",
        "France": r"^[0-9]{5}$",
        "Austria": r"^[1-9][0-9]{3}$",
        "Switzerland": r"^[1-9][0-9]{3}$",
        "Luxembourg": r"^[1-9][0-9]{3}$",
    }

    pattern = postal_patterns.get(country, r"^.+$")  # Default: any non-empty

    if not re.match(pattern, postal_code.upper().strip()):
        return {"valid": False, "message": _("Invalid postal code format for {0}").format(country)}

    return {"valid": True}


def get_postal_code_pattern(country="Netherlands"):
    """Get regex pattern for postal code validation by country.

    Args:
        country (str): Country name

    Returns:
        str: Regex pattern for the specified country
    """
    patterns = {
        "Netherlands": r"^[1-9][0-9]{3}\s?[A-Z]{2}$",
        "Germany": r"^[0-9]{5}$",
        "Belgium": r"^[1-9][0-9]{3}$",
        "France": r"^[0-9]{5}$",
        "Austria": r"^[1-9][0-9]{3}$",
        "Switzerland": r"^[1-9][0-9]{3}$",
        "Luxembourg": r"^[1-9][0-9]{3}$",
    }

    return patterns.get(country, r"^.+$")


def normalize_dutch_postal_code(postal_code):
    """Normalize Dutch postal code to standard format (1234 AB).

    Args:
        postal_code (str): Postal code to normalize

    Returns:
        str: Normalized postal code or None if invalid
    """
    if not postal_code:
        return None

    # Remove all spaces and convert to uppercase
    clean_code = postal_code.upper().replace(" ", "")

    # Validate the cleaned version without space
    if re.match(r"^[1-9][0-9]{3}[A-Z]{2}$", clean_code):
        # Return in standard format with space
        return f"{clean_code[:4]} {clean_code[4:]}"

    return None


# Legacy compatibility functions for existing code
def is_valid_dutch_postal_code(postal_code):
    """Legacy compatibility function - returns boolean only.

    Args:
        postal_code (str): Postal code to validate

    Returns:
        bool: True if valid, False otherwise
    """
    result = validate_dutch_postal_code(postal_code)
    return result["valid"]
