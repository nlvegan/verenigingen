"""
SEPA Configuration Service

This service handles all SEPA-related configuration and settings validation.
Extracted from Direct Debit Batch system for better separation of concerns.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities


class SEPAConfigurationService:
    """Service for managing SEPA configuration and settings"""

    def __init__(self):
        self._settings_cache = None

    def get_sepa_settings(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get SEPA settings with caching.

        Args:
            force_refresh: Force refresh of cached settings

        Returns:
            Dictionary containing SEPA settings
        """
        if self._settings_cache is None or force_refresh:
            self._settings_cache = self._load_sepa_settings()

        return self._settings_cache

    def _load_sepa_settings(self) -> Dict[str, Any]:
        """
        Load SEPA settings from various sources.

        Returns:
            Consolidated SEPA settings dictionary
        """
        # Load from Verenigingen Settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")

        # Load company information
        company = frappe.get_cached_doc("Company", verenigingen_settings.company)

        # Build settings dictionary
        settings = {
            # Organization information
            "organization_name": company.company_name,
            "organization_address": self._format_company_address(company),
            "country_code": "NL",  # Dutch organizations
            # SEPA credentials
            "creditor_id": verenigingen_settings.get("sepa_creditor_id"),
            "bic": verenigingen_settings.get("company_bic"),
            "iban": verenigingen_settings.get("company_iban"),
            # Processing settings
            "batch_size_limit": getattr(verenigingen_settings, "sepa_batch_size_limit", 1000),
            "grace_period_days": getattr(verenigingen_settings, "grace_period_days", 5),
            "collection_date_offset": getattr(verenigingen_settings, "collection_date_offset", 5),
            # Validation settings
            "enable_strict_validation": getattr(verenigingen_settings, "enable_strict_sepa_validation", True),
            "allow_zero_amounts": getattr(verenigingen_settings, "allow_zero_amount_transactions", False),
            # Company reference
            "company": verenigingen_settings.company,
        }

        return settings

    def _format_company_address(self, company) -> str:
        """
        Format company address for SEPA XML.

        Args:
            company: Company document

        Returns:
            Formatted address string
        """
        address_parts = []

        if hasattr(company, "address_line_1") and company.address_line_1:
            address_parts.append(company.address_line_1)

        if hasattr(company, "address_line_2") and company.address_line_2:
            address_parts.append(company.address_line_2)

        if hasattr(company, "city") and company.city:
            city_part = company.city
            if hasattr(company, "pincode") and company.pincode:
                city_part = f"{company.pincode} {city_part}"
            address_parts.append(city_part)

        return ", ".join(address_parts) if address_parts else "Address not configured"

    def validate_sepa_configuration(self) -> Dict[str, Any]:
        """
        Validate SEPA configuration completeness.

        Returns:
            Validation result with errors and warnings
        """
        settings = self.get_sepa_settings()
        errors = []
        warnings = []

        # Required fields validation
        required_fields = {
            "creditor_id": "SEPA Creditor ID",
            "bic": "Company BIC",
            "iban": "Company IBAN",
            "organization_name": "Organization Name",
        }

        for field, display_name in required_fields.items():
            if not settings.get(field):
                errors.append(f"{display_name} is required for SEPA processing")

        # IBAN validation
        if settings.get("iban"):
            if not SEPAUtilities.validate_dutch_iban(settings["iban"]):
                errors.append("Company IBAN format is invalid")

        # BIC validation
        if settings.get("bic") and settings.get("iban"):
            derived_bic = SEPAUtilities.get_bic_from_iban(settings["iban"])
            if derived_bic and derived_bic != settings["bic"]:
                warnings.append(f"BIC might not match IBAN. Expected: {derived_bic}")

        # Creditor ID format validation
        if settings.get("creditor_id"):
            if not self._validate_creditor_id_format(settings["creditor_id"]):
                errors.append("SEPA Creditor ID format is invalid")

        return {"is_valid": len(errors) == 0, "errors": errors, "warnings": warnings, "settings": settings}

    def _validate_creditor_id_format(self, creditor_id: str) -> bool:
        """
        Validate SEPA Creditor ID format.

        Args:
            creditor_id: Creditor ID to validate

        Returns:
            True if format is valid
        """
        if not creditor_id:
            return False

        # Dutch creditor ID format: NL + 2 digits + ZZZ + 9 alphanumeric
        import re

        pattern = r"^NL\d{2}ZZZ[A-Z0-9]{9}$"
        return bool(re.match(pattern, creditor_id.upper()))

    def get_collection_date_settings(self) -> Dict[str, int]:
        """
        Get collection date calculation settings.

        Returns:
            Dictionary with date offset settings
        """
        settings = self.get_sepa_settings()

        return {
            "offset_days": settings.get("collection_date_offset", 5),
            "grace_period_days": settings.get("grace_period_days", 5),
            "minimum_notice_days": 1,  # SEPA minimum
            "maximum_notice_days": 35,  # SEPA maximum
        }

    def is_test_mode(self) -> bool:
        """
        Check if SEPA processing is in test mode.

        Returns:
            True if in test mode
        """
        settings = self.get_sepa_settings()
        return settings.get("test_mode", False)

    def get_batch_processing_limits(self) -> Dict[str, int]:
        """
        Get batch processing limits and constraints.

        Returns:
            Dictionary with processing limits
        """
        settings = self.get_sepa_settings()

        return {
            "max_batch_size": settings.get("batch_size_limit", 1000),
            "max_amount_per_transaction": 999999.99,  # SEPA limit
            "max_total_batch_amount": 999999999.99,  # Practical limit
            "min_amount_per_transaction": 0.01 if not settings.get("allow_zero_amounts") else 0.00,
        }

    def refresh_settings_cache(self) -> None:
        """Force refresh of settings cache"""
        self._settings_cache = None


# Singleton instance for global use
sepa_config_service = SEPAConfigurationService()
