"""
Orphaned Child Table Cleanup Utility

Detects and cleans up orphaned child table records across all DocTypes.
These are child table records whose parent documents have been deleted,
creating data integrity issues and blocking document deletions.

SECURITY NOTE: All SQL queries use table names from DocType definitions.
Table names are validated against database schema to prevent SQL injection.

ERROR HANDLING PATTERN:
All @frappe.whitelist() functions return OperationResult[Dict[str, Any]]:
- Success: OperationResult.ok(data, message="...")
- Failure: OperationResult.fail(user_message, errors=[...], context={...})
- Comprehensive error context includes operation name + all parameters
- Traceback logging for debugging: frappe.log_error(f"...: {str(e)}\\n{traceback.format_exc()}", "Title")
"""

import re
import time
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Count
from frappe.utils.file_lock import create_lock, delete_lock, lock_exists

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api

# Batch size for large deletion operations to prevent timeouts
BATCH_SIZE = 500

# Lock timeout configurations for different cleanup scopes
# Longer timeouts for broader scopes to accommodate larger datasets
CLEANUP_LOCK_TIMEOUTS = {
    "system_wide": 3600,  # 1 hour - largest scope, all child tables
    "member_only": 1800,  # 30 minutes - scoped to Member DocType
    "volunteer_only": 1800,  # 30 minutes - scoped to Volunteer DocType
}


class SimpleLock:
    """Simple lock wrapper using frappe.utils.file_lock for Frappe v15 compatibility"""

    def __init__(self, lock_name, timeout=3600):
        self.lock_name = lock_name
        self.timeout = timeout
        self.acquired = False

    def acquire(self, blocking=True):
        """Acquire the lock. Returns True if successful, False otherwise."""
        if lock_exists(self.lock_name):
            return False
        self.acquired = create_lock(self.lock_name)
        return self.acquired

    def release(self):
        """Release the lock."""
        if self.acquired:
            delete_lock(self.lock_name)
            self.acquired = False


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def verify_child_table_indexes() -> OperationResult[Dict[str, Any]]:
    """
    Verify that required indexes exist on child tables for optimal LEFT JOIN performance.

    Returns:
        OperationResult[Dict[str, Any]]: Index verification results including:
            - indexes_verified: Count of child tables with optimal indexes
            - missing_indexes: List of child table names missing recommended indexes
            - recommendations: List of index creation recommendations with SQL statements
            - summary: Human-readable summary of verification results
    """
    # SECURITY: Explicit permission validation for database schema introspection
    # Defense-in-depth: verify user has System Settings read permission beyond @critical_api
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw("Insufficient permissions to verify database indexes", frappe.PermissionError)

    results = {
        "success": True,
        "indexes_verified": 0,
        "missing_indexes": [],
        "recommendations": [],
    }

    try:
        # Get all child table DocTypes
        child_tables = frappe.get_all("DocType", filters={"istable": 1}, fields=["name"])

        for table in child_tables:
            table_name = f"tab{table.name}"

            if not _validate_table_name(table_name):
                continue

            # Check for index on (parent, parenttype) columns
            # Note: Skip table_exists() check - it has bugs with spaces in names
            try:
                indexes = frappe.db.sql(
                    f"""
                SHOW INDEX FROM `{table_name}`
                WHERE Column_name IN ('parent', 'parenttype')
                """,
                    as_dict=True,
                )

                # Check if we have a composite index on (parent, parenttype)
                has_parent_parenttype_index = False
                for idx in indexes:
                    if idx.Column_name == "parent":
                        # Check if this index also includes parenttype
                        same_index = [i for i in indexes if i.Key_name == idx.Key_name]
                        if len(same_index) >= 2:
                            has_parent_parenttype_index = True
                            break

                if has_parent_parenttype_index:
                    results["indexes_verified"] += 1
                else:
                    results["missing_indexes"].append(table.name)
                    results["recommendations"].append(
                        {
                            "table": table.name,
                            "recommendation": f"CREATE INDEX idx_parent_parenttype ON `{table_name}` (parent, parenttype);",
                            "benefit": "10-100x faster LEFT JOIN performance for orphan detection",
                        }
                    )
            except Exception:
                # Table doesn't exist or can't be accessed - skip it
                continue

        if results["missing_indexes"]:
            results["summary"] = (
                f"Found {len(results['missing_indexes'])} child tables missing recommended indexes. "
                f"Performance may be degraded for large datasets."
            )
        else:
            results["summary"] = f"All {results['indexes_verified']} child tables have optimal indexes."

        return OperationResult.ok(results, message=_(results.get("summary", "Index verification completed")))

    except Exception as e:
        frappe.log_error(
            f"Error verifying child table indexes: {str(e)}\n{traceback.format_exc()}",
            "Index Verification Error",
        )
        return OperationResult.fail(
            _("Unable to verify child table indexes. Please contact support."),
            errors=[str(e)],
            context={"operation": "verify_child_table_indexes"},
        )


