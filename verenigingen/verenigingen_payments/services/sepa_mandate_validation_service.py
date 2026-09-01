"""
SEPA Mandate Validation Service

This service handles SEPA mandate validation and business rule enforcement.
Extracted from SEPA Mandate controller for better separation of concerns.
"""

from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, format_iban, validate_iban
from verenigingen.utils.validation_utilities import DateRangeValidator


class SEPAMandateValidationService:
    """Service for SEPA mandate validation and business rule enforcement"""

    def __init__(self):
        pass

    def validate_mandate_dates(self, mandate_doc) -> Dict[str, any]:
        """
        Validate mandate date constraints and business rules.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with validation results

        Raises:
            frappe.ValidationError: If critical validation fails
        """
        validation_result = {"is_valid": True, "warnings": [], "errors": []}

        try:
            # Use existing DateRangeValidator for robust date validation
            date_validator = DateRangeValidator()

            # Validate date range if both dates are provided
            if mandate_doc.sign_date and mandate_doc.expiry_date:
                range_validation = date_validator.validate_date_range(
                    mandate_doc.sign_date,
                    mandate_doc.expiry_date,
                    allow_past_start=True,  # Allow past sign dates for SEPA mandates
                    allow_equal_dates=True,  # Allow same date sign/expiry
                    throw_on_error=False,
                )
                if not range_validation.get("valid", False):
                    validation_result["errors"].append(_("Sign date cannot be after expiry date"))
                    validation_result["is_valid"] = False

            # Validate that sign_date is not in the future
            if mandate_doc.sign_date:
                today = getdate()
                if getdate(mandate_doc.sign_date) > today:
                    validation_result["errors"].append(_("Sign date cannot be in the future"))
                    validation_result["is_valid"] = False

            # Note: We don't validate that expiry_date is in the past for active mandates
            # because the lifecycle service will automatically set the status to "Expired"

            return validation_result

        except Exception as e:
            frappe.log_error(
                title="SEPA Mandate Validation", message=f"Error in validate_mandate_dates: {str(e)}"
            )
            validation_result["errors"].append(f"Date validation error: {str(e)}")
            validation_result["is_valid"] = False
            return validation_result

    def validate_mandate_iban(self, mandate_doc) -> Dict[str, any]:
        """
        Validate IBAN and derive BIC if possible.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with validation results and derived BIC

        Raises:
            frappe.ValidationError: If IBAN validation fails
        """
        validation_result = {"is_valid": True, "warnings": [], "errors": [], "derived_bic": None}

        try:
            if not mandate_doc.iban:
                validation_result["errors"].append(_("IBAN is required for SEPA mandate"))
                validation_result["is_valid"] = False
                return validation_result

            # Validate IBAN format using existing validator
            iban_validation = validate_iban(mandate_doc.iban)

            if not iban_validation.get("valid", False):
                validation_result["errors"].append(
                    _("Invalid IBAN format: {0}").format(iban_validation.get("message", "Unknown error"))
                )
                validation_result["is_valid"] = False
                return validation_result

            # Format IBAN with proper spacing
            formatted_iban = format_iban(mandate_doc.iban)
            if formatted_iban and formatted_iban != mandate_doc.iban:
                mandate_doc.iban = formatted_iban

            # Try to derive BIC from IBAN
            derived_bic = derive_bic_from_iban(mandate_doc.iban)

            if derived_bic:
                validation_result["derived_bic"] = derived_bic

                # If BIC is provided, validate it matches derived BIC
                if mandate_doc.bic and mandate_doc.bic != derived_bic:
                    validation_result["warnings"].append(
                        _("Provided BIC {0} does not match derived BIC {1}").format(
                            mandate_doc.bic, derived_bic
                        )
                    )

                # Auto-populate BIC if not provided
                if not mandate_doc.bic:
                    mandate_doc.bic = derived_bic
                    validation_result["warnings"].append(
                        _("BIC automatically derived from IBAN: {0}").format(derived_bic)
                    )

            return validation_result

        except Exception as e:
            frappe.log_error(
                title="SEPA Mandate Validation", message=f"Error in validate_mandate_iban: {str(e)}"
            )
            validation_result["errors"].append(f"IBAN validation error: {str(e)}")
            validation_result["is_valid"] = False
            return validation_result

    def validate_mandate_business_rules(self, mandate_doc) -> Dict[str, any]:
        """
        Validate SEPA mandate business rules and constraints.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with validation results
        """
        validation_result = {"is_valid": True, "warnings": [], "errors": []}

        try:
            # Validate required fields for active mandates
            if mandate_doc.status == "Active":
                required_fields = ["iban", "mandate_id", "account_holder_name"]
                for field in required_fields:
                    if not getattr(mandate_doc, field, None):
                        validation_result["errors"].append(
                            _("{0} is required for active mandates").format(
                                _(field.title().replace("_", " "))
                            )
                        )
                        validation_result["is_valid"] = False

            # Validate mandate type constraints
            if mandate_doc.mandate_type == "OOFF" and mandate_doc.expiry_date:  # One-off mandates
                if mandate_doc.sign_date and mandate_doc.expiry_date:
                    from frappe.utils import date_diff

                    days_diff = date_diff(mandate_doc.expiry_date, mandate_doc.sign_date)
                    if days_diff > 30:  # One-off mandates shouldn't be valid for more than 30 days
                        validation_result["warnings"].append(
                            _("One-off mandate valid for {0} days - consider if this is intentional").format(
                                days_diff
                            )
                        )

            # Validate member relationship if provided
            if mandate_doc.member:
                if not frappe.db.exists("Member", mandate_doc.member):
                    validation_result["errors"].append(
                        _("Member {0} does not exist").format(mandate_doc.member)
                    )
                    validation_result["is_valid"] = False

            return validation_result

        except Exception as e:
            frappe.log_error(
                title="SEPA Mandate Validation", message=f"Error in validate_mandate_business_rules: {str(e)}"
            )
            validation_result["errors"].append(f"Business rule validation error: {str(e)}")
            validation_result["is_valid"] = False
            return validation_result

    def validate_mandate_uniqueness(self, mandate_doc) -> Dict[str, any]:
        """
        Validate that mandate ID is unique and customer doesn't have conflicting active mandates.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with validation results
        """
        validation_result = {"is_valid": True, "warnings": [], "errors": []}

        try:
            # Check mandate ID uniqueness
            if mandate_doc.mandate_id:
                # Build filters for uniqueness check
                filters = {"mandate_id": mandate_doc.mandate_id}

                # For existing documents, exclude self from the check
                # For new documents (no name yet), check all mandates
                if mandate_doc.name:
                    filters["name"] = ["!=", mandate_doc.name]

                existing_mandate = frappe.db.exists("SEPA Mandate", filters)

                if existing_mandate:
                    validation_result["errors"].append(
                        _("Mandate ID {0} already exists").format(mandate_doc.mandate_id)
                    )
                    validation_result["is_valid"] = False

            # Check for conflicting active mandates for same member/IBAN
            if mandate_doc.member and mandate_doc.iban and mandate_doc.status == "Active":
                conflicting_mandates = frappe.db.sql(
                    """
                    SELECT name, mandate_id
                    FROM `tabSEPA Mandate`
                    WHERE member = %s
                        AND iban = %s
                        AND status = 'Active'
                        AND name != %s
                """,
                    (mandate_doc.member, mandate_doc.iban, mandate_doc.name or ""),
                )

                if conflicting_mandates:
                    validation_result["warnings"].append(
                        _("Member already has active mandate {0} for this IBAN").format(
                            conflicting_mandates[0][1]
                        )
                    )

            return validation_result

        except Exception as e:
            frappe.log_error(
                title="SEPA Mandate Validation", message=f"Error in validate_mandate_uniqueness: {str(e)}"
            )
            validation_result["errors"].append(f"Uniqueness validation error: {str(e)}")
            validation_result["is_valid"] = False
            return validation_result


# Singleton instance for global use
sepa_mandate_validation_service = SEPAMandateValidationService()
