"""
CSV Import Background Processor

Reusable utility for processing large CSV imports in background jobs with:
- Batch processing to prevent timeouts
- Real-time progress tracking
- Comprehensive error handling and recovery

This module can be used by any DocType that needs to import large datasets
without blocking the UI or hitting request timeouts.

Note: This processor does NOT send notifications. Import status is tracked
on the import document itself (import_status, progress_percentage, etc.).
If specific import DocTypes need notifications, they should implement them
in their own finalize_callback, respecting Email Configuration settings.

Author: Verenigingen Development Team
"""

import traceback
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import get_datetime, now


def ensure_bulk_import_members_set():
    """
    Ensure frappe.local.bulk_import_members exists.

    This helper function guarantees the bulk import tracking set is initialized,
    preventing race conditions and warnings when member creation code runs
    outside the normal CSVImportBackgroundProcessor flow.

    Should be called:
    - At the start of bulk import processing
    - Before any member creation that might check this set

    Returns:
        set: The bulk_import_members set (created if it didn't exist)
    """
    if not hasattr(frappe.local, "bulk_import_members"):
        frappe.local.bulk_import_members = set()
    return frappe.local.bulk_import_members


@contextmanager
def bulk_member_operations(import_doc_name: str = None):
    """
    Context manager for bulk import operations.

    Sets up the bulk operations flag and member tracking set, ensuring
    proper cleanup on both success and failure. This prevents fee override
    hooks and background event processing during bulk imports.

    Args:
        import_doc_name: Optional name of the import document for logging

    Yields:
        set: The bulk_import_members tracking set

    Usage:
        with bulk_member_operations("MEMBER-IMPORT-2025-00016") as member_set:
            # Process import rows
            member_set.add(member.name)
    """
    try:
        frappe.flags.bulk_member_operations = True
        member_set = ensure_bulk_import_members_set()
        frappe.logger().info(f"Bulk import started: {import_doc_name or 'unnamed'}")
        yield member_set
    finally:
        frappe.flags.bulk_member_operations = False
        if hasattr(frappe.local, "bulk_import_members"):
            frappe.local.bulk_import_members.clear()
        frappe.logger().info(f"Bulk import cleanup complete: {import_doc_name or 'unnamed'}")