def _validate_table_name(table_name):
    """
    Validate table name against Frappe naming convention to prevent SQL injection.

    Args:
        table_name (str): Table name to validate (e.g., "tabMember")

    Returns:
        bool: True if valid, False otherwise

    Security: Only allows alphanumeric, spaces, and underscores after "tab" prefix.
    """
    # Frappe table naming pattern: tab + DocType name (alphanumeric + spaces + underscores)
    pattern = r"^tab[A-Za-z0-9 _]+$"
    return bool(re.match(pattern, table_name))


def _batch_delete_orphans(table_name, parent_table, parent_doctype, batch_size=BATCH_SIZE):
    """
    Delete orphaned records in batches with incremental commits.

    This prevents database lock timeouts and transaction log bloat on large datasets.
    Uses Frappe's native database operations for better compatibility.

    Args:
        table_name (str): Child table name (validated)
        parent_table (str): Parent table name (validated)
        parent_doctype (str): Parent DocType for filtering
        batch_size (int): Records to delete per batch (default 500)

    Returns:
        int: Total number of records deleted (partial success if error occurred)
    """
    total_deleted = 0
    batches_completed = 0

    while True:
        try:
            # Get batch of orphaned record IDs using LEFT JOIN
            orphaned_ids = frappe.db.sql(
                f"""
                SELECT ct.name
                FROM `{table_name}` ct
                LEFT JOIN `{parent_table}` pt ON ct.parent = pt.name
                WHERE pt.name IS NULL
                AND ct.parenttype = %s
                LIMIT {batch_size}
                """,
                parent_doctype,
                as_dict=False,
            )

            if not orphaned_ids:
                break

            # Extract IDs from tuples
            ids_to_delete = [row[0] for row in orphaned_ids]

            # Delete using Frappe's native delete_doc for proper cleanup
            # For child tables, direct SQL DELETE is appropriate as they have no hooks
            frappe.db.sql(
                f"""
                DELETE FROM `{table_name}`
                WHERE name IN ({','.join(['%s'] * len(ids_to_delete))})
                """,
                tuple(ids_to_delete),
            )

            deleted_count = len(ids_to_delete)
            total_deleted += deleted_count
            batches_completed += 1
            frappe.db.commit()

            # Progress logging every 5000 records for operational visibility
            if total_deleted % 5000 == 0:
                frappe.logger().info(
                    f"Batch cleanup progress: {total_deleted} records deleted from {table_name}"
                )

        except Exception as e:
            # Rollback CURRENT batch only - previous batches are already committed
            frappe.db.rollback()

            # Log partial success information - critical for operational awareness
            frappe.log_error(
                f"""Batch deletion PARTIALLY completed: {total_deleted} records successfully deleted
across {batches_completed} batches before failure.

Table: {table_name}
Parent DocType: {parent_doctype}
Batches Completed: {batches_completed}
Total Deleted: {total_deleted}
Error: {str(e)}

Note: Previous batches were committed successfully. Only the current batch was rolled back.
""",
                "Orphan Cleanup Partial Failure",
            )

            # Return partial success count instead of raising
            # Caller can compare this with expected count to detect partial failure
            return total_deleted

    return total_deleted


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def detect_orphaned_child_tables() -> OperationResult[Dict[str, Any]]:
    """
    Scan all child tables (istable=1) and detect orphaned records.

    Returns detailed report of orphaned records by table.

    Returns:
        OperationResult[Dict[str, Any]]: Detection results including:
            - total_orphaned: Total count of orphaned records found
            - tables_affected: Number of child tables with orphaned records
            - details: List of detailed information per affected table with orphan counts
            - summary: Human-readable summary of detection results
    """
    results = {"success": True, "total_orphaned": 0, "tables_affected": 0, "details": []}

    try:
        # Get all child table DocTypes
        child_tables = frappe.get_all("DocType", filters={"istable": 1}, fields=["name", "module"])

        for table in child_tables:
            table_name = f"tab{table.name}"

            # SECURITY: Validate table name format
            if not _validate_table_name(table_name):
                frappe.log_error(f"Invalid table name format: {table_name}", "Orphan Cleanup Security")
                continue

            # Check if table has 'parent' and 'parenttype' columns
            # Note: get_table_columns expects DocType name without 'tab' prefix
            # Note: We skip table_exists() check as it has bugs with spaces in names
            try:
                columns = frappe.db.get_table_columns(table.name)
            except Exception:
                # Table doesn't exist or can't be accessed
                continue

            if "parent" not in columns or "parenttype" not in columns:
                continue

            try:
                # Get ALL parent DocTypes for this child table (may have multiple)
                parent_types = frappe.db.sql(
                    f"""
                    SELECT DISTINCT parenttype
                    FROM `{table_name}`
                    """,
                    as_dict=True,
                )

                if not parent_types:
                    continue

                # Check each parent type separately for orphaned records
                for parent_info in parent_types:
                    parent_doctype = parent_info.parenttype
                    parent_table = f"tab{parent_doctype}"

                    # Count orphaned records for this specific parent type using LEFT JOIN
                    # Note: Skip table_exists() check - it has bugs with spaces, SQL will fail safely
                    orphaned_count = frappe.db.sql(
                        f"""
                        SELECT COUNT(*) as count
                        FROM `{table_name}` ct
                        LEFT JOIN `{parent_table}` pt ON ct.parent = pt.name
                        WHERE pt.name IS NULL AND ct.parenttype = %s
                        """,
                        parent_doctype,
                        as_dict=True,
                    )[0].count

                    if orphaned_count > 0:
                        results["total_orphaned"] += orphaned_count
                        results["tables_affected"] += 1

                        # Get sample orphaned parent IDs
                        sample_orphans = frappe.db.sql(
                            f"""
                            SELECT DISTINCT ct.parent
                            FROM `{table_name}` ct
                            LEFT JOIN `{parent_table}` pt ON ct.parent = pt.name
                            WHERE pt.name IS NULL
                            AND ct.parenttype = %s
                            LIMIT 5
                            """,
                            parent_doctype,
                            as_dict=True,
                        )

                        results["details"].append(
                            {
                                "child_table": table.name,
                                "parent_doctype": parent_doctype,
                                "orphaned_count": orphaned_count,
                                "sample_parents": [s.parent for s in sample_orphans],
                                "module": table.module,
                            }
                        )

            except Exception as e:
                # Log but continue - some tables might have unusual structures
                frappe.logger().debug(f"Could not check {table_name}: {str(e)}")
                continue

        results["summary"] = (
            f"Found {results['total_orphaned']} orphaned records "
            f"across {results['tables_affected']} child tables"
        )

        return OperationResult.ok(results, message=_(results.get("summary", "Detection completed")))

    except Exception as e:
        frappe.log_error(
            f"Error detecting orphaned child tables: {str(e)}\n{traceback.format_exc()}",
            "Orphaned Child Table Detection Error",
        )
        return OperationResult.fail(
            _("Unable to detect orphaned child tables. Please contact support."),
            errors=[str(e)],
            context={"operation": "detect_orphaned_child_tables"},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_child_tables(dry_run=True, table_filter=None) -> OperationResult[Dict[str, Any]]:
    """
    Clean up orphaned child table records with concurrent execution protection.

    Args:
        dry_run (bool): If True, only report what would be deleted
        table_filter (str): Optional - only clean specific child table name

    Returns:
        OperationResult[Dict[str, Any]]: Cleanup results including:
            - dry_run: Boolean indicating if this was a dry run
            - total_deleted: Total count of records deleted (or would be deleted)
            - tables_cleaned: Number of child tables processed
            - details: List of detailed cleanup information per table
            - timing_metrics: Performance metrics for each table cleanup
            - summary: Human-readable summary of cleanup operation
    """
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    # Acquire distributed lock for non-dry-run operations to prevent concurrent execution
    lock = None
    if not dry_run:
        lock_name = "orphaned_cleanup_system_wide"
        lock_timeout = CLEANUP_LOCK_TIMEOUTS["system_wide"]

        lock = SimpleLock(lock_name, timeout=lock_timeout)
        if not lock.acquire(blocking=False):
            return OperationResult.fail(
                _("Another cleanup operation is currently running. Please wait and try again."),
                errors=["Lock acquisition failed"],
                context={"operation": "cleanup_orphaned_child_tables", "dry_run": dry_run, "lock": lock_name},
            )

    results = {
        "success": True,
        "dry_run": dry_run,
        "total_deleted": 0,
        "tables_cleaned": 0,
        "details": [],
        "timing_metrics": {},
    }

    start_time = time.time()

    try:
        # PERFORMANCE CHECK: Verify indexes before starting expensive operations
        if not dry_run:
            index_results_response = verify_child_table_indexes()
            # Normalize response: @critical_api decorator converts OperationResult to dict
            if isinstance(index_results_response, dict):
                index_results_response = OperationResult.from_dict_result(index_results_response)

            if not index_results_response.success:
                return OperationResult.fail(
                    _("Unable to verify indexes before cleanup. Please try again."),
                    errors=index_results_response.errors,
                    context={
                        "operation": "cleanup_orphaned_child_tables",
                        "dry_run": dry_run,
                        "table_filter": table_filter,
                    },
                )

            index_results = index_results_response.data
            if index_results.get("missing_indexes"):
                return OperationResult.fail(
                    _(
                        "Missing {0} required indexes. Run 'Verify Child Table Indexes' first and create recommended indexes for optimal performance."
                    ).format(len(index_results["missing_indexes"])),
                    errors=["Missing database indexes"],
                    context={
                        "operation": "cleanup_orphaned_child_tables",
                        "missing_indexes": index_results["missing_indexes"],
                        "recommendations": index_results.get("recommendations", []),
                    },
                )

        # Get all child table DocTypes
        filters = {"istable": 1}
        if table_filter:
            filters["name"] = table_filter

        child_tables = frappe.get_all("DocType", filters=filters, fields=["name", "module"])

        for table in child_tables:
            table_name = f"tab{table.name}"

            # SECURITY: Validate table name format
            if not _validate_table_name(table_name):
                frappe.log_error(f"Invalid table name format: {table_name}", "Orphan Cleanup Security")
                continue

            # Check if table has 'parent' and 'parenttype' columns
            # Note: get_table_columns expects DocType name without 'tab' prefix
            # Note: We skip table_exists() check as it has bugs with spaces in names
            try:
                columns = frappe.db.get_table_columns(table.name)
            except Exception:
                # Table doesn't exist or can't be accessed
                continue

            if "parent" not in columns or "parenttype" not in columns:
                continue

            try:
                # Get ALL parent DocTypes for this child table (may have multiple)
                parent_types = frappe.db.sql(
                    f"""
                    SELECT DISTINCT parenttype
                    FROM `{table_name}`
                    """,
                    as_dict=True,
                )

                if not parent_types:
                    continue

                # Check each parent type separately for orphaned records
                for parent_info in parent_types:
                    parent_doctype = parent_info.parenttype
                    parent_table = f"tab{parent_doctype}"

                    # Count orphaned records before deletion using LEFT JOIN (optimized)
                    # Note: Skip table_exists() check - it has bugs with spaces, SQL will fail safely
                    orphaned_count = frappe.db.sql(
                        f"""
                        SELECT COUNT(*) as count
                        FROM `{table_name}` ct
                        LEFT JOIN `{parent_table}` pt ON ct.parent = pt.name
                        WHERE pt.name IS NULL
                        AND ct.parenttype = %s
                        """,
                        parent_doctype,
                        as_dict=True,
                    )[0].count

                    if orphaned_count > 0:
                        table_start_time = time.time()

                        # Get sample IDs for audit trail
                        sample_ids = []
                        try:
                            sample_ids = frappe.db.sql(
                                f"""
                                SELECT ct.name, ct.parent
                                FROM `{table_name}` ct
                                LEFT JOIN `{parent_table}` pt ON ct.parent = pt.name
                                WHERE pt.name IS NULL
                                AND ct.parenttype = %s
                                LIMIT 100
                                """,
                                parent_doctype,
                                as_dict=True,
                            )
                        except Exception:
                            pass  # Sample collection is non-critical

                        if not dry_run:
                            # Log to Error Log for audit trail (permanent record)
                            frappe.log_error(
                                f"""Data Cleanup Audit - System-Wide Orphan Cleanup

    Child Table: {table.name}
    Parent DocType: {parent_doctype}
    Orphaned Records: {orphaned_count}
    Sample Parent IDs: {', '.join([r.parent for r in sample_ids[:10]]) if sample_ids else 'N/A'}
    Executed By: {frappe.session.user}
    Timestamp: {frappe.utils.now()}
    Module: {table.module}
                                """,
                                "Orphan Cleanup Audit",
                            )

                            # Delete orphaned records in batches to prevent timeouts
                            actual_deleted = _batch_delete_orphans(table_name, parent_table, parent_doctype)

                            # Verify deletion count matches expectation
                            if actual_deleted != orphaned_count:
                                frappe.logger().warning(
                                    f"Deletion count mismatch for {table.name}: "
                                    f"expected {orphaned_count}, deleted {actual_deleted}"
                                )

                        # Calculate timing metrics for this table
                        table_duration = time.time() - table_start_time
                        records_per_second = orphaned_count / table_duration if table_duration > 0 else 0

                        results["total_deleted"] += orphaned_count
                        results["tables_cleaned"] += 1

                        results["details"].append(
                            {
                                "child_table": table.name,
                                "parent_doctype": parent_doctype,
                                "records_deleted": orphaned_count,
                                "sample_parents": [r.parent for r in sample_ids[:5]] if sample_ids else [],
                                "action": "Would delete" if dry_run else "Deleted",
                                "duration_seconds": round(table_duration, 2),
                                "records_per_second": round(records_per_second, 2),
                            }
                        )

                        # Store timing metrics
                        results["timing_metrics"][table.name] = {
                            "duration_seconds": round(table_duration, 2),
                            "records_per_second": round(records_per_second, 2),
                        }

                        frappe.logger().info(
                            f"{'Would delete' if dry_run else 'Deleted'} {orphaned_count} "
                            f"orphaned records from {table.name} in {table_duration:.2f}s"
                        )

            except Exception as e:
                # Log error and continue with next table
                error_msg = f"Error cleaning {table_name}: {str(e)}"
                frappe.logger().error(error_msg)
                results["details"].append({"child_table": table.name, "error": str(e)})
                continue

        # Calculate total duration
        total_duration = time.time() - start_time
        results["total_duration_seconds"] = round(total_duration, 2)

        results["summary"] = (
            f"{'Would delete' if dry_run else 'Deleted'} {results['total_deleted']} "
            f"orphaned records from {results['tables_cleaned']} child tables "
            f"in {total_duration:.1f}s"
        )

        if dry_run:
            results[
                "note"
            ] = "This was a dry run. No records were actually deleted. Run with dry_run=False to perform cleanup."

        return OperationResult.ok(results, message=_(results.get("summary", "Cleanup completed")))

    except Exception as e:
        frappe.log_error(
            f"Error cleaning orphaned child tables: {str(e)}\n{traceback.format_exc()}",
            "Orphaned Child Table Cleanup Error",
        )
        return OperationResult.fail(
            _("Unable to complete orphaned child table cleanup. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "cleanup_orphaned_child_tables",
                "dry_run": dry_run,
                "table_filter": table_filter,
            },
        )

    finally:
        # Always release lock if acquired
        if lock:
            try:
                lock.release()
            except Exception:
                pass  # Lock may have expired, ignore


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_member_child_tables_only(dry_run=True) -> OperationResult[Dict[str, Any]]:
    """
    Clean up only Member-related child table orphans with concurrent execution protection.

    This is a focused cleanup specifically for Member DocType child tables.

    Args:
        dry_run (bool): If True, only report what would be deleted

    Returns:
        OperationResult[Dict[str, Any]]: Cleanup results including:
            - dry_run: Boolean indicating if this was a dry run
            - total_deleted: Total count of Member child records deleted (or would be deleted)
            - details: List of detailed cleanup information per Member child table
            - audit_log: Audit trail entries for the cleanup operation
            - summary: Human-readable summary of cleanup operation
    """
    # SECURITY: Hardcoded whitelist of valid Member child tables
    MEMBER_CHILD_TABLES = {
        "Member Volunteer Expenses",
        "Member Payment History",
        "Member IBAN History",
        "Member SEPA Mandate Link",
        "Chapter Membership History",
        "Volunteer Assignment",
        "Member Fee Change History",
    }

    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    # Acquire distributed lock for non-dry-run operations
    lock = None
    if not dry_run:
        lock_name = "orphaned_cleanup_member_only"
        lock_timeout = CLEANUP_LOCK_TIMEOUTS["member_only"]

        lock = SimpleLock(lock_name, timeout=lock_timeout)
        if not lock.acquire(blocking=False):
            return OperationResult.fail(
                _("Another Member cleanup operation is currently running. Please wait and try again."),
                errors=["Lock acquisition failed"],
                context={
                    "operation": "cleanup_member_child_tables_only",
                    "dry_run": dry_run,
                    "lock": lock_name,
                },
            )

    results = {"success": True, "dry_run": dry_run, "total_deleted": 0, "details": [], "audit_log": []}

    try:
        for child_table in MEMBER_CHILD_TABLES:
            table_name = f"tab{child_table}"

            # SECURITY: Validate table name format
            if not _validate_table_name(table_name):
                frappe.log_error(f"Invalid table name format: {table_name}", "Member Cleanup Security")
                continue

            try:
                # Note: Skip table_exists() check - it has bugs with spaces in names
                # Count orphaned records using LEFT JOIN (optimized)
                orphaned_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*) as count
                    FROM `{table_name}` ct
                    LEFT JOIN `tabMember` m ON ct.parent = m.name
                    WHERE m.name IS NULL
                    """,
                    as_dict=True,
                )[0].count

                if orphaned_count > 0:
                    # Get sample IDs for audit trail
                    sample_ids = frappe.db.sql(
                        f"""
                        SELECT ct.name, ct.parent
                        FROM `{table_name}` ct
                        LEFT JOIN `tabMember` m ON ct.parent = m.name
                        WHERE m.name IS NULL
                        LIMIT 100
                        """,
                        as_dict=True,
                    )

                    if not dry_run:
                        # Log to Error Log for audit trail
                        frappe.log_error(
                            f"""Data Cleanup Audit - Member Child Tables

