"""
Version History Cleanup Utilities
Secure functions for managing version history storage
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_all_versions():
    """
    Clear all version history from the Version table.

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear version history"), frappe.PermissionError)

    # Get statistics before deletion
    stats = frappe.db.sql(
        """
        SELECT
            ref_doctype,
            COUNT(*) as count,
            SUM(LENGTH(data)) as total_size
        FROM tabVersion
        GROUP BY ref_doctype
        ORDER BY total_size DESC
    """,
        as_dict=True,
    )

    # Get total count and size
    total_result = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_count,
            SUM(LENGTH(data)) as total_size
        FROM tabVersion
    """,
        as_dict=True,
    )

    total_count = total_result[0].total_count if total_result else 0
    # SUM() over an empty table returns NULL, so an already-cleared tabVersion
    # gave total_size = None and the size arithmetic below raised TypeError -
    # i.e. calling this endpoint twice in a row failed the second time.
    total_size = (total_result[0].total_size if total_result else 0) or 0

    # Delete all versions using TRUNCATE for better performance.
    # TRUNCATE is faster than DELETE for clearing entire tables and bypasses
    # MySQL safe mode. sql_ddl() rather than sql(): TRUNCATE is DDL, and Frappe
    # rejects it once the request has written anything (ImplicitCommitError).
    # sql_ddl() marks it as DDL and commits any pending work first.
    frappe.db.sql_ddl("TRUNCATE TABLE tabVersion")

    # Log the action
    frappe.logger("verenigingen.version_cleanup").warning(
        f"Version table cleared by {frappe.session.user}: "
        f"{total_count:,} versions deleted, "
        f"{total_size / (1024 * 1024):.2f} MB freed"
    )

    return {
        "success": True,
        "deleted_count": total_count,
        "size_freed_mb": round(total_size / (1024 * 1024), 2),
        "doctype_breakdown": stats[:10],  # Top 10 doctypes
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_version_statistics():
    """
    Get statistics about version history storage.

    Returns: Detailed breakdown of version storage
    """
    # Overall statistics
    total_result = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_count,
            SUM(LENGTH(data)) as total_size,
            MIN(creation) as oldest,
            MAX(creation) as newest
        FROM tabVersion
    """,
        as_dict=True,
    )

    # By DocType
    doctype_stats = frappe.db.sql(
        """
        SELECT
            ref_doctype,
            COUNT(*) as count,
            SUM(LENGTH(data)) as total_size,
            AVG(LENGTH(data)) as avg_size
        FROM tabVersion
        GROUP BY ref_doctype
        ORDER BY total_size DESC
        LIMIT 20
    """,
        as_dict=True,
    )

    # Format sizes
    for stat in doctype_stats:
        stat["total_size_mb"] = round(stat["total_size"] / (1024 * 1024), 2)
        stat["avg_size_bytes"] = int(stat["avg_size"])

    total = total_result[0] if total_result else {}

    return {
        "success": True,
        "total_versions": total.get("total_count", 0),
        # `or 0`, not a .get() default: SUM() over an empty table returns a
        # present-but-None key, and an emptied tabVersion made this 500.
        "total_size_mb": round((total.get("total_size") or 0) / (1024 * 1024), 2),
        "oldest_version": total.get("oldest"),
        "newest_version": total.get("newest"),
        "doctype_breakdown": doctype_stats,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_versions_older_than_days(days=90):
    """
    Clear version history older than specified days.

    Args:
        days: Delete versions older than this many days (default: 90)

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear version history"), frappe.PermissionError)

    # Validate days parameter
    days = int(days)
    if days < 1:
        frappe.throw(_("Days must be at least 1"))

    # Get statistics before deletion
    stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as count,
            SUM(LENGTH(data)) as total_size
        FROM tabVersion
        WHERE creation < DATE_SUB(NOW(), INTERVAL %s DAY)
    """,
        (days,),
        as_dict=True,
    )

    count = stats[0].count if stats else 0
    size = stats[0].total_size if stats else 0

    if count == 0:
        return {
            "success": True,
            "deleted_count": 0,
            "size_freed_mb": 0,
            "message": f"No versions older than {days} days found",
        }

    # Delete old versions
    frappe.db.sql(
        """
        DELETE FROM tabVersion
        WHERE creation < DATE_SUB(NOW(), INTERVAL %s DAY)
    """,
        (days,),
    )
    frappe.db.commit()

    # Log the action
    frappe.logger("verenigingen.version_cleanup").info(
        f"Versions older than {days} days cleared by {frappe.session.user}: "
        f"{count:,} versions deleted, "
        f"{size / (1024 * 1024):.2f} MB freed"
    )

    return {
        "success": True,
        "deleted_count": count,
        "size_freed_mb": round(size / (1024 * 1024), 2),
        "days_threshold": days,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def nuclear_truncate_version_and_deleted_tables(confirm_nuclear_truncate=False, dry_run=True):
    """
    Nuclear TRUNCATE cleanup: Instantly reset Version and Deleted Document tables to empty state.

    This function uses SQL TRUNCATE statements to instantly empty both the Version history
    table and the Deleted Document table. This is much faster than row-by-row deletion
    and is useful for development/testing environments or when you need to reclaim
    significant disk space quickly.

    Tables that will be TRUNCATED:
    - tabVersion (document version history)
    - tabDeleted Document (soft-deleted documents)

    Args:
        confirm_nuclear_truncate (bool): Must be True to proceed
        dry_run (bool): If True, only shows what would be truncated

    Returns:
        dict: Results of the truncate operation including record counts and sizes freed

    Security:
        - Requires Verenigingen Administrator role
        - Rate limited to 2 uses per hour per user (via COR)
    """
    # Security validation - Verenigingen Administrator only
    user = frappe.session.user
    if user != "Administrator":
        user_roles = frappe.get_roles()
        if Roles.VERENIGINGEN_ADMIN not in user_roles:
            frappe.throw(
                _("This operation requires Verenigingen Administrator role."),
                frappe.PermissionError,
            )

    if not confirm_nuclear_truncate:
        frappe.throw(
            _("You must set confirm_nuclear_truncate=True to proceed with this destructive operation")
        )

    # Log the attempt for audit
    frappe.logger("verenigingen.security").warning(
        f"Nuclear TRUNCATE (Version + Deleted Documents) {'(DRY RUN)' if dry_run else 'EXECUTING'} "
        f"initiated by {frappe.session.user}"
    )

    results = {
        "dry_run": dry_run,
        "tables_truncated": [],
        "records_before": {},
        "size_freed_mb": {},
        "errors": [],
        "summary": "",
    }

    try:
        # Get Version table statistics
        version_stats = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(LENGTH(data)), 0) as total_size
            FROM tabVersion
        """,
            as_dict=True,
        )
        version_count = version_stats[0].total_count if version_stats else 0
        version_size = version_stats[0].total_size if version_stats else 0
        results["records_before"]["tabVersion"] = version_count
        results["size_freed_mb"]["tabVersion"] = round(version_size / (1024 * 1024), 2)

        # Get Deleted Document table statistics
        deleted_stats = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_count,
                ROUND(DATA_LENGTH / 1024 / 1024, 2) as size_mb
            FROM information_schema.TABLES t
            CROSS JOIN (SELECT COUNT(*) as total_count FROM `tabDeleted Document`) c
            WHERE t.TABLE_SCHEMA = %s
            AND t.TABLE_NAME = 'tabDeleted Document'
        """,
            (frappe.conf.db_name,),
            as_dict=True,
        )

        if deleted_stats:
            deleted_count = deleted_stats[0].total_count
            deleted_size = deleted_stats[0].size_mb or 0
        else:
            # Fallback if information_schema query fails
            deleted_count = frappe.db.count("Deleted Document")
            deleted_size = 0

        results["records_before"]["tabDeleted Document"] = deleted_count
        results["size_freed_mb"]["tabDeleted Document"] = deleted_size

        # Calculate totals
        total_records = version_count + deleted_count
        total_size_mb = results["size_freed_mb"]["tabVersion"] + deleted_size

        if dry_run:
            results["summary"] = (
                f"DRY RUN: Would truncate 2 tables - "
                f"tabVersion ({version_count:,} records, {results['size_freed_mb']['tabVersion']:.2f} MB), "
                f"tabDeleted Document ({deleted_count:,} records, {deleted_size:.2f} MB). "
                f"Total: {total_records:,} records, {total_size_mb:.2f} MB"
            )
            return results

        # ========== ACTUAL TRUNCATE OPERATION ==========
        # Deliberately NO frappe.db.begin(), and sql_ddl() rather than sql():
        # START TRANSACTION and a raw TRUNCATE are both in Frappe's
        # IMPLICIT_COMMIT_QUERY_TYPES and are rejected once the request has
        # written anything. Two TRUNCATEs cannot be made atomic with each other
        # in any case - DDL commits implicitly and cannot be rolled back - so the
        # transaction wrapper never provided the guarantee it appeared to.
        frappe.db.commit()

        try:
            # Truncate Version table
            frappe.db.sql_ddl("TRUNCATE TABLE `tabVersion`")
            results["tables_truncated"].append("tabVersion")
            frappe.logger().info(f"Truncated tabVersion ({version_count:,} records)")

            # Truncate Deleted Document table
            frappe.db.sql_ddl("TRUNCATE TABLE `tabDeleted Document`")
            results["tables_truncated"].append("tabDeleted Document")
            frappe.logger().info(f"Truncated tabDeleted Document ({deleted_count:,} records)")

            results["summary"] = (
                f"Nuclear TRUNCATE completed: "
                f"tabVersion ({version_count:,} records, {results['size_freed_mb']['tabVersion']:.2f} MB), "
                f"tabDeleted Document ({deleted_count:,} records, {deleted_size:.2f} MB). "
                f"Total freed: {total_records:,} records, {total_size_mb:.2f} MB"
            )

            frappe.logger("verenigingen.security").info(
                f"Nuclear TRUNCATE (Version + Deleted Documents) completed by {frappe.session.user}: {results['summary']}"
            )

        except Exception as e:
            # No rollback: TRUNCATE is DDL and commits implicitly, so a failure
            # partway through leaves the earlier table truncated. results
            # ["tables_truncated"] records exactly which ones went.
            results["summary"] = f"Critical error after truncating {results['tables_truncated']}: {str(e)}"
            results["errors"].append(str(e))
            frappe.log_error(
                f"Nuclear TRUNCATE (Version + Deleted Documents) failed: {str(e)}",
                "Version Cleanup Error",
            )

    except Exception as e:
        results["summary"] = f"Unexpected error during truncate: {str(e)}"
        results["errors"].append(str(e))
        frappe.log_error(
            f"Nuclear TRUNCATE (Version + Deleted Documents) unexpected error: {str(e)}",
            "Version Cleanup Error",
        )

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_versions_by_doctype(doctype: str, older_than_days=None):
    """
    Clear version history for a specific DocType.

    Args:
        doctype: The DocType to clear versions for
        older_than_days: Optional - only delete versions older than N days

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear version history"), frappe.PermissionError)

    # Build query
    if older_than_days:
        older_than_days = int(older_than_days)
        where_clause = "ref_doctype = %s AND creation < DATE_SUB(NOW(), INTERVAL %s DAY)"
        params = (doctype, older_than_days)
    else:
        where_clause = "ref_doctype = %s"
        params = (doctype,)

    # Get statistics before deletion
    stats = frappe.db.sql(
        f"""
        SELECT
            COUNT(*) as count,
            SUM(LENGTH(data)) as total_size
        FROM tabVersion
        WHERE {where_clause}
    """,
        params,
        as_dict=True,
    )

    count = stats[0].count if stats else 0
    size = stats[0].total_size if stats else 0

    if count == 0:
        return {
            "success": True,
            "deleted_count": 0,
            "size_freed_mb": 0,
            "message": f"No versions found for {doctype}",
        }

    # Delete versions
    frappe.db.sql(
        f"""
        DELETE FROM tabVersion
        WHERE {where_clause}
    """,
        params,
    )
    frappe.db.commit()

    # Log the action
    frappe.logger("verenigingen.version_cleanup").info(
        f"Versions for {doctype} cleared by {frappe.session.user}: "
        f"{count:,} versions deleted, "
        f"{size / (1024 * 1024):.2f} MB freed"
    )

    return {
        "success": True,
        "doctype": doctype,
        "deleted_count": count,
        "size_freed_mb": round(size / (1024 * 1024), 2),
        "older_than_days": older_than_days,
    }
