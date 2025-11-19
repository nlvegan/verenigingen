"""
Mollie Transaction Manager

Provides transaction safety and atomic operations for Mollie integration.
"""

from functools import wraps
from typing import Any, Callable, Dict

import frappe
from frappe.utils import now_datetime


class MollieOperationManager:
    """Manages Mollie operations with proper error handling."""

    def __init__(self):
        self.operations = {}

    def register_operation(self, operation_name: str, operation_data: Dict[str, Any]):
        """Register an operation for tracking."""
        self.operations[operation_name] = {
            "data": operation_data,
            "timestamp": now_datetime(),
            "status": "started",
        }

    def complete_operation(self, operation_name: str, result: Any = None):
        """Mark operation as completed."""
        if operation_name in self.operations:
            self.operations[operation_name]["status"] = "completed"
            self.operations[operation_name]["result"] = result
            self.operations[operation_name]["completed_at"] = now_datetime()

    def fail_operation(self, operation_name: str, error: str):
        """Mark operation as failed."""
        if operation_name in self.operations:
            self.operations[operation_name]["status"] = "failed"
            self.operations[operation_name]["error"] = error
            self.operations[operation_name]["failed_at"] = now_datetime()


class MollieTransactionManager:
    """Manages transaction safety for Mollie operations."""

    def __init__(self):
        self.transaction_stack = []

    def begin_transaction(self, transaction_id: str):
        """Begin a new transaction."""
        frappe.db.begin()
        self.transaction_stack.append({"id": transaction_id, "started_at": now_datetime()})

    def commit_transaction(self, transaction_id: str):
        """Commit the current transaction."""
        if self.transaction_stack and self.transaction_stack[-1]["id"] == transaction_id:
            frappe.db.commit()
            self.transaction_stack.pop()
        else:
            frappe.log_error(
                f"Transaction ID mismatch: expected {transaction_id}", "Mollie Transaction Error"
            )

    def rollback_transaction(self, transaction_id: str):
        """Rollback the current transaction."""
        if self.transaction_stack and self.transaction_stack[-1]["id"] == transaction_id:
            frappe.db.rollback()
            self.transaction_stack.pop()
        else:
            frappe.log_error(
                f"Transaction ID mismatch: expected {transaction_id}", "Mollie Transaction Error"
            )


def atomic_mollie_operation(operation_name: str, max_retries: int = 1):
    """
    Decorator for atomic Mollie operations with retry capability.

    Args:
        operation_name: Name of the operation for tracking
        max_retries: Maximum number of retry attempts
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            operation_manager = MollieOperationManager()
            transaction_manager = MollieTransactionManager()

            for attempt in range(max_retries + 1):
                transaction_id = f"{operation_name}_{attempt}_{frappe.generate_hash()[:8]}"

                try:
                    # Begin transaction
                    transaction_manager.begin_transaction(transaction_id)

                    # Register operation
                    operation_manager.register_operation(
                        operation_name,
                        {"args": args, "kwargs": kwargs, "attempt": attempt + 1, "max_retries": max_retries},
                    )

                    # Execute function
                    result = func(*args, **kwargs)

                    # Commit transaction
                    transaction_manager.commit_transaction(transaction_id)
                    operation_manager.complete_operation(operation_name, result)

                    return result

                except Exception as e:
                    # Rollback transaction
                    transaction_manager.rollback_transaction(transaction_id)
                    operation_manager.fail_operation(operation_name, str(e))

                    # If this was the last attempt, re-raise the exception
                    if attempt == max_retries:
                        frappe.log_error(
                            f"Mollie operation '{operation_name}' failed after {max_retries + 1} attempts: {e}",
                            "Mollie Operation Failed",
                        )
                        raise

                    # Log retry attempt
                    frappe.logger().warning(
                        f"Mollie operation '{operation_name}' attempt {attempt + 1} failed: {e}. Retrying..."
                    )

        return wrapper

    return decorator
