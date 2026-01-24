"""
SEPA Utility Functions

This module contains utility functions extracted from the Direct Debit Batch system
to improve code organization and reusability.

DEPRECATION NOTICE:
Several IBAN/BIC validation functions in this module are deprecated in favor of
the canonical validators in verenigingen.utils.validation.iban_validator:
- get_bic_from_iban() → Use iban_validator.derive_bic_from_iban() (supports 25+ banks vs 10)
- validate_iban_format() → Use iban_validator.validate_iban() (includes MOD-97 checksum)
- validate_dutch_iban() → Use iban_validator.validate_iban() (full validation)
- format_iban_display() → Use iban_validator.format_iban() (identical functionality)

See: docs/refactoring/PAYMENT_MODULE_DUPLICATION_AUDIT.md
"""

import re
import warnings
from decimal import Decimal, InvalidOperation
from typing import Optional, Union

import frappe


class SEPAUtilities:
    """Utility class for SEPA-related operations"""

    @staticmethod
    def get_bic_from_iban(iban: str) -> Optional[str]:
        """
        Derive BIC from IBAN for Dutch banks.

        .. deprecated:: 1.0.0
            Use :func:`verenigingen.utils.validation.iban_validator.derive_bic_from_iban` instead.
            This function only supports 10 Dutch banks, while the canonical validator supports 25+.

            **Migration Example**::

                # Old (only 10 banks)
                from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities
                bic = SEPAUtilities.get_bic_from_iban(iban)

                # New (25+ banks including BITV, FVLB, HAND, DHBN, NWAB, etc.)
                from verenigingen.utils.validation.iban_validator import derive_bic_from_iban
                bic = derive_bic_from_iban(iban)

        Args:
            iban: International Bank Account Number

        Returns:
            BIC code if derivable from IBAN, None otherwise
        """
        warnings.warn(
            "SEPAUtilities.get_bic_from_iban() is deprecated. "
            "Use iban_validator.derive_bic_from_iban() instead (supports 25+ banks vs 10). "
            "Missing banks: BITV, FVLB, HAND, DHBN, NWAB, COBA, DEUT, FBHL, NNBA, AEGN, ZWLB, VOPA, RBRB, etc.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Delegate to canonical implementation
        from verenigingen.utils.validation.iban_validator import derive_bic_from_iban

        return derive_bic_from_iban(iban)

    @staticmethod
    def validate_iban_format(iban: str) -> bool:
        """
        Validate IBAN format using basic regex pattern.

        .. deprecated:: 1.0.0
            Use :func:`verenigingen.utils.validation.iban_validator.validate_iban` instead.
            This function only does basic regex validation WITHOUT checksum verification.
            The canonical validator includes proper MOD-97 checksum validation.

            **Security Risk**: This function may accept invalid IBANs with incorrect checksums!

            **Migration Example**::

                # Old (NO checksum validation - security risk!)
                from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities
                is_valid = SEPAUtilities.validate_iban_format(iban)

                # New (includes MOD-97 checksum validation)
                from verenigingen.utils.validation.iban_validator import validate_iban
                result = validate_iban(iban)
                is_valid = result["valid"]

        Args:
            iban: International Bank Account Number to validate

        Returns:
            True if IBAN format is valid, False otherwise
        """
        warnings.warn(
            "SEPAUtilities.validate_iban_format() is deprecated. "
            "Use iban_validator.validate_iban() instead. "
            "This function lacks MOD-97 checksum validation and may accept invalid IBANs!",
            DeprecationWarning,
            stacklevel=2,
        )

        # Delegate to canonical implementation
        from verenigingen.utils.validation.iban_validator import validate_iban

        result = validate_iban(iban)
        return result["valid"]

    @staticmethod
    def format_iban_display(iban: str) -> str:
        """
        Format IBAN for display with spaces every 4 characters.

        .. deprecated:: 1.0.0
            Use :func:`verenigingen.utils.validation.iban_validator.format_iban` instead.
            Both functions are functionally identical.

            **Migration Example**::

                # Old
                from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities
                formatted = SEPAUtilities.format_iban_display(iban)

                # New
                from verenigingen.utils.validation.iban_validator import format_iban
                formatted = format_iban(iban)

        Args:
            iban: IBAN to format

        Returns:
            Formatted IBAN string
        """
        warnings.warn(
            "SEPAUtilities.format_iban_display() is deprecated. "
            "Use iban_validator.format_iban() instead (identical functionality).",
            DeprecationWarning,
            stacklevel=2,
        )

        # Delegate to canonical implementation
        from verenigingen.utils.validation.iban_validator import format_iban

        return format_iban(iban) or ""

    @staticmethod
    def validate_dutch_iban(iban: str) -> bool:
        """
        Validate Dutch IBAN format and checksum.

        .. deprecated:: 1.0.0
            Use :func:`verenigingen.utils.validation.iban_validator.validate_iban` instead.
            This function has incomplete validation (see TODO comment in code).
            The canonical validator provides full MOD-97 checksum validation.

            **Security Risk**: This function may accept invalid Dutch IBANs!

            **Migration Example**::

                # Old (incomplete validation - see TODO in code)
                from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities
                is_valid = SEPAUtilities.validate_dutch_iban(iban)

                # New (complete validation with MOD-97 checksum)
                from verenigingen.utils.validation.iban_validator import validate_iban
                result = validate_iban(iban)
                is_valid = result["valid"] and iban.replace(" ", "").upper().startswith("NL")

        Args:
            iban: Dutch IBAN to validate

        Returns:
            True if valid Dutch IBAN, False otherwise
        """
        warnings.warn(
            "SEPAUtilities.validate_dutch_iban() is deprecated. "
            "Use iban_validator.validate_iban() instead. "
            "This function has incomplete validation (see TODO in original code) and may accept invalid IBANs!",
            DeprecationWarning,
            stacklevel=2,
        )

        # Delegate to canonical implementation
        from verenigingen.utils.validation.iban_validator import validate_iban

        if not iban:
            return False

        # Validate using canonical validator
        result = validate_iban(iban)
        if not result["valid"]:
            return False

        # Check if Dutch IBAN
        clean_iban = iban.replace(" ", "").upper()
        return clean_iban.startswith("NL")


class BatchLoggingUtilities:
    """Utility class for batch logging operations"""

    @staticmethod
    def add_to_batch_log(batch_name: str, message: str, level: str = "Info") -> None:
        """
        Add entry to batch processing log.

        Args:
            batch_name: Name of the batch being processed
            message: Log message
            level: Log level (Info, Warning, Error)
        """
        if not batch_name or not message:
            return

        try:
            # Create log entry
            frappe.get_doc(
                {
                    "doctype": "SEPA Operation Audit Log",
                    "batch_name": batch_name,
                    "operation": "Batch Processing",
                    "message": message,
                    "log_level": level,
                    "timestamp": frappe.utils.now(),
                }
            ).insert(ignore_permissions=True)

        except Exception as e:
            # Fallback to system logging if batch log fails
            frappe.log_error(f"Failed to add batch log entry: {str(e)}", "Batch Logging Error")

    @staticmethod
    def add_to_document_batch_log(doc, message: str) -> None:
        """
        Add timestamped message to document batch log field.

        Args:
            doc: Document with batch_log field
            message: Log message to add
        """
        from datetime import datetime

        from frappe.utils import format_datetime

        timestamp = format_datetime(datetime.now())
        log_message = f"{timestamp}: {message}\n"

        if doc.batch_log:
            doc.batch_log += log_message
        else:
            doc.batch_log = log_message

    @staticmethod
    def log_batch_operation(batch_name: str, operation: str, details: dict = None) -> None:
        """
        Log batch operation with structured details.

        Args:
            batch_name: Name of the batch
            operation: Operation being performed
            details: Additional operation details
        """
        message = f"Operation: {operation}"
        if details:
            details_str = ", ".join([f"{k}: {v}" for k, v in details.items()])
            message += f" | Details: {details_str}"

        BatchLoggingUtilities.add_to_batch_log(batch_name, message, "Info")


class CalculationUtilities:
    """Utility class for financial calculations"""

    @staticmethod
    def calculate_batch_totals(invoices: list) -> dict:
        """
        Calculate totals for a batch of invoices.

        Args:
            invoices: List of invoice dictionaries

        Returns:
            Dictionary with total_amount (Decimal), count, and currency
        """
        if not invoices:
            return {"total_amount": Decimal("0.00"), "count": 0, "currency": "EUR"}

        total_amount = Decimal("0")
        count = len(invoices)
        currency = "EUR"  # Default for Dutch SEPA

        for invoice in invoices:
            # Handle different possible field names for amount
            raw_amount = (
                invoice.get("outstanding_amount") or invoice.get("grand_total") or invoice.get("amount")
            )

            # Convert to Decimal safely
            try:
                if raw_amount is None:
                    amount = Decimal("0")
                elif isinstance(raw_amount, Decimal):
                    amount = raw_amount
                else:
                    amount = Decimal(str(raw_amount))
            except (InvalidOperation, ValueError, TypeError):
                amount = Decimal("0")

            total_amount += amount

            # Use currency from first invoice if available
            if "currency" in invoice and currency == "EUR":
                currency = invoice["currency"]

        # Quantize to 2 decimal places for monetary precision
        return {
            "total_amount": total_amount.quantize(Decimal("0.01")),
            "count": count,
            "currency": currency,
        }

    @staticmethod
    def format_currency_amount(amount: float, currency: str = "EUR") -> str:
        """
        Format currency amount for display.

        Args:
            amount: Amount to format
            currency: Currency code

        Returns:
            Formatted currency string
        """
        if currency == "EUR":
            return f"€ {amount:,.2f}"
        else:
            return f"{currency} {amount:,.2f}"

    @staticmethod
    def calculate_document_totals_python(invoices_list) -> dict:
        """
        Fallback Python calculation for document totals when SQL fails.

        Args:
            invoices_list: List of invoice objects with amount fields

        Returns:
            Dictionary with entry_count and total_amount (Decimal)
        """
        if not invoices_list:
            return {"entry_count": 0, "total_amount": Decimal("0.00")}

        # Functionally equivalent to SQL aggregation with comprehensive edge case handling
        entry_count = len(invoices_list)

        # Handle None/NULL values same way as SQL COALESCE(amount, 0)
        # Use Decimal for monetary precision
        total = Decimal("0")
        for invoice in invoices_list:
            try:
                raw_amount = invoice.amount
                if raw_amount is None:
                    amount = Decimal("0")
                elif isinstance(raw_amount, Decimal):
                    amount = raw_amount
                elif isinstance(raw_amount, str):
                    amount = Decimal(raw_amount.strip()) if raw_amount.strip() else Decimal("0")
                else:
                    amount = Decimal(str(raw_amount))
                total += amount
            except (ValueError, TypeError, AttributeError, InvalidOperation):
                # Skip invalid entries (equivalent to SQL ignoring invalid data)
                continue

        return {"entry_count": entry_count, "total_amount": total.quantize(Decimal("0.01"))}


class FileManagementUtilities:
    """Utility class for file management operations"""

    @staticmethod
    def attach_file_to_document(file_path: str, doctype: str, docname: str) -> str:
        """
        Attach file to a Frappe document.

        Args:
            file_path: Path to file to attach
            doctype: Document type to attach to
            docname: Document name to attach to

        Returns:
            File URL of attached file

        Raises:
            Exception: If file attachment fails
        """
        import os

        try:
            file_name = os.path.basename(file_path)

            with open(file_path, "rb") as f:
                file_content = f.read()

            # Use Frappe's file API to attach the file
            file_doc = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": file_name,
                    "attached_to_doctype": doctype,
                    "attached_to_name": docname,
                    "content": file_content,
                    "is_private": 1,
                }
            )
            file_doc.insert()

            return file_doc.file_url
        except Exception as e:
            frappe.log_error(
                f"Error attaching file {file_path} to {doctype} {docname}: {str(e)}", "File Attachment Error"
            )
            raise


