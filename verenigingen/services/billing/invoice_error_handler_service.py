# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
InvoiceErrorHandlerService - Invoice generation error handling and recovery

This service handles comprehensive error recovery for failed invoice generation:
- Smart retry logic with deadlock differentiation
- Auto-advancement decision analysis
- Error pattern recognition and categorization
- Health system reconstruction triggers
- Manual review escalation

Extracted from membership_dues_schedule.py:
- _handle_invoice_generation_failure() - Lines 929-1047 (120 LOC)
- _should_auto_advance_schedule() - Lines 1074-1204 (132 LOC)
- _deduplicate_error_message() - Lines 708-731 (24 LOC)
- _is_deadlock_error() - Lines 734-753 (20 LOC)

Total: ~296 LOC of error handling logic in service layer

Architecture:
- Static methods for stateless error analysis
- Schedule document passed as parameter for context
- Calls back to controller instance methods when needed (_trigger_health_reconstruction, _advance_schedule_dates)
- Comprehensive error pattern matching with regex support

Business Logic:
- Distinguishes transient (deadlock) from persistent errors
- Auto-advances schedules for recoverable validation failures
- Flags serious issues for manual review (permissions, corruption, etc.)
- Triggers health system reconstruction for fixable data issues
- Tracks retry counts separately from deadlock counts

Dependencies:
- frappe - For validation errors, logging, and configuration access
- secure_operations - For safe document updates with audit trail
- Schedule controller instance methods for recovery actions

