"""
CSV Import Background Processor

Reusable utility for processing large CSV imports in background jobs with:
- Batch processing to prevent timeouts
- Real-time progress tracking
- Email notifications on completion
- Comprehensive error handling and recovery

This module can be used by any DocType that needs to import large datasets
without blocking the UI or hitting request timeouts.

Author: Verenigingen Development Team
"""

import traceback
from typing import Callable, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import get_datetime, now


class CSVImportBackgroundProcessor:
    """
    Background processor for CSV imports with progress tracking.

    This class handles the orchestration of large imports by:
    1. Processing records in configurable batches
    2. Updating progress in real-time
    3. Handling errors without stopping the entire import
    4. Sending notifications on completion
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

            # Set bulk operations flag to prevent fee override hooks and background event processing
            frappe.flags.bulk_member_operations = True

            # Initialize a set to track members being imported (persists for the entire background job)
            if not hasattr(frappe.local, "bulk_import_members"):
                frappe.local.bulk_import_members = set()

            frappe.logger().info(f"Bulk import initialized for {self.import_doc_name}")

            # Update status to processing
            self._update_status("In Progress", 0, len(data_rows))

            created_count = 0
            updated_count = 0
            skipped_count = 0
            error_log = []
            processed_records = []

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
                                processed_records.append(record_name)
                        elif result == "updated":
                            updated_count += 1
                            if record_name:
                                processed_records.append(record_name)
                        else:
                            skipped_count += 1

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
                finalize_callback(created_count, updated_count, skipped_count, error_log, processed_records)
            else:
                self._default_finalize(created_count, updated_count, skipped_count, error_log)

            # Send completion notification
            self._send_completion_notification(created_count, updated_count, skipped_count)

            # Clear bulk operations flag and member tracking set
            frappe.flags.bulk_member_operations = False
            if hasattr(frappe.local, "bulk_import_members"):
                frappe.local.bulk_import_members.clear()
            frappe.logger().info(f"Bulk import completed and cleaned up for {self.import_doc_name}")

            return {
                "success": True,
                "created": created_count,
                "updated": updated_count,
                "skipped": skipped_count,
                "total": total_rows,
                "errors": len(error_log),
            }

        except Exception as e:
            # Clear flag and tracking set on error too
            frappe.flags.bulk_member_operations = False
            if hasattr(frappe.local, "bulk_import_members"):
                frappe.local.bulk_import_members.clear()

            error_msg = f"Import failed: {str(e)}\n{traceback.format_exc()}"
            frappe.logger().error(f"CSV Import Background Job Failed: {error_msg}")

            # Update import doc with failure status
            self._update_status("Failed", error=error_msg)

            # Send failure notification
            self._send_failure_notification(error_msg)

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
        self.import_doc.reload()
        self.import_doc.import_status = "Completed"
        self.import_doc.import_summary = (
            f"Import completed. Created: {created}, Updated: {updated}, Skipped: {skipped}"
        )

        if error_log:
            self.import_doc.error_log = "\n".join(error_log[:100])  # Limit to first 100 errors

        self.import_doc.save(ignore_permissions=True)
        frappe.db.commit()

    def _send_completion_notification(self, created: int, updated: int, skipped: int):
        """Send email notification on successful completion."""
        try:
            if not self.import_doc.owner:
                return

            frappe.sendmail(
                recipients=[self.import_doc.owner],
                subject=_("CSV Import Completed: {0}").format(self.import_doc_name),
                message=_(
                    """
                    <p>Your CSV import has completed successfully.</p>
                    <ul>
                        <li>Created: {0}</li>
                        <li>Updated: {1}</li>
                        <li>Skipped: {2}</li>
                    </ul>
                    <p><a href="/app/{3}/{4}">View Import Document</a></p>
                """
                ).format(
                    created, updated, skipped, self.doctype.lower().replace(" ", "-"), self.import_doc_name
                ),
            )
        except Exception as e:
            frappe.logger().error(f"Failed to send completion notification: {str(e)}")

    def _send_failure_notification(self, error_msg: str):
        """Send email notification on import failure."""
        try:
            if not self.import_doc.owner:
                return

            frappe.sendmail(
                recipients=[self.import_doc.owner],
                subject=_("CSV Import Failed: {0}").format(self.import_doc_name),
                message=_(
                    """
                    <p>Your CSV import has failed.</p>
                    <p><strong>Error:</strong> {0}</p>
                    <p><a href="/app/{1}/{2}">View Import Document</a></p>
                """
                ).format(
                    error_msg[:500],  # Limit error message length
                    self.doctype.lower().replace(" ", "-"),
                    self.import_doc_name,
                ),
            )
        except Exception as e:
            frappe.logger().error(f"Failed to send failure notification: {str(e)}")


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
