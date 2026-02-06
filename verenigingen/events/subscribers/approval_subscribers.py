"""
Background Job Handlers for Member Approval Events

These functions handle the heavy operations triggered by member approval events,
running in background jobs to prevent timestamp conflicts and improve performance.

Each handler is designed to be idempotent and resilient to failures.
"""

import logging

import frappe
from frappe import _
from frappe.utils import now_datetime

logger = logging.getLogger(__name__)


def handle_customer_creation(event_name, event_data, **kwargs):
    """
    Background job to create customer record for approved member.

    This runs after the main approval transaction to avoid document conflicts.
    Includes retry logic and database transaction protection.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    if not member_name:
        return

    # Retry logic for resilience
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            member = frappe.get_doc("Member", member_name)

            # Check if customer already exists
            if member.customer:
                logger.info(f"Customer already exists for member {member_name}: {member.customer}")
                return {"success": True, "action": "already_exists", "customer": member.customer}

            # Create customer using existing helper
            from verenigingen.api.payment_processing import get_or_create_customer

            customer_result = get_or_create_customer(member)
            if customer_result:
                logger.info(f"Customer created for member {member_name}: {customer_result}")
                return {"success": True, "action": "created", "customer": customer_result}
            else:
                raise Exception("Customer creation failed")

        except Exception as e:
            retry_count += 1

            if retry_count >= max_retries:
                logger.error(
                    f"Error in customer creation background job for {member_name} after {max_retries} attempts: {str(e)}"
                )
                frappe.log_error(
                    f"Customer creation background job failed for {member_name}: {str(e)}",
                    "Approval Background Job Error",
                )
                return {"success": False, "error": str(e), "retries": retry_count}
            else:
                logger.warning(
                    f"Customer creation attempt {retry_count} failed for {member_name}, retrying: {str(e)}"
                )
                import time

                time.sleep(10 * (2**retry_count))  # Conservative exponential backoff: 20s, 40s, 80s


def handle_chapter_assignment(event_name, event_data, **kwargs):
    """
    Background job to assign member to chapter.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    chapter = event_data.get("chapter")

    if not member_name or not chapter:
        return {"success": True, "action": "skipped", "reason": "No chapter specified"}

    try:
        member = frappe.get_doc("Member", member_name)

        # Activate the pending chapter membership created during application submission
        from verenigingen.utils.application_helpers import activate_pending_chapter_membership

        activate_pending_chapter_membership(member, chapter)

        logger.info(f"Chapter membership activated for member {member_name} in chapter {chapter}")
        return {"success": True, "action": "activated", "chapter": chapter}

    except Exception as e:
        logger.error(f"Error in chapter assignment background job for {member_name}: {str(e)}")
        frappe.log_error(
            f"Chapter assignment background job failed for {member_name}: {str(e)}",
            "Approval Background Job Error",
        )
        return {"success": False, "error": str(e)}


def handle_iban_history_creation(event_name, event_data, **kwargs):
    """
    Background job to create initial IBAN history record.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    if not member_name:
        return

    try:
        member = frappe.get_doc("Member", member_name)

        # Use existing helper function
        from verenigingen.services.member.approval.member_approval_service import create_member_iban_history

        create_member_iban_history(member)

        logger.info(f"IBAN history creation completed for member {member_name}")
        return {"success": True, "action": "created"}

    except Exception as e:
        logger.error(f"Error in IBAN history creation background job for {member_name}: {str(e)}")
        # This is non-critical, so don't fail the entire process
        return {"success": False, "error": str(e), "critical": False}


def handle_user_account_creation(event_name, event_data, **kwargs):
    """
    Background job to create user account for approved member.

    Uses the existing AccountCreationManager which already supports background processing.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    if not member_name:
        return

    try:
        member = frappe.get_doc("Member", member_name)

        # Use existing secure account creation system
        from verenigingen.services.member.account.member_user_account_service import create_secure_user_account_for_member

        user_creation_result = create_secure_user_account_for_member(member)

        logger.info(f"User account creation initiated for member {member_name}: {user_creation_result}")
        return user_creation_result

    except Exception as e:
        logger.error(f"Error in user account creation background job for {member_name}: {str(e)}")
        # User accounts can be created manually later, so this is non-critical
        return {"success": False, "error": str(e), "critical": False}


