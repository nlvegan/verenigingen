"""
API validation utilities for Verenigingen app

This module provides consistent input validation, sanitization, and security
checks for API endpoints to prevent common security vulnerabilities.
"""

import re
from functools import wraps
from typing import Any, Dict, List, Optional, Union

import frappe

from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.error_handling import PermissionError, ValidationError


class APIValidator:
    """API input validation and sanitization utilities"""

    # Common regex patterns
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    PHONE_PATTERN = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")
    DUTCH_POSTAL_CODE_PATTERN = re.compile(r"^\d{4}[A-Z]{2}$")
    IBAN_PATTERN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{4}\d{10}$")

    # Safe characters for different field types
    SAFE_NAME_CHARS = re.compile(r"^[a-zA-Z\s\-\'\.]+$")
    SAFE_ALPHANUMERIC = re.compile(r"^[a-zA-Z0-9\s\-_\.]+$")

    @classmethod
    def validate_email(cls, email: str, required: bool = True) -> Optional[str]:
        """
        Validate and normalize email address

        Args:
            email: Email address to validate
            required: Whether email is required

        Returns:
            Normalized email address

        Raises:
            ValidationError: If email is invalid
        """
        if not email:
            if required:
                raise ValidationError("Email address is required")
            return None

        # Normalize email
        email = email.strip().lower()

        # Check length
        max_length = ConfigManager.get("max_email_length", 254)
        if len(email) > max_length:
            raise ValidationError(f"Email address too long (max {max_length} characters)")

        # Validate format
        if not cls.EMAIL_PATTERN.match(email):
            raise ValidationError("Invalid email address format")

        return email

    @classmethod
    def validate_name(cls, name: str, field_name: str = "name", required: bool = True) -> Optional[str]:
        """
        Validate and sanitize name fields

        Args:
            name: Name to validate
            field_name: Name of the field for error messages
            required: Whether name is required

        Returns:
            Sanitized name

        Raises:
            ValidationError: If name is invalid
        """
        if not name:
            if required:
                raise ValidationError(f"{field_name} is required")
            return None

        # Strip whitespace and normalize
        name = name.strip()

        # Check length
        max_length = ConfigManager.get("max_name_length", 100)
        if len(name) > max_length:
            raise ValidationError(f"{field_name} too long (max {max_length} characters)")

        if len(name) < 1:
            raise ValidationError(f"{field_name} cannot be empty")

        # Check for safe characters
        if not cls.SAFE_NAME_CHARS.match(name):
            raise ValidationError(f"{field_name} contains invalid characters")

        return name

    @classmethod
    def validate_phone(cls, phone: str, required: bool = False) -> Optional[str]:
        """
        Validate and normalize phone number

        Args:
            phone: Phone number to validate
            required: Whether phone is required

        Returns:
            Normalized phone number

        Raises:
            ValidationError: If phone is invalid
        """
        if not phone:
            if required:
                raise ValidationError("Phone number is required")
            return None

        # Strip whitespace
        phone = phone.strip()

        # Validate format
        if not cls.PHONE_PATTERN.match(phone):
            raise ValidationError("Invalid phone number format")

        return phone

    @classmethod
    def validate_postal_code(
        cls, postal_code: str, country: str = "NL", required: bool = True
    ) -> Optional[str]:
        """
        Validate postal code format

        Args:
            postal_code: Postal code to validate
            country: Country code (currently only supports NL)
            required: Whether postal code is required

        Returns:
            Normalized postal code

        Raises:
            ValidationError: If postal code is invalid
        """
        if not postal_code:
            if required:
                raise ValidationError("Postal code is required")
            return None

        # Normalize postal code
        postal_code = postal_code.upper().replace(" ", "")

        if country == "NL":
            if not cls.DUTCH_POSTAL_CODE_PATTERN.match(postal_code):
                raise ValidationError("Invalid Dutch postal code format (expected: 1234AB)")
        else:
            raise ValidationError(f"Postal code validation not supported for country: {country}")

        return postal_code

    @classmethod
    def validate_iban(cls, iban: str, required: bool = False) -> Optional[str]:
        """
        Validate IBAN format

        Args:
            iban: IBAN to validate
            required: Whether IBAN is required

        Returns:
            Normalized IBAN

        Raises:
            ValidationError: If IBAN is invalid
        """
        if not iban:
            if required:
                raise ValidationError("IBAN is required")
            return None

        # Normalize IBAN
        iban = iban.upper().replace(" ", "")

        # Check basic format
        if not cls.IBAN_PATTERN.match(iban):
            raise ValidationError("Invalid IBAN format")

        # For more thorough validation, could implement MOD-97 check here

        return iban

    @classmethod
    def validate_amount(
        cls,
        amount: Union[str, float, int],
        min_amount: float = 0,
        max_amount: float = None,
        required: bool = True,
    ) -> Optional[float]:
        """
        Validate monetary amount

        Args:
            amount: Amount to validate
            min_amount: Minimum allowed amount
            max_amount: Maximum allowed amount
            required: Whether amount is required

        Returns:
            Validated amount as float

        Raises:
            ValidationError: If amount is invalid
        """
        if amount is None or amount == "":
            if required:
                raise ValidationError("Amount is required")
            return None

        # Convert to float
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            raise ValidationError("Invalid amount format")

        # Check range
        if amount < min_amount:
            raise ValidationError(f"Amount must be at least {min_amount}")

        if max_amount is not None and amount > max_amount:
            raise ValidationError(f"Amount cannot exceed {max_amount}")

        # Round to 2 decimal places for currency
        return round(amount, 2)

    @classmethod
    def validate_date(
        cls, date_value: Union[str, frappe.utils.datetime], required: bool = True
    ) -> Optional[str]:
        """
        Validate date format

        Args:
            date_value: Date to validate
            required: Whether date is required

        Returns:
            Normalized date string

        Raises:
            ValidationError: If date is invalid
        """
        if not date_value:
            if required:
                raise ValidationError("Date is required")
            return None

        # Try to parse date
        try:
            if isinstance(date_value, str):
                parsed_date = frappe.utils.getdate(date_value)
            else:
                parsed_date = date_value

            return frappe.utils.formatdate(parsed_date)
        except:
            raise ValidationError("Invalid date format")

    @classmethod
    def sanitize_text(cls, text: str, max_length: int = 1000, allow_html: bool = False) -> str:
        """
        Sanitize text input to prevent XSS and other attacks

        Args:
            text: Text to sanitize
            max_length: Maximum allowed length
            allow_html: Whether to allow HTML tags

        Returns:
            Sanitized text

        Raises:
            ValidationError: If text is too long
        """
        if not text:
            return ""

        # Strip whitespace
        text = text.strip()

        # Check length
        if len(text) > max_length:
            raise ValidationError(f"Text too long (max {max_length} characters)")

        # Remove or escape HTML if not allowed
        if not allow_html:
            import html

            text = html.escape(text)

        return text


