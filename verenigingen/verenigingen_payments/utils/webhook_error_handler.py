"""
Webhook Error Handler

Comprehensive error handling and logging for webhook processing.
Implements correlation IDs and structured error responses.
"""

import traceback
import uuid
from typing import Any, Dict, Optional

import frappe
from frappe.utils import now

from verenigingen.verenigingen_payments.utils.shared.responses import ResponseBuilder


class WebhookErrorHandler:
    """Centralized error handling for webhook operations"""

    def __init__(self, webhook_type: str = "webhook", correlation_id: Optional[str] = None):
        self.webhook_type = webhook_type
        self.correlation_id = correlation_id or str(uuid.uuid4())[:8]
        self.logger = frappe.logger()

    def log_info(self, message: str, extra_data: Optional[Dict] = None) -> None:
        """Log info message with correlation ID"""
        log_message = f"[{self.webhook_type}:{self.correlation_id}] {message}"
        if extra_data:
            log_message += f" | Data: {frappe.as_json(extra_data)}"
        self.logger.info(log_message)

    def log_warning(self, message: str, extra_data: Optional[Dict] = None) -> None:
        """Log warning message with correlation ID"""
        log_message = f"⚠️ [{self.webhook_type}:{self.correlation_id}] {message}"
        if extra_data:
            log_message += f" | Data: {frappe.as_json(extra_data)}"
        self.logger.warning(log_message)

    def log_error(
        self, message: str, exception: Optional[Exception] = None, extra_data: Optional[Dict] = None
    ) -> None:
        """Log error message with correlation ID and optional exception details"""
        log_message = f"❌ [{self.webhook_type}:{self.correlation_id}] {message}"
        if extra_data:
            log_message += f" | Data: {frappe.as_json(extra_data)}"

        self.logger.error(log_message)

        # Log full traceback for exceptions
        if exception:
            frappe.log_error(
                f"{message}: {str(exception)}\n\nCorrelation ID: {self.correlation_id}\n\n{traceback.format_exc()}",
                f"{self.webhook_type.title()} Error [{self.correlation_id}]",
            )

    def handle_validation_error(self, error_message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        """Handle validation errors with structured response."""
        self.log_warning(f"Validation failed: {error_message}", details)
        response = ResponseBuilder.error(error_message, status="validation_error", details=details or {})
        # The original dict never included error_code; keep the shape identical.
        response.pop("error_code", None)
        response["correlation_id"] = self.correlation_id
        response["timestamp"] = now()
        return response

    def handle_business_logic_error(
        self, error_message: str, exception: Optional[Exception] = None, details: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Handle business logic errors with structured response."""
        self.log_error(f"Business logic error: {error_message}", exception, details)
        response = ResponseBuilder.error(error_message, status="business_error", details=details or {})
        # The original dict never included error_code; keep the shape identical.
        response.pop("error_code", None)
        response["correlation_id"] = self.correlation_id
        response["timestamp"] = now()
        return response

    def handle_system_error(
        self, error_message: str, exception: Optional[Exception] = None, details: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Handle system/technical errors with structured response."""
        self.log_error(f"System error: {error_message}", exception, details)
        response = ResponseBuilder.error("Internal processing error occurred", status="system_error")
        response["correlation_id"] = self.correlation_id
        response["timestamp"] = now()
        # Don't expose internal details in the response for security
        response["internal_message"] = error_message if frappe.conf.get("developer_mode") else None
        # Remove the error_code/details keys that ResponseBuilder adds but the original dict never had
        response.pop("error_code", None)
        response.pop("details", None)
        return response

    def handle_external_api_error(
        self, api_name: str, error_message: str, exception: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """Handle external API errors (like Mollie API failures)."""
        self.log_error(f"{api_name} API error: {error_message}", exception, {"api": api_name})
        response = ResponseBuilder.error(
            f"External service ({api_name}) error occurred", status="external_api_error"
        )
        response["correlation_id"] = self.correlation_id
        response["timestamp"] = now()
        response["api_name"] = api_name
        # Remove the error_code/details keys that ResponseBuilder adds but the original dict never had
        response.pop("error_code", None)
        response.pop("details", None)
        return response

    def wrap_with_error_handling(self, operation_name: str, operation_func, *args, **kwargs):
        """
        Wrapper function that adds comprehensive error handling to any operation

        Args:
            operation_name: Human-readable name of the operation
            operation_func: Function to execute
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Either the direct result (for successful operations) or error dict
        """
        try:
            self.log_info(f"Starting operation: {operation_name}")
            result = operation_func(*args, **kwargs)
            self.log_info(f"Completed operation: {operation_name}")

            # If result is already a dict with status, check for error conditions
            if isinstance(result, dict) and "status" in result:
                if result["status"] in ["error", "validation_error", "business_error"]:
                    return result
                elif result["status"] in ["ignored", "warning", "skipped"]:
                    # These are valid non-error states
                    return result
                else:
                    # For success states, return the result as-is
                    return result
            else:
                # Raw result (not a status dict) - return as-is for successful operations
                return result

        # Order matters: PermissionError must precede ValidationError because
        # our local verenigingen.utils.error_handling.PermissionError multi-
        # inherits from both (see PR #107). DoesNotExistError extends
        # ValidationError in Frappe (frappe/exceptions.py:44 — http 404),
        # so it must precede ValidationError too; otherwise the 404 path
        # is silently routed to the generic validation handler.
        # DuplicateEntryError extends NameError (not ValidationError), so
        # its position relative to ValidationError doesn't matter -- but
        # UniqueValidationError (a unique-FIELD collision) DOES extend
        # ValidationError, so it must precede that branch too (#699), or a
        # unique-field collision gets the generic "validation failed"
        # treatment and leaks the raw exception repr into the response's
        # `details` instead of the clean "Duplicate entry" message.
        except frappe.PermissionError as e:
            return self.handle_business_logic_error(f"Permission denied during {operation_name}", e)

        except frappe.DoesNotExistError as e:
            return self.handle_business_logic_error(f"Required record not found during {operation_name}", e)

        except (frappe.DuplicateEntryError, frappe.UniqueValidationError) as e:
            return self.handle_business_logic_error(f"Duplicate entry during {operation_name}", e)

        except frappe.ValidationError as e:
            return self.handle_validation_error(
                f"{operation_name} validation failed", {"validation_error": str(e)}
            )

        except Exception as e:
            # Catch-all for unexpected system errors
            return self.handle_system_error(f"Unexpected error during {operation_name}", e)

    def create_success_response(self, message: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Create structured success response.

        NOTE: data is merged FLAT into the response (not nested under a "data" key).
        This is intentional — callers expect top-level keys such as "payment_entry".
        ResponseBuilder.success would nest under data=, so we use it only for the
        base dict and apply the flat merge ourselves.
        """
        # Build base via ResponseBuilder then strip the "data" key (we merge flat below)
        response = ResponseBuilder.success(message)
        response.pop("data", None)
        response["correlation_id"] = self.correlation_id
        response["timestamp"] = now()

        if data:
            response.update(data)

        self.log_info(f"Success: {message}")
        return response

    def is_error_result(self, result) -> bool:
        """Check if a result represents an error condition"""
        if isinstance(result, dict) and "status" in result:
            return result["status"] in [
                "error",
                "validation_error",
                "business_error",
                "system_error",
                "external_api_error",
            ]
        return False

    def update_webhook_log(self, webhook_log, result: Dict[str, Any]) -> None:
        """Update webhook processing log with result and correlation ID"""
        try:
            if not webhook_log:
                return

            webhook_log.correlation_id = self.correlation_id
            webhook_log.status = "success" if result.get("status") == "success" else "error"
            webhook_log.processing_result = frappe.as_json(result)

            if result.get("status") not in ["success"]:
                webhook_log.error_details = result.get("message", "Unknown error")

            webhook_log.save()

        except Exception as e:
            self.log_error(
                "Failed to update webhook log",
                e,
                {"webhook_log_name": webhook_log.name if webhook_log else None},
            )

    def get_correlation_id(self) -> str:
        """Get the correlation ID for this processing session"""
        return self.correlation_id