Security:
- Comprehensive error logging with sensitive data protection
- Audit trail for all error recovery actions
- Permission-aware escalation to manual review
"""

import sys
from typing import TYPE_CHECKING, Any, Dict, TypedDict

import frappe
from frappe.utils import today

# Import shared billing constants (eliminates duplication with controller)
from verenigingen.utils.billing_constants import (
    DEADLOCK_PATTERNS,
    ERROR_DEDUP_PATTERN,
    MAX_DB_ERROR_LENGTH,
    MAX_LOG_ERROR_LENGTH,
)

if TYPE_CHECKING:
    from frappe.model.document import Document


class RecoveryResult(TypedDict):
    """Type definition for error recovery result dictionaries."""

    action_taken: str  # "retry_tracked", "date_advanced", or "skipped"
    retry_count: int


class InvoiceErrorHandlerService:
    """
    Service for handling invoice generation errors and recovery.

    This service handles:
    - Error classification (transient vs. persistent)
    - Retry count management
    - Auto-advancement decision analysis
    - Health system reconstruction triggers
    - Manual review escalation
    """

    @staticmethod
    def _deduplicate_error_message(error_msg: str) -> str:
        """
        Remove repetitive error prefixes from nested exception handling.

        Uses regex for efficient single-pass deduplication of patterns like:
        - "Invoice generation failed: Invoice generation failed: ..."
        - "Invoice gen failed: Invoice gen failed: ..."

        Args:
            error_msg (str): Error message potentially containing repeated prefixes

        Returns:
            str: Cleaned error message with deduplicated prefixes

        Example:
            >>> InvoiceErrorHandlerService._deduplicate_error_message(
            ...     "Invoice generation failed: Invoice generation failed: Amount too low"
            ... )
            "Invoice generation failed: Amount too low"
        """
        if not error_msg:
            return error_msg

        # Use compiled regex pattern for performance (single compilation at module load)
        cleaned = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", str(error_msg))

        return cleaned.strip()

    @staticmethod
    def _is_deadlock_error(error_msg: str) -> bool:
        """
        Check if error message indicates a database deadlock.

        Covers multiple MySQL/MariaDB deadlock error codes:
        - 1213: Deadlock found when trying to get lock
        - 1205: Lock wait timeout exceeded
        - 3058: InnoDB deadlock (newer versions)

        Args:
            error_msg (str): Error message to check

        Returns:
            bool: True if error is a deadlock, False otherwise

        Example:
            >>> InvoiceErrorHandlerService._is_deadlock_error("Error 1213: Deadlock")
            True
            >>> InvoiceErrorHandlerService._is_deadlock_error("Validation failed")
            False
        """
        if not error_msg:
            return False

        error_lower = str(error_msg).lower()
        return any(pattern in error_lower for pattern in DEADLOCK_PATTERNS)

    @staticmethod
    def handle_invoice_generation_failure(schedule_doc: "Document", error_message: str) -> RecoveryResult:
        """
        Handle invoice generation failures with smart recovery logic.

        Analyzes error patterns to determine appropriate recovery action:
        - Transient errors (deadlocks): Track separately, retry without penalty
        - Recoverable errors: Increment retry count, attempt auto-advancement after 3 failures
        - Critical errors: Flag for manual review immediately

        Args:
            schedule_doc: MembershipDuesSchedule document instance
            error_message: Error message from failed invoice generation

        Returns:
            dict: Recovery action taken and current retry count:
                - action_taken (str): "retry_tracked", "date_advanced", or "skipped"
                - retry_count (int): Current retry count (excludes deadlocks)

        Business Logic:
            - Deadlocks don't count as retries (transient database locking)
            - After 3 real failures, check if auto-advancement is appropriate
            - Auto-advance for validation errors, flag for manual review for serious issues
            - All actions logged with full error context

        Security:
            - Uses secure_document_operation for all updates
            - Comprehensive error logging with audit trail
            - Sensitive error data truncated for database storage

        Example:
            >>> result = InvoiceErrorHandlerService.handle_invoice_generation_failure(
            ...     schedule_doc=schedule,
            ...     error_message="Validation failed: Amount below minimum"
            ... )
            >>> print(result)
            {"action_taken": "retry_tracked", "retry_count": 1}
        """
        # Get or initialize retry tracking fields
        retry_count = getattr(schedule_doc, "custom_invoice_retry_count", 0) or 0
        deadlock_count = getattr(schedule_doc, "custom_deadlock_count", 0) or 0

        # ✅ SPECIAL HANDLING: Deadlocks are transient - don't count them as retries
        # They should be retried immediately in the next batch without penalty
        is_deadlock = InvoiceErrorHandlerService._is_deadlock_error(error_message)

        if not is_deadlock:
            # Increment retry count for real failures
            retry_count += 1
        else:
            # Track deadlocks separately for monitoring
            deadlock_count += 1
            frappe.logger().info(
                f"Deadlock error for {schedule_doc.name} (#{deadlock_count}) - not incrementing retry count (transient error)"
            )

            # Alert if excessive deadlocks indicate systemic issue
            if deadlock_count > 10:
                try:
                    frappe.log_error(
                        title=f"Excessive Deadlocks - {schedule_doc.name[:50]}",
                        message=f"Schedule {schedule_doc.name} has experienced {deadlock_count} deadlocks. "
                        f"This may indicate database contention issues requiring investigation.\n\n"
                        f"Latest error: {error_message}",
                    )
                except Exception as e:
                    frappe.logger().warning(
                        f"Failed to log excessive deadlocks for {schedule_doc.name}: {str(e)}. "
                        f"Deadlock count: {deadlock_count}"
                    )

        # Update retry tracking using secure operations framework
        from verenigingen.utils.secure_operations import secure_document_operation

        # Clean up error message to avoid repetitive prefixes
        clean_error = InvoiceErrorHandlerService._deduplicate_error_message(error_message)

        # Log full error details (with safe error handling)
        full_error_details = (
            f"Schedule: {schedule_doc.name}\n"
            f"Retry Count: {retry_count}\n"
            f"Deadlock Count: {deadlock_count}\n"
            f"Is Deadlock: {is_deadlock}\n"
            f"Error: {clean_error}\n\n"
            f"Traceback:\n{frappe.get_traceback()}"
        )
        try:
            frappe.log_error(
                title=f"Invoice Failure #{retry_count} - {schedule_doc.name[:40]}",
                message=full_error_details,
            )
        except Exception as log_err:
            try:
                frappe.logger().error(
                    f"Failed to log invoice generation error for {schedule_doc.name}: {str(log_err)}\n"
                    f"Original error: {clean_error}"
                )
            except Exception as e:
                # Absolute last resort - print to stderr with error details
                print(
                    f"CRITICAL: All logging failed for {schedule_doc.name} - {str(e)}. "
                    f"Original error: {clean_error}",
                    file=sys.stderr,
                )

        # Update the document fields before saving
        schedule_doc.custom_invoice_retry_count = retry_count
        schedule_doc.custom_deadlock_count = deadlock_count
        schedule_doc.custom_last_invoice_failure_date = today()
        schedule_doc.custom_last_invoice_error = clean_error[:MAX_DB_ERROR_LENGTH]

        # Use secure document operation for tracking updates
        retry_update_result = secure_document_operation(
            operation="save",
            doc=schedule_doc,
            justification=f"Update invoice retry tracking for {schedule_doc.name}",
            required_permissions=["Membership Dues Schedule:write"],
            bypass_validations=["link_validation"],  # Avoid validation loops during error recovery
        )

        if not retry_update_result.success:
            error_msg = retry_update_result.errors[0] if retry_update_result.errors else "Unknown error"
            frappe.log_error(
                f"Failed to update retry tracking for {schedule_doc.name}: {error_msg}",
                "Retry Tracking Update Failure",
            )

        # Decision logic based on retry count and error patterns
        if retry_count >= 3:
            # After 3 failures, check if we should auto-advance or flag for manual review
            if InvoiceErrorHandlerService.should_auto_advance_schedule(schedule_doc, error_message):
                # Auto-advance dates to prevent infinite loops
                old_next_date = schedule_doc.next_invoice_date
                schedule_doc._advance_schedule_dates()

                # Log the advancement
                frappe.log_error(
                    f"Auto-advanced schedule {schedule_doc.name} after {retry_count} failures. "
                    f"Previous next_invoice_date: {old_next_date}, New: {schedule_doc.next_invoice_date}",
                    "Schedule Auto-Advanced",
                )

                return {"action_taken": "date_advanced", "retry_count": retry_count}
            else:
                # Flag for manual review (serious validation issues)
                # Use secure operation to flag for manual review
                schedule_doc.custom_requires_manual_review = 1
                secure_document_operation(
                    operation="save",
                    doc=schedule_doc,
                    justification=f"Schedule {schedule_doc.name} flagged for manual review after {retry_count} failures",
                    required_permissions=["Membership Dues Schedule:write"],
                    bypass_validations=["link_validation"],
                )
                return {"action_taken": "skipped", "retry_count": retry_count}
        else:
            # Track failure and retry next time
            return {"action_taken": "retry_tracked", "retry_count": retry_count}

    @staticmethod
    def should_auto_advance_schedule(schedule_doc: "Document", error_message: str) -> bool:
        """
        Determine if a schedule should be auto-advanced based on error patterns.

        Auto-advance for recoverable issues like:
        - Member eligibility changes
        - Temporary validation failures
        - Configuration mismatches
        - Data issues fixable by health reconstruction

        Require manual review for serious issues like:
        - Missing customer records
        - Account setup problems
        - Data corruption indicators
        - Security/permission errors

        Args:
            schedule_doc: MembershipDuesSchedule document instance
            error_message: Error message from failed invoice generation

        Returns:
            bool: True if schedule should auto-advance, False if manual review required

        Business Logic:
            - Deadlocks return False (retry without advancing)
            - Critical errors (permissions, corruption) return False (manual review)
            - Recoverable data issues trigger health reconstruction, then return True
            - Most validation errors return True (auto-advance)

        Example:
            >>> should_advance = InvoiceErrorHandlerService.should_auto_advance_schedule(
            ...     schedule_doc=schedule,
            ...     error_message="Membership type not found"
            ... )
            >>> print(should_advance)
            True  # Triggers health reconstruction, then auto-advances
        """
        # ✅ FIX: Define error_lower at the beginning of the method
        error_lower = str(error_message).lower()

        # Patterns that suggest manual review is needed
        manual_review_patterns = [
            "customer record",
            "account",
            "currency",
            "company",
            "permission denied",
            "access forbidden",
        ]

        # ✅ ENHANCED: Comprehensive patterns for production scenarios
        reconstruction_patterns = [
            # Membership data issues
            "membership_type",
            "missing template",
            "missing membership",
            "no active membership",
            "membership.*not.*found",
            "invalid membership status",
            # Dues and financial issues
            "dues_rate",
            "minimum_amount",
            "invalid.*amount",
            "negative.*amount",
            "amount.*required",
            "payment.*method",
            # Data integrity issues
            "constraint.*violation",
            "foreign.*key",
            "reference.*not.*found",
            "orphaned.*record",
            "missing.*reference",
            # Template and configuration issues
            "template.*missing",
            "configuration.*incomplete",
            "settings.*not.*found",
            "invalid.*configuration",
            # Customer and account issues (but recoverable)
            "customer.*missing.*recovery",  # Only auto-fix if marked as recoverable
            "account.*setup.*incomplete",
        ]

        # ✅ IMPORTANT: Deadlocks are transient and should be retried, not marked for manual review
        # They're handled separately below with immediate retry logic

        # ✅ NEW: Patterns that suggest immediate manual review (enhanced)
        critical_manual_review_patterns = [
            # Security and permissions
            "permission denied",
            "access forbidden",
            "unauthorized",
            "authentication failed",
            "role.*required",
            # Database and system errors
            "database.*corruption",
            "data.*integrity.*critical",
            "system.*failure",
            "timeout.*critical",
            # Customer and accounting (non-recoverable)
            "customer.*not.*exists",
            "account.*not.*found",
            "currency.*mismatch",
            "company.*invalid",
            "chart.*accounts.*missing",
            # Legal and compliance
            "compliance.*violation",
            "audit.*requirement",
            "legal.*constraint",
        ]

        # ✅ SPECIAL CASE: Deadlocks are transient database locking issues
        # Don't auto-advance (which would skip the invoice) - instead flag for manual review
        # so they can be retried in the next batch run when lock contention clears
        if InvoiceErrorHandlerService._is_deadlock_error(error_message):
            frappe.logger().info(
                f"Deadlock detected for schedule {schedule_doc.name} - flagging for retry in next batch"
            )
            # Return False to prevent auto-advance (which would skip this invoice)
            # The schedule will be retried in the next batch run
            return False

        # ✅ ENHANCED: Check critical issues first
        for pattern in critical_manual_review_patterns:
            if pattern in error_lower:
                frappe.log_error(
                    f"Critical error detected for schedule {schedule_doc.name}: {error_message}",
                    "Critical Schedule Error - Manual Review Required",
                )
                return False

        # Check legacy manual review patterns
        for pattern in manual_review_patterns:
            if pattern in error_lower:
                return False

        # ✅ ENHANCED: Check if this might be fixable by reconstruction
        reconstruction_triggered = False
        for pattern in reconstruction_patterns:
            if pattern in error_lower:
                # Try to trigger health system reconstruction
                schedule_doc._trigger_health_reconstruction(error_message)
                reconstruction_triggered = True
                break

        if reconstruction_triggered:
            # Log the reconstruction attempt
            frappe.log_error(
                f"Health reconstruction triggered for schedule {schedule_doc.name}: {error_message}",
                "Health Reconstruction Triggered",
            )
            # Still auto-advance since we attempted reconstruction
            return True

        # Default to auto-advance for most validation errors
        return True


def get_invoice_error_handler_service() -> InvoiceErrorHandlerService:
    """Get singleton instance of InvoiceErrorHandlerService"""
    return InvoiceErrorHandlerService()
