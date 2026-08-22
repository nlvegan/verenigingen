# History Manager Utilities - Shared patterns for history tracking managers
#
# Provides common utilities for:
# - ChapterMembershipHistoryManager (Member -> chapter_membership_history)
# - AssignmentHistoryManager (Volunteer -> assignment_history)
#
# These utilities ensure consistent behavior across history tracking operations.

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import frappe

from verenigingen.utils.safe_error_logging import safe_log_error
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


class HistoryOperationResult:
    """Result of a history operation with success status and details."""

    def __init__(self, success: bool, message: str = "", errors: List[str] = None):
        self.success = success
        self.message = message
        self.errors = errors or []

    def __bool__(self):
        return self.success


def ensure_doc_exists(doctype: str, name: str, operation_name: str) -> bool:
    """
    Check if a document exists before attempting operations.

    Args:
        doctype: Document type to check
        name: Document name to check
        operation_name: Description of the operation (for logging)

    Returns:
        bool: True if document exists, False otherwise
    """
    if not frappe.db.exists(doctype, name):
        frappe.logger().warning(f"Cannot {operation_name} - {doctype} {name} no longer exists")
        return False
    return True


def check_duplicate_entry(
    entries: List[Any], match_fields: Dict[str, Any], status_field: str = "status"
) -> Optional[Any]:
    """
    Check for duplicate entries in a child table based on field matching.

    Args:
        entries: List of child table entries to search
        match_fields: Dictionary of field_name -> value to match
        status_field: Name of the status field (default: "status")

    Returns:
        The matching entry if found, None otherwise
    """
    for entry in entries or []:
        all_match = True
        for field_name, expected_value in match_fields.items():
            entry_value = getattr(entry, field_name, None)
            # Handle date comparisons by converting to string
            if str(entry_value) != str(expected_value):
                all_match = False
                break
        if all_match:
            return entry
    return None


def find_entry_by_criteria(
    entries: List[Any], criteria: Dict[str, Any], status_values: List[str] = None
) -> Optional[Any]:
    """
    Find an entry matching criteria with optional status filtering.

    Args:
        entries: List of child table entries to search
        criteria: Dictionary of field_name -> value to match
        status_values: Optional list of acceptable status values

    Returns:
        The matching entry if found, None otherwise
    """
    for entry in entries or []:
        all_match = True
        for field_name, expected_value in criteria.items():
            entry_value = getattr(entry, field_name, None)
            if str(entry_value) != str(expected_value):
                all_match = False
                break

        if all_match:
            if status_values is None:
                return entry
            entry_status = getattr(entry, "status", None)
            if entry_status in status_values:
                return entry

    return None


@contextmanager
def recursion_guard(doc: Any, flag_name: str):
    """
    Context manager to prevent recursive updates on a document.

    Usage:
        with recursion_guard(volunteer, "_updating_assignment_history"):
            # Do operations that might trigger recursive calls
            pass

    Args:
        doc: The document to guard
        flag_name: Name of the flag attribute to set

    Yields:
        bool: True if this is the first entry (not recursive), False if recursive
    """
    if getattr(doc, flag_name, False):
        frappe.logger().info(f"Skipping recursive history update for {doc.doctype} {doc.name}")
        yield False
        return

    setattr(doc, flag_name, True)
    try:
        yield True
    finally:
        setattr(doc, flag_name, False)


