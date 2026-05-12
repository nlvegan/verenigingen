# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Hierarchical file storage utilities for board documents
"""

import os

import frappe
from frappe.utils import get_files_path
from frappe.utils.file_manager import save_file_on_filesystem


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
    file_url: str, filename: str, is_private: int, attached_to_doctype: str, attached_to_name: str
):
    """
    Create File DocType record for permission management.

    This ensures Frappe's permission system knows about the file and can control access.
    Without this record, files will return "Forbidden" errors even to authorized users.

    Security Note: This function respects Frappe's permission system and will FAIL
    if the user lacks permission. Callers must handle cleanup of any files already
    saved to disk.

    Args:
        file_url: File URL path
        filename: Original filename
        is_private: Whether file is private
        attached_to_doctype: Parent DocType (e.g., "Chapter", "Organization Document")
        attached_to_name: Parent document name

    Returns:
        File record name if created successfully

    Raises:
        frappe.PermissionError: If user lacks permission to create File records
        FileRecordCreationError: If record creation fails for other reasons
    """
    # Check if File record already exists
    existing_file = frappe.db.exists("File", {"file_url": file_url})
    if existing_file:
        frappe.logger().debug(f"File record already exists for {file_url}")
        return existing_file

    # Create new File record
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": filename,
            "file_url": file_url,
            "is_private": is_private,
            "attached_to_doctype": attached_to_doctype,
            "attached_to_name": attached_to_name,
            "folder": "Home/Attachments",  # Default folder for organized files
        }
    )

    # Insert without triggering file system operations (file already saved)
    file_doc.flags.ignore_file_validate = True

    try:
        file_doc.insert()
        frappe.logger().info(f"Created File record for document: {file_url}")
        return file_doc.name
    except frappe.PermissionError:
        # Log security event for audit trail
        _log_file_permission_event(
            event_type="file_record_permission_denied",
            file_url=file_url,
            attached_to_doctype=attached_to_doctype,
            attached_to_name=attached_to_name,
        )
        # Re-raise with context - caller must clean up file on disk
        raise frappe.PermissionError(
            f"Permission denied creating File record for {file_url}. "
            f"User {frappe.session.user} lacks write permission on File DocType."
        )
    except Exception as e:
        # Log and re-raise - caller must clean up file on disk
        frappe.log_error(
            f"Failed to create File record for {file_url}: {str(e)}",
            "Document File Record Creation Error",
        )
        raise FileRecordCreationError(f"Failed to create File record for {file_url}: {str(e)}") from e


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
        dict with file_url and file_name
    """
    # Get hierarchical path
    relative_path = get_chapter_document_path(chapter_name, category, year, filename)

    # Determine base directory
    if is_private:
        base_path = os.path.join(get_files_path(is_private=1), relative_path)
        file_url = f"/private/files/{relative_path}"
    else:
        base_path = os.path.join(get_files_path(is_private=0), relative_path)
        file_url = f"/files/{relative_path}"

    # Create directory structure if it doesn't exist
    directory = os.path.dirname(base_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    # Save file to disk
    if hasattr(content, "read"):
        # File object
        with open(base_path, "wb") as f:
            f.write(content.read())
    else:
        # Bytes content
        with open(base_path, "wb") as f:
            f.write(content)

    # Create File DocType record for permission management
    # If this fails, clean up the file we just saved
    try:
        _create_file_record(
            file_url=file_url,
            filename=filename,
            is_private=is_private,
            attached_to_doctype="Chapter",
            attached_to_name=chapter_name,
        )
    except (frappe.PermissionError, FileRecordCreationError):
        # Clean up orphaned file - suppress cleanup errors to preserve original exception
        try:
            os.remove(base_path)
        except (FileNotFoundError, OSError):
            pass  # File already gone or locked - continue raising original error
        raise

    return {"file_name": filename, "file_url": file_url}


def organize_existing_chapter_document(file_url: str, chapter_name: str, category: str, year: str) -> str:
    """
    Move an existing file to hierarchical storage structure.

    Args:
        file_url: Current file URL
        chapter_name: Chapter name
        category: Document category
        year: Document year

    Returns:
        New file URL
    """
    if not file_url:
        return file_url

    # Skip if already in hierarchical structure
    if "/documents/chapters/" in file_url:
        return file_url

    try:
        # Get current file path
        if file_url.startswith("/private/files/"):
            current_path = file_url.replace("/private/files/", "")
            is_private = 1
            base_dir = get_files_path(is_private=1)
        elif file_url.startswith("/files/"):
            current_path = file_url.replace("/files/", "")
            is_private = 0
            base_dir = get_files_path(is_private=0)
        else:
            return file_url

        current_full_path = os.path.join(base_dir, current_path)

        # Check if file exists
        if not os.path.exists(current_full_path):
            frappe.log_error(f"File not found for organization: {current_full_path}")
            return file_url

        # Get filename
        filename = os.path.basename(current_path)

        # Generate new path
        relative_path = get_chapter_document_path(chapter_name, category, year, filename)
        new_full_path = os.path.join(base_dir, relative_path)

        # Create directory structure
        new_directory = os.path.dirname(new_full_path)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory, exist_ok=True)

        # Move file
        os.rename(current_full_path, new_full_path)

        # Determine new URL
        if is_private:
            new_file_url = f"/private/files/{relative_path}"
        else:
            new_file_url = f"/files/{relative_path}"

        # Update or create File DocType record
        existing_file = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if existing_file:
            # Update existing File record with new URL
            frappe.db.set_value("File", existing_file, "file_url", new_file_url, update_modified=False)
            frappe.logger().info(f"Updated File record {existing_file} with new URL: {new_file_url}")
        else:
            # Create new File record if none exists
            # If this fails, move file back to original location
            try:
                _create_file_record(
                    file_url=new_file_url,
                    filename=filename,
                    is_private=is_private,
                    attached_to_doctype="Chapter",
                    attached_to_name=chapter_name,
                )
            except (frappe.PermissionError, FileRecordCreationError) as e:
                # Attempt rollback - suppress filesystem errors to preserve original exception
                try:
                    os.rename(new_full_path, current_full_path)
                except OSError as rollback_error:
                    frappe.log_error(
                        f"Rollback failed after permission error: {rollback_error}\n"
                        f"Original error: {e}\n"
                        f"File may be at: {new_full_path}",
                        "Critical: File Organization Rollback Failed",
                    )
                raise

        return new_file_url

    except (frappe.PermissionError, FileRecordCreationError):
        # Permission/creation errors should propagate - no silent failures
        raise
    except OSError as e:
        # Filesystem errors during organization are non-security failures
        # Log and return original URL so document save can proceed
        frappe.log_error(
            f"Filesystem error organizing chapter document: {str(e)}\n\n"
            f"File: {file_url}\nChapter: {chapter_name}\nCategory: {category}\nYear: {year}",
            "Chapter Document File Organization Error",
        )
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
        dict with file_url and file_name
    """
    # Get hierarchical path
    relative_path = get_organization_document_path(
        organization_type, organization_name, category, year, filename
    )

    # Determine base directory
    if is_private:
        base_path = os.path.join(get_files_path(is_private=1), relative_path)
        file_url = f"/private/files/{relative_path}"
    else:
        base_path = os.path.join(get_files_path(is_private=0), relative_path)
        file_url = f"/files/{relative_path}"

    # Create directory structure if it doesn't exist
    directory = os.path.dirname(base_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    # Save file to disk
    if hasattr(content, "read"):
        # File object
        with open(base_path, "wb") as f:
            f.write(content.read())
    else:
        # Bytes content
        with open(base_path, "wb") as f:
            f.write(content)

    # Create File DocType record for permission management
    # Attach to Organization Document if name provided, otherwise to the organization
    if document_name:
        attached_to_doctype = "Organization Document"
        attached_to_name = document_name
    else:
        attached_to_doctype = organization_type
        attached_to_name = organization_name

    # If record creation fails, clean up the file we just saved
    try:
        _create_file_record(
            file_url=file_url,
            filename=filename,
            is_private=is_private,
            attached_to_doctype=attached_to_doctype,
            attached_to_name=attached_to_name,
        )
    except (frappe.PermissionError, FileRecordCreationError):
        # Clean up orphaned file - suppress cleanup errors to preserve original exception
        try:
            os.remove(base_path)
        except (FileNotFoundError, OSError):
            pass  # File already gone or locked - continue raising original error
        raise

    return {"file_name": filename, "file_url": file_url}


def organize_organization_document(
    file_url: str, organization_type: str, organization_name: str, category: str, year: str
) -> str:
    """
    Move an existing file to hierarchical storage structure for any organization type.

    Args:
        file_url: Current file URL
        organization_type: Type of organization (Chapter, Team, Movement)
        organization_name: Name of the organization
        category: Document category
        year: Document year

    Returns:
        New file URL
    """
    if not file_url:
        return file_url

    # Determine the expected path pattern for this org type
    org_type_path = f"/{organization_type.lower()}s/"

    # Skip if already in hierarchical structure for this org type
    if "/documents/" in file_url and org_type_path in file_url:
        return file_url

    try:
        # Get current file path
        if file_url.startswith("/private/files/"):
            current_path = file_url.replace("/private/files/", "")
            is_private = 1
            base_dir = get_files_path(is_private=1)
        elif file_url.startswith("/files/"):
            current_path = file_url.replace("/files/", "")
            is_private = 0
            base_dir = get_files_path(is_private=0)
        else:
            return file_url

        current_full_path = os.path.join(base_dir, current_path)

        # Check if file exists
        if not os.path.exists(current_full_path):
            frappe.log_error(
                f"File not found for organization: {current_full_path}",
                "Organization Document File Not Found",
            )
            return file_url

        # Get filename
        filename = os.path.basename(current_path)

        # Generate new path
        relative_path = get_organization_document_path(
            organization_type, organization_name, category, year, filename
        )
        new_full_path = os.path.join(base_dir, relative_path)

        # Create directory structure
        new_directory = os.path.dirname(new_full_path)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory, exist_ok=True)

        # Move file
        os.rename(current_full_path, new_full_path)

        # Determine new URL
        if is_private:
            new_file_url = f"/private/files/{relative_path}"
        else:
            new_file_url = f"/files/{relative_path}"

        # Update or create File DocType record
        existing_file = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if existing_file:
            # Update existing File record with new URL
            frappe.db.set_value("File", existing_file, "file_url", new_file_url, update_modified=False)
            frappe.logger().info(f"Updated File record {existing_file} with new URL: {new_file_url}")
        else:
            # Create new File record if none exists
            # If this fails, move file back to original location
            try:
                _create_file_record(
                    file_url=new_file_url,
                    filename=filename,
                    is_private=is_private,
                    attached_to_doctype=organization_type,
                    attached_to_name=organization_name,
                )
            except (frappe.PermissionError, FileRecordCreationError) as e:
                # Attempt rollback - suppress filesystem errors to preserve original exception
                try:
                    os.rename(new_full_path, current_full_path)
                except OSError as rollback_error:
                    frappe.log_error(
                        f"Rollback failed after permission error: {rollback_error}\n"
                        f"Original error: {e}\n"
                        f"File may be at: {new_full_path}",
                        "Critical: File Organization Rollback Failed",
                    )
                raise

        return new_file_url

    except (frappe.PermissionError, FileRecordCreationError):
        # Permission/creation errors should propagate - no silent failures
        raise
    except OSError as e:
        # Filesystem errors during organization are non-security failures
        # Log and return original URL so document save can proceed
        frappe.log_error(
            f"Filesystem error organizing organization document: {str(e)}\n\n"
            f"File: {file_url}\nOrganization Type: {organization_type}\n"
            f"Organization: {organization_name}\nCategory: {category}\nYear: {year}",
            "Organization Document File Organization Error",
        )
        return file_url
