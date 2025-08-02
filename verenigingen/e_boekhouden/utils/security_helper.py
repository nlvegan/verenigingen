"""
Security helper for E-Boekhouden migration operations.

This module provides secure alternatives to ignore_permissions=True patterns,
implementing proper role-based access control for migration operations.
"""

import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, List, Optional

import frappe

# Migration system user - should have appropriate roles assigned
MIGRATION_SYSTEM_USER = "Administrator"

# Required roles for different operations
MIGRATION_ROLES = {
    "account_creation": ["Accounts Manager", "System Manager"],
    "payment_processing": ["Accounts User", "Accounts Manager"],
    "party_creation": ["Sales User", "Purchase User", "Accounts Manager"],
    "journal_entries": ["Accounts User", "Accounts Manager"],
    "settings_update": ["System Manager"],
}


@contextmanager
def migration_context(operation_type: str = "general", user: Optional[str] = None):
    """
    Context manager for migration operations with proper permissions.

    Args:
        operation_type: Type of operation (account_creation, payment_processing, etc.)
        user: Optional user to run operation as (defaults to MIGRATION_SYSTEM_USER)

    Usage:
        with migration_context("account_creation"):
            account.insert()  # No need for ignore_permissions=True
    """
    current_user = frappe.session.user
    migration_user = user or MIGRATION_SYSTEM_USER

    try:
        # Check if current user has required roles
        if not has_migration_permission(operation_type):
            frappe.throw(
                f"User {current_user} does not have permission for {operation_type} operations. "
                f"Required roles: {', '.join(MIGRATION_ROLES.get(operation_type, []))}"
            )

        # Switch to migration user with proper roles
        frappe.set_user(migration_user)

        # Set migration flags for audit trail
        frappe.flags.in_migration = True
        frappe.flags.migration_operation = operation_type
        frappe.flags.migration_initiated_by = current_user

        yield

    finally:
        # Restore original user
        frappe.set_user(current_user)
        frappe.flags.in_migration = False
        frappe.flags.migration_operation = None
        frappe.flags.migration_initiated_by = None


def has_migration_permission(operation_type: str) -> bool:
    """
    Check if current user has permission for migration operation.

    Args:
        operation_type: Type of operation to check

    Returns:
        True if user has required roles
    """
    required_roles = MIGRATION_ROLES.get(operation_type, ["System Manager"])
    user_roles = frappe.get_roles(frappe.session.user)

    return any(role in user_roles for role in required_roles)


