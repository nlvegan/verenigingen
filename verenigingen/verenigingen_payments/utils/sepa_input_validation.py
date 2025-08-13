"""
SEPA Input Validation Utilities

Comprehensive input validation for SEPA batch operations including:
- IBAN format validation
- Amount validation
- Date validation
- Mandate reference validation
- Batch parameter validation
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import SEPAError, ValidationError
from verenigingen.utils.validation.iban_validator import validate_iban


class SEPAInputValidator:
    """Comprehensive input validation for SEPA operations"""

    # SEPA XML constraints
    MAX_MESSAGE_ID_LENGTH = 35
    MAX_CREDITOR_NAME_LENGTH = 70
    MAX_DEBTOR_NAME_LENGTH = 70
    MAX_REMITTANCE_INFO_LENGTH = 140
    MAX_MANDATE_ID_LENGTH = 35
    MIN_AMOUNT = Decimal("0.01")
    MAX_AMOUNT = Decimal("999999999.99")
    MAX_BATCH_SIZE = 10000

    # Date constraints
    MIN_COLLECTION_DATE_OFFSET = 1  # Days from today
    MAX_COLLECTION_DATE_OFFSET = 30  # Days from today

    # Allowed characters in SEPA text fields (basic Latin)
    SEPA_TEXT_PATTERN = re.compile(r"^[a-zA-Z0-9\+\?\-\:\(\)\.\,\'\s/]*$")

    @staticmethod
    def validate_batch_creation_params(**params) -> Dict[str, Any]:
        """
        Validate parameters for SEPA batch creation

        Args:
            **params: Batch creation parameters

        Returns:
            Validation result dictionary

        Raises:
            ValidationError: If validation fails
        """
        validation_result = {"valid": True, "errors": [], "warnings": [], "cleaned_params": {}}

        try:
            # Required parameters
            required_fields = ["batch_date", "batch_type", "invoice_list"]
            for field in required_fields:
                if field not in params or params[field] is None:
                    validation_result["errors"].append(f"Required field missing: {field}")

            if validation_result["errors"]:
                validation_result["valid"] = False
                return validation_result

            # Validate batch date
            batch_date_result = SEPAInputValidator.validate_collection_date(params["batch_date"])
            if not batch_date_result["valid"]:
                validation_result["errors"].extend(batch_date_result["errors"])
            else:
                validation_result["cleaned_params"]["batch_date"] = batch_date_result["cleaned_date"]

            # Validate batch type
            batch_type_result = SEPAInputValidator.validate_batch_type(params["batch_type"])
            if not batch_type_result["valid"]:
                validation_result["errors"].extend(batch_type_result["errors"])
            else:
                validation_result["cleaned_params"]["batch_type"] = batch_type_result["cleaned_type"]

            # Validate invoice list
            invoice_list_result = SEPAInputValidator.validate_invoice_list(params["invoice_list"])
            if not invoice_list_result["valid"]:
                validation_result["errors"].extend(invoice_list_result["errors"])
            else:
                validation_result["cleaned_params"]["invoice_list"] = invoice_list_result["cleaned_invoices"]
                validation_result["warnings"].extend(invoice_list_result.get("warnings", []))

            # Optional parameters
            if "description" in params:
                desc_result = SEPAInputValidator.validate_sepa_text(
                    params["description"],
                    max_length=SEPAInputValidator.MAX_REMITTANCE_INFO_LENGTH,
                    field_name="description",
                )
                if not desc_result["valid"]:
                    validation_result["errors"].extend(desc_result["errors"])
                else:
                    validation_result["cleaned_params"]["description"] = desc_result["cleaned_text"]

            # Overall validation
            validation_result["valid"] = len(validation_result["errors"]) == 0

        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Validation error: {str(e)}")

        return validation_result

    @staticmethod
    def validate_collection_date(date_input: Union[str, date, datetime]) -> Dict[str, Any]:
        """
        Validate SEPA collection date

        Args:
            date_input: Date in various formats

        Returns:
            Validation result with cleaned date
        """
        result = {"valid": True, "errors": [], "cleaned_date": None}

        try:
            # Convert to date object
            if isinstance(date_input, str):
                try:
                    parsed_date = getdate(date_input)
                except Exception:
                    result["errors"].append(f"Invalid date format: {date_input}")
                    result["valid"] = False
                    return result
            elif isinstance(date_input, datetime):
                parsed_date = date_input.date()
            elif isinstance(date_input, date):
                parsed_date = date_input
            else:
                result["errors"].append(f"Invalid date type: {type(date_input)}")
                result["valid"] = False
                return result

            # Validate date constraints
            today_date = getdate(today())
            min_date = add_days(today_date, SEPAInputValidator.MIN_COLLECTION_DATE_OFFSET)
            max_date = add_days(today_date, SEPAInputValidator.MAX_COLLECTION_DATE_OFFSET)

            if parsed_date < min_date:
                result["errors"].append(
                    f"Collection date too early. Minimum: {min_date} (got: {parsed_date})"
                )
            elif parsed_date > max_date:
                result["errors"].append(f"Collection date too late. Maximum: {max_date} (got: {parsed_date})")

            # Check for weekends/holidays (basic check)
            if parsed_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                result["errors"].append(
                    f"Collection date cannot be weekend: {parsed_date} ({parsed_date.strftime('%A')})"
                )

            if result["errors"]:
                result["valid"] = False
            else:
                result["cleaned_date"] = parsed_date

        except Exception as e:
            result["errors"].append(f"Date validation error: {str(e)}")
            result["valid"] = False

        return result

    @staticmethod
    def validate_batch_type(batch_type: str) -> Dict[str, Any]:
        """
        Validate SEPA batch type

        Args:
            batch_type: Batch type string

        Returns:
            Validation result with cleaned type
        """
        result = {"valid": True, "errors": [], "cleaned_type": None}

        # Valid SEPA direct debit types
        valid_types = [
            "CORE",  # SEPA Core Direct Debit
            "B2B",  # SEPA Business-to-Business Direct Debit
            "COR1",  # SEPA Core Direct Debit with 1-day settlement
        ]

        if not batch_type or not isinstance(batch_type, str):
            result["errors"].append("Batch type is required and must be a string")
            result["valid"] = False
            return result

        cleaned_type = batch_type.strip().upper()

        if cleaned_type not in valid_types:
            result["errors"].append(
                f"Invalid batch type: {batch_type}. Valid types: {', '.join(valid_types)}"
            )
            result["valid"] = False
        else:
            result["cleaned_type"] = cleaned_type

        return result

    @staticmethod
    def validate_invoice_list(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate list of invoices for SEPA batch

        Args:
            invoices: List of invoice dictionaries

        Returns:
            Validation result with cleaned invoices
        """
        result = {"valid": True, "errors": [], "warnings": [], "cleaned_invoices": []}

        if not invoices or not isinstance(invoices, list):
            result["errors"].append("Invoice list is required and must be a list")
            result["valid"] = False
            return result

        if len(invoices) == 0:
            result["errors"].append("Invoice list cannot be empty")
            result["valid"] = False
            return result

        if len(invoices) > SEPAInputValidator.MAX_BATCH_SIZE:
            result["errors"].append(
                f"Too many invoices. Maximum: {SEPAInputValidator.MAX_BATCH_SIZE}, got: {len(invoices)}"
            )
            result["valid"] = False
            return result

        total_amount = Decimal("0")
        seen_invoices = set()

        for i, invoice in enumerate(invoices):
            invoice_result = SEPAInputValidator.validate_single_invoice(invoice, index=i)

            if not invoice_result["valid"]:
                result["errors"].extend(invoice_result["errors"])
                continue

            cleaned_invoice = invoice_result["cleaned_invoice"]

            # Check for duplicates
            invoice_id = cleaned_invoice["invoice"]
            if invoice_id in seen_invoices:
                result["errors"].append(f"Duplicate invoice in batch: {invoice_id}")
                continue

            seen_invoices.add(invoice_id)

            # Enhanced amount aggregation with functional equivalence to SQL patterns
            # Follows direct_debit_batch.py defensive programming patterns
            try:
                invoice_amount = cleaned_invoice.get("amount")
                if invoice_amount is None:
                    # Handle None values same way as SQL COALESCE(amount, 0)
                    invoice_amount = Decimal("0")
                elif isinstance(invoice_amount, (str, int, float)):
                    # Ensure consistent Decimal conversion for precision
                    invoice_amount = Decimal(str(invoice_amount))
                elif not isinstance(invoice_amount, Decimal):
                    # Handle unexpected types gracefully
                    invoice_amount = Decimal(str(invoice_amount))

                total_amount += invoice_amount

            except (ValueError, TypeError, InvalidOperation) as e:
                # Handle conversion errors gracefully (same as SQL COALESCE behavior)
                frappe.logger().warning(f"Invalid amount in invoice {invoice_id}, treating as 0: {str(e)}")
                # Skip adding to total_amount, effectively treating as 0

            result["cleaned_invoices"].append(cleaned_invoice)

            # Add any warnings
            result["warnings"].extend(invoice_result.get("warnings", []))

        # Validate total amount
        if total_amount > SEPAInputValidator.MAX_AMOUNT * len(invoices):
            result["errors"].append(f"Total batch amount too large: {total_amount}")

        result["valid"] = len(result["errors"]) == 0
        return result

    @staticmethod
    def validate_single_invoice(invoice: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
        """
        Validate a single invoice for SEPA processing

        Args:
            invoice: Invoice dictionary
            index: Invoice index in batch

        Returns:
            Validation result with cleaned invoice
        """
        result = {"valid": True, "errors": [], "warnings": [], "cleaned_invoice": {}}

        prefix = f"Invoice {index + 1}"

        # Required fields for SEPA invoice
        required_fields = ["invoice", "amount", "iban", "member_name", "mandate_reference"]

        for field in required_fields:
            if field not in invoice or invoice[field] is None:
                result["errors"].append(f"{prefix}: Required field missing: {field}")

        if result["errors"]:
            result["valid"] = False
            return result

        try:
            # Validate invoice ID
            invoice_id = str(invoice["invoice"]).strip()
            if not invoice_id:
                result["errors"].append(f"{prefix}: Invoice ID cannot be empty")
            elif len(invoice_id) > 50:  # Reasonable limit
                result["errors"].append(f"{prefix}: Invoice ID too long (max 50 chars)")
            else:
                result["cleaned_invoice"]["invoice"] = invoice_id

            # Validate amount
            amount_result = SEPAInputValidator.validate_amount(invoice["amount"])
            if not amount_result["valid"]:
                result["errors"].extend([f"{prefix}: {err}" for err in amount_result["errors"]])
            else:
                result["cleaned_invoice"]["amount"] = amount_result["cleaned_amount"]

            # Validate IBAN
            iban_result = validate_iban(invoice["iban"])
            if not iban_result["valid"]:
                result["errors"].append(f"{prefix}: {iban_result['message']}")
            else:
                result["cleaned_invoice"]["iban"] = iban_result["formatted_iban"]

            # Validate member name
            name_result = SEPAInputValidator.validate_sepa_text(
                invoice["member_name"],
                max_length=SEPAInputValidator.MAX_DEBTOR_NAME_LENGTH,
                field_name="member_name",
            )
            if not name_result["valid"]:
                result["errors"].extend([f"{prefix}: {err}" for err in name_result["errors"]])
            else:
                result["cleaned_invoice"]["member_name"] = name_result["cleaned_text"]

            # Validate mandate reference
            mandate_result = SEPAInputValidator.validate_mandate_reference(invoice["mandate_reference"])
            if not mandate_result["valid"]:
                result["errors"].extend([f"{prefix}: {err}" for err in mandate_result["errors"]])
            else:
                result["cleaned_invoice"]["mandate_reference"] = mandate_result["cleaned_reference"]

            # Optional fields
            for optional_field in ["bic", "currency", "description"]:
                if optional_field in invoice and invoice[optional_field]:
                    if optional_field == "bic":
                        bic_result = SEPAInputValidator.validate_bic(invoice[optional_field])
                        if bic_result["valid"]:
                            result["cleaned_invoice"]["bic"] = bic_result["cleaned_bic"]
                        else:
                            result["warnings"].append(f"{prefix}: Invalid BIC: {bic_result['errors'][0]}")
                    elif optional_field == "currency":
                        if invoice[optional_field].upper() != "EUR":
                            result["errors"].append(f"{prefix}: Only EUR currency supported")
                        else:
                            result["cleaned_invoice"]["currency"] = "EUR"
                    elif optional_field == "description":
                        desc_result = SEPAInputValidator.validate_sepa_text(
                            invoice[optional_field],
                            max_length=SEPAInputValidator.MAX_REMITTANCE_INFO_LENGTH,
                            field_name="description",
                        )
                        if desc_result["valid"]:
                            result["cleaned_invoice"]["description"] = desc_result["cleaned_text"]
                        else:
                            result["warnings"].extend([f"{prefix}: {err}" for err in desc_result["errors"]])

            # Set defaults for missing optional fields
            result["cleaned_invoice"].setdefault("currency", "EUR")
            result["cleaned_invoice"].setdefault("description", f"Invoice {invoice_id}")

        except Exception as e:
            result["errors"].append(f"{prefix}: Validation error: {str(e)}")

        result["valid"] = len(result["errors"]) == 0
        return result

    @staticmethod
    def validate_amount(amount_input: Union[str, int, float, Decimal]) -> Dict[str, Any]:
        """
        Validate SEPA amount

        Args:
            amount_input: Amount in various formats

        Returns:
            Validation result with cleaned amount
        """
        result = {"valid": True, "errors": [], "cleaned_amount": None}

        try:
            # Convert to Decimal for precise monetary calculations
            if isinstance(amount_input, str):
                # Clean string input
                cleaned_str = amount_input.strip().replace(",", ".")
                amount = Decimal(cleaned_str)
            elif isinstance(amount_input, (int, float)):
                amount = Decimal(str(amount_input))
            elif isinstance(amount_input, Decimal):
                amount = amount_input
            else:
                result["errors"].append(f"Invalid amount type: {type(amount_input)}")
                result["valid"] = False
                return result

            # Validate amount constraints
            if amount <= 0:
                result["errors"].append("Amount must be positive")
            elif amount < SEPAInputValidator.MIN_AMOUNT:
                result["errors"].append(f"Amount too small. Minimum: {SEPAInputValidator.MIN_AMOUNT}")
            elif amount > SEPAInputValidator.MAX_AMOUNT:
                result["errors"].append(f"Amount too large. Maximum: {SEPAInputValidator.MAX_AMOUNT}")

            # Check decimal places (max 2 for EUR)
            if amount.as_tuple().exponent < -2:
                result["errors"].append("Amount cannot have more than 2 decimal places")

            if result["errors"]:
                result["valid"] = False
            else:
                # Round to 2 decimal places
                result["cleaned_amount"] = amount.quantize(Decimal("0.01"))

        except (InvalidOperation, ValueError):
            result["errors"].append(f"Invalid amount format: {amount_input}")
            result["valid"] = False
        except Exception as e:
            result["errors"].append(f"Amount validation error: {str(e)}")
            result["valid"] = False

        return result

    @staticmethod
    def validate_mandate_reference(mandate_ref: str) -> Dict[str, Any]:
        """
        Validate SEPA mandate reference

        Args:
            mandate_ref: Mandate reference string

        Returns:
            Validation result with cleaned reference
        """
        result = {"valid": True, "errors": [], "cleaned_reference": None}

        if not mandate_ref or not isinstance(mandate_ref, str):
            result["errors"].append("Mandate reference is required")
            result["valid"] = False
            return result

        cleaned_ref = mandate_ref.strip()

        if not cleaned_ref:
            result["errors"].append("Mandate reference cannot be empty")
            result["valid"] = False
            return result

        if len(cleaned_ref) > SEPAInputValidator.MAX_MANDATE_ID_LENGTH:
            result["errors"].append(
                f"Mandate reference too long. Maximum: {SEPAInputValidator.MAX_MANDATE_ID_LENGTH} chars"
            )
            result["valid"] = False
            return result

        # Basic format check - alphanumeric with some special chars
        if not re.match(r"^[a-zA-Z0-9\-_\.]+$", cleaned_ref):
            result["errors"].append("Mandate reference contains invalid characters")
            result["valid"] = False
        else:
            result["cleaned_reference"] = cleaned_ref

        return result

    @staticmethod
    def validate_bic(bic: str) -> Dict[str, Any]:
        """
        Validate BIC (Bank Identifier Code)

        Args:
            bic: BIC string

        Returns:
            Validation result with cleaned BIC
        """
        result = {"valid": True, "errors": [], "cleaned_bic": None}

        if not bic or not isinstance(bic, str):
            result["errors"].append("BIC must be a string")
            result["valid"] = False
            return result

        cleaned_bic = bic.strip().upper()

        # BIC format: 8 or 11 characters
        # Format: BBBBCCLL[bbb] where:
        # BBBB = Bank code (4 letters)
        # CC = Country code (2 letters)
        # LL = Location code (2 alphanumeric)
        # bbb = Branch code (3 alphanumeric, optional)

        if len(cleaned_bic) not in [8, 11]:
            result["errors"].append("BIC must be 8 or 11 characters long")
            result["valid"] = False
            return result

        # Basic format check
        if not re.match(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", cleaned_bic):
            result["errors"].append("Invalid BIC format")
            result["valid"] = False
        else:
            result["cleaned_bic"] = cleaned_bic

        return result

    @staticmethod
    def validate_sepa_text(text: str, max_length: int, field_name: str = "text") -> Dict[str, Any]:
        """
        Validate text field for SEPA compliance

        Args:
            text: Text to validate
            max_length: Maximum allowed length
            field_name: Field name for error messages

        Returns:
            Validation result with cleaned text
        """
        result = {"valid": True, "errors": [], "cleaned_text": None}

        if not text or not isinstance(text, str):
            result["errors"].append(f"{field_name} must be a non-empty string")
            result["valid"] = False
            return result

        # Trim whitespace
        cleaned_text = text.strip()

        if not cleaned_text:
            result["errors"].append(f"{field_name} cannot be empty after trimming")
            result["valid"] = False
            return result

        if len(cleaned_text) > max_length:
            result["errors"].append(
                f"{field_name} too long. Maximum: {max_length} chars, got: {len(cleaned_text)}"
            )
            result["valid"] = False
            return result

        # Check for SEPA-allowed characters
        if not SEPAInputValidator.SEPA_TEXT_PATTERN.match(cleaned_text):
            result["errors"].append(f"{field_name} contains invalid characters for SEPA")
            result["valid"] = False
        else:
            result["cleaned_text"] = cleaned_text

        return result


# API functions for validation
@frappe.whitelist()
def validate_sepa_batch_params(**params) -> Dict[str, Any]:
    """
    API endpoint to validate SEPA batch creation parameters

    Returns:
        Validation result dictionary
    """
    try:
        return SEPAInputValidator.validate_batch_creation_params(**params)
    except Exception as e:
        frappe.log_error(f"SEPA batch validation error: {str(e)}", "SEPA Input Validation")
        return {"valid": False, "errors": [f"Validation system error: {str(e)}"], "warnings": []}


@frappe.whitelist()
def validate_single_sepa_invoice(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    API endpoint to validate a single invoice for SEPA processing

    Args:
        invoice_data: Invoice data dictionary

    Returns:
        Validation result dictionary
    """
    try:
        return SEPAInputValidator.validate_single_invoice(invoice_data)
    except Exception as e:
        frappe.log_error(f"SEPA invoice validation error: {str(e)}", "SEPA Input Validation")
        return {"valid": False, "errors": [f"Validation system error: {str(e)}"], "warnings": []}


@frappe.whitelist()
def get_sepa_validation_rules() -> Dict[str, Any]:
    """
    API endpoint to get SEPA validation rules and constraints

    Returns:
        Dictionary of validation rules
    """
    return {
        "constraints": {
            "max_message_id_length": SEPAInputValidator.MAX_MESSAGE_ID_LENGTH,
            "max_creditor_name_length": SEPAInputValidator.MAX_CREDITOR_NAME_LENGTH,
            "max_debtor_name_length": SEPAInputValidator.MAX_DEBTOR_NAME_LENGTH,
            "max_remittance_info_length": SEPAInputValidator.MAX_REMITTANCE_INFO_LENGTH,
            "max_mandate_id_length": SEPAInputValidator.MAX_MANDATE_ID_LENGTH,
            "min_amount": float(SEPAInputValidator.MIN_AMOUNT),
            "max_amount": float(SEPAInputValidator.MAX_AMOUNT),
            "max_batch_size": SEPAInputValidator.MAX_BATCH_SIZE,
            "min_collection_date_offset": SEPAInputValidator.MIN_COLLECTION_DATE_OFFSET,
            "max_collection_date_offset": SEPAInputValidator.MAX_COLLECTION_DATE_OFFSET,
        },
        "valid_batch_types": ["CORE", "B2B", "COR1"],
        "required_invoice_fields": ["invoice", "amount", "iban", "member_name", "mandate_reference"],
        "optional_invoice_fields": ["bic", "currency", "description"],
        "supported_currency": "EUR",
    }
