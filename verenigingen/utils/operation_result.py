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

        >>> # With metadata
        >>> result = OperationResult.ok(invoice, created=True, submitted=False)
        >>> print(result.metadata["created"])  # True
    """

    success: bool
    data: Optional[T] = None
    error_message: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
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
        message: str,
        errors: Optional[List[str]] = None,
        error_code: Optional[str] = None,
        **metadata: Any,
    ) -> "OperationResult[T]":
        """
        Create a failed result.

        Args:
            message: Main error message
            errors: List of specific error details
            error_code: Structured error code for monitoring (e.g., "HIST_001")
            **metadata: Additional metadata about the failure

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
        """
        return cls(
            success=False,
            error_message=message,
            errors=errors or [],
            error_code=error_code,
            metadata=metadata,
        )

    def unwrap(self) -> T:
        """
        Get data or raise exception if failed.

        Use this when you want to convert to exception-based flow.

        Returns:
            The result data

        Raises:
            ValueError: If the operation failed

        Examples:
            >>> result = create_member(data)
            >>> member = result.unwrap()  # Raises if failed
        """
        if not self.success:
            error_details = f": {', '.join(self.errors)}" if self.errors else ""
            raise ValueError(f"Operation failed: {self.error_message}{error_details}")
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
                return OperationResult.fail(str(e))
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

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses.

        Returns:
            Dictionary representation

        Examples:
            >>> result = OperationResult.ok(member)
            >>> return result.to_dict()
        """
        result_dict = {
            "success": self.success,
            "timestamp": frappe.utils.now(),
        }

        if self.success:
            # For Document objects, convert to dict
            if hasattr(self.data, "as_dict") and callable(getattr(self.data, "as_dict", None)):
                result_dict["data"] = self.data.as_dict()
            else:
                result_dict["data"] = self.data
        else:
            result_dict["error"] = self.error_message
            if self.errors:
                result_dict["errors"] = self.errors
            if self.error_code:
                result_dict["error_code"] = self.error_code

        # Add metadata
        result_dict.update(self.metadata)

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

    def wrapper(*args, **kwargs) -> OperationResult:
        try:
            result = func(*args, **kwargs)
            return OperationResult.ok(result)
        except Exception as e:
            return OperationResult.fail(str(e))

    return wrapper


__all__ = [
    "OperationResult",
    "MemberResult",
    "VolunteerResult",
    "InvoiceResult",
    "PaymentResult",
    "wrap_operation",
]