def handle_approval_notification(event_name, event_data, **kwargs):
    """
    Background job to send approval notification email.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member and invoice information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    invoice_name = event_data.get("invoice")

    if not member_name:
        return

    try:
        member = frappe.get_doc("Member", member_name)
        invoice = None
        membership_type_doc = None

        if invoice_name:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_name)

                # Get membership type for email template
                if hasattr(member, "selected_membership_type") and member.selected_membership_type:
                    membership_type_doc = frappe.get_doc("Membership Type", member.selected_membership_type)

            except Exception as e:
                logger.warning(f"Could not load invoice {invoice_name} for notification: {str(e)}")

        # Use existing notification helper
        from verenigingen.api.membership_application_review import send_approval_notification

        send_approval_notification(member, invoice, membership_type_doc)

        logger.info(f"Approval notification sent for member {member_name}")
        return {"success": True, "action": "notification_sent"}

    except Exception as e:
        logger.error(f"Error in approval notification background job for {member_name}: {str(e)}")
        # Email notifications are non-critical
        return {"success": False, "error": str(e), "critical": False}


def handle_volunteer_activation(event_name, event_data, **kwargs):
    """
    Background job to activate volunteer record if member is interested in volunteering.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Event payload with member information
        **kwargs: Additional job metadata (dedupe, delay, etc.) - ignored
    """
    member_name = event_data.get("member")
    if not member_name:
        return

    try:
        member = frappe.get_doc("Member", member_name)

        # Check if member is interested in volunteering
        if not (hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering):
            return {"success": True, "action": "skipped", "reason": "Not interested in volunteering"}

        # Use existing volunteer activation helper
        from verenigingen.services.volunteer.volunteer_activation_service import activate_volunteer_record

        activate_volunteer_record(member)

        logger.info(f"Volunteer activation completed for member {member_name}")
        return {"success": True, "action": "volunteer_activated"}

    except Exception as e:
        logger.error(f"Error in volunteer activation background job for {member_name}: {str(e)}")
        # Volunteer activation is non-critical
        return {"success": False, "error": str(e), "critical": False}


def get_approval_background_job_status(member_name):
    """
    Utility function to check the status of background jobs for a member approval.

    This can be called by the frontend to show progress to users.
    """
    if not member_name:
        return {"error": "Member name required"}

    try:
        # Check for active jobs related to this member
        active_jobs = frappe.get_all(
            "RQ Job",
            filters={
                "job_name": ["like", f"approval_%_{member_name}"],
                "status": ["in", ["queued", "started"]],
            },
            fields=["job_name", "status", "creation", "modified"],
        )

        completed_jobs = frappe.get_all(
            "RQ Job",
            filters={"job_name": ["like", f"approval_%_{member_name}"], "status": "finished"},
            fields=["job_name", "status", "creation", "modified"],
        )

        failed_jobs = frappe.get_all(
            "RQ Job",
            filters={"job_name": ["like", f"approval_%_{member_name}"], "status": "failed"},
            fields=["job_name", "status", "creation", "modified", "exc_info"],
        )

        return {
            "member": member_name,
            "active_jobs": len(active_jobs),
            "completed_jobs": len(completed_jobs),
            "failed_jobs": len(failed_jobs),
            "jobs": {"active": active_jobs, "completed": completed_jobs, "failed": failed_jobs},
        }

    except Exception as e:
        logger.error(f"Error checking background job status for {member_name}: {str(e)}")
        return {"error": str(e)}
