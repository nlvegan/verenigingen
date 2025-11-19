"""
Service Error Handler - Standardized error handling for extracted services.

This module provides consistent error handling patterns for all services
extracted from member.py to ensure uniform behavior and logging.

Functions:
    - handle_service_error(): Standard error handler with logging
    - safe_import(): Safe import with fallback handling
    - ServiceError: Custom exception class for service-specific errors
"""

import logging

import frappe
from frappe import _


class ServiceError(Exception):
    """Custom exception for service-specific errors with context."""

    def __init__(self, message, service_name=None, context=None, original_error=None):
        self.service_name = service_name
        self.context = context
        self.original_error = original_error
        super().__init__(message)


def handle_service_error(error, service_name, operation, context=None, raise_error=True, log_level="error"):
    """Standardized error handling for all services.

    Args:
        error (Exception): The original error
        service_name (str): Name of the service where error occurred
        operation (str): Description of the operation that failed
        context (dict, optional): Additional context information
        raise_error (bool): Whether to re-raise the error after logging
        log_level (str): Logging level (error, warning, info)

    Returns:
        dict: Error result with success=False and error details

    Raises:
        ServiceError: If raise_error is True
    """
    error_message = str(error)
    context_str = f" | Context: {context}" if context else ""
    full_message = f"[{service_name}] {operation} failed: {error_message}{context_str}"

    # Log the error with appropriate level
    if log_level == "error":
        frappe.log_error(full_message, f"{service_name} Error")
    elif log_level == "warning":
        frappe.logger().warning(full_message)
    else:
        frappe.logger().info(full_message)

    # Create standardized error result
    error_result = {
        "success": False,
        "error": error_message,
        "service": service_name,
        "operation": operation,
        "context": context,
    }

    if raise_error:
        raise ServiceError(
            f"{operation} failed: {error_message}",
            service_name=service_name,
            context=context,
            original_error=error,
        )

    return error_result


def safe_import(module_name, fallback_factory=None, service_name="Unknown"):
    """Safely import a module with fallback handling.

    Args:
        module_name (str): Module to import
        fallback_factory (callable, optional): Function that returns fallback object
        service_name (str): Name of service attempting import

    Returns:
        module: Imported module or fallback object

    Raises:
        ServiceError: If import fails and no fallback provided
    """
    try:
        # Dynamic import
        if "." in module_name:
            module_parts = module_name.split(".")
            module = __import__(module_name, fromlist=[module_parts[-1]])
            return module
        else:
            return __import__(module_name)
    except ImportError as e:
        if fallback_factory:
            frappe.logger().warning(
                f"[{service_name}] Failed to import {module_name}, using fallback: {str(e)}"
            )
            return fallback_factory()
        else:
            handle_service_error(e, service_name, f"Import {module_name}", {"module": module_name})


def create_service_result(success=True, data=None, error=None, service_name=None, operation=None):
    """Create standardized service result object.

    Args:
        success (bool): Whether operation succeeded
        data: Result data if successful
        error (str): Error message if failed
        service_name (str): Name of service
        operation (str): Operation performed

    Returns:
        dict: Standardized result object
    """
    result = {
        "success": success,
        "timestamp": frappe.utils.now(),
    }

    if success:
        result["data"] = data
    else:
        result["error"] = error
        if service_name:
            result["service"] = service_name
        if operation:
            result["operation"] = operation

    return result


def validate_required_fields(doc, required_fields, service_name, operation="validation"):
    """Validate that required fields are present on a document.

    Args:
        doc: Document object to validate
        required_fields (list): List of required field names
        service_name (str): Name of service performing validation
        operation (str): Operation being performed

    Returns:
        dict: Validation result

    Raises:
        ServiceError: If validation fails
    """
    missing_fields = []

    for field in required_fields:
        if not hasattr(doc, field) or not getattr(doc, field):
            missing_fields.append(field)

    if missing_fields:
        error_message = f"Missing required fields: {', '.join(missing_fields)}"
        handle_service_error(
            ValueError(error_message),
            service_name,
            operation,
            {"missing_fields": missing_fields, "doc_name": getattr(doc, "name", "Unknown")},
        )

    return create_service_result(success=True, service_name=service_name, operation=operation)
