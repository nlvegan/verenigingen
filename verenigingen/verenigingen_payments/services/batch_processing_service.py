"""
Batch Processing Service

This service handles medium complexity batch processing operations for SEPA direct debit.
Extracted from Direct Debit Batch system for better separation of concerns.
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe import _

from verenigingen.verenigingen_payments.services.batch_validation_service import batch_validation_service
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    InvoiceManagementUtilities,
)

if TYPE_CHECKING:
    from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class BatchProcessingService:
    """Service for SEPA batch processing operations"""

    def __init__(self):
        self.config_service = sepa_config_service
        self.validation_service = batch_validation_service

    def mark_batch_invoices_as_paid(self, batch_doc) -> int:
        """
        Mark all invoices in the batch as paid and create payment entries.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            Number of successfully processed invoices

        Raises:
            frappe.ValidationError: If batch is not in correct state
        """
        if batch_doc.docstatus != 1:
            frappe.throw(_("Batch must be submitted before marking invoices as paid"))

        success_count = 0

        for invoice_item in batch_doc.invoices:
            try:
                # Get the invoice
                invoice = frappe.get_doc("Sales Invoice", invoice_item.invoice)

                # Create payment entry
                payment_entry = self._create_payment_entry_for_invoice(
                    invoice=invoice,
                    payment_type="Receive",
                    mode_of_payment="SEPA Direct Debit",
                    reference_no=batch_doc.name,
                    reference_date=batch_doc.batch_date,
                )

                # Update batch invoice status. The batch is submitted and these
                # child fields are NOT allow_on_submit, so we persist them via
                # db_set (the sanctioned pattern for tracking-field writes on a
                # submitted document) instead of doc.save(), which would raise
                # UpdateAfterSubmitError after the Payment Entry is already created.
                self._set_invoice_status_after_submit(
                    invoice_item, "Successful", "PDNG", f"Payment entry {payment_entry.name} created"
                )

                # Advance the mandate's sequence type FRST -> RCUR by marking this
                # invoice's Pending SEPA Mandate Usage row as Collected. Only the
                # SUCCESS branch does this: a returned/failed FRST collection must
                # stay FRST. A missing usage row is a normal no-op (not every
                # invoice is a SEPA collection).
                self._mark_mandate_usage_collected(invoice_item.invoice)

                success_count += 1

            except Exception as e:
                self._set_invoice_status_after_submit(invoice_item, "Failed", "RJCT", f"Error: {str(e)}")
                frappe.log_error(
                    title="SEPA Direct Debit Payment Error",
                    message=f"Error processing payment for invoice {invoice_item.invoice}: {str(e)}",
                )

        # Update batch status (persisted via db_set, see above).
        self._update_batch_status_after_processing(batch_doc, success_count)

        # Log results. batch_log is not allow_on_submit either, so persist via db_set.
        BatchLoggingUtilities.add_to_document_batch_log(
            batch_doc, f"Processed {success_count} of {len(batch_doc.invoices)} invoices"
        )
        batch_doc.db_set("batch_log", batch_doc.batch_log, update_modified=False)

        return success_count

    def process_batch_submission(self, batch_doc) -> bool:
        """
        Process the batch submission - placeholder for bank integration.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            True if submission successful

        Raises:
            frappe.ValidationError: If SEPA file not generated or other errors
        """
        try:
            if not batch_doc.sepa_file_generated:
                frappe.throw(_("SEPA file must be generated before processing"))

            # Set status to submitted
            batch_doc.status = "Submitted"
            BatchLoggingUtilities.add_to_document_batch_log(batch_doc, _("Batch submitted for processing"))
            batch_doc.save()

            # Here you would add code to communicate with your bank's API
            # For now, this is a placeholder

            frappe.logger().info(f"Batch {batch_doc.name} submitted for processing")
            return True

        except Exception as e:
            error_msg = _("Error processing batch: {0}").format(str(e))
            BatchLoggingUtilities.add_to_document_batch_log(batch_doc, error_msg)
            frappe.log_error(
                title="SEPA Direct Debit Batch Error",
                message=f"Error processing batch {batch_doc.name}: {str(e)}",
            )
            raise frappe.ValidationError(error_msg)

    def calculate_batch_totals_optimized(self, batch_doc) -> None:
        """
        Calculate batch totals with SQL optimization for large batches.

        Args:
            batch_doc: Direct Debit Batch document to calculate totals for
        """
        try:
            # Try SQL aggregation first for performance (handles large batches efficiently)
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as entry_count,
                       COALESCE(SUM(amount), 0) as total_amount
                FROM `tabDirect Debit Batch Invoice`
                WHERE parent = %s
            """,
                (batch_doc.name,),
                as_dict=True,
            )

            if result and len(result) > 0:
                batch_doc.entry_count = result[0].entry_count
                batch_doc.total_amount = result[0].total_amount

                # Log successful calculation for audit
                BatchLoggingUtilities.log_batch_operation(
                    batch_doc.name,
                    "Calculate Totals (SQL)",
                    {
                        "entry_count": batch_doc.entry_count,
                        "total_amount": batch_doc.total_amount,
                        "method": "SQL optimization",
                    },
                )
            else:
                # Fallback to Python calculation
                self._calculate_totals_python_fallback(batch_doc)

        except Exception as e:
            # Fallback to Python calculation if SQL fails
            frappe.logger().warning(
                f"SQL aggregation failed for batch {batch_doc.name}, using Python fallback: {str(e)}"
            )
            self._calculate_totals_python_fallback(batch_doc)

    def validate_batch_invoices_optimized(self, batch_doc) -> Dict[str, Any]:
        """
        Validate all invoices in batch for direct debit eligibility using performance optimization.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            Dictionary with validation results

        Raises:
            frappe.ValidationError: If validation fails critically
        """
        if not batch_doc.invoices:
            frappe.throw(_("No invoices added to batch"))

        # Use performance optimizer for bulk validation
        try:
            from verenigingen.verenigingen_payments.utils.batch_performance_optimizer import (
                get_batch_performance_optimizer,
            )

            performance_optimizer = get_batch_performance_optimizer()
            invoice_names = [invoice.invoice for invoice in batch_doc.invoices]

            # Get invoice details in bulk to avoid N+1 queries
            invoice_details = performance_optimizer.get_invoices_with_details_bulk(invoice_names)

            validation_errors = []
            valid_count = 0

            for invoice_item in batch_doc.invoices:
                invoice_name = invoice_item.invoice
                invoice_data = invoice_details.get(invoice_name)

                if not invoice_data:
                    validation_errors.append(f"Invoice {invoice_name} not found")
                    continue

                # Validate individual invoice
                validation_result = InvoiceManagementUtilities.validate_invoice_for_sepa(invoice_data)

                if not validation_result["is_valid"]:
                    validation_errors.extend(
                        [f"Invoice {invoice_name}: {error}" for error in validation_result["errors"]]
                    )
                else:
                    valid_count += 1

            # Check for validation errors
            if validation_errors:
                error_summary = f"Found {len(validation_errors)} validation errors in batch"
                BatchLoggingUtilities.add_to_document_batch_log(batch_doc, error_summary)

                # Log details but don't fail the entire process for minor issues
                for error in validation_errors[:10]:  # Log first 10 errors
                    frappe.logger().warning(f"Batch {batch_doc.name} validation: {error}")

                if valid_count == 0:
                    frappe.throw(_("No valid invoices found in batch"))

            return {
                "is_valid": len(validation_errors) == 0,
                "total_invoices": len(batch_doc.invoices),
                "valid_invoices": valid_count,
                "errors": validation_errors[:10],  # Limit error details
                "has_warnings": len(validation_errors) > 0,
            }

        except frappe.ValidationError:
            # Intentional validation throws (e.g. "No valid invoices found in
            # batch") must propagate unchanged — wrapping them in the generic
            # F3001 ("Negative batch total amount calculated") handler below
            # masked the real cause and produced misleading error messages.
            raise
        except Exception as e:
            from verenigingen.verenigingen_payments.utils.financial_error_handler import (
                handle_data_integrity_error,
            )

            handle_data_integrity_error(
                "F3001",
                {
                    "stage": "batch invoice validation",
                    "batch_name": batch_doc.name,
                    "error": str(e),
                },
            )
            raise

    def _create_payment_entry_for_invoice(
        self, invoice, payment_type: str, mode_of_payment: str, reference_no: str, reference_date
    ) -> "PaymentEntry":
        """
        Create payment entry for an invoice with proper permissions.

        Args:
            invoice: Sales Invoice document
            payment_type: Type of payment (Receive/Pay)
            mode_of_payment: Payment method
            reference_no: Reference number for payment
            reference_date: Date of payment reference

        Returns:
            PaymentEntry document

        Raises:
            frappe.PermissionError: If user lacks payment entry permissions
            frappe.ValidationError: If amount is invalid
            Exception: For other payment creation errors
        """
        from decimal import Decimal

        from verenigingen.verenigingen_payments.services.payment import payment_entry_service

        # Use consolidated payment entry creation service
        return payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal(str(invoice.outstanding_amount)),
            posting_date=reference_date,
            reference_no=reference_no,
            reference_date=reference_date,
            mode_of_payment=mode_of_payment,
            payment_type=payment_type,
        )

    def _set_invoice_status_after_submit(
        self, invoice_item, status: str, result_code: str, result_message: str
    ) -> None:
        """
        Persist a batch invoice child row's status fields on a SUBMITTED batch.

        These child fields are not allow_on_submit, so they are written via
        db_set(update_modified=False) rather than parent.save() (which would
        raise UpdateAfterSubmitError). No commit is issued — the writes stay
        inside the request transaction so they remain atomic with the Payment
        Entries created in the same call.
        """
        invoice_item.db_set("status", status, update_modified=False)
        invoice_item.db_set("result_code", result_code, update_modified=False)
        invoice_item.db_set("result_message", result_message, update_modified=False)

    def _mark_mandate_usage_collected(self, invoice_name: str) -> None:
        """Mark the SEPA Mandate Usage row for a successfully-collected invoice
        as Collected, advancing the mandate's next sequence type to RCUR.

        The usage row (a child of SEPA Mandate) links to the invoice via
        reference_name. We only touch a row still in "Pending" state. The write
        uses db_set (no save(), no commit) so it stays inside the request
        transaction, atomic with the Payment Entry and status writes above —
        consistent with the surrounding post-submit tracking writes.

        A missing usage row is a normal no-op: not every collected invoice is a
        SEPA direct debit, and historical invoices may predate usage tracking.

        This is best-effort and MUST NOT raise: it runs after the Payment Entry is
        created and the invoice is marked Successful, so a propagated error would
        hit the caller's failure branch and wrongly reclassify an already-paid
        collection as Failed (a double-debit hazard). Any failure here is logged
        and swallowed; the worst case is the next collection staying FRST.
        """
        from frappe.utils import today

        try:
            # order_by creation so the oldest Pending row is advanced first when an
            # invoice has been retried (deterministic, not arbitrary).
            usage_name = frappe.db.get_value(
                "SEPA Mandate Usage",
                {"reference_name": invoice_name, "status": "Pending"},
                "name",
                order_by="creation asc",
            )
            if not usage_name:
                return

            frappe.db.set_value(
                "SEPA Mandate Usage",
                usage_name,
                {"status": "Collected", "processing_date": today()},
                update_modified=False,
            )
        except Exception:
            frappe.log_error(
                title="SEPA Mandate Usage Update Error",
                message=f"Failed to mark SEPA Mandate Usage collected for invoice {invoice_name}",
            )

    def _update_batch_status_after_processing(self, batch_doc, success_count: int) -> None:
        """Update batch status based on processing results.

        Persisted via db_set: the batch is submitted and the parent status write
        must not go through save() (UpdateAfterSubmitError on the non-allow_on_submit
        child rows / batch_log). No commit — stays within the request transaction.
        """
        total_invoices = len(batch_doc.invoices)

        if success_count == total_invoices:
            new_status = "Processed"
        elif success_count > 0:
            new_status = "Partially Processed"
        else:
            new_status = "Failed"

        batch_doc.db_set("status", new_status, update_modified=False)

    def _calculate_totals_python_fallback(self, batch_doc) -> None:
        """Fallback Python calculation when SQL fails"""
        totals = CalculationUtilities.calculate_document_totals_python(batch_doc.invoices)
        batch_doc.entry_count = totals["entry_count"]
        batch_doc.total_amount = totals["total_amount"]

        # Log fallback usage
        BatchLoggingUtilities.log_batch_operation(
            batch_doc.name,
            "Calculate Totals (Python Fallback)",
            {
                "entry_count": batch_doc.entry_count,
                "total_amount": batch_doc.total_amount,
                "method": "Python fallback",
            },
        )


# Singleton instance for global use
batch_processing_service = BatchProcessingService()
