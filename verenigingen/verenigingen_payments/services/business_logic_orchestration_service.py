"""
Business Logic Orchestration Service

This service handles complex business logic orchestration for SEPA direct debit operations.
Extracted from Direct Debit Batch system for better separation of concerns.
Contains the most complex business logic methods that coordinate multiple operations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.verenigingen_payments.services.batch_processing_service import batch_processing_service
from verenigingen.verenigingen_payments.services.batch_validation_service import batch_validation_service
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import sepa_xml_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    InvoiceManagementUtilities,
)


class BusinessLogicOrchestrationService:
    """Service for orchestrating complex SEPA business logic operations"""

    def __init__(self):
        self.config_service = sepa_config_service
        self.validation_service = batch_validation_service
        self.xml_service = sepa_xml_service
        self.batch_service = batch_processing_service

    def orchestrate_complete_batch_processing(self, batch_doc) -> Dict[str, Any]:
        """
        Orchestrate the complete batch processing workflow from validation to XML generation.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            Dictionary with orchestration results

        Raises:
            frappe.ValidationError: If any critical step fails
        """
        try:
            results = {
                "validation_passed": False,
                "xml_generated": False,
                "batch_ready": False,
                "errors": [],
                "warnings": [],
            }

            # Step 1: Comprehensive validation
            validation_result = self._orchestrate_batch_validation(batch_doc)
            results.update(validation_result)

            if not validation_result["validation_passed"]:
                return results

            # Step 2: Calculate optimized totals
            self.batch_service.calculate_batch_totals_optimized(batch_doc)

            # Step 3: Generate SEPA XML if validation passed
            if validation_result["validation_passed"]:
                xml_file = self.xml_service.generate_sepa_xml_for_batch(batch_doc)
                results["xml_generated"] = bool(xml_file)
                results["xml_file"] = xml_file

            # Step 4: Final readiness check
            results["batch_ready"] = self._verify_batch_readiness(batch_doc)

            # Log orchestration completion
            BatchLoggingUtilities.add_to_document_batch_log(
                batch_doc, f"Batch processing orchestration completed. Ready: {results['batch_ready']}"
            )

            return results

        except Exception as e:
            error_msg = f"Batch processing orchestration failed: {str(e)}"
            BatchLoggingUtilities.add_to_document_batch_log(batch_doc, error_msg)
            frappe.log_error(f"Orchestration error for batch {batch_doc.name}: {str(e)}")
            raise frappe.ValidationError(error_msg)

    def orchestrate_batch_creation_workflow(
        self, invoices: List[Dict[str, Any]], collection_date: str = None
    ) -> Dict[str, Any]:
        """
        Orchestrate the complete batch creation workflow from invoice selection to validation.

        Args:
            invoices: List of invoice data dictionaries
            collection_date: Optional collection date

        Returns:
            Dictionary with creation workflow results
        """
        try:
            results = {
                "batch_created": False,
                "batch_name": None,
                "total_amount": 0.0,
                "invoice_count": 0,
                "validation_results": {},
                "errors": [],
                "warnings": [],
            }

            # Step 1: Pre-creation validation
            creation_validation = batch_validation_service.validate_batch_creation(invoices, collection_date)
            if not creation_validation.is_valid:
                results["errors"] = creation_validation.errors
                return results

            # Step 2: Create batch document
            batch_doc = self._create_batch_document(invoices, collection_date)
            results["batch_created"] = bool(batch_doc)
            results["batch_name"] = batch_doc.name if batch_doc else None

            if not batch_doc:
                results["errors"].append("Failed to create batch document")
                return results

            # Step 3: Calculate totals
            totals = CalculationUtilities.calculate_batch_totals(invoices)
            results["total_amount"] = totals["total_amount"]
            results["invoice_count"] = totals["count"]

            # Step 4: Comprehensive post-creation validation
            validation_results = self._orchestrate_batch_validation(batch_doc)
            results["validation_results"] = validation_results

            # Step 5: Mandate coverage validation
            mandate_validation = batch_validation_service.validate_mandate_coverage(invoices)
            if not mandate_validation.is_valid:
                results["warnings"].extend(mandate_validation.details.get("missing_mandates", []))

            frappe.logger().info(f"Batch creation workflow completed for {results['invoice_count']} invoices")
            return results

        except Exception as e:
            error_msg = f"Batch creation workflow failed: {str(e)}"
            frappe.log_error(error_msg)
            results["errors"].append(error_msg)
            return results

    def orchestrate_payment_processing_workflow(self, batch_doc) -> Dict[str, Any]:
        """
        Orchestrate the complete payment processing workflow including reconciliation.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            Dictionary with payment processing results
        """
        try:
            results = {
                "processing_started": False,
                "payments_created": 0,
                "successful_payments": 0,
                "failed_payments": 0,
                "total_amount_processed": 0.0,
                "batch_status": "Unknown",
                "errors": [],
                "warnings": [],
            }

            # Step 1: Pre-processing validation
            if not batch_doc.sepa_file_generated:
                results["errors"].append("SEPA file must be generated before payment processing")
                return results

            # Step 2: Submit batch for processing
            submission_result = self.batch_service.process_batch_submission(batch_doc)
            results["processing_started"] = submission_result

            if not submission_result:
                results["errors"].append("Failed to submit batch for processing")
                return results

            # Step 3: Process payments
            successful_payments = self.batch_service.mark_batch_invoices_as_paid(batch_doc)
            results["successful_payments"] = successful_payments
            results["payments_created"] = len(batch_doc.invoices)
            results["failed_payments"] = len(batch_doc.invoices) - successful_payments

            # Step 4: Calculate processed amount
            processed_amount = 0.0
            for i, invoice_item in enumerate(batch_doc.invoices):
                if i < successful_payments:  # Assuming first N were successful
                    processed_amount += float(invoice_item.amount or 0)

            results["total_amount_processed"] = processed_amount
            results["batch_status"] = batch_doc.status

            # Step 5: Log processing summary
            BatchLoggingUtilities.add_to_document_batch_log(
                batch_doc,
                f"Payment processing completed: {successful_payments}/{len(batch_doc.invoices)} successful",
            )

            return results

        except Exception as e:
            error_msg = f"Payment processing workflow failed: {str(e)}"
            BatchLoggingUtilities.add_to_document_batch_log(batch_doc, error_msg)
            frappe.log_error(f"Payment processing error for batch {batch_doc.name}: {str(e)}")
            results["errors"].append(error_msg)
            return results

    def orchestrate_automated_batch_creation(self, collection_date: str = None) -> Dict[str, Any]:
        """
        Orchestrate automated batch creation for scheduled processing.

        Args:
            collection_date: Optional collection date (defaults to calculated date)

        Returns:
            Dictionary with automated creation results
        """
        try:
            results = {
                "batches_created": 0,
                "total_invoices": 0,
                "total_amount": 0.0,
                "created_batches": [],
                "errors": [],
                "warnings": [],
            }

            # Step 1: Calculate collection date if not provided
            if not collection_date:
                date_settings = self.config_service.get_collection_date_settings()
                offset_days = date_settings["offset_days"]
                collection_date = (datetime.now().date() + timedelta(days=offset_days)).strftime("%Y-%m-%d")

            # Step 2: Get eligible invoices
            eligible_invoices = self._get_eligible_invoices_for_automation(collection_date)

            if not eligible_invoices:
                results["warnings"].append("No eligible invoices found for automated batch creation")
                return results

            # Step 3: Group invoices by logical batches (e.g., by collection criteria)
            invoice_groups = self._group_invoices_for_batching(eligible_invoices)

            # Step 4: Create batches for each group
            for group_name, group_invoices in invoice_groups.items():
                try:
                    batch_result = self.orchestrate_batch_creation_workflow(group_invoices, collection_date)

                    if batch_result["batch_created"]:
                        results["batches_created"] += 1
                        results["total_invoices"] += batch_result["invoice_count"]
                        results["total_amount"] += batch_result["total_amount"]
                        results["created_batches"].append(
                            {
                                "batch_name": batch_result["batch_name"],
                                "group": group_name,
                                "invoice_count": batch_result["invoice_count"],
                                "total_amount": batch_result["total_amount"],
                            }
                        )
                    else:
                        results["errors"].extend(batch_result["errors"])

                except Exception as e:
                    error_msg = f"Failed to create batch for group {group_name}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.log_error(error_msg)

            # Step 5: Log automation summary
            frappe.logger().info(
                f"Automated batch creation completed: {results['batches_created']} batches, "
                f"{results['total_invoices']} invoices, €{results['total_amount']:,.2f}"
            )

            return results

        except Exception as e:
            error_msg = f"Automated batch creation failed: {str(e)}"
            frappe.log_error(error_msg)
            results["errors"].append(error_msg)
            return results

    def _orchestrate_batch_validation(self, batch_doc) -> Dict[str, Any]:
        """Orchestrate comprehensive batch validation"""
        results = {"validation_passed": True, "errors": [], "warnings": []}

        try:
            # Invoice validation
            invoice_validation = self.batch_service.validate_batch_invoices_optimized(batch_doc)
            if not invoice_validation["is_valid"]:
                results["validation_passed"] = False
                results["errors"].extend(invoice_validation["errors"])

            # Sequence type validation
            sequence_validation = self.batch_service.validate_sepa_sequence_types(batch_doc)
            if not sequence_validation["is_valid"]:
                results["warnings"].extend(sequence_validation["errors"])

            # Configuration validation
            config_validation = self.config_service.validate_sepa_configuration()
            if not config_validation["is_valid"]:
                results["validation_passed"] = False
                results["errors"].extend(config_validation["errors"])

            return results

        except Exception as e:
            results["validation_passed"] = False
            results["errors"].append(f"Validation orchestration failed: {str(e)}")
            return results

    def _verify_batch_readiness(self, batch_doc) -> bool:
        """Verify that batch is ready for processing"""
        try:
            # Check basic requirements
            if not batch_doc.invoices:
                return False

            if not batch_doc.sepa_file_generated:
                return False

            if batch_doc.status not in ["Generated", "Ready"]:
                return False

            # Check all invoices have required data
            for invoice in batch_doc.invoices:
                if not invoice.iban or not invoice.mandate_reference:
                    return False

            return True

        except Exception:
            return False

    def _create_batch_document(self, invoices: List[Dict[str, Any]], collection_date: str = None):
        """Create a new Direct Debit Batch document"""
        try:
            batch_doc = frappe.new_doc("Direct Debit Batch")
            batch_doc.collection_date = collection_date or frappe.utils.today()
            batch_doc.batch_date = frappe.utils.today()
            batch_doc.status = "Draft"

            # Add invoices to batch
            for invoice_data in invoices:
                batch_doc.append(
                    "invoices",
                    {
                        "invoice": invoice_data.get("name"),
                        "customer": invoice_data.get("customer"),
                        "amount": invoice_data.get("outstanding_amount", 0),
                        "currency": invoice_data.get("currency", "EUR"),
                        "iban": invoice_data.get("iban"),
                        "mandate_reference": invoice_data.get("mandate_reference"),
                        "membership": invoice_data.get("membership"),
                    },
                )

            batch_doc.insert()
            return batch_doc

        except Exception as e:
            frappe.log_error(f"Error creating batch document: {str(e)}")
            return None

    def _get_eligible_invoices_for_automation(self, collection_date: str) -> List[Dict[str, Any]]:
        """Get invoices eligible for automated batch creation"""
        try:
            # Get unpaid invoices with SEPA mandates
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
                    "outstanding_amount": [">", 0],
                    "currency": "EUR",
                    "due_date": ["<=", collection_date],
                },
                fields=["name", "customer", "outstanding_amount", "currency", "due_date", "posting_date"],
            )

            # Filter for customers with active SEPA mandates
            eligible_invoices = []
            for invoice in invoices:
                mandate = frappe.get_value(
                    "SEPA Mandate",
                    {
                        "customer": invoice["customer"],
                        "status": "Active",
                        "valid_from": ["<=", collection_date],
                        "valid_until": [">=", collection_date],
                    },
                    ["name", "iban", "mandate_reference"],
                )

                if mandate:
                    invoice.update({"iban": mandate[1], "mandate_reference": mandate[2]})
                    eligible_invoices.append(invoice)

            return eligible_invoices

        except Exception as e:
            frappe.log_error(f"Error getting eligible invoices: {str(e)}")
            return []

    def _group_invoices_for_batching(self, invoices: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group invoices into logical batches"""
        try:
            # Simple grouping by due date month for now
            # This can be made more sophisticated based on business rules
            groups = {}

            for invoice in invoices:
                due_date = invoice.get("due_date")
                if due_date:
                    month_key = (
                        due_date.strftime("%Y-%m") if hasattr(due_date, "strftime") else str(due_date)[:7]
                    )
                    group_name = f"batch_{month_key}"

                    if group_name not in groups:
                        groups[group_name] = []

                    groups[group_name].append(invoice)

            # Ensure no group exceeds batch size limits
            limits = self.config_service.get_batch_processing_limits()
            max_batch_size = limits["max_batch_size"]

            final_groups = {}
            for group_name, group_invoices in groups.items():
                if len(group_invoices) <= max_batch_size:
                    final_groups[group_name] = group_invoices
                else:
                    # Split large groups
                    for i in range(0, len(group_invoices), max_batch_size):
                        split_group_name = f"{group_name}_part{i // max_batch_size + 1}"
                        final_groups[split_group_name] = group_invoices[i : i + max_batch_size]

            return final_groups

        except Exception as e:
            frappe.log_error(f"Error grouping invoices: {str(e)}")
            return {"default": invoices}  # Fallback to single group


# Singleton instance for global use
business_logic_service = BusinessLogicOrchestrationService()
