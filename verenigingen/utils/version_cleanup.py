"""
Version History Cleanup Utilities
Secure functions for managing version history storage
"""

import frappe
from frappe import _


@frappe.whitelist()
def clear_all_versions():
    """
    Clear all version history from the Version table.

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
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
    total_size = total_result[0].total_size if total_result else 0

    # Delete all versions
    frappe.db.sql("DELETE FROM tabVersion")
    frappe.db.commit()

    # Log the action
    frappe.logger("verenigingen.version_cleanup").warning(
        f"Version table cleared by {frappe.session.user}: "
        f"{total_count:,} versions deleted, "
        f"{total_size/(1024*1024):.2f} MB freed"
    )

    return {
        "success": True,
        "deleted_count": total_count,
        "size_freed_mb": round(total_size / (1024 * 1024), 2),
        "doctype_breakdown": stats[:10],  # Top 10 doctypes
    }


@frappe.whitelist()
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
        "total_size_mb": round(total.get("total_size", 0) / (1024 * 1024), 2),
        "oldest_version": total.get("oldest"),
        "newest_version": total.get("newest"),
        "doctype_breakdown": doctype_stats,
    }


@frappe.whitelist()
def clear_versions_older_than_days(days=90):
    """
    Clear version history older than specified days.

    Args:
        days: Delete versions older than this many days (default: 90)

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
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
        f"{size/(1024*1024):.2f} MB freed"
    )

    return {
        "success": True,
        "deleted_count": count,
        "size_freed_mb": round(size / (1024 * 1024), 2),
        "days_threshold": days,
    }


@frappe.whitelist()
def clear_versions_by_doctype(doctype, older_than_days=None):
    """
    Clear version history for a specific DocType.

    Args:
        doctype: The DocType to clear versions for
        older_than_days: Optional - only delete versions older than N days

    Security: System Manager only
    Returns: Statistics about deleted versions
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
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
        f"{size/(1024*1024):.2f} MB freed"
    )

    return {
        "success": True,
        "doctype": doctype,
        "deleted_count": count,
        "size_freed_mb": round(size / (1024 * 1024), 2),
        "older_than_days": older_than_days,
    }