def validate_api_input(**validators):
    """
    Decorator to validate API input parameters

    Usage:
        @validate_api_input(
            email=APIValidator.validate_email,
            amount=lambda x: APIValidator.validate_amount(x, min_amount=0)
        )
        def my_api_function(email, amount):
            # Function receives validated parameters
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Validate and sanitize inputs
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    try:
                        kwargs[param_name] = validator(kwargs[param_name])
                    except ValidationError as e:
                        raise ValidationError(f"Invalid {param_name}: {str(e)}")

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_roles(required_roles: List[str], any_role: bool = True):
    """
    Decorator to require specific roles for API access

    Args:
        required_roles: List of required roles
        any_role: If True, user needs any of the roles; if False, user needs all roles
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_roles = frappe.get_roles()

            if any_role:
                has_permission = any(role in user_roles for role in required_roles)
            else:
                has_permission = all(role in user_roles for role in required_roles)

            if not has_permission:
                raise PermissionError(f"Access denied. Required roles: {', '.join(required_roles)}")

            return func(*args, **kwargs)

        return wrapper

    return decorator


def rate_limit(max_requests: int = 100, window_minutes: int = 60):
    """
    Decorator to implement rate limiting for API endpoints

    Args:
        max_requests: Maximum requests allowed
        window_minutes: Time window in minutes
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Simple rate limiting implementation
            # In production, this would use Redis or similar
            # cache_key = "rate_limit:{frappe.session.user}:{func.__name__}"

            # For now, just log the rate limit attempt
            frappe.logger("verenigingen.rate_limit").info(
                "Rate limit check for {frappe.session.user} on {func.__name__}"
            )

            return func(*args, **kwargs)

        return wrapper

    return decorator


# Common validation patterns for API endpoints


def validate_member_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate member creation/update data"""
    validated = {}

    # Required fields
    validated["first_name"] = APIValidator.validate_name(data.get("first_name"), "first name", required=True)
    validated["last_name"] = APIValidator.validate_name(data.get("last_name"), "last name", required=True)
    validated["email_id"] = APIValidator.validate_email(data.get("email_id"), required=True)

    # Optional fields
    if "phone" in data:
        validated["phone"] = APIValidator.validate_phone(data["phone"])

    if "postal_code" in data:
        validated["postal_code"] = APIValidator.validate_postal_code(data["postal_code"])

    # Sanitize text fields
    for field in ["address_line_1", "address_line_2", "city"]:
        if field in data:
            validated[field] = APIValidator.sanitize_text(data[field], max_length=200)

    return validated


