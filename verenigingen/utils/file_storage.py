# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Hierarchical file storage utilities for board documents
"""

import os

import frappe


def sanitize_path_component(component: str) -> str:
    """
    Sanitize a path component to prevent directory traversal attacks.

    Security features:
    - Iteratively removes traversal sequences (handles .... -> .. bypass)
    - Removes null bytes that could truncate paths
    - Normalizes Unicode to prevent homograph attacks
    - Only allows alphanumeric characters, dashes, and spaces
    - Uses frappe.scrub for consistent naming

    Args:
        component: Raw path component

    Returns:
        Sanitized path component safe for filesystem use
    """
    import re
    import unicodedata

    if not component:
        return "unknown"

    # Convert to string
    sanitized = str(component)

    # Remove null bytes (can truncate paths in some filesystems)
    sanitized = sanitized.replace("\x00", "")

    # Normalize Unicode to NFC form (prevents homograph attacks with lookalike chars)
    sanitized = unicodedata.normalize("NFC", sanitized)

    # Iteratively remove directory traversal sequences and path separators
    # This handles cases like "...." which become ".." after single replacement
    prev_len = -1
    while len(sanitized) != prev_len:
        prev_len = len(sanitized)
        sanitized = sanitized.replace("..", "").replace("/", "").replace("\\", "")

    # Use frappe.scrub for consistent naming (converts spaces to underscores, lowercases)
    sanitized = frappe.scrub(sanitized).replace("_", "-")

    # Additional validation: only allow alphanumeric, dash, and remove other special chars
    # This prevents any remaining potentially dangerous characters
    sanitized = re.sub(r"[^a-zA-Z0-9\-]", "", sanitized)

    # Ensure result isn't empty after sanitization
    if not sanitized or sanitized.strip() == "":
        return "unknown"

    return sanitized


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize a filename for safe use as the leaf segment of a file path.

    Unlike sanitize_path_component (which is for directory segments and
    strips every dot), this preserves file extensions while preventing
    directory traversal: strips path separators, leading dots, null
    bytes, and `..` sequences. Falls back to 'unknown' when empty.
    """
    import os
    import re
    import unicodedata

    if not filename:
        return "unknown"

    name = str(filename).replace("\x00", "")
    name = unicodedata.normalize("NFC", name)

    # Strip any directory components — keep only the basename
    name = os.path.basename(name).replace("\\", "").replace("/", "")

    # Iteratively neutralise '..' sequences (handles '....' → '..' → '')
    prev_len = -1
    while len(name) != prev_len:
        prev_len = len(name)
        name = name.replace("..", "")

    # No hidden files, no trailing space (Windows hostile to both)
    name = name.lstrip(". ").rstrip(" .")

    # Conservative charset: alphanumerics + dot/dash/underscore/space
    name = re.sub(r"[^a-zA-Z0-9._\- ]", "", name)

    # Length cap, preserving extension when reasonable
    if len(name) > max_length:
        stem, ext = os.path.splitext(name)
        if ext and len(ext) < 16:
            name = stem[: max_length - len(ext)] + ext
        else:
            name = name[:max_length]

    return name or "unknown"


class FileRecordCreationError(Exception):
    """Raised when File DocType record creation fails."""

    pass


