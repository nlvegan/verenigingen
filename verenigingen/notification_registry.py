"""
Notification Registry - Central source of truth for all notification keys.

This module defines all notification keys used throughout the application,
along with their metadata (category, description, default settings).

Usage:
    from verenigingen.notification_registry import NOTIFICATION_KEYS, get_notification_meta

    # Get metadata for a key
    meta = get_notification_meta("member_activated")

    # Use in email service calls
    email_service.send_templated_email(
        template_name="member_activated",
        notification_key="member_activated",
        ...
    )

Adding new notification keys:
    1. Add the key to NOTIFICATION_KEYS below with all required fields
    2. Use the key in your code with notification_key="your_key"
    3. Run "Sync Registry" in Email Configuration to add it to the database
"""

# Category constants for consistency
CATEGORY_MEMBER = "Member"
CATEGORY_PAYMENT = "Payment"
CATEGORY_CHAPTER = "Chapter"
CATEGORY_VOLUNTEER = "Volunteer"
CATEGORY_ADMIN = "Admin"
CATEGORY_SYSTEM = "System"

# Priority constants
PRIORITY_LOW = "Low"
PRIORITY_MEDIUM = "Medium"
PRIORITY_HIGH = "High"
PRIORITY_CRITICAL = "Critical"

# Recipient policy constants
POLICY_DOCUMENT_FIELD = "Document-Field"
POLICY_ROLE_BASED = "Role-Based"
POLICY_FIXED = "Fixed"
POLICY_CUSTOM = "Custom"


