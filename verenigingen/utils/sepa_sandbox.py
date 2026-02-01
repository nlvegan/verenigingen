# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
SEPA Sandbox Mode Utility.

Provides a sandbox mode for safe SEPA testing that prevents
accidental production bank submissions.

Configuration (site_config.json):
    sepa_sandbox_mode: true/false

When sandbox mode is enabled:
    - All Message IDs are prefixed with "TEST-"
    - Bank uploads are blocked with clear message
    - Test IBANs can be generated for testing

Example usage:
    >>> from verenigingen.utils.sepa_sandbox import get_sandbox
    >>> sandbox = get_sandbox()
    >>> if sandbox.is_sandbox_mode():
    ...     msg_id = sandbox.get_sandbox_msg_id("BATCH-001")
    ...     result = sandbox.check_upload_allowed()
    ...     if not result.allowed:
    ...         print(result.message)
"""
import random
import string
from dataclasses import dataclass
from typing import Dict, Optional

import frappe


@dataclass
class SandboxCheckResult:
    """
    Result of checking if bank upload is allowed.

    Attributes:
        allowed: Whether the upload is allowed
        message: Human-readable message explaining the result
        sandbox_mode: Whether sandbox mode is currently enabled
    """

    allowed: bool
    message: str
    sandbox_mode: bool


class SEPASandbox:
    """
    SEPA Sandbox Mode Manager.

    When sandbox mode is enabled:
    - All Message IDs are prefixed with "TEST-"
    - Bank uploads are blocked with clear message
    - Test IBANs can be generated for testing

    Configuration:
        Set sepa_sandbox_mode: true in site_config.json to enable.
        Sandbox mode is OFF by default (production-safe).
    """

    TEST_PREFIX = "TEST-"

    # Known test IBAN bases per country (valid format)
    # These are commonly used test IBANs from various banks
    TEST_IBAN_BASES: Dict[str, str] = {
        "NL": "NL91ABNA0417164300",  # Dutch test IBAN (18 chars)
        "DE": "DE89370400440532013000",  # German test IBAN (22 chars)
        "BE": "BE68539007547034",  # Belgian test IBAN (16 chars)
        "FR": "FR1420041010050500013M02606",  # French test IBAN (27 chars)
    }

    def is_sandbox_mode(self) -> bool:
        """
        Check if sandbox mode is enabled.

        Reads the sepa_sandbox_mode setting from site_config.json.
        Defaults to False (production-safe).

        Returns:
            bool: True if sandbox mode is enabled, False otherwise
        """
        return frappe.conf.get("sepa_sandbox_mode", False)

    def get_sandbox_msg_id(self, original_id: str) -> str:
        """
        Get message ID with sandbox prefix if in sandbox mode.

        In sandbox mode, prefixes the message ID with "TEST-" to make
        it clearly identifiable as a test message. This helps prevent
        confusion if test data accidentally reaches production systems.

        Args:
            original_id: Original message ID

        Returns:
            str: Prefixed ID in sandbox mode, original otherwise.
                 Already prefixed IDs are not double-prefixed.
        """
        if self.is_sandbox_mode():
            if not original_id.startswith(self.TEST_PREFIX):
                return f"{self.TEST_PREFIX}{original_id}"
        return original_id

    def check_upload_allowed(self) -> SandboxCheckResult:
        """
        Check if bank upload is allowed.

        In sandbox mode, uploads are blocked to prevent accidental
        production bank submissions during testing.

        Returns:
            SandboxCheckResult: Result indicating if upload is allowed,
                               with explanatory message and sandbox status.
        """
        if self.is_sandbox_mode():
            return SandboxCheckResult(
                allowed=False,
                message=(
                    "Bank upload blocked: SEPA sandbox mode is enabled. "
                    "Disable sepa_sandbox_mode in site_config.json for production uploads."
                ),
                sandbox_mode=True,
            )

        return SandboxCheckResult(
            allowed=True,
            message="Production mode - bank upload allowed",
            sandbox_mode=False,
        )

    def generate_test_iban(self, country: str = "NL") -> str:
        """
        Generate a test IBAN for the specified country.

        Uses known test IBAN bases with a random suffix for uniqueness.
        The generated IBANs follow the correct format for each country
        but may not pass full IBAN validation (check digit calculation).

        Args:
            country: ISO 3166-1 alpha-2 country code (NL, DE, BE, FR).
                    Defaults to NL. Case-insensitive.

        Returns:
            str: A valid-format test IBAN for the specified country.
                For unknown countries, returns a fallback format.
        """
        country = country.upper()

        if country in self.TEST_IBAN_BASES:
            # Use known test IBAN base with random suffix variation
            base = self.TEST_IBAN_BASES[country]
            # Modify last 4 digits for uniqueness while preserving length
            suffix = "".join(random.choices(string.digits, k=4))
            return base[:-4] + suffix

        # Fallback: generate basic format for unknown country
        # Format: country (2) + check digits (2) + 16 random digits = 20 chars
        # This won't have valid check digits but follows a basic format
        return f"{country}00{''.join(random.choices(string.digits, k=16))}"


# Singleton instance
_sandbox: Optional[SEPASandbox] = None


def get_sandbox() -> SEPASandbox:
    """
    Get the singleton SEPASandbox instance.

    Returns:
        SEPASandbox: Shared sandbox instance

    Example:
        >>> sandbox = get_sandbox()
        >>> if sandbox.is_sandbox_mode():
        ...     print("Running in sandbox mode")
    """
    global _sandbox
    if _sandbox is None:
        _sandbox = SEPASandbox()
    return _sandbox