class SEPAXMLValidator:
    """Utility class for SEPA XML validation"""

    @staticmethod
    def validate_sepa_xml_schema(xml_string: str, batch_name: str = None) -> dict:
        """
        Validate SEPA XML against pain.008.001.08 schema.

        Args:
            xml_string: XML string to validate
            batch_name: Optional batch name for logging

        Returns:
            Dictionary with validation results
        """
        try:
            # Try to import xmlschema for validation
            try:
                import xmlschema
            except ImportError:
                frappe.logger().info("xmlschema not available - skipping XML schema validation")
                return {"valid": True, "warnings": ["Schema validation skipped - xmlschema not installed"]}

            # Check if XSD schema file exists
            import os

            schema_path = os.path.join(frappe.get_app_path("verenigingen"), "schemas", "pain.008.001.08.xsd")

            if not os.path.exists(schema_path):
                # For financial transactions, missing schema validation is a concern
                batch_ref = f" for batch {batch_name}" if batch_name else ""
                frappe.log_error(
                    f"SEPA XSD schema not found at {schema_path} - validation skipped{batch_ref}",
                    "SEPA Schema Validation - Missing XSD File",
                )
                return {
                    "valid": True,
                    "warnings": ["Schema file not found - validation skipped"],
                    "critical": True,
                }

            # Perform validation
            schema = xmlschema.XMLSchema(schema_path)
            validation_errors = list(
                schema.iter_errors(
                    xml_string.decode("utf-8") if isinstance(xml_string, bytes) else xml_string
                )
            )

            if validation_errors:
                error_messages = [str(error) for error in validation_errors[:5]]  # Limit to first 5 errors
                return {
                    "valid": False,
                    "errors": error_messages,
                    "warning": f"Found {len(validation_errors)} validation errors",
                }
            else:
                return {"valid": True, "message": "XML validates against pain.008.001.08 schema"}

        except Exception as e:
            frappe.log_error(
                f"Error during SEPA XML schema validation: {str(e)}", "SEPA XML Validation Error"
            )
            return {
                "valid": False,
                "errors": [f"Validation failed with error: {str(e)}"],
                "critical": True,
            }


