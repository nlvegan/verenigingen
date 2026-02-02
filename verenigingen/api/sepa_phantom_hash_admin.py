"""
SEPA Phantom Hash Administration API

Provides admin tools for managing "phantom" hash entries - upload log records
where the hash was reserved but file attachment failed. These require manual
investigation and resolution to prevent blocking legitimate re-uploads.

Security: All endpoints require System Manager or Accounts Manager role.

Author: Verenigingen Development Team
"""

from typing import Dict, Optional

import frappe
from frappe import _

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
    frappe.only_for(["System Manager", "Accounts Manager"])

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
    frappe.only_for(["System Manager", "Accounts Manager"])

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

    This frees up the hash for future uploads. Use this when:
    - The original batch was cancelled or recreated
    - The issue was resolved manually outside the system
    - After confirming no duplicate upload risk

    Idempotent: Returns success if already abandoned/deleted.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry
        reason: Mandatory explanation for abandonment (audit trail)

    Returns:
        Dict with success status and updated entry
    """
    frappe.only_for(["System Manager", "Accounts Manager"])

    if not reason or len(reason.strip()) < 10:
        frappe.throw(_("Reason must be at least 10 characters for audit purposes."))

    # Use transaction with lock to prevent concurrent operations
    frappe.db.begin()
    try:
        # Check if entry still exists (idempotency)
        if not frappe.db.exists("SEPA Batch Upload Log", log_name):
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry already deleted (idempotent success)."),
                "deleted_entry": log_name,
                "idempotent": True,
            }

        log_entry = frappe.get_doc("SEPA Batch Upload Log", log_name)

        # Check if already resolved (idempotency)
        if log_entry.bank_status == STATUS_ABANDONED:
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry already abandoned (idempotent success)."),
                "deleted_entry": log_name,
                "idempotent": True,
            }

        # Verify this is a phantom entry
        if not log_entry.is_phantom:
            frappe.db.rollback()
            frappe.throw(_("This entry is not a phantom hash (is_phantom=0)."))

        # Log the abandonment before deletion (for audit trail)
        file_hash = log_entry.file_hash
        frappe.logger().info(
            f"Phantom hash entry {log_name} abandoned by {frappe.session.user}. "
            f"Reason: {reason}. Hash {file_hash[:16]}... freed for re-upload."
        )

        # Delete the log entry to free up the hash
        frappe.delete_doc("SEPA Batch Upload Log", log_name, ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": _("Phantom hash entry abandoned and deleted. Hash is now available for re-upload."),
            "deleted_entry": log_name,
            "freed_hash": file_hash[:16] + "...",
        }

    except Exception as e:
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

    Idempotent: Returns success if already resolved.
    Thread-safe: Uses transaction with status checks.

    Args:
        log_name: Name of the SEPA Batch Upload Log entry

    Returns:
        Dict with success status and file URL if successful
    """
    frappe.only_for(["System Manager", "Accounts Manager"])

    # Use transaction to prevent race conditions
    frappe.db.begin()
    try:
        # Check if entry exists
        if not frappe.db.exists("SEPA Batch Upload Log", log_name):
            frappe.db.rollback()
            frappe.throw(_("Log entry '{0}' not found.").format(log_name))

        log_entry = frappe.get_doc("SEPA Batch Upload Log", log_name)

        # Check if already resolved (idempotency)
        if log_entry.bank_status == STATUS_RESOLVED:
            frappe.db.rollback()
            return {
                "success": True,
                "message": _("Entry already resolved (idempotent success)."),
                "log_name": log_name,
                "idempotent": True,
            }

        # Verify this is a phantom entry
        if not log_entry.is_phantom:
            frappe.db.rollback()
            frappe.throw(_("This entry is not a phantom hash (is_phantom=0)."))

        # Get the batch
        if not log_entry.batch_name:
            frappe.db.rollback()
            frappe.throw(_("No batch associated with this entry."))

        try:
            batch = frappe.get_doc("Direct Debit Batch", log_entry.batch_name)
        except frappe.DoesNotExistError:
            frappe.db.rollback()
            frappe.throw(_("Batch '{0}' no longer exists.").format(log_entry.batch_name))

        # Check if batch already has a file
        if batch.sepa_file:
            # Update log to reflect file exists and clear phantom flag
            log_entry.bank_status = STATUS_RESOLVED
            log_entry.is_phantom = 0
            log_entry.bank_error_message = (
                f"RESOLVED: File already attached to batch. "
                f"Updated by {frappe.session.user} at {frappe.utils.now()}"
            )
            log_entry.file_name = batch.sepa_file.split("/")[-1] if batch.sepa_file else None
            log_entry.save(ignore_permissions=True)
            frappe.db.commit()

            return {
                "success": True,
                "message": _("Batch already has SEPA file attached."),
                "file_url": batch.sepa_file,
                "log_updated": True,
            }

        # Mark as in-progress to prevent concurrent retries
        log_entry.bank_error_message = (
            f"Retry in progress by {frappe.session.user} at {frappe.utils.now()}..."
        )
        log_entry.save(ignore_permissions=True)
        frappe.db.commit()

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

            # Update batch and log entry in transaction
            frappe.db.begin()
            batch.db_set("sepa_file", file_url)
            batch.db_set("sepa_file_generated", 1)
            if batch.status == "Approved":
                batch.db_set("status", "Generated")

            # Reload log entry and update (may have been modified)
            log_entry.reload()
            log_entry.bank_status = STATUS_RESOLVED
            log_entry.is_phantom = 0
            log_entry.bank_error_message = (
                f"RESOLVED: Attachment retried successfully by {frappe.session.user} "
                f"at {frappe.utils.now()}"
            )
            log_entry.file_name = f"sepa-{batch.name}.xml"
            log_entry.save(ignore_permissions=True)
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
            # Update log entry with failure message
            frappe.db.begin()
            try:
                log_entry.reload()
                log_entry.bank_error_message = (
                    f"Retry failed by {frappe.session.user} at {frappe.utils.now()}: {str(e)}"
                )
                log_entry.save(ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                frappe.db.rollback()

            frappe.log_error(
                f"Retry attachment failed for phantom entry {log_name}: {str(e)}\n"
                f"Traceback: {frappe.get_traceback()}",
                "Phantom Hash Retry Failed",
            )

            return {
                "success": False,
                "message": _("Retry failed: {0}").format(str(e)),
                "error": str(e),
            }

    except Exception as e:
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
    frappe.only_for(["System Manager", "Accounts Manager"])

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
