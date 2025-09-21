"""
Example Service - Demonstration of service infrastructure usage.

This module provides an example of how to build services using the new
infrastructure components including base classes, configuration, metrics,
and testing frameworks.

This serves as a template and reference for future service development.
"""

import time
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import DataService, StatelessService
from verenigingen.services.infrastructure.service_config import get_service_config
from verenigingen.services.infrastructure.service_metrics import record_operation
from verenigingen.utils.security.api_security_framework import public_api, standard_api
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.service_error_handler import ServiceError


class ExampleCalculationService(StatelessService):
    """Example stateless service demonstrating infrastructure usage."""

    def __init__(self, service_name: str = "example_calculation"):
        super().__init__(service_name)
        self.config = get_service_config(service_name)

        # Configure service-specific settings
        self.config.set("max_calculation_value", 10000, required=True)
        self.config.set("enable_caching", True)
        self.config.add_validator("max_calculation_value", lambda x: isinstance(x, (int, float)) and x > 0)

    def validate_configuration(self) -> bool:
        """Validate service configuration."""
        errors = self.config.validate()
        if errors:
            raise ServiceError(f"Configuration validation failed: {'; '.join(errors)}")
        return True

    def calculate_fibonacci(self, n: int) -> Dict:
        """Calculate Fibonacci number with performance monitoring.

        Args:
            n: Number to calculate Fibonacci for

        Returns:
            Result dictionary with calculation details
        """

        def _fibonacci_operation():
            # Validate input
            max_value = self.config.get("max_calculation_value")
            if n > max_value:
                raise ServiceError(f"Input {n} exceeds maximum allowed value {max_value}")

            if n < 0:
                raise ServiceError("Fibonacci calculation requires non-negative input")

            # Calculate Fibonacci
            if n <= 1:
                return n

            a, b = 0, 1
            for i in range(2, n + 1):
                a, b = b, a + b

            return b

        # Use base class operation execution with timing and error handling
        start_time = time.time()
        try:
            result = self.execute_operation(_fibonacci_operation)
            duration = time.time() - start_time

            # Record metrics
            record_operation(self.service_name, "calculate_fibonacci", duration, success=True)

            return self.create_result(
                success=True,
                message=f"Calculated Fibonacci({n}) successfully",
                data={
                    "input": n,
                    "result": result,
                    "calculation_time": duration,
                    "service": self.service_name,
                },
            )

        except Exception as e:
            duration = time.time() - start_time
            record_operation(self.service_name, "calculate_fibonacci", duration, success=False)
            return self.handle_error(e, "calculate_fibonacci", {"input": n}, raise_error=False)

    def batch_calculate(self, numbers: List[int]) -> Dict:
        """Calculate Fibonacci for multiple numbers.

        Args:
            numbers: List of numbers to calculate

        Returns:
            Batch calculation results
        """
        start_time = time.time()
        results = []
        errors = []

        for num in numbers:
            try:
                result = self.calculate_fibonacci(num)
                results.append(result)
            except Exception as e:
                errors.append(f"Error calculating Fibonacci({num}): {str(e)}")

        duration = time.time() - start_time
        success = len(errors) == 0

        record_operation(self.service_name, "batch_calculate", duration, success=success)

        return self.create_result(
            success=success,
            message=f"Batch calculation completed: {len(results)} successful, {len(errors)} errors",
            data={
                "results": results,
                "total_processed": len(numbers),
                "successful": len(results),
                "failed": len(errors),
                "total_time": duration,
            },
            errors=errors,
        )


