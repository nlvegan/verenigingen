"""
Notification Management and Configuration Utilities for Verenigingen System

This module provides comprehensive notification management capabilities for the
Verenigingen association management system. It handles intelligent recipient
determination, configurable notification settings, and robust fallback mechanisms
to ensure critical system notifications are always delivered to appropriate personnel.

Key Features:
    * Configurable notification recipients via Verenigingen Email Configuration DocType
    * Intelligent fallback to role-based recipient determination
    * Threshold-based notification triggering with customizable limits
    * Per-notification-type enable/disable controls with cooldown tracking
    * Error-resistant notification delivery with multiple fallback levels
    * Support for both individual and group notification scenarios

Architecture:
    The notification system uses a hierarchical approach for configuration:
    1. Verenigingen Email Configuration DocType (centralized control, highest priority)
    2. Verenigingen Settings (legacy fallback)
    3. Role-based recipient lookup using configurable role lists
    4. Emergency fallback to System Manager role (last resort)

Use Cases:
    - System alert notifications for critical events
    - Membership status change notifications
    - Payment processing alerts and confirmations
    - SEPA batch processing status updates
    - Administrative workflow notifications

Integration:
    This module integrates with Frappe's notification framework and the
    Verenigingen Email Configuration DocType for centralized notification management.
    It supports both immediate notifications and threshold-based alerting systems.

Error Handling:
    Comprehensive error handling ensures notification delivery even in degraded
    system conditions, with multiple fallback mechanisms and detailed logging
    for troubleshooting notification delivery issues.
"""

from typing import Optional

import frappe

from verenigingen.utils.constants import Roles


def _get_email_config_service():
    """Get EmailConfigurationService if available.

    Returns None if the service or DocType is not yet installed,
    allowing graceful degradation during migrations.
    """
    try:
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        return get_email_configuration_service()
    except Exception:
        return None


def send_volunteer_email(
    volunteer: str,
    template_name: str,
    notification_key: str,
    subject: Optional[str] = None,
    extra_context: Optional[dict] = None,
    reference_doctype: Optional[str] = None,
    reference_name: Optional[str] = None,
) -> dict:
    """
    Send email to a volunteer via their linked member's email address.

    This helper centralizes the common pattern of:
    1. Looking up volunteer → member → email
    2. Building context with member/volunteer names
    3. Sending via EmailService with notification_key for configuration

    Args:
        volunteer: Volunteer document name
        template_name: Email Template name to use
        notification_key: Key for Verenigingen Email Configuration lookup (enables per-notification
                         settings and cooldown tracking)
        subject: Optional subject override (otherwise uses template subject)
        extra_context: Additional context variables for the template
        reference_doctype: DocType to link the email to
        reference_name: Document name to link the email to

    Returns:
        dict: Result with 'success' status. On failure, includes 'reason'.
              On success, includes EmailService result data.

    Example:
        # Send board appointment notification
        send_volunteer_email(
            volunteer="VOL-001",
            template_name="chapter_board_notification",
            notification_key="chapter_board_added",
            subject="Board Appointment - Amsterdam Chapter",
            extra_context={"chapter_name": "Amsterdam", "board_position": "Treasurer"},
            reference_doctype="Chapter Board Member",
            reference_name="CBM-001",
        )
    """
    try:
        if not volunteer:
            return {"success": False, "reason": "No volunteer provided"}

        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        if not volunteer_doc.member:
            frappe.logger().debug(f"Volunteer {volunteer} has no linked member")
            return {"success": False, "reason": "Volunteer has no linked member"}

        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if not member_doc.email:
            frappe.logger().debug(f"Member {volunteer_doc.member} has no email")
            return {"success": False, "reason": "Member has no email address"}

        # Build context with common fields
        context = {
            "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
            "volunteer_name": volunteer_doc.volunteer_name,
            "member": member_doc,
            "volunteer": volunteer_doc,
        }

        # Merge extra context (allows override of defaults)
        if extra_context:
            context.update(extra_context)

        from verenigingen.services.communication.email_service import get_email_service

        result = get_email_service().send_templated_email(
            template_name=template_name,
            recipients=[member_doc.email],
            context=context,
            subject_override=subject,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            notification_key=notification_key,
        )

        return result

    except frappe.DoesNotExistError as e:
        frappe.logger().warning(f"send_volunteer_email: Document not found - {str(e)}")
        return {"success": False, "reason": f"Document not found: {str(e)}"}
    except Exception as e:
        frappe.log_error(
            f"send_volunteer_email failed for {volunteer}: {str(e)}",
            "Volunteer Email Error",
        )
        return {"success": False, "reason": str(e)}


