"""
Batch Validation Service

This service handles all validation logic for SEPA direct debit batches.
Extracted from Direct Debit Batch system for better separation of concerns.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from frappe.utils import getdate

from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service


class ValidationResult:
    """Container for validation results"""

    def __init__(self):
        self.is_valid = True
        self.errors = []
        self.warnings = []
        self.details = {}

    def add_error(self, message: str, code: str = None):
        """Add validation error"""
        self.is_valid = False
        error = {"message": message}
        if code:
            error["code"] = code
        self.errors.append(error)

    def add_warning(self, message: str, code: str = None):
        """Add validation warning"""
        warning = {"message": message}
        if code:
            warning["code"] = code
        self.warnings.append(warning)

    def add_detail(self, key: str, value: Any):
        """Add validation detail"""
        self.details[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "details": self.details,
        }


class BatchValidationService:
    """Service for validating SEPA direct debit batches"""

    def __init__(self):
        self.config_service = sepa_config_service

    def validate_batch_creation(self, invoices: List[Dict], collection_date: str = None) -> ValidationResult:
        """
        Validate batch creation requirements.

        Args:
            invoices: List of invoices to include in batch
            collection_date: Proposed collection date

        Returns:
            ValidationResult with validation outcome
        """
        result = ValidationResult()

        # Validate SEPA configuration
        config_validation = self.config_service.validate_sepa_configuration()
        if not config_validation["is_valid"]:
            for error in config_validation["errors"]:
                result.add_error(f"Configuration error: {error}", "CONFIG_ERROR")
            return result

        # Validate invoices
        # NOTE: extend()-ing the error lists directly bypasses add_error(), which is
        # what flips result.is_valid. We must invalidate the aggregate result here too,
        # otherwise validate_batch_creation would report is_valid=True despite collected
        # errors and callers gating on is_valid would let a batch with bad
        # invoices/dates/limits through to creation.
        invoice_validation = self._validate_invoices(invoices)
        if not invoice_validation.is_valid:
            result.is_valid = False
            result.errors.extend(invoice_validation.errors)
            result.warnings.extend(invoice_validation.warnings)

        # Validate collection date
        if collection_date:
            date_validation = self._validate_collection_date(collection_date)
            if not date_validation.is_valid:
                result.is_valid = False
                result.errors.extend(date_validation.errors)
                result.warnings.extend(date_validation.warnings)

        # Validate batch limits
        limits_validation = self._validate_batch_limits(invoices)
        if not limits_validation.is_valid:
            result.is_valid = False
            result.errors.extend(limits_validation.errors)
            result.warnings.extend(limits_validation.warnings)

        return result

    def _validate_invoices(self, invoices: List[Dict]) -> ValidationResult:
        """
        Validate individual invoices for SEPA processing.

        Args:
            invoices: List of invoices to validate

        Returns:
            ValidationResult for invoice validation
        """
        result = ValidationResult()

        if not invoices:
            result.add_error("No invoices provided for batch", "NO_INVOICES")
            return result

        limits = self.config_service.get_batch_processing_limits()
        invalid_invoices = []

        for i, invoice in enumerate(invoices):
            invoice_errors = []

            # Validate required fields
            required_fields = ["name", "customer", "outstanding_amount"]
            for field in required_fields:
                if not invoice.get(field):
                    invoice_errors.append(f"Missing required field: {field}")

            # Validate amount
            amount = invoice.get("outstanding_amount", 0)
            try:
                amount = float(amount)
                if amount < limits["min_amount_per_transaction"]:
                    invoice_errors.append(f"Amount too small: {amount}")
                elif amount > limits["max_amount_per_transaction"]:
                    invoice_errors.append(f"Amount too large: {amount}")
            except (ValueError, TypeError):
                invoice_errors.append(f"Invalid amount: {amount}")

            # Validate currency
            currency = invoice.get("currency", "EUR")
            if currency != "EUR":
                invoice_errors.append(f"Unsupported currency: {currency}")

            # Validate invoice status
            status = invoice.get("status")
            if status not in ["Unpaid", "Overdue", "Partly Paid"]:
                invoice_errors.append(f"Invalid invoice status for SEPA: {status}")

            if invoice_errors:
                invalid_invoices.append(
                    {"index": i, "invoice": invoice.get("name", f"Invoice {i}"), "errors": invoice_errors}
                )

        if invalid_invoices:
            result.add_error(f"Found {len(invalid_invoices)} invalid invoices", "INVALID_INVOICES")
            result.add_detail("invalid_invoices", invalid_invoices)

        result.add_detail("total_invoices", len(invoices))
        result.add_detail("valid_invoices", len(invoices) - len(invalid_invoices))

        return result

    def _validate_collection_date(self, collection_date: str) -> ValidationResult:
        """
        Validate proposed collection date.

        Args:
            collection_date: Collection date string (YYYY-MM-DD)

        Returns:
            ValidationResult for date validation
        """
        result = ValidationResult()

        try:
            # Parse collection date
            collection_dt = datetime.strptime(collection_date, "%Y-%m-%d").date()
            # Site-tz today: the notice-day boundaries below reject a batch outright
            # (DATE_TOO_EARLY), and the collection date the caller submits comes from
            # the site's calendar, not the process's (#637).
            today = getdate()

            # Get date settings
            date_settings = self.config_service.get_collection_date_settings()
            min_notice = date_settings["minimum_notice_days"]
            max_notice = date_settings["maximum_notice_days"]

            # Calculate date boundaries
            earliest_date = today + timedelta(days=min_notice)
            latest_date = today + timedelta(days=max_notice)

            # Validate date range
            if collection_dt < earliest_date:
                result.add_error(
                    f"Collection date too early. Minimum notice: {min_notice} days", "DATE_TOO_EARLY"
                )
            elif collection_dt > latest_date:
                result.add_warning(
                    f"Collection date far in future. Consider using date within {max_notice} days",
                    "DATE_FAR_FUTURE",
                )

            # Validate weekend (for Dutch banking)
            if collection_dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
                result.add_warning(
                    "Collection date is weekend. Banks may process on next business day", "WEEKEND_COLLECTION"
                )

            result.add_detail("collection_date", collection_date)
            result.add_detail("days_from_today", (collection_dt - today).days)

        except ValueError:
            result.add_error(f"Invalid date format: {collection_date}", "INVALID_DATE_FORMAT")

        return result

    def _validate_batch_limits(self, invoices: List[Dict]) -> ValidationResult:
        """
        Validate batch against processing limits.

        Args:
            invoices: List of invoices in batch

        Returns:
            ValidationResult for batch limits
        """
        result = ValidationResult()
        limits = self.config_service.get_batch_processing_limits()

        # Validate batch size
        if len(invoices) > limits["max_batch_size"]:
            result.add_error(
                f"Batch too large: {len(invoices)} invoices (max: {limits['max_batch_size']})",
                "BATCH_TOO_LARGE",
            )

        # Calculate total amount
        total_amount = 0
        for invoice in invoices:
            try:
                amount = float(invoice.get("outstanding_amount", 0))
                total_amount += amount
            except (ValueError, TypeError):
                continue

        # Validate total amount
        if total_amount > limits["max_total_batch_amount"]:
            result.add_error(
                f"Batch total too large: €{total_amount:,.2f} (max: €{limits['max_total_batch_amount']:,.2f})",
                "BATCH_AMOUNT_TOO_LARGE",
            )

        result.add_detail("batch_size", len(invoices))
        result.add_detail("total_amount", total_amount)

        return result


# Singleton instance for global use
batch_validation_service = BatchValidationService()