class InvoiceManagementUtilities:
    """Utility class for invoice management operations"""

    @staticmethod
    def update_batch_invoice_status(
        invoices_list, invoice_index: int, status: str, result_code: str = None, result_message: str = None
    ) -> bool:
        """
        Update status of a specific invoice in a batch.

        Args:
            invoices_list: List of invoice objects
            invoice_index: Index of invoice to update
            status: New status to set
            result_code: Optional result code
            result_message: Optional result message

        Returns:
            True if update successful, False otherwise

        Raises:
            IndexError: If invoice_index is invalid
        """
        if invoice_index < 0 or invoice_index >= len(invoices_list):
            raise IndexError("Invalid invoice index")

        invoice = invoices_list[invoice_index]
        invoice.status = status

        if result_code:
            invoice.result_code = result_code

        if result_message:
            invoice.result_message = result_message

        return True

    @staticmethod
    def generate_invoice_description(
        invoice_name: str, member_name: str = None, membership_period: str = None
    ) -> str:
        """
        Generate standardized description for SEPA invoice processing.

        Args:
            invoice_name: Name/ID of the invoice
            member_name: Optional member name
            membership_period: Optional membership period

        Returns:
            Formatted description string
        """
        description = f"Invoice {invoice_name}"

        if member_name:
            description += f" - {member_name}"

        if membership_period:
            description += f" ({membership_period})"

        return description

    @staticmethod
    def validate_invoice_for_sepa(invoice_data: dict) -> dict:
        """
        Validate invoice data for SEPA direct debit processing.

        Args:
            invoice_data: Dictionary containing invoice information

        Returns:
            Dictionary with validation results
        """
        errors = []
        warnings = []

        # Required fields
        required_fields = ["name", "customer", "outstanding_amount", "currency"]
        for field in required_fields:
            if not invoice_data.get(field):
                errors.append(f"Missing required field: {field}")

        # Amount validation
        try:
            raw_amount = invoice_data.get("outstanding_amount", 0)
            if isinstance(raw_amount, Decimal):
                amount = raw_amount
            else:
                amount = Decimal(str(raw_amount))
            if amount <= 0:
                errors.append("Outstanding amount must be greater than zero")
            elif amount > Decimal("999999.99"):  # SEPA limit
                errors.append("Amount exceeds SEPA transaction limit")
        except (ValueError, TypeError, InvalidOperation):
            errors.append("Invalid outstanding amount format")

        # Currency validation
        currency = invoice_data.get("currency", "")
        if currency != "EUR":
            errors.append(f"Unsupported currency: {currency} (only EUR supported)")

        # Status validation
        status = invoice_data.get("status", "")
        valid_statuses = ["Unpaid", "Overdue", "Partly Paid"]
        if status not in valid_statuses:
            warnings.append(f"Invoice status '{status}' may not be suitable for SEPA processing")

        return {"is_valid": len(errors) == 0, "errors": errors, "warnings": warnings}
