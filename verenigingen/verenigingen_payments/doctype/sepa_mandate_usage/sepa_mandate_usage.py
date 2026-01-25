# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.api.sepa_duplicate_prevention import (
    acquire_processing_lock,
    release_processing_lock,
)
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


class SEPAMandateUsage(Document):
    def validate(self):
        self.validate_mandate_status()
        self.set_sequence_type()
        self.validate_amount()

    def validate_mandate_status(self):
        """Validate that the mandate is active and valid"""
        if not self.get("parent"):  # Skip if this is not part of a SEPA Mandate
            return

        mandate = frappe.get_doc("SEPA Mandate", self.parent)
        if mandate.status != "Active":
            frappe.throw(f"Cannot use inactive mandate: {mandate.mandate_id}")

        # Check mandate expiry
        if mandate.expiry_date and getdate(mandate.expiry_date) < getdate(today()):
            frappe.throw(f"Mandate {mandate.mandate_id} has expired")

    def set_sequence_type(self):
        """Auto-determine sequence type based on mandate history"""
        if not self.sequence_type and self.get("parent"):
            self.sequence_type = self.determine_sequence_type()

    def determine_sequence_type(self):
        """
        Determine FRST/RCUR based on actual mandate usage history
        This replaces the basic batch-level logic with individual tracking
        """
        if not self.get("parent"):
            return "FRST"  # Default for standalone usage

        mandate_name = self.parent

        # Check if this mandate has been used before successfully
        previous_usage = frappe.get_all(
            "SEPA Mandate Usage",
            filters={"parent": mandate_name, "status": "Collected", "name": ["!=", self.name or ""]},
            fields=["usage_date", "sequence_type"],
            order_by="usage_date desc",
            limit=1,
        )

        if not previous_usage:
            # First usage of this mandate
            return "FRST"

        # Check if mandate was reset (new mandate after cancellation)
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        last_usage_date = previous_usage[0].usage_date

        if mandate.sign_date and getdate(mandate.sign_date) > getdate(last_usage_date):
            # Mandate was renewed after last usage
            return "FRST"

        return "RCUR"

    def validate_amount(self):
        """Validate amount against mandate limits"""
        if not self.amount or not self.get("parent"):
            return

        mandate = frappe.get_doc("SEPA Mandate", self.parent)
        if mandate.maximum_amount and self.amount > mandate.maximum_amount:
            frappe.throw(f"Amount €{self.amount} exceeds mandate maximum of €{mandate.maximum_amount}")

    # Note: SEPA Mandate Usage is a child table document ("istable": 1)
    # Child tables don't have on_submit() events - they're managed by the parent document
    # The usage tracking happens through the parent-child relationship automatically

    def mark_as_collected(self, processing_date=None):
        """Mark usage as successfully collected"""
        self.status = "Collected"
        self.processing_date = processing_date or today()
        self.save()

    def mark_as_failed(self, failure_reason, processing_date=None):
        """Mark usage as failed with reason"""
        self.status = "Failed"
        self.failure_reason = failure_reason
        self.processing_date = processing_date or today()
        self.save()

    def mark_as_returned(self, return_reason, processing_date=None):
        """Mark usage as returned by bank"""
        self.status = "Returned"
        self.failure_reason = return_reason
        self.processing_date = processing_date or today()
        self.save()

    def retry_usage(self):
        """Retry a failed usage"""
        if self.status not in ["Failed", "Returned"]:
            frappe.throw("Can only retry failed or returned usages")

        self.retry_count = (self.retry_count or 0) + 1
        self.last_retry_date = today()
        self.status = "Pending"
        self.save()


