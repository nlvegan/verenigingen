# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class SEPAAuditLog(Document):
    """
    SEPA Audit Log DocType

    Stores comprehensive audit trails for all SEPA compliance operations
    including mandate creation, batch processing, and payment workflows.
    """

    def validate(self):
        """Validate audit log entry"""
        # Ensure timestamp is set
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Set user if not provided
        if not self.user:
            self.user = frappe.session.user

        # Generate trace ID if not provided
        if not self.trace_id:
            self.trace_id = frappe.local.request_id or frappe.generate_hash(length=10)

        # Validate compliance status
        valid_statuses = ["Compliant", "Exception", "Failed", "Pending Review"]
        if self.compliance_status not in valid_statuses:
            frappe.throw(f"Invalid compliance status. Must be one of: {', '.join(valid_statuses)}")

    def before_insert(self):
        """Before insert hook"""
        # Set creation timestamp
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Generate event ID if not provided
        if not self.event_id:
            self.event_id = frappe.generate_hash(length=12)

    def on_trash(self):
        """Prevent manual deletion of audit logs"""
        # Only allow deletion by system or during cleanup
        if frappe.session.user not in ["Administrator", "System"]:
            frappe.throw("Audit logs cannot be manually deleted")

    @staticmethod
    def log_sepa_event(process_type, reference_doc, action, details=None):
        """
        Log SEPA compliance events with full audit trail

        Args:
            process_type: Type of SEPA process (Mandate Creation, Batch Generation, etc.)
            reference_doc: Reference document object
            action: Action being performed
            details: Additional details dict

        Returns:
            SEPAAuditLog document
        """
        try:
            # Ensure details is a dict
            if details is None:
                details = {}

            # Create audit log entry
            doc = frappe.new_doc("SEPA Audit Log")
            doc.update(
                {
                    "event_id": frappe.generate_hash(length=12),
                    "timestamp": frappe.utils.now(),
                    "process_type": process_type,
                    "action": action,
                    "compliance_status": details.get("compliance_status", "Compliant"),
                    "details": json.dumps(details),
                    "sensitive_data": details.get("sensitive_data", False),
                }
            )

            # Set reference if provided and exists in database
            if reference_doc:
                # Only set reference if the document actually exists in the database
                if hasattr(reference_doc, "name") and frappe.db.exists(
                    reference_doc.doctype, reference_doc.name
                ):
                    doc.reference_doctype = reference_doc.doctype
                    doc.reference_name = reference_doc.name

            # Insert without permissions check (system operation)
            doc.insert(ignore_permissions=True)
            return doc

        except Exception as e:
            frappe.log_error(f"SEPA audit logging failed: {str(e)}")
            # For debugging, let's also print the error
            print(f"SEPA audit logging error: {str(e)}")
            return None

    @staticmethod
    def log_mandate_creation(member, mandate, iban, bic, success=True, error_msg=None):
        """
        Log SEPA mandate creation with comprehensive details

        Args:
            member: Member document
            mandate: SEPA Mandate document (if successful)
            iban: IBAN provided
            bic: BIC provided
            success: Whether creation was successful
            error_msg: Error message if failed
        """
        details = {
            "member": member.name if member else None,
            "member_name": f"{member.get('first_name', '')} {member.get('last_name', '')}"
            if member
            else None,
            "iban_masked": iban[:4] + "****" + iban[-4:] if iban and len(iban) > 8 else "****",
            "bic": bic,
            "authorization_method": "online_portal",
            "compliance_status": "Compliant" if success else "Failed",
            "validation_checks": {
                "iban_valid": True if success else False,
                "bic_valid": True if success else False,
                "member_eligible": True if success else False,
            },
            "sensitive_data": True,  # Contains IBAN information
        }

        if not success and error_msg:
            details["error"] = error_msg

        reference_doc = mandate if mandate else member
        action = "mandate_created" if success else "mandate_creation_failed"

        return SEPAAuditLog.log_sepa_event(
            process_type="Mandate Creation", reference_doc=reference_doc, action=action, details=details
        )

    @staticmethod
    def log_payment_processing(payment_request, success=True, error_msg=None, amount=None):
        """
        Log SEPA payment processing with audit trail

        Args:
            payment_request: Payment request document
            success: Whether processing was successful
            error_msg: Error message if failed
            amount: Payment amount
        """
        details = {
            "amount": amount or payment_request.get("amount", 0) if payment_request else 0,
            "compliance_status": "Compliant" if success else "Failed",
            "processing_timestamp": frappe.utils.now(),
            "sensitive_data": False,
        }

        if not success and error_msg:
            details["error"] = error_msg

        action = "processing_completed" if success else "processing_failed"

        return SEPAAuditLog.log_sepa_event(
            process_type="Payment Processing", reference_doc=payment_request, action=action, details=details
        )

    @staticmethod
    def log_batch_generation(batch_doc, success=True, error_msg=None):
        """
        Log SEPA batch generation process

        Args:
            batch_doc: Direct Debit Batch document
            success: Whether generation was successful
            error_msg: Error message if failed
        """
        details = {
            "batch_size": len(batch_doc.get("batch_entries", [])) if batch_doc else 0,
            "compliance_status": "Compliant" if success else "Failed",
            "sensitive_data": False,
        }

        if not success and error_msg:
            details["error"] = error_msg

        action = "batch_generated" if success else "batch_generation_failed"

        return SEPAAuditLog.log_sepa_event(
            process_type="Batch Generation", reference_doc=batch_doc, action=action, details=details
        )
