"""
Batch Processing Service

This service handles medium complexity batch processing operations for SEPA direct debit.
Extracted from Direct Debit Batch system for better separation of concerns.
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.verenigingen_payments.services.batch_validation_service import batch_validation_service
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    InvoiceManagementUtilities,
)


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

        for i, invoice_item in enumerate(batch_doc.invoices):
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

                # Update batch invoice status
                InvoiceManagementUtilities.update_batch_invoice_status(
                    batch_doc.invoices, i, "Successful", "PDNG", f"Payment entry {payment_entry.name} created"
                )

                # Update membership payment status
                if hasattr(invoice_item, "membership") and invoice_item.membership:
                    self._update_membership_payment_status(invoice_item.membership)

                success_count += 1

            except Exception as e:
                InvoiceManagementUtilities.update_batch_invoice_status(
                    batch_doc.invoices, i, "Failed", "RJCT", f"Error: {str(e)}"
                )
                frappe.log_error(
                    f"Error processing payment for invoice {invoice_item.invoice}: {str(e)}",
                    "SEPA Direct Debit Payment Error",
                )

        # Update batch status
        self._update_batch_status_after_processing(batch_doc, success_count)

        # Log results
        BatchLoggingUtilities.add_to_document_batch_log(
            batch_doc, f"Processed {success_count} of {len(batch_doc.invoices)} invoices"
        )

        batch_doc.save()
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
                f"Error processing batch {batch_doc.name}: {str(e)}", "SEPA Direct Debit Batch Error"
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

        except Exception as e:
            from verenigingen.verenigingen_payments.utils.financial_error_handler import (
                handle_data_integrity_error,
            )

            handle_data_integrity_error(e, "batch invoice validation", batch_doc.name)
            raise

    def validate_sepa_sequence_types(self, batch_doc) -> Dict[str, Any]:
        """
        Validate SEPA sequence types for automated batch processing.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            Dictionary with validation results and any corrections made
        """
        if not batch_doc.invoices:
            return {"is_valid": True, "corrections": 0, "errors": []}

        corrections_made = 0
        validation_errors = []
        sequence_type_stats = {"FRST": 0, "RCUR": 0, "OOFF": 0, "FNAL": 0}

        try:
            # Get all mandate information in bulk for performance
            customer_list = [invoice.customer for invoice in batch_doc.invoices if invoice.customer]
            mandate_data = self._get_mandate_sequence_types_bulk(customer_list, batch_doc.collection_date)

            for invoice_item in batch_doc.invoices:
                customer = invoice_item.customer
                current_sequence = getattr(invoice_item, "sequence_type", None)

                if customer in mandate_data:
                    correct_sequence = mandate_data[customer]["sequence_type"]

                    # Update sequence type if incorrect or missing
                    if current_sequence != correct_sequence:
                        invoice_item.sequence_type = correct_sequence
                        invoice_item.mandate_reference = mandate_data[customer]["mandate_reference"]
                        corrections_made += 1

                    # Update statistics
                    if correct_sequence in sequence_type_stats:
                        sequence_type_stats[correct_sequence] += 1
                else:
                    validation_errors.append(f"No valid mandate found for customer {customer}")

            # Log validation results
            if corrections_made > 0:
                BatchLoggingUtilities.add_to_document_batch_log(
                    batch_doc, f"Corrected {corrections_made} sequence types automatically"
                )

            # Log sequence type distribution
            sequence_summary = ", ".join(
                [f"{seq}: {count}" for seq, count in sequence_type_stats.items() if count > 0]
            )
            BatchLoggingUtilities.add_to_document_batch_log(
                batch_doc, f"Sequence type distribution: {sequence_summary}"
            )

            return {
                "is_valid": len(validation_errors) == 0,
                "corrections": corrections_made,
                "errors": validation_errors,
                "sequence_stats": sequence_type_stats,
            }

        except Exception as e:
            frappe.log_error(f"Error validating sequence types for batch {batch_doc.name}: {str(e)}")
            validation_errors.append(f"Sequence type validation failed: {str(e)}")
            return {
                "is_valid": False,
                "corrections": corrections_made,
                "errors": validation_errors,
                "sequence_stats": sequence_type_stats,
            }

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
            Exception: For other payment creation errors
        """
        try:
            # Get payment entry using ERPNext's built-in function
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

            payment_entry = get_payment_entry(invoice.doctype, invoice.name)
            payment_entry.mode_of_payment = mode_of_payment
            payment_entry.reference_no = reference_no
            payment_entry.reference_date = reference_date
            payment_entry.paid_amount = invoice.outstanding_amount
            payment_entry.received_amount = invoice.outstanding_amount

            # Insert and submit payment entry
            payment_entry.insert()
            payment_entry.submit()

            return payment_entry

        except frappe.PermissionError as e:
            from verenigingen.verenigingen_payments.utils.financial_error_handler import (
                handle_permission_error,
            )

            handle_permission_error(e, "create payment entry", f"invoice {invoice.name}")
            raise
        except Exception as e:
            frappe.log_error(
                f"Error creating payment entry for invoice {invoice.name}: {str(e)}",
                "SEPA Payment Entry Creation Error",
            )
            raise

    def _update_membership_payment_status(self, membership_name: str) -> None:
        """
        Update payment status on membership after successful payment.

        Args:
            membership_name: Name of the membership to update
        """
        try:
            if not membership_name:
                return

            membership = frappe.get_doc("Membership", membership_name)
            membership.payment_status = "Paid"
            membership.save()

            frappe.logger().info(f"Updated payment status for membership {membership_name}")

        except Exception as e:
            frappe.log_error(
                f"Error updating membership payment status for {membership_name}: {str(e)}",
                "Membership Payment Status Update Error",
            )
            # Don't raise - this is not critical for payment processing

    def _update_batch_status_after_processing(self, batch_doc, success_count: int) -> None:
        """Update batch status based on processing results"""
        total_invoices = len(batch_doc.invoices)

        if success_count == total_invoices:
            batch_doc.status = "Processed"
        elif success_count > 0:
            batch_doc.status = "Partially Processed"
        else:
            batch_doc.status = "Failed"

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

    def _get_mandate_sequence_types_bulk(
        self, customer_list: List[str], collection_date
    ) -> Dict[str, Dict[str, str]]:
        """
        Get mandate sequence types for multiple customers in bulk.

        Args:
            customer_list: List of customer names
            collection_date: Collection date for sequence type determination

        Returns:
            Dictionary mapping customer names to mandate info
        """
        try:
            # Get active mandates for all customers
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={
                    "customer": ["in", customer_list],
                    "status": "Active",
                    "valid_from": ["<=", collection_date],
                    "valid_until": [">=", collection_date],
                },
                fields=["customer", "mandate_reference", "sequence_type", "last_used_date"],
            )

            mandate_data = {}
            for mandate in mandates:
                customer = mandate["customer"]

                # Determine sequence type based on usage
                if not mandate.get("last_used_date"):
                    sequence_type = "FRST"  # First usage
                else:
                    sequence_type = "RCUR"  # Recurring usage

                mandate_data[customer] = {
                    "mandate_reference": mandate["mandate_reference"],
                    "sequence_type": sequence_type,
                }

            return mandate_data

        except Exception as e:
            frappe.log_error(f"Error getting mandate sequence types: {str(e)}")
            return {}


# Singleton instance for global use
batch_processing_service = BatchProcessingService()