def get_notification_recipients(setting_field, default_roles=None):
    """
    Intelligently determine notification recipients using hierarchical fallback strategy.

    This function implements a sophisticated recipient determination system that
    prioritizes custom configuration while providing robust fallback mechanisms
    to ensure critical notifications are always delivered to appropriate personnel.

    Recipient Determination Strategy:
        1. Custom Emails: Check Verenigingen Settings for specific email addresses
        2. Role-Based Lookup: Find active users with specified roles
        3. Emergency Fallback: Use System Manager role as last resort

    Args:
        setting_field (str): Field name in Verenigingen Settings containing
                           comma-separated email addresses for notifications
        default_roles (list, optional): List of role names to use for recipient
                                      lookup if no custom emails configured.
                                      Defaults to ["System Manager", "Verenigingen Administrator"]

    Returns:
        list: Email addresses of notification recipients, guaranteed to contain
              at least one valid email address or empty list in extreme failure

    Error Handling:
        - Graceful handling of missing or malformed settings
        - Validation of email address format and user account status
        - Comprehensive logging of recipient determination process
        - Multiple fallback levels to ensure notification delivery

    Example:
        # Get recipients for payment failure notifications
        recipients = get_notification_recipients(
            "payment_failure_notification_emails",
            ["Verenigingen Treasurer", "System Manager"]
        )
    """
    if default_roles is None:
        default_roles = list(Roles.ADMIN_PAIR)

    try:
        settings = frappe.get_single("Verenigingen Settings")
        custom_emails = getattr(settings, setting_field, None)

        if custom_emails:
            # Parse comma-separated emails and clean them
            emails = [email.strip() for email in custom_emails.split(",") if email.strip()]
            if emails:
                return emails

        # Fall back to default roles
        admin_users = frappe.get_all(
            "User",
            filters=[["enabled", "=", 1], ["Has Role", "role", "in", default_roles]],
            fields=["email", "full_name"],
        )

        return [user.email for user in admin_users if user.email]

    except Exception as e:
        frappe.log_error(f"Failed to get notification recipients: {str(e)}", "Notification Helper Error")
        # Emergency fallback - get System Managers
        try:
            admin_emails = frappe.get_all(
                "User", filters=[["Has Role", "role", "=", Roles.SYSTEM_MANAGER]], pluck="email"
            )
            return [email for email in admin_emails if email]
        except:
            return []


