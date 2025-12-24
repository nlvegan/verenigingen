"""
Migrate email settings from Verenigingen Settings to Email Configuration.

This patch:
1. Creates the Email Configuration singleton if it doesn't exist
2. Migrates relevant settings from Verenigingen Settings
3. Populates the notification registry with all known notification types
"""

import frappe


def execute():
    """Execute the migration patch."""
    # Check if Email Configuration DocType exists
    if not frappe.db.exists("DocType", "Email Configuration"):
        frappe.logger().info("Email Configuration DocType not found, skipping migration")
        return

    # Check if already migrated
    if frappe.db.exists("Email Configuration", "Email Configuration"):
        existing = frappe.get_single("Email Configuration")
        if existing.notification_types and len(existing.notification_types) > 0:
            frappe.logger().info("Email Configuration already has notification types, skipping")
            return

    frappe.logger().info("Starting email settings migration to Email Configuration")

    # Get list of existing email templates
    existing_templates = set(frappe.get_all("Email Template", pluck="name"))

    # Get existing settings from Verenigingen Settings
    old_settings = {}
    if frappe.db.exists("DocType", "Verenigingen Settings"):
        try:
            vs = frappe.get_single("Verenigingen Settings")
            old_settings = {
                "financial_admin_emails": getattr(vs, "financial_admin_emails", None),
                "stuck_schedule_notification_emails": getattr(vs, "stuck_schedule_notification_emails", None),
                "send_chapter_assignment_notifications": getattr(
                    vs, "send_chapter_assignment_notifications", False
                ),
                "send_termination_notifications": getattr(vs, "send_termination_notifications", False),
            }
        except Exception as e:
            frappe.logger().warning(f"Could not read Verenigingen Settings: {e}")

    # Create or update Email Configuration
    if frappe.db.exists("Email Configuration", "Email Configuration"):
        config = frappe.get_single("Email Configuration")
    else:
        config = frappe.new_doc("Email Configuration")

    # Migrate settings
    config.master_email_enabled = 1
    config.email_mode = "Active"

    if old_settings.get("financial_admin_emails"):
        config.financial_admin_emails = old_settings["financial_admin_emails"]

    if old_settings.get("stuck_schedule_notification_emails"):
        config.system_alert_emails = old_settings["stuck_schedule_notification_emails"]

    # Populate notification registry
    notification_types = _get_default_notification_types(old_settings, existing_templates)

    config.notification_types = []
    for nt in notification_types:
        # Remove email_template if template doesn't exist
        template = nt.get("email_template")
        if template and template not in existing_templates:
            nt.pop("email_template", None)
        config.append("notification_types", nt)

    config.flags.ignore_permissions = True
    config.flags.ignore_links = True  # Skip link validation during migration
    config.save()

    frappe.db.commit()
    frappe.logger().info(f"Email Configuration created with {len(notification_types)} notification types")


