"""
Bank-Specific SEPA Validation for Dutch Banks

This module provides bank-specific validation logic for ING Bank, Triodos Bank,
and other Dutch banks. Each bank may have specific requirements beyond the
standard SEPA specification.

Author: Verenigingen Development Team
Date: August 2025
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

import frappe

from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager


class BankSpecificValidator:
    """Validator for bank-specific SEPA requirements"""

    def __init__(self):
        self.config_manager = get_sepa_config_manager()

    def validate_transaction_for_bank(
        self, transaction_data: Dict[str, Any], bank_bic: str
    ) -> Dict[str, Any]:
        """
        Validate a transaction against bank-specific requirements

        Args:
            transaction_data: Transaction details (amount, member, mandate, etc.)
            bank_bic: BIC code of the bank (e.g., INGBNL2A, TRIONL2U)

        Returns:
            Dict with validation results
        """
        bank_config = self.config_manager.get_bank_specific_config(bank_bic)
        errors = []
        warnings = []

        # Validate remittance information length
        if transaction_data.get("remittance_info"):
            max_length = bank_config.get("max_remittance_length", 140)
            if len(transaction_data["remittance_info"]) > max_length:
                errors.append(f"Remittance info exceeds {max_length} characters for {bank_config['name']}")

        # Validate structured address requirements
        if bank_config.get("requires_structured_address", False):
            address_validation = self._validate_structured_address(transaction_data, bank_bic)
            errors.extend(address_validation["errors"])
            warnings.extend(address_validation["warnings"])

        # ING-specific validations
        if bank_bic == "INGBNL2A":
            ing_validation = self._validate_ing_specific(transaction_data)
            errors.extend(ing_validation["errors"])
            warnings.extend(ing_validation["warnings"])

        # Triodos-specific validations
        elif bank_bic == "TRIONL2U":
            triodos_validation = self._validate_triodos_specific(transaction_data)
            errors.extend(triodos_validation["errors"])
            warnings.extend(triodos_validation["warnings"])

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "bank_name": bank_config["name"],
        }

    def _validate_structured_address(self, transaction_data: Dict[str, Any], bank_bic: str) -> Dict[str, Any]:
        """Validate structured address requirements (mandatory as of Nov 2025)"""
        errors = []
        warnings = []

        debtor_address = transaction_data.get("debtor_address", {})

        # Town name and country are mandatory for structured addresses
        if not debtor_address.get("town"):
            errors.append("Town name (TwnNm) is mandatory for structured addresses")

        if not debtor_address.get("country"):
            errors.append("Country code (Ctry) is mandatory for structured addresses")

        # Validate address line limits (max 2 address lines, 70 chars each)
        address_lines = [debtor_address.get("address_line_1", ""), debtor_address.get("address_line_2", "")]

        for i, line in enumerate(address_lines):
            if line and len(line) > 70:
                errors.append(f"Address line {i+1} exceeds 70 characters")

        return {"errors": errors, "warnings": warnings}

    def _validate_ing_specific(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """ING Bank specific validations"""
        errors = []
        warnings = []

        # ING prefers structured addresses
        debtor_address = transaction_data.get("debtor_address", {})
        if not debtor_address:
            warnings.append("ING Bank prefers structured address information")

        # Validate mandate ID length (ING specific limit)
        mandate_id = transaction_data.get("mandate_id", "")
        if len(mandate_id) > 35:
            errors.append("Mandate ID exceeds 35 characters (ING limit)")

        return {"errors": errors, "warnings": warnings}

    def _validate_triodos_specific(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Triodos Bank specific validations"""
        errors = []
        warnings = []

        # Triodos has ethical screening requirements
        # This is more of a business rule than technical validation
        if transaction_data.get("purpose_code") == "GOVI":
            warnings.append(
                "Government-related transactions may require additional ethical screening by Triodos"
            )

        # Validate mandate ID format for Triodos
        mandate_id = transaction_data.get("mandate_id", "")
        if mandate_id and not mandate_id.replace("-", "").replace("_", "").isalnum():
            warnings.append("Triodos prefers alphanumeric mandate IDs (with optional hyphens/underscores)")

        return {"errors": errors, "warnings": warnings}

    def get_supported_banks(self) -> List[Dict[str, str]]:
        """Get list of supported banks with specific validation"""
        return [
            {"bic": "INGBNL2A", "name": "ING Bank N.V.", "country": "NL"},
            {"bic": "TRIONL2U", "name": "Triodos Bank N.V.", "country": "NL"},
            {"bic": "ABNANL2A", "name": "ABN AMRO Bank N.V.", "country": "NL"},
            {"bic": "RABONL2U", "name": "Rabobank", "country": "NL"},
        ]


def get_bank_specific_validator() -> BankSpecificValidator:
    """Factory function to get bank-specific validator"""
    return BankSpecificValidator()


@frappe.whitelist()
def validate_sepa_transaction_for_bank(transaction_data, bank_bic):
    """
    API endpoint to validate SEPA transaction for specific bank

    Args:
        transaction_data: JSON string or dict with transaction details
        bank_bic: BIC code of the target bank

    Returns:
        Validation results
    """
    try:
        if isinstance(transaction_data, str):
            transaction_data = frappe.parse_json(transaction_data)

        validator = get_bank_specific_validator()
        result = validator.validate_transaction_for_bank(transaction_data, bank_bic)

        return result

    except Exception as e:
        frappe.log_error(f"Bank-specific validation error: {str(e)}", "Bank Validation Error")
        return {"valid": False, "errors": [f"Validation error: {str(e)}"], "warnings": []}


@frappe.whitelist()
def get_bank_validation_requirements(bank_bic):
    """Get validation requirements for a specific bank"""
    try:
        config_manager = get_sepa_config_manager()
        bank_config = config_manager.get_bank_specific_config(bank_bic)

        return {
            "success": True,
            "bank_name": bank_config["name"],
            "requirements": {
                "structured_address": bank_config.get("requires_structured_address", False),
                "max_remittance_length": bank_config.get("max_remittance_length", 140),
                "mandate_id_max_length": bank_config.get("mandate_id_max_length", 35),
                "creditor_id_validation": bank_config.get("creditor_id_validation", "standard"),
                "supports_supplementary_data": bank_config.get("supports_supplementary_data", False),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