def migration_operation(operation_type: str = "general"):
    """
    Decorator for functions that require migration permissions.

    Args:
        operation_type: Type of operation

    Usage:
        @migration_operation("account_creation")
        def create_account(account_data):
            account = frappe.new_doc("Account")
            ...
            account.insert()  # Runs with proper permissions
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with migration_context(operation_type):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def validate_and_insert(doc, skip_validation: bool = False):
    """
    Insert document with proper permission context.

    Args:
        doc: Frappe document to insert
        skip_validation: If True, sets flags to skip certain validations
                        (use sparingly and only for known migration data issues)

    Returns:
        Inserted document
    """
    # Determine operation type based on doctype
    operation_map = {
        "Account": "account_creation",
        "Payment Entry": "payment_processing",
        "Customer": "party_creation",
        "Supplier": "party_creation",
        "Journal Entry": "journal_entries",
        "Sales Invoice": "payment_processing",
        "Purchase Invoice": "payment_processing",
    }

    operation_type = operation_map.get(doc.doctype, "general")

    with migration_context(operation_type):
        if skip_validation:
            # Only skip non-critical validations, never skip permissions
            frappe.flags.skip_non_critical_validations = True

        try:
            doc.insert()

            # Log for audit trail
            frappe.logger().info(
                f"Migration insert: {doc.doctype} {doc.name} "
                f"by {frappe.flags.migration_initiated_by} "
                f"(operation: {operation_type})"
            )

        finally:
            if skip_validation:
                frappe.flags.skip_non_critical_validations = False

    return doc


def validate_and_save(doc, skip_validation: bool = False):
    """
    Save document with proper permission context.

    Args:
        doc: Frappe document to save
        skip_validation: If True, sets flags to skip certain validations

    Returns:
        Saved document
    """
    operation_map = {
        "Account": "account_creation",
        "Payment Entry": "payment_processing",
        "Customer": "party_creation",
        "Supplier": "party_creation",
        "Journal Entry": "journal_entries",
    }

    operation_type = operation_map.get(doc.doctype, "general")

    with migration_context(operation_type):
        if skip_validation:
            frappe.flags.skip_non_critical_validations = True

        try:
            doc.save()

            # Log for audit trail
            frappe.logger().info(
                f"Migration save: {doc.doctype} {doc.name} " f"by {frappe.flags.migration_initiated_by}"
            )

        finally:
            if skip_validation:
                frappe.flags.skip_non_critical_validations = False

    return doc


def batch_insert(docs: List, operation_type: str = "general", batch_size: int = 100):
    """
    Insert multiple documents in batches with proper permissions.

    Args:
        docs: List of documents to insert
        operation_type: Type of operation
        batch_size: Number of documents per batch

    Returns:
        List of inserted documents
    """
    inserted = []

    with migration_context(operation_type):
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]

            for doc in batch:
                try:
                    doc.insert()
                    inserted.append(doc)
                except Exception as e:
                    frappe.log_error(
                        f"Batch insert failed for {doc.doctype}: {str(e)}", "Migration Batch Insert"
                    )

            # Commit after each batch
            frappe.db.commit()

            frappe.logger().info(f"Batch insert progress: {len(inserted)}/{len(docs)} documents")

    return inserted


def get_migration_user_roles() -> List[str]:
    """Get all roles assigned to the migration user."""
    return frappe.get_roles(MIGRATION_SYSTEM_USER)


@contextmanager
def cleanup_context():
    """
    Special context for cleanup operations that require delete permissions.

    Note: frappe.delete_doc() requires ignore_permissions=True for system cleanup.
    This context ensures proper audit trail while allowing necessary deletions.
    """
    current_user = frappe.session.user

    try:
        # Verify user has delete permissions
        if not any(
            frappe.has_permission(doctype, "delete")
            for doctype in [
                "Account",
                "Customer",
                "Supplier",
                "Sales Invoice",
                "Purchase Invoice",
                "Payment Entry",
                "Journal Entry",
            ]
        ):
            frappe.throw("User does not have delete permissions for cleanup operations")

        # Set cleanup flags
        frappe.flags.in_cleanup = True
        frappe.flags.cleanup_initiated_by = current_user

        yield

    finally:
        frappe.flags.in_cleanup = False
        frappe.flags.cleanup_initiated_by = None


@contextmanager
def migration_transaction(
    operation_type: str = "general", batch_size: int = 100, auto_commit_interval: int = 50
):
    """
    Context manager for migration operations with proper transaction management.

    This provides:
    - Automatic transaction rollback on errors
    - Batch commits for large operations
    - Progress tracking and logging
    - Proper error handling and recovery

    Args:
        operation_type: Type of operation for permission checking
        batch_size: Number of operations before auto-commit
        auto_commit_interval: Commit every N seconds regardless of batch size

    Usage:
        with migration_transaction("account_creation") as tx:
            for account_data in large_account_list:
                account = create_account(account_data)
                tx.track_operation("account_created", account.name)
    """
    current_user = frappe.session.user
    start_time = time.time()
    last_commit_time = start_time

    # Transaction state
    transaction_state = {
        "operations_count": 0,
        "last_commit_count": 0,
        "errors": [],
        "rollback_savepoint": None,
        "committed_operations": [],
        "pending_operations": [],
    }

    try:
        # Check permissions
        if not has_migration_permission(operation_type):
            frappe.throw(f"User {current_user} does not have permission for {operation_type} operations")

        # Switch to migration user context
        frappe.set_user(MIGRATION_SYSTEM_USER)

        # Set transaction flags
        frappe.flags.in_migration_transaction = True
        frappe.flags.migration_transaction_type = operation_type
        frappe.flags.migration_initiated_by = current_user

        # Start savepoint for rollback capability
        try:
            frappe.db.sql("SAVEPOINT migration_start")
            transaction_state["rollback_savepoint"] = "migration_start"
        except Exception as e:
            # Fallback if savepoints not supported
            frappe.logger().warning(f"Database savepoints not supported ({str(e)}), using simple transaction")
            transaction_state["rollback_savepoint"] = None

        # Create transaction manager object
        class TransactionManager:
            def __init__(self, state):
                self.state = state

            def track_operation(self, operation_type: str, doc_name: str, details: dict = None):
                """Track an operation for commit/rollback purposes."""
                self.state["operations_count"] += 1
                self.state["pending_operations"].append(
                    {
                        "type": operation_type,
                        "doc_name": doc_name,
                        "details": details,
                        "timestamp": time.time(),
                    }
                )

                # Auto-commit logic
                current_time = time.time()
                operations_since_commit = self.state["operations_count"] - self.state["last_commit_count"]
                time_since_commit = current_time - last_commit_time

                if operations_since_commit >= batch_size or time_since_commit >= auto_commit_interval:
                    self.commit_batch()

            def commit_batch(self):
                """Commit current batch of operations."""
                try:
                    frappe.db.commit()

                    # Move pending to committed
                    self.state["committed_operations"].extend(self.state["pending_operations"])
                    self.state["pending_operations"] = []
                    self.state["last_commit_count"] = self.state["operations_count"]

                    frappe.logger().info(
                        f"Migration batch commit: {self.state['operations_count']} operations "
                        f"({operation_type})"
                    )

                    # Update savepoint
                    if self.state["rollback_savepoint"]:
                        frappe.db.sql("RELEASE SAVEPOINT migration_start")
                        frappe.db.sql("SAVEPOINT migration_start")

                except Exception as e:
                    frappe.logger().error(f"Batch commit failed: {str(e)}")
                    self.state["errors"].append(f"Batch commit failed: {str(e)}")
                    raise

            def get_stats(self):
                """Get transaction statistics."""
                return {
                    "total_operations": self.state["operations_count"],
                    "committed_operations": len(self.state["committed_operations"]),
                    "pending_operations": len(self.state["pending_operations"]),
                    "errors": len(self.state["errors"]),
                    "duration": time.time() - start_time,
                }

        tx_manager = TransactionManager(transaction_state)
        yield tx_manager

        # Final commit of any remaining operations
        if transaction_state["pending_operations"]:
            tx_manager.commit_batch()

        # Log completion
        stats = tx_manager.get_stats()
        frappe.logger().info(
            f"Migration transaction completed: {stats['total_operations']} operations "
            f"in {stats['duration']:.2f}s ({operation_type})"
        )

    except Exception as e:
        # Rollback on error
        error_msg = f"Migration transaction failed: {str(e)}"
        frappe.logger().error(error_msg)

        try:
            if transaction_state["rollback_savepoint"]:
                frappe.db.sql("ROLLBACK TO SAVEPOINT migration_start")
                frappe.logger().info("Successfully rolled back to savepoint")
            else:
                frappe.db.rollback()
                frappe.logger().info("Successfully rolled back transaction")

            # Log rollback details
            stats = {
                "operations_attempted": transaction_state["operations_count"],
                "operations_rolled_back": len(transaction_state["pending_operations"]),
                "operations_preserved": len(transaction_state["committed_operations"]),
            }
            frappe.logger().info(f"Rollback stats: {stats}")

        except Exception as rollback_error:
            frappe.logger().error(f"Rollback failed: {str(rollback_error)}")

        # Re-raise original error
        raise

    finally:
        # Cleanup
        try:
            if transaction_state["rollback_savepoint"]:
                frappe.db.sql("RELEASE SAVEPOINT migration_start")
        except Exception:
            pass

        # Restore original user
        frappe.set_user(current_user)

        # Clear transaction flags
        frappe.flags.in_migration_transaction = False
        frappe.flags.migration_transaction_type = None
        frappe.flags.migration_initiated_by = None


@contextmanager
def atomic_migration_operation(operation_type: str = "general"):
    """
    Atomic context for single migration operations that must complete entirely or not at all.

    This is different from migration_transaction in that it's designed for single operations
    that should either succeed completely or be rolled back entirely.

    Usage:
        with atomic_migration_operation("payment_processing"):
            pe = create_payment_entry(mutation_data)
            allocate_to_invoices(pe, invoices)
            # If any step fails, everything is rolled back
    """
    current_user = frappe.session.user

    try:
        # Check permissions
        if not has_migration_permission(operation_type):
            frappe.throw(f"User {current_user} does not have permission for {operation_type} operations")

        # Switch to migration user
        frappe.set_user(MIGRATION_SYSTEM_USER)

        # Set atomic operation flags
        frappe.flags.in_atomic_migration = True
        frappe.flags.atomic_operation_type = operation_type
        frappe.flags.atomic_initiated_by = current_user

        # Start transaction with fallback
        savepoint_created = False
        try:
            frappe.db.sql("SAVEPOINT atomic_migration")
            savepoint_created = True
        except Exception as e:
            frappe.logger().warning(f"Savepoint not supported ({str(e)}), using simple transaction")
            # Continue without savepoint - frappe.db.commit/rollback will handle it

        yield

        # Commit if successful (commit automatically releases savepoints)
        frappe.db.commit()

        frappe.logger().info(f"Atomic migration operation completed: {operation_type}")

    except Exception as e:
        # Rollback on any error
        frappe.logger().error(f"Atomic migration operation failed ({operation_type}): {str(e)}")

        if savepoint_created:
            try:
                frappe.db.sql("ROLLBACK TO SAVEPOINT atomic_migration")
                frappe.db.sql("RELEASE SAVEPOINT atomic_migration")
                frappe.logger().info(f"Successfully rolled back atomic operation: {operation_type}")
            except Exception as rollback_error:
                frappe.logger().error(f"Rollback failed for atomic operation: {str(rollback_error)}")
                frappe.db.rollback()  # Full rollback as fallback
        else:
            # No savepoint, use full rollback
            frappe.db.rollback()
            frappe.logger().info(f"Rolled back atomic operation (no savepoint): {operation_type}")

        raise

    finally:
        # Restore original user
        frappe.set_user(current_user)

        # Clear atomic flags
        frappe.flags.in_atomic_migration = False
        frappe.flags.atomic_operation_type = None
        frappe.flags.atomic_initiated_by = None


def ensure_migration_user_setup():
    """
    Ensure migration user has required roles.
    Run this during setup/installation.
    """
    required_roles = set()
    for roles in MIGRATION_ROLES.values():
        required_roles.update(roles)

    current_roles = set(get_migration_user_roles())
    missing_roles = required_roles - current_roles

    if missing_roles:
        frappe.logger().warning(
            f"Migration user {MIGRATION_SYSTEM_USER} missing roles: {missing_roles}. "
            "Please assign these roles for migration to work properly."
        )

        # Could automatically assign roles here if needed
        # for role in missing_roles:
        #     frappe.get_doc({
        #         "doctype": "Has Role",
        #         "parent": MIGRATION_SYSTEM_USER,
        #         "parenttype": "User",
        #         "role": role
        #     }).insert(ignore_permissions=True)  # This one case where it's needed!

    return missing_roles


# Audit logging functions
def log_migration_activity(operation: str, doctype: str, docname: str, details: dict = None):
    """
    Log migration activity for audit trail.

    Args:
        operation: Operation performed (insert, update, delete)
        doctype: Document type
        docname: Document name
        details: Additional details
    """
    try:
        log_entry = {
            "doctype": "Activity Log",
            "subject": f"Migration: {operation} {doctype} {docname}",
            "operation": operation,
            "reference_doctype": doctype,
            "reference_name": docname,
            "user": frappe.session.user,
            "migration_user": frappe.flags.migration_initiated_by,
            "migration_operation": frappe.flags.migration_operation,
            "full_name": frappe.get_cached_value("User", frappe.session.user, "full_name"),
            "details": frappe.as_json(details) if details else None,
        }

        # Create log entry if Activity Log doctype exists
        if frappe.db.exists("DocType", "Activity Log"):
            frappe.get_doc(log_entry).insert(ignore_permissions=True)  # Logging needs this

    except Exception:
        # Don't fail migration if logging fails
        pass
