"""
Validation Utilities

Consolidated utility functions for common validation patterns throughout the Verenigingen codebase.
These utilities ensure consistent validation logic and error handling across all modules.
"""

from datetime import date
from typing import Dict, Optional, Tuple, Union

import frappe
from frappe import _
from frappe.utils import getdate, today


class ValidationError(frappe.ValidationError):
    """Custom validation error for better error handling"""

    pass


class AgeValidationResult:
    """Result object for age validation operations"""

    def __init__(
        self, is_valid: bool, age_years: float, message: Optional[str] = None, warning: Optional[str] = None
    ):
        self.is_valid = is_valid
        self.age_years = age_years
        self.message = message
        self.warning = warning

    def __bool__(self):
        return self.is_valid


class AgeValidator:
    """Centralized age validation utility with configurable business rules"""

    # Age validation contexts with different requirements
    CONTEXTS = {
        "membership": {
            "min_age": 16,
            "max_age": 120,
            "error_template": _("Member must be at least {min_age} years old (current age: {age:.1f})"),
            "max_error_template": _("Please verify birth date - age {age:.1f} years seems unrealistic"),
        },
        "volunteer": {
            "min_age": 16,
            "max_age": 120,
            "error_template": _("Volunteers must be at least {min_age} years old (current age: {age:.1f})"),
            "max_error_template": _("Please verify birth date - age {age:.1f} years seems unrealistic"),
        },
        "voting": {
            "min_age": 18,
            "max_age": 120,
            "error_template": _("Voting rights require minimum age of {min_age} (current age: {age:.1f})"),
            "max_error_template": _("Please verify birth date - age {age:.1f} years seems unrealistic"),
        },
        "student_membership": {
            "min_age": 18,
            "max_age": 30,
            "error_template": _(
                "Student memberships are available for ages {min_age}-{max_age} (current age: {age:.1f})"
            ),
            "max_error_template": _(
                "Student memberships are available for ages {min_age}-{max_age} (current age: {age:.1f})"
            ),
        },
        "youth_membership": {
            "min_age": 16,
            "max_age": 17,
            "error_template": _(
                "Youth memberships are available for ages {min_age}-{max_age} (current age: {age:.1f})"
            ),
            "max_error_template": _(
                "Youth memberships are available for ages {min_age}-{max_age} (current age: {age:.1f})"
            ),
        },
        "senior_membership": {
            "min_age": 65,
            "max_age": 120,
            "error_template": _(
                "Senior memberships are available for ages {min_age}+ (current age: {age:.1f})"
            ),
            "max_error_template": _("Please verify birth date - age {age:.1f} years seems unrealistic"),
        },
    }

    @staticmethod
    def calculate_age(
        birth_date: Union[str, date], reference_date: Optional[Union[str, date]] = None
    ) -> float:
        """
        Calculate age in years with decimal precision

        Args:
            birth_date: Birth date as string or date object
            reference_date: Reference date for calculation (defaults to today)

        Returns:
            Age in years as float
        """
        birth_date_obj = getdate(birth_date) if isinstance(birth_date, str) else birth_date
        reference_date_obj = getdate(reference_date) if reference_date else getdate(today())

        if birth_date_obj > reference_date_obj:
            raise ValidationError(_("Birth date cannot be in the future"))

        age_days = (reference_date_obj - birth_date_obj).days
        return age_days / 365.25

    @classmethod
    def validate_age(
        cls,
        birth_date: Union[str, date],
        context: str = "membership",
        custom_min_age: Optional[int] = None,
        custom_max_age: Optional[int] = None,
        allow_parental_consent: bool = False,
        throw_on_error: bool = True,
    ) -> AgeValidationResult:
        """
        Validate age requirements with context-aware business rules

        Args:
            birth_date: Birth date to validate
            context: Validation context (membership, volunteer, voting, etc.)
            custom_min_age: Override minimum age requirement
            custom_max_age: Override maximum age requirement
            allow_parental_consent: Allow under-age with parental consent
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            AgeValidationResult object
        """
        try:
            age_years = cls.calculate_age(birth_date)
        except ValidationError as e:
            if throw_on_error:
                raise
            return AgeValidationResult(False, 0, str(e))

        # Get context configuration
        context_config = cls.CONTEXTS.get(context, cls.CONTEXTS["membership"])

        # Use custom ages if provided, otherwise fall back to configurable settings or context defaults
        min_age = custom_min_age
        if min_age is None:
            min_age = cls._get_configurable_min_age(context, context_config["min_age"])

        max_age = custom_max_age or context_config["max_age"]

        # Validate minimum age
        if age_years < min_age:
            if allow_parental_consent and context in ["membership", "youth_membership"] and age_years >= 16:
                # Special case: allow 16-17 year olds with parental consent for regular membership
                warning_msg = _("Parental consent required for members under {min_age}").format(
                    min_age=min_age
                )
                return AgeValidationResult(True, age_years, warning=warning_msg)
            else:
                error_msg = context_config["error_template"].format(
                    min_age=min_age, max_age=max_age, age=age_years
                )
                if throw_on_error:
                    raise ValidationError(error_msg)
                return AgeValidationResult(False, age_years, error_msg)

        # Validate maximum age
        if age_years > max_age:
            error_msg = context_config["max_error_template"].format(
                min_age=min_age, max_age=max_age, age=age_years
            )
            if throw_on_error:
                raise ValidationError(error_msg)
            return AgeValidationResult(False, age_years, error_msg)

        # Add warnings for edge cases
        warning = None
        if age_years < 18 and context not in ["youth_membership"]:
            warning = _("Member is under 18 - may require parental consent")
        elif age_years > 100:
            warning = _("Please verify birth date - member would be over 100 years old")

        return AgeValidationResult(True, age_years, warning=warning)

    @classmethod
    def validate_membership_age_for_type(
        cls, birth_date: Union[str, date], membership_type: str, throw_on_error: bool = True
    ) -> AgeValidationResult:
        """
        Validate age requirements for specific membership types

        Args:
            birth_date: Birth date to validate
            membership_type: Type of membership (Student, Youth, Senior, etc.)
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            AgeValidationResult object
        """
        membership_lower = membership_type.lower()

        # Determine context based on membership type
        if "student" in membership_lower:
            context = "student_membership"
        elif "youth" in membership_lower or "junior" in membership_lower:
            context = "youth_membership"
        elif "senior" in membership_lower:
            context = "senior_membership"
        else:
            # Regular membership - use voting age for adult memberships
            context = "voting" if "adult" in membership_lower else "membership"

        return cls.validate_age(birth_date, context=context, throw_on_error=throw_on_error)

    @classmethod
    def _get_configurable_min_age(cls, context: str, fallback_age: int) -> int:
        """
        Get minimum age from configurable settings with fallback to context defaults

        Args:
            context: Validation context
            fallback_age: Fallback age if no configuration found

        Returns:
            Minimum age requirement
        """
        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Map contexts to setting fields
            context_field_map = {
                "membership": "minimum_membership_age",
                "volunteer": "minimum_volunteer_age",
                "voting": "minimum_voting_age",
                "student_membership": "minimum_student_age",
                "youth_membership": "minimum_youth_age",
                "senior_membership": "minimum_senior_age",
            }

            field_name = context_field_map.get(context)
            if field_name and hasattr(settings, field_name):
                configured_age = getattr(settings, field_name)
                if configured_age is not None and configured_age > 0:
                    return int(configured_age)
        except Exception:
            # If settings cannot be loaded, fall back to defaults
            pass

        return fallback_age


