"""
Standardized API Response Framework and Utilities

This module provides a comprehensive framework for creating consistent, structured
API responses across all endpoints in the Verenigingen association management system.
It ensures standardized error handling, response formatting, and status management
to provide excellent developer experience and reliable API integration.

Key Features:
- Standardized response structure with consistent formatting
- Comprehensive error handling with detailed error codes and messages
- Support for paginated responses with metadata
- Batch operation results with success/failure tracking
- Automatic exception handling through decorators
- Internationalization support for user-facing messages
- HTTP status code management and response headers

Business Context:
Consistent API responses are critical for frontend integration and external
system integration within the association management ecosystem. This framework
ensures:
- Reliable integration with member portal and administrative interfaces
- Consistent error handling for payment processing and SEPA operations
- Standardized data formats for mobile applications and third-party systems
- Proper status reporting for batch operations and automated processes

Architecture:
This framework integrates with:
- All API endpoints in the Verenigingen application
- Frontend applications requiring structured response data
- External systems integrating with association services
- Error logging and monitoring systems for operational awareness
- Internationalization framework for multi-language support

Response Structure:
All API responses follow a consistent structure:
```json
{
    "success": boolean,
    "status": "success|error|warning|info",
    "timestamp": "ISO timestamp",
    "data": any,                    // Response payload
    "message": "User message",      // Optional user-facing message
    "meta": {},                     // Metadata (pagination, etc.)
    "error": {                      // Error details (if applicable)
        "message": "Error description",
        "code": "ERROR_CODE",
        "details": any,             // Additional error context
        "field_errors": {}          // Field-specific validation errors
    }
}
```

Response Types:
1. Success Responses:
   - Simple success with optional data and message
   - Paginated responses with navigation metadata
   - Batch operation results with success/failure statistics

2. Error Responses:
   - Validation errors with field-specific details
   - Authentication and authorization errors
   - Resource not found errors
   - System errors with appropriate HTTP status codes

3. Special Responses:
   - Batch operation summaries with partial success handling
   - Paginated data with navigation and count metadata
   - Warning responses for non-critical issues

Integration Features:
- Automatic HTTP status code setting for web responses
- Exception handling decorators for seamless error management
- Internationalization support through Frappe's translation framework
- Logging integration for error tracking and monitoring

Author: Development Team
Date: 2025-08-02
Version: 1.0
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _


class ResponseStatus(Enum):
    """Standard response status values"""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class APIResponse:
    """Standardized API response builder for consistent JSON responses"""

    @staticmethod
    def success(data: Any = None, message: str = None, meta: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Create a successful API response

        Args:
            data: Response data payload
            message: Success message
            meta: Additional metadata (pagination, etc.)

        Returns:
            Standardized success response dictionary
        """
        response = {
            "success": True,
            "status": ResponseStatus.SUCCESS.value,
            "timestamp": frappe.utils.now(),
        }

        if data is not None:
            response["data"] = data

        if message:
            response["message"] = _(message)

        if meta:
            response["meta"] = meta

        return response

    @staticmethod
    def error(
        message: str, error_code: str = None, details: Any = None, status_code: int = 400
    ) -> Dict[str, Any]:
        """
        Create an error API response

        Args:
            message: Error message
            error_code: Application-specific error code
            details: Additional error details
            status_code: HTTP status code

        Returns:
            Standardized error response dictionary
        """
        response = {
            "success": False,
            "status": ResponseStatus.ERROR.value,
            "timestamp": frappe.utils.now(),
            "error": {"message": _(message), "code": error_code or "GENERAL_ERROR"},
        }

        if details:
            response["error"]["details"] = details

        # Set HTTP status code if running in web context
        if hasattr(frappe.local, "response"):
            frappe.local.response["http_status_code"] = status_code

        return response

    @staticmethod
    def validation_error(message: str, field_errors: Dict[str, List[str]] = None) -> Dict[str, Any]:
        """
        Create a validation error response

        Args:
            message: General validation error message
            field_errors: Dictionary of field-specific errors

        Returns:
            Standardized validation error response
        """
        response = APIResponse.error(message=message, error_code="VALIDATION_ERROR", status_code=422)

        if field_errors:
            response["error"]["field_errors"] = field_errors

        return response

    @staticmethod
    def not_found(resource: str, identifier: str = None) -> Dict[str, Any]:
        """
        Create a not found error response

        Args:
            resource: Resource type that was not found
            identifier: Resource identifier

        Returns:
            Standardized not found response
        """
        message = _("{0} not found").format(resource)
        if identifier:
            message = _("{0} '{1}' not found").format(resource, identifier)

        return APIResponse.error(message=message, error_code="NOT_FOUND", status_code=404)

    @staticmethod
    def unauthorized(message: str = None) -> Dict[str, Any]:
        """
        Create an unauthorized error response

        Args:
            message: Custom unauthorized message

        Returns:
            Standardized unauthorized response
        """
        default_message = _("Access denied. Please check your permissions.")

        return APIResponse.error(
            message=message or default_message, error_code="UNAUTHORIZED", status_code=401
        )

    @staticmethod
    def forbidden(message: str = None) -> Dict[str, Any]:
        """
        Create a forbidden error response

        Args:
            message: Custom forbidden message

        Returns:
            Standardized forbidden response
        """
        default_message = _("You don't have permission to perform this action.")

        return APIResponse.error(message=message or default_message, error_code="FORBIDDEN", status_code=403)

    @staticmethod
    def paginated(
        data: List[Any], page: int, per_page: int, total_count: int, message: str = None
    ) -> Dict[str, Any]:
        """
        Create a paginated response

        Args:
            data: List of items for current page
            page: Current page number (1-based)
            per_page: Items per page
            total_count: Total number of items
            message: Optional success message

        Returns:
            Standardized paginated response
        """
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        meta = {
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            }
        }

        return APIResponse.success(data=data, message=message, meta=meta)

    @staticmethod
    def batch_operation(
        total: int, successful: int, failed: int, errors: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a batch operation response

        Args:
            total: Total number of items processed
            successful: Number of successful operations
            failed: Number of failed operations
            errors: List of error details for failed operations

        Returns:
            Standardized batch operation response
        """
        success_rate = (successful / total * 100) if total > 0 else 0

        data = {
            "summary": {
                "total": total,
                "successful": successful,
                "failed": failed,
                "success_rate": round(success_rate, 2),
            }
        }

        if errors:
            data["errors"] = errors

        # Determine if overall operation was successful
        is_success = failed == 0
        status = ResponseStatus.SUCCESS if is_success else ResponseStatus.WARNING

        message = _("Batch operation completed")
        if failed > 0:
            message = _("Batch operation completed with {0} errors").format(failed)

        response = {
            "success": is_success,
            "status": status.value,
            "timestamp": frappe.utils.now(),
            "data": data,
            "message": message,
        }

        return response


def api_response_handler(func):
    """
    Decorator to automatically handle API responses and exceptions

    Usage:
        @frappe.whitelist()
        @api_response_handler
        def my_api_function():
            return {"key": "value"}  # Will be wrapped in success response
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)

            # If function already returns a standardized response, pass it through
            if isinstance(result, dict) and "success" in result and "status" in result:
                return result

            # Otherwise, wrap in success response
            return APIResponse.success(data=result)

        except frappe.ValidationError as e:
            return APIResponse.validation_error(str(e))
        except frappe.PermissionError as e:
            return APIResponse.forbidden(str(e))
        except frappe.DoesNotExistError as e:
            return APIResponse.not_found("Resource", str(e))
        except Exception as e:
            frappe.log_error(f"API Error in {func.__name__}: {str(e)}")
            return APIResponse.error(
                message=_("An unexpected error occurred. Please try again."), error_code="INTERNAL_ERROR"
            )

    return wrapper


# Convenience functions for common response patterns
def success_with_data(data: Any, message: str = None) -> Dict[str, Any]:
    """Convenience function for success response with data"""
    return APIResponse.success(data=data, message=message)


def success_with_message(message: str) -> Dict[str, Any]:
    """Convenience function for success response with message only"""
    return APIResponse.success(message=message)


def error_response(message: str, error_code: str = None) -> Dict[str, Any]:
    """Convenience function for error response"""
    return APIResponse.error(message=message, error_code=error_code)


def validation_errors(field_errors: Dict[str, List[str]]) -> Dict[str, Any]:
    """Convenience function for validation errors"""
    return APIResponse.validation_error(message=_("Validation failed"), field_errors=field_errors)
