"""
Deleted Document Cleanup Utilities
Frappe's soft-delete functionality stores deleted documents in the "Deleted Document" table.
These functions help manage and clean up this table to reclaim database space.
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_deleted_document_statistics():
    """
    Get statistics about the Deleted Document table.

    Returns: Detailed breakdown of deleted documents
    """
    # Overall statistics
    total_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_count,
            COUNT(DISTINCT deleted_doctype) as unique_doctypes,
            MIN(creation) as oldest,
            MAX(creation) as newest
        FROM `tabDeleted Document`
    """,
        as_dict=True,
    )

    # By DocType
    doctype_stats = frappe.db.sql(
        """
        SELECT
            deleted_doctype,
            COUNT(*) as count,
            MIN(creation) as oldest_deletion,
            MAX(creation) as newest_deletion
        FROM `tabDeleted Document`
        GROUP BY deleted_doctype
        ORDER BY count DESC
        LIMIT 20
    """,
        as_dict=True,
    )

    # Calculate approximate storage (rough estimate based on avg document size)
    size_result = frappe.db.sql(
        """
        SELECT
            ROUND(DATA_LENGTH / 1024 / 1024, 2) as size_mb,
            TABLE_ROWS as row_count
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
        AND TABLE_NAME = 'tabDeleted Document'
    """,
        (frappe.conf.db_name,),
        as_dict=True,
    )

    total = total_stats[0] if total_stats else {}
    size = size_result[0] if size_result else {"size_mb": 0, "row_count": 0}

    return {
        "success": True,
        "total_deleted_documents": total.get("total_count", 0),
        "unique_doctypes": total.get("unique_doctypes", 0),
        "oldest_deletion": total.get("oldest"),
        "newest_deletion": total.get("newest"),
        "storage_size_mb": size.get("size_mb", 0),
        "doctype_breakdown": doctype_stats,
    }


@frappe.whitelist()
def clear_all_deleted_documents():
    """
    Clear ALL deleted documents from the Deleted Document table.

    Security: System Manager only
    Returns: Statistics about cleared documents
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear deleted documents"), frappe.PermissionError)

    # Get statistics before deletion
    stats_before = get_deleted_document_statistics()

    # Delete all deleted documents using TRUNCATE for better performance
    # TRUNCATE is faster than DELETE for clearing entire tables and bypasses MySQL safe mode
    frappe.db.sql("TRUNCATE TABLE `tabDeleted Document`")
    frappe.db.commit()

    # Note: OPTIMIZE TABLE not needed after TRUNCATE as it already rebuilds the table

    # Log the action
    frappe.logger("verenigingen.deleted_document_cleanup").warning(
        f"All deleted documents cleared by {frappe.session.user}: "
        f"{stats_before['total_deleted_documents']:,} documents deleted, "
        f"{stats_before['storage_size_mb']:.2f} MB freed"
    )

    return {
        "success": True,
        "deleted_count": stats_before["total_deleted_documents"],
        "size_freed_mb": stats_before["storage_size_mb"],
        "unique_doctypes": stats_before["unique_doctypes"],
        "oldest_deletion": stats_before["oldest_deletion"],
        "newest_deletion": stats_before["newest_deletion"],
    }


@frappe.whitelist()
def clear_deleted_documents_older_than_days(days=90):
    """
    Clear deleted documents older than specified days.

    Args:
        days: Delete documents deleted more than this many days ago (default: 90)

    Security: System Manager only
    Returns: Statistics about cleared documents
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear deleted documents"), frappe.PermissionError)

    # Validate days parameter
    days = int(days)
    if days < 1:
        frappe.throw(_("Days must be at least 1"))

    # Get count before deletion
    count_result = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabDeleted Document`
        WHERE creation < DATE_SUB(NOW(), INTERVAL %s DAY)
    """,
        (days,),
        as_dict=True,
    )

    count = count_result[0].count if count_result else 0

    if count == 0:
        return {
            "success": True,
            "deleted_count": 0,
            "message": f"No deleted documents older than {days} days found",
        }

    # Delete old deleted documents
    frappe.db.sql(
        """
        DELETE FROM `tabDeleted Document`
        WHERE creation < DATE_SUB(NOW(), INTERVAL %s DAY)
    """,
        (days,),
    )
    frappe.db.commit()

    # Optimize the table to reclaim space
    frappe.db.sql("OPTIMIZE TABLE `tabDeleted Document`")

    # Log the action
    frappe.logger("verenigingen.deleted_document_cleanup").info(
        f"Deleted documents older than {days} days cleared by {frappe.session.user}: "
        f"{count:,} documents deleted"
    )

    return {"success": True, "deleted_count": count, "days_threshold": days}


@frappe.whitelist()
def clear_deleted_documents_by_doctype(doctype, older_than_days=None):
    """
    Clear deleted documents for a specific DocType.

    Args:
        doctype: The DocType to clear deleted documents for
        older_than_days: Optional - only delete documents older than N days

    Security: System Manager only
    Returns: Statistics about cleared documents
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear deleted documents"), frappe.PermissionError)

    # Build query
    if older_than_days:
        older_than_days = int(older_than_days)
        where_clause = "deleted_doctype = %s AND creation < DATE_SUB(NOW(), INTERVAL %s DAY)"
        params = (doctype, older_than_days)
    else:
        where_clause = "deleted_doctype = %s"
        params = (doctype,)

    # Get count before deletion
    count_result = frappe.db.sql(
        f"""
        SELECT COUNT(*) as count
        FROM `tabDeleted Document`
        WHERE {where_clause}
    """,
        params,
        as_dict=True,
    )

    count = count_result[0].count if count_result else 0

    if count == 0:
        return {"success": True, "deleted_count": 0, "message": f"No deleted documents found for {doctype}"}

    # Delete documents
    frappe.db.sql(
        f"""
        DELETE FROM `tabDeleted Document`
        WHERE {where_clause}
    """,
        params,
    )
    frappe.db.commit()

    # Optimize the table to reclaim space
    frappe.db.sql("OPTIMIZE TABLE `tabDeleted Document`")

    # Log the action
    frappe.logger("verenigingen.deleted_document_cleanup").info(
        f"Deleted documents for {doctype} cleared by {frappe.session.user}: " f"{count:,} documents deleted"
    )

    return {"success": True, "doctype": doctype, "deleted_count": count, "older_than_days": older_than_days}


@frappe.whitelist()
def permanently_delete_doctype_documents(doctype, document_names):
    """
    Permanently delete specific documents that are in the Deleted Document table.

    This is useful when you want to permanently remove specific sensitive documents.

    Args:
        doctype: The DocType of the documents
        document_names: List of document names to permanently delete

    Security: System Manager only
    Returns: Count of permanently deleted documents
    """
    # Security check - System Manager only
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can permanently delete documents"), frappe.PermissionError)

    # Convert to list if needed
    if isinstance(document_names, str):
        import json

        document_names = json.loads(document_names)

    if not isinstance(document_names, list):
        frappe.throw(_("document_names must be a list"))

    deleted_count = 0

    for doc_name in document_names:
        result = frappe.db.sql(
            """
            DELETE FROM `tabDeleted Document`
            WHERE deleted_doctype = %s
            AND deleted_name = %s
        """,
            (doctype, doc_name),
        )

        if result:
            deleted_count += 1

    frappe.db.commit()

    # Log the action
    frappe.logger("verenigingen.deleted_document_cleanup").warning(
        f"Permanently deleted {deleted_count} {doctype} documents by {frappe.session.user}"
    )

    return {"success": True, "deleted_count": deleted_count, "doctype": doctype}
