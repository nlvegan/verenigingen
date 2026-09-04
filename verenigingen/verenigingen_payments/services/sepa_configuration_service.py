"""
SEPA Configuration Service

This service handles all SEPA-related configuration and settings validation.
Extracted from Direct Debit Batch system for better separation of concerns.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities

# Single source of truth for these defaults -- previously duplicated as bare
# literals at both the point of read and every downstream `.get(key, <literal>)`
# fallback (#535).
DEFAULT_BATCH_SIZE_LIMIT = 1000
DEFAULT_GRACE_PERIOD_DAYS = 5
DEFAULT_COLLECTION_DATE_OFFSET = 5


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
        # Load general settings (for company reference)
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        # Load payment/SEPA-specific settings
        payment_settings = get_payments_settings()

        # Load company information
        company = frappe.get_cached_doc("Company", verenigingen_settings.company)

        # Build settings dictionary
        settings = {
            # Organization information
            "organization_name": company.company_name,
            "organization_address": self._format_company_address(company),
            "country_code": "NL",  # Dutch organizations
            # SEPA credentials (from Payments Settings)
            "creditor_id": payment_settings.get(
                "creditor_id"
            ),  # Field name is creditor_id, not sepa_creditor_id
            "bic": payment_settings.get("company_bic"),
            "iban": payment_settings.get("company_iban"),
            # Processing settings
            # `or <default>`, not `getattr(doc, field, <default>)` / `doc.get(field, <default>)`:
            # a field declared on the doctype is a valid column on every loaded
            # Document, present in `doc.__dict__` whether or not anything was ever
            # written to `tabSingles` for it (measured on test_site_fresh: deleting
            # the row outright still leaves `getattr(doc, field, "MISSING")` ==
            # `None`, never "MISSING"). So a presence-based fallback never fires --
            # the resolved value can come back `None` (no row at all) or `0`
            # (something has since saved the Single, coercing the missing Int to 0),
            # but never the intended default either way. `sepa_batch_size_limit` is
            # never meaningfully 0 or unset in practice, so treating both as "not
            # configured" and falling back is safe -- and it is not just cosmetic: a
            # bare `None` reaches `len(invoices) > limits["max_batch_size"]` in
            # batch_validation_service.py and raises TypeError, not just "wrong
            # number".
            "batch_size_limit": payment_settings.get("sepa_batch_size_limit") or DEFAULT_BATCH_SIZE_LIMIT,
            # grace_period_days / collection_date_offset: #535 also named these two,
            # but neither gets a real field here. Both keys are consumed only inside
            # get_collection_date_settings() below, which -- confirmed by grepping
            # every caller -- never reads them back out: `minimum_notice_days` and
            # `maximum_notice_days` are the only keys anything downstream uses, and
            # both are fixed SEPA-scheme constants, not derived from these two.
            # Declaring real fields would make them look configurable while
            # remaining just as inert, and "grace_period_days" would additionally
            # collide in name and intent with the real, working
            # `Verenigingen Settings.default_grace_period_days` (a different
            # default, a different meaning -- membership termination grace, not
            # SEPA mandate/collection grace). Kept as named constants rather than
            # `getattr`/`.get()` reads of a field that does not exist, so this is no
            # longer #535's silent-default shape: it is a documented, intentional
            # constant, not a bug hiding behind a default parameter. #830 tracks
            # whether either should become a real, wired setting.
            "grace_period_days": DEFAULT_GRACE_PERIOD_DAYS,
            "collection_date_offset": DEFAULT_COLLECTION_DATE_OFFSET,
            # Validation settings
            # Note: an "enable_strict_validation" key used to live here, read from a
            # nonexistent "enable_strict_sepa_validation" field (#535). It had zero
            # consumers of its own (nothing read the resolved key either), so it was
            # removed rather than wired to a field nothing reads. See #466 for the
            # earlier discovery that no field with this intent exists on either
            # Settings doctype.
            "allow_zero_amounts": bool(payment_settings.get("allow_zero_amount_transactions")),
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

        # Dutch creditor ID format: NL + 2 check digits + ZZZ + variable length alphanumeric
        # Standard allows up to 11, but some banks issue longer IDs (up to 15)
        # Example: NL69ZZZ123456780000 (12 digits after ZZZ)
        import re

        pattern = r"^NL\d{2}ZZZ[A-Z0-9]{1,15}$"
        return bool(re.match(pattern, creditor_id.upper()))

    def get_collection_date_settings(self) -> Dict[str, int]:
        """
        Get collection date calculation settings.

        Returns:
            Dictionary with date offset settings
        """
        settings = self.get_sepa_settings()

        return {
            "offset_days": settings.get("collection_date_offset", DEFAULT_COLLECTION_DATE_OFFSET),
            "grace_period_days": settings.get("grace_period_days", DEFAULT_GRACE_PERIOD_DAYS),
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
            "max_batch_size": settings.get("batch_size_limit", DEFAULT_BATCH_SIZE_LIMIT),
            "max_amount_per_transaction": 999999.99,  # SEPA limit
            "max_total_batch_amount": 999999999.99,  # Practical limit
            "min_amount_per_transaction": 0.01 if not settings.get("allow_zero_amounts") else 0.00,
        }

    def refresh_settings_cache(self) -> None:
        """Force refresh of settings cache"""
        self._settings_cache = None


# Singleton instance for global use
sepa_config_service = SEPAConfigurationService()