class DateRangeValidator:
    """Utility for validating date ranges with common business rules"""

    @staticmethod
    def validate_date_range(
        start_date: Union[str, date],
        end_date: Union[str, date],
        allow_past_start: bool = False,
        allow_equal_dates: bool = False,
        min_duration_days: Optional[int] = None,
        max_duration_days: Optional[int] = None,
        throw_on_error: bool = True,
    ) -> Dict[str, Union[bool, str]]:
        """
        Validate date range with common business rules

        Args:
            start_date: Start date of the range
            end_date: End date of the range
            allow_past_start: Whether start date can be in the past
            allow_equal_dates: Whether start and end dates can be equal
            min_duration_days: Minimum duration in days
            max_duration_days: Maximum duration in days
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            Dict with validation result
        """
        start_obj = getdate(start_date)
        end_obj = getdate(end_date)
        today_obj = getdate(today())

        # Validate date order
        if not allow_equal_dates and start_obj >= end_obj:
            error_msg = _("End date must be after start date")
            if throw_on_error:
                raise ValidationError(error_msg)
            return {"valid": False, "message": error_msg}
        elif allow_equal_dates and start_obj > end_obj:
            error_msg = _("End date cannot be before start date")
            if throw_on_error:
                raise ValidationError(error_msg)
            return {"valid": False, "message": error_msg}

        # Validate past start date
        if not allow_past_start and start_obj < today_obj:
            error_msg = _("Start date cannot be in the past")
            if throw_on_error:
                raise ValidationError(error_msg)
            return {"valid": False, "message": error_msg}

        # Validate duration constraints
        duration_days = (end_obj - start_obj).days

        if min_duration_days and duration_days < min_duration_days:
            error_msg = _("Duration must be at least {min_days} days").format(min_days=min_duration_days)
            if throw_on_error:
                raise ValidationError(error_msg)
            return {"valid": False, "message": error_msg}

        if max_duration_days and duration_days > max_duration_days:
            error_msg = _("Duration cannot exceed {max_days} days").format(max_days=max_duration_days)
            if throw_on_error:
                raise ValidationError(error_msg)
            return {"valid": False, "message": error_msg}

        return {"valid": True, "duration_days": duration_days}

    @staticmethod
    def is_date_today_or_future(date_value: Union[str, date]) -> bool:
        """
        Check if a date is today or in the future

        Args:
            date_value: Date to check as string or date object

        Returns:
            True if date is today or in the future, False otherwise
        """
        date_obj = getdate(date_value) if isinstance(date_value, str) else date_value
        today_obj = getdate(today())
        return date_obj >= today_obj

    @staticmethod
    def is_date_before(date1: Union[str, date], date2: Union[str, date]) -> bool:
        """
        Check if date1 is before date2

        Args:
            date1: First date to compare as string or date object
            date2: Second date to compare as string or date object

        Returns:
            True if date1 is before date2, False otherwise
        """
        date1_obj = getdate(date1) if isinstance(date1, str) else date1
        date2_obj = getdate(date2) if isinstance(date2, str) else date2
        return date1_obj < date2_obj

    @staticmethod
    def is_date_in_past(date_value: Union[str, date]) -> bool:
        """
        Check if a date is in the past (before today)

        Args:
            date_value: Date to check as string or date object

        Returns:
            True if date is in the past, False otherwise
        """
        date_obj = getdate(date_value) if isinstance(date_value, str) else date_value
        today_obj = getdate(today())
        return date_obj < today_obj

    @staticmethod
    def is_date_today_or_past(date_value: Union[str, date]) -> bool:
        """
        Check if a date is today or in the past

        Args:
            date_value: Date to check as string or date object

        Returns:
            True if date is today or in the past, False otherwise
        """
        date_obj = getdate(date_value) if isinstance(date_value, str) else date_value
        today_obj = getdate(today())
        return date_obj <= today_obj

    @staticmethod
    def is_date_today_or_before(date1: Union[str, date], date2: Union[str, date]) -> bool:
        """
        Check if date1 is today or before date2

        Args:
            date1: First date to compare as string or date object
            date2: Second date to compare as string or date object

        Returns:
            True if date1 is today or before date2, False otherwise
        """
        date1_obj = getdate(date1) if isinstance(date1, str) else date1
        date2_obj = getdate(date2) if isinstance(date2, str) else date2
        return date1_obj <= date2_obj

    @staticmethod
    def is_date_in_future(date_value: Union[str, date]) -> bool:
        """
        Check if a date is in the future (after today)

        Args:
            date_value: Date to check as string or date object

        Returns:
            True if date is in the future, False otherwise
        """
        date_obj = getdate(date_value) if isinstance(date_value, str) else date_value
        today_obj = getdate(today())
        return date_obj > today_obj

    @staticmethod
    def is_date_today_or_after(date1: Union[str, date], date2: Union[str, date]) -> bool:
        """
        Check if date1 is today or after date2

        Args:
            date1: First date to compare as string or date object
            date2: Second date to compare as string or date object

        Returns:
            True if date1 is today or after date2, False otherwise
        """
        date1_obj = getdate(date1) if isinstance(date1, str) else date1
        date2_obj = getdate(date2) if isinstance(date2, str) else date2
        return date1_obj >= date2_obj

    @staticmethod
    def validate_historical_date_window(
        date_value: Union[str, date],
        max_years_past: Optional[int] = None,
        max_days_future: Optional[int] = None,
        field_name: str = "date",
        throw_on_error: bool = True,
    ) -> Dict[str, Union[bool, str]]:
        """
        Validate a single date falls within acceptable historical window.

        Useful for validating dates that should be recent (e.g., sign dates, effective dates)
        but allow reasonable historical and future windows for backfilling or scheduling.

        Args:
            date_value: Date to validate
            max_years_past: Maximum years in the past allowed (e.g., 10 for SEPA mandates)
            max_days_future: Maximum days in the future allowed (e.g., 30 for scheduled starts)
            field_name: Name of the field for error messages
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            Dict with validation result: {"valid": bool, "message": str (if invalid)}

        Examples:
            # SEPA mandate sign date (not >10 years past, not future)
            validate_historical_date_window(sign_date, max_years_past=10, max_days_future=0)

            # Membership start date (not >5 years past, allow 30 days future scheduling)
            validate_historical_date_window(start_date, max_years_past=5, max_days_future=30)
        """
        from frappe.utils import date_diff

        date_obj = getdate(date_value) if isinstance(date_value, str) else date_value
        today_obj = getdate(today())

        # Validate not too far in past
        if max_years_past is not None:
            days_ago = date_diff(today_obj, date_obj)
            years_ago = days_ago / 365.0

            if years_ago > max_years_past:
                error_msg = _(
                    "{field_name} cannot be more than {max_years} years in the past. "
                    "Provided: {date_value}"
                ).format(
                    field_name=field_name.replace("_", " ").title(),
                    max_years=max_years_past,
                    date_value=frappe.format_date(date_value),
                )
                if throw_on_error:
                    raise ValidationError(error_msg)
                return {"valid": False, "message": error_msg}

        # Validate not too far in future
        if max_days_future is not None:
            days_future = date_diff(date_obj, today_obj)

            if days_future > max_days_future:
                error_msg = _(
                    "{field_name} cannot be more than {max_days} days in the future. "
                    "Provided: {date_value}"
                ).format(
                    field_name=field_name.replace("_", " ").title(),
                    max_days=max_days_future,
                    date_value=frappe.format_date(date_value),
                )
                if throw_on_error:
                    raise ValidationError(error_msg)
                return {"valid": False, "message": error_msg}

        return {"valid": True}


