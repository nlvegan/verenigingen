"""
Background Processing Member Approval API

Lightweight approval API that uses event-driven background processing to eliminate
timestamp conflicts and improve performance. This replaces the heavy synchronous
operations in the original approval flow.

Architecture:
1. Fast synchronous operations: Member status, invoice creation
2. Event emission for background operations: Customer, chapter, notifications
3. User feedback with progress tracking
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.operation_result import OperationResult

# Import security decorators
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
@high_security_api()  # Member application approval workflow
def approve_membership_application_background(
    member_name: str,
    membership_type: str = None,
    chapter: str = None,
    notes: str = None,
    create_invoice: bool = True,
) -> OperationResult[Dict[str, Any]]:
    """
    Approve a membership application using background processing for heavy operations.

    .. deprecated::
        Never adopted in production. The canonical approval path is
        ``approve_membership_application()`` in ``api/membership_application_review.py``.

    This lightweight version handles critical operations synchronously and queues
    heavy operations in background jobs to prevent timestamp conflicts.

    Synchronous operations (fast, critical):
    - Member status updates
    - Invoice creation (for immediate user feedback)
    - Basic validation

    Background operations (heavy, non-critical):
    - Customer creation
    - Chapter assignment
    - User account creation
    - Email notifications
    - IBAN history
    - Volunteer activation

    Args:
        member_name: Name of member to approve
        membership_type: Membership type (optional)
        chapter: Chapter to assign to (optional)
        notes: Approval notes (optional)
        create_invoice: Whether to create invoice (default True)

    Returns:
        OperationResult[Dict[str, Any]]: Approval status and background job info
    """
    try:
        # Input sanitization and validation
        from verenigingen.utils.security.audit_logging import log_security_event
        from verenigingen.utils.validation.api_validators import APIValidator

        try:
            # Validate and sanitize all inputs
            member_name = APIValidator.sanitize_text(str(member_name), max_length=255)
            if membership_type:
                membership_type = APIValidator.sanitize_text(str(membership_type), max_length=255)
            if chapter:
                chapter = APIValidator.sanitize_text(str(chapter), max_length=255)
            if notes:
                notes = APIValidator.sanitize_text(str(notes), max_length=2000, allow_html=False)

            # Validate member exists before proceeding
            if not frappe.db.exists("Member", member_name):
                log_security_event(
                    "invalid_member_access",
                    {"message": f"Attempted approval of non-existent member: {member_name}"},
                    severity="error",
                )
                frappe.throw(_("Invalid member reference"))

        except Exception as e:
            log_security_event(
                "input_validation_failure",
                {"message": f"Input validation failed for approval: {str(e)}"},
                severity="warning",
            )
            frappe.throw(_("Invalid input data provided"))

        member = frappe.get_doc("Member", member_name)

        # Validate application can be approved
        if member.application_status not in ["Pending"]:
            frappe.throw(_("This application cannot be approved in its current state"))

        # Check chapter-based permissions
        from verenigingen.services.chapter.chapter_security import validate_chapter_permission_or_throw

        validate_chapter_permission_or_throw(member_name, "approve")

        # Resolve membership type using approval service helper
        from verenigingen.services.member.approval.member_approval_service import resolve_membership_type

        membership_type = resolve_membership_type(member, membership_type)

        # Pre-check: Validate membership type has a valid dues schedule template
        from verenigingen.services.member.approval.member_approval_service import (
            validate_membership_type_for_approval,
        )

        validate_membership_type_for_approval(membership_type, member, is_application_approval=True)

        # ==========================================
        # CRITICAL SYNCHRONOUS OPERATIONS
        # ==========================================
        # Create membership and invoice via canonical MembershipCreationService path.
        # approval_fields are passed through to be set on the member in one consolidated save,
        # avoiding the timestamp conflicts that the old retry loop tried to work around.

        # Build approval_fields — same pattern as the canonical review API
        approval_fields = {
            "application_status": "Approved",
            "status": "Active",
            "member_since": today(),
            "reviewed_by": frappe.session.user,
            "review_date": now_datetime(),
            "selected_membership_type": membership_type,
        }
        if notes:
            approval_fields["review_notes"] = notes

        # If member has custom dues rate, set fee_override_reason to satisfy validation
        if hasattr(member, "dues_rate") and member.dues_rate:
            if not getattr(member, "fee_override_reason", None):
                approval_fields["fee_override_reason"] = "Application approval"

        invoice = None
        membership = None
        try:
            membership = member.create_membership_on_approval(
                create_invoice=create_invoice,
                approval_fields=approval_fields,
            )

            # Get invoice from member after create_membership_on_approval sets it
            member.reload()
            if hasattr(member, "application_invoice") and member.application_invoice:
                invoice = frappe.get_doc("Sales Invoice", member.application_invoice)

            log_security_event(
                "data_modification",
                {"message": f"Membership approved: {member_name} status change Pending -> Approved/Active"},
                severity="info",
            )

        except (frappe.ValidationError, frappe.PermissionError):
            raise
        except Exception as e:
            frappe.log_error(
                f"Membership creation failed during background approval for {member_name}: {str(e)}",
                "Background Approval Error",
            )
            frappe.throw(_("Failed to approve membership application. Please try again."))

        # ==========================================
        # EMIT EVENTS FOR BACKGROUND PROCESSING
        # ==========================================
        # These operations are queued as background jobs to prevent timestamp conflicts

        approval_data = {
            "membership_type": membership_type,
            "chapter": chapter,
            "notes": notes,
            "create_invoice": create_invoice,
        }

        try:
            from verenigingen.events.approval_events import emit_member_approval_initiated

            emit_member_approval_initiated(member_name, approval_data)

            # Emit completion event with invoice info
            completion_data = {
                "invoice": invoice.name if invoice else None,
                "user_account_status": "queued",  # Will be updated by background jobs
            }

            from verenigingen.events.approval_events import emit_member_approval_completed

            emit_member_approval_completed(member_name, completion_data)

        except Exception as e:
            # Event emission errors should not fail the approval
            frappe.log_error(
                f"Failed to emit background events for {member_name}: {str(e)}",
                "Background Approval Event Error",
            )

        # ==========================================
        # RESPONSE WITH PROGRESS TRACKING
        # ==========================================

        response = {
            "member_id": member.member_id,
            "invoice": invoice.name if invoice else None,
            "amount": invoice.grand_total if invoice else None,
            # Background processing info
            "background_processing": {
                "status": "initiated",
                "operations": [
                    "customer_creation",
                    "chapter_assignment" if chapter else None,
                    "user_account_creation",
                    "email_notifications",
                    "iban_history_creation",
                    "volunteer_activation" if getattr(member, "interested_in_volunteering", False) else None,
                ],
                "estimated_completion": "2-3 minutes",
                "tracking_endpoint": f"/api/method/verenigingen.events.subscribers.approval_subscribers.get_approval_background_job_status?member_name={member_name}",
            },
            # Progress tracking for UI
            "progress_tracking": {
                "immediate_complete": ["member_status", "invoice_creation" if invoice else None],
                "background_pending": ["customer_creation", "notifications", "user_accounts"],
                "can_track_progress": True,
            },
        }

        # Filter out None values from operations list
        response["background_processing"]["operations"] = [
            op for op in response["background_processing"]["operations"] if op is not None
        ]

        return OperationResult.ok(
            response, message=_("Application approved! Background processing initiated for additional setup.")
        )

    except Exception as e:
        frappe.log_error(
            f"Member approval background processing failed: {str(e)}\n{traceback.format_exc()}",
            "Background Approval API Error",
        )
        return OperationResult.fail(
            _("Failed to approve membership application"),
            errors=[str(e)],
            context={"member_name": member_name, "operation": "approve_membership_application_background"},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_approval_progress(member_name: str) -> OperationResult[Dict[str, Any]]:
    """
    API endpoint to check the progress of background approval operations.

    This allows the frontend to show real-time progress to users.

    Args:
        member_name: Name of member to check approval progress for

    Returns:
        OperationResult[Dict[str, Any]]: Background job status and progress information
    """
    try:
        from verenigingen.events.subscribers.approval_subscribers import get_approval_background_job_status

        status = get_approval_background_job_status(member_name)

        return OperationResult.ok(status, message=_("Approval progress retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting approval progress for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Get Approval Progress Error",
        )
        return OperationResult.fail(
            _("Failed to retrieve approval progress status"),
            errors=[str(e)],
            context={"member_name": member_name, "operation": "get_approval_progress"},
        )