class ExampleDataService(DataService):
    """Example data service demonstrating database operations with infrastructure."""

    def __init__(self, service_name: str = "example_data"):
        super().__init__(service_name)
        self.config = get_service_config(service_name)

        # Configure data service settings
        self.config.set("default_limit", 100)
        self.config.set("max_batch_size", 1000)
        self.config.set("enable_caching", True)

    def validate_configuration(self) -> bool:
        """Validate data service configuration."""
        # Call parent validation (includes database connectivity)
        return super().validate_configuration()

    def search_members(self, search_term: str = "", limit: int = None) -> Dict:
        """Search for members with caching and performance monitoring.

        Args:
            search_term: Term to search for in member names
            limit: Maximum number of results

        Returns:
            Search results with metadata
        """

        def _search_operation():
            limit_value = limit or self.config.get("default_limit")

            if self.config.get("enable_caching"):
                cache_key = f"member_search:{search_term}:{limit_value}"
                return self.cached_query(cache_key, self._perform_member_search, search_term, limit_value)
            else:
                return self._perform_member_search(search_term, limit_value)

        start_time = time.time()
        try:
            members = self.execute_with_transaction(_search_operation)
            duration = time.time() - start_time

            record_operation(self.service_name, "search_members", duration, success=True)

            return self.create_result(
                success=True,
                message=f"Found {len(members)} members",
                data={
                    "members": members,
                    "search_term": search_term,
                    "limit": limit,
                    "count": len(members),
                    "search_time": duration,
                },
            )

        except Exception as e:
            duration = time.time() - start_time
            record_operation(self.service_name, "search_members", duration, success=False)
            return self.handle_error(
                e, "search_members", {"search_term": search_term, "limit": limit}, raise_error=False
            )

    def _perform_member_search(self, search_term: str, limit: int) -> List[Dict]:
        """Perform the actual member search query.

        Args:
            search_term: Search term
            limit: Result limit

        Returns:
            List of member records
        """
        if search_term:
            members = self.safe_query(
                "Member",
                filters=[["full_name", "like", f"%{search_term}%"]],
                fields=["name", "full_name", "email", "status"],
                limit=limit,
            )
        else:
            members = self.safe_query("Member", fields=["name", "full_name", "email", "status"], limit=limit)

        return members

    def bulk_update_member_status(self, member_updates: List[Dict]) -> Dict:
        """Bulk update member statuses with transaction management.

        Args:
            member_updates: List of {"member_name": str, "new_status": str}

        Returns:
            Bulk update results
        """
        max_batch_size = self.config.get("max_batch_size")
        if len(member_updates) > max_batch_size:
            return self.create_result(
                success=False,
                message=f"Batch size {len(member_updates)} exceeds maximum {max_batch_size}",
                errors=[f"Maximum batch size is {max_batch_size}"],
            )

        def _update_member_status(update_data):
            frappe.db.set_value("Member", update_data["member_name"], "status", update_data["new_status"])

        return self.bulk_operation(_update_member_status, member_updates)


# Factory functions for easy service creation
def create_calculation_service() -> ExampleCalculationService:
    """Create and configure calculation service.

    Returns:
        Configured ExampleCalculationService instance
    """
    service = ExampleCalculationService()
    service.validate_configuration()
    return service


def create_data_service() -> ExampleDataService:
    """Create and configure data service.

    Returns:
        Configured ExampleDataService instance
    """
    service = ExampleDataService()
    service.validate_configuration()
    return service


# Convenience API functions for external use
@public_api(operation_type=OperationType.UTILITY)
def calculate_fibonacci_api(n: int) -> Dict:
    """API endpoint for Fibonacci calculation.

    Args:
        n: Number to calculate

    Returns:
        API response with calculation result
    """
    service = create_calculation_service()
    return service.calculate_fibonacci(n)


@standard_api(operation_type=OperationType.MEMBER_DATA)
def search_members_api(search_term: str = "", limit: int = 10) -> Dict:
    """API endpoint for member search.

    Args:
        search_term: Search term
        limit: Result limit

    Returns:
        API response with search results
    """
    service = create_data_service()
    return service.search_members(search_term, limit)


@standard_api(operation_type=OperationType.UTILITY)
def get_service_metrics_api() -> Dict:
    """API endpoint to get service performance metrics.

    Returns:
        Service metrics and health information
    """
    from verenigingen.services.infrastructure.service_metrics import get_metrics_collector, get_system_health

    metrics_collector = get_metrics_collector()

    return {
        "success": True,
        "data": {
            "all_service_metrics": metrics_collector.get_all_metrics(),
            "aggregated_metrics": metrics_collector.get_aggregated_metrics(),
            "system_health": get_system_health(),
        },
    }