def _get_default_notification_types(old_settings: dict, existing_templates: set) -> list:
    """Get the default notification types to populate.

    Args:
        old_settings: Dictionary of old settings for determining initial enabled state.
        existing_templates: Set of existing Email Template names.

    Returns:
        List of notification type dictionaries.
    """
    chapter_enabled = old_settings.get("send_chapter_assignment_notifications", True)
    termination_enabled = old_settings.get("send_termination_notifications", True)

    def safe_template(template_name):
        """Return template name only if it exists, else None."""
        return template_name if template_name in existing_templates else None

    return [
        # Member Notifications
        {
            "notification_key": "member_application_confirmation",
            "label": "Application Confirmation",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "membership_application_confirmation",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Confirmation email sent when member submits application",
        },
        {
            "notification_key": "member_application_approved",
            "label": "Application Approved",
            "category": "Member",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 0,
            "email_template": "membership_application_approved",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when membership application is approved",
        },
        {
            "notification_key": "member_application_rejected",
            "label": "Application Rejected",
            "category": "Member",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 0,
            "email_template": "membership_application_rejected",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when membership application is rejected",
        },
        {
            "notification_key": "member_status_changed",
            "label": "Status Changed",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "member_lifecycle_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when member status changes",
        },
        {
            "notification_key": "member_welcome",
            "label": "Welcome Email",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 0,
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Welcome email sent to new active members",
        },
        # Chapter Notifications
        {
            "notification_key": "chapter_assignment",
            "label": "Chapter Assignment",
            "category": "Chapter",
            "enabled": 1 if chapter_enabled else 0,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "chapter_membership_approved",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Email sent when member is assigned to a chapter",
        },
        {
            "notification_key": "chapter_board_added",
            "label": "Board Member Added",
            "category": "Chapter",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "chapter_board_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "volunteer.email",
            "description": "Email sent when volunteer is added to chapter board",
        },
        {
            "notification_key": "chapter_board_removed",
            "label": "Board Member Removed",
            "category": "Chapter",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "chapter_board_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "volunteer.email",
            "description": "Email sent when volunteer is removed from chapter board",
        },
        # Payment Notifications
        {
            "notification_key": "payment_success",
            "label": "Payment Successful",
            "category": "Payment",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "payment_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Confirmation email when payment is processed successfully",
        },
        {
            "notification_key": "payment_failure_first",
            "label": "First Payment Failure",
            "category": "Payment",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 1440,  # 24 hours
            "email_template": "payment_failure_first",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "First notification when payment fails",
        },
        {
            "notification_key": "payment_failure_second",
            "label": "Second Payment Failure",
            "category": "Payment",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 1440,
            "email_template": "payment_failure_second",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Second notification for repeated payment failure",
        },
        {
            "notification_key": "payment_failure_final",
            "label": "Final Payment Failure",
            "category": "Payment",
            "enabled": 1,
            "priority": "Critical",
            "cooldown_minutes": 0,
            "email_template": "payment_failure_final",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Final warning before subscription cancellation",
        },
        {
            "notification_key": "payment_reminder_friendly",
            "label": "Payment Reminder",
            "category": "Payment",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 10080,  # 7 days
            "email_template": "payment_reminder_friendly",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Friendly reminder about upcoming payment",
        },
        {
            "notification_key": "payment_reminder_urgent",
            "label": "Urgent Payment Reminder",
            "category": "Payment",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 4320,  # 3 days
            "email_template": "payment_reminder_urgent",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Urgent reminder for overdue payment",
        },
        {
            "notification_key": "subscription_cancelled",
            "label": "Subscription Cancelled",
            "category": "Payment",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 0,
            "email_template": "subscription_cancelled",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Notification when subscription is cancelled",
        },
        # SEPA Notifications
        {
            "notification_key": "sepa_batch_success",
            "label": "SEPA Batch Success",
            "category": "Admin",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "recipient_policy": "Fixed",
            "description": "Admin notification when SEPA batch processes successfully",
        },
        {
            "notification_key": "sepa_batch_warning",
            "label": "SEPA Batch Warning",
            "category": "Admin",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 30,
            "recipient_policy": "Fixed",
            "description": "Admin notification when SEPA batch has warnings",
        },
        {
            "notification_key": "sepa_batch_error",
            "label": "SEPA Batch Error",
            "category": "Admin",
            "enabled": 1,
            "priority": "Critical",
            "cooldown_minutes": 0,
            "recipient_policy": "Fixed",
            "description": "Admin notification when SEPA batch fails",
        },
        {
            "notification_key": "sepa_mandate_created",
            "label": "Mandate Created",
            "category": "Payment",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "sepa_mandate_created",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Confirmation when SEPA mandate is created",
        },
        {
            "notification_key": "sepa_mandate_expiring",
            "label": "Mandate Expiring",
            "category": "Payment",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 10080,
            "email_template": "sepa_mandate_expiring",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Warning when SEPA mandate is about to expire",
        },
        # Volunteer Notifications
        {
            "notification_key": "expense_approval_request",
            "label": "Expense Approval Request",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "expense_approval_request",
            "recipient_policy": "Role-Based",
            "recipient_roles": "Expense Approver, Verenigingen Administrator",
            "description": "Request for expense approval sent to approvers",
        },
        {
            "notification_key": "expense_approved",
            "label": "Expense Approved",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 0,
            "email_template": "expense_approved",
            "recipient_policy": "Document-Field",
            "recipient_field": "owner",
            "description": "Confirmation when expense is approved",
        },
        {
            "notification_key": "expense_rejected",
            "label": "Expense Rejected",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 0,
            "email_template": "expense_rejected",
            "recipient_policy": "Document-Field",
            "recipient_field": "owner",
            "description": "Notification when expense is rejected",
        },
        {
            "notification_key": "team_assignment",
            "label": "Team Assignment",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "team_role_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "volunteer.email",
            "description": "Notification when volunteer is assigned to a team",
        },
        # Donation Notifications
        {
            "notification_key": "donation_confirmation",
            "label": "Donation Confirmation",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "donation_confirmation",
            "recipient_policy": "Document-Field",
            "recipient_field": "donor_email",
            "description": "Thank you email when donation is received",
        },
        {
            "notification_key": "donation_payment_confirmation",
            "label": "Donation Payment Confirmed",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "donation_payment_confirmation",
            "recipient_policy": "Document-Field",
            "recipient_field": "donor_email",
            "description": "Confirmation when donation payment is processed",
        },
        {
            "notification_key": "periodic_agreement_confirmation",
            "label": "Periodic Agreement Setup",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 0,
            "email_template": "periodic_agreement_confirmation",
            "recipient_policy": "Document-Field",
            "recipient_field": "donor_email",
            "description": "Confirmation when periodic donation agreement is created",
        },
        {
            "notification_key": "anbi_consent_request",
            "label": "ANBI Consent Request",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 43200,  # 30 days
            "email_template": "anbi_consent_request",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Request for ANBI tax deduction consent",
        },
        # System/Admin Notifications
        {
            "notification_key": "system_stuck_schedules",
            "label": "Stuck Dues Schedules",
            "category": "System",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 240,  # 4 hours
            "email_template": "stuck_dues_schedules_alert",
            "recipient_policy": "Fixed",
            "description": "Alert when dues schedules are stuck in processing",
        },
        {
            "notification_key": "system_security_alert",
            "label": "Security Alert",
            "category": "System",
            "enabled": 1,
            "priority": "Critical",
            "cooldown_minutes": 0,
            "recipient_policy": "Role-Based",
            "recipient_roles": "System Manager",
            "description": "Alert for security-related events",
        },
        {
            "notification_key": "csv_import_complete",
            "label": "CSV Import Complete",
            "category": "System",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 0,
            "recipient_policy": "Document-Field",
            "recipient_field": "owner",
            "description": "Notification when CSV import completes successfully",
        },
        {
            "notification_key": "csv_import_failed",
            "label": "CSV Import Failed",
            "category": "System",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 0,
            "recipient_policy": "Document-Field",
            "recipient_field": "owner",
            "description": "Notification when CSV import fails",
        },
        {
            "notification_key": "termination_overdue",
            "label": "Overdue Terminations",
            "category": "Admin",
            "enabled": 1 if termination_enabled else 0,
            "priority": "High",
            "cooldown_minutes": 1440,
            "email_template": "termination_overdue_notification",
            "recipient_policy": "Role-Based",
            "recipient_roles": "Verenigingen Administrator, System Manager",
            "description": "Alert for overdue termination requests requiring action",
        },
    ]