# Convenience functions for backward compatibility and ease of use


def validate_minimum_age(
    birth_date: Union[str, date], min_age: int = 16, context: str = "membership"
) -> Tuple[bool, float]:
    """
    Legacy wrapper for age validation (backward compatibility)

    Returns:
        Tuple of (is_valid, age_in_years)
    """
    result = AgeValidator.validate_age(
        birth_date, context=context, custom_min_age=min_age, throw_on_error=False
    )
    return result.is_valid, result.age_years


def calculate_age(birth_date: Union[str, date]) -> float:
    """
    Simple age calculation utility

    Returns:
        Age in years as float
    """
    return AgeValidator.calculate_age(birth_date)


def validate_member_age(
    birth_date: Union[str, date], membership_type: str = "Regular"
) -> AgeValidationResult:
    """
    Validate age for membership applications

    Returns:
        AgeValidationResult object
    """
    return AgeValidator.validate_membership_age_for_type(birth_date, membership_type, throw_on_error=False)


def validate_volunteer_age(birth_date: Union[str, date]) -> AgeValidationResult:
    """
    Validate age for volunteer applications

    Returns:
        AgeValidationResult object
    """
    return AgeValidator.validate_age(birth_date, context="volunteer", throw_on_error=False)


def validate_date_range(
    start_date: Union[str, date], end_date: Union[str, date], **kwargs
) -> Dict[str, Union[bool, str]]:
    """
    Simple date range validation utility

    Returns:
        Dict with validation result
    """
    return DateRangeValidator.validate_date_range(start_date, end_date, **kwargs)


