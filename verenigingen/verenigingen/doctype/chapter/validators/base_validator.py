# verenigingen/verenigingen/doctype/chapter/validators/basevalidator.py
from dataclasses import dataclass
from typing import Any, Dict, List

import frappe


@dataclass
class ValidationResult:
    """Container for validation results"""

    is_valid: bool
    errors: List[str]
    warnings: List[str] = None

    def post_init(self):
        if self.warnings is None:
            self.warnings = []

    def add_error(self, message: str):
        """Add an error message"""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str):
        """Add a warning message"""
        self.warnings.append(message)

    def merge(self, other: "ValidationResult"):
        """Merge another validation result into this one"""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.is_valid:
            self.is_valid = False


class BaseValidator:
    """Base class for all chapter validators"""

    def __init__(self, chapter_doc=None):
        self.chapter_doc = chapter_doc
        self.context = {}

    def create_result(self, is_valid: bool = True) -> ValidationResult:
        """Create a new validation result"""
        return ValidationResult(is_valid=is_valid, errors=[], warnings=[])

    def validate_required_field(self, value: Any, field_name: str, result: ValidationResult):
        """Validate that a required field has a value"""
        if not value:
            result.add_error(("Field '{0}' is required").format(field_name))

    def validate_field_length(self, value: str, field_name: str, max_length: int, result: ValidationResult):
        """Validate field length"""
        if value and len(value) > max_length:
            result.add_error(
                ("Field '{0}' exceeds maximum length of {1} characters").format(field_name, max_length)
            )

    def validate_date_range(
        self, start_date: str, end_date: str, start_field: str, end_field: str, result: ValidationResult
    ):
        """Validate that end date is after start date"""
        if start_date and end_date:
            try:
                start_obj = frappe.utils.getdate(start_date)
                end_obj = frappe.utils.getdate(end_date)

                if start_obj > end_obj:
                    result.add_error(("{0} cannot be after {1}").format(start_field, end_field))
            except (ValueError, TypeError):
                result.add_error(("Invalid date format"))

    def validate_email(self, email: str, field_name: str, result: ValidationResult):
        """Validate email format"""
        if email and not frappe.utils.validate_email_address(email):
            result.add_error(("Invalid email format in field '{0}'").format(field_name))

    def validate_unique_in_list(self, items: List[Dict], key: str, item_name: str, result: ValidationResult):
        """Validate that a key is unique within a list of items"""
        seen_values = set()

        for item in items:
            value = item.get(key)
            if value:
                if value in seen_values:
                    result.add_error(("Duplicate {0} found: {1}").format(item_name, value))
                seen_values.add(value)

    def log_validation_error(self, error_message: str, context: Dict = None):
        """Log validation errors for debugging"""
        frappe.log_error(
            message=f"Chapter Validation Error: {error_message}\nContext: {context or self.context}",
            title="Chapter Validation Error",
        )
