#!/usr/bin/env python3
"""
Fix Chapter Document File Permissions
======================================

This script creates missing File DocType records for chapter board documents.
Without these records, users get "Forbidden" errors when trying to access files.

The custom file storage system saves files directly to disk without creating
File records, which are needed for Frappe's permission system to work.

Usage:
    bench --site dev.veganisme.net execute "scripts.fix_chapter_document_permissions.create_missing_file_records"
"""

import frappe
from frappe import _


def create_missing_file_records(dry_run=False):
    """
    Create File DocType records for all chapter board documents.

    Args:
        dry_run: If True, only report what would be done without making changes
    """
    frappe.init_context()

    print("=" * 80)
    print("Chapter Document File Permission Fix")
    print("=" * 80)
    print()

    if dry_run:
        print("DRY RUN MODE - No changes will be made")
        print()

    # Get all chapters with board documents
    chapters = frappe.get_all("Chapter", fields=["name"])

    total_documents = 0
    files_created = 0
    files_skipped = 0
    errors = 0

    for chapter_data in chapters:
        chapter = frappe.get_doc("Chapter", chapter_data.name)

        if not chapter.board_documents:
            continue

        print(f"\nProcessing Chapter: {chapter.name}")
        print("-" * 80)

        for doc in chapter.board_documents:
            total_documents += 1

            if not doc.document_file:
                print(f"  ⚠️  Skipping '{doc.document_name}' - no file attached")
                files_skipped += 1
                continue

            # Check if File record already exists
            existing_file = frappe.db.exists("File", {"file_url": doc.document_file})

            if existing_file:
                print(f"  ✓  '{doc.document_name}' - File record already exists")
                files_skipped += 1
                continue

            # Determine if file is private
            is_private = 1 if doc.document_file.startswith("/private/") else 0

            if dry_run:
                print(f"  →  Would create File record for '{doc.document_name}'")
                print(f"     URL: {doc.document_file}")
                print(f"     Private: {is_private}")
                files_created += 1
            else:
                try:
                    # Create File record
                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": doc.document_name,
                        "file_url": doc.document_file,
                        "is_private": is_private,
                        "attached_to_doctype": "Chapter",
                        "attached_to_name": chapter.name,
                        "folder": "Home/Attachments"
                    })

                    # Insert without triggering file system operations
                    file_doc.flags.ignore_file_validate = True
                    file_doc.insert(ignore_permissions=True)

                    print(f"  ✓  Created File record for '{doc.document_name}'")
                    files_created += 1

                except Exception as e:
                    print(f"  ✗  ERROR creating File record for '{doc.document_name}': {str(e)}")
                    errors += 1

    # Summary
    print()
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"Total documents processed: {total_documents}")
    print(f"File records created: {files_created}")
    print(f"File records skipped (already exist): {files_skipped}")
    print(f"Errors: {errors}")
    print()

    if not dry_run and files_created > 0:
        frappe.db.commit()
        print("✓ Changes committed to database")
    elif dry_run:
        print("DRY RUN - No changes were made")

    print()


if __name__ == "__main__":
    # Run in dry-run mode by default when executed directly
    create_missing_file_records(dry_run=True)
