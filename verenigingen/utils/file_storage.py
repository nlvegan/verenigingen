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

    Args:
        component: Raw path component

    Returns:
        Sanitized path component safe for filesystem use
    """
    if not component:
        return "unknown"

    # Remove directory traversal sequences and path separators
    sanitized = str(component).replace("..", "").replace("/", "").replace("\\", "")

    # Use frappe.scrub for consistent naming
    sanitized = frappe.scrub(sanitized).replace("_", "-")

    # Ensure result isn't empty after sanitization
    if not sanitized or sanitized.strip() == "":
        return "unknown"

    return sanitized


def _create_file_record(
    file_url: str, filename: str, is_private: int, attached_to_doctype: str, attached_to_name: str
):
    """
    Create File DocType record for permission management.

    This ensures Frappe's permission system knows about the file and can control access.
    Without this record, files will return "Forbidden" errors even to authorized users.

    Args:
        file_url: File URL path
        filename: Original filename
        is_private: Whether file is private
        attached_to_doctype: Parent DocType (e.g., "Chapter")
        attached_to_name: Parent document name
    """
    try:
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
        file_doc.insert(ignore_permissions=True)

        frappe.logger().info(f"Created File record for chapter document: {file_url}")
        return file_doc.name

    except Exception as e:
        # Log error but don't fail the file save operation
        frappe.log_error(
            f"Failed to create File record for {file_url}: {str(e)}",
            "Chapter Document File Record Creation Error",
        )
        return None


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

    # Build path: documents/chapters/{chapter}/{category}/{year}/{filename}
    relative_path = os.path.join("documents", "chapters", safe_chapter, safe_category, safe_year, filename)

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
    _create_file_record(
        file_url=file_url,
        filename=filename,
        is_private=is_private,
        attached_to_doctype="Chapter",
        attached_to_name=chapter_name,
    )

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
            _create_file_record(
                file_url=new_file_url,
                filename=filename,
                is_private=is_private,
                attached_to_doctype="Chapter",
                attached_to_name=chapter_name,
            )

        return new_file_url

    except Exception as e:
        error_msg = f"Failed to organize file into hierarchical structure. File: {file_url}, Error: {str(e)}"
        frappe.log_error(
            f"{error_msg}\n\nChapter: {chapter_name}\nCategory: {category}\nYear: {year}",
            "Board Document File Organization Error",
        )
        # Return original URL so document can still save successfully
        # The file remains in its original location
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