class CSVImportBackgroundProcessor:
    """
    Background processor for CSV imports with progress tracking.

    This class handles the orchestration of large imports by:
    1. Processing records in configurable batches
    2. Updating progress in real-time
    3. Handling errors without stopping the entire import

    Note: This processor does NOT send notifications. Status is tracked on
    the import document. If notifications are needed, implement them in
    your finalize_callback with proper Email Configuration checks.
    """

    def __init__(self, import_doc_name: str, doctype: str):
        """
        Initialize the background processor.

        Args:
            import_doc_name: Name of the import document (e.g., MEMBER-IMPORT-2025-00016)
            doctype: DocType name of the import document (e.g., "Mijnrood CSV Import")
        """
        self.import_doc_name = import_doc_name
        self.doctype = doctype
        self.import_doc = None

    def load_import_doc(self):
        """Load the import document."""
        self.import_doc = frappe.get_doc(self.doctype, self.import_doc_name)

    def process_import(
        self,
        data_rows: List[Dict],
        process_row_callback: Callable[[Dict, List[str]], tuple],
        finalize_callback: Optional[Callable[[int, int, int, List[str], List[str]], None]] = None,
        batch_size: int = 50,
        batch_commit: bool = True,
    ) -> Dict:
        """
        Process CSV import in batches with progress tracking.

        Args:
            data_rows: List of dictionaries containing row data
            process_row_callback: Function to process a single row.
                                 Should return (result_status, record_name) tuple
                                 where result_status is "created", "updated", or "skipped"
            finalize_callback: Optional function to call after processing completes.
                             Receives (created_count, updated_count, skipped_count, error_log, processed_records)
            batch_size: Number of rows to process before committing
            batch_commit: Whether to commit after each batch

        Returns:
            dict: Summary of import results
        """
        try:
            self.load_import_doc()

            # Use context manager for bulk operations flag management
            with bulk_member_operations(self.import_doc_name):
                # Update status to processing
                self._update_status("In Progress", 0, len(data_rows))

                created_count = 0
                updated_count = 0
                skipped_count = 0
                error_log = []
                created_records = []
                updated_records = []
                skipped_records = []

                total_rows = len(data_rows)

                # Process in batches
                for batch_start in range(0, total_rows, batch_size):
                    batch_end = min(batch_start + batch_size, total_rows)
                    batch = data_rows[batch_start:batch_end]

                    frappe.logger().info(
                        f"Processing batch {batch_start}-{batch_end} of {total_rows} for {self.import_doc_name}"
                    )

                    # Process each row in the batch
                    for row in batch:
                        try:
                            result, record_name = process_row_callback(row, error_log)

                            if result == "created":
                                created_count += 1
                                if record_name:
                                    created_records.append(record_name)
                            elif result == "updated":
                                updated_count += 1
                                if record_name:
                                    updated_records.append(record_name)
                            else:
                                skipped_count += 1
                                if record_name:
                                    skipped_records.append(record_name)

                        except Exception as e:
                            skipped_count += 1
                            error_msg = f"Row {row.get('row_number', '?')}: {str(e)}"
                            error_log.append(error_msg)
                            frappe.logger().error(f"Error processing row: {error_msg}")

                    # Update progress after each batch
                    processed_so_far = batch_end
                    self._update_progress(
                        processed_so_far, total_rows, created_count, updated_count, skipped_count
                    )

                    # Commit batch if enabled
                    if batch_commit:
                        frappe.db.commit()

                # Finalize import
                if finalize_callback:
                    finalize_callback(
                        created_count,
                        updated_count,
                        skipped_count,
                        error_log,
                        created_records,
                        updated_records,
                        skipped_records,
                    )
                else:
                    self._default_finalize(created_count, updated_count, skipped_count, error_log)

            # Context manager handles cleanup; return success result
            return {
                "success": True,
                "created": created_count,
                "updated": updated_count,
                "skipped": skipped_count,
                "total": total_rows,
                "errors": len(error_log),
            }

        except Exception as e:
            # Context manager already cleaned up flags in finally block
            error_msg = f"Import failed: {str(e)}\n{traceback.format_exc()}"
            frappe.logger().error(f"CSV Import Background Job Failed: {error_msg}")

            # Update import doc with failure status
            self._update_status("Failed", error=error_msg)

            return {"success": False, "error": str(e)}

    def _update_status(self, status: str, processed: int = 0, total: int = 0, error: str = None):
        """Update import document status."""
        try:
            # Reload to avoid conflicts
            self.import_doc.reload()

            self.import_doc.import_status = status

            if hasattr(self.import_doc, "progress_percentage"):
                if total > 0:
                    self.import_doc.progress_percentage = int((processed / total) * 100)

            if hasattr(self.import_doc, "last_processed_at"):
                self.import_doc.last_processed_at = now()

            if error:
                self.import_doc.error_log = error

            self.import_doc.save(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            frappe.logger().error(f"Failed to update import status: {str(e)}")

    def _update_progress(self, processed: int, total: int, created: int, updated: int, skipped: int):
        """Update progress fields during processing."""
        try:
            # Reload to get latest state
            self.import_doc.reload()

            if hasattr(self.import_doc, "progress_percentage"):
                self.import_doc.progress_percentage = int((processed / total) * 100)

            if hasattr(self.import_doc, "rows_processed"):
                self.import_doc.rows_processed = processed

            if hasattr(self.import_doc, "total_rows"):
                self.import_doc.total_rows = total

            if hasattr(self.import_doc, "members_created"):
                self.import_doc.members_created = created

            if hasattr(self.import_doc, "members_updated"):
                self.import_doc.members_updated = updated

            if hasattr(self.import_doc, "members_skipped"):
                self.import_doc.members_skipped = skipped

            if hasattr(self.import_doc, "last_processed_at"):
                self.import_doc.last_processed_at = now()

            self.import_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.logger().error(f"Failed to update progress: {str(e)}")

    def _default_finalize(self, created: int, updated: int, skipped: int, error_log: List[str]):
        """Default finalization if no custom callback provided."""
        from verenigingen.utils.import_helpers import (
            persist_full_error_log,
            truncate_error_log_for_display,
        )

        self.import_doc.reload()
        self.import_doc.import_status = "Completed"
        self.import_doc.import_summary = (
            f"Import completed. Created: {created}, Updated: {updated}, Skipped: {skipped}"
        )

        if error_log:
            # Persist full error log as File attachment before truncating
            filename = persist_full_error_log(error_log, self.doctype, self.import_doc_name)
            # Truncate for UI display
            self.import_doc.error_log = truncate_error_log_for_display(
                error_log, max_lines=100, full_log_filename=filename
            )

        self.import_doc.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
def queue_csv_import_processing(
    import_doc_name: str, doctype: str, processor_method: str, timeout: int = 3600, queue: str = "long"
):
    """
    Queue a CSV import for background processing.

    Args:
        import_doc_name: Name of the import document
        doctype: DocType name of the import document
        processor_method: Fully qualified method path to process the import
                         (e.g., "verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.process_import_background")
        timeout: Job timeout in seconds (default 1 hour)
        queue: Queue name (default "long")

    Returns:
        dict: Job enqueue confirmation
    """
    frappe.enqueue(
        method=processor_method,
        queue=queue,
        timeout=timeout,
        import_doc_name=import_doc_name,
        now=False,  # Process in background
    )

    return {
        "success": True,
        "message": _("Import queued for background processing"),
        "import_doc": import_doc_name,
    }