NOTIFICATION_KEYS = {
    # =========================================================================
    # MEMBER NOTIFICATIONS
    # =========================================================================
    "member_activated": {
        "label": "Member Activated",
        "category": CATEGORY_MEMBER,
        "description": "Sent when a member's status changes to Active after approval or reactivation.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "member_suspended": {
        "label": "Member Suspended",
        "category": CATEGORY_MEMBER,
        "description": "Sent when a member's status changes to Suspended due to payment issues or policy violations.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "member_terminated": {
        "label": "Member Terminated",
        "category": CATEGORY_MEMBER,
        "description": "Sent when a membership is terminated, either by request or administrative action.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "member_status_change": {
        "label": "Member Status Change",
        "category": CATEGORY_MEMBER,
        "description": "Generic notification for any member status transition not covered by specific notifications.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "member_status_changed": {
        "label": "Member Status Changed (Admin)",
        "category": CATEGORY_ADMIN,
        "description": "Admin notification when a member's status changes, for audit and tracking purposes.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "member_application_confirmation": {
        "label": "Application Confirmation",
        "category": CATEGORY_MEMBER,
        "description": "Sent to applicants confirming receipt of their membership application.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "member_application_rejected": {
        "label": "Application Rejected",
        "category": CATEGORY_MEMBER,
        "description": "Sent when a membership application is rejected, including the reason.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "membership_renewal_reminder": {
        "label": "Renewal Reminder",
        "category": CATEGORY_MEMBER,
        "description": "Periodic reminder sent to members whose membership is approaching expiration.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "termination_overdue": {
        "label": "Termination Overdue",
        "category": CATEGORY_ADMIN,
        "description": "Admin alert when a termination request has not been processed within the expected timeframe.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "termination_pending_approval": {
        "label": "Termination Pending Approval",
        "category": CATEGORY_ADMIN,
        "description": "Sent to designated approver when a termination request requires secondary approval (disciplinary cases).",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "termination_approved": {
        "label": "Termination Request Approved",
        "category": CATEGORY_MEMBER,
        "description": "Sent to requester when their termination request is approved.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "termination_rejected": {
        "label": "Termination Request Rejected",
        "category": CATEGORY_MEMBER,
        "description": "Sent to requester when their termination request is rejected, including the reason.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    # =========================================================================
    # CHAPTER NOTIFICATIONS
    # =========================================================================
    "chapter_member_joined": {
        "label": "Chapter Member Joined",
        "category": CATEGORY_CHAPTER,
        "description": "Sent when a member joins a chapter, notifying chapter leadership.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "chapter_member_left": {
        "label": "Chapter Member Left",
        "category": CATEGORY_CHAPTER,
        "description": "Sent when a member leaves a chapter, notifying chapter leadership.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "chapter_board_added": {
        "label": "Board Member Added",
        "category": CATEGORY_CHAPTER,
        "description": "Sent when someone is appointed to a chapter board position.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "chapter_board_removed": {
        "label": "Board Member Removed",
        "category": CATEGORY_CHAPTER,
        "description": "Sent when someone is removed from a chapter board position.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "chapter_board_role_changed": {
        "label": "Board Role Changed",
        "category": CATEGORY_CHAPTER,
        "description": "Sent when a chapter board member's role or responsibilities change.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "chapter_settings_changed": {
        "label": "Chapter Settings Changed",
        "category": CATEGORY_CHAPTER,
        "description": "Sent to chapter leadership when chapter configuration or settings are modified.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    # =========================================================================
    # PAYMENT NOTIFICATIONS
    # =========================================================================
    "payment_success": {
        "label": "Payment Successful",
        "category": CATEGORY_PAYMENT,
        "description": "Confirmation sent when a payment is successfully processed.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "payment_failure_final": {
        "label": "Payment Failed (Final)",
        "category": CATEGORY_PAYMENT,
        "description": "Sent after all retry attempts have failed for a payment.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "payment_reminder_urgent": {
        "label": "Payment Reminder (Urgent)",
        "category": CATEGORY_PAYMENT,
        "description": "Urgent reminder for overdue payments requiring immediate attention.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "payment_plan_request": {
        "label": "Payment Plan Requested",
        "category": CATEGORY_PAYMENT,
        "description": "Admin notification when a member requests a payment plan arrangement.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "payment_plan_approved": {
        "label": "Payment Plan Approved",
        "category": CATEGORY_PAYMENT,
        "description": "Sent to member when their payment plan request is approved.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "payment_history_failure_alert": {
        "label": "Payment History Sync Failed",
        "category": CATEGORY_PAYMENT,
        "description": "System alert when payment history synchronization encounters errors.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "payment_history_critical_error": {
        "label": "Payment History Critical Error",
        "category": CATEGORY_PAYMENT,
        "description": "Critical system alert for severe payment history processing failures.",
        "priority": PRIORITY_CRITICAL,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    # =========================================================================
    # DONATION NOTIFICATIONS
    # =========================================================================
    "donation_confirmation": {
        "label": "Donation Confirmation",
        "category": CATEGORY_PAYMENT,
        "description": "Thank-you confirmation sent to donors after a donation is received.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "donation_payment_confirmation": {
        "label": "Donation Payment Confirmed",
        "category": CATEGORY_PAYMENT,
        "description": "Sent when payment for a donation pledge is successfully processed.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "periodic_donation_confirmation": {
        "label": "Recurring Donation Started",
        "category": CATEGORY_PAYMENT,
        "description": "Confirmation sent when a recurring donation agreement is set up.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "periodic_donation_expiry": {
        "label": "Recurring Donation Expiring",
        "category": CATEGORY_PAYMENT,
        "description": "Reminder sent before a recurring donation agreement expires.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "periodic_donation_cancellation": {
        "label": "Recurring Donation Cancelled",
        "category": CATEGORY_PAYMENT,
        "description": "Confirmation sent when a recurring donation agreement is cancelled.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    # =========================================================================
    # DUES & BILLING NOTIFICATIONS
    # =========================================================================
    "dues_schedule_auto_creation_summary": {
        "label": "Dues Schedule Auto-Creation Summary",
        "category": CATEGORY_PAYMENT,
        "description": "Admin summary of automatically created dues schedules from scheduled job.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "dues_schedule_manual_creation": {
        "label": "Dues Schedule Created",
        "category": CATEGORY_PAYMENT,
        "description": "Notification when a dues schedule is manually created for a member.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "dues_amendment_approved": {
        "label": "Contribution Amendment Approved",
        "category": CATEGORY_PAYMENT,
        "description": "Sent when a request to change contribution amount is approved.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "dues_amendment_rejected": {
        "label": "Contribution Amendment Rejected",
        "category": CATEGORY_PAYMENT,
        "description": "Sent when a request to change contribution amount is rejected.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    # =========================================================================
    # SEPA NOTIFICATIONS
    # =========================================================================
    "sepa_batch_success": {
        "label": "SEPA Batch Successful",
        "category": CATEGORY_PAYMENT,
        "description": "Admin notification when a SEPA direct debit batch is successfully processed.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "sepa_batch_warning": {
        "label": "SEPA Batch Warning",
        "category": CATEGORY_PAYMENT,
        "description": "Admin alert when a SEPA batch completes with warnings or partial failures.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "sepa_batch_error": {
        "label": "SEPA Batch Error",
        "category": CATEGORY_PAYMENT,
        "description": "Admin alert when a SEPA direct debit batch fails processing.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    # =========================================================================
    # PONTO NOTIFICATIONS
    # =========================================================================
    "ponto_payment_link_request": {
        "label": "Ponto Payment Link",
        "category": CATEGORY_PAYMENT,
        "description": "Sent to member with a Ponto payment link for manual payment.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    # =========================================================================
    # VOLUNTEER NOTIFICATIONS
    # =========================================================================
    "team_member_added": {
        "label": "Added to Team",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent when a volunteer is added to a team.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "team_member_removed": {
        "label": "Removed from Team",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent when a volunteer is removed from a team.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "team_role_changed": {
        "label": "Team Role Changed",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent when a volunteer's role within a team changes.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "team_settings_changed": {
        "label": "Team Settings Changed",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent to team leadership when team configuration is modified.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "team_leadership_changed": {
        "label": "Team Leadership Changed",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent when team leadership (coordinator, lead) changes.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "expense_approval_request": {
        "label": "Expense Approval Request",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent to approvers when a volunteer submits an expense claim.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "expense_approved": {
        "label": "Expense Approved",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent to volunteer when their expense claim is approved.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    "expense_rejected": {
        "label": "Expense Rejected",
        "category": CATEGORY_VOLUNTEER,
        "description": "Sent to volunteer when their expense claim is rejected.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
    # =========================================================================
    # SYSTEM NOTIFICATIONS
    # =========================================================================
    "system_stuck_schedules": {
        "label": "Stuck Schedules Alert",
        "category": CATEGORY_SYSTEM,
        "description": "System alert when dues schedules are stuck in processing state.",
        "priority": PRIORITY_HIGH,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "analytics_alert": {
        "label": "Analytics Alert",
        "category": CATEGORY_SYSTEM,
        "description": "Triggered alert based on analytics rule thresholds being exceeded.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_CUSTOM,
    },
    "security_policy_digest": {
        "label": "Security Policy Digest",
        "category": CATEGORY_SYSTEM,
        "description": "Periodic summary of security policy violations and critical operations.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    # =========================================================================
    # ADMIN NOTIFICATIONS
    # =========================================================================
    "anbi_consent_request": {
        "label": "ANBI Consent Request",
        "category": CATEGORY_ADMIN,
        "description": "Sent to donors requesting consent for ANBI tax deduction reporting.",
        "priority": PRIORITY_MEDIUM,
        "recipient_policy": POLICY_DOCUMENT_FIELD,
    },
}


def get_notification_meta(notification_key: str) -> dict:
    """Get metadata for a notification key.

    Args:
        notification_key: The notification key to look up.

    Returns:
        Dict with label, category, description, priority, recipient_policy.
        Returns empty dict if key not found.
    """
    return NOTIFICATION_KEYS.get(notification_key, {})


def get_all_keys() -> list:
    """Get list of all registered notification keys.

    Returns:
        Sorted list of notification key strings.
    """
    return sorted(NOTIFICATION_KEYS.keys())


def get_keys_by_category(category: str) -> list:
    """Get notification keys filtered by category.

    Args:
        category: Category to filter by (Member, Payment, Chapter, etc.)

    Returns:
        List of notification keys in that category.
    """
    return [key for key, meta in NOTIFICATION_KEYS.items() if meta.get("category") == category]


def validate_notification_key(notification_key: str) -> bool:
    """Check if a notification key is registered.

    Args:
        notification_key: The key to validate.

    Returns:
        True if registered, False otherwise.
    """
    return notification_key in NOTIFICATION_KEYS
