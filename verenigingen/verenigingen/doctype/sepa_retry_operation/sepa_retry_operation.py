# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SEPARetryOperation(Document):
    """
    SEPA Retry Operation - child table for individual retry operations within a SEPA Retry Batch
    Following patterns from DirectDebitBatch child table validation
    """

    def validate(self):
        """Validate retry operation - following child table patterns from main system"""
        # Set defaults for new operations
        if not self.status:
            self.status = "Pending"

        if not self.retry_attempts:
            self.retry_attempts = 0

        if not self.max_retries:
            self.max_retries = 3  # Following SEPAErrorHandler default

        # Validate retry logic constraints
        self.validate_retry_constraints()
        self.validate_error_category()
        self.validate_reference_documents()

    def validate_retry_constraints(self):
        """Validate retry attempt constraints - adapted from DirectDebitBatch validation patterns"""
        # Check if retry attempts exceed maximum
        if self.retry_attempts > self.max_retries:
            frappe.throw(
                _("Retry attempts ({0}) cannot exceed max retries ({1}) for {2} operation").format(
                    self.retry_attempts, self.max_retries, self.operation_type
                )
            )

        # Validate status transitions
        if self.status == "Success" and self.retry_attempts == 0:
            # Success should have at least one attempt recorded
            self.retry_attempts = 1

        # Set next retry time if still retrying
        if self.status == "Pending" and self.retry_attempts > 0:
            if not self.next_retry_time:
                # Calculate next retry time using exponential backoff (following SEPAErrorHandler pattern)
                from datetime import timedelta

                base_delay_minutes = 5  # 5 minutes base delay
                delay_minutes = base_delay_minutes * (2 ** (self.retry_attempts - 1))
                delay_minutes = min(delay_minutes, 120)  # Cap at 2 hours

                self.next_retry_time = now_datetime() + timedelta(minutes=delay_minutes)

    def validate_error_category(self):
        """Validate error category matches allowed values from SEPAErrorHandler"""
        if self.error_category:
            allowed_categories = ["temporary", "validation", "authorization", "data", "unknown"]
            if self.error_category not in allowed_categories:
                frappe.throw(_("Error category must be one of: {0}").format(", ".join(allowed_categories)))

            # Auto-set retry eligibility based on category (following SEPAErrorHandler logic)
            if self.error_category in ["validation", "data"]:
                # These typically shouldn't be retried
                if self.status == "Pending" and self.retry_attempts > 0:
                    frappe.msgprint(
                        _("Warning: {0} errors typically cannot be resolved by retrying").format(
                            self.error_category
                        ),
                        indicator="orange",
                    )

    def validate_reference_documents(self):
        """Validate reference document information"""
        # If reference document is specified, validate the doctype exists
        if self.reference_doctype and self.reference_document:
            if not frappe.db.exists(self.reference_doctype, self.reference_document):
                frappe.throw(
                    _("Reference document {0} of type {1} does not exist").format(
                        self.reference_document, self.reference_doctype
                    )
                )

        # Some operation types should have reference documents
        operation_types_requiring_reference = ["Invoice Creation", "Mandate Validation", "Payment Processing"]

        if self.operation_type in operation_types_requiring_reference:
            if not (self.reference_doctype and self.reference_document):
                frappe.msgprint(
                    _("Operation type '{0}' typically requires a reference document").format(
                        self.operation_type
                    ),
                    indicator="yellow",
                )

    def is_eligible_for_retry(self):
        """Check if this operation is eligible for retry - following SEPAErrorHandler patterns"""
        # Already succeeded or failed permanently
        if self.status in ["Success", "Skipped"]:
            return False

        # Exceeded max retries
        if self.retry_attempts >= self.max_retries:
            return False

        # Check error category eligibility (following SEPAErrorHandler logic)
        if self.error_category in ["validation", "data"]:
            return False  # These need manual intervention

        if self.error_category == "authorization" and self.retry_attempts > 0:
            return False  # Don't retry auth errors after first attempt

        # Temporary and unknown errors can be retried
        return self.error_category in ["temporary", "unknown", None]

    def should_retry_now(self):
        """Check if retry should happen now based on timing"""
        if not self.is_eligible_for_retry():
            return False

        if not self.next_retry_time:
            return True  # No delay set, can retry now

        return now_datetime() >= self.next_retry_time
