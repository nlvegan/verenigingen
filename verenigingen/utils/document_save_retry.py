"""
Document Save Retry Utilities

Provides robust retry mechanisms for document saves with timestamp mismatch handling.

This module eliminates code duplication in retry logic and ensures consistent
error handling across the application.

Author: Verenigingen Development Team
Created: 2025-10-07
"""

from typing import Any, Callable, Dict, Optional

import frappe


def save_with_timestamp_retry(
    doc,
    max_retries: int = 1,
    fields_to_restore: Optional[Dict[str, Any]] = None,
    field_restore_callback: Optional[Callable] = None,
) -> bool:
    """
    Save document with automatic retry on timestamp mismatch.

    This utility handles the common pattern of:
    1. Try to save document
    2. On TimestampMismatchError, reload document
    3. Restore fields that were set but wiped by reload
    4. Retry save once

    Args:
        doc: Document to save
        max_retries: Number of retries (default 1)
        fields_to_restore: Dict of {field_name: value} to restore after reload
        field_restore_callback: Callable that restores fields after reload
                               (alternative to fields_to_restore dict)

    Returns:
        bool: True if save succeeded

    Raises:
        frappe.TimestampMismatchError: If all retries exhausted
        Exception: Any other save errors

    Example:
        ```python
        # Simple field restoration
        save_with_timestamp_retry(
            member,
            fields_to_restore={
                'current_membership_plan': membership.name,
                'current_dues_schedule': dues_schedule,
                'application_invoice': invoice.name
            }
        )

        # Complex restoration with callback
        def restore_fields(doc):
            doc.current_membership_plan = membership.name
            doc.current_dues_schedule = dues_schedule
            update_member_duration_fields(doc)  # Complex calculation
            doc.application_invoice = invoice.name

        save_with_timestamp_retry(member, field_restore_callback=restore_fields)
        ```

    Design Notes:
        - Supports both simple field restoration (dict) and complex (callback)
        - Logs all retry attempts for debugging
        - Preserves original exception if retries exhausted
        - Thread-safe (no global state)
    """
    for attempt in range(max_retries + 1):
        try:
            doc.save()
            if attempt > 0:
                frappe.logger().info(
                    f"Document save succeeded on retry attempt {attempt} for "
                    f"{doc.doctype}:{doc.name or 'NEW'}"
                )
            return True

        except frappe.TimestampMismatchError:
            if attempt >= max_retries:
                frappe.logger().error(
                    f"Timestamp mismatch save failed after {max_retries + 1} attempts for "
                    f"{doc.doctype}:{doc.name or 'NEW'}"
                )
                raise

            frappe.logger().info(
                f"Timestamp mismatch saving {doc.doctype}:{doc.name or 'NEW'}, "
                f"retrying (attempt {attempt + 1}/{max_retries})"
            )

            # Reload to get latest version
            doc.reload()

            # Restore fields that were set but wiped by reload
            if field_restore_callback:
                # Use callback for complex restoration logic
                field_restore_callback(doc)
            elif fields_to_restore:
                # Simple field restoration from dict
                for field, value in fields_to_restore.items():
                    # Only restore non-None values unless explicitly set to None
                    if value is not None or field in fields_to_restore:
                        setattr(doc, field, value)

    # Should never reach here, but for type safety
    return False


def save_with_rollback(
    doc,
    rollback_docs: Optional[list] = None,
    max_retries: int = 1,
    fields_to_restore: Optional[Dict[str, Any]] = None,
    field_restore_callback: Optional[Callable] = None,
) -> bool:
    """
    Save document with automatic rollback of related documents if save fails.

    Useful for coordinated saves where multiple documents must be consistent.
    If the main document save fails, this will cancel/delete related documents.

    Args:
        doc: Main document to save
        rollback_docs: List of documents to rollback if main save fails
        max_retries: Number of retries for timestamp mismatch
        fields_to_restore: Fields to restore after reload (see save_with_timestamp_retry)
        field_restore_callback: Callback to restore fields (see save_with_timestamp_retry)

    Returns:
        bool: True if save succeeded

    Raises:
        Exception: Original save error after rollback attempt

    Example:
        ```python
        # Submit membership, but rollback if member save fails
        membership.submit()

        try:
            save_with_rollback(
                member,
                rollback_docs=[membership],
                fields_to_restore={'current_membership_plan': membership.name}
            )
        except Exception as e:
            # membership will be cancelled automatically
            frappe.throw("Failed to update member after membership creation")
        ```

    Design Notes:
        - Rollback attempts are logged for audit
        - Rollback failures are logged but don't prevent exception propagation
        - Uses save_with_timestamp_retry internally
    """
    try:
        return save_with_timestamp_retry(
            doc,
            max_retries=max_retries,
            fields_to_restore=fields_to_restore,
            field_restore_callback=field_restore_callback,
        )

    except Exception as save_error:
        # Save failed, attempt to rollback related documents
        if rollback_docs:
            frappe.logger().error(
                f"Save failed for {doc.doctype}:{doc.name or 'NEW'}, "
                f"attempting rollback of {len(rollback_docs)} related document(s)"
            )

            for rollback_doc in rollback_docs:
                try:
                    if rollback_doc.docstatus == 1:
                        # Submitted document - cancel it
                        frappe.logger().warning(
                            f"Rolling back {rollback_doc.doctype}:{rollback_doc.name} via cancel"
                        )
                        rollback_doc.cancel()

                    elif rollback_doc.docstatus == 0 and rollback_doc.name:
                        # Draft document - delete it
                        frappe.logger().warning(
                            f"Rolling back {rollback_doc.doctype}:{rollback_doc.name} via delete"
                        )
                        rollback_doc.delete()

                except Exception as rollback_error:
                    # Log rollback failure but don't prevent original exception
                    frappe.log_error(
                        f"Failed to rollback {rollback_doc.doctype}:{rollback_doc.name}: "
                        f"{str(rollback_error)}",
                        "Document Rollback Failed",
                    )

        # Re-raise original save error
        raise save_error