def safe_child_table_update(
    doc: Any,
    child_table_name: str,
    justification: str,
    doctype_permission: str,
    auto_cleanup: bool = False,
) -> HistoryOperationResult:
    """
    Safely update a specific child table without triggering full document validation.

    Uses Frappe's native update_child_table() method which only syncs the specified
    child table, avoiding validation errors from unrelated child tables.

    If the update fails with a validation error and auto_cleanup is True, attempts
    to clean up broken link references and retry once.

    Args:
        doc: Parent document containing the child table
        child_table_name: Name of the child table field to update
        justification: Description of the operation (for logging)
        doctype_permission: Permission to check (e.g., "Member:write")
        auto_cleanup: If True, attempt cleanup and retry on validation errors (default: False)

    Returns:
        HistoryOperationResult with success status and any errors
    """
    try:
        # Validate permission
        doctype, perm = doctype_permission.split(":")
        if not frappe.has_permission(doctype, perm, doc.name):
            # Allow system user for automated operations
            if frappe.session.user != "Administrator" and not frappe.flags.in_test:
                return HistoryOperationResult(
                    success=False,
                    message="Permission denied",
                    errors=[f"User {frappe.session.user} does not have {perm} permission on {doctype}"],
                )

        # Use Frappe's native update_child_table - only updates the specific child table
        doc.update_child_table(child_table_name)

        frappe.logger().debug(
            f"Successfully updated {child_table_name} for {doc.doctype} {doc.name}: {justification}"
        )

        return HistoryOperationResult(success=True, message="Child table updated successfully")

    # #475: BaseHistoryManager._with_doc was given an `except NON_RESUMABLE_DB_ERRORS: raise`
    # by #460 precisely so its callers would see these -- but that guard sits OUTSIDE this
    # helper, which is where _with_doc delegates the actual write. So it never fired for the
    # one call it was written to protect. This guard must come first: a 1205/1213 is not a
    # ValidationError (it derives straight from Exception), so it would otherwise fall
    # through to the trailing catch-all and be returned as an ordinary failed result,
    # indistinguishable from a broken link.
    except NON_RESUMABLE_DB_ERRORS:
        raise

    except frappe.TimestampMismatchError as e:
        # Handle concurrent modification
        return HistoryOperationResult(
            success=False,
            message="Concurrent modification detected",
            errors=[f"Document was modified by another process: {str(e)}"],
        )

    except (frappe.LinkValidationError, frappe.ValidationError) as e:
        error_msg = str(e)

        # Check if this looks like a broken link error and auto_cleanup is enabled
        is_link_error = (
            "Could not find" in error_msg
            or "does not exist" in error_msg.lower()
            or "must be set first" in error_msg.lower()
        )

        if auto_cleanup and is_link_error:
            # Verify the error relates to our child table before cleanup
            child_doctype = get_child_table_doctype(doc, child_table_name)
            error_is_ours = error_relates_to_child_table(error_msg, child_doctype)

            if not error_is_ours:
                frappe.logger().warning(
                    f"Validation error does not appear to relate to {child_table_name} "
                    f"(child doctype: {child_doctype}), skipping cleanup: {error_msg}"
                )
                # Fall through to error return below
            else:
                frappe.logger().warning(
                    f"Link validation error in {child_table_name}, attempting cleanup: {error_msg}"
                )

                # Attempt to clean up broken links in the specific child table
                cleanup_result = cleanup_child_table_broken_links(
                    doc, child_table_name, remove_broken_rows=True
                )

                if cleanup_result.success and "No broken links found" not in cleanup_result.message:
                    # Cleanup did something, retry the update
                    frappe.logger().info(f"Cleanup performed: {cleanup_result.message}. Retrying update...")

                    try:
                        doc.update_child_table(child_table_name)
                        frappe.logger().info(
                            f"Successfully updated {child_table_name} after cleanup for {doc.doctype} {doc.name}"
                        )
                        return HistoryOperationResult(
                            success=True,
                            message=f"Child table updated after cleanup: {cleanup_result.message}",
                        )
                    except NON_RESUMABLE_DB_ERRORS:
                        raise
                    except Exception as retry_error:
                        frappe.logger().error(f"Retry after cleanup still failed: {str(retry_error)}")
                        return HistoryOperationResult(
                            success=False,
                            message="Update failed even after cleanup",
                            errors=[f"Original: {error_msg}", f"After cleanup: {str(retry_error)}"],
                        )

        # No cleanup attempted or cleanup didn't help
        frappe.logger().error(
            f"Failed to update {child_table_name} for {doc.doctype} {doc.name}: {error_msg}"
        )
        return HistoryOperationResult(success=False, message="Validation failed", errors=[error_msg])

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(
            f"Failed to update {child_table_name} for {doc.doctype} {doc.name}: {error_msg}"
        )
        return HistoryOperationResult(success=False, message="Update failed", errors=[error_msg])


def log_history_error(title: str, message: str, include_traceback: bool = False):
    """
    Log a history operation error using the safe error logging utility.

    Args:
        title: Short title for the error
        message: Detailed error message
        include_traceback: Whether to include the current traceback
    """
    if include_traceback:
        import traceback

        message = f"{message}\n\nTraceback:\n{traceback.format_exc()}"

    safe_log_error(title, message)


