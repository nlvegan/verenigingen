"""
Financial Data Validator
Ensures financial data integrity and compliance

Features:
- IBAN validation with country-specific rules
- Amount precision and range validation
- Currency code validation (ISO 4217)
- Transaction reference format validation
- Balance consistency checks
"""

import decimal
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _


class FinancialValidator:
    """
    Comprehensive financial data validation

    Provides:
    - IBAN structure and checksum validation
    - Amount validation with precision rules
    - Currency validation against ISO 4217
    - Reference format validation
    - Balance reconciliation
    """

    # IBAN length by country (ISO 13616)
    IBAN_LENGTHS = {
        "AD": 24,
        "AE": 23,
        "AL": 28,
        "AT": 20,
        "AZ": 28,
        "BA": 20,
        "BE": 16,
        "BG": 22,
        "BH": 22,
        "BR": 29,
        "BY": 28,
        "CH": 21,
        "CR": 22,
        "CY": 28,
        "CZ": 24,
        "DE": 22,
        "DK": 18,
        "DO": 28,
        "EE": 20,
        "EG": 29,
        "ES": 24,
        "FI": 18,
        "FO": 18,
        "FR": 27,
        "GB": 22,
        "GE": 22,
        "GI": 23,
        "GL": 18,
        "GR": 27,
        "GT": 28,
        "HR": 21,
        "HU": 28,
        "IE": 22,
        "IL": 23,
        "IS": 26,
        "IT": 27,
        "JO": 30,
        "KW": 30,
        "KZ": 20,
        "LB": 28,
        "LC": 32,
        "LI": 21,
        "LT": 20,
        "LU": 20,
        "LV": 21,
        "MC": 27,
        "MD": 24,
        "ME": 22,
        "MK": 19,
        "MR": 27,
        "MT": 31,
        "MU": 30,
        "NL": 18,
        "NO": 15,
        "PK": 24,
        "PL": 28,
        "PS": 29,
        "PT": 25,
        "QA": 29,
        "RO": 24,
        "RS": 22,
        "SA": 24,
        "SE": 24,
        "SI": 19,
        "SK": 24,
        "SM": 27,
        "TN": 24,
        "TR": 26,
        "UA": 29,
        "VA": 22,
        "VG": 24,
        "XK": 20,
    }

    # ISO 4217 Currency codes
    VALID_CURRENCIES = {
        "EUR",
        "USD",
        "GBP",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "HRK",
        "RUB",
        "TRY",
        "CNY",
        "INR",
        "KRW",
        "SGD",
        "HKD",
        "TWD",
        "THB",
        "IDR",
        "MYR",
        "PHP",
        "MXN",
        "BRL",
        "ARS",
        "CLP",
        "COP",
        "PEN",
        "UYU",
        "ZAR",
        "ILS",
        "AED",
        "SAR",
    }

    def __init__(self):
        """Initialize financial validator"""
        self.validation_errors = []
        self.validation_warnings = []

    def validate_iban(self, iban: str) -> Tuple[bool, Optional[str]]:
        """
        Validate IBAN according to ISO 13616

        Args:
            iban: IBAN string to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not iban:
            return False, "IBAN is required"

        # Remove spaces and convert to uppercase
        iban = iban.replace(" ", "").upper()

        # Check basic format (2 letters, 2 digits, then alphanumeric)
        if not re.match(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$", iban):
            return False, "Invalid IBAN format"

        # Check country code
        country_code = iban[:2]
        if country_code not in self.IBAN_LENGTHS:
            return False, f"Unknown country code: {country_code}"

        # Check length
        expected_length = self.IBAN_LENGTHS[country_code]
        if len(iban) != expected_length:
            return (
                False,
                f"Invalid IBAN length for {country_code}: expected {expected_length}, got {len(iban)}",
            )

        # Validate checksum using mod 97 algorithm
        if not self._validate_iban_checksum(iban):
            return False, "Invalid IBAN checksum"

        return True, None

    def _validate_iban_checksum(self, iban: str) -> bool:
        """
        Validate IBAN checksum using mod 97 algorithm

        Args:
            iban: IBAN string (already sanitized)

        Returns:
            bool: True if checksum is valid
        """
        # Move first 4 characters to end
        rearranged = iban[4:] + iban[:4]

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric_string = ""
        for char in rearranged:
            if char.isdigit():
                numeric_string += char
            else:
                numeric_string += str(ord(char) - ord("A") + 10)

        # Calculate mod 97
        return int(numeric_string) % 97 == 1

    def validate_amount(
        self,
        amount: Any,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        precision: int = 2,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate monetary amount

        Args:
            amount: Amount to validate
            min_amount: Minimum allowed amount
            max_amount: Maximum allowed amount
            precision: Required decimal precision

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Convert to Decimal for precise financial calculations
            decimal_amount = Decimal(str(amount))

            # Check for NaN or Infinity
            if not decimal_amount.is_finite():
                return False, "Amount must be a finite number"

            # Check precision
            if decimal_amount.as_tuple().exponent < -precision:
                return False, f"Amount cannot have more than {precision} decimal places"

            # Check minimum
            if min_amount is not None and decimal_amount < Decimal(str(min_amount)):
                return False, f"Amount must be at least {min_amount}"

            # Check maximum
            if max_amount is not None and decimal_amount > Decimal(str(max_amount)):
                return False, f"Amount must not exceed {max_amount}"

            # Check for negative zero
            if decimal_amount == 0 and decimal_amount.is_signed():
                return False, "Negative zero is not allowed"

            return True, None

        except (ValueError, decimal.InvalidOperation) as e:
            return False, f"Invalid amount format: {str(e)}"

    def validate_currency(self, currency: str) -> Tuple[bool, Optional[str]]:
        """
        Validate currency code against ISO 4217

        Args:
            currency: Currency code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not currency:
            return False, "Currency code is required"

        currency = currency.upper()

        if len(currency) != 3:
            return False, "Currency code must be 3 characters"

        if currency not in self.VALID_CURRENCIES:
            return False, f"Invalid currency code: {currency}"

        return True, None

    def validate_transaction_reference(
        self, reference: str, pattern: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate transaction reference format

        Args:
            reference: Transaction reference to validate
            pattern: Optional regex pattern for validation

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not reference:
            return False, "Transaction reference is required"

        # Check length
        if len(reference) > 140:  # SEPA standard max length
            return False, "Transaction reference too long (max 140 characters)"

        # Check for invalid characters (SEPA allowed characters)
        sepa_pattern = r"^[a-zA-Z0-9/\-?:().,\'+ ]+$"
        if not re.match(sepa_pattern, reference):
            return False, "Transaction reference contains invalid characters"

        # Check custom pattern if provided
        if pattern and not re.match(pattern, reference):
            return False, "Transaction reference does not match required format"

        return True, None

    def validate_balance_consistency(
        self,
        opening_balance: Decimal,
        transactions: List[Dict[str, Any]],
        closing_balance: Decimal,
        tolerance: Decimal = Decimal("0.01"),
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate balance consistency across transactions

        Args:
            opening_balance: Starting balance
            transactions: List of transaction dictionaries with 'amount' and 'type' (debit/credit)
            closing_balance: Expected ending balance
            tolerance: Acceptable difference due to rounding

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            calculated_balance = Decimal(str(opening_balance))

            for tx in transactions:
                amount = Decimal(str(tx.get("amount", 0)))
                tx_type = tx.get("type", "").lower()

                if tx_type == "credit":
                    calculated_balance += amount
                elif tx_type == "debit":
                    calculated_balance -= amount
                else:
                    return False, f"Invalid transaction type: {tx_type}"

            difference = abs(calculated_balance - Decimal(str(closing_balance)))

            if difference > tolerance:
                return False, (
                    f"Balance mismatch: calculated {calculated_balance}, "
                    f"expected {closing_balance}, difference {difference}"
                )

            return True, None

        except Exception as e:
            return False, f"Balance validation error: {str(e)}"

    def validate_settlement_data(self, settlement: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive settlement data validation

        Args:
            settlement: Settlement data dictionary

        Returns:
            Dict with validation results
        """
        results = {"valid": True, "errors": [], "warnings": []}

        # Validate settlement ID
        if not settlement.get("id"):
            results["errors"].append("Settlement ID is required")
            results["valid"] = False

        # Validate reference
        if settlement.get("reference"):
            valid, error = self.validate_transaction_reference(settlement["reference"])
            if not valid:
                results["errors"].append(f"Settlement reference: {error}")
                results["valid"] = False

        # Validate amount
        if "amount" in settlement:
            valid, error = self.validate_amount(settlement["amount"], min_amount=Decimal("0.01"))
            if not valid:
                results["errors"].append(f"Settlement amount: {error}")
                results["valid"] = False

        # Validate currency
        if "currency" in settlement:
            valid, error = self.validate_currency(settlement["currency"])
            if not valid:
                results["errors"].append(f"Settlement currency: {error}")
                results["valid"] = False

        # Validate periods
        if "periods" in settlement:
            for period in settlement["periods"]:
                # Validate period dates
                if "from" in period and "until" in period:
                    try:
                        from_date = datetime.fromisoformat(period["from"].replace("Z", "+00:00"))
                        until_date = datetime.fromisoformat(period["until"].replace("Z", "+00:00"))

                        if from_date >= until_date:
                            results["warnings"].append(
                                "Invalid period range: {} to {}".format(period["from"], period["until"])
                            )
                    except ValueError as e:
                        results["errors"].append(f"Invalid period dates: {str(e)}")
                        results["valid"] = False

        return results

    def validate_payment_data(self, payment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate payment data structure

        Args:
            payment: Payment data dictionary

        Returns:
            Dict with validation results
        """
        results = {"valid": True, "errors": [], "warnings": []}

        # Required fields
        required_fields = ["id", "amount", "currency", "status"]
        for field in required_fields:
            if field not in payment:
                results["errors"].append(f"Missing required field: {field}")
                results["valid"] = False

        # Validate amount if present
        if "amount" in payment:
            valid, error = self.validate_amount(
                payment["amount"]["value"] if isinstance(payment["amount"], dict) else payment["amount"],
                min_amount=Decimal("0.01"),
                max_amount=Decimal("999999.99"),
            )
            if not valid:
                results["errors"].append(f"Payment amount: {error}")
                results["valid"] = False

        # Validate currency
        if "currency" in payment:
            currency = (
                payment["amount"]["currency"] if isinstance(payment["amount"], dict) else payment["currency"]
            )
            valid, error = self.validate_currency(currency)
            if not valid:
                results["errors"].append(f"Payment currency: {error}")
                results["valid"] = False

        # Validate IBAN if present
        if "iban" in payment:
            valid, error = self.validate_iban(payment["iban"])
            if not valid:
                results["warnings"].append(f"Payment IBAN: {error}")

        # Validate metadata
        if "metadata" in payment and isinstance(payment["metadata"], dict):
            # Check for sensitive data in metadata
            sensitive_keys = ["password", "pin", "cvv", "secret"]
            for key in payment["metadata"].keys():
                if any(sensitive in key.lower() for sensitive in sensitive_keys):
                    results["warnings"].append(f"Potential sensitive data in metadata: {key}")

        return results

    def get_validation_report(self) -> Dict[str, Any]:
        """
        Get comprehensive validation report

        Returns:
            Dict with validation statistics
        """
        return {
            "total_errors": len(self.validation_errors),
            "total_warnings": len(self.validation_warnings),
            "errors": self.validation_errors[-10:],  # Last 10 errors
            "warnings": self.validation_warnings[-10:],  # Last 10 warnings
            "timestamp": datetime.now().isoformat(),
        }
