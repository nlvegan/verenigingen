"""
Member Event Subscribers

Background job handlers for member status and lifecycle change events.
These handle the actual business logic triggered by member status transitions.
"""

import time

import frappe
from frappe import _


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
        member_name = event_data.get("member")
        old_status = event_data.get("old_status")
        new_status = event_data.get("new_status")
        status_type = event_data.get("status_type")

        if not member_name:
            frappe.logger("events").warning("No member name in status change notification event")
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
        frappe.log_error(
            f"Failed to send status change notification: {str(e)}", "Member Status Notification Error"
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
        member_name = event_data.get("member")
        new_status = event_data.get("new_status")

        if not member_name:
            return

        member = frappe.get_doc("Member", member_name)

        # Update chapter assignments based on new status
        if new_status == "Approved":
            _assign_member_to_chapter(member)
        elif new_status in ["Suspended", "Terminated"]:
            _update_chapter_membership_status(member, new_status)

        frappe.logger("events").info(f"Updated chapter assignments for {member_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update chapter assignments: {str(e)}", "Chapter Assignment Update Error")


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
        new_status = event_data.get("new_status")

        if not member_name:
            return

        member = frappe.get_doc("Member", member_name)

        # Update user account based on member status
        if hasattr(member, "user") and member.user:
            user_doc = frappe.get_doc("User", member.user)

            if new_status in ["Suspended", "Terminated"]:
                user_doc.enabled = 0
                user_doc.save()
            elif new_status == "Active":
                user_doc.enabled = 1
                user_doc.save()

        frappe.logger("events").info(f"Updated user account for {member_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update user account: {str(e)}", "User Account Update Error")


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
        "company": frappe.defaults.get_global_default("company") or "Verenigingen",
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


def _assign_member_to_chapter(member):
    """Assign approved member to appropriate chapter"""
    # Get postal code from linked address
    postal_code = None
    if member.primary_address:
        address_doc = frappe.get_doc("Address", member.primary_address)
        postal_code = address_doc.pincode

    if not postal_code:
        return

    # Find appropriate chapter based on postal code
    chapters = frappe.get_all("Chapter", filters={"status": "Active"}, fields=["name", "postal_codes"])

    for chapter in chapters:
        if _postal_code_matches_chapter(postal_code, chapter.postal_codes):
            # Create or update chapter membership
            existing = frappe.db.exists("Chapter Member", {"member": member.name, "chapter": chapter.name})

            if not existing:
                chapter_member = frappe.get_doc(
                    {
                        "doctype": "Chapter Member",
                        "member": member.name,
                        "chapter": chapter.name,
                        "status": "Active",
                    }
                )
                chapter_member.insert()
            break


def _update_chapter_membership_status(member, status):
    """Update status of all chapter memberships for this member"""
    chapter_members = frappe.get_all("Chapter Member", filters={"member": member.name}, fields=["name"])

    for cm in chapter_members:
        chapter_member = frappe.get_doc("Chapter Member", cm.name)
        chapter_member.status = status
        chapter_member.save()


def _postal_code_matches_chapter(postal_code, postal_codes):
    """Check if postal code falls within chapter's ranges"""
    if not postal_codes:
        return False

    # Extract numeric part from Dutch postal code (e.g., "1234AB" -> 1234, "1234 AB" -> 1234)
    try:
        import re

        # Extract the first numeric part from the postal code
        numeric_match = re.match(r"(\d+)", postal_code.strip() if postal_code else "")
        postal_numeric = int(numeric_match.group(1)) if numeric_match else 0
    except (ValueError, AttributeError):
        return False

    for range_str in postal_codes.split(","):
        if "-" in range_str:
            start, end = range_str.strip().split("-")
            if int(start) <= postal_numeric <= int(end):
                return True
        else:
            if int(range_str.strip()) == postal_numeric:
                return True

    return False