def get_request_cache(cache_name: str) -> set:
    """
    Get or create a request-level cache for deduplication.

    This prevents duplicate operations within the same request when multiple
    code paths call the same history method.

    Args:
        cache_name: Name of the cache attribute on frappe.local

    Returns:
        The cache set (created if it doesn't exist)
    """
    if not hasattr(frappe.local, cache_name):
        setattr(frappe.local, cache_name, set())
    return getattr(frappe.local, cache_name)


def make_cache_key(*parts) -> str:
    """
    Create a cache key from multiple parts.

    Args:
        *parts: Values to combine into a cache key

    Returns:
        A pipe-separated string key
    """
    return "|".join(str(p) for p in parts)


def get_child_table_doctype(doc: Any, child_table_name: str) -> Optional[str]:
    """
    Get the DocType name for a child table.

    Args:
        doc: Parent document containing the child table
        child_table_name: Name of the child table field

    Returns:
        The child DocType name, or None if not found
    """
    # Try to get from existing rows
    child_table = getattr(doc, child_table_name, None)
    if child_table and len(child_table) > 0:
        return child_table[0].doctype

    # Try to get from parent meta
    try:
        parent_meta = frappe.get_meta(doc.doctype)
        for df in parent_meta.fields:
            if df.fieldname == child_table_name and df.fieldtype == "Table":
                return df.options
    except Exception:
        pass

    return None


def error_relates_to_child_table(error_msg: str, child_doctype: str) -> bool:
    """
    Check if a validation error message relates to a specific child table.

    This prevents cleanup of the wrong table when an error from a different
    child table is raised.

    Args:
        error_msg: The error message string
        child_doctype: The child DocType name to check against

    Returns:
        True if the error appears to relate to the child table, False otherwise
    """
    if not error_msg or not child_doctype:
        return False

    error_lower = error_msg.lower()
    doctype_lower = child_doctype.lower()

    # Check if the child doctype name appears in the error
    # This handles errors like "Could not find Row #11 in Chapter Membership History"
    if doctype_lower in error_lower:
        return True

    # Check for common error patterns with table reference
    # E.g., "in row 5 of chapter_membership_history"
    child_table_pattern = child_doctype.lower().replace(" ", "_")
    if child_table_pattern in error_lower:
        return True

    # Try to get field names from the child doctype and check if any appear in error
    try:
        child_meta = frappe.get_meta(child_doctype)
        link_fields = []

        for df in child_meta.fields:
            if df.fieldtype in ("Link", "Dynamic Link"):
                link_fields.append(df.fieldname)
                if df.options:
                    link_fields.append(df.options)

        # Check if any link field or its target doctype appears in error
        for field in link_fields:
            if field and field.lower() in error_lower:
                return True
    except Exception:
        pass

    # If we can't determine, be conservative and DENY cleanup
    # This prevents cleaning up the wrong table when uncertain
    # Only allow cleanup when we positively identify the error relates to our table
    return False


