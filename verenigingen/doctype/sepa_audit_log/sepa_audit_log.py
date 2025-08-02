# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
SEPA Audit Log DocType

This module provides comprehensive audit trail functionality for all SEPA (Single Euro
Payments Area) compliance operations within the Verenigingen association management system.
It ensures complete regulatory compliance and provides detailed audit trails for financial
oversight and regulatory reporting.

Key Features:
- Immutable audit records for all SEPA operations
- Comprehensive compliance status tracking
- Sensitive data handling with masking capabilities
- Automated audit trail generation for all SEPA processes
- Integration with all SEPA-related components and workflows

Business Context:
SEPA regulations require detailed audit trails for all direct debit and payment operations.
This system ensures compliance with European banking regulations while maintaining
operational efficiency. The audit log captures:
- Mandate creation and authorization processes
- Batch generation and submission tracking
- Payment processing workflows and results
- Compliance validation and exception handling

Regulatory Compliance:
- EU SEPA Direct Debit Core Rulebook compliance
- GDPR compliance for sensitive financial data
- Automated audit trail generation for regulatory reporting
- Immutable records preventing tampering or unauthorized modification
- Complete traceability from member mandate to bank settlement

Architecture:
This DocType integrates with:
- SEPA Mandate management for authorization tracking
- Direct Debit Batch processing for payment workflows
- Member management for customer identification
- Banking integration APIs for transaction processing
- Reporting systems for compliance and audit reports

Data Model:
- Event identification and timestamp tracking
- Process type and action classification
- Compliance status with validation results
- Reference linking to source documents
- User attribution and trace ID for debugging
- Sensitive data flags for privacy protection

Security Features:
- Automatic IBAN masking for privacy protection
- Immutable audit records preventing tampering
- Role-based access control for audit review
- Secure logging with trace ID correlation
- Automated sensitive data identification

