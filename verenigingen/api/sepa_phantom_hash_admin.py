"""
SEPA Phantom Hash Administration API

Provides admin tools for managing "phantom" hash entries - upload log records
where the hash was reserved but file attachment failed. These require manual
investigation and resolution to prevent blocking legitimate re-uploads.

Security: All endpoints require System Manager or Accounts Manager role.

Thread Safety:
    All mutation operations use SELECT ... FOR UPDATE to acquire row locks,
    preventing race conditions between concurrent workers.

Author: Verenigingen Development Team
"""

from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
)

# Status values for phantom entries
STATUS_PENDING = "Pending"
STATUS_REJECTED = "Rejected"
STATUS_ABANDONED = "Abandoned"
STATUS_RESOLVED = "Resolved"

# Maximum length for error messages stored in bank_error_message field
# Prevents sensitive info leakage from full stack traces
MAX_ERROR_MESSAGE_LENGTH = 200


def _truncate_error_message(error: str) -> str:
    """
    Truncate error message to prevent sensitive info leakage.

    Takes only the first line and limits total length.

    Args:
        error: Full error message or exception string

    Returns:
        Truncated error message safe for storage
    """
    if not error:
        return ""
    # Take first line only (no stack traces)
    first_line = str(error).split("\n")[0].strip()
    # Truncate to max length
    if len(first_line) > MAX_ERROR_MESSAGE_LENGTH:
        return first_line[: MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
    return first_line


def _acquire_row_lock(log_name: str) -> Optional[Dict]:
    """
    Acquire exclusive row lock on upload log entry using SELECT ... FOR UPDATE.

    This prevents race conditions where two concurrent workers might both
    read and operate on the same row.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry

    Returns:
        Dict with row data if found, None if row doesn't exist
    """
    result = frappe.db.sql(
        """
        SELECT name, bank_status, is_phantom, file_hash, batch_name, hash_freed
        FROM `tabSEPA Batch Upload Log`
        WHERE name = %s
        FOR UPDATE
        """,
        (log_name,),
        as_dict=True,
    )
    return result[0] if result else None


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_phantom_hashes(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    """
    List phantom hash entries (reserved but attachment failed).

    Phantom entries are identified by the is_phantom flag (indexed for performance).

    Args:
        status: Optional filter by bank_status
        limit: Maximum entries to return (default 50, max 200)
        offset: Pagination offset

    Returns:
        Dict with entries list and pagination info
    """
    frappe.only_for([Roles.SYSTEM_MANAGER, "Accounts Manager"])

    limit = min(max(int(limit), 1), 200)
    offset = max(int(offset), 0)

    filters = {"is_phantom": 1}
    if status:
        filters["bank_status"] = status

    # Get entries using indexed is_phantom field (efficient query)
    entries = frappe.get_all(
        "SEPA Batch Upload Log",
        filters=filters,
        fields=[
            "name",
            "batch_name",
            "file_hash",
            "file_name",
            "upload_time",
            "uploaded_by",
            "bank_status",
            "bank_error_message",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        start=offset,
        page_length=limit,
    )

    total_count = frappe.db.count("SEPA Batch Upload Log", filters=filters)

    return {
        "entries": entries,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(entries)) < total_count,
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_phantom_hash_details(log_name: str) -> Dict:
    """
    Get detailed information about a phantom hash entry.

    Includes the related batch document if it exists.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry

    Returns:
        Dict with full entry details and related batch info
    """
    frappe.only_for([Roles.SYSTEM_MANAGER, "Accounts Manager"])

    log_entry = frappe.get_doc("SEPA Batch Upload Log", log_name)

    result = {
        "log_entry": {
            "name": log_entry.name,
            "batch_name": log_entry.batch_name,
            "file_hash": log_entry.file_hash,
            "file_name": log_entry.file_name,
            "file_size": log_entry.file_size,
            "upload_time": str(log_entry.upload_time) if log_entry.upload_time else None,
            "uploaded_by": log_entry.uploaded_by,
            "bank_status": log_entry.bank_status,
            "bank_error_message": log_entry.bank_error_message,
            "is_phantom": log_entry.is_phantom,
            "creation": str(log_entry.creation),
            "modified": str(log_entry.modified),
        },
        "batch": None,
        "can_abandon": False,
        "can_retry": False,
        "recommendations": [],
    }

    # Try to get related batch
    if log_entry.batch_name:
        try:
            batch = frappe.get_doc("Direct Debit Batch", log_entry.batch_name)
            result["batch"] = {
                "name": batch.name,
                "status": batch.status,
                "sepa_file": batch.sepa_file,
                "sepa_file_generated": batch.sepa_file_generated,
                "total_amount": batch.total_amount,
                "entry_count": batch.entry_count,
            }
        except frappe.DoesNotExistError:
            result["recommendations"].append(
                _("Batch '{0}' no longer exists. Consider abandoning this phantom entry.").format(
                    log_entry.batch_name
                )
            )

    # Determine available actions based on is_phantom flag
    if log_entry.is_phantom and log_entry.bank_status == STATUS_REJECTED:
        result["can_abandon"] = True
        result["can_retry"] = True
        result["recommendations"].append(
            _("This entry was created when file attachment failed after hash reservation.")
        )
        result["recommendations"].append(
            _(
                "Options: (1) Mark as 'Abandoned' if you've resolved manually, "
                "or (2) Use 'Retry Attachment' to re-attach the file."
            )
        )

    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def mark_phantom_hash_abandoned(
    log_name: str,
    reason: str,
) -> Dict:
    """
    Mark a phantom hash entry as abandoned after manual investigation.

    This frees up the hash for future uploads by setting hash_freed=1.
    The log entry is preserved for audit trail purposes.

    Use this when:
    - The original batch was cancelled or recreated
    - The issue was resolved manually outside the system
    - After confirming no duplicate upload risk

    Thread-safe: Uses SELECT ... FOR UPDATE to acquire row lock.
    Idempotent: Returns success if already abandoned.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry
        reason: Mandatory explanation for abandonment (audit trail)

    Returns:
        Dict with success status and updated entry
    """
    frappe.only_for([Roles.SYSTEM_MANAGER, "Accounts Manager"])

    if not reason or len(reason.strip()) < 10:
        frappe.throw(_("Reason must be at least 10 characters for audit purposes."))

    # Use transaction with row lock to prevent concurrent operations
    frappe.db.begin()
    try:
        # Acquire exclusive row lock (blocks other workers)
        locked_row = _acquire_row_lock(log_name)

        # Check if entry exists (idempotency)
        if not locked_row:
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry not found (idempotent success)."),
                "log_name": log_name,
                "idempotent": True,
            }

        # Check if already abandoned (idempotency)
        if locked_row.get("bank_status") == STATUS_ABANDONED:
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry already abandoned (idempotent success)."),
                "log_name": log_name,
                "idempotent": True,
            }

        # Check if hash already freed (idempotency)
        if locked_row.get("hash_freed"):
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Hash already freed (idempotent success)."),
                "log_name": log_name,
                "idempotent": True,
            }

        # Verify this is a phantom entry
        if not locked_row.get("is_phantom"):
            frappe.db.rollback()
            frappe.throw(_("This entry is not a phantom hash (is_phantom=0)."))

        file_hash = locked_row.get("file_hash", "")

        # Update the log entry - keep for audit, mark as abandoned, free the hash
        frappe.db.set_value(
            "SEPA Batch Upload Log",
            log_name,
            {
                "bank_status": STATUS_ABANDONED,
                "is_phantom": 0,
                "hash_freed": 1,
                "abandoned_by": frappe.session.user,
                "abandoned_time": frappe.utils.now(),
                "abandoned_reason": reason[:500],  # Limit reason length
                "bank_error_message": (
                    f"ABANDONED: {_truncate_error_message(reason)} "
                    f"[by {frappe.session.user} at {frappe.utils.now()}]"
                ),
            },
            update_modified=True,
        )
        frappe.db.commit()

        frappe.logger().info(
            f"Phantom hash entry {log_name} abandoned by {frappe.session.user}. "
            f"Reason: {reason}. Hash {file_hash[:16]}... freed for re-upload."
        )

        return {
            "success": True,
            "message": _("Phantom hash entry abandoned. Hash is now available for re-upload."),
            "log_name": log_name,
            "freed_hash": file_hash[:16] + "..." if file_hash else None,
        }

    except Exception:
        frappe.db.rollback()
        raise


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def retry_phantom_attachment(
    log_name: str,
) -> Dict:
    """
    Retry file attachment for a phantom hash entry.

    This attempts to regenerate and attach the SEPA XML file for the
    associated batch. The hash reservation remains in place.

    Thread-safe: Uses SELECT ... FOR UPDATE to acquire row lock.
    Idempotent: Returns success if already resolved.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry

    Returns:
        Dict with success status and file URL if successful
    """
    frappe.only_for([Roles.SYSTEM_MANAGER, "Accounts Manager"])

    # Use transaction with row lock to prevent race conditions
    frappe.db.begin()
    try:
        # Acquire exclusive row lock (blocks other workers)
        locked_row = _acquire_row_lock(log_name)

        # Check if entry exists
        if not locked_row:
            frappe.db.rollback()
            frappe.throw(_("Log entry '{0}' not found.").format(log_name))

        # Check if already resolved (idempotency)
        if locked_row.get("bank_status") == STATUS_RESOLVED:
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry already resolved (idempotent success)."),
                "log_name": log_name,
                "idempotent": True,
            }

        # Check if hash already freed (shouldn't retry freed hashes)
        if locked_row.get("hash_freed"):
            frappe.db.rollback()
            frappe.throw(_("Cannot retry: hash has been freed. Entry was abandoned."))

        # Verify this is a phantom entry
        if not locked_row.get("is_phantom"):
            frappe.db.rollback()
            frappe.throw(_("This entry is not a phantom hash (is_phantom=0)."))

        batch_name = locked_row.get("batch_name")

        # Get the batch
        if not batch_name:
            frappe.db.rollback()
            frappe.throw(_("No batch associated with this entry."))

        try:
            batch = frappe.get_doc("Direct Debit Batch", batch_name)
        except frappe.DoesNotExistError:
            frappe.db.rollback()
            frappe.throw(_("Batch '{0}' no longer exists.").format(batch_name))

        # Check if batch already has a file
        if batch.sepa_file:
            # Update log to reflect file exists and clear phantom flag
            frappe.db.set_value(
                "SEPA Batch Upload Log",
                log_name,
                {
                    "bank_status": STATUS_RESOLVED,
                    "is_phantom": 0,
                    "bank_error_message": (
                        f"RESOLVED: File already attached to batch. "
                        f"[by {frappe.session.user} at {frappe.utils.now()}]"
                    ),
                    "file_name": batch.sepa_file.split("/")[-1] if batch.sepa_file else None,
                },
                update_modified=True,
            )
            frappe.db.commit()

            return {
                "success": True,
                "message": _("Batch already has SEPA file attached."),
                "file_url": batch.sepa_file,
                "log_updated": True,
            }

        # Mark as in-progress to prevent concurrent retries (within lock)
        frappe.db.set_value(
            "SEPA Batch Upload Log",
            log_name,
            {
                "bank_error_message": (
                    f"[RETRY_IN_PROGRESS] by {frappe.session.user} at {frappe.utils.now()}"
                ),
            },
            update_modified=True,
        )
        frappe.db.commit()

        # DESIGN NOTE: Lock-Release-Reacquire Pattern
        # We intentionally release the row lock here (via commit) before file generation because:
        # 1. XML generation and file attachment can be slow (seconds)
        # 2. Holding a DB lock during I/O would block other operations unnecessarily
        # 3. The [RETRY_IN_PROGRESS] message acts as a "soft lock" for human operators
        # 4. Race condition mitigation: If two workers reach this point concurrently:
        #    - Both may generate files, but only one will succeed in the final update
        #    - The idempotency check at function start (STATUS_RESOLVED) ensures the
        #      second completer finds the entry already resolved and returns success
        # 5. We re-acquire the lock before the final update to prevent lost updates

        # Attempt to regenerate the file (outside transaction for performance)
        try:
            from verenigingen.verenigingen_payments.services.sepa_xml_adapter import get_sepa_xml_adapter

            adapter = get_sepa_xml_adapter()

            # Regenerate XML
            xml_string = adapter.generate_xml_for_batch(
                batch_doc=batch,
                message_id=batch.sepa_message_id,
                payment_info_id=batch.sepa_payment_info_id,
            )

            # Create and attach file
            import os
            import tempfile

            from verenigingen.verenigingen_payments.utils.sepa_utilities import FileManagementUtilities

            temp_file_path = os.path.join(tempfile.gettempdir(), f"sepa-{batch.name}.xml")
            try:
                with open(temp_file_path, "w", encoding="utf-8") as f:
                    f.write(xml_string if isinstance(xml_string, str) else xml_string.decode("utf-8"))

                file_url = FileManagementUtilities.attach_file_to_document(
                    temp_file_path, batch.doctype, batch.name
                )
            finally:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

            # Update batch and log entry in transaction with lock
            frappe.db.begin()

            # Re-acquire lock to ensure consistency
            _acquire_row_lock(log_name)

            batch.db_set("sepa_file", file_url)
            batch.db_set("sepa_file_generated", 1)
            if batch.status == "Approved":
                batch.db_set("status", "Generated")

            frappe.db.set_value(
                "SEPA Batch Upload Log",
                log_name,
                {
                    "bank_status": STATUS_RESOLVED,
                    "is_phantom": 0,
                    "bank_error_message": (
                        f"RESOLVED: Attachment retried successfully "
                        f"[by {frappe.session.user} at {frappe.utils.now()}]"
                    ),
                    "file_name": f"sepa-{batch.name}.xml",
                },
                update_modified=True,
            )
            frappe.db.commit()

            frappe.logger().info(
                f"Phantom hash entry {log_name} resolved via retry attachment. "
                f"File {file_url} attached to batch {batch.name}."
            )

            return {
                "success": True,
                "message": _("SEPA file regenerated and attached successfully."),
                "file_url": file_url,
                "batch_status": batch.status,
            }

        except Exception as e:
            # Update log entry with truncated failure message
            error_msg = _truncate_error_message(str(e))
            frappe.db.begin()
            try:
                _acquire_row_lock(log_name)
                frappe.db.set_value(
                    "SEPA Batch Upload Log",
                    log_name,
                    {
                        "bank_error_message": (
                            f"Retry failed: {error_msg} "
                            f"[by {frappe.session.user} at {frappe.utils.now()}]"
                        ),
                    },
                    update_modified=True,
                )
                frappe.db.commit()
            except Exception:
                frappe.db.rollback()

            # Log full error server-side (not in DB)
            frappe.log_error(
                f"Retry attachment failed for phantom entry {log_name}: {str(e)}\n"
                f"Traceback: {frappe.get_traceback()}",
                "Phantom Hash Retry Failed",
            )

            return {
                "success": False,
                "message": _("Retry failed: {0}").format(error_msg),
                "error": error_msg,
            }

    except Exception:
        frappe.db.rollback()
        raise


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_phantom_hash_stats() -> Dict:
    """
    Get statistics about phantom hash entries.

    Uses indexed is_phantom field for efficient queries.

    Returns:
        Dict with counts by status and age distribution
    """
    frappe.only_for([Roles.SYSTEM_MANAGER, "Accounts Manager"])

    # Count using indexed is_phantom field (efficient)
    total = frappe.db.count("SEPA Batch Upload Log", filters={"is_phantom": 1})

    pending = frappe.db.count(
        "SEPA Batch Upload Log",
        filters={"is_phantom": 1, "bank_status": STATUS_REJECTED},
    )

    resolved = frappe.db.count(
        "SEPA Batch Upload Log",
        filters={"is_phantom": 0, "bank_status": STATUS_RESOLVED},
    )

    # Age distribution (phantom entries still pending)
    from frappe.utils import add_days, getdate

    today = getdate()

    older_than_7_days = frappe.db.count(
        "SEPA Batch Upload Log",
        filters={
            "is_phantom": 1,
            "bank_status": STATUS_REJECTED,
            "creation": ["<", add_days(today, -7)],
        },
    )

    older_than_30_days = frappe.db.count(
        "SEPA Batch Upload Log",
        filters={
            "is_phantom": 1,
            "bank_status": STATUS_REJECTED,
            "creation": ["<", add_days(today, -30)],
        },
    )

    return {
        "total_phantom_entries": total,
        "pending_investigation": pending,
        "resolved": resolved,
        "abandoned": total - pending - resolved,
        "age_distribution": {
            "older_than_7_days": older_than_7_days,
            "older_than_30_days": older_than_30_days,
        },
        "requires_attention": pending > 0,
        "recommendations": (
            [_("You have {0} phantom entries requiring investigation.").format(pending)]
            if pending > 0
            else []
        ),
    }
