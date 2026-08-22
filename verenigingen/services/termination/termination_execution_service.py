# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
TerminationExecutionService - Membership termination execution logic

This service handles the execution of membership terminations with:
- Idempotency checking to prevent double-execution
- Pre-execution validation for retry safety
- Declarative system updates using operation pattern
- Comprehensive error recovery with status revert
- Execution tracking and audit integration

Extracted from membership_termination_request.py:
- execute_termination_internal() - Lines 91-176 (86 LOC)
- execute_system_updates_safely() - Lines 177-234 (58 LOC)
- execute_termination() - Lines 296-312 (17 LOC)
Total extraction: ~161 LOC

Architecture:
- Static methods for stateless operations
- Idempotency via execution_date check
- Error recovery via status revert
- Integration with TerminationExecutor for system updates
- Audit trail integration via document methods

Dependencies:
- frappe.db for member validation
- TerminationExecutor for declarative operations
- Document audit trail methods
- frappe.msgprint for user feedback

Security:
- Validates member existence before execution
- Checks status is "Executed" before proceeding
- Logs all operations for audit trail
- Reverts status on failure for retry safety
"""

import random
import string
from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe import _
from frappe.utils import now

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class TerminationExecutionService(StatelessService):
    """
    Service for executing membership terminations.

    This service handles:
    - Idempotency checking to prevent double-execution
    - Pre-execution validation
    - System updates via declarative operations
    - Execution tracking (dates, users, counters)
    - Error recovery with status revert
    """

    def __init__(self):
        """Initialize the Termination Execution Service"""
        super().__init__(service_name="TerminationExecutionService")

    # ========================================================================
    # PUBLIC EXECUTION METHODS
    # ========================================================================

    def execute(self, termination_request: "Document") -> bool:
        """Execute termination with idempotency and error recovery.

        This is the main entry point for termination execution. It:
        1. Validates input type (runtime type checking)
        2. Checks idempotency with database-level locking (prevents race conditions)
        3. Validates pre-execution conditions (member exists, status correct)
        4. Executes system updates using declarative operations within a transaction
        5. Updates execution tracking fields
        6. Handles errors with proper rollback and status revert for retry

        CRITICAL FIXES (QCE Review 2025-11-24):
        - Added FOR UPDATE lock to prevent race conditions in concurrent execution
        - Wrapped all operations in explicit database transaction
        - Proper rollback on failure before status revert

        HIGH PRIORITY FIXES (QCE Review 2025-11-24):
        - Issue #7: Added runtime type validation for input document

        Args:
            termination_request: MembershipTerminationRequest document

        Returns:
            True if execution successful, False if already executed

        Raises:
            TypeError: If termination_request is not a Document instance
            frappe.ValidationError: If pre-execution validation fails
            Exception: If execution fails (after rollback and status revert)

        Examples:
            >>> from verenigingen.services.termination import TerminationExecutionService
            >>> termination_request = frappe.get_doc("Membership Termination Request", "TR-001")
            >>> success = TerminationExecutionService().execute(termination_request)
        """
        # QCE Fix #7: Runtime type validation for safety
        if not isinstance(termination_request, frappe.model.document.Document):
            raise TypeError(
                f"Expected frappe.model.document.Document, got {type(termination_request).__name__}. "
                f"termination_request must be a valid Frappe Document instance."
            )

        # Verify it's the correct DocType
        if termination_request.doctype != "Membership Termination Request":
            raise TypeError(
                f"Expected DocType 'Membership Termination Request', got '{termination_request.doctype}'. "
                f"This service only handles Membership Termination Request documents."
            )

        # Manage savepoint manually rather than using frappe.database.savepoint(),
        # whose default catch=Exception silently swallows any exception inside the
        # with-block. Manual management lets us roll back AND re-raise so the
        # outer caller (and _handle_error) sees the real failure.
        # Works both standalone (Frappe's implicit request transaction) and when
        # called from within an existing transaction (e.g. MijnRood sync event
        # processor). FOR UPDATE locks still work within savepoints.
        savepoint_name = "".join(random.sample(string.ascii_lowercase, 10))
        frappe.db.savepoint(savepoint_name)
        try:
            # STEP 1: Idempotency check with database-level locking
            # FOR UPDATE lock prevents race conditions in concurrent execution
            if self._check_idempotency_with_lock(termination_request):
                self._release_savepoint_safe(savepoint_name)
                return True  # Already executed, skip duplicate

            self.logger.info(f"Starting termination execution for {termination_request.name}")

            # STEP 2: Pre-execution validation - minimal checks for retry safety
            self._validate_preconditions(termination_request)

            # STEP 3: Execute system updates using declarative operations
            results = self.execute_system_updates(termination_request)

            # STEP 4: Update execution tracking fields and status
            self._update_tracking(termination_request, results)
            termination_request.status = "Executed"

            # STEP 5: Save changes (use flags to avoid validation issues and recursion)
            termination_request.flags.ignore_validate_update_after_submit = True
            termination_request.flags.skip_status_change_hook = True  # Prevent recursive execution
            termination_request.save()

            # Add audit trail entry
            termination_request.add_audit_entry(
                "Termination Executed",
                f"System updates completed: {len(results.get('actions_taken', []))} actions",
            )

            # Body completed successfully. Release the savepoint, but tolerate
            # MySQL complaining the savepoint no longer exists — that just means
            # an inner operation did its own commit. The work is already
            # persisted at this point, so we still treat this as success.
            self._release_savepoint_safe(savepoint_name)

            self.logger.info(f"Termination execution completed for {termination_request.name}")

            # Show success message to user (after savepoint released)
            if results.get("errors"):
                frappe.msgprint(
                    _("Membership termination executed with {0} warnings. Check logs for details.").format(
                        len(results["errors"])
                    ),
                    indicator="orange",
                )
            else:
                frappe.msgprint(_("Membership termination executed successfully"))

            return True

        # Exempt from the re-raise rule the rest of services/termination follows (#470):
        # this handler does not swallow. Every path through it ends in _handle_error's
        # frappe.throw, so a 1205/1213 raised by an operation still reaches the caller --
        # as a ValidationError rather than as itself. That class-masking matters to
        # MijnRoodTerminationSyncService and to the dispatcher above it, and is tracked
        # separately; it is a question about how a failure is reported, not whether the
        # unit of work is abandoned.
        except Exception as e:  # non-resumable-ok: does not swallow -- _handle_error re-raises
            self.logger.error(f"Savepoint rolled back for {termination_request.name} due to error: {str(e)}")

            # Roll back the savepoint to discard any partial work. If a nested
            # call already released or rolled back the savepoint (e.g. via an
            # inner commit), MySQL will raise — swallow that secondary error so
            # we surface the original one through _handle_error.
            try:
                frappe.db.rollback(save_point=savepoint_name)
            except Exception as rollback_error:  # non-resumable-ok: cleanup after the failure
                self.logger.warning(
                    f"Savepoint {savepoint_name} could not be rolled back "
                    f"(may have been released by a nested commit): {rollback_error}"
                )

            # Error recovery - revert status and re-raise
            self._handle_error(termination_request, e)

    def execute_system_updates(self, termination_request: "Document") -> Dict[str, Any]:
        """Execute system updates using declarative operation pattern.

        This method uses the TerminationExecutor to run a series of
        declarative operations that update all related systems:
        - Cancel memberships and SEPA mandates
        - Disable chapter memberships
        - End board positions
        - Suspend team memberships
        - Deactivate user accounts
        - Terminate volunteer and employee records
        - Update customer records
        - Cancel outstanding and future invoices
        - Cancel dues schedules
        - Update member status (final commit point)

        Order matters: preparatory operations first, member status update last.

        Args:
            termination_request: MembershipTerminationRequest document

        Returns:
            Dict with execution results:
                - actions_taken: List of successful actions
                - errors: List of error messages
                - sepa_mandates_cancelled: Count
                - positions_ended: Count
                - customer_updated: Boolean
                - outstanding_invoices_cancelled: Count

        Examples:
            >>> results = TerminationExecutionService().execute_system_updates(termination_request)
            >>> print(f"Actions: {len(results['actions_taken'])}, Errors: {len(results['errors'])}")
        """
        from verenigingen.services.termination.termination_operations import (
            CancelDuesSchedulesOperation,
            CancelFutureInvoicesOperation,
            CancelMembershipsOperation,
            CancelOutstandingInvoicesOperation,
            CancelSEPAMandatesOperation,
            DeactivateUserAccountOperation,
            DisableChapterMembershipsOperation,
            EndBoardPositionsOperation,
            SuspendTeamMembershipsOperation,
            TerminateEmployeeRecordsOperation,
            TerminateVolunteerRecordsOperation,
            TerminationExecutor,
            UpdateCustomerRecordOperation,
            UpdateMemberStatusOperation,
            UpdateOutstandingInvoicesOperation,
        )

        member = termination_request.member
        self.logger.info(f"Starting safe system updates for member {member}")

        # Take the member's row lock BEFORE the first operation runs.
        #
        # Since #436 the history managers lock the parent row they rewrite -- Member for
        # ChapterMembershipHistoryManager, Volunteer for AssignmentHistoryManager -- and
        # a termination takes both. The canonical order is Member before Volunteer, and
        # this list appeared to obey it only by accident: DisableChapterMemberships
        # (idx 2) takes the Member lock, but disable_chapter_memberships_safe returns
        # early when there is no *enabled* Chapter Member row, so a board member who is
        # off the roster locks Volunteer at idx 3 and Member only at idx 13. Whether the
        # order inverts was decided by the member's data, not by this list. Measured both
        # ways in tests/unit/test_history_lock_order.py. #459.
        #
        # It cannot be fixed by reordering: UpdateMemberStatusOperation is deliberately
        # last (it is the commit point, and TerminationExecutor enforces that), and its
        # member.save() is a Member lock. Taking the row up front makes every later
        # acquisition a re-lock of a row this transaction already holds.
        #
        # execute() calls _validate_preconditions first, which checks the member exists,
        # so this really locks a row: get_value on a missing name emits WHERE name='' and
        # locks nothing at all, silently.
        #
        # Cost: the lock is held from here to the end of the transaction instead of from
        # whichever operation first happened to touch the member. That is one member row
        # -- the one this whole operation is about -- and idx 2 already held it for most
        # of the list in the common case. Deliberately NOT wrapped in a try/except: a
        # 1205/1213 here is not resumable, and execute() rolls the savepoint back and
        # re-raises.
        frappe.db.get_value("Member", member, "name", for_update=True)

        # Define termination operations in execution order
        # Order matters: preparatory operations first, member status update last
        operations = [
            # Phase 1: Preparatory operations (can be reversed/retried)
            CancelMembershipsOperation(member, termination_request),
            CancelSEPAMandatesOperation(member, termination_request),
            DisableChapterMembershipsOperation(member, termination_request),
            EndBoardPositionsOperation(member, termination_request),
            SuspendTeamMembershipsOperation(member, termination_request),
            DeactivateUserAccountOperation(member, termination_request),
            TerminateVolunteerRecordsOperation(member, termination_request),
            TerminateEmployeeRecordsOperation(member, termination_request),
            UpdateCustomerRecordOperation(member, termination_request),
            UpdateOutstandingInvoicesOperation(member, termination_request),
            CancelOutstandingInvoicesOperation(member, termination_request),
            CancelFutureInvoicesOperation(member, termination_request),
            CancelDuesSchedulesOperation(member, termination_request),
            # Phase 2: Final commit point (member status change)
            UpdateMemberStatusOperation(member, termination_request),
        ]

        # Execute all operations and collect results
        executor = TerminationExecutor(operations)
        results = executor.execute()

        # Log results summary
        self.logger.info(f"System updates completed: {results}")

        # Add detailed audit entries
        for action in results["actions_taken"]:
            termination_request.add_audit_entry("System Update", action, is_system=True)

        for error in results["errors"]:
            termination_request.add_audit_entry("System Update Error", error, is_system=True)

        return results

    def execute_from_api(self, termination_request: "Document") -> Dict[str, str]:
        """Execute termination from API endpoint with status validation.

        This is a wrapper for API calls that validates the status before
        executing the termination.

        Args:
            termination_request: MembershipTerminationRequest document

        Returns:
            Dict with status and message

        Raises:
            frappe.ValidationError: If status is not "Approved"
            Exception: If execution fails

        Examples:
            >>> result = TerminationExecutionService().execute_from_api(termination_request)
            >>> print(result["message"])
        """
        if termination_request.status != "Approved":
            frappe.throw(_("Only approved requests can be executed"))

        # Call the main execution method (status updated after success)
        success = self.execute(termination_request)

        if success:
            frappe.msgprint(_("Termination executed successfully"))
            return {"status": termination_request.status, "message": "Termination executed successfully"}
        else:
            frappe.throw(_("Failed to execute termination"))

    # ========================================================================
    # HELPER METHODS (Private)
    # ========================================================================

    def _release_savepoint_safe(self, savepoint_name: str) -> None:
        """Release a savepoint, tolerating "does not exist" errors.

        If a nested operation did its own commit, the savepoint will already
        have been released by MySQL. Surfacing that as a failure would be
        misleading — the body succeeded and its writes are persisted, so we
        only log the cleanup hiccup and continue.
        """
        try:
            frappe.db.release_savepoint(savepoint_name)
        except Exception as cleanup_error:  # non-resumable-ok: cleanup after the failure
            self.logger.warning(
                f"Savepoint {savepoint_name} could not be released "
                f"(likely already released by an inner commit): {cleanup_error}"
            )

    def _check_idempotency_with_lock(self, termination_request: "Document") -> bool:
        """Check if termination was already executed with database-level locking.

        QCE CRITICAL FIX #1 (2025-11-24):
        Uses FOR UPDATE lock to prevent race conditions in concurrent execution.
        Two processes trying to execute the same termination will serialize at
        the database level - the second will see execution_date already set.

        This prevents TOCTOU (Time-of-Check-Time-of-Use) vulnerability where:
        1. Process A checks execution_date (None)
        2. Process B checks execution_date (None)  ← Race condition
        3. Both processes execute termination    ← Data corruption

        With FOR UPDATE lock:
        1. Process A acquires lock, checks execution_date (None)
        2. Process B waits for lock
        3. Process A executes and sets execution_date
        4. Process B acquires lock, checks execution_date (SET) ← Safe
        5. Process B skips duplicate execution

        Args:
            termination_request: MembershipTerminationRequest document

        Returns:
            True if already executed (skip duplicate), False if not executed yet
        """
        # Acquire database-level lock and check execution_date atomically
        # This query locks the row until transaction commits/rollbacks
        locked_row = frappe.db.sql(
            """
            SELECT execution_date, executed_by
            FROM `tabMembership Termination Request`
            WHERE name = %s
            FOR UPDATE
            """,
            termination_request.name,
            as_dict=True,
        )

        # Check if already executed
        if locked_row and locked_row[0].execution_date:
            self.logger.info(
                f"Termination {termination_request.name} already executed on "
                f"{locked_row[0].execution_date} by {locked_row[0].executed_by} "
                f"- skipping duplicate execution (detected with database lock)"
            )
            frappe.msgprint(
                _("This termination was already executed on {0}").format(
                    frappe.format(locked_row[0].execution_date, {"fieldtype": "Datetime"})
                ),
                indicator="blue",
            )
            return True  # Already executed

        # Lock acquired, execution_date is None - proceed with execution
        self.logger.debug(f"Idempotency check passed with lock for {termination_request.name} - proceeding")
        return False  # Not yet executed

    def _validate_preconditions(self, termination_request: "Document") -> None:
        """Validate pre-execution conditions for retry safety.

        This performs minimal validation to enable safe retry after partial failure:
        - Only checks member exists (not status, as status may have changed)
        - Logs current member status for audit purposes
        - Validates termination request status is "Executed"

        Args:
            termination_request: MembershipTerminationRequest document

        Raises:
            frappe.ValidationError: If member doesn't exist or status not "Executed"
        """
        member = termination_request.member

        # Check member exists - don't check status, as this enables retry after partial failure
        if not frappe.db.exists("Member", member):
            frappe.throw(_("Member {0} no longer exists").format(member))

        # Log member current status for audit purposes but don't block
        current_member_status = frappe.db.get_value("Member", member, "status")
        self.logger.info(
            f"Executing termination {termination_request.name} - "
            f"member {member} current status: {current_member_status}"
        )

        # Validate request is in executable state (must be Approved to execute)
        if termination_request.status != "Approved":
            frappe.throw(
                _("Termination can only be executed when status is 'Approved', current status: {0}").format(
                    termination_request.status
                )
            )

    def _update_tracking(self, termination_request: "Document", results: Dict[str, Any]) -> None:
        """Update execution tracking fields from results.

        QCE HIGH PRIORITY FIX #8 (2025-11-24):
        Added retry detection and logging. Currently tracks original execution details
        (executed_by, execution_date) and logs retry attempts separately.

        BUSINESS DECISION: Original execution details preserved on retry.
        - executed_by: User who initiated ORIGINAL successful execution
        - execution_date: Timestamp of ORIGINAL successful execution
        - Retry attempts logged to audit trail but not tracked in separate fields

        FUTURE ENHANCEMENT: To track retry attempts in database, add these fields to DocType:
        - last_retry_by (Link to User)
        - last_retry_date (Datetime)
        - execution_attempts (Int)

        Updates:
        - executed_by: Current user (if not already set)
        - execution_date: Current timestamp (if not already set)
        - sepa_mandates_cancelled: Count from results
        - positions_ended: Count from results
        - newsletters_updated: 1 if customer updated, 0 otherwise
        - outstanding_invoices_cancelled: Count from results

        Args:
            termination_request: MembershipTerminationRequest document
            results: Execution results dict from TerminationExecutor
        """
        # Update execution fields (detect retry if executed_by already set)
        if not termination_request.executed_by:
            termination_request.executed_by = frappe.session.user
            termination_request.execution_date = now()
            self.logger.info(
                f"Tracking execution for {termination_request.name}: "
                f"executed_by={frappe.session.user}, execution_date={now()}"
            )
        else:
            # This is a retry - log it
            self.logger.warning(
                f"RETRY DETECTED for {termination_request.name}: "
                f"Original execution by {termination_request.executed_by} on {termination_request.execution_date}. "
                f"Retry by {frappe.session.user} on {now()}. "
                f"Original execution details preserved (business decision)."
            )
            # Note: To track retries in database, add last_retry_by, last_retry_date, execution_attempts fields

        # Update counters from results (always update - may differ on retry)
        termination_request.sepa_mandates_cancelled = results.get("sepa_mandates_cancelled", 0)
        termination_request.positions_ended = results.get("positions_ended", 0)
        termination_request.newsletters_updated = 1 if results.get("customer_updated") else 0
        termination_request.outstanding_invoices_cancelled = results.get("outstanding_invoices_cancelled", 0)

    def _handle_error(self, termination_request: "Document", error: Exception) -> None:
        """Handle execution errors with proper rollback and status revert for retry.

        QCE CRITICAL FIX #3 (2025-11-24):
        Now operates in a NEW transaction after the main transaction has been rolled back.
        This ensures:
        1. All partial changes from failed execution are rolled back
        2. Status revert to "Approved" happens in clean transaction
        3. Audit trail entry is persisted separately from failed execution

        When execution fails:
        1. Main transaction already rolled back by caller
        2. Logs error with full details
        3. Starts new transaction for status revert
        4. Adds audit trail entry
        5. Reverts status to "Approved" (enables retry)
        6. Commits the status revert transaction
        7. Re-raises exception to caller

        This enables safe retry after fixing issues WITHOUT persisting partial changes.

        Args:
            termination_request: MembershipTerminationRequest document
            error: Exception that occurred

        Raises:
            frappe.ValidationError: With formatted error message
        """
        error_msg = str(error)
        self.logger.error(f"Termination execution failed for {termination_request.name}: {error_msg}")

        # Revert status in a savepoint so this works both standalone and
        # within an existing transaction (e.g. MijnRood sync event processor).
        try:
            with frappe.database.savepoint():
                # Reload document to get fresh state after savepoint rollback
                termination_request.reload()

                # Add audit trail entry for the failure
                termination_request.add_audit_entry("Execution Failed", f"Error: {error_msg}")

                # Revert status to enable retry (only if currently "Executed")
                if termination_request.status == "Executed":
                    termination_request.status = "Approved"
                    termination_request.flags.ignore_validate_update_after_submit = True
                    termination_request.flags.skip_termination_validation = True
                    termination_request.save()

                    self.logger.info(
                        f"Status reverted to Approved for {termination_request.name} - retry enabled"
                    )

        # Runs after the failure, in a transaction a 1213 has already replaced. Re-raising
        # here would substitute the revert's own error for the real one, which is the
        # opposite of what this method exists to do.
        except Exception as revert_error:  # non-resumable-ok: recovery after the failure
            self.logger.error(f"Failed to revert status for {termination_request.name}: {str(revert_error)}")

        # Re-raise original exception
        frappe.throw(_("Failed to execute termination: {0}").format(error_msg))


def get_termination_execution_service() -> TerminationExecutionService:
    """Get instance of TerminationExecutionService."""
    return TerminationExecutionService()
