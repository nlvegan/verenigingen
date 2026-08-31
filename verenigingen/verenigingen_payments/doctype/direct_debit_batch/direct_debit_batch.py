"""
Direct Debit Batch DocType Implementation

This module implements the Direct Debit Batch DocType for SEPA-compliant
direct debit processing in the Verenigingen association management system.
It handles the complete lifecycle of direct debit batch processing including
validation, SEPA XML generation, and bank submission.

Key Features:
    - SEPA Direct Debit Core Scheme compliance
    - Comprehensive invoice validation and processing
    - SEPA XML file generation with proper formatting
    - Mandate usage tracking and sequence type management
    - Batch totals calculation and validation
    - Error handling and transaction safety

Business Process:
    1. Batch Creation: Aggregate unpaid invoices into processing batches
    2. Validation: Comprehensive validation of invoices, mandates, and bank details
    3. SEPA Generation: Create SEPA-compliant XML files for bank submission
    4. Processing: Track submission status and bank responses
    5. Reconciliation: Match bank confirmations with batch entries

Compliance Features:
    - SEPA Direct Debit Core Scheme (SDD Core) compliance
    - Dutch banking standards (IBAN validation, mandate management)
    - SEPA XML format validation (pain.008.001.08)
    - Mandate sequence type management (FRST, RCUR, OOFF, FNAL)
    - Creditor identifier validation and management

Security Model:
    - Comprehensive validation of financial data
    - Mandate authorization verification
    - IBAN format validation and verification
    - Audit logging for all batch operations
    - Transaction safety with rollback capabilities

Integration Points:
    - Sales Invoice system for payment processing
    - SEPA Mandate Management for authorization
    - Bank account and customer information systems
    - Financial reporting and reconciliation systems
    - eBoekhouden integration for accounting

Technical Implementation:
    - XML generation with proper namespaces and validation
    - Temporary file management for SEPA file creation
    - Error handling with detailed validation messages
    - Performance optimization for large batch processing

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.verenigingen_payments.services.batch_processing_service import batch_processing_service
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import sepa_xml_service
from verenigingen.verenigingen_payments.utils.financial_error_handler import handle_data_integrity_error
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    FileManagementUtilities,
    InvoiceManagementUtilities,
    SEPAXMLValidator,
)


class DirectDebitBatch(Document):
    def validate(self):
        """Validation logic - runs on save"""
        # All document-modifying logic runs here during save
        self.validate_no_duplicate_invoices()
        self.validate_invoices()
        self.validate_sequence_types()
        self.calculate_totals()

    def validate_no_duplicate_invoices(self):
        """Reject a batch that lists the same Sales Invoice more than once (#606).

        Each child row becomes one transaction in the SEPA XML, so two rows for
        one invoice are two debits of one member's account for one debt. Nothing
        upstream deduplicates:

        - `batch_processing_service.validate_batch_invoices_optimized` validates
          each row's Sales Invoice in isolation and never compares the rows to
          each other (measured -- it reports a duplicated invoice as two valid
          rows);
        - `batch_performance_optimizer.process_batch_invoices_optimized` iterates
          its `invoice_names` argument as a list;
        - `dd_batch_optimizer`'s `processed_invoices` set removes invoices already
          claimed by an EARLIER batching strategy, never duplicates within one
          group.

        Every batch pipeline ends at this document's `save()`/`insert()` -- 14
        persistence statements across 8 production files, and no production code
        INSERTS a `Direct Debit Batch Invoice` row without going through its
        parent. It says inserts, not writes, deliberately: `dd_batch_api.
        apply_conflict_resolutions` loads existing child rows standalone and
        `save()`s and `delete_doc()`s them (see the consolidation note below), so
        those mutations never re-enter this check.
        So one check here covers the class rather than one dedup per producer, and
        it fails the batch loudly instead of quietly collecting twice.

        WHY IT THROWS EVEN UNDER `_automated_processing`, and the cost. The
        sequence-type criticals below are recorded on the document and acted on by
        `sepa_batch_notifications.handle_automated_batch_validation`, which flips
        the batch to "Validation Failed" and notifies. `dd_batch_optimizer.
        create_dd_batch_document` never calls it -- it inserts and never reads
        `validation_status` -- but its scheduler caller `dd_batch_scheduler` DOES,
        for every batch name `create_optimal_batches` returns. So the recorded
        route is not unreachable, and throwing has a real price on that pipeline:
        `create_optimal_batches` wraps the whole group loop in `except Exception`,
        so a duplicate in group 3 stops groups 4+ being built. It USED TO also
        report `batches_created: 0` while groups 1-2 sat inserted and committed,
        and `dd_batch_scheduler` USED TO read that as "No batches created - no
        eligible invoices" through `frappe.logger().info` -- a rotating file at
        level ERROR that reaches nobody -- so a lost month looked like a quiet
        no-op, and the retry is not the next day but the next configured creation
        day (`batch_creation_days`, default `"1"`). #627 fixed that half: the
        failure now names the batches it already committed, lands in the Error Log
        with its traceback and raises a system notification.
        The tradeoff is still taken deliberately: a lost optimization run is
        recoverable and re-runnable by hand, whereas a batch that persists with a
        duplicate can be submitted by a path that never reads `validation_status`
        -- and that money does not come back. #627 also removed the reachable
        PRODUCER (an unbounded SEPA Mandate join in both automated collection
        queries) and added a producer-side refusal that drops a duplicated invoice
        rather than the run, so reaching this throw now takes a route neither
        producer has. #662 is the known remaining one -- the same unbounded join in
        `dd_batch_api.get_eligible_invoices` -- which has no working in-tree consumer
        today only because of #679.

        SCOPE. This is a WITHIN-batch check. Two batches each listing the invoice
        once are still two debits, and the guard cannot see that;
        `sepa_batch_ui`/`_secure` check it per invoice ("already in batch X") and
        `dd_batch_optimizer` excludes already-batched invoices in SQL evaluated
        once per run, before any batch in that run exists.

        It also cannot see a duplicate that has been MERGED rather than removed --
        one row carrying the sum of two -- because there genuinely is one row per
        invoice afterwards. That shape was reachable through
        `dd_batch_api.apply_conflict_resolutions`' `consolidate_entries`, which
        grouped rows by `mandate_reference` and summed the group; it now keys on
        the invoice and removes duplicate rows without summing (#613), so the only
        producer of it is gone. The blind spot itself remains: any future code that
        collapses two rows into one carrying their sum would pass this check.
        """
        rows_by_invoice = {}
        for position, row in enumerate(self.invoices or [], start=1):
            if row.invoice:
                rows_by_invoice.setdefault(row.invoice, []).append(position)

        duplicates = {inv: rows for inv, rows in rows_by_invoice.items() if len(rows) > 1}
        if not duplicates:
            return

        # Name the invoice AND the row numbers: an operator has to find the rows
        # to delete, and a batch can be hundreds of lines long.
        listed = "; ".join(
            "{0} (rows {1})".format(invoice, ", ".join(str(r) for r in rows))
            for invoice, rows in sorted(duplicates.items())
        )
        frappe.throw(
            _(
                "This batch lists the same invoice more than once, which would "
                "debit the member more than once for one debt: {0}. Remove the "
                "duplicate rows."
            ).format(listed)
        )

    def validate_invoices(self):
        """Validate that all invoices are valid for direct debit using performance optimization"""
        validation_result = batch_processing_service.validate_batch_invoices_optimized(self)

        if not validation_result["is_valid"] and validation_result["valid_invoices"] == 0:
            frappe.throw(_("No valid invoices found in batch"))

        if validation_result.get("has_warnings"):
            frappe.msgprint(_("Some invoice validation warnings were found. Check batch log for details."))

    def validate_sequence_types(self):
        """Validate SEPA sequence types for automated batch processing"""
        if not self.invoices:
            return

        # Import here to avoid circular imports
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        critical_errors = []
        warnings = []

        for invoice in self.invoices:
            if not invoice.mandate_reference:
                # NOT caught by validate_invoices, whatever the comment that used
                # to sit here claimed (#606). That path calls
                # `InvoiceManagementUtilities.validate_invoice_for_sepa`, which
                # reads name/customer/outstanding_amount/currency/status off the
                # Sales Invoice and never looks at the batch row's
                # mandate_reference at all -- measured: a row with none comes back
                # is_valid, errors []. A row with no mandate reference has no
                # MndtId to present in the SEPA XML, so it cannot be collected.
                #
                # What DOES catch it on the way to the database is
                # `mandate_reference` being `reqd: 1` on Direct Debit Batch
                # Invoice: `validate` runs before `_validate_mandatory`, so in the
                # manual path this critical error fires first and says something
                # an operator can act on, but in the automated path the recorded
                # `validation_status` is never observed -- the insert dies on
                # MandatoryError before anything can read it. This branch is
                # therefore about the ERROR MESSAGE, not about a state that would
                # otherwise reach the bank.
                critical_errors.append(
                    {
                        "invoice": invoice.invoice,
                        "issue": "No mandate reference on batch row",
                        "mandate_reference": None,
                    }
                )
                continue

            # Get mandate for this member
            mandate_name = frappe.db.get_value(
                "SEPA Mandate", {"mandate_id": invoice.mandate_reference, "status": "Active"}, "name"
            )

            if not mandate_name:
                critical_errors.append(
                    {
                        "invoice": invoice.invoice,
                        "issue": "No active mandate found for reference",
                        "mandate_reference": invoice.mandate_reference,
                    }
                )
                continue

            # Get expected sequence type
            try:
                expected_info = get_mandate_sequence_type(mandate_name, invoice.invoice)
                expected_type = expected_info["sequence_type"]

                # Compare with actual sequence type
                if hasattr(invoice, "sequence_type") and invoice.sequence_type:
                    if invoice.sequence_type != expected_type:
                        # Classify error severity
                        if expected_type == "FRST" and invoice.sequence_type == "RCUR":
                            critical_errors.append(
                                {
                                    "invoice": invoice.invoice,
                                    "issue": "RCUR used for first mandate usage - SEPA compliance violation",
                                    "expected": expected_type,
                                    "actual": invoice.sequence_type,
                                    "reason": expected_info.get("reason", ""),
                                }
                            )
                        else:
                            warnings.append(
                                {
                                    "invoice": invoice.invoice,
                                    "issue": "Sequence type mismatch - review recommended",
                                    "expected": expected_type,
                                    "actual": invoice.sequence_type,
                                    "reason": expected_info.get("reason", ""),
                                }
                            )
                else:
                    # No sequence type set - auto-assign the correct one
                    invoice.sequence_type = expected_type

            except Exception as e:
                critical_errors.append(
                    {
                        "invoice": invoice.invoice,
                        "issue": f"Error determining sequence type: {str(e)}",
                        "mandate_reference": invoice.mandate_reference,
                    }
                )

        # Handle validation results
        if critical_errors:
            # Store validation results for automated processing
            self.validation_status = "Critical Errors"
            self.validation_errors = frappe.as_json(critical_errors)
            if warnings:
                self.validation_warnings = frappe.as_json(warnings)

            # In automated context, we'll handle this gracefully
            # In manual context, throw error immediately
            if not getattr(self, "_automated_processing", False):
                error_messages = []
                for error in critical_errors:
                    error_messages.append(f"Invoice {error['invoice']}: {error['issue']}")

                frappe.throw(
                    _("Critical sequence type validation errors found:\n{0}").format(
                        "\n".join(error_messages)
                    )
                )

        elif warnings:
            # Store warnings but allow processing
            self.validation_status = "Warnings"
            self.validation_warnings = frappe.as_json(warnings)

            # Log warnings using frappe.log_error for better error tracking
            for warning in warnings:
                frappe.log_error(
                    f"Sequence type warning for invoice {warning['invoice']}: {warning['issue']}",
                    "Direct Debit Batch Sequence Warning",
                )

        else:
            self.validation_status = "Passed"

    def calculate_totals(self):
        """Calculate batch totals - optimized with database aggregation for large batches"""
        # For a not-yet-persisted document the child rows are only in memory
        # (self.invoices) and are NOT in `tabDirect Debit Batch Invoice` yet, so
        # the SQL aggregation below would return 0 and clobber the real total.
        # Compute from the in-memory rows in that case.
        if self.is_new() or not self.name:
            self._calculate_totals_python()
            return

        batch_processing_service.calculate_batch_totals_optimized(self)
        try:
            result = frappe.db.sql(
                """
                SELECT
                    COUNT(*) as entry_count,
                    SUM(COALESCE(amount, 0)) as total_amount
                FROM `tabDirect Debit Batch Invoice`
                WHERE parent = %s
            """,
                self.name,
                as_dict=True,
            )

            if result and result[0]:
                stats = result[0]
                self.entry_count = stats.entry_count or 0
                self.total_amount = stats.total_amount or 0.0
            else:
                self.entry_count = 0
                self.total_amount = 0.0

        except Exception as e:
            # For financial processing, SQL aggregation failure is critical
            # Log error and use fallback, but validate results strictly
            frappe.log_error(
                f"SQL aggregation failed for batch {self.name}: {str(e)}",
                "DirectDebitBatch - Critical Calculation Error",
            )

            # Use fallback but validate consistency
            self._calculate_totals_python()

            # Verify we have reasonable values after fallback
            if self.entry_count < 0 or self.total_amount < 0:
                handle_data_integrity_error(
                    "F3001",
                    {
                        "batch_name": self.name,
                        "entry_count": self.entry_count,
                        "total_amount": self.total_amount,
                    },
                )

    def _calculate_totals_python(self):
        """Fallback Python calculation for new documents or when SQL fails"""
        totals = CalculationUtilities.calculate_document_totals_python(self.invoices)
        self.entry_count = totals["entry_count"]
        self.total_amount = totals["total_amount"]

    def before_submit(self):
        """Reject submitting a batch scheduled to collect on a date in the past.

        A SEPA direct-debit collection date must be today or in the future -- banks
        require advance notice and cannot execute a debit dated in the past. This
        guards only the real submit path: historical batches recorded for
        reconciliation set docstatus directly in the DB and never call submit(), so
        they are unaffected. Previously nothing validated batch_date against today.
        """
        if self.batch_date and getdate(self.batch_date) < getdate(today()):
            frappe.throw(
                _(
                    "Batch date {0} is in the past. A SEPA collection cannot be scheduled "
                    "for a past date -- set the batch date to today or a future date."
                ).format(self.batch_date)
            )

    def on_submit(self):
        """Generate SEPA file on submit if not already generated"""
        if not self.sepa_file_generated:
            self.generate_sepa_xml()

    def on_cancel(self):
        """Handle batch cancellation"""
        self.status = "Cancelled"
        self.add_to_batch_log(_("Batch cancelled"))

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def generate_sepa_xml(self):
        """Generate SEPA Direct Debit XML file for Dutch banks"""
        return sepa_xml_service.generate_sepa_xml_for_batch(self)

    def attach_sepa_file(self, file_path):
        """Attach SEPA file to document"""
        return FileManagementUtilities.attach_file_to_document(file_path, self.doctype, self.name)

    def add_to_batch_log(self, message):
        """Add message to batch log"""
        BatchLoggingUtilities.add_to_document_batch_log(self, message)

    def process_batch(self):
        """Process the batch - to be implemented based on bank requirements"""
        # This would typically involve sending the SEPA file to the bank
        try:
            if not self.sepa_file_generated:
                frappe.throw(_("SEPA file must be generated before processing"))

            # Set status to submitted
            self.status = "Submitted"
            self.add_to_batch_log(_("Batch submitted for processing"))
            self.save()

            # Here you would add code to communicate with your bank's API
            # For now, this is a placeholder

            frappe.logger().info(f"Batch {self.name} submitted for processing")
            return True
        except Exception as e:
            error_msg = _("Error processing batch: {0}").format(str(e))
            self.add_to_batch_log(error_msg)
            frappe.log_error(f"Error processing batch {self.name}: {str(e)}", "SEPA Direct Debit Batch Error")
            frappe.throw(error_msg)

    def update_invoice_status(self, invoice_index, status, result_code=None, result_message=None):
        """Update status of a specific invoice in the batch"""
        try:
            InvoiceManagementUtilities.update_batch_invoice_status(
                self.invoices, invoice_index, status, result_code, result_message
            )
            self.save()
        except IndexError:
            frappe.throw(_("Invalid invoice index"))

    def mark_invoices_as_paid(self):
        """Mark all invoices in the batch as paid"""
        return batch_processing_service.mark_batch_invoices_as_paid(self)

    def _validate_sepa_xml_schema(self, xml_string):
        """Validate SEPA XML against pain.008.001.08 schema (Recommendation #3)"""
        return SEPAXMLValidator.validate_sepa_xml_schema(xml_string, self.name)


# Helper Functions


def create_payment_entry_for_invoice(invoice, payment_type, mode_of_payment, reference_no, reference_date):
    """
    Create a payment entry for an invoice.

    Args:
        invoice: Sales Invoice document
        payment_type: Type of payment (Receive/Pay)
        mode_of_payment: Payment method
        reference_no: Payment reference number
        reference_date: Payment reference date

    Returns:
        PaymentEntry: Created and submitted payment entry

    Raises:
        frappe.PermissionError: If user lacks payment entry permissions
        frappe.ValidationError: If amount is invalid
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


def get_bic_from_iban(iban):
    """
    Try to determine BIC from IBAN.

    Uses canonical iban_validator which supports 25+ Dutch banks
    (including BITV, FVLB, HAND, DHBN, NWAB, COBA, DEUT, FBHL, NNBA, etc.)
    """
    from verenigingen.utils.validation.iban_validator import derive_bic_from_iban

    return derive_bic_from_iban(iban)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_batch(batch_name: str):
    """Process a direct debit batch"""
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)
        batch.check_permission("write")

        if batch.docstatus != 1:
            frappe.throw(_("Batch must be submitted before processing"))

        if not batch.sepa_file_generated:
            batch.generate_sepa_xml()

        result = batch.process_batch()

        return result
    except Exception as e:
        frappe.log_error(
            f"Error processing batch {batch_name}: {str(e)}", "SEPA Direct Debit Batch Processing Error"
        )
        frappe.throw(_("Error processing batch: {0}").format(str(e)))


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def mark_invoices_as_paid(batch_name: str):
    """Mark all invoices in a batch as paid"""
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)
        batch.check_permission("write")

        if batch.docstatus != 1:
            frappe.throw(_("Batch must be submitted before marking invoices as paid"))

        success_count = batch.mark_invoices_as_paid()

        return success_count
    except Exception as e:
        frappe.log_error(
            f"Error marking invoices as paid for batch {batch_name}: {str(e)}",
            "SEPA Direct Debit Payment Error",
        )
        frappe.throw(_("Error marking invoices as paid: {0}").format(str(e)))


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_enhanced_dues_batch(collection_date=None):
    """
    Create a direct debit batch using the enhanced processor for membership dues schedules
    This is the new enhanced method that works with the flexible dues system
    """
    try:
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor

        processor = SEPAProcessor()
        batch = processor.create_dues_collection_batch(collection_date)

        if batch:
            frappe.msgprint(
                _("Enhanced SEPA Dues Batch {0} created with {1} invoices totaling €{2}").format(
                    batch.name, len(batch.invoices), batch.total_amount
                )
            )
            return batch.name
        else:
            frappe.msgprint(_("No eligible dues schedules found for collection"))
            return None

    except Exception as e:
        frappe.log_error(
            f"Error creating enhanced dues batch: {str(e)}", "Enhanced SEPA Dues Batch Creation Error"
        )
        frappe.throw(_("Error creating enhanced dues batch: {0}").format(str(e)))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_dues_collection_preview(collection_date=None, days_ahead=30):
    """
    Get a preview of upcoming dues collections without creating batches
    """
    try:
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import (
            get_upcoming_dues_collections,
        )

        collections = get_upcoming_dues_collections(days_ahead)

        return {
            "success": True,
            "collections": collections,
            "total_dates": len(collections),
            "total_schedules": sum(c["count"] for c in collections),
            "total_amount": sum(c["total_amount"] for c in collections),
        }

    except Exception as e:
        frappe.log_error(f"Error getting dues collection preview: {str(e)}", "Dues Collection Preview Error")
        return {"success": False, "error": str(e)}
