#!/usr/bin/env python3
# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Utility script to migrate existing board documents to hierarchical file structure.

Usage:
    bench --site dev.veganisme.net execute verenigingen.utils.migrate_board_documents.migrate_all_documents
    bench --site dev.veganisme.net execute verenigingen.utils.migrate_board_documents.migrate_chapter_documents --args "['Chapter Name']"
"""

import re

import frappe
from frappe.utils import today

from verenigingen.utils.file_storage import cleanup_empty_directories, organize_existing_chapter_document


def migrate_chapter_documents(chapter_name: str, dry_run: bool = False):
    """
    Migrate all board documents for a specific chapter to hierarchical storage.

    Args:
        chapter_name: Name of the chapter
        dry_run: If True, only report what would be done without making changes
    """
    try:
        chapter = frappe.get_doc("Chapter", chapter_name)
        migrated = 0
        skipped = 0

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Migrating documents for chapter: {chapter_name}")
        print("=" * 80)

        for doc in chapter.board_documents:
            if not doc.document_file:
                print(f"⚠️  Skipping: {doc.document_name} (no file attached)")
                skipped += 1
                continue

            # Check if already in hierarchical structure
            if "/documents/chapters/" in doc.document_file:
                print(f"✓  Already organized: {doc.document_name}")
                skipped += 1
                continue

            # Extract year
            year_match = re.search(r"\b(20\d{2})\b", doc.document_name)
            year = year_match.group(1) if year_match else "Other"

            old_url = doc.document_file
            category = doc.document_type or "Other"

            print(f"\n📄 {doc.document_name}")
            print(f"   Category: {category}")
            print(f"   Year: {year}")
            print(f"   Old path: {old_url}")

            if not dry_run:
                # Move file
                new_url = organize_existing_chapter_document(
                    file_url=old_url, chapter_name=chapter_name, category=category, year=year
                )

                if new_url != old_url:
                    # Update document
                    doc.document_file = new_url
                    print(f"   New path: {new_url}")
                    print(f"   ✅ Migrated")
                    migrated += 1
                else:
                    print(f"   ⚠️  Migration failed or file not found")
                    skipped += 1
            else:
                # Calculate what new path would be
                safe_chapter = frappe.scrub(chapter_name).replace("_", "-")
                safe_category = frappe.scrub(category).replace("_", "-")
                new_path = f"/private/files/documents/chapters/{safe_chapter}/{safe_category}/{year}/"
                print(f"   Would move to: {new_path}")
                migrated += 1

        if not dry_run and migrated > 0:
            # Save chapter with updated file URLs
            chapter.save()
            frappe.db.commit()

        print("\n" + "=" * 80)
        print(f"{'[DRY RUN] ' if dry_run else ''}Migration complete for {chapter_name}:")
        print(f"  ✅ Migrated: {migrated}")
        print(f"  ⏭️  Skipped: {skipped}")

        return {"migrated": migrated, "skipped": skipped}

    except Exception as e:
        frappe.log_error(f"Error migrating chapter {chapter_name}: {str(e)}")
        print(f"\n❌ Error: {str(e)}")
        return {"migrated": 0, "skipped": 0, "error": str(e)}


def migrate_all_documents(dry_run: bool = False):
    """
    Migrate all board documents across all chapters to hierarchical storage.

    Args:
        dry_run: If True, only report what would be done without making changes
    """
    print(f"\n{'=' * 80}")
    print(f"{'[DRY RUN] ' if dry_run else ''}MIGRATING ALL BOARD DOCUMENTS TO HIERARCHICAL STORAGE")
    print(f"{'=' * 80}\n")

    # Get all chapters with board documents
    chapters = frappe.get_all("Chapter", filters={}, fields=["name"])

    total_migrated = 0
    total_skipped = 0
    total_errors = 0

    for chapter in chapters:
        result = migrate_chapter_documents(chapter.name, dry_run=dry_run)
        total_migrated += result.get("migrated", 0)
        total_skipped += result.get("skipped", 0)
        if result.get("error"):
            total_errors += 1

    print(f"\n{'=' * 80}")
    print(f"{'[DRY RUN] ' if dry_run else ''}MIGRATION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total chapters processed: {len(chapters)}")
    print(f"Total documents migrated: {total_migrated}")
    print(f"Total documents skipped: {total_skipped}")
    print(f"Total errors: {total_errors}")

    if not dry_run:
        print(f"\n🧹 Cleaning up empty directories...")
        try:
            from frappe.utils import get_files_path

            cleanup_empty_directories(get_files_path(is_private=1))
            print("✅ Cleanup complete")
        except Exception as e:
            print(f"⚠️  Cleanup error: {str(e)}")

    print(f"\n{'[DRY RUN COMPLETE]' if dry_run else 'MIGRATION COMPLETE'}\n")


if __name__ == "__main__":
    # Run as dry run first
    print("Running dry run to preview changes...")
    migrate_all_documents(dry_run=True)