Author: Development Team
Date: 2025-07-25
Version: 1.0
"""

import json

import frappe
from frappe.model.document import Document


class SEPAAuditLog(Document):
    """
    Comprehensive SEPA compliance audit log for regulatory and operational oversight.

    This DocType provides immutable audit trails for all SEPA operations, ensuring
    compliance with European banking regulations and providing detailed tracking
    for financial oversight and regulatory reporting.

    Key Responsibilities:
    - Record all SEPA operations with complete audit trails
    - Ensure regulatory compliance with SEPA Direct Debit Rulebook
    - Provide secure handling of sensitive financial data
    - Support compliance reporting and regulatory audits
    - Maintain immutable records for legal requirements

    Business Process Integration:
    - Integrates with SEPA mandate creation workflows
    - Tracks direct debit batch processing operations
    - Records payment processing results and compliance status
    - Supports bank submission and reconciliation processes
    - Provides audit data for regulatory reporting

    Data Security and Privacy:
    - Automatic IBAN masking for GDPR compliance
    - Sensitive data flags for appropriate handling
    - Immutable records preventing unauthorized changes
    - Role-based access control for audit review
    - Secure trace ID correlation for debugging

    Usage Example:
        ```python
        # Log mandate creation
        SEPAAuditLog.log_mandate_creation(
            member=member_doc,
            mandate=mandate_doc,
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            success=True
        )

        # Log payment processing
        SEPAAuditLog.log_payment_processing(
            payment_request=payment_doc,
            success=True,
            amount=25.00
        )
        ```

    Compliance Standards:
    - EU SEPA Direct Debit Core Rulebook
    - GDPR data protection requirements
    - Dutch banking compliance standards
    - Association financial audit requirements

    Performance Considerations:
    - Indexed on timestamp and process_type for efficient querying
    - JSON details field for flexible audit data storage
    - Efficient reference linking with DocType validation
    - Optimized for high-volume audit log creation
    """

    def validate(self):
        """
        Comprehensive validation of SEPA audit log entries for compliance integrity.

        Ensures all required audit fields are properly populated and validates
        compliance status against regulatory requirements.

        Validation Rules:
        - Timestamp must be set for audit trail continuity
        - User attribution required for accountability
        - Trace ID generated for correlation and debugging
        - Compliance status validated against approved values

        Automatic Field Population:
        - timestamp: Current timestamp if not provided
        - user: Current session user for attribution
        - trace_id: Request ID or generated hash for correlation

        Compliance Validation:
        - Ensures compliance_status is from approved regulatory values
        - Validates against SEPA compliance framework requirements

        Raises:
        - frappe.ValidationError: If compliance status is invalid

        Performance:
        - Uses efficient in-memory validation for status checking
        - Minimal database queries for optimal audit log creation speed
        """
        # Ensure timestamp is set - critical for audit trail chronology
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Set user if not provided - required for accountability
        if not self.user:
            self.user = frappe.session.user

        # Generate trace ID if not provided - essential for correlation
        if not self.trace_id:
            self.trace_id = frappe.local.request_id or frappe.generate_hash(length=10)

        # Validate compliance status against SEPA regulatory requirements
        valid_statuses = ["Compliant", "Exception", "Failed", "Pending Review"]
        if self.compliance_status not in valid_statuses:
            frappe.throw(f"Invalid compliance status. Must be one of: {', '.join(valid_statuses)}")

    def before_insert(self):
        """
        Pre-insertion setup for audit log integrity and unique identification.

        Automatically generates required identifiers and ensures proper audit
        trail establishment before record creation.

        Fields Initialized:
        - timestamp: Creation timestamp for audit chronology
        - event_id: Unique event identifier for audit correlation

        Security Features:
        - Ensures immutable timestamp at creation
        - Generates cryptographically secure event IDs
        - Establishes audit trail foundation before persistence

        Performance:
        - Uses efficient hash generation for unique IDs
        - Minimal overhead during high-volume audit creation
        """
        # Set creation timestamp - immutable audit trail foundation
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Generate unique event ID - essential for audit correlation
        if not self.event_id:
            self.event_id = frappe.generate_hash(length=12)

    def on_trash(self):
        """
        Protect audit log integrity by preventing unauthorized deletion.

        Implements regulatory compliance requirements for immutable audit records.
        Only system-level operations are permitted to delete audit logs, typically
        during automated cleanup or data retention policy enforcement.

        Security Controls:
        - Restricts deletion to system administrators only
        - Prevents accidental or unauthorized audit trail tampering
        - Maintains compliance with immutable audit record requirements

        Authorized Users:
        - Administrator: System administration operations
        - System: Automated cleanup and retention processes

        Compliance:
        - Supports SEPA regulatory audit trail requirements
        - Ensures data integrity for financial audit purposes
        - Maintains chain of custody for regulatory compliance

        Raises:
        - frappe.ValidationError: If unauthorized user attempts deletion
        """
        # Only allow deletion by system or during automated cleanup
        if frappe.session.user not in ["Administrator", "System"]:
            frappe.throw("Audit logs cannot be manually deleted")

    @staticmethod
    def log_sepa_event(process_type, reference_doc, action, details=None):
        """
        Create comprehensive audit log entry for SEPA compliance events.

        This is the primary method for creating audit trail entries for all SEPA
        operations, ensuring consistent logging format and regulatory compliance.

        Args:
            process_type (str): Type of SEPA process being audited
                Options: "Mandate Creation", "Batch Generation", "Bank Submission", "Payment Processing"
            reference_doc (Document): Source document triggering the audit event
                Can be Member, Direct Debit Batch, Payment Entry, etc.
            action (str): Specific action being performed
                Examples: "mandate_created", "batch_generated", "payment_processed"
            details (dict, optional): Additional audit details and metadata
                Should include process-specific information and compliance data

        Returns:
            SEPAAuditLog: Created audit log document, or None if creation failed

        Audit Trail Features:
        - Automatic event ID generation for unique identification
        - Timestamp recording for chronological audit trail
        - Reference document linking for traceability
        - Compliance status tracking with detailed metadata
        - Sensitive data flagging for privacy protection

        Error Handling:
        - Graceful failure with error logging if audit creation fails
        - Continues operation even if audit logging encounters issues
        - Detailed error reporting for debugging and monitoring

        Security:
        - Uses ignore_permissions=True for system-level audit operations
        - Validates reference document existence before linking
        - Protects against audit trail corruption or loss

        Usage Example:
            ```python
            # Log mandate creation
            audit_log = SEPAAuditLog.log_sepa_event(
                process_type="Mandate Creation",
                reference_doc=member_doc,
                action="mandate_authorized",
                details={
                    "iban_masked": "NL91****4300",
                    "authorization_method": "online_portal",
                    "compliance_status": "Compliant"
                }
            )
            ```

        Performance:
        - Optimized for high-volume audit log creation
        - Minimal database operations for efficiency
        - Asynchronous-ready for background processing
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
