"""
Deleted Document Cleanup Utilities
Frappe's soft-delete functionality stores deleted documents in the "Deleted Document" table.
These functions help manage and clean up this table to reclaim database space.

ERROR HANDLING PATTERN:
All @frappe.whitelist() functions return OperationResult[Dict[str, Any]]:
- Success: OperationResult.ok(data, message="...")
- Failure: OperationResult.fail(user_message, errors=[...], context={...})
- Comprehensive error context includes operation name + all parameters
- Traceback logging for debugging: frappe.log_error(f"...: {str(e)}\\n{traceback.format_exc()}", "Title")
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_deleted_document_statistics() -> OperationResult[Dict[str, Any]]:
    """
    Get statistics about the Deleted Document table.

    Returns:
        OperationResult[Dict[str, Any]]: Detailed breakdown of deleted documents
    """
    try:
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

        data = {
            "success": True,
            "total_deleted_documents": total.get("total_count", 0),
            "unique_doctypes": total.get("unique_doctypes", 0),
            "oldest_deletion": total.get("oldest"),
            "newest_deletion": total.get("newest"),
            "storage_size_mb": size.get("size_mb", 0),
            "doctype_breakdown": doctype_stats,
        }

        return OperationResult.ok(
            data,
            message=_("Retrieved statistics for {0} deleted documents").format(total.get("total_count", 0)),
        )

    except Exception as e:
        frappe.log_error(
            f"Error getting deleted document statistics: {str(e)}\n{traceback.format_exc()}",
            "Deleted Document Statistics Error",
        )
        return OperationResult.fail(
            _("Failed to retrieve deleted document statistics"),
            errors=[str(e)],
            context={"operation": "get_deleted_document_statistics"},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_all_deleted_documents() -> OperationResult[Dict[str, Any]]:
    """
    Clear ALL deleted documents from the Deleted Document table.

    Security: System Manager only
    Returns:
        OperationResult[Dict[str, Any]]: Statistics about cleared documents
    """
    try:
        # Security check - System Manager only
        if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
            return OperationResult.fail(
                _("Only System Managers can clear deleted documents"),
                errors=["Permission denied"],
                context={"operation": "clear_all_deleted_documents", "user": frappe.session.user},
            )

        # Get statistics before deletion. get_deleted_document_statistics is
        # @high_security_api, and that decorator serialises its OperationResult
        # to a plain dict - so this must be read as a mapping, not by attribute
        # (`.success` raised "'dict' object has no attribute 'success'", which
        # the except below turned into a generic failure).
        stats_before_result = get_deleted_document_statistics()
        if not stats_before_result.get("success"):
            return OperationResult.fail(
                _("Failed to retrieve statistics before deletion"),
                errors=stats_before_result.get("errors") or [],
                context={"operation": "clear_all_deleted_documents"},
            )

        stats_before = stats_before_result.get("data") or {}

        # Publish the statistics helper's own audit row (and anything else the
        # request left pending) before the truncate. TRUNCATE is DDL: Frappe
        # rejects it - like START TRANSACTION - once transaction_writes > 0, and
        # the @high_security_api call above always leaves exactly that. Measured:
        # transaction_writes 0 -> 1 -> ImplicitCommitError.
        frappe.db.commit()

        # TRUNCATE is faster than DELETE for clearing entire tables and bypasses
        # MySQL safe mode. sql_ddl() is required rather than sql(): it marks the
        # statement as DDL (and commits first) instead of tripping the guard.
        frappe.db.sql_ddl("TRUNCATE TABLE `tabDeleted Document`")

        # Note: OPTIMIZE TABLE not needed after TRUNCATE as it already rebuilds the table

        # Read defensively: SQL aggregates over an already-empty table come back
        # NULL, and formatting None with :,/:.2f raises TypeError -- which is
        # exactly how clear_all_versions failed on a second consecutive call.
        deleted_count = stats_before.get("total_deleted_documents") or 0
        size_freed_mb = stats_before.get("storage_size_mb") or 0

        # Log the action
        frappe.logger("verenigingen.deleted_document_cleanup").warning(
            f"All deleted documents cleared by {frappe.session.user}: "
            f"{deleted_count:,} documents deleted, {size_freed_mb:.2f} MB freed"
        )

        data = {
            "success": True,
            "deleted_count": deleted_count,
            "size_freed_mb": size_freed_mb,
            "unique_doctypes": stats_before.get("unique_doctypes") or 0,
            "oldest_deletion": stats_before.get("oldest_deletion"),
            "newest_deletion": stats_before.get("newest_deletion"),
        }

        return OperationResult.ok(
            data,
            message=_("Cleared {0} deleted documents, freed {1:.2f} MB").format(deleted_count, size_freed_mb),
        )

    except Exception as e:
        frappe.log_error(
            f"Error clearing all deleted documents: {str(e)}\n{traceback.format_exc()}",
            "Clear Deleted Documents Error",
        )
        return OperationResult.fail(
            _("Failed to clear deleted documents"),
            errors=[str(e)],
            context={"operation": "clear_all_deleted_documents", "user": frappe.session.user},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_deleted_documents_older_than_days(days=90) -> OperationResult[Dict[str, Any]]:
    """
    Clear deleted documents older than specified days.

    Args:
        days: Delete documents deleted more than this many days ago (default: 90)

    Security: System Manager only
    Returns:
        OperationResult[Dict[str, Any]]: Statistics about cleared documents
    """
    try:
        # Security check - System Manager only
        if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
            return OperationResult.fail(
                _("Only System Managers can clear deleted documents"),
                errors=["Permission denied"],
                context={
                    "operation": "clear_deleted_documents_older_than_days",
                    "user": frappe.session.user,
                    "days": days,
                },
            )

        # Validate days parameter
        days = int(days)
        if days < 1:
            return OperationResult.fail(
                _("Days must be at least 1"),
                errors=["Invalid days parameter"],
                context={"operation": "clear_deleted_documents_older_than_days", "days": days},
            )

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
            data = {"success": True, "deleted_count": 0, "days_threshold": days}
            return OperationResult.ok(
                data, message=_("No deleted documents older than {0} days found").format(days)
            )

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

        data = {"success": True, "deleted_count": count, "days_threshold": days}
        return OperationResult.ok(
            data, message=_("Cleared {0} deleted documents older than {1} days").format(count, days)
        )

    except Exception as e:
        frappe.log_error(
            f"Error clearing deleted documents older than {days} days: {str(e)}\n{traceback.format_exc()}",
            "Clear Old Deleted Documents Error",
        )
        return OperationResult.fail(
            _("Failed to clear deleted documents"),
            errors=[str(e)],
            context={
                "operation": "clear_deleted_documents_older_than_days",
                "days": days,
                "user": frappe.session.user,
            },
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_deleted_documents_by_doctype(doctype: str, older_than_days=None) -> OperationResult[Dict[str, Any]]:
    """
    Clear deleted documents for a specific DocType.

    Args:
        doctype: The DocType to clear deleted documents for
        older_than_days: Optional - only delete documents older than N days

    Security: System Manager only
    Returns:
        OperationResult[Dict[str, Any]]: Statistics about cleared documents
    """
    try:
        # Security check - System Manager only
        if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
            return OperationResult.fail(
                _("Only System Managers can clear deleted documents"),
                errors=["Permission denied"],
                context={
                    "operation": "clear_deleted_documents_by_doctype",
                    "user": frappe.session.user,
                    "doctype": doctype,
                    "older_than_days": older_than_days,
                },
            )

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
            data = {
                "success": True,
                "deleted_count": 0,
                "doctype": doctype,
                "older_than_days": older_than_days,
            }
            return OperationResult.ok(data, message=_("No deleted documents found for {0}").format(doctype))

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
            f"Deleted documents for {doctype} cleared by {frappe.session.user}: "
            f"{count:,} documents deleted"
        )

        data = {
            "success": True,
            "doctype": doctype,
            "deleted_count": count,
            "older_than_days": older_than_days,
        }
        return OperationResult.ok(
            data, message=_("Cleared {0} deleted documents for {1}").format(count, doctype)
        )

    except Exception as e:
        frappe.log_error(
            f"Error clearing deleted documents for doctype {doctype}: {str(e)}\n{traceback.format_exc()}",
            "Clear Deleted Documents By DocType Error",
        )
        return OperationResult.fail(
            _("Failed to clear deleted documents"),
            errors=[str(e)],
            context={
                "operation": "clear_deleted_documents_by_doctype",
                "doctype": doctype,
                "older_than_days": older_than_days,
                "user": frappe.session.user,
            },
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def permanently_delete_doctype_documents(
    doctype: str, document_names: str | list
) -> OperationResult[Dict[str, Any]]:
    """
    Permanently delete specific documents that are in the Deleted Document table.

    This is useful when you want to permanently remove specific sensitive documents.

    Args:
        doctype: The DocType of the documents
        document_names: List of document names to permanently delete

    Security: System Manager only
    Returns:
        OperationResult[Dict[str, Any]]: Count of permanently deleted documents
    """
    try:
        # Security check - System Manager only
        if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
            return OperationResult.fail(
                _("Only System Managers can permanently delete documents"),
                errors=["Permission denied"],
                context={
                    "operation": "permanently_delete_doctype_documents",
                    "user": frappe.session.user,
                    "doctype": doctype,
                    "document_count": len(document_names) if isinstance(document_names, list) else 0,
                },
            )

        # Convert to list if needed
        if isinstance(document_names, str):
            import json

            document_names = json.loads(document_names)

        if not isinstance(document_names, list):
            return OperationResult.fail(
                _("document_names must be a list"),
                errors=["Invalid parameter type"],
                context={
                    "operation": "permanently_delete_doctype_documents",
                    "doctype": doctype,
                    "document_names_type": type(document_names).__name__,
                },
            )

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

        data = {
            "success": True,
            "deleted_count": deleted_count,
            "doctype": doctype,
            "total_requested": len(document_names),
        }
        return OperationResult.ok(
            data,
            message=_("Permanently deleted {0} of {1} {2} documents").format(
                deleted_count, len(document_names), doctype
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error permanently deleting documents for doctype {doctype}: {str(e)}\n{traceback.format_exc()}",
            "Permanently Delete Documents Error",
        )
        return OperationResult.fail(
            _("Failed to permanently delete documents"),
            errors=[str(e)],
            context={
                "operation": "permanently_delete_doctype_documents",
                "doctype": doctype,
                "document_count": len(document_names) if isinstance(document_names, list) else 0,
                "user": frappe.session.user,
            },
        )