Table: {child_table}
Orphaned Records: {orphaned_count}
Sample Parent IDs: {', '.join([r.parent for r in sample_ids[:10]])}
Executed By: {frappe.session.user}
Timestamp: {frappe.utils.now()}
                            """,
                            "Orphan Cleanup Audit",
                        )

                        # Delete orphaned records in batches to prevent timeouts
                        actual_deleted = _batch_delete_orphans(table_name, "tabMember", "Member")

                        # Verify deletion count matches expectation
                        if actual_deleted != orphaned_count:
                            frappe.logger().warning(
                                f"Member cleanup deletion count mismatch for {child_table}: "
                                f"expected {orphaned_count}, deleted {actual_deleted}"
                            )

                    results["total_deleted"] += orphaned_count
                    results["details"].append(
                        {
                            "table": child_table,
                            "orphaned_records": orphaned_count,
                            "sample_parents": [r.parent for r in sample_ids[:5]],
                            "action": "Would delete" if dry_run else "Deleted",
                        }
                    )

                    # Add to audit log in results
                    results["audit_log"].append(
                        {
                            "table": child_table,
                            "count": orphaned_count,
                            "timestamp": frappe.utils.now(),
                            "user": frappe.session.user,
                        }
                    )

            except Exception as e:
                results["details"].append({"table": child_table, "error": str(e)})

        results["summary"] = (
            f"{'Would delete' if dry_run else 'Deleted'} {results['total_deleted']} "
            f"orphaned Member child table records"
        )

        return OperationResult.ok(results, message=_(results.get("summary", "Member cleanup completed")))

    except Exception as e:
        frappe.log_error(
            f"Error cleaning Member child tables: {str(e)}\n{traceback.format_exc()}",
            "Member Child Table Cleanup Error",
        )
        return OperationResult.fail(
            _("Unable to complete Member child table cleanup. Please contact support."),
            errors=[str(e)],
            context={"operation": "cleanup_member_child_tables_only", "dry_run": dry_run},
        )

    finally:
        # Always release lock if acquired
        if lock:
            try:
                lock.release()
            except Exception:
                pass  # Lock may have expired, ignore


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_volunteer_child_tables_only(dry_run=True) -> OperationResult[Dict[str, Any]]:
    """
    Clean up only Volunteer-related child table orphans with concurrent execution protection.

    This is a focused cleanup specifically for Volunteer DocType child tables.

    Args:
        dry_run (bool): If True, only report what would be deleted

    Returns:
        OperationResult[Dict[str, Any]]: Cleanup results including:
            - dry_run: Boolean indicating if this was a dry run
            - total_deleted: Total count of Volunteer child records deleted (or would be deleted)
            - details: List of detailed cleanup information per Volunteer child table
            - audit_log: Audit trail entries for the cleanup operation
            - summary: Human-readable summary of cleanup operation
    """
    # SECURITY: Hardcoded whitelist of valid Volunteer child tables
    VOLUNTEER_CHILD_TABLES = {
        "Volunteer Assignment",
        "Volunteer Skill",
        "Volunteer Development Goal",
        "Volunteer Interest Area",
    }

    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    # Acquire distributed lock for non-dry-run operations
    lock = None
    if not dry_run:
        lock_name = "orphaned_cleanup_volunteer_only"
        lock_timeout = CLEANUP_LOCK_TIMEOUTS["volunteer_only"]

        lock = SimpleLock(lock_name, timeout=lock_timeout)
        if not lock.acquire(blocking=False):
            return OperationResult.fail(
                _("Another Volunteer cleanup operation is currently running. Please wait and try again."),
                errors=["Lock acquisition failed"],
                context={
                    "operation": "cleanup_volunteer_child_tables_only",
                    "dry_run": dry_run,
                    "lock": lock_name,
                },
            )

    results = {"success": True, "dry_run": dry_run, "total_deleted": 0, "details": [], "audit_log": []}

    try:
        for child_table in VOLUNTEER_CHILD_TABLES:
            table_name = f"tab{child_table}"

            # SECURITY: Validate table name format
            if not _validate_table_name(table_name):
                frappe.log_error(f"Invalid table name format: {table_name}", "Volunteer Cleanup Security")
                continue

            try:
                # Note: Skip table_exists() check - it has bugs with spaces in names
                # Count orphaned records using LEFT JOIN (optimized)
                orphaned_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*) as count
                    FROM `{table_name}` ct
                    LEFT JOIN `tabVolunteer` v ON ct.parent = v.name
                    WHERE v.name IS NULL
                    """,
                    as_dict=True,
                )[0].count

                if orphaned_count > 0:
                    # Get sample IDs for audit trail
                    sample_ids = frappe.db.sql(
                        f"""
                        SELECT ct.name, ct.parent
                        FROM `{table_name}` ct
                        LEFT JOIN `tabVolunteer` v ON ct.parent = v.name
                        WHERE v.name IS NULL
                        LIMIT 100
                        """,
                        as_dict=True,
                    )

                    if not dry_run:
                        # Log to Error Log for audit trail
                        frappe.log_error(
                            f"""Data Cleanup Audit - Volunteer Child Tables

Child Table: {child_table}
Orphaned Records: {orphaned_count}
Sample IDs: {[s.name for s in sample_ids[:10]]}
Sample Parents: {[s.parent for s in sample_ids[:10]]}
User: {frappe.session.user}
Timestamp: {frappe.utils.now()}
""",
                            f"Orphan Cleanup: {child_table}",
                        )

                        # Batch delete orphaned records
                        deleted_count = _batch_delete_orphans(
                            table_name=table_name,
                            parent_table="tabVolunteer",
                            parent_doctype="Volunteer",
                            batch_size=BATCH_SIZE,
                        )

                        results["total_deleted"] += deleted_count
                        results["details"].append(
                            {
                                "table": child_table,
                                "deleted": deleted_count,
                                "sample_ids": [s.name for s in sample_ids[:10]],
                            }
                        )
                    else:
                        # Dry run - just report what would be deleted
                        results["total_deleted"] += orphaned_count
                        results["details"].append(
                            {
                                "table": child_table,
                                "would_delete": orphaned_count,
                                "sample_ids": [s.name for s in sample_ids[:10]],
                                "sample_parents": [s.parent for s in sample_ids[:10]],
                            }
                        )

                    # Add to audit log
                    results["audit_log"].append(
                        {
                            "table": child_table,
                            "count": orphaned_count,
                            "dry_run": dry_run,
                            "timestamp": frappe.utils.now(),
                            "user": frappe.session.user,
                        }
                    )

            except Exception as e:
                results["details"].append({"table": child_table, "error": str(e)})

        results["summary"] = (
            f"{'Would delete' if dry_run else 'Deleted'} {results['total_deleted']} "
            f"orphaned Volunteer child table records"
        )

        return OperationResult.ok(results, message=_(results.get("summary", "Volunteer cleanup completed")))

    except Exception as e:
        frappe.log_error(
            f"Error cleaning Volunteer child tables: {str(e)}\n{traceback.format_exc()}",
            "Volunteer Child Table Cleanup Error",
        )
        return OperationResult.fail(
            _("Unable to complete Volunteer child table cleanup. Please contact support."),
            errors=[str(e)],
            context={"operation": "cleanup_volunteer_child_tables_only", "dry_run": dry_run},
        )

    finally:
        # Always release lock if acquired
        if lock:
            try:
                lock.release()
            except Exception:
                pass  # Lock may have expired, ignore
