"""
Member Lifecycle Service - Centralized member lifecycle management.

This service handles all aspects of member lifecycle including application processing,
status transitions, membership management, and workflow coordination.

Extracted from Member DocType to improve maintainability, testability, and reusability.

Key Features:
    - Application approval and rejection workflows
    - Status synchronization and validation
    - Membership lifecycle management
    - Integration with chapter management and user creation
    - Comprehensive error handling and audit trails
    - Concurrency-safe operations

Author: Verenigingen Development Team
Created: 2025-09-18
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.constants.error_codes import ErrorCodes, get_safe_error_message
from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberLifecycleService(StatelessService):
    """
    Centralized service for managing member lifecycle operations.

    This service provides a clean interface for all member lifecycle operations
    including application processing, status management, and membership handling.

    TRANSACTION HANDLING WARNING:
        Do NOT use explicit frappe.db.begin()/commit()/rollback() in lifecycle
        methods. Frappe's request/test harness manages transactions automatically.
        Manual transaction control breaks tests and can cause double/partial commits.

        For race condition prevention, use:
        - Row-level locking: SELECT ... FOR UPDATE (within current transaction)
        - Advisory locks: verenigingen.utils.db_advisory_lock.advisory_lock()

        See: docs/patterns/TRANSACTION_PATTERNS.md
    """

    def __init__(self):
        """Initialize the Member Lifecycle Service"""
        super().__init__(service_name="MemberLifecycleService")

    def _log_error(
        self,
        error_code: str,
        operation: str,
        message: str,
        member_name: str = None,
        exception: Exception = None,
        **context,
    ):
        """Log error with structured context for observability.

        Args:
            error_code: Unique error code (e.g., LIFECYCLE_001)
            operation: Operation name (e.g., approve_application)
            message: Human-readable error message
            member_name: Member document name (optional)
            exception: Original exception (optional)
            **context: Additional context key-value pairs
        """
        log_context = {
            "error_code": error_code,
            "operation": operation,
            "service": "MemberLifecycleService",
        }
        if member_name:
            log_context["member"] = member_name
        log_context.update(context)

        error_msg = f"[{error_code}] {message}"
        if member_name:
            error_msg += f" | member={member_name}"
        if exception:
            error_msg += f" | error={str(exception)}"
        for key, value in context.items():
            error_msg += f" | {key}={value}"

        frappe.log_error(error_msg, f"Member Lifecycle [{error_code}]")

    def approve_application(self, member: "Document") -> OperationResult[str]:
        """
        Validate application, assign member_id, and update status fields.

        Uses database-level row locking (FOR UPDATE) to prevent race conditions
        when multiple users attempt to approve the same application concurrently.

        Args:
            member: Member document to approve

        Returns:
            OperationResult[str]: OperationResult with member_id on success or error details on failure
        """
        try:
            # Acquire row lock to prevent concurrent approval
            # FOR UPDATE works within the current transaction
            locked_row = frappe.db.sql(
                """SELECT application_status FROM `tabMember`
                   WHERE name = %s FOR UPDATE""",
                (member.name,),
                as_dict=True,
            )

            if not locked_row:
                return OperationResult.fail(
                    f"Member {member.name} not found",
                    error_code=ErrorCodes.LIFECYCLE_MEMBER_NOT_FOUND,
                )

            # Check if already approved (may have changed since page load)
            if locked_row[0].application_status == "Approved":
                return OperationResult.fail(
                    "Application is already approved",
                    errors=["Application is already approved"],
                    error_code=ErrorCodes.LIFECYCLE_ALREADY_APPROVED,
                    current_status=locked_row[0].application_status,
                )

            # Reload member to get fresh data within lock
            member.reload()

            # Validate pre-conditions
            validation_result = self._validate_application_approval(member)
            if not validation_result.success:
                return validation_result.chain("Application validation failed")

            # Assign member ID if needed
            if not member.member_id:
                member.member_id = member.generate_member_id()

            # Update status fields
            member.application_status = "Approved"
            member.status = "Active"
            member.reviewed_by = frappe.session.user
            member.review_date = now_datetime()

            # Set flag to skip status validation during save to prevent override
            member.flags.ignore_status_validation = True

            # Save with concurrency handling
            save_result = self._save_member_with_retry(member, "approve")
            if not save_result.success:
                return save_result.chain("Failed to save approved application")

            # Perform post-approval setup (customer creation, user creation, chapter activation)
            setup_result = self._perform_post_approval_setup(member)

            return OperationResult.ok(member.member_id, approved=True, setup_results=setup_result)

        except Exception as e:
            self._log_error(
                error_code=ErrorCodes.LIFECYCLE_APPROVAL_FAILED,
                operation="approve_application",
                message="Application approval failed",
                member_name=member.name,
                exception=e,
                reviewed_by=frappe.session.user,
            )
            # Return safe error message - internal details logged above
            return OperationResult.fail(
                get_safe_error_message(ErrorCodes.LIFECYCLE_APPROVAL_FAILED),
                error_code=ErrorCodes.LIFECYCLE_APPROVAL_FAILED,
                internal_error=str(e),  # Available for debugging but not exposed to UI
            )

    def reject_application(self, member: "Document", reason: str) -> OperationResult[str]:
        """
        Reject member application and clean up pending records.

        Uses database-level row locking (FOR UPDATE) to prevent race conditions
        when multiple users attempt to reject the same application concurrently.

        Args:
            member: Member document to reject
            reason: Reason for rejection

        Returns:
            OperationResult[str]: OperationResult with status on success or error details on failure
        """
        try:
            # Acquire row lock to prevent concurrent rejection
            # FOR UPDATE works within the current transaction
            locked_row = frappe.db.sql(
                """SELECT application_status FROM `tabMember`
                   WHERE name = %s FOR UPDATE""",
                (member.name,),
                as_dict=True,
            )

            if not locked_row:
                return OperationResult.fail(
                    f"Member {member.name} not found",
                    error_code=ErrorCodes.LIFECYCLE_MEMBER_NOT_FOUND,
                )

            # Check if already processed (may have changed since page load)
            if locked_row[0].application_status in ("Approved", "Rejected"):
                msg = f"Application has already been {locked_row[0].application_status.lower()}"
                return OperationResult.fail(
                    msg,
                    errors=[msg],
                    error_code=ErrorCodes.LIFECYCLE_ALREADY_PROCESSED,
                    current_status=locked_row[0].application_status,
                )

            # Reload member to get fresh data within lock
            member.reload()

            # Validate pre-conditions
            validation_result = self._validate_application_rejection(member)
            if not validation_result.success:
                return validation_result.chain("Application rejection validation failed")

            # Update status fields
            member.application_status = "Rejected"
            member.status = "Rejected"
            member.reviewed_by = frappe.session.user
            member.review_date = now_datetime()
            member.review_notes = reason  # Use valid field name (not rejection_reason which doesn't exist)

            # Set flags to skip status validation and preserve rejection reason for retry
            member.flags.ignore_status_validation = True
            member.flags.rejection_reason = reason

            # Save with concurrency handling
            save_result = self._save_member_with_retry(member, "reject")
            if not save_result.success:
                return save_result.chain("Failed to save rejected application")

            # Perform post-rejection cleanup
            cleanup_result = self._perform_post_rejection_cleanup(member)

            return OperationResult.ok(
                member.status,
                rejected=True,
                review_date=str(member.review_date),
                cleanup_results=cleanup_result,
            )

        except Exception as e:
            self._log_error(
                error_code=ErrorCodes.LIFECYCLE_REJECTION_FAILED,
                operation="reject_application",
                message="Application rejection failed",
                member_name=member.name,
                exception=e,
                reviewed_by=frappe.session.user,
                rejection_reason=reason[:100] if reason else None,
            )
            # Return safe error message - internal details logged above
            return OperationResult.fail(
                get_safe_error_message(ErrorCodes.LIFECYCLE_REJECTION_FAILED),
                error_code=ErrorCodes.LIFECYCLE_REJECTION_FAILED,
                internal_error=str(e),  # Available for debugging but not exposed to UI
            )

    def update_membership_status(self, member) -> OperationResult[Dict[str, Any]]:
        """
        Update member's membership status based on active memberships.

        Args:
            member: Member document to update

        Returns:
            OperationResult[Dict]: OperationResult with membership status data on success
        """
        try:
            # Get active membership
            active_membership = self._get_active_membership(member)

            if active_membership:
                member.membership_status = "Active"
                # Update current membership type if field exists
                if hasattr(member, "current_membership_type"):
                    member.current_membership_type = active_membership.membership_type

                return OperationResult.ok(
                    {
                        "membership_status": "Active",
                        "membership_type": active_membership.membership_type,
                        "membership_name": active_membership.name,
                    }
                )
            else:
                # Check for expired memberships
                expired_membership = self._get_most_recent_expired_membership(member)

                if expired_membership:
                    member.membership_status = "Expired"
                    # Keep the last membership type even if expired
                    if hasattr(member, "current_membership_type"):
                        member.current_membership_type = expired_membership.membership_type

                    return OperationResult.ok(
                        {
                            "membership_status": "Expired",
                            "membership_type": expired_membership.membership_type,
                            "membership_name": expired_membership.name,
                        }
                    )
                else:
                    # No memberships found
                    member.membership_status = None
                    if hasattr(member, "current_membership_type"):
                        member.current_membership_type = None

                    return OperationResult.ok(
                        {
                            "membership_status": None,
                            "membership_type": None,
                            "membership_name": None,
                        }
                    )

        except Exception as e:
            self.logger.error(f"Error updating membership status for member {member.name}: {str(e)}")
            return OperationResult.fail(
                f"Membership status update failed: {str(e)}",
                membership_status=None,
                membership_type=None,
                membership_name=None,
            )

    def sync_status_fields(self, member) -> OperationResult[Dict[str, Any]]:
        """
        Synchronize status and application_status fields.

        Args:
            member: Member document to synchronize

        Returns:
            OperationResult[Dict]: OperationResult with status sync data on success
        """
        try:
            changes_made = []

            # Check if this member was created through application process
            is_application_member = bool(getattr(member, "application_id", None))

            if is_application_member:
                # Handle application-created members
                if hasattr(member, "application_status") and member.application_status:
                    if member.application_status == "Approved" and member.status != "Active":
                        member.status = "Active"
                        changes_made.append("Set status to Active (application approved)")

                        # Set member_since date when application becomes approved
                        if not getattr(member, "member_since", None):
                            member.member_since = today()
                            changes_made.append("Set member_since date")

                    elif member.application_status == "Rejected" and member.status != "Rejected":
                        # Don't override status if member was terminated
                        if member.status not in ["Terminated", "Suspended"]:
                            member.status = "Rejected"
                            changes_made.append("Set status to Rejected (application rejected)")
            else:
                # Handle backend-created members
                if not hasattr(member, "application_status") or not member.application_status:
                    member.application_status = "Approved"
                    changes_made.append("Set application_status to Approved (backend-created member)")

            return OperationResult.ok(
                {
                    "changes_made": changes_made,
                    "is_application_member": is_application_member,
                    "final_status": member.status,
                    "final_application_status": getattr(member, "application_status", None),
                }
            )

        except Exception as e:
            self.logger.error(f"Error syncing status fields for member {member.name}: {str(e)}")
            return OperationResult.fail(
                f"Status synchronization failed: {str(e)}",
                changes_made=[],
                is_application_member=False,
                final_status=None,
                final_application_status=None,
            )

    def get_status_color(self, status: str) -> str:
        """
        Get display color for member status.

        Args:
            status: Member status

        Returns:
            Color code for status display
        """
        status_colors = {
            "Active": "green",
            "Inactive": "gray",
            "Suspended": "orange",
            "Terminated": "red",
            "Pending": "blue",
            "Rejected": "red",
            "Application": "blue",
        }
        return status_colors.get(status, "gray")

    def is_application_member(self, member) -> bool:
        """
        Check if member was created through application process.

        Args:
            member: Member document to check

        Returns:
            True if member has application_id, False otherwise
        """
        return bool(getattr(member, "application_id", None))

    # Private helper methods

    def _validate_application_approval(self, member) -> OperationResult[None]:
        """Validate that application can be approved

        Returns:
            OperationResult[None]: Success if validation passes, failure with errors otherwise
        """
        if not self.is_application_member(member):
            return OperationResult.fail(
                "Not an application member", errors=["This is not an application member"]
            )

        if getattr(member, "application_status", None) == "Approved":
            return OperationResult.fail("Already approved", errors=["Application is already approved"])

        return OperationResult.ok(None)

    def _validate_application_rejection(self, member) -> OperationResult[None]:
        """Validate that application can be rejected

        Returns:
            OperationResult[None]: Success if validation passes, failure with errors otherwise
        """
        if not self.is_application_member(member):
            return OperationResult.fail(
                "Not an application member", errors=["This is not an application member"]
            )

        if getattr(member, "application_status", None) == "Rejected":
            return OperationResult.fail("Already rejected", errors=["Application is already rejected"])

        return OperationResult.ok(None)

    def _save_member_with_retry(self, member, operation: str) -> OperationResult[None]:
        """Save member with concurrency handling

        Returns:
            OperationResult[None]: Success if save succeeds, failure with errors otherwise
        """
        try:
            member.save()
            return OperationResult.ok(None)
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            try:
                member.reload()

                # Re-apply changes based on operation
                if operation == "approve":
                    if not member.member_id:
                        member.member_id = member.generate_member_id()
                    member.application_status = "Approved"
                    member.status = "Active"
                    member.reviewed_by = frappe.session.user
                    member.review_date = now_datetime()
                    # Preserve flag after reload
                    member.flags.ignore_status_validation = True
                elif operation == "reject":
                    member.application_status = "Rejected"
                    member.status = "Rejected"
                    member.reviewed_by = frappe.session.user
                    member.review_date = now_datetime()
                    # Restore rejection_reason from flags if available
                    if hasattr(member.flags, "rejection_reason"):
                        member.review_notes = member.flags.rejection_reason
                    # Preserve flags after reload
                    member.flags.ignore_status_validation = True

                member.save()
                return OperationResult.ok(None, retried=True)
            except Exception as e:
                return OperationResult.fail(f"Failed to save after retry: {str(e)}")
        except Exception as e:
            return OperationResult.fail(f"Failed to save member: {str(e)}")

    def _perform_post_approval_setup(self, member) -> Dict[str, Any]:
        """Perform post-approval setup tasks"""
        setup_results = {
            "user_created": False,
            "customer_created": False,
            "chapter_activated": False,
            "errors": [],
        }

        try:
            # Create user account immediately (synchronous) for approval workflow
            if not member.user:
                try:
                    from verenigingen.services.member.account.member_user_account_service import (
                        get_member_user_account_service,
                    )

                    user_name, _action = get_member_user_account_service().create_user_for_member(member)
                    setup_results["user_created"] = True
                    setup_results["user_name"] = user_name
                    self.logger.info(f"Created user account {user_name} for member {member.name}")
                    # Reload member to get updated user field
                    member.reload()
                except Exception as e:
                    setup_results["errors"].append(f"Failed to create user: {str(e)}")
                    self.logger.error(f"Exception creating user for {member.name}: {str(e)}")

            # Create customer if not exists
            if not member.customer:
                try:
                    member.create_customer()
                    setup_results["customer_created"] = True
                except Exception as e:
                    setup_results["errors"].append(f"Failed to create customer: {str(e)}")

            # Activate pending Chapter Member records
            try:
                from verenigingen.utils.application_helpers import activate_pending_chapter_membership

                # Find pending chapter memberships for this member
                # Note: Chapter Member is a child table, so the chapter is in 'parent' field
                pending_chapters = frappe.db.sql(
                    """
                    SELECT parent as chapter, name
                    FROM `tabChapter Member`
                    WHERE member = %s AND status = 'Pending'
                    """,
                    (member.name,),
                    as_dict=True,
                )

                activated_chapters = []
                for chapter_record in pending_chapters:
                    try:
                        success = activate_pending_chapter_membership(member, chapter_record.chapter)
                        if success:
                            activated_chapters.append(chapter_record.chapter)
                    except Exception as e:
                        setup_results["errors"].append(
                            f"Failed to activate chapter {chapter_record.chapter}: {str(e)}"
                        )

                if activated_chapters:
                    setup_results["chapter_activated"] = True
                    setup_results["activated_chapters"] = activated_chapters

            except Exception as e:
                setup_results["errors"].append(f"Failed to activate chapter memberships: {str(e)}")

        except Exception as e:
            setup_results["errors"].append(f"Post-approval setup failed: {str(e)}")

        return setup_results

    def _perform_post_rejection_cleanup(self, member) -> Dict[str, Any]:
        """Perform post-rejection cleanup tasks.

        Removes ALL pending chapter memberships (not just one), updating both
        Chapter Member records and chapter membership history.
        """
        cleanup_results = {"chapters_removed": [], "errors": []}

        try:
            from verenigingen.utils.application_helpers import remove_all_pending_chapter_memberships

            cleanup_results["chapters_removed"] = remove_all_pending_chapter_memberships(member)
        except Exception as e:
            cleanup_results["errors"].append(f"Post-rejection cleanup failed: {str(e)}")

        return cleanup_results

    def _get_active_membership(self, member):
        """
        Get active membership for member - delegates to MemberMembershipService.

        REFACTORED: Now uses MemberMembershipService for consistent membership queries.
        """
        try:
            from verenigingen.services.member.core.member_membership_service import MemberMembershipService

            return MemberMembershipService().get_active_membership_for_member_doc(member)
        except Exception:
            return None

    def _get_most_recent_expired_membership(self, member):
        """Get most recent expired membership for member"""
        try:
            expired = frappe.get_all(
                "Membership",
                filters={"member": member.name, "renewal_date": ["<", today()], "docstatus": 1},
                fields=["name", "membership_type", "renewal_date"],
                order_by="renewal_date desc",
                limit=1,
            )

            if expired:
                return frappe.get_doc("Membership", expired[0].name)
            return None
        except Exception:
            return None


# Lazy singleton - initialized on first access to avoid circular import issues
_member_lifecycle_service_instance = None


def get_member_lifecycle_service() -> MemberLifecycleService:
    """Get MemberLifecycleService instance (lazy singleton to avoid circular imports)."""
    global _member_lifecycle_service_instance
    if _member_lifecycle_service_instance is None:
        _member_lifecycle_service_instance = MemberLifecycleService()
    return _member_lifecycle_service_instance


# For backward compatibility with `from ... import member_lifecycle_service`
# Use __getattr__ for lazy access - no explicit binding here
def __getattr__(name):
    """Module-level __getattr__ for lazy singleton access."""
    if name == "member_lifecycle_service":
        return get_member_lifecycle_service()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
