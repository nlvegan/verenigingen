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
        self.validate_invoices()
        self.validate_sequence_types()
        self.calculate_totals()

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
                continue  # Will be caught by validate_invoices

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


def update_membership_payment_status(membership_name):
    """Update payment status on membership"""
    try:
        membership = frappe.get_doc("Membership", membership_name)
        membership.payment_status = "Paid"
        membership.payment_date = today()

        # If membership is in Pending status, change to Active
        if membership.status == "Pending":
            membership.status = "Active"

        membership.flags.ignore_validate_update_after_submit = True
        membership.save()

        frappe.logger().info(f"Updated payment status for membership {membership_name}")
        return membership
    except Exception as e:
        frappe.log_error(
            f"Error updating membership payment status for {membership_name}: {str(e)}",
            "Membership Update Error",
        )
        raise


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
def generate_direct_debit_batch(date=None):
    """
    Create a direct debit batch for unpaid membership invoices
    This can be called via JS or scheduled jobs
    """
    try:
        from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
            create_direct_debit_batch,
        )

        batch = create_direct_debit_batch(date)

        if batch:
            frappe.msgprint(
                _("SEPA Direct Debit Batch {0} created with {1} entries").format(
                    batch.name, batch.entry_count
                )
            )
            return batch.name
        else:
            frappe.msgprint(_("No eligible invoices found for direct debit"))
            return None
    except Exception as e:
        frappe.log_error(
            f"Error generating direct debit batch: {str(e)}", "SEPA Direct Debit Batch Generation Error"
        )
        frappe.throw(_("Error generating direct debit batch: {0}").format(str(e)))


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
def create_direct_debit_batch_for_unpaid_memberships():
    """
    Create a batch for direct debit payments for unpaid memberships
    This is meant to be scheduled daily via hooks.py
    """
    try:
        from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
            get_unpaid_membership_invoices,
        )

        # Get all unpaid invoices for memberships with SEPA Direct Debit payment method
        unpaid_invoices = get_unpaid_membership_invoices()

        if not unpaid_invoices:
            frappe.logger().info("No unpaid membership invoices found for direct debit")
            return None

        # Create a new batch
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_description = f"Membership payments batch - {frappe.utils.today()}"
        batch.batch_type = "RCUR"  # Recurring direct debit
        batch.currency = "EUR"  # Default currency

        # Add invoices to batch
        for invoice in unpaid_invoices:
            batch.append(
                "invoices",
                {
                    "invoice": invoice["invoice"],
                    "membership": invoice["membership"],
                    "member": invoice["member"],
                    "member_name": invoice["member_name"],
                    "amount": invoice["amount"],
                    "currency": invoice["currency"],
                    "bank_account": invoice["bank_account"],
                    "iban": invoice["iban"],
                    "mandate_reference": invoice["mandate_reference"],
                    "status": "Pending",
                },
            )

        # Calculate totals
        batch.total_amount = sum(invoice["amount"] for invoice in unpaid_invoices)
        batch.entry_count = len(unpaid_invoices)

        # Save the batch
        batch.insert()

        frappe.logger().info(f"Created direct debit batch {batch.name} with {batch.entry_count} invoices")

        return batch.name
    except Exception as e:
        frappe.log_error(
            f"Error creating direct debit batch for unpaid memberships: {str(e)}",
            "SEPA Direct Debit Batch Creation Error",
        )
        return None


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