def validate_historical_date_window(
    date_value: Union[str, date],
    max_years_past: Optional[int] = None,
    max_days_future: Optional[int] = None,
    field_name: str = "date",
    throw_on_error: bool = True,
) -> Dict[str, Union[bool, str]]:
    """
    Convenience function for historical date window validation

    Returns:
        Dict with validation result
    """
    return DateRangeValidator.validate_historical_date_window(
        date_value, max_years_past, max_days_future, field_name, throw_on_error
    )


class QueryBuilder:
    """Utility for building common database queries with standardized patterns"""

    # DocType status configurations
    DOCTYPE_STATUS_CONFIG = {
        # Core Member Management
        "Member": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Suspended", "Terminated"],
            "uses_docstatus": False,
        },
        "Volunteer": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Suspended", "Terminated"],
            "uses_docstatus": False,
        },
        "Team": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Dissolved"],
            "uses_docstatus": False,
        },
        "Chapter": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Dissolved"],
            "uses_docstatus": False,
        },
        # Membership and Billing
        "Membership": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Expired", "Terminated", "Cancelled"],
            "uses_docstatus": True,
        },
        "SEPA Mandate": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Cancelled", "Expired"],
            "uses_docstatus": False,
        },
        "Membership Dues Schedule": {
            "status_field": "status",
            "active_values": ["Active"],
            "inactive_values": ["Inactive", "Completed", "Cancelled"],
            "uses_docstatus": True,
        },
        # Financial Documents
        "Sales Invoice": {
            "status_field": "status",
            "active_values": ["Unpaid", "Paid", "Overdue", "Partly Paid"],
            "inactive_values": ["Draft", "Cancelled"],
            "uses_docstatus": True,
        },
        "Payment Entry": {
            "status_field": None,  # Uses docstatus only
            "active_values": [],
            "inactive_values": [],
            "uses_docstatus": True,
        },
        "Journal Entry": {
            "status_field": None,  # Uses docstatus only
            "active_values": [],
            "inactive_values": [],
            "uses_docstatus": True,
        },
    }

    @classmethod
    def get_active_records_filters(
        cls, doctype: str, additional_filters: Optional[Dict] = None, include_draft: bool = False
    ) -> Dict:
        """
        Generate standardized filters for active/valid records

        Args:
            doctype: Name of the DocType
            additional_filters: Additional filters to merge
            include_draft: Whether to include draft documents (for docstatus DocTypes)

        Returns:
            Dict of filters for active records
        """
        config = cls.DOCTYPE_STATUS_CONFIG.get(doctype)
        if not config:
            # Fallback for unknown DocTypes
            filters = additional_filters.copy() if additional_filters else {}
            # Try common patterns
            if frappe.db.has_column(doctype, "status"):
                filters["status"] = "Active"
            if frappe.db.has_column(doctype, "docstatus") and not include_draft:
                filters["docstatus"] = 1
            return filters

        filters = {}

        # Add status filter if the DocType uses status field
        if config["status_field"] and config["active_values"]:
            if len(config["active_values"]) == 1:
                filters[config["status_field"]] = config["active_values"][0]
            else:
                filters[config["status_field"]] = ["in", config["active_values"]]

        # Add docstatus filter if the DocType uses workflow
        if config["uses_docstatus"] and not include_draft:
            filters["docstatus"] = 1

        # Merge additional filters
        if additional_filters:
            filters.update(additional_filters)

        return filters

    @classmethod
    def get_inactive_records_filters(
        cls, doctype: str, additional_filters: Optional[Dict] = None, include_cancelled: bool = True
    ) -> Dict:
        """
        Generate standardized filters for inactive/invalid records

        Args:
            doctype: Name of the DocType
            additional_filters: Additional filters to merge
            include_cancelled: Whether to include cancelled documents

        Returns:
            Dict of filters for inactive records
        """
        config = cls.DOCTYPE_STATUS_CONFIG.get(doctype)
        if not config:
            # Fallback for unknown DocTypes
            filters = additional_filters.copy() if additional_filters else {}
            if frappe.db.has_column(doctype, "status"):
                filters["status"] = ["!=", "Active"]
            return filters

        filters = {}

        # Add status filter for inactive values
        if config["status_field"] and config["inactive_values"]:
            if len(config["inactive_values"]) == 1:
                filters[config["status_field"]] = config["inactive_values"][0]
            else:
                filters[config["status_field"]] = ["in", config["inactive_values"]]

        # Add cancelled documents if requested
        if config["uses_docstatus"] and include_cancelled:
            if "docstatus" not in filters:
                filters["docstatus"] = ["in", [0, 2]]  # Draft or Cancelled

        # Merge additional filters
        if additional_filters:
            filters.update(additional_filters)

        return filters

    @classmethod
    def get_all_active_records(
        cls,
        doctype: str,
        fields: Optional[list] = None,
        additional_filters: Optional[Dict] = None,
        filters: Optional[Dict] = None,  # Alias for backward compatibility
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list:
        """
        Get all active records for a DocType with standardized filtering

        Args:
            doctype: Name of the DocType
            fields: Fields to retrieve
            additional_filters: Additional filters to apply (preferred parameter name)
            filters: Alias for additional_filters (backward compatibility)
            limit: Maximum number of records to return
            order_by: Order by clause

        Returns:
            List of active records
        """
        # Handle backward compatibility - prefer additional_filters but allow filters as alias
        filter_dict = additional_filters or filters
        filters = cls.get_active_records_filters(doctype, filter_dict)

        return frappe.get_all(
            doctype, fields=fields or ["name"], filters=filters, limit=limit, order_by=order_by
        )

    @classmethod
    def count_active_records(cls, doctype: str, additional_filters: Optional[Dict] = None) -> int:
        """
        Count active records for a DocType

        Args:
            doctype: Name of the DocType
            additional_filters: Additional filters to apply

        Returns:
            Count of active records
        """
        filters = cls.get_active_records_filters(doctype, additional_filters)
        return frappe.db.count(doctype, filters)

    @classmethod
    def exists_active_record(cls, doctype: str, name: str, additional_filters: Optional[Dict] = None) -> bool:
        """
        Check if an active record exists

        Args:
            doctype: Name of the DocType
            name: Name of the record
            additional_filters: Additional filters to apply

        Returns:
            True if active record exists
        """
        filters = cls.get_active_records_filters(doctype, additional_filters)
        filters["name"] = name
        return bool(frappe.db.exists(doctype, filters))


class DocumentExistenceValidator:
    """Utility for validating document existence with standardized error handling"""

    @staticmethod
    def validate_document_exists(
        doctype: str, name: str, custom_error: Optional[str] = None, throw_on_error: bool = True
    ) -> bool:
        """
        Validate document exists with standardized error handling

        Args:
            doctype: DocType name
            name: Document name
            custom_error: Custom error message
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            True if document exists

        Raises:
            ValidationError: If document doesn't exist and throw_on_error is True
        """
        if not frappe.db.exists(doctype, name):
            error_msg = custom_error or _("The requested {0} '{1}' does not exist").format(doctype, name)
            if throw_on_error:
                frappe.throw(error_msg, frappe.DoesNotExistError)
            return False
        return True

    @staticmethod
    def check_document_exists(doctype: str, name: str) -> bool:
        """
        Check if document exists (simple boolean check without throwing exceptions)

        Args:
            doctype: DocType name
            name: Document name or dict of filters

        Returns:
            True if document exists, False otherwise
        """
        return bool(frappe.db.exists(doctype, name))

    @staticmethod
    def validate_active_document_exists(
        doctype: str, name: str, custom_error: Optional[str] = None, throw_on_error: bool = True
    ) -> bool:
        """
        Validate active document exists

        Args:
            doctype: DocType name
            name: Document name
            custom_error: Custom error message
            throw_on_error: Whether to throw exception on validation failure

        Returns:
            True if active document exists
        """
        if not QueryBuilder.exists_active_record(doctype, name):
            error_msg = custom_error or _(
                "The requested active {0} '{1}' does not exist or is inactive"
            ).format(doctype, name)
            if throw_on_error:
                frappe.throw(error_msg, frappe.DoesNotExistError)
            return False
        return True


# Convenience functions for common query patterns


def get_active_records_filters(doctype: str, additional_filters: Optional[Dict] = None) -> Dict:
    """Get standardized filters for active records"""
    return QueryBuilder.get_active_records_filters(doctype, additional_filters)


def get_all_active_records(doctype: str, **kwargs) -> list:
    """Get all active records with standardized filtering"""
    return QueryBuilder.get_all_active_records(doctype, **kwargs)


def count_active_records(doctype: str, additional_filters: Optional[Dict] = None) -> int:
    """Count active records"""
    return QueryBuilder.count_active_records(doctype, additional_filters)


def validate_document_exists(doctype: str, name: str, custom_error: Optional[str] = None) -> bool:
    """Validate document exists with error handling"""
    return DocumentExistenceValidator.validate_document_exists(
        doctype, name, custom_error, throw_on_error=True
    )
