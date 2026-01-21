"""
OperationResult Pattern for Verenigingen

This module provides a unified OperationResult pattern for functions that may fail.
This pattern is preferred over exceptions for expected failure cases and provides
a consistent API for success/failure handling.

Architecture:
    - Generic type-safe result wrapper
    - Builder methods for success and failure cases
    - Integration with exception hierarchy
    - Type hints for better IDE support

Usage:
    from verenigingen.utils.operation_result import OperationResult

    def create_member(data: dict) -> OperationResult[Member]:
        if not data.get("email"):
            return OperationResult.fail("Email is required", errors=["email"])

        member = frappe.get_doc({"doctype": "Member", **data})
        member.insert()
        return OperationResult.ok(member)

    # Using the result
    result = create_member(data)
    if result.success:
        print(f"Created member: {result.data.name}")
    else:
        print(f"Failed: {result.error_message}")
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

import frappe

# Type variable for generic result data
T = TypeVar("T")


class OperationResultException(Exception):
    """
    Exception raised when unwrapping a failed OperationResult.

    This exception preserves all structured information from the OperationResult,
    allowing callers to access error_code, http_status, metadata, etc. when
    converting result-based code to exception-based code.

    Attributes:
        operation_result: The original failed OperationResult
        error_code: Shortcut to operation_result.error_code
        http_status: Shortcut to operation_result.http_status
        errors: Shortcut to operation_result.errors

    Examples:
        >>> result = some_operation()
        >>> try:
        ...     data = result.unwrap()
        ... except OperationResultException as e:
        ...     print(f"Error code: {e.error_code}")
        ...     print(f"HTTP status: {e.http_status}")
        ...     print(f"Details: {e.operation_result.metadata}")
    """

    def __init__(self, operation_result: "OperationResult"):
        self.operation_result = operation_result
        # Build a descriptive message
        error_details = ""
        if operation_result.errors:
            error_details = f": {', '.join(operation_result.errors)}"
        message = f"Operation failed: {operation_result.error_message}{error_details}"
        super().__init__(message)

    @property
    def error_code(self) -> Optional[str]:
        """Get error code from the wrapped result."""
        return self.operation_result.error_code

    @property
    def http_status(self) -> Optional[int]:
        """Get HTTP status from the wrapped result."""
        return self.operation_result.http_status

    @property
    def errors(self) -> List[str]:
        """Get error list from the wrapped result."""
        return self.operation_result.errors


@dataclass
class OperationResult(Generic[T]):
    """
    Result of an operation that may succeed or fail.

    This pattern is preferred over exceptions for expected failure cases
    (validation errors, not found, etc.). Use exceptions for unexpected failures.

    Attributes:
        success: Whether the operation succeeded
        data: Result data if successful, None otherwise
        error_message: Error message if failed, None otherwise
        errors: List of specific error messages
        error_code: Structured error code for monitoring/alerting (e.g., "HIST_001")
        http_status: HTTP status code for API responses (e.g., 400, 404, 500)
        metadata: Additional context about the operation

    Examples:
        >>> # Success case
        >>> result = OperationResult.ok(member_doc)
        >>> if result.success:
        ...     print(result.data.name)

        >>> # Failure case
        >>> result = OperationResult.fail("Validation failed", errors=["Invalid email"])
        >>> if not result.success:
        ...     print(result.error_message)
        ...     print(result.errors)

        >>> # Failure with error code for monitoring
        >>> result = OperationResult.fail(
        ...     "Donation sync failed",
        ...     error_code="HIST_001",
        ...     errors=["Donor not found"]
        ... )

        >>> # Failure with HTTP status
        >>> result = OperationResult.fail(
        ...     "Member not found",
        ...     error_code="NOT_FOUND",
        ...     http_status=404
        ... )

        >>> # With metadata
        >>> result = OperationResult.ok(invoice, created=True, submitted=False)
        >>> print(result.metadata["created"])  # True
    """

    success: bool
    data: Optional[T] = None
    error_message: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    http_status: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> "OperationResult[T]":
        """
        Create a successful result.

        Args:
            data: The result data
            **metadata: Additional metadata about the operation

        Returns:
            OperationResult with success=True

        Examples:
            >>> member = frappe.get_doc("Member", "MEM-001")
            >>> result = OperationResult.ok(member, cached=True)
        """
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(
        cls,
        message: Optional[str] = None,
        errors: Optional[List[str]] = None,
        error_code: Optional[str] = None,
        http_status: Optional[int] = None,
        exception: Optional[Any] = None,
        traceback: Optional[str] = None,
        **metadata: Any,
    ) -> "OperationResult[T]":
        """
        Create a failed result.

        Args:
            message: Main error message
            errors: List of specific error details
            error_code: Structured error code for monitoring (e.g., "HIST_001")
            http_status: HTTP status code for API responses (e.g., 400, 404, 500)
            exception: Exception object or repr string for debugging
            traceback: Traceback string for debugging
            **metadata: Additional metadata about the failure

        Note:
            For backward compatibility, passing `error=` in metadata will be used
            as the message if `message` is not provided. This supports legacy code
            that used `OperationResult.fail(error=str(e), ...)`.

        Returns:
            OperationResult with success=False

        Examples:
            >>> result = OperationResult.fail(
            ...     "Validation failed",
            ...     errors=["Email is required", "Birth date is invalid"]
            ... )

            >>> # With error code for monitoring
            >>> result = OperationResult.fail(
            ...     "History sync failed",
            ...     error_code="HIST_001",
            ...     errors=["Database connection failed"]
            ... )

            >>> # With HTTP status
            >>> result = OperationResult.fail(
            ...     "Resource not found",
            ...     error_code="NOT_FOUND",
            ...     http_status=404
            ... )

            >>> # From exception (typically via from_exception helper)
            >>> result = OperationResult.fail(
            ...     "Operation failed",
            ...     exception=repr(e),
            ...     traceback=traceback.format_exc()
            ... )
        """
        # Handle backward compatibility: support `error=` as alias for `message`
        # This allows legacy code like `OperationResult.fail(error=str(e), ...)`
        # to work, using `error` as fallback if `message` is not provided.
        # Always remove `error` from metadata to prevent it from leaking into the result.
        error_from_metadata = metadata.pop("error", None)
        resolved_message = message
        if resolved_message is None:
            resolved_message = error_from_metadata
        if resolved_message is None:
            resolved_message = "Operation failed"

        # Build clean metadata dict, adding exception/traceback if provided
        clean_metadata = dict(metadata)
        if exception is not None:
            clean_metadata["exception"] = repr(exception) if not isinstance(exception, str) else exception
        if traceback is not None:
            clean_metadata["traceback"] = traceback

        return cls(
            success=False,
            error_message=resolved_message,
            errors=errors or [],
            error_code=error_code,
            http_status=http_status,
            metadata=clean_metadata,
        )

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        http_status: Optional[int] = None,
        include_traceback: bool = True,
        **metadata: Any,
    ) -> "OperationResult[T]":
        """
        Create a failed OperationResult from an exception.

        This is the preferred way to convert exceptions to OperationResult,
        as it captures structured information for debugging while maintaining
        a clean API.

        Args:
            exc: The exception to convert
            message: Override message (defaults to str(exc))
            error_code: Structured error code for monitoring
            http_status: HTTP status code for API responses
            include_traceback: Whether to capture and include the traceback
            **metadata: Additional metadata

        Returns:
            OperationResult with success=False and exception details

        Examples:
            >>> try:
            ...     do_something()
            ... except ValidationError as e:
            ...     return OperationResult.from_exception(
            ...         e,
            ...         message="Validation failed",
            ...         error_code="VALIDATION_ERROR",
            ...         http_status=400
            ...     )

            >>> # Quick conversion with defaults
            >>> except Exception as e:
            ...     return OperationResult.from_exception(e)
        """
        import traceback as tb_module

        tb_str = tb_module.format_exc() if include_traceback else None

        return cls.fail(
            message=message or str(exc),
            errors=[type(exc).__name__],
            error_code=error_code,
            http_status=http_status,
            exception=exc,
            traceback=tb_str,
            **metadata,
        )

    def unwrap(self) -> T:
        """
        Get data or raise exception if failed.

        Use this when you want to convert to exception-based flow.
        The raised OperationResultException preserves all structured information
        from the failed result (error_code, http_status, metadata, etc.).

        Returns:
            The result data

        Raises:
            OperationResultException: If the operation failed, with full result details

        Examples:
            >>> result = create_member(data)
            >>> member = result.unwrap()  # Raises if failed

            >>> # Catching and inspecting the exception
            >>> try:
            ...     member = result.unwrap()
            ... except OperationResultException as e:
            ...     print(f"Error code: {e.error_code}")
            ...     print(f"HTTP status: {e.http_status}")
        """
        if not self.success:
            raise OperationResultException(self)
        return self.data  # type: ignore

    def unwrap_or(self, default: T) -> T:
        """
        Get data or return default if failed.

        Args:
            default: Default value to return on failure

        Returns:
            The result data or default

        Examples:
            >>> result = get_member("MEM-001")
            >>> member = result.unwrap_or(None)
        """
        return self.data if self.success else default

    def map(self, func: callable) -> "OperationResult":
        """
        Transform the result data if successful.

        Args:
            func: Function to apply to the data

        Returns:
            New OperationResult with transformed data

        Examples:
            >>> result = get_member("MEM-001")
            >>> email_result = result.map(lambda m: m.email)
        """
        if self.success and self.data is not None:
            try:
                return OperationResult.ok(func(self.data), **self.metadata)
            except Exception as e:
                # Preserve structured exception info for debugging
                return OperationResult.from_exception(
                    e,
                    message=f"Transform failed: {e}",
                    **self.metadata,
                )
        return self  # type: ignore

    def chain(self, message: str, **extra_metadata: Any) -> "OperationResult[T]":
        """
        Chain this failed result with additional context.

        This is useful for propagating errors up the call stack while adding context.
        If the result is successful, returns self unchanged. If failed, wraps the
        error with additional context.

        Args:
            message: Additional context message
            **extra_metadata: Additional metadata to merge

        Returns:
            Self if successful, new OperationResult with context if failed

        Examples:
            >>> validation_result = validate_member(member)
            >>> if not validation_result.success:
            ...     return validation_result.chain("Failed to approve application")

            >>> # More concise than:
            >>> if not validation_result.success:
            ...     return OperationResult.fail(
            ...         "Failed to approve application",
            ...         errors=validation_result.errors
            ...     )
        """
        if self.success:
            return self

        # Merge errors
        errors = self.errors if self.errors else [self.error_message] if self.error_message else []

        # Merge metadata
        merged_metadata = {**self.metadata, **extra_metadata}

        # Preserve error_code from original result
        return OperationResult.fail(message, errors=errors, error_code=self.error_code, **merged_metadata)

    def to_dict(self, nested: bool = True, scrub_sensitive: bool = False) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses.

        Args:
            nested: If True (default), uses stable nested schema where metadata
                    is under "meta" key and errors are in a structured "error" object.
                    If False, uses legacy flat schema for backward compatibility.
            scrub_sensitive: If True, redact sensitive keys (tokens, passwords, etc.)
                            from metadata before including in output. Use this when
                            returning results to clients or logging.

        Returns:
            Dictionary representation

        Examples:
            >>> result = OperationResult.ok(member)
            >>> return result.to_dict()

            >>> # Nested schema (default) - stable API
            >>> {
            ...     "success": True,
            ...     "timestamp": "2025-01-20 12:00:00",
            ...     "data": {...},
            ...     "meta": {"cached": True}
            ... }

            >>> # Nested schema for failures
            >>> {
            ...     "success": False,
            ...     "timestamp": "2025-01-20 12:00:00",
            ...     "error": {
            ...         "message": "Validation failed",
            ...         "errors": ["Email required"],
            ...         "code": "VALIDATION_ERROR",
            ...         "http_status": 400
            ...     },
            ...     "meta": {"field": "email"}
            ... }

            >>> # Legacy flat schema (nested=False)
            >>> result.to_dict(nested=False)

            >>> # Scrub sensitive data before returning to client
            >>> result.to_dict(scrub_sensitive=True)
        """
        result_dict: Dict[str, Any] = {
            "success": self.success,
            "timestamp": frappe.utils.now(),
        }

        # Serialize data
        def serialize_data(data: Any) -> Any:
            if hasattr(data, "as_dict") and callable(getattr(data, "as_dict", None)):
                return data.as_dict()
            return data

        # Optionally scrub metadata
        metadata_to_use = self.metadata
        if scrub_sensitive and self.metadata:
            from verenigingen.utils.error_handling import scrub_metadata

            metadata_to_use = scrub_metadata(self.metadata)

        if nested:
            # New nested schema - stable, no key collisions
            if self.success:
                result_dict["data"] = serialize_data(self.data)
            else:
                # Structured error object
                error_obj: Dict[str, Any] = {
                    "message": self.error_message,
                }
                if self.errors:
                    error_obj["errors"] = self.errors
                if self.error_code:
                    error_obj["code"] = self.error_code
                if self.http_status:
                    error_obj["http_status"] = self.http_status
                result_dict["error"] = error_obj

            # Metadata under separate key to prevent collisions
            if metadata_to_use:
                result_dict["meta"] = dict(metadata_to_use)
        else:
            # Legacy flat schema for backward compatibility
            if self.success:
                result_dict["data"] = serialize_data(self.data)
            else:
                result_dict["error"] = self.error_message
                if self.errors:
                    result_dict["errors"] = self.errors
                if self.error_code:
                    result_dict["error_code"] = self.error_code
                if self.http_status:
                    result_dict["http_status"] = self.http_status

            # Flatten metadata into top level (legacy behavior - can cause collisions)
            result_dict.update(metadata_to_use)

        return result_dict

    @classmethod
    def from_dict_result(cls, dict_result: Dict[str, Any]) -> "OperationResult":
        """
        Create OperationResult from legacy dict-based result.

        This helps migrate from the old dict-based pattern to OperationResult.

        Args:
            dict_result: Dictionary with 'success', 'data', 'error' keys

        Returns:
            OperationResult instance

        Examples:
            >>> # Legacy code returns dict
            >>> old_result = {"success": True, "data": member}
            >>> result = OperationResult.from_dict_result(old_result)
        """
        if dict_result.get("success"):
            data = dict_result.get("data")
            metadata = {k: v for k, v in dict_result.items() if k not in ["success", "data"]}
            return cls.ok(data, **metadata)
        else:
            error = dict_result.get("error", "Operation failed")
            errors = dict_result.get("errors", [])
            metadata = {k: v for k, v in dict_result.items() if k not in ["success", "error", "errors"]}
            return cls.fail(error, errors=errors, **metadata)