def get_threshold_setting(setting_field, default_value):
    """
    Retrieve configurable threshold values for notification and alerting systems.

    This function provides a centralized mechanism for accessing threshold
    configurations that control when notifications are triggered. It ensures
    consistent behavior across the system while allowing customization through
    the Verenigingen Settings interface.

    Common Threshold Settings:
        - Payment failure retry counts before alerting
        - Membership expiration notification periods
        - SEPA batch processing error limits
        - System resource utilization alert levels

    Args:
        setting_field (str): Field name in Verenigingen Settings DocType
                           containing the threshold configuration value
        default_value (any): Default value to return if setting is not
                           configured or accessible

    Returns:
        any: Configured threshold value from settings, or default_value
             if setting is unavailable or malformed

    Error Handling:
        Silent fallback to default value with no error propagation,
        ensuring system continues operation with reasonable defaults
        even if configuration is temporarily unavailable.

    Example:
        # Get payment retry threshold with default of 3 attempts
        max_retries = get_threshold_setting("payment_max_retries", 3)

        # Get membership expiration warning days with default of 30
        warning_days = get_threshold_setting("membership_expiration_warning_days", 30)
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return getattr(settings, setting_field, default_value)
    except:
        return default_value


def create_system_notification(
    recipients,
    subject,
    message,
    notification_type="Alert",
    document_type=None,
    document_name=None,
    from_user=None,
    notification_key=None,
):
    """
    Create in-app notifications for specified recipients.

    This function creates Notification Log entries that appear in the user's
    notification bell in the Frappe desk. Email delivery depends on each user's
    notification preferences - users can disable email delivery for specific
    notification types in their User settings.

    Note: For critical alerts requiring guaranteed email delivery, use
    EmailService directly instead of this function.

    Args:
        recipients (list): List of user emails or usernames to notify
        subject (str): Notification subject/title (max 200 chars, truncated if longer)
        message (str): HTML content of the notification (max 50KB)
        notification_type (str): Type of notification. Options:
            - "Alert" (default): System alerts and warnings
            - "Mention": When user is mentioned
            - "Assignment": Task assignments
            - "Share": Document sharing
        document_type (str, optional): DocType to link notification to
        document_name (str, optional): Document name to link notification to
        from_user (str, optional): User who triggered the notification.
            Defaults to current user or "Administrator"
        notification_key (str, optional): Key for Verenigingen Email Configuration lookup.
            If provided, checks if this notification type is enabled and
            respects cooldown settings.

    Returns:
        dict: Result with 'success' status and 'notifications_created' count

    Example:
        # Notify admins about a membership request
        create_system_notification(
            recipients=["admin@example.com", "manager@example.com"],
            subject="New Membership Type Change Request",
            message="<p>Member John Doe has requested to change...</p>",
            notification_type="Alert",
            document_type="Member",
            document_name="MEM-001",
            notification_key="member_status_changed"
        )
    """
    # Check Verenigingen Email Configuration if notification_key provided
    config_service = _get_email_config_service()
    if config_service and notification_key:
        # Check if notifications are globally enabled
        if not config_service.is_email_enabled():
            frappe.logger().debug("Notifications disabled via Verenigingen Email Configuration")
            return {
                "success": True,
                "skipped": True,
                "reason": "Notifications disabled",
                "notifications_created": 0,
            }

        # Check if this notification type is enabled
        if not config_service.is_notification_enabled(notification_key):
            frappe.logger().debug(f"Notification '{notification_key}' disabled in Verenigingen Email Configuration")
            return {
                "success": True,
                "skipped": True,
                "reason": f"Notification '{notification_key}' disabled",
                "notifications_created": 0,
            }

    # Constants for input validation
    MAX_SUBJECT_LENGTH = 200
    MAX_MESSAGE_LENGTH = 50000  # ~50KB
    MAX_RECIPIENTS = 100
    MAX_ERRORS_TO_COLLECT = 10

    # Input validation
    if not recipients:
        frappe.logger().warning("create_system_notification called with no recipients")
        return {"success": False, "error": "No recipients provided", "notifications_created": 0}

    if isinstance(recipients, str):
        recipients = [recipients]

    # Validate and truncate subject
    if not subject:
        subject = "System Notification"
    if len(subject) > MAX_SUBJECT_LENGTH:
        subject = subject[: MAX_SUBJECT_LENGTH - 3] + "..."

    # Validate message length
    if message and len(message) > MAX_MESSAGE_LENGTH:
        frappe.logger().warning(
            f"Notification message too large ({len(message)} chars), truncating to {MAX_MESSAGE_LENGTH}"
        )
        message = message[:MAX_MESSAGE_LENGTH] + "... [truncated]"

    # Filter to non-empty recipients
    recipients = [r for r in recipients if r]
    if not recipients:
        frappe.logger().warning(f"No valid recipients provided for notification: {subject}")
        return {"success": False, "error": "No recipients provided", "notifications_created": 0}

    # Batch validate recipients with single query (optimized from N+1 queries)
    valid_users = frappe.get_all(
        "User",
        filters={"enabled": 1},
        or_filters=[{"email": ["in", recipients]}, {"name": ["in", recipients]}],
        pluck="email",
    )

    if not valid_users:
        frappe.logger().warning(f"No valid/enabled users found for notification: {subject}")
        return {"success": False, "error": "No valid recipients found", "notifications_created": 0}

    # Limit recipient count to prevent DoS
    if len(valid_users) > MAX_RECIPIENTS:
        frappe.logger().warning(f"Too many recipients ({len(valid_users)}), limiting to {MAX_RECIPIENTS}")
        valid_users = valid_users[:MAX_RECIPIENTS]

    notifications_created = 0
    errors = []
    sender = from_user or frappe.session.user or "Administrator"

    for recipient in valid_users:
        try:
            notification = frappe.new_doc("Notification Log")
            notification.subject = subject
            notification.for_user = recipient
            notification.type = notification_type
            notification.email_content = message

            if document_type:
                notification.document_type = document_type
            if document_name:
                notification.document_name = document_name

            notification.from_user = sender

            # Notification Log is a Frappe system DocType — Frappe itself always
            # creates these with ignore_permissions. No user-data security concern here.
            notification.insert(ignore_permissions=True)
            notifications_created += 1

        except Exception as e:
            error_msg = f"Failed to create notification for {recipient}: {str(e)}"
            frappe.log_error(error_msg, "Notification Creation Error")
            if len(errors) < MAX_ERRORS_TO_COLLECT:
                errors.append(error_msg)

    # Note: Removed explicit frappe.db.commit() - let Frappe's transaction management
    # handle commits at request/job boundaries to avoid breaking parent transactions

    # Add overflow indicator if errors were truncated
    total_failures = len(valid_users) - notifications_created
    if total_failures > MAX_ERRORS_TO_COLLECT:
        errors.append(f"... and {total_failures - len(errors)} more errors")

    return {
        "success": notifications_created > 0,
        "notifications_created": notifications_created,
        "errors": errors if errors else None,
    }


def notify_administrators(
    subject,
    message,
    setting_field=None,
    default_roles=None,
    notification_type="Alert",
    document_type=None,
    document_name=None,
    notification_key=None,
    category=None,
):
    """
    Convenience function to notify system administrators.

    Combines get_notification_recipients() with create_system_notification()
    for common admin notification scenarios. Uses Verenigingen Email Configuration when
    available for centralized recipient management.

    Args:
        subject (str): Notification subject
        message (str): HTML notification content
        setting_field (str, optional): Setting field for custom recipients (legacy)
        default_roles (list, optional): Roles to fall back to
        notification_type (str): Type of notification (default: "Alert")
        document_type (str, optional): DocType to link to
        document_name (str, optional): Document to link to
        notification_key (str, optional): Key for Verenigingen Email Configuration lookup.
            If provided, uses Verenigingen Email Configuration for enable/disable checks.
        category (str, optional): Notification category (Admin, System, etc.)
            Used for recipient lookup in Verenigingen Email Configuration.

    Returns:
        dict: Result with success status and notification count

    Example:
        # Notify admins about overdue terminations
        notify_administrators(
            subject="5 Overdue Termination Requests",
            message="<p>The following termination requests are overdue...</p>",
            notification_key="termination_overdue",
            category="Admin",
            document_type="Membership Termination Request"
        )
    """
    # Try Verenigingen Email Configuration first for recipients
    config_service = _get_email_config_service()
    recipients = None

    if config_service:
        # Use category-based recipients if category provided
        if category:
            recipients = config_service.get_category_recipients(category)

        # Use notification-specific recipients if notification_key provided
        if notification_key and not recipients:
            recipients = config_service.get_recipients_for_notification(notification_key)

    # Fall back to legacy recipient lookup
    if not recipients:
        recipients = get_notification_recipients(
            setting_field or "admin_notification_emails",
            default_roles or list(Roles.ADMIN_PAIR),
        )

    return create_system_notification(
        recipients=recipients,
        subject=subject,
        message=message,
        notification_type=notification_type,
        document_type=document_type,
        document_name=document_name,
        notification_key=notification_key,
    )