def create_mandate_usage_record(mandate_name, reference_doctype, reference_name, amount, sequence_type=None):
    """
    Create a mandate usage record for tracking SEPA transactions.

    Uses a mandate-level lock to prevent race conditions in sequence type
    determination. Two concurrent calls for the same mandate will be serialized,
    ensuring correct FRST/RCUR assignment.

    Args:
        mandate_name: Name of the SEPA Mandate
        reference_doctype: Type of document (Sales Invoice, etc.)
        reference_name: Name of the reference document
        amount: Transaction amount
        sequence_type: Force specific sequence type, otherwise auto-determined

    Returns:
        Name of created SEPA Mandate Usage record (as child table row)

    Raises:
        ValidationError: If lock cannot be acquired (another operation in progress)
    """
    # Acquire mandate-level lock to prevent sequence type race conditions
    # This ensures only one usage record is created at a time per mandate
    lock_timeout = 30  # 30 seconds should be enough for a single save operation

    if not acquire_processing_lock("mandate_usage", mandate_name, timeout=lock_timeout):
        frappe.throw(_("Another operation is modifying mandate {0}. Please try again.").format(mandate_name))

    try:
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)

        # Add usage record to the mandate's usage_history child table
        # The sequence_type will be auto-determined in validate() if None
        usage_row = mandate.append(
            "usage_history",
            {
                "usage_date": today(),
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "amount": amount,
                "status": "Pending",
                "sequence_type": sequence_type,
            },
        )

        # Save the parent mandate to persist the child table record
        # The SEPAMandateUsage.validate() will be called here, which calls
        # determine_sequence_type() if sequence_type is None
        mandate.save()

        # Invalidate lifecycle manager cache to ensure fresh sequence type determination
        # for any subsequent calls
        _invalidate_lifecycle_cache(mandate.mandate_id)

        return usage_row.name

    finally:
        # Always release the lock, even if an error occurred
        release_processing_lock("mandate_usage", mandate_name)


def _invalidate_lifecycle_cache(mandate_id: str) -> None:
    """
    Invalidate the lifecycle manager cache for a mandate after usage record creation.

    This ensures subsequent sequence type determinations use fresh data including
    the newly created usage record.
    """
    try:
        from verenigingen.verenigingen_payments.utils.sepa_mandate_lifecycle_manager import (
            SEPAMandateLifecycleManager,
        )

        manager = SEPAMandateLifecycleManager()
        manager.invalidate_cache(mandate_id)
    except ImportError:
        # Lifecycle manager not available - skip cache invalidation
        pass
    except Exception as e:
        # Log but don't fail the main operation
        frappe.logger().warning(f"Failed to invalidate lifecycle cache for {mandate_id}: {str(e)}")


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def get_mandate_sequence_type(mandate_name: str, reference_name: str = None):
    """
    API to determine what sequence type should be used for a mandate

    Args:
        mandate_name: Name of the SEPA Mandate
        reference_name: Optional reference to exclude from history check

    Returns:
        Dict with sequence_type and reasoning
    """
    try:
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        mandate.check_permission("read")

        # Check previous successful usage
        filters = {"parent": mandate_name, "status": "Collected"}

        if reference_name:
            filters["reference_name"] = ["!=", reference_name]

        previous_usage = frappe.get_all(
            "SEPA Mandate Usage",
            filters=filters,
            fields=["usage_date", "sequence_type"],
            order_by="usage_date desc",
            limit=1,
        )

        if not previous_usage:
            return {"sequence_type": "FRST", "reason": "First usage of this mandate"}

        # Check if mandate was renewed
        last_usage_date = previous_usage[0].usage_date
        if mandate.sign_date and getdate(mandate.sign_date) > getdate(last_usage_date):
            return {"sequence_type": "FRST", "reason": "Mandate was renewed after last usage"}

        return {"sequence_type": "RCUR", "reason": "Recurring usage - mandate has been used before"}

    except Exception as e:
        frappe.log_error(f"Error determining sequence type for mandate {mandate_name}: {str(e)}")
        return {"sequence_type": "FRST", "reason": f"Error occurred, defaulting to FRST: {str(e)}"}
