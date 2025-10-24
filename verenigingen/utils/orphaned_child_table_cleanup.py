"""
Orphaned Child Table Cleanup Utility

Detects and cleans up orphaned child table records across all DocTypes.
These are child table records whose parent documents have been deleted,
creating data integrity issues and blocking document deletions.

SECURITY NOTE: All SQL queries use table names from DocType definitions.
Table names are validated against database schema to prevent SQL injection.
"""

import re

import frappe
from frappe import _


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


@frappe.whitelist()
def detect_orphaned_child_tables():
    """
    Scan all child tables (istable=1) and detect orphaned records.

    Returns detailed report of orphaned records by table.
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

            # Check if table exists in database
            if not frappe.db.table_exists(table_name):
                continue

            # Check if table has 'parent' and 'parenttype' columns
            columns = frappe.db.get_table_columns(table_name)
            if "parent" not in columns or "parenttype" not in columns:
                continue

            try:
                # Get parent DocType from a sample record
                sample = frappe.db.sql(
                    f"""
                    SELECT DISTINCT parenttype
                    FROM `{table_name}`
                    LIMIT 1
                    """,
                    as_dict=True,
                )

                if not sample:
                    continue

                parent_doctype = sample[0].parenttype
                parent_table = f"tab{parent_doctype}"

                # Check if parent table exists
                if not frappe.db.table_exists(parent_table):
                    continue

                # Count orphaned records
                orphaned_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*) as count
                    FROM `{table_name}` ct
                    WHERE ct.parent NOT IN (
                        SELECT name FROM `{parent_table}`
                    )
                    AND ct.parenttype = %s
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
                        SELECT DISTINCT parent
                        FROM `{table_name}` ct
                        WHERE ct.parent NOT IN (
                            SELECT name FROM `{parent_table}`
                        )
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

        return results

    except Exception as e:
        frappe.log_error(
            f"Error detecting orphaned child tables: {str(e)}", "Orphaned Child Table Detection Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_orphaned_child_tables(dry_run=True, table_filter=None):
    """
    Clean up orphaned child table records.

    Args:
        dry_run (bool): If True, only report what would be deleted
        table_filter (str): Optional - only clean specific child table name

    Returns:
        dict: Cleanup results with counts and details
    """
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    results = {"success": True, "dry_run": dry_run, "total_deleted": 0, "tables_cleaned": 0, "details": []}

    try:
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

            # Check if table exists in database
            if not frappe.db.table_exists(table_name):
                continue

            # Check if table has 'parent' and 'parenttype' columns
            columns = frappe.db.get_table_columns(table_name)
            if "parent" not in columns or "parenttype" not in columns:
                continue

            try:
                # Get parent DocType from records
                sample = frappe.db.sql(
                    f"""
                    SELECT DISTINCT parenttype
                    FROM `{table_name}`
                    LIMIT 1
                    """,
                    as_dict=True,
                )

                if not sample:
                    continue

                parent_doctype = sample[0].parenttype
                parent_table = f"tab{parent_doctype}"

                # Check if parent table exists
                if not frappe.db.table_exists(parent_table):
                    continue

                # Count orphaned records before deletion
                orphaned_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*) as count
                    FROM `{table_name}` ct
                    WHERE ct.parent NOT IN (
                        SELECT name FROM `{parent_table}`
                    )
                    AND ct.parenttype = %s
                    """,
                    parent_doctype,
                    as_dict=True,
                )[0].count

                if orphaned_count > 0:
                    # Get sample IDs for audit trail
                    sample_ids = []
                    try:
                        sample_ids = frappe.db.sql(
                            f"""
                            SELECT name, parent
                            FROM `{table_name}`
                            WHERE parent NOT IN (
                                SELECT name FROM `{parent_table}`
                            )
                            AND parenttype = %s
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

                        # Actually delete the orphaned records
                        frappe.db.sql(
                            f"""
                            DELETE FROM `{table_name}`
                            WHERE parent NOT IN (
                                SELECT name FROM `{parent_table}`
                            )
                            AND parenttype = %s
                            """,
                            parent_doctype,
                        )
                        frappe.db.commit()

                    results["total_deleted"] += orphaned_count
                    results["tables_cleaned"] += 1

                    results["details"].append(
                        {
                            "child_table": table.name,
                            "parent_doctype": parent_doctype,
                            "records_deleted": orphaned_count,
                            "sample_parents": [r.parent for r in sample_ids[:5]] if sample_ids else [],
                            "action": "Would delete" if dry_run else "Deleted",
                        }
                    )

                    frappe.logger().info(
                        f"{'Would delete' if dry_run else 'Deleted'} {orphaned_count} "
                        f"orphaned records from {table.name}"
                    )

            except Exception as e:
                # Log error and continue with next table
                error_msg = f"Error cleaning {table_name}: {str(e)}"
                frappe.logger().error(error_msg)
                results["details"].append({"child_table": table.name, "error": str(e)})
                continue

        results["summary"] = (
            f"{'Would delete' if dry_run else 'Deleted'} {results['total_deleted']} "
            f"orphaned records from {results['tables_cleaned']} child tables"
        )

        if dry_run:
            results[
                "note"
            ] = "This was a dry run. No records were actually deleted. Run with dry_run=False to perform cleanup."

        return results

    except Exception as e:
        frappe.log_error(
            f"Error cleaning orphaned child tables: {str(e)}", "Orphaned Child Table Cleanup Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_member_child_tables_only(dry_run=True):
    """
    Clean up only Member-related child table orphans.

    This is a focused cleanup specifically for Member DocType child tables.
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

    results = {"success": True, "dry_run": dry_run, "total_deleted": 0, "details": [], "audit_log": []}

    try:
        for child_table in MEMBER_CHILD_TABLES:
            table_name = f"tab{child_table}"

            # SECURITY: Validate table name format
            if not _validate_table_name(table_name):
                frappe.log_error(f"Invalid table name format: {table_name}", "Member Cleanup Security")
                continue

            if not frappe.db.table_exists(table_name):
                continue

            try:
                # Count orphaned records
                orphaned_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*) as count
                    FROM `{table_name}`
                    WHERE parent NOT IN (
                        SELECT name FROM `tabMember`
                    )
                    """,
                    as_dict=True,
                )[0].count

                if orphaned_count > 0:
                    # Get sample IDs for audit trail
                    sample_ids = frappe.db.sql(
                        f"""
                        SELECT name, parent
                        FROM `{table_name}`
                        WHERE parent NOT IN (
                            SELECT name FROM `tabMember`
                        )
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

                        frappe.db.sql(
                            f"""
                            DELETE FROM `{table_name}`
                            WHERE parent NOT IN (
                                SELECT name FROM `tabMember`
                            )
                            """
                        )
                        frappe.db.commit()

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

        return results

    except Exception as e:
        return {"success": False, "error": str(e)}
