# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import now_datetime


class SEPARetryOperation(Document):
    """
    SEPA Retry Operation - child table for individual retry operations within a SEPA Retry Batch
    Following patterns from DirectDebitBatch child table validation
    """

    # #596: this class used to define validate() (default status/retry_attempts/
    # max_retries, retry_attempts <= max_retries, error_category allow-list,
    # exponential-backoff next_retry_time, reference-document existence). Frappe
    # never runs it -- there is no d.run_method("validate") for children anywhere
    # in insert()/save(). SEPARetryBatch.validate() -> validate_operations()
    # (sepa_retry_batch.py) already iterates self.operations from the parent and
    # now carries every one of these checks, including the two that had no other
    # enforcement (reference-document existence and the backoff computation --
    # without the latter, should_retry_now() below retries immediately since
    # next_retry_time is never set). The error-category-vs-status "shouldn't be
    # retried" and reference-document-recommended notices were frappe.logger()
    # .warning() calls, which are dropped by default handler level and never
    # written anywhere CI or an operator would see -- not preserved.

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