# Convenience type aliases
MemberResult = OperationResult[Any]  # Would be OperationResult[Member] with proper typing
VolunteerResult = OperationResult[Any]
InvoiceResult = OperationResult[Any]
PaymentResult = OperationResult[Any]


def wrap_operation(func: callable) -> callable:
    """
    Decorator to wrap a function that may raise exceptions into OperationResult.

    Use this to convert exception-based code to OperationResult pattern.

    Features:
        - If the function already returns an OperationResult, it is passed through unchanged
        - On exceptions, captures full traceback and exception type for debugging
        - Logs errors immediately via log_error() for observability
        - Preserves function metadata via functools.wraps

    Args:
        func: Function that may raise exceptions

    Returns:
        Wrapped function that returns OperationResult

    Examples:
        >>> @wrap_operation
        ... def create_member(data: dict):
        ...     member = frappe.get_doc({"doctype": "Member", **data})
        ...     member.insert()
        ...     return member
        >>>
        >>> result = create_member(data)  # Returns OperationResult
    """
    import functools

    from verenigingen.utils.error_handling import log_error

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> OperationResult:
        try:
            result = func(*args, **kwargs)
            # If function already returns OperationResult, pass through unchanged
            if isinstance(result, OperationResult):
                return result
            return OperationResult.ok(result)
        except Exception as e:
            # Log error immediately for observability
            trace_id = log_error(
                e,
                context={"function": getattr(func, "__name__", "<unknown>")},
                module=getattr(func, "__module__", "vereinigingen.utils.operation_result"),
            )
            # Return structured result with trace_id for correlation
            return OperationResult.from_exception(
                e,
                message=str(e),
                trace_id=trace_id,
            )

    return wrapper


__all__ = [
    "OperationResult",
    "OperationResultException",
    "MemberResult",
    "VolunteerResult",
    "InvoiceResult",
    "PaymentResult",
    "wrap_operation",
]