def cleanup_child_table_broken_links(
    doc: Any, child_table_name: str, remove_broken_rows: bool = True
) -> HistoryOperationResult:
    """
    Clean up broken link references in a child table.

    Identifies rows with Link or Dynamic Link fields pointing to non-existent
    documents and either removes those rows or clears the broken link values.

    Args:
        doc: Parent document containing the child table
        child_table_name: Name of the child table field
        remove_broken_rows: If True, remove entire row; if False, just clear the broken link

    Returns:
        HistoryOperationResult with details of cleanup performed
    """
    try:
        child_table = getattr(doc, child_table_name, None)
        if not child_table:
            return HistoryOperationResult(success=True, message="No child table entries to clean")

        # Get child table DocType meta
        if not child_table:
            return HistoryOperationResult(success=True, message="Empty child table")

        # Get the child DocType name from the first row or from meta
        child_doctype = None
        if child_table:
            child_doctype = child_table[0].doctype if child_table[0] else None

        if not child_doctype:
            # Try to get from parent meta
            parent_meta = frappe.get_meta(doc.doctype)
            for df in parent_meta.fields:
                if df.fieldname == child_table_name and df.fieldtype == "Table":
                    child_doctype = df.options
                    break

        if not child_doctype:
            return HistoryOperationResult(
                success=False, message="Could not determine child DocType", errors=["Unknown child DocType"]
            )

        child_meta = frappe.get_meta(child_doctype)

        # Find Link and Dynamic Link fields
        link_fields = []
        dynamic_link_fields = []

        for df in child_meta.fields:
            if df.fieldtype == "Link":
                link_fields.append({"fieldname": df.fieldname, "options": df.options})
            elif df.fieldtype == "Dynamic Link":
                dynamic_link_fields.append({"fieldname": df.fieldname, "options": df.options})

        rows_to_remove = []
        links_cleared = 0
        rows_checked = 0

        for row in child_table:
            rows_checked += 1
            row_has_broken_link = False

            # Check regular Link fields
            for link_field in link_fields:
                value = getattr(row, link_field["fieldname"], None)
                if value:
                    doctype = link_field["options"]
                    if not frappe.db.exists(doctype, value):
                        frappe.logger().warning(
                            f"Broken link in {child_doctype} row {row.idx}: "
                            f"{link_field['fieldname']}={value} ({doctype} does not exist)"
                        )
                        if remove_broken_rows:
                            row_has_broken_link = True
                        else:
                            setattr(row, link_field["fieldname"], None)
                            links_cleared += 1

            # Check Dynamic Link fields
            for dyn_link_field in dynamic_link_fields:
                value = getattr(row, dyn_link_field["fieldname"], None)
                doctype_field = dyn_link_field["options"]
                doctype = getattr(row, doctype_field, None)

                if value and doctype:
                    # Normal case: both value and doctype present
                    try:
                        if not frappe.db.exists(doctype, value):
                            frappe.logger().warning(
                                f"Broken dynamic link in {child_doctype} row {row.idx}: "
                                f"{dyn_link_field['fieldname']}={value} ({doctype} does not exist)"
                            )
                            if remove_broken_rows:
                                row_has_broken_link = True
                            else:
                                setattr(row, dyn_link_field["fieldname"], None)
                                setattr(row, doctype_field, None)
                                links_cleared += 1
                    except Exception as e:
                        # Invalid doctype or other error - treat as broken
                        frappe.logger().warning(
                            f"Could not validate dynamic link in {child_doctype} row {row.idx}: "
                            f"{dyn_link_field['fieldname']}={value}, doctype={doctype}: {str(e)}"
                        )
                        if remove_broken_rows:
                            row_has_broken_link = True
                        else:
                            setattr(row, dyn_link_field["fieldname"], None)
                            setattr(row, doctype_field, None)
                            links_cleared += 1
                elif value and not doctype:
                    # Orphaned dynamic link: has value but no doctype - definitely broken
                    frappe.logger().warning(
                        f"Orphaned dynamic link in {child_doctype} row {row.idx}: "
                        f"{dyn_link_field['fieldname']}={value} but {doctype_field} is empty"
                    )
                    if remove_broken_rows:
                        row_has_broken_link = True
                    else:
                        setattr(row, dyn_link_field["fieldname"], None)
                        links_cleared += 1

            if row_has_broken_link:
                rows_to_remove.append(row)

        # Remove broken rows
        rows_removed = 0
        if remove_broken_rows and rows_to_remove:
            for row in rows_to_remove:
                child_table.remove(row)
                rows_removed += 1

            # Resequence idx values to ensure they are consecutive (1, 2, 3, ...)
            # This prevents issues with Frappe's child table handling
            for new_idx, row in enumerate(child_table, start=1):
                row.idx = new_idx

        if rows_removed > 0 or links_cleared > 0:
            message = (
                f"Cleaned {child_table_name}: {rows_removed} rows removed, {links_cleared} links cleared"
            )
            frappe.logger().info(message)
            return HistoryOperationResult(success=True, message=message)
        else:
            return HistoryOperationResult(success=True, message="No broken links found")

    except Exception as e:
        error_msg = f"Error cleaning child table {child_table_name}: {str(e)}"
        frappe.logger().error(error_msg)
        return HistoryOperationResult(success=False, message="Cleanup failed", errors=[error_msg])
