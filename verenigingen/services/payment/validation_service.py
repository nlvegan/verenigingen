"""
Payment Validation Service

Orchestrates payment validation logic by delegating to canonical validators.
Provides consistent error formatting and validation patterns across payment operations.

This service does NOT reimplement validation logic - it orchestrates existing validators:
- verenigingen.utils.validation.iban_validator (European IBAN validation)
- verenigingen.utils.services.sepa_service (SEPA-specific validation)
- Frappe payment method validation

Design Principles:
- Thin orchestration layer (delegates to existing validators)
- Consistent error response format using Result pattern
- Context-aware error messages for better UX
- Type-safe with comprehensive type hints
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import frappe
from frappe import _


@dataclass
class ValidationResult:
    """
    Standardized validation result using Result pattern.

    Replaces inconsistent error handling (exceptions, None, bool returns)
    with explicit success/failure signaling.
    """

    valid: bool
    message: str = ""
    errors: List[str] = None
    data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @classmethod
    def success(cls, message: str = "", data: Optional[Dict[str, Any]] = None) -> "ValidationResult":
        """Create successful validation result"""
        return cls(valid=True, message=message, data=data or {})

    @classmethod
    def failure(cls, message: str, errors: Optional[List[str]] = None) -> "ValidationResult":
        """Create failed validation result"""
        return cls(valid=False, message=message, errors=errors or [message])


class PaymentValidationService:
    """
    Payment validation orchestration service.

    Consolidates payment validation logic without reimplementing validators.
    Delegates to canonical validators for actual validation logic.
    """

    # Payment amount bounds (configurable via settings in future)
    MIN_PAYMENT_AMOUNT = 0.01
    MAX_PAYMENT_AMOUNT = 100000.00  # €100k reasonable max for association payments

    @staticmethod
    def validate_iban_with_context(
        iban: str, context: str = "payment", auto_format: bool = True
    ) -> ValidationResult:
        """
        Validate IBAN with context-appropriate error messages.

        Delegates to: verenigingen.utils.validation.iban_validator.validate_iban()

        Args:
            iban: IBAN to validate
            context: Context for error messages ("payment", "sepa_mandate", "member")
            auto_format: Whether to format IBAN in response data

        Returns:
            ValidationResult with formatted IBAN in data if valid

        Examples:
            >>> result = PaymentValidationService.validate_iban_with_context("NL91ABNA0417164300")
            >>> result.valid
            True
            >>> result.data["formatted_iban"]
            'NL91 ABNA 0417 1643 00'
        """
        from verenigingen.utils.validation.iban_validator import format_iban, validate_iban

        if not iban or not iban.strip():
            return ValidationResult.failure(_("IBAN is required for {0}").format(context))

        # Delegate to canonical IBAN validator
        validation_result = validate_iban(iban)

        if not validation_result["valid"]:
            error_message = validation_result["message"]

            # Enhance error messages based on context
            enhanced_message = PaymentValidationService._enhance_iban_error_message(error_message, context)

            return ValidationResult.failure(enhanced_message)

        # Format IBAN if requested
        data = {}
        if auto_format:
            try:
                data["formatted_iban"] = format_iban(iban)
                data["iban_clean"] = iban.replace(" ", "").upper()
            except Exception as e:
                frappe.log_error(f"IBAN formatting failed for {iban}: {e}")
                data["formatted_iban"] = iban
                data["iban_clean"] = iban

        return ValidationResult.success(_("IBAN is valid"), data=data)

    @staticmethod
    def _enhance_iban_error_message(error_message: str, context: str) -> str:
        """
        Enhance IBAN error messages with context-specific guidance.

        Args:
            error_message: Original error from validator
            context: Validation context

        Returns:
            Enhanced user-friendly error message
        """
        error_lower = error_message.lower()

        # Checksum errors - most common user mistake
        if "checksum" in error_lower or "invalid" in error_lower:
            return _(
                "The IBAN you entered appears to be incorrect. "
                "Please double-check the account number and try again. "
                "Common issues include typos or missing/extra digits."
            )

        # Length errors
        if "too short" in error_lower:
            return _("The IBAN you entered is too short. " "Please enter the complete IBAN number.")

        if "must be" in error_lower and "characters" in error_lower:
            # Country-specific length message is already helpful
            return error_message

        # Character errors
        if "invalid characters" in error_lower:
            return _(
                "The IBAN contains invalid characters. " "IBANs should only contain letters and numbers."
            )

        # Unsupported country
        if "unsupported country" in error_lower:
            return _(
                "The country code in this IBAN is not supported. "
                "We currently support European SEPA countries. "
                "Please contact support if you need help with international payments."
            )

        # Default: return original message
        return error_message

    @staticmethod
    def validate_bank_details(
        iban: str,
        bic: Optional[str] = None,
        account_holder_name: Optional[str] = None,
        auto_derive_bic: bool = True,
        require_bic: bool = False,
    ) -> ValidationResult:
        """
        Comprehensive bank detail validation including IBAN, BIC, and holder name.

        Orchestrates:
        - iban_validator.validate_iban() for IBAN validation
        - SEPAService.derive_bic_from_iban() for BIC derivation (Dutch IBANs)

        Args:
            iban: IBAN to validate
            bic: BIC code (optional, can be auto-derived for Dutch IBANs)
            account_holder_name: Account holder name (optional)
            auto_derive_bic: Attempt to derive BIC from IBAN if not provided
            require_bic: Whether BIC is mandatory

        Returns:
            ValidationResult with validated/derived bank details in data

        Examples:
            >>> result = PaymentValidationService.validate_bank_details(
            ...     iban="NL91ABNA0417164300",
            ...     auto_derive_bic=True
            ... )
            >>> result.valid
            True
            >>> result.data["bic"]
            'ABNANL2A'
        """
        errors = []
        data = {}

        # Step 1: Validate IBAN
        iban_result = PaymentValidationService.validate_iban_with_context(iban, context="bank_details")

        if not iban_result.valid:
            errors.extend(iban_result.errors)
        else:
            data.update(iban_result.data)

        # Step 2: Validate/derive BIC
        if iban_result.valid:
            if auto_derive_bic and not bic:
                from verenigingen.utils.validation.iban_validator import derive_bic_from_iban

                try:
                    derived_bic = derive_bic_from_iban(iban)
                    if derived_bic:
                        data["bic"] = derived_bic
                        data["bic_derived"] = True
                    elif require_bic:
                        errors.append(_("BIC is required and could not be automatically derived from IBAN"))
                except Exception as e:
                    frappe.log_error(f"BIC derivation failed for {iban}: {e}")
                    if require_bic:
                        errors.append(_("BIC is required"))
            elif bic:
                # Validate provided BIC format (basic check)
                bic_validation = PaymentValidationService._validate_bic_format(bic)
                if not bic_validation.valid:
                    errors.extend(bic_validation.errors)
                else:
                    data["bic"] = bic.upper()
                    data["bic_derived"] = False
            elif require_bic:
                errors.append(_("BIC is required"))

        # Step 3: Validate account holder name (basic check)
        if account_holder_name:
            holder_validation = PaymentValidationService._validate_account_holder_name(account_holder_name)
            if not holder_validation.valid:
                errors.extend(holder_validation.errors)
            else:
                data["account_holder_name"] = account_holder_name.strip()

        # Return result
        if errors:
            return ValidationResult.failure(_("Bank details validation failed"), errors=errors)

        return ValidationResult.success(_("Bank details are valid"), data=data)

    @staticmethod
    def _validate_bic_format(bic: str) -> ValidationResult:
        """
        Validate BIC format (basic format check).

        BIC format: 4 letters (bank) + 2 letters (country) + 2 alphanumeric (location) + optional 3 alphanumeric (branch)
        Examples: ABNANL2A, INGBNL2AXXX

        Args:
            bic: BIC code to validate

        Returns:
            ValidationResult indicating if BIC format is valid
        """
        import re

        if not bic or not bic.strip():
            return ValidationResult.failure(_("BIC is empty"))

        bic = bic.strip().upper()

        # BIC format: 8 or 11 characters
        if len(bic) not in [8, 11]:
            return ValidationResult.failure(_("BIC must be 8 or 11 characters long"))

        # Pattern: 4 letters + 2 letters + 2 alphanumeric + (optional 3 alphanumeric)
        if not re.match(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$", bic):
            return ValidationResult.failure(_("Invalid BIC format. Expected format: ABNANL2A or ABNANL2AXXX"))

        return ValidationResult.success(_("BIC format is valid"))

    @staticmethod
    def _validate_account_holder_name(name: str) -> ValidationResult:
        """
        Validate account holder name (basic sanity checks).

        Args:
            name: Account holder name

        Returns:
            ValidationResult indicating if name is valid
        """
        if not name or not name.strip():
            return ValidationResult.failure(_("Account holder name is empty"))

        name = name.strip()

        # Minimum length check
        if len(name) < 2:
            return ValidationResult.failure(_("Account holder name is too short (minimum 2 characters)"))

        # Maximum length check (SEPA mandate spec)
        if len(name) > 70:
            return ValidationResult.failure(_("Account holder name is too long (maximum 70 characters)"))

        # Check for suspicious patterns (all numbers, special characters only)
        import re

        if re.match(r"^\d+$", name):
            return ValidationResult.failure(_("Account holder name cannot be only numbers"))

        return ValidationResult.success(_("Account holder name is valid"))

    @staticmethod
    def validate_payment_method(method: str) -> ValidationResult:
        """
        Validate payment method exists and is enabled.

        Args:
            method: Mode of Payment name

        Returns:
            ValidationResult with payment method details in data

        Examples:
            >>> result = PaymentValidationService.validate_payment_method("Cash")
            >>> result.valid
            True
            >>> result.data["method_name"]
            'Cash'
        """
        if not method or not method.strip():
            return ValidationResult.failure(_("Payment method is required"))

        method = method.strip()

        # Check if Mode of Payment exists
        if not frappe.db.exists("Mode of Payment", method):
            return ValidationResult.failure(_("Payment method '{0}' does not exist").format(method))

        # Check if payment method is enabled
        mode_of_payment = frappe.get_cached_doc("Mode of Payment", method)

        if mode_of_payment.enabled == 0:
            return ValidationResult.failure(_("Payment method '{0}' is disabled").format(method))

        return ValidationResult.success(
            _("Payment method is valid"),
            data={
                "method_name": method,
                "method_type": mode_of_payment.type if hasattr(mode_of_payment, "type") else None,
            },
        )

    @staticmethod
    def validate_payment_amount(
        amount: float,
        context: str = "payment",
        allow_zero: bool = False,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
    ) -> ValidationResult:
        """
        Validate payment amount is positive and within reasonable bounds.

        Args:
            amount: Payment amount to validate
            context: Context for error messages
            allow_zero: Whether zero amounts are allowed
            min_amount: Custom minimum (overrides default)
            max_amount: Custom maximum (overrides default)

        Returns:
            ValidationResult with normalized amount in data

        Examples:
            >>> result = PaymentValidationService.validate_payment_amount(25.00)
            >>> result.valid
            True
            >>> result.data["amount"]
            Decimal('25.00')
        """
        # Use custom bounds or defaults
        min_bound = min_amount if min_amount is not None else PaymentValidationService.MIN_PAYMENT_AMOUNT
        max_bound = max_amount if max_amount is not None else PaymentValidationService.MAX_PAYMENT_AMOUNT

        # Handle None/empty
        if amount is None:
            return ValidationResult.failure(_("Payment amount is required for {0}").format(context))

        # Convert to Decimal for precise validation
        try:
            amount_decimal = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            return ValidationResult.failure(
                _("Invalid payment amount: '{0}' is not a valid number").format(amount)
            )

        # Check for negative
        if amount_decimal < 0:
            return ValidationResult.failure(_("Payment amount cannot be negative"))

        # Check for zero (if not allowed)
        if amount_decimal == 0 and not allow_zero:
            return ValidationResult.failure(_("Payment amount must be greater than zero"))

        # Check minimum
        if amount_decimal < Decimal(str(min_bound)) and not (allow_zero and amount_decimal == 0):
            return ValidationResult.failure(_("Payment amount must be at least {0}").format(min_bound))

        # Check maximum
        if amount_decimal > Decimal(str(max_bound)):
            return ValidationResult.failure(_("Payment amount cannot exceed {0}").format(max_bound))

        # Check for excessive decimal places (max 2 for currency)
        if amount_decimal.as_tuple().exponent < -2:
            return ValidationResult.failure(_("Payment amount can have maximum 2 decimal places"))

        return ValidationResult.success(
            _("Payment amount is valid"),
            data={"amount": amount_decimal, "amount_formatted": f"{amount_decimal:.2f}"},
        )


# Factory function for service access
def get_payment_validation_service() -> PaymentValidationService:
    """
    Get PaymentValidationService instance (singleton pattern).

    Returns:
        PaymentValidationService instance
    """
    return PaymentValidationService()


# Convenience API endpoints for whitelisted access
@frappe.whitelist()
def validate_iban_api(iban: str, context: str = "payment") -> Dict[str, Any]:
    """
    API endpoint for IBAN validation.

    Args:
        iban: IBAN to validate
        context: Validation context

    Returns:
        dict with validation result
    """
    service = get_payment_validation_service()
    result = service.validate_iban_with_context(iban, context)

    return {"valid": result.valid, "message": result.message, "errors": result.errors, "data": result.data}


@frappe.whitelist()
def validate_bank_details_api(
    iban: str, bic: Optional[str] = None, account_holder_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    API endpoint for comprehensive bank details validation.

    Args:
        iban: IBAN to validate
        bic: Optional BIC code
        account_holder_name: Optional account holder name

    Returns:
        dict with validation result
    """
    service = get_payment_validation_service()
    result = service.validate_bank_details(iban, bic, account_holder_name)

    return {"valid": result.valid, "message": result.message, "errors": result.errors, "data": result.data}


@frappe.whitelist()
def validate_payment_method_api(method: str) -> Dict[str, Any]:
    """
    API endpoint for payment method validation.

    Args:
        method: Mode of Payment name

    Returns:
        dict with validation result
    """
    service = get_payment_validation_service()
    result = service.validate_payment_method(method)

    return {"valid": result.valid, "message": result.message, "errors": result.errors, "data": result.data}


@frappe.whitelist()
def validate_payment_amount_api(amount: float, context: str = "payment") -> Dict[str, Any]:
    """
    API endpoint for payment amount validation.

    Args:
        amount: Payment amount
        context: Validation context

    Returns:
        dict with validation result
    """
    service = get_payment_validation_service()
    result = service.validate_payment_amount(amount, context)

    # Convert Decimal to float for JSON serialization
    if result.valid and result.data:
        result.data["amount"] = float(result.data["amount"])

    return {"valid": result.valid, "message": result.message, "errors": result.errors, "data": result.data}
