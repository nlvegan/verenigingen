"""
Import Helpers

Shared utilities for CSV/data import processing.
Used by CSVImportBackgroundProcessor and DocType-specific import controllers.
"""

from typing import List

import frappe
from frappe.utils import now_datetime

# Maximum lines to persist in error log file (safety cap)
MAX_ERROR_LOG_LINES = 100000

# Maximum file size in bytes (5MB)
MAX_ERROR_LOG_SIZE = 5 * 1024 * 1024


def persist_full_error_log(
    error_log: List[str],
    doctype: str,
    docname: str,
    max_lines: int = MAX_ERROR_LOG_LINES,
    max_size: int = MAX_ERROR_LOG_SIZE,
) -> str:
    """
    Persist full error log as File attachment for audit purposes.

    This preserves complete error details that would otherwise be lost
    when truncating for UI display. The full log can be downloaded
    from the document's attachments.

    Args:
        error_log: List of error messages from import processing
        doctype: DocType to attach the file to
        docname: Document name to attach the file to
        max_lines: Maximum lines to include (default 100,000)
        max_size: Maximum file size in bytes (default 5MB)

    Returns:
        Filename of the created attachment, or empty string if no log created
    """
    if not error_log:
        return ""

    try:
        # Apply line cap for safety
        if len(error_log) > max_lines:
            truncated_log = error_log[:max_lines]
            truncation_note = (
                f"\n... truncated {len(error_log) - max_lines} additional errors (cap: {max_lines} lines)"
            )
        else:
            truncated_log = error_log
            truncation_note = ""

        # Generate timestamped filename with a random suffix. The timestamp
        # has second resolution, so two error logs persisted in the same
        # second would collide without the random suffix.
        timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
        unique_suffix = frappe.generate_hash(length=6)
        filename = f"import_errors_{timestamp}_{unique_suffix}.txt"

        # Build file content with header
        content_lines = [
            f"Full Error Log for {docname}",
            f"Generated: {now_datetime().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Errors: {len(error_log)}",
            "=" * 60,
            "",
        ]
        content_lines.extend(truncated_log)
        if truncation_note:
            content_lines.append(truncation_note)

        content = "\n".join(content_lines)

        # Apply size cap
        if len(content.encode("utf-8")) > max_size:
            # Truncate content to fit size limit
            content = content[: max_size - 100]  # Leave room for truncation message
            content += f"\n\n... file truncated (size limit: {max_size // 1024 // 1024}MB)"

        # Create File document attached to the import document
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": filename,
                "attached_to_doctype": doctype,
                "attached_to_name": docname,
                "content": content,
                "is_private": 1,
            }
        )
        # Security: Error log file attachment during import processing.
        # Import jobs run in background without user context. Error logs
        # are private files attached to the import document for debugging.
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        frappe.logger().info(f"Persisted full error log ({len(error_log)} entries) as {filename}")
        return filename

    # Deliberately swallowed: the only consumer (_default_finalize) uses the return
    # value solely to embed a filename in the truncated on-screen log. If the
    # attachment cannot be written the import outcome is unchanged, the first 100
    # error lines are still displayed, and the cause is on the logger. Failing the
    # whole import because an audit convenience failed would be worse.
    except Exception as e:  # swallow-ok: best-effort
        frappe.logger().error(f"Failed to persist full error log: {str(e)}")
        return ""


def truncate_error_log_for_display(
    error_log: List[str], max_lines: int = 100, full_log_filename: str = ""
) -> str:
    """
    Truncate error log for UI display while referencing the full log attachment.

    Args:
        error_log: Full list of error messages
        max_lines: Maximum lines to show in UI (default 100)
        full_log_filename: Filename of persisted full log (for reference in message)

    Returns:
        Truncated error log string suitable for UI display
    """
    if not error_log:
        return ""

    truncated = "\n".join(error_log[:max_lines])

    if len(error_log) > max_lines:
        remaining = len(error_log) - max_lines
        if full_log_filename:
            truncated += f"\n\n... and {remaining} more errors (see attached {full_log_filename})"
        else:
            truncated += f"\n\n... and {remaining} more errors"

    return truncated