def _create_file_record(
    content, filename: str, is_private: int, attached_to_doctype: str, attached_to_name: str
):
    """
    Create a File DocType record (and store its bytes) via the framework.

    The file is stored by Frappe itself rather than written to a hierarchical path
    by hand. This is deliberate: Frappe's File doctype flattens every private file
    to ``/private/files/<basename>`` on insert (see
    ``File.handle_is_private_changed``), so a hand-built hierarchical ``file_url``
    never survives — it leaves the stored record pointing at a flattened URL that
    does not match, which both breaks dedup and (for private files) makes the
    document "Forbidden" because no File record covers the served URL. Letting the
    framework own storage gives a valid, permission-aware record whose ``file_url``
    is the URL the file is actually served from, and content-hash dedup for free.

    The logical hierarchy (organization / category / year) is preserved in the
    owning document's own fields, not in the on-disk path.

    Security Note: respects Frappe's permission system and will FAIL if the user
    lacks permission. The framework cleans up its own file on failure.

    Args:
        content: File content (bytes or a file-like object)
        filename: Original filename (already sanitized by the caller)
        is_private: Whether file is private
        attached_to_doctype: Parent DocType (e.g., "Chapter", "Organization Document")
        attached_to_name: Parent document name

    Returns:
        The inserted File document (its ``file_url`` is the real, served URL).

    Raises:
        frappe.PermissionError: If user lacks permission to create File records
        FileRecordCreationError: If record creation fails for other reasons
    """
    content_bytes = content.read() if hasattr(content, "read") else content

    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": filename,
            "content": content_bytes,
            "is_private": is_private,
            "attached_to_doctype": attached_to_doctype,
            "attached_to_name": attached_to_name,
            "folder": "Home/Attachments",
        }
    )

    try:
        file_doc.insert()
        frappe.logger().info(f"Created File record for document: {file_doc.file_url}")
        return file_doc
    except frappe.PermissionError:
        # Log security event for audit trail
        _log_file_permission_event(
            event_type="file_record_permission_denied",
            file_url=filename,
            attached_to_doctype=attached_to_doctype,
            attached_to_name=attached_to_name,
        )
        raise frappe.PermissionError(
            f"Permission denied creating File record for {filename}. "
            f"User {frappe.session.user} lacks write permission on File DocType."
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to create File record for {filename}: {str(e)}",
            "Document File Record Creation Error",
        )
        raise FileRecordCreationError(f"Failed to create File record for {filename}: {str(e)}") from e


def _log_file_permission_event(
    event_type: str, file_url: str, attached_to_doctype: str, attached_to_name: str
):
    """
    Log file-related security events for audit purposes.

    Args:
        event_type: Type of security event
        file_url: URL of the file
        attached_to_doctype: Parent DocType
        attached_to_name: Parent document name
    """
    try:
        frappe.logger("security").info(
            f"File security event: {event_type} | "
            f"User: {frappe.session.user} | "
            f"File: {file_url} | "
            f"Parent: {attached_to_doctype}/{attached_to_name}"
        )
    except Exception:
        pass  # Don't fail on logging errors


def get_chapter_document_path(chapter_name: str, category: str, year: str, filename: str) -> str:
    """
    Generate hierarchical file path for chapter documents.

    Pattern: /private/files/documents/chapters/{chapter}/{category}/{year}/{filename}

    Args:
        chapter_name: Name of the chapter
        category: Document category (e.g., "Policy", "Meeting Minutes")
        year: Document year (e.g., "2025")
        filename: Original filename

    Returns:
        Relative file path from site directory
    """
    # Sanitize path components to prevent directory traversal
    safe_chapter = sanitize_path_component(chapter_name)
    safe_category = sanitize_path_component(category)
    safe_year = sanitize_path_component(str(year))
    safe_filename = sanitize_filename(filename)

    # Build path: documents/chapters/{chapter}/{category}/{year}/{filename}
    relative_path = os.path.join(
        "documents", "chapters", safe_chapter, safe_category, safe_year, safe_filename
    )

    return relative_path


def save_chapter_document(
    content, filename: str, chapter_name: str, category: str, year: str, is_private: int = 1
) -> dict:
    """
    Save a chapter document to hierarchical storage.

    Args:
        content: File content (bytes or file object)
        filename: Original filename
        chapter_name: Chapter name
        category: Document category
        year: Document year
        is_private: Whether file is private (default: 1)

    Returns:
        dict with file_url (the real, served URL), file_name and the File record name
    """
    # Let the framework store the file and register the permission record. We pass
    # the content rather than writing a hierarchical path by hand because Frappe
    # flattens private files to /private/files/<basename> on insert, so a hand-built
    # hierarchical path would never survive (see _create_file_record). The
    # chapter/category/year hierarchy is metadata on the owning document, not the
    # on-disk path. The framework cleans up its own file on failure.
    file_doc = _create_file_record(
        content=content,
        filename=sanitize_filename(filename),
        is_private=is_private,
        attached_to_doctype="Chapter",
        attached_to_name=chapter_name,
    )

    return {"file_name": file_doc.file_name, "file_url": file_doc.file_url, "name": file_doc.name}


def organize_existing_chapter_document(file_url: str, chapter_name: str, category: str, year: str) -> str:
    """
    Return the file URL unchanged (no-op).

    This previously moved an existing file into a hierarchical on-disk path and
    rewrote its File record. That approach cannot work: Frappe's File doctype
    flattens private files to /private/files/<basename> on insert, so the
    hierarchical move left the file without a matching File record (Forbidden) and
    created a second, flattened copy on disk. Files now stay in the framework's
    flat store with a valid record; the chapter/category/year hierarchy is metadata
    on the owning document. The signature is kept for backward compatibility.
    """
    return file_url


