"""
Member Event Subscribers

Background job handlers for member status and lifecycle change events.
These handle the actual business logic triggered by member status transitions.
"""

import time

import frappe
from frappe import _

from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


def handle_status_change_notifications(event_name, event_data, **kwargs):
    """
    Handle notification sending for member status changes.

    Sends appropriate emails based on status transitions (Pending -> Approved, etc.).

    Args:
        event_name: Name of the event being handled
        event_data: Event data dictionary
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        # Skip notifications during bulk imports
        if frappe.flags.in_import or frappe.flags.in_bulk_import:
            return

        member_name = event_data.get("member")
        old_status = event_data.get("old_status")
        new_status = event_data.get("new_status")
        status_type = event_data.get("status_type")

        if not member_name:
            frappe.logger("events").warning("No member name in status change notification event")
            return

        # Check if member still exists before attempting to send notifications
        if not frappe.db.exists("Member", member_name):
            frappe.logger("events").warning(
                f"Cannot send status change notification - Member {member_name} no longer exists"
            )
            return

        member = frappe.get_doc("Member", member_name)

        # Send approval notification for application status changes
        if status_type == "application" and new_status == "Approved":
            _send_approval_notification(member)

        # Send status change notification for lifecycle changes
        elif status_type == "lifecycle":
            _send_lifecycle_notification(member, old_status, new_status)

        frappe.logger("events").info(
            f"Sent status change notification for {member_name}: {old_status} -> {new_status}"
        )

    except Exception as e:
        # Log production errors with full traceback for audit trail
        # Bulk import skip already handled above, so this is a real error
        frappe.log_error(
            title=f"Member Status Notification Error: {event_data.get('member')}",
            message=frappe.get_traceback(),
        )


def handle_chapter_assignment_updates(event_name, event_data, **kwargs):
    """
    Handle chapter assignment updates when member status changes.

    Updates chapter membership records based on member status transitions.

    Args:
        event_name: Name of the event being handled
        event_data: Event data dictionary
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        # Skip during bulk imports
        if frappe.flags.in_import or frappe.flags.in_bulk_import:
            return

        # Skip during bulk operations - chapter assignment is handled in bulk
        if getattr(frappe.flags, "bulk_member_operations", False):
            frappe.logger("events").info("Skipping chapter assignment update - bulk operation in progress")
            return

        member_name = event_data.get("member")
        new_status = event_data.get("new_status")

        if not member_name:
            return

        # Check if member still exists before attempting to update chapter assignments
        if not frappe.db.exists("Member", member_name):
            frappe.logger("events").warning(
                f"Cannot update chapter assignments - Member {member_name} no longer exists"
            )
            return

        member = frappe.get_doc("Member", member_name)

        # Update chapter assignments based on new status
        if new_status == "Approved":
            _assign_member_to_chapter(member)
        elif new_status in ["Suspended", "Terminated"]:
            _update_chapter_membership_status(member, new_status)

        frappe.logger("events").info(f"Updated chapter assignments for {member_name}")

    except Exception as e:
        # Log production errors with full traceback for audit trail
        # Bulk import skip already handled above, so this is a real error
        frappe.log_error(
            title=f"Chapter Assignment Error: {event_data.get('member')}", message=frappe.get_traceback()
        )


def handle_lifecycle_notifications(event_name, event_data, **kwargs):
    """
    Handle notifications for member lifecycle changes.

    Sends appropriate communications for status transitions like Active -> Suspended.

    Args:
        event_name: Name of the event being handled
        event_data: Event data dictionary
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        member_name = event_data.get("member")
        old_status = event_data.get("old_status")
        new_status = event_data.get("new_status")

        if not member_name:
            return

        # Check if member still exists before attempting to send lifecycle notifications
        if not frappe.db.exists("Member", member_name):
            frappe.logger("events").warning(
                f"Cannot send lifecycle notification - Member {member_name} no longer exists"
            )
            return

        member = frappe.get_doc("Member", member_name)

        # Send lifecycle-specific notifications
        if new_status == "Suspended":
            _send_suspension_notification(member)
        elif new_status == "Terminated":
            _send_termination_notification(member)
        elif new_status == "Active" and old_status in ["Suspended", "Inactive"]:
            _send_reactivation_notification(member)

        frappe.logger("events").info(
            f"Sent lifecycle notification for {member_name}: {old_status} -> {new_status}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to send lifecycle notification: {str(e)}", "Member Lifecycle Notification Error"
        )


def handle_user_account_updates(event_name, event_data, **kwargs):
    """
    Handle user account updates when member lifecycle changes.

    Manages user account status based on member status transitions.

    Args:
        event_name: Name of the event being handled
        event_data: Event data dictionary
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        member_name = event_data.get("member")
        old_status = event_data.get("old_status")
        new_status = event_data.get("new_status")

        if not member_name:
            return

        # Skip if status hasn't actually changed
        if old_status == new_status:
            frappe.logger("events").info(
                f"Skipping user account update for {member_name} - status unchanged ({old_status})"
            )
            return

        # Check if member still exists before attempting to update user account
        if not frappe.db.exists("Member", member_name):
            frappe.logger("events").warning(
                f"Cannot update user account - Member {member_name} no longer exists"
            )
            return

        member = frappe.get_doc("Member", member_name)

        # Update user account based on member status
        if hasattr(member, "user") and member.user:
            user_doc = frappe.get_doc("User", member.user)

            # Only update if there's an actual change
            if new_status in ["Suspended", "Terminated"] and user_doc.enabled == 1:
                user_doc.enabled = 0
                user_doc.save()
            elif new_status == "Active" and user_doc.enabled == 0:
                user_doc.enabled = 1
                user_doc.save()

        frappe.logger("events").info(f"Updated user account for {member_name}")

    except Exception as e:
        # Use shorter error message to avoid field length issues
        error_msg = str(e)[:100]  # Truncate to avoid field length errors
        frappe.log_error(f"User account update failed: {error_msg}", "User Account Update")