def validate_payment_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate payment processing data"""
    validated = {}

    # Required fields
    validated["amount"] = APIValidator.validate_amount(data.get("amount"), min_amount=0.01, required=True)

    # Optional fields
    if "iban" in data:
        validated["iban"] = APIValidator.validate_iban(data["iban"])

    if "description" in data:
        validated["description"] = APIValidator.sanitize_text(data["description"], max_length=500)

    return validated


def validate_volunteer_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate volunteer registration data"""
    validated = {}

    # Text fields
    for field in ["skills", "availability", "interests"]:
        if field in data:
            validated[field] = APIValidator.sanitize_text(data[field], max_length=1000)

    return validated


# Security utilities


def check_sql_injection(query: str) -> bool:
    """
    Check for potential SQL injection patterns

    Args:
        query: SQL query to check

    Returns:
        True if query appears safe
    """
    # Simple SQL injection detection patterns
    dangerous_patterns = [
        r"('\s*(or|and)\s+'.*'=.*')",
        r"(union\s+select)",
        r"(drop\s+table)",
        r"(insert\s+into)",
        r"(delete\s+from)",
        r"(update\s+.*set)",
        r"(exec\s*\()",
        r"(script\s*>)",
    ]

    query_lower = query.lower()
    for pattern in dangerous_patterns:
        if re.search(pattern, query_lower):
            return False

    return True


def sanitize_filter_params(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize filter parameters for database queries

    Args:
        filters: Filter dictionary

    Returns:
        Sanitized filters
    """
    sanitized = {}

    for key, value in filters.items():
        # Sanitize key names
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            continue  # Skip invalid field names

        # Sanitize values
        if isinstance(value, str):
            # Check for SQL injection attempts
            if not check_sql_injection(value):
                continue  # Skip dangerous values

            sanitized[key] = APIValidator.sanitize_text(value, max_length=200)
        elif isinstance(value, (int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            # Sanitize list values
            sanitized_list = []
            for item in value:
                if isinstance(item, str) and check_sql_injection(item):
                    sanitized_list.append(APIValidator.sanitize_text(item, max_length=200))
                elif isinstance(item, (int, float)):
                    sanitized_list.append(item)

            if sanitized_list:
                sanitized[key] = sanitized_list

    return sanitized
