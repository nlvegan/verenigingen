"""
Mollie Integration Validators

Validation utilities for payments, IBANs, and other financial data.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _

from verenigingen.utils.validation.iban_validator import validate_iban as _canonical_validate_iban


class IBANValidator:
    """Validator for International Bank Account Numbers (IBAN)."""

    # IBAN country code lengths
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
        "VG": 24,
        "XK": 20,
    }

    @classmethod
    def validate_iban(cls, iban: str) -> bool:
        """
        Validate IBAN format and checksum.

        Delegates to the canonical ``validate_iban`` helper.  The bool return
        and calling conventions are unchanged; callers at lines 177, 321, 446
        and ``payment_processors.py:519`` all depend on this returning bool.

        Args:
            iban: IBAN string to validate

        Returns:
            True if IBAN is valid, False otherwise
        """
        # The canonical validate_iban is type-guarded (iban: str) and raises
        # FrappeTypeError on None/non-str, whereas this validator's contract is to
        # return False for any invalid input (callers depend on a plain bool). Guard
        # before delegating to preserve the pre-refactor behaviour.
        if not isinstance(iban, str):
            return False
        return _canonical_validate_iban(iban)["valid"]

    @classmethod
    def _validate_checksum(cls, iban: str) -> bool:
        """
        Validate IBAN checksum using mod-97 algorithm.

        Kept for external callers (e.g. ``test_mollie_validators.py``) that
        call this method directly.  Delegates to the canonical validator which
        runs the same streaming mod-97 algorithm.

        Note: unlike the pre-refactor implementation this method now accepts
        an un-normalized IBAN (spaces, lowercase) because it delegates to the
        canonical helper which normalises first.  The existing test corpus
        only passes already-normalised IBANs here, so behaviour is unchanged.
        """
        if not isinstance(iban, str):
            return False
        return _canonical_validate_iban(iban)["valid"]

    @classmethod
    def format_iban(cls, iban: str) -> str:
        """
        Format IBAN with standard spacing.

        Args:
            iban: Raw IBAN string

        Returns:
            Formatted IBAN with spaces every 4 characters
        """
        if not iban:
            return ""

        # Remove existing spaces and uppercase
        clean_iban = iban.replace(" ", "").upper()

        # Add spaces every 4 characters
        formatted = " ".join(clean_iban[i : i + 4] for i in range(0, len(clean_iban), 4))
        return formatted

    @classmethod
    def extract_bank_info(cls, iban: str) -> Dict[str, str]:
        """
        Extract bank information from IBAN.

        Args:
            iban: Valid IBAN string

        Returns:
            Dictionary with country_code, check_digits, bank_code, account_number
        """
        if not cls.validate_iban(iban):
            return {}

        clean_iban = iban.replace(" ", "").upper()

        result = {
            "country_code": clean_iban[:2],
            "check_digits": clean_iban[2:4],
            "bank_identifier": clean_iban[4:8] if len(clean_iban) > 8 else clean_iban[4:],
            "account_number": clean_iban[8:] if len(clean_iban) > 8 else "",
        }

        return result


class PaymentDataValidator:
    """Validator for payment data and business rules."""

    MIN_AMOUNT = Decimal("0.01")  # Minimum payment amount (1 cent)
    MAX_AMOUNT = Decimal("10000.00")  # Maximum single payment amount

    ALLOWED_CURRENCIES = ["EUR", "USD", "GBP"]  # Supported currencies

    # Payment type validation
    VALID_PAYMENT_TYPES = ["donation", "membership_dues", "event_registration", "volunteer_expense", "other"]

    @classmethod
    def validate_amount(cls, amount: Union[Decimal, float, str]) -> bool:
        """
        Validate payment amount.

        Args:
            amount: Payment amount to validate

        Returns:
            True if amount is valid, False otherwise
        """
        try:
            decimal_amount = Decimal(str(amount))

            # Check if positive
            if decimal_amount <= 0:
                return False

            # Check minimum and maximum
            if decimal_amount < cls.MIN_AMOUNT or decimal_amount > cls.MAX_AMOUNT:
                return False

            # Check decimal places (max 2 for EUR)
            if decimal_amount.as_tuple().exponent < -2:
                return False

            return True

        # InvalidOperation (a decimal.DecimalException / ArithmeticError) is
        # raised by Decimal(str(amount)) for non-numeric strings like "abc" and
        # for None ("None") — it is NOT a ValueError/TypeError, so it must be
        # listed explicitly or validate_amount crashes instead of returning False.
        except (ValueError, TypeError, OverflowError, InvalidOperation):
            return False

    @classmethod
    def validate_currency(cls, currency: str) -> bool:
        """
        Validate currency code.

        Args:
            currency: ISO currency code

        Returns:
            True if currency is supported, False otherwise
        """
        return currency and currency.upper() in cls.ALLOWED_CURRENCIES

    @classmethod
    def validate_payment_type(cls, payment_type: str) -> bool:
        """
        Validate payment type.

        Args:
            payment_type: Payment type string

        Returns:
            True if payment type is valid, False otherwise
        """
        return payment_type and payment_type.lower() in cls.VALID_PAYMENT_TYPES

    @classmethod
    def validate_email(cls, email: str) -> bool:
        """
        Validate email address format.

        Args:
            email: Email address to validate

        Returns:
            True if email format is valid, False otherwise
        """
        if not email:
            return False

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(email_pattern, email) is not None

    @classmethod
    def validate_dutch_postal_code(cls, postal_code: str) -> bool:
        """
        Validate Dutch postal code format - delegated to postal_code_validator.
        """
        from verenigingen.utils.validation.postal_code_validator import is_valid_dutch_postal_code

        return is_valid_dutch_postal_code(postal_code)

    @classmethod
    def validate_member_data(cls, member_data: Dict[str, Any]) -> List[str]:
        """
        Validate member data for payment processing.

        Args:
            member_data: Dictionary with member information

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Required fields
        required_fields = ["first_name", "last_name", "email"]
        for field in required_fields:
            if not member_data.get(field):
                errors.append(f"Missing required field: {field}")

        # Email validation
        if member_data.get("email") and not cls.validate_email(member_data["email"]):
            errors.append("Invalid email address format")

        # Postal code validation (if Dutch)
        postal_code = member_data.get("postal_code")
        country = member_data.get("country", "").upper()
        if country == "NL" and postal_code and not cls.validate_dutch_postal_code(postal_code):
            errors.append("Invalid Dutch postal code format")

        # IBAN validation (if provided)
        iban = member_data.get("iban")
        if iban and not IBANValidator.validate_iban(iban):
            errors.append("Invalid IBAN format")

        return errors

    @classmethod
    def validate_payment_data(cls, payment_data: Dict[str, Any]) -> List[str]:
        """
        Validate payment data before processing.

        Args:
            payment_data: Dictionary with payment information

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Amount validation
        amount = payment_data.get("amount")
        if not amount:
            errors.append("Payment amount is required")
        elif not cls.validate_amount(amount):
            errors.append(f"Invalid payment amount: {amount}")

        # Currency validation
        currency = payment_data.get("currency", "EUR")
        if not cls.validate_currency(currency):
            errors.append(f"Unsupported currency: {currency}")

        # Payment type validation
        payment_type = payment_data.get("payment_type")
        if payment_type and not cls.validate_payment_type(payment_type):
            errors.append(f"Invalid payment type: {payment_type}")

        # Description validation
        description = payment_data.get("description", "")
        if not description or len(description.strip()) < 3:
            errors.append("Payment description must be at least 3 characters")

        # Redirect URL validation
        redirect_url = payment_data.get("redirect_url", "")
        if redirect_url and not redirect_url.startswith(("http://", "https://")):
            errors.append("Invalid redirect URL format")

        return errors


class BusinessRuleValidator:
    """Validator for business-specific rules."""

    @classmethod
    def validate_membership_eligibility(cls, member_data: Dict[str, Any]) -> List[str]:
        """
        Validate member eligibility for membership.

        Args:
            member_data: Member information

        Returns:
            List of validation errors
        """
        errors = []

        # Age validation (must be 16+ for membership)
        birth_date = member_data.get("birth_date")
        if birth_date:
            from frappe.utils import get_datetime, getdate

            try:
                birth_date_obj = getdate(birth_date)
                # Site-tz today, not the server/process date: in the late-UTC window
                # the two name different calendar days, so an applicant turning 16
                # today is wrongly rejected as under-age (#628).
                today = getdate()
                age = (
                    today.year
                    - birth_date_obj.year
                    - ((today.month, today.day) < (birth_date_obj.month, birth_date_obj.day))
                )

                if age < 16:
                    errors.append("Member must be at least 16 years old")

            # frappe.utils.getdate raises frappe.exceptions.ValidationError (not a
            # ValueError/TypeError) for unparseable date strings, so it must be
            # caught explicitly or this crashes instead of reporting the error.
            except (ValueError, TypeError, frappe.exceptions.ValidationError):
                errors.append("Invalid birth date format")

        return errors

    @classmethod
    def validate_volunteer_eligibility(cls, member_data: Dict[str, Any]) -> List[str]:
        """
        Validate member eligibility for volunteer activities.

        Args:
            member_data: Member information

        Returns:
            List of validation errors
        """
        errors = []

        # Base eligibility check
        errors.extend(cls.validate_membership_eligibility(member_data))

        # Additional volunteer-specific checks could go here

        return errors


# Module-level convenience functions for backward compatibility
def validate_iban(iban: str) -> bool:
    """
    Validate IBAN format and checksum.

    This is a module-level convenience wrapper around IBANValidator.validate_iban.

    Args:
        iban: IBAN string to validate

    Returns:
        True if IBAN is valid, False otherwise
    """
    return IBANValidator.validate_iban(iban)


def format_iban(iban: str) -> str:
    """
    Format IBAN with standard spacing.

    This is a module-level convenience wrapper around IBANValidator.format_iban.

    Args:
        iban: Raw IBAN string

    Returns:
        Formatted IBAN with spaces every 4 characters
    """
    return IBANValidator.format_iban(iban)