def cleanup_empty_directories(base_path: str):
    """
    Remove empty directories after file reorganization.

    Args:
        base_path: Base directory to clean up
    """
    try:
        for root, dirs, files in os.walk(base_path, topdown=False):
            for directory in dirs:
                dir_path = os.path.join(root, directory)
                try:
                    if not os.listdir(dir_path):  # Directory is empty
                        os.rmdir(dir_path)
                except Exception:
                    pass  # Skip if can't remove
    except Exception as e:
        frappe.log_error(f"Error cleaning up directories: {str(e)}")


# =============================================================================
# Organization Document Storage (Unified for Chapter/Team/Movement)
# =============================================================================


def get_organization_document_path(
    organization_type: str, organization_name: str, category: str, year: str, filename: str
) -> str:
    """
    Generate hierarchical file path for organization documents.

    Pattern: /documents/{org_type}s/{org_name}/{category}/{year}/{filename}

    Args:
        organization_type: Type of organization (Chapter, Team, Movement)
        organization_name: Name of the organization
        category: Document category (e.g., "Policy", "Meeting Minutes")
        year: Document year (e.g., "2025")
        filename: Original filename

    Returns:
        Relative file path from site files directory
    """
    # Sanitize path components to prevent directory traversal
    safe_org_type = sanitize_path_component(organization_type).lower() + "s"  # chapters, teams, movements
    safe_org_name = sanitize_path_component(organization_name)
    safe_category = sanitize_path_component(category)
    safe_year = sanitize_path_component(str(year))
    safe_filename = sanitize_filename(filename)

    # Build path: documents/{org_type}s/{org_name}/{category}/{year}/{filename}
    relative_path = os.path.join(
        "documents", safe_org_type, safe_org_name, safe_category, safe_year, safe_filename
    )

    return relative_path


def save_organization_document(
    content,
    filename: str,
    organization_type: str,
    organization_name: str,
    category: str,
    year: str,
    is_private: int = 1,
    document_name: str = None,
) -> dict:
    """
    Save an organization document to hierarchical storage.

    Args:
        content: File content (bytes or file object)
        filename: Original filename
        organization_type: Type of organization (Chapter, Team, Movement)
        organization_name: Name of the organization
        category: Document category
        year: Document year
        is_private: Whether file is private (default: 1)
        document_name: Optional Organization Document name for attachment

    Returns:
        dict with file_url (the real, served URL), file_name and the File record name
    """
    # Attach to the Organization Document if a name is provided, otherwise to the
    # organization itself.
    if document_name:
        attached_to_doctype = "Organization Document"
        attached_to_name = document_name
    else:
        attached_to_doctype = organization_type
        attached_to_name = organization_name

    # Let the framework store the file and register the permission record. We pass
    # the content rather than writing a hierarchical path by hand because Frappe
    # flattens private files to /private/files/<basename> on insert, so a hand-built
    # hierarchical path would never survive (see _create_file_record) — it would
    # leave the file "Forbidden" for lack of a matching File record. The
    # org/category/year hierarchy is metadata on the Organization Document, not the
    # on-disk path. The framework cleans up its own file on failure.
    file_doc = _create_file_record(
        content=content,
        filename=sanitize_filename(filename),
        is_private=is_private,
        attached_to_doctype=attached_to_doctype,
        attached_to_name=attached_to_name,
    )

    return {"file_name": file_doc.file_name, "file_url": file_doc.file_url, "name": file_doc.name}


def organize_organization_document(
    file_url: str, organization_type: str, organization_name: str, category: str, year: str
) -> str:
    """
    Return the file URL unchanged (no-op).

    This previously moved an existing file into a hierarchical on-disk path and
    rewrote its File record. That approach cannot work: Frappe's File doctype
    flattens private files to /private/files/<basename> on insert, so the
    hierarchical move left the file without a matching File record (Forbidden) and
    created a second, flattened copy on disk. Files now stay in the framework's
    flat store with a valid record; the org/category/year hierarchy is metadata on
    the Organization Document. The signature is kept for backward compatibility.
    """
    return file_url
