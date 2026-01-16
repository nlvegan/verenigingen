"""
Input Validator for API Security Framework

Provides input data validation and sanitization for API endpoints.

DEPENDENCY RULES:
- This is a pure validation module (no Frappe I/O)
- MAY import from types.py
- MAY import APIValidator.sanitize_text() from api_validators.py (centralized utility)
- MUST NOT import from higher-level modules (api_security_framework, etc.)
"""

import html
import json
from typing import Any, Dict, List

from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.validation.api_validators import APIValidator


class InputValidator:
    """
    Validate and sanitize API input data.

    This class provides methods to validate and sanitize input data
    based on operation type and security requirements.

    INVARIANTS:
    - All string inputs are sanitized to prevent XSS
    - JSON payloads are validated but not mangled
    - File data is passed through without sanitization
    - Max lengths are enforced per operation type
    """

    # Max length limits by operation type
    MAX_LENGTHS = {
        OperationType.MEMBER_DATA: 5000,  # Allow larger data for membership applications
        OperationType.REPORTING: 2000,  # Allow larger data for reports
        OperationType.FINANCIAL: 100000,  # Allow large JSON payloads for batch operations
        OperationType.ADMIN: 50000,  # Allow larger payloads for bulk admin operations
    }
    DEFAULT_MAX_LENGTH = 1000

    # Keys that suggest file data (skip validation)
    FILE_RELATED_KEYS = ["filedata", "file_content", "content", "data", "file"]

    def get_max_length(self, operation_type: OperationType = None) -> int:
        """Get appropriate max_length based on operation type."""
        if operation_type and operation_type in self.MAX_LENGTHS:
            return self.MAX_LENGTHS[operation_type]
        return self.DEFAULT_MAX_LENGTH

    def _decode_html_entities(self, value: str) -> str:
        """Decode HTML entities if present (e.g., &quot; -> ").

        Form submissions often encode special characters as HTML entities.
        We decode them before validation to process the actual content.
        """
        return html.unescape(value)

    def is_file_data(self, key: str, value: str) -> bool:
        """Check if value appears to be file/attachment data."""
        # Check if key suggests file data
        if any(file_key in key.lower() for file_key in self.FILE_RELATED_KEYS):
            return True

        # Check if value looks like base64 data
        if len(value) > 1000:
            if value.startswith("data:"):
                return True
            # Very long alphanumeric string (likely base64)
            if len(value) > 10000 and value.replace("/", "").replace("+", "").replace("=", "").isalnum():
                return True

        return False

    def is_json_payload(self, value: str) -> bool:
        """Check if value is a valid JSON array or object."""
        stripped = value.strip()
        if not stripped.startswith(("[", "{")):
            return False
        try:
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    def validate_string(self, key: str, value: str, max_length: int = DEFAULT_MAX_LENGTH) -> str:
        """Validate and sanitize a string value."""
        # Skip validation for file data
        if self.is_file_data(key, value):
            return value

        # Decode HTML entities first (common issue with form submissions)
        decoded_value = self._decode_html_entities(value)

        # Check if this is a JSON payload
        if self.is_json_payload(decoded_value):
            # Just validate length for JSON payloads
            effective_max_length = 100000
            if len(decoded_value) > effective_max_length:
                raise VValidationError(f"JSON payload too long (max {effective_max_length} characters)")
            return decoded_value

        # Sanitize regular text
        return APIValidator.sanitize_text(decoded_value, max_length=max_length)

    def validate_dict(self, data: Dict[str, Any], max_length: int = 500) -> Dict[str, Any]:
        """Validate dictionary input data recursively."""
        validated = {}
        for key, value in data.items():
            if isinstance(value, str):
                decoded_value = self._decode_html_entities(value)
                validated[key] = APIValidator.sanitize_text(decoded_value, max_length=max_length)
            elif isinstance(value, dict):
                validated[key] = self.validate_dict(value, max_length)
            elif isinstance(value, list):
                validated[key] = self.validate_list(value, max_length)
            else:
                validated[key] = value
        return validated

    def validate_list(self, data: List[Any], max_length: int = 500) -> List[Any]:
        """Validate list input data recursively."""
        validated = []
        for item in data:
            if isinstance(item, str):
                decoded_item = self._decode_html_entities(item)
                validated.append(APIValidator.sanitize_text(decoded_item, max_length=max_length))
            elif isinstance(item, dict):
                validated.append(self.validate_dict(item, max_length))
            elif isinstance(item, list):
                validated.append(self.validate_list(item, max_length))
            else:
                validated.append(item)
        return validated

    def validate(self, operation_type: OperationType = None, **kwargs) -> Dict[str, Any]:
        """
        Validate and sanitize all input data.

        Args:
            operation_type: Type of operation (affects max_length limits)
            **kwargs: Input data to validate

        Returns:
            Dict with validated/sanitized values
        """
        max_length = self.get_max_length(operation_type)
        validated_data = {}

        for key, value in kwargs.items():
            # Skip None values
            if value is None:
                validated_data[key] = value
                continue

            # Handle different types
            if isinstance(value, str):
                validated_data[key] = self.validate_string(key, value, max_length)
            elif isinstance(value, dict):
                validated_data[key] = self.validate_dict(value, max_length)
            elif isinstance(value, list):
                validated_data[key] = self.validate_list(value, max_length)
            else:
                validated_data[key] = value

        return validated_data


# Singleton instance for convenience
_input_validator = None


def get_input_validator() -> InputValidator:
    """Get singleton InputValidator instance."""
    global _input_validator
    if _input_validator is None:
        _input_validator = InputValidator()
    return _input_validator