def handle_cache_invalidation(event_name, event_data, **kwargs):
    """
    Handle cache invalidation for member lifecycle changes.

    Clears relevant caches when member status changes to ensure data consistency.

    Args:
        event_name: Name of the event being handled
        event_data: Event data dictionary
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        member_name = event_data.get("member")

        if not member_name:
            return

        # Check if member still exists before invalidating caches
        # Note: We still clear caches even if member is deleted, as stale cache entries should be removed
        if not frappe.db.exists("Member", member_name):
            frappe.logger("events").info(f"Member {member_name} no longer exists - clearing caches anyway")

        # Clear member-specific caches
        frappe.cache().delete_keys("member_dashboard_*")
        frappe.cache().delete_keys("chapter_members_*")
        frappe.cache().delete_keys("analytics_*")

        # Clear global member statistics cache
        frappe.cache().delete_key("member_statistics")

        frappe.logger("events").info(f"Cleared caches for member {member_name}")

    except Exception as e:
        frappe.log_error(f"Failed to clear caches: {str(e)}", "Cache Invalidation Error")


# Helper functions for specific notification types


def _send_approval_notification(member):
    """Send approval notification email to new member"""
    if not member.email:
        return

    try:
        # MIGRATED: Use unified EmailService instead of direct template calls
        from verenigingen.services.communication.compatibility import send_member_notification

        result = send_member_notification(
            member_name=member.name,
            notification_type="approval",
            context={"member_name": member.full_name, "membership_number": member.name},
        )

        if result.get("success"):
            frappe.logger("events").info(f"Approval notification sent successfully to {member.email}")
        else:
            frappe.logger("events").warning(
                f"Failed to send approval notification: {'; '.join(result.get('errors', []))}"
            )

    except Exception as e:
        frappe.logger("events").error(f"Failed to send approval notification: {str(e)}")


def _send_lifecycle_notification(member, old_status, new_status):
    """Send general lifecycle change notification"""
    if not member.email:
        return

    # MIGRATED: Use unified EmailService with professional template
    from verenigingen.services.communication.email_service import get_email_service

    email_service = get_email_service()
    context = {
        "member_name": member.full_name,
        "old_status": old_status,
        "new_status": new_status,
        "membership_number": member.name,
        "company": get_mollie_config().get_default_company(),
    }

    email_service.send_templated_email(
        template_name="member_lifecycle_notification",
        recipients=[member.email],
        context=context,
        subject_override=f"Membership Status Update: {old_status} to {new_status}",
        reference_doctype="Member",
        reference_name=member.name,
    )


def _send_suspension_notification(member):
    """Send suspension notification"""
    if not member.email:
        return

    try:
        # MIGRATED: Use unified EmailService instead of direct template calls
        from verenigingen.services.communication.compatibility import send_member_notification

        result = send_member_notification(
            member_name=member.name,
            notification_type="suspension",
            context={"member_name": member.full_name, "membership_number": member.name},
        )

        if result.get("success"):
            frappe.logger("events").info(f"Suspension notification sent successfully to {member.email}")
        else:
            frappe.logger("events").warning(
                f"Failed to send suspension notification: {'; '.join(result.get('errors', []))}"
            )

    except Exception as e:
        frappe.logger("events").error(f"Failed to send suspension notification: {str(e)}")


def _send_termination_notification(member):
    """Send termination notification"""
    if not member.email:
        return

    try:
        # MIGRATED: Use unified EmailService instead of direct template calls
        from verenigingen.services.communication.compatibility import send_member_notification

        result = send_member_notification(
            member_name=member.name,
            notification_type="termination",
            context={"member_name": member.full_name, "membership_number": member.name},
        )

        if result.get("success"):
            frappe.logger("events").info(f"Termination notification sent successfully to {member.email}")
        else:
            frappe.logger("events").warning(
                f"Failed to send termination notification: {'; '.join(result.get('errors', []))}"
            )

    except Exception as e:
        frappe.logger("events").error(f"Failed to send termination notification: {str(e)}")


def _send_reactivation_notification(member):
    """Send reactivation notification"""
    if not member.email:
        return

    try:
        # MIGRATED: Use unified EmailService instead of direct template calls
        from verenigingen.services.communication.compatibility import send_member_notification

        result = send_member_notification(
            member_name=member.name,
            notification_type="reactivation",
            context={"member_name": member.full_name, "membership_number": member.name},
        )

        if result.get("success"):
            frappe.logger("events").info(f"Reactivation notification sent successfully to {member.email}")
        else:
            frappe.logger("events").warning(
                f"Failed to send reactivation notification: {'; '.join(result.get('errors', []))}"
            )

    except Exception as e:
        frappe.logger("events").error(f"Failed to send reactivation notification: {str(e)}")


def _add_member_to_chapter_with_retry(chapter_doc, member_name, chapter_name):
    """
    Add a member to a chapter's members table with retry logic for concurrent modifications.

    Handles race conditions when multiple background jobs try to add members to the same
    chapter simultaneously by reloading the document and checking for duplicates on each retry.

    Args:
        chapter_doc: Initial chapter document (may be stale)
        member_name: Name of the member to add
        chapter_name: Name of the chapter (for reloading)
    """
    from verenigingen.utils.retry_utilities import retry_with_backoff

    @retry_with_backoff(
        max_retries=3,
        base_delay=0.5,
        max_delay=5.0,
    )
    def save_chapter_member():
        # Reload to get the latest version and avoid timestamp mismatch
        fresh_chapter = frappe.get_doc("Chapter", chapter_name)

        # Double-check if member was already added by another concurrent job
        member_exists = any(cm.member == member_name for cm in fresh_chapter.members or [])

        if not member_exists:
            fresh_chapter.append("members", {"member": member_name, "status": "Active"})
            fresh_chapter.save(ignore_permissions=True)
            frappe.logger("events").info(f"Assigned member {member_name} to chapter {chapter_name}")
        else:
            frappe.logger("events").info(
                f"Member {member_name} already in chapter {chapter_name} (added by concurrent job)"
            )

    save_chapter_member()


def _assign_member_to_chapter(member):
    """Assign approved member to appropriate chapter using centralized lookup"""
    # Get postal code from linked address
    postal_code = None
    if member.primary_address:
        address_doc = frappe.get_doc("Address", member.primary_address)
        postal_code = address_doc.pincode

    if not postal_code:
        return

    # Use centralized optimized chapter lookup
    from verenigingen.utils.optimized_chapter_lookup import get_lookup_instance

    lookup = get_lookup_instance()
    best_chapter = lookup.find_best_chapter_for_postal_code(postal_code)

    if best_chapter:
        # Verify chapter exists
        if not frappe.db.exists("Chapter", best_chapter):
            frappe.logger("events").warning(f"Chapter {best_chapter} not found for member {member.name}")
            return

        # Check if member is already in this chapter's members child table
        chapter_doc = frappe.get_doc("Chapter", best_chapter)

        # Check if member already exists in the chapter's members child table
        member_exists = False
        for cm in chapter_doc.members or []:
            if cm.member == member.name:
                member_exists = True
                break

        if not member_exists:
            # Add member to chapter's members child table with retry logic
            # to handle concurrent modifications during bulk processing
            try:
                _add_member_to_chapter_with_retry(chapter_doc, member.name, best_chapter)
            except Exception as e:
                # Log the error properly without triggering broken pipe
                frappe.logger("events").error(
                    f"Failed to assign member {member.name} to chapter {best_chapter} "
                    f"after retries: {str(e)}"
                )
                # Don't raise - this is a background job, failure shouldn't block member creation


def _update_chapter_membership_status(member, status):
    """Update status of all chapter memberships for this member"""
    chapter_members = frappe.get_all("Chapter Member", filters={"member": member.name}, fields=["name"])

    for cm in chapter_members:
        chapter_member = frappe.get_doc("Chapter Member", cm.name)
        chapter_member.status = status
        chapter_member.save()
