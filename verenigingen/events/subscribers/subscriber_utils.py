"""
Shared utilities for event subscriber handlers.

Provides safe document retrieval and bulk import detection
used across chapter, member, and team subscriber modules.
"""

import frappe


def get_doc_if_exists(doctype, name, log_prefix="Subscriber"):
    """Get document with existence check and warning log.

    Returns None with a warning log if the document doesn't exist yet
    (common during background job processing before commit).

    Args:
        doctype: Frappe DocType name
        name: Document name/ID
        log_prefix: Prefix for log messages

    Returns:
        Document object or None
    """
    if not frappe.db.exists(doctype, name):
        frappe.logger("events").warning(
            f"Cannot process {log_prefix} - {doctype} {name} not yet committed to database"
        )
        return None
    return frappe.get_doc(doctype, name)


def should_skip_for_bulk(is_bulk_import=False):
    """Check if event processing should be skipped during bulk imports.

    Checks both the explicit parameter (reliable cross-process) and
    Frappe flags (backwards compatibility).

    Args:
        is_bulk_import: Explicit bulk import flag from event data

    Returns:
        True if processing should be skipped
    """
    return is_bulk_import or frappe.flags.in_import or getattr(frappe.flags, "in_bulk_import", False)
