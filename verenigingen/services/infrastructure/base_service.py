"""
Base Service Classes - Abstract classes providing common service patterns.

This module defines base classes that establish consistent patterns for
service development across the Verenigingen application. All services
should inherit from these base classes to ensure uniform behavior.

Classes:
    - BaseService: Abstract base class for all services
    - StatelessService: Base for stateless utility services
    - StatefulService: Base for services that manage state
    - APIService: Base for API endpoint services
    - DataService: Base for data manipulation services
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import ServiceError, create_service_result, handle_service_error


class BaseService(ABC):
    """Abstract base class for all services.

    Provides common functionality including error handling, logging,
    performance monitoring, and standardized result formatting.
    """

    def __init__(self, service_name: str = None):
        """Initialize base service.

        Args:
            service_name: Human-readable name for this service
        """
        self.service_name = service_name or self.__class__.__name__
        self.logger = logging.getLogger(f"verenigingen.services.{self.service_name}")
        self._metrics = {"calls": 0, "errors": 0, "total_time": 0.0}
        self._metrics_lock = threading.Lock()
        self._is_shutdown = False

    def _start_operation(self, operation_name: str) -> float:
        """Start timing an operation.

        Args:
            operation_name: Name of the operation being timed

        Returns:
            Start time for operation
        """
        self.logger.debug(f"Starting {operation_name}")
        with self._metrics_lock:
            self._metrics["calls"] += 1
        return time.time()

    def _end_operation(self, operation_name: str, start_time: float, success: bool = True):
        """End timing an operation.

        Args:
            operation_name: Name of the operation
            start_time: Start time from _start_operation
            success: Whether the operation succeeded
        """
        duration = time.time() - start_time
        with self._metrics_lock:
            self._metrics["total_time"] += duration
            if not success:
                self._metrics["errors"] += 1

        self.logger.debug(f"Completed {operation_name} in {duration:.3f}s (success: {success})")

    def handle_error(
        self, error: Exception, operation: str, context: Dict = None, raise_error: bool = True
    ) -> Dict:
        """Handle service errors using standardized pattern.

        Args:
            error: The exception that occurred
            operation: Description of the failed operation
            context: Additional context information
            raise_error: Whether to re-raise the exception

        Returns:
            Error result dictionary if not re-raising
        """
        return handle_service_error(
            error=error,
            service_name=self.service_name,
            operation=operation,
            context=context,
            raise_error=raise_error,
        )

    def create_result(
        self,
        success: bool = True,
        message: str = "",
        data: Any = None,
        errors: List[str] = None,
        metadata: Dict = None,
    ) -> Dict:
        """Create standardized service result.

        Args:
            success: Whether the operation succeeded
            message: Human-readable message
            data: Result data
            errors: List of error messages
            metadata: Additional metadata (service name, timestamp, etc.)

        Returns:
            Standardized result dictionary
        """
        result = {
            "success": success,
            "message": message,
            "data": data,
            "errors": errors or [],
            "timestamp": time.time(),
            "service": self.service_name,
        }

        if metadata:
            result["metadata"] = metadata

        return result

    def get_metrics(self) -> Dict:
        """Get performance metrics for this service.

        Returns:
            Dictionary containing call count, error count, and timing info
        """
        with self._metrics_lock:
            avg_time = self._metrics["total_time"] / max(self._metrics["calls"], 1)
            return {
                **self._metrics,
                "average_time": avg_time,
                "error_rate": self._metrics["errors"] / max(self._metrics["calls"], 1),
            }

    @abstractmethod
    def validate_configuration(self) -> bool:
        """Validate that the service is properly configured.

        Returns:
            True if configuration is valid

        Raises:
            ServiceError: If configuration is invalid
        """
        pass

    def cleanup(self):
        """Clean up service resources.

        Should be called when service is no longer needed.
        """
        self._is_shutdown = True
        self.logger.info(f"Service {self.service_name} cleaned up")

    def is_healthy(self) -> bool:
        """Check if service is in a healthy state.

        Returns:
            True if service is healthy
        """
        if self._is_shutdown:
            return False

        with self._metrics_lock:
            # Service is unhealthy if error rate > 50%
            if self._metrics["calls"] > 0 and self._metrics["errors"] / self._metrics["calls"] > 0.5:
                return False

        return True


class StatelessService(BaseService):
    """Base class for stateless utility services.

    Stateless services perform operations without maintaining internal state.
    They are typically used for calculations, validations, and transformations.
    """

    def validate_configuration(self) -> bool:
        """Stateless services have minimal configuration requirements."""
        return True

    def execute_operation(self, operation_func, *args, **kwargs) -> Any:
        """Execute a stateless operation with timing and error handling.

        Args:
            operation_func: Function to execute
            *args: Arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the operation
        """
        operation_name = operation_func.__name__
        start_time = self._start_operation(operation_name)

        try:
            result = operation_func(*args, **kwargs)
            self._end_operation(operation_name, start_time, success=True)
            return result
        except Exception as e:
            self._end_operation(operation_name, start_time, success=False)
            self.handle_error(e, operation_name, {"args": args, "kwargs": kwargs})


class StatefulService(BaseService):
    """Base class for services that manage state.

    Stateful services maintain internal state and typically interact with
    the database or external systems. They require more careful error handling
    and transaction management.
    """

    def __init__(self, service_name: str = None):
        super().__init__(service_name)
        self._state = {}
        self._transaction_active = False

    def validate_configuration(self) -> bool:
        """Validate configuration including database connectivity."""
        try:
            # Basic database connectivity test
            frappe.db.sql("SELECT 1")
            return True
        except Exception as e:
            raise ServiceError(f"Database connectivity check failed: {str(e)}")

    def begin_transaction(self):
        """Begin a database transaction."""
        if not self._transaction_active:
            frappe.db.begin()
            self._transaction_active = True

    def commit_transaction(self):
        """Commit the current transaction."""
        if self._transaction_active:
            frappe.db.commit()
            self._transaction_active = False

    def rollback_transaction(self):
        """Rollback the current transaction."""
        if self._transaction_active:
            frappe.db.rollback()
            self._transaction_active = False

    def execute_with_transaction(self, operation_func, *args, **kwargs) -> Any:
        """Execute operation within a transaction with automatic rollback on error.

        Args:
            operation_func: Function to execute
            *args: Arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the operation
        """
        operation_name = operation_func.__name__
        start_time = self._start_operation(operation_name)

        self.begin_transaction()
        try:
            result = operation_func(*args, **kwargs)
            self.commit_transaction()
            self._end_operation(operation_name, start_time, success=True)
            return result
        except Exception as e:
            self.rollback_transaction()
            self._end_operation(operation_name, start_time, success=False)
            self.handle_error(e, operation_name, {"args": args, "kwargs": kwargs})


class APIService(BaseService):
    """Base class for API endpoint services.

    API services handle web requests and provide standardized response formatting,
    security validation, and input/output processing.
    """

    def validate_configuration(self) -> bool:
        """Validate API service configuration."""
        # Check if security framework is available
        try:
            from verenigingen.utils.security.api_security_framework import OperationType

            return True
        except ImportError:
            self.logger.warning("Security framework not available, using fallback")
            return True

    def validate_permissions(
        self, operation: str, doctype: str = None, context: Dict = None
    ) -> Dict[str, Any]:
        """Validate permissions for API operation.

        Args:
            operation: Operation being performed (create, read, update, delete, list)
            doctype: DocType to check permissions for (defaults to Member)
            context: Additional context for permission check

        Returns:
            Permission validation result
        """
        # Default to Member DocType if not specified
        doctype = doctype or "Member"
        context = context or {}

        # Check if user is authenticated
        if frappe.session.user == "Guest":
            return self.create_result(
                success=False,
                message="Authentication required",
                errors=["User must be authenticated to access this resource"],
            )

        # Check system user permissions
        if frappe.session.user == "Administrator":
            return self.create_result(
                success=True,
                message="Administrator access granted",
                data={"user": frappe.session.user, "permission_level": "admin"},
            )

        # Map operations to permission types
        permission_map = {
            "create": "create",
            "read": "read",
            "update": "write",
            "delete": "delete",
            "list": "read",
            "export": "export",
            "import": "import",
            "print": "print",
            "email": "email",
        }

        permission_type = permission_map.get(operation, "read")

        # Check specific DocType permissions
        if not frappe.has_permission(doctype, permission_type):
            return self.create_result(
                success=False,
                message=f"Insufficient permissions for {operation} on {doctype}",
                errors=[f"User {frappe.session.user} lacks {permission_type} permission for {doctype}"],
            )

        # Additional context-based checks
        permission_level = "standard"
        additional_checks = []

        # Role-based additional permissions
        user_roles = frappe.get_roles(frappe.session.user)
        if "System Manager" in user_roles:
            permission_level = "system_manager"
        elif "Verenigingen Manager" in user_roles:
            permission_level = "manager"
        elif "Verenigingen Member" in user_roles:
            permission_level = "member"

        # Check for sensitive operations
        sensitive_operations = ["delete", "export", "import"]
        if operation in sensitive_operations:
            if permission_level not in ["admin", "system_manager", "manager"]:
                return self.create_result(
                    success=False,
                    message=f"Sensitive operation {operation} requires elevated permissions",
                    errors=[f"Operation {operation} requires manager-level access or higher"],
                )
            additional_checks.append(f"Sensitive operation {operation} validated")

        # Check document-level permissions if document name provided
        doc_name = context.get("doc_name")
        if doc_name and operation in ["read", "update", "delete"]:
            if not frappe.has_permission(doctype, permission_type, doc_name):
                return self.create_result(
                    success=False,
                    message=f"No permission for {operation} on {doctype} {doc_name}",
                    errors=[f"Document-level permission denied for {doctype} {doc_name}"],
                )
            additional_checks.append(f"Document-level permission validated for {doc_name}")

        return self.create_result(
            success=True,
            message=f"Permission granted for {operation} on {doctype}",
            data={
                "user": frappe.session.user,
                "operation": operation,
                "doctype": doctype,
                "permission_type": permission_type,
                "permission_level": permission_level,
                "user_roles": user_roles,
                "additional_checks": additional_checks,
            },
        )

    def validate_input(self, data: Dict, required_fields: List[str] = None) -> Dict:
        """Validate API input data.

        Args:
            data: Input data to validate
            required_fields: List of required field names

        Returns:
            Validation result with errors if any
        """
        errors = []
        required_fields = required_fields or []

        for field in required_fields:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")

        return self.create_result(
            success=len(errors) == 0, message="Input validation completed", errors=errors
        )

    def format_api_response(
        self, success: bool, data: Any = None, message: str = "", errors: List[str] = None
    ) -> Dict:
        """Format API response in standard format.

        Args:
            success: Whether the operation succeeded
            data: Response data
            message: Human-readable message
            errors: List of error messages

        Returns:
            Standardized API response
        """
        return {
            "success": success,
            "message": message,
            "data": data,
            "errors": errors or [],
            "timestamp": frappe.utils.now(),
            "service": self.service_name,
        }

    def get_security_context(self) -> Dict[str, Any]:
        """Get security context for API operations.

        Returns:
            Security context including user, roles, and service information
        """
        try:
            user_roles = frappe.get_roles(frappe.session.user)
            return {
                "user": frappe.session.user,
                "roles": user_roles,
                "service": self.service_name,
                "session_id": getattr(frappe.session, "sid", None),
                "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None,
                "user_agent": frappe.get_request_header("User-Agent", "Unknown"),
                "timestamp": frappe.utils.now(),
            }
        except Exception as e:
            self.logger.warning(f"Failed to get security context: {str(e)}")
            return {
                "user": "unknown",
                "roles": [],
                "service": self.service_name,
                "timestamp": frappe.utils.now(),
            }


class DataService(StatefulService):
    """Base class for data manipulation services.

    Data services handle database operations with optimized querying,
    caching, and data transformation capabilities.
    """

    def __init__(self, service_name: str = None):
        super().__init__(service_name)
        self._cache = {}
        self._cache_enabled = True
        self._cache_lock = threading.Lock()
        self._field_validation_enabled = True

    def enable_cache(self):
        """Enable result caching."""
        self._cache_enabled = True

    def disable_cache(self):
        """Disable result caching."""
        self._cache_enabled = False
        with self._cache_lock:
            self._cache.clear()

    def clear_cache(self):
        """Clear the service cache."""
        with self._cache_lock:
            self._cache.clear()

    def cached_query(self, cache_key: str, query_func, *args, **kwargs) -> Any:
        """Execute query with caching.

        Args:
            cache_key: Unique key for caching the result
            query_func: Function that performs the query
            *args: Arguments for query function
            **kwargs: Keyword arguments for query function

        Returns:
            Query result (cached or fresh)
        """
        with self._cache_lock:
            if self._cache_enabled and cache_key in self._cache:
                self.logger.debug(f"Cache hit for key: {cache_key}")
                return self._cache[cache_key]

        result = self.execute_with_transaction(query_func, *args, **kwargs)

        with self._cache_lock:
            if self._cache_enabled:
                self._cache[cache_key] = result
                self.logger.debug(f"Cached result for key: {cache_key}")

        return result

    def bulk_operation(self, operation_func, items: List[Any], batch_size: int = 100) -> Dict:
        """Execute bulk operations in batches.

        Args:
            operation_func: Function to execute for each item
            items: List of items to process
            batch_size: Number of items to process per batch

        Returns:
            Result summary with success/failure counts
        """
        total_items = len(items)
        processed = 0
        errors = []

        for i in range(0, total_items, batch_size):
            batch = items[i : i + batch_size]
            self.begin_transaction()

            try:
                for item in batch:
                    operation_func(item)
                    processed += 1

                self.commit_transaction()
                self.logger.info(f"Processed batch {i // batch_size + 1}: {len(batch)} items")

            except Exception as e:
                self.rollback_transaction()
                error_msg = f"Batch {i // batch_size + 1} failed: {str(e)}"
                errors.append(error_msg)
                self.logger.error(error_msg)

        return self.create_result(
            success=len(errors) == 0,
            message=f"Bulk operation completed: {processed}/{total_items} items processed",
            data={"processed": processed, "total": total_items, "batch_size": batch_size},
            errors=errors,
        )

    def enable_field_validation(self):
        """Enable field validation for data operations."""
        self._field_validation_enabled = True

    def disable_field_validation(self):
        """Disable field validation for data operations."""
        self._field_validation_enabled = False

    def validate_query_fields(self, doctype: str, query_params: Dict) -> Dict[str, Any]:
        """Validate fields in query parameters.

        Args:
            doctype: DocType to validate against
            query_params: Query parameters with fields to validate

        Returns:
            Validation result
        """
        if not self._field_validation_enabled:
            return {"success": True, "message": "Field validation disabled"}

        try:
            from verenigingen.services.infrastructure.field_validator import validate_query_operation

            return validate_query_operation(doctype, query_params)
        except ImportError:
            self.logger.warning("Field validator not available")
            return {"success": True, "message": "Field validator not available"}

    def safe_query(self, doctype: str, **kwargs) -> List[Dict]:
        """Perform query with field validation.

        Args:
            doctype: DocType to query
            **kwargs: Query parameters

        Returns:
            Query results
        """
        if self._field_validation_enabled:
            validation_result = self.validate_query_fields(doctype, kwargs)
            if not validation_result["success"]:
                raise ValueError(f"Field validation failed: {validation_result['errors']}")

        return frappe.get_all(doctype, **kwargs)

    def safe_get_doc(self, doctype: str, name: str, fields: List[str] = None) -> Dict:
        """Get document with field validation.

        Args:
            doctype: DocType name
            name: Document name
            fields: Fields to retrieve

        Returns:
            Document data
        """
        if self._field_validation_enabled and fields:
            from verenigingen.services.infrastructure.field_validator import validate_service_fields

            validation_result = validate_service_fields(doctype, fields)
            if not validation_result["success"]:
                raise ValueError(f"Field validation failed: {validation_result['errors']}")

        if fields:
            return frappe.get_doc(doctype, name).as_dict(fields=fields)
        else:
            return frappe.get_doc(doctype, name).as_dict()

    def cleanup(self):
        """Clean up data service resources including cache."""
        super().cleanup()
        with self._cache_lock:
            self._cache.clear()
