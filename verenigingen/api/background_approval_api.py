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

import frappe
from frappe import _
from frappe.utils import now_datetime, today

# Import security decorators
from verenigingen.utils.security.api_security_framework import high_security_api


@frappe.whitelist()
@high_security_api()  # Member application approval workflow
def approve_membership_application_background(
    member_name, membership_type=None, chapter=None, notes=None, create_invoice=True
):
    """
    Approve a membership application using background processing for heavy operations.

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
        Dict with approval status and background job info
    """
    # Input sanitization and validation
    from verenigingen.utils.security.rate_limiter import log_security_event, validate_input_security

    try:
        # Validate and sanitize all inputs
        member_name = validate_input_security(member_name, "member_name", max_length=255)
        if membership_type:
            membership_type = validate_input_security(membership_type, "membership_type", max_length=255)
        if chapter:
            chapter = validate_input_security(chapter, "chapter", max_length=255)
        if notes:
            notes = validate_input_security(notes, "notes", max_length=2000, allow_html=False)

        # Validate member exists before proceeding
        if not frappe.db.exists("Member", member_name):
            log_security_event(
                frappe.session.user,
                "invalid_member_access",
                f"Attempted approval of non-existent member: {member_name}",
                "high",
            )
            frappe.throw(_("Invalid member reference"))

    except Exception as e:
        log_security_event(
            frappe.session.user,
            "input_validation_failure",
            f"Input validation failed for approval: {str(e)}",
            "medium",
        )
        frappe.throw(_("Invalid input data provided"))

    member = frappe.get_doc("Member", member_name)

    # Validate application can be approved
    if member.application_status not in ["Pending"]:
        frappe.throw(_("This application cannot be approved in its current state"))

    # Check chapter-based permissions
    from verenigingen.utils.chapter_security import validate_chapter_permission_or_throw

    validate_chapter_permission_or_throw(member_name, "approve")

    # Resolve membership type using existing helper
    from verenigingen.api.membership_application_review import resolve_membership_type

    membership_type = resolve_membership_type(member, membership_type)

    # Pre-check: Validate membership type has a valid dues schedule template
    from verenigingen.api.membership_application_review import validate_membership_type_for_approval

    validate_membership_type_for_approval(membership_type, member, is_application_approval=True)

    # ==========================================
    # CRITICAL SYNCHRONOUS OPERATIONS
    # ==========================================
    # These operations must complete in the main transaction for workflow consistency

    # 1. Update member status (CRITICAL - must be synchronous)
    # Use retry logic for timestamp conflicts (Frappe handles transactions natively)
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Reload member to get latest data and avoid timestamp conflicts
            member.reload()

            member.application_status = "Approved"
            member.status = "Active"
            member.member_since = today()
            member.reviewed_by = frappe.session.user
            member.review_date = now_datetime()
            if notes:
                member.review_notes = notes

            # Set selected membership type
            try:
                member.selected_membership_type = membership_type
            except AttributeError:
                # Field might not exist in database yet, log but continue
                frappe.logger().warning(
                    f"Could not set selected_membership_type field on member {member.name}"
                )

            member.save()  # Frappe handles transaction automatically

            log_security_event(
                frappe.session.user,
                "membership_approved",
                f"Member {member_name} approved with status change: Pending -> Approved/Active",
                "low",
            )
            break  # Success - exit retry loop

        except frappe.TimestampMismatchError as e:
            retry_count += 1

            if retry_count >= max_retries:
                log_security_event(
                    frappe.session.user,
                    "approval_save_failed",
                    f"Failed to save member {member_name} after {max_retries} attempts due to timestamp conflicts",
                    "high",
                )
                frappe.throw(_("Document was modified during approval. Please refresh and try again."))
            else:
                # Wait before retrying (shorter for user-facing operation)
                import time

                time.sleep(1 + (retry_count * 0.5))  # 1.5s, 2s, 2.5s

        except Exception as e:
            log_security_event(
                frappe.session.user,
                "approval_save_failed",
                f"Failed to save member {member_name} during approval: {str(e)}",
                "high",
            )
            frappe.throw(_("Failed to save member approval status. Please try again."))

    # 2. Create invoice (synchronous for immediate user feedback)
    invoice = None
    if create_invoice:
        try:
            from verenigingen.api.membership_application_review import create_membership_and_invoice

            membership, membership_type_doc, billing_amount = create_membership_and_invoice(
                member, membership_type
            )

            # Create invoice for immediate feedback
            # First ensure customer exists (quick operation)
            from verenigingen.api.payment_processing import create_application_invoice, get_or_create_customer

            customer_result = get_or_create_customer(member)
            if customer_result:
                invoice = create_application_invoice(member, membership)

        except Exception as e:
            # Log the error but continue - background jobs will handle any cleanup needed
            frappe.log_error(
                f"Invoice creation failed during background approval for {member_name}: {str(e)}",
                "Background Approval Invoice Error",
            )
            invoice = None

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
            f"Failed to emit background events for {member_name}: {str(e)}", "Background Approval Event Error"
        )

    # ==========================================
    # RESPONSE WITH PROGRESS TRACKING
    # ==========================================

    response = {
        "success": True,
        "message": _("Application approved! Background processing initiated for additional setup."),
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

    return response


@frappe.whitelist()
def get_approval_progress(member_name):
    """
    API endpoint to check the progress of background approval operations.

    This allows the frontend to show real-time progress to users.
    """
    try:
        from verenigingen.events.subscribers.approval_subscribers import get_approval_background_job_status

        return get_approval_background_job_status(member_name)

    except Exception as e:
        frappe.log_error(f"Error getting approval progress for {member_name}: {str(e)}")
        return {"error": "Failed to get progress status"}


def safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)
