# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SEPARetryBatch(Document):
    """
    SEPA Retry Batch - manages batch processing of failed SEPA payment retries
    Following patterns from DirectDebitBatch and SEPAErrorHandler
    """

    def validate(self):
        """Validate the retry batch before saving - following DirectDebitBatch patterns"""
        self.validate_operations()
        self.calculate_totals()

        # Set default status for new documents
        if not self.status:
            self.status = "Pending"

    def validate_operations(self):
        """Validate retry operations - adapted from DirectDebitBatch.validate_invoices()"""
        if not self.operations:
            # Allow empty batches (they can be populated later)
            return

        for operation in self.operations:
            # Set defaults for new operations, BEFORE the retry_attempts<=max_retries
            # check below. Moved here from the dead SEPARetryOperation.validate()
            # (#596) in the same order that method used. This is a behaviour change
            # from the tree just before this PR (though not from anything that ever
            # actually ran): the check below used to sit above a max_retries default
            # set only at the bottom of the loop, so `if operation.retry_attempts and
            # operation.max_retries` was False -- and the check silently skipped --
            # for a row with retry_attempts set and max_retries left unset. Ordering
            # the default first, as the original dead code did, means that row now
            # gets checked and can throw where it silently saved before.
            if not operation.status:
                operation.status = "Pending"

            if not operation.retry_attempts:
                operation.retry_attempts = 0

            if not operation.max_retries:
                operation.max_retries = 3

            # Success should have at least one attempt recorded. Moved here from
            # the dead SEPARetryOperation.validate() (#596).
            if operation.status == "Success" and operation.retry_attempts == 0:
                operation.retry_attempts = 1

            # Validate operation type is set
            if not operation.operation_type:
                frappe.throw(_("Operation type is required for all retry operations"))

            # Validate error category is from allowed values
            if operation.error_category and operation.error_category not in [
                "temporary",
                "validation",
                "authorization",
                "data",
                "unknown",
            ]:
                frappe.throw(_("Invalid error category: {0}").format(operation.error_category))

            # Validate retry attempts don't exceed max
            if operation.retry_attempts and operation.max_retries:
                if operation.retry_attempts > operation.max_retries:
                    frappe.throw(
                        _("Retry attempts ({0}) cannot exceed max retries ({1}) for operation {2}").format(
                            operation.retry_attempts, operation.max_retries, operation.operation_type
                        )
                    )

            # Validate the reference document exists. Moved here from the dead
            # SEPARetryOperation.validate() (#596) -- Frappe never runs a child
            # DocType's validate(), so this was never enforced.
            if operation.reference_doctype and operation.reference_document:
                if not frappe.db.exists(operation.reference_doctype, operation.reference_document):
                    frappe.throw(
                        _("Reference document {0} of type {1} does not exist").format(
                            operation.reference_document, operation.reference_doctype
                        )
                    )

            # Compute the exponential-backoff next_retry_time for a still-pending
            # operation. Moved here from the dead SEPARetryOperation.validate()
            # (#596) -- without it, should_retry_now() ("if not self.next_retry_time:
            # return True") retries immediately with no backoff.
            if operation.status == "Pending" and operation.retry_attempts and not operation.next_retry_time:
                base_delay_minutes = 5
                delay_minutes = base_delay_minutes * (2 ** (operation.retry_attempts - 1))
                delay_minutes = min(delay_minutes, 120)  # Cap at 2 hours
                operation.next_retry_time = now_datetime() + timedelta(minutes=delay_minutes)

    def calculate_totals(self):
        """Calculate batch totals from the in-memory operations.

        The in-memory ``self.operations`` are the source of truth here: during
        on_submit the children are mutated in memory and validate() (which calls
        this method) runs BEFORE those child rows are written to the DB, so a SQL
        aggregation would read stale 'Pending' rows and miscount. Iterating the
        loaded child docs reflects the current intent in both the insert and the
        submit/save flows.
        """
        self.total_operations = len(self.operations)
        self.successful_retries = len([op for op in self.operations if op.status == "Success"])
        self.failed_retries = len([op for op in self.operations if op.status == "Failed"])
        pending_operations = len([op for op in self.operations if op.status == "Pending"])

        # Update batch status based on operation states (same logic)
        if self.total_operations == 0:
            self.status = "Pending"
        elif pending_operations > 0 and self.status not in ["Pending", "Processing"]:
            # Don't override Processing status
            pass
        elif self.failed_retries == 0 and self.successful_retries == self.total_operations:
            self.status = "Completed"
        elif self.failed_retries > 0 and self.successful_retries > 0:
            self.status = "Partially Completed"
        elif self.failed_retries == self.total_operations:
            self.status = "Failed"

    def _calculate_totals_python(self):
        """Fallback Python calculation for new documents or when SQL fails"""
        if not self.operations:
            self.total_operations = 0
            self.successful_retries = 0
            self.failed_retries = 0
            return

        self.total_operations = len(self.operations)
        self.successful_retries = len([op for op in self.operations if op.status == "Success"])
        self.failed_retries = len([op for op in self.operations if op.status == "Failed"])

    def on_submit(self):
        """Process the retry batch when submitted - following DirectDebitBatch pattern"""
        self.status = "Processing"

        # Add processing timestamp
        self.db_set("processing_started", now_datetime())

        # Process operations (this would be enhanced with actual retry logic)
        self.process_retry_operations()

    def on_cancel(self):
        """Handle batch cancellation - following DirectDebitBatch pattern.

        Frappe's cancel flow only persists the docstatus change; plain field
        assignments made here are not written back. Use db_set so the cancelled
        status and the log note are actually saved.
        """
        self.add_to_batch_log(_("Retry batch cancelled"))
        self.db_set("status", "Cancelled")
        self.db_set("notes", self.notes)

    def process_retry_operations(self):
        """Process all retry operations in the batch"""
        try:
            processed_count = 0

            for i, operation in enumerate(self.operations):
                if operation.status == "Pending":
                    # Update operation status to show it's being processed
                    operation.status = "Retrying"
                    operation.last_retry_time = now_datetime()

                    # Process the operation (placeholder for actual retry logic)
                    result = self.process_single_operation(operation)

                    if result["success"]:
                        operation.status = "Success"
                        processed_count += 1
                    else:
                        operation.status = "Failed"
                        operation.final_error = result.get("error", "Unknown error")

                    operation.retry_attempts = (operation.retry_attempts or 0) + 1

            # Update totals and final status
            self.calculate_totals()

            # Set final processing timestamp
            self.db_set("processing_completed", now_datetime())

            # Save with updated status
            self.save()

            frappe.logger().info(f"SEPA Retry Batch {self.name} processed {processed_count} operations")

        except Exception as e:
            self.status = "Failed"
            self.notes = f"Batch processing failed: {str(e)}"
            self.db_set("processing_completed", now_datetime())
            self.save()
            frappe.log_error(f"SEPA Retry Batch {self.name} processing failed: {str(e)}")

    def process_single_operation(self, operation):
        """
        Process a single retry operation - placeholder for actual retry logic
        Following error handling patterns from SEPAErrorHandler
        """
        try:
            # This is where actual retry logic would go:
            # - Re-validate mandate
            # - Retry invoice creation
            # - Retry batch processing
            # - etc.

            # For now, simulate processing based on error category
            if operation.error_category == "validation":
                # Validation errors typically don't succeed on retry
                return {"success": False, "error": "Validation error persists"}
            elif operation.error_category == "temporary":
                # Temporary errors have higher success chance
                return {"success": True}
            else:
                # Unknown/other errors - mixed results
                return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_to_batch_log(self, message):
        """Add entry to batch processing log - following DirectDebitBatch pattern"""
        if not hasattr(self, "_batch_log"):
            self._batch_log = []

        self._batch_log.append({"timestamp": now_datetime(), "message": message})

        # Store in notes field for now (could be enhanced with separate log table)
        current_notes = self.notes or ""
        log_entry = f"[{now_datetime()}] {message}"
        self.notes = f"{current_notes}\n{log_entry}" if current_notes else log_entry
