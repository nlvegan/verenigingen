# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Scheduled task to auto-create missing dues schedules for members with assigned membership types
"""

import frappe
from frappe.utils import add_days, add_months, add_years, getdate, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.settings_utils import get_payments_settings


def _calculate_next_invoice_date(billing_frequency):
    """Calculate next invoice date based on billing frequency"""
    if billing_frequency == "Daily":
        return add_days(today(), 1)
    elif billing_frequency == "Weekly":
        return add_days(today(), 7)
    elif billing_frequency == "Monthly":
        return add_months(today(), 1)
    elif billing_frequency == "Quarterly":
        return add_months(today(), 3)
    elif billing_frequency == "Semi-Annual":
        return add_months(today(), 6)
    elif billing_frequency == "Annual":
        return add_years(today(), 1)
    else:
        # Default to monthly for other frequencies
        return add_months(today(), 1)


def _get_template_dues_rate(template):
    """Get dues rate from template with fallback logic"""
    if template.suggested_amount:
        return template.suggested_amount
    elif hasattr(template, "dues_rate") and template.dues_rate:
        return template.dues_rate
    else:
        raise ValueError(
            f"Template '{template.name}' must have either suggested_amount or dues_rate configured"
        )


def _validate_final_dues_rate(template_dues_rate, membership_type_doc):
    """Validate final dues rate with proper fallback"""
    if template_dues_rate and template_dues_rate > 0:
        return template_dues_rate

    # Fallback to membership type minimum_amount if template rate is not available
    minimum_amount = getattr(membership_type_doc, "minimum_amount", 0)
    if minimum_amount and minimum_amount > 0:
        return minimum_amount

    # If no valid rate found, raise error
    raise ValueError(
        f"No valid dues rate found for membership type '{membership_type_doc.name}'. "
        f"Template must have suggested_amount or membership type must have minimum_amount."
    )


def _get_validated_dues_rate(member):
    """Get validated dues rate for a member - for preview mode only"""
    try:
        # Get membership details
        membership = frappe.db.get_value(
            "Membership",
            {"member": member.member_name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        if not membership:
            return 0

        membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)

        # Get template dues rate
        template_dues_rate = 0
        if membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                template_dues_rate = _get_template_dues_rate(template)
            except Exception:
                pass

        # Validate and return rate
        return _validate_final_dues_rate(template_dues_rate, membership_type_doc)

    except Exception:
        # Return 0 for preview if validation fails
        return 0


def auto_create_missing_dues_schedules_scheduled():
    """
    Scheduled task version - Auto-create missing dues schedules for members who have:
    1. An active membership with a membership type
    2. No active dues schedule

    This scheduled task ensures billing continuity for members.
    Note: Retry logic is now handled by DuesScheduleCreationService with frappe.enqueue().
    """
    from verenigingen.utils.db_advisory_lock import get_lock, release_lock

    if not get_lock("sched_auto_create_dues_schedules", timeout=0):
        frappe.logger().info("auto_create_missing_dues_schedules already running, skipping")
        return {"total_found": 0, "created": 0, "errors": 0, "skipped": True}

    try:
        return _auto_create_missing_dues_schedules_impl()
    finally:
        release_lock("sched_auto_create_dues_schedules")


def _auto_create_missing_dues_schedules_impl():
    frappe.logger().info("Starting scheduled auto-creation of missing dues schedules")

    # Call the enhanced version that's defined later in this file
    result = auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=True)

    # Only send summary email if inner function didn't already send one
    # (i.e., when there are errors but no creations)
    if result.get("created_count", 0) == 0 and result.get("error_count", 0) > 0:
        _send_summary_email(result)

    return {
        "total_found": result.get("total_members", 0),
        "created": result.get("created_count", 0),
        "errors": result.get("error_count", 0),
    }


def _process_dues_schedule_retry_queue():
    """
    DEPRECATED: Process the retry queue for failed dues schedule creations

    This function is obsolete and will be removed in a future version.
    Retry logic is now handled by DuesScheduleCreationService using frappe.enqueue().

    Returns empty result for backward compatibility.
    """
    frappe.logger().warning(
        "[DEPRECATED] _process_dues_schedule_retry_queue() is deprecated. "
        "Use DuesScheduleCreationService instead."
    )
    return {
        "processed_count": 0,
        "created_count": 0,
        "error_count": 0,
        "failed_retries": [],
        "successful_retries": [],
    }


def _create_max_retry_alert(member_name, retry_data):
    """
    DEPRECATED: Create alert when member reaches maximum retry attempts

    This function is obsolete and will be removed in a future version.
    Alerts are now handled by DuesScheduleCreationService._create_failure_alert().
    """
    frappe.logger().warning(
        "[DEPRECATED] _create_max_retry_alert() is deprecated. "
        "Use DuesScheduleCreationService._create_failure_alert() instead."
    )
    return  # No-op for backward compatibility
    try:
        # Create notification for administrators
        notification = frappe.new_doc("Notification Log")
        notification.subject = f"Dues Schedule Creation Failed - Max Retries Exceeded: {member_name}"
        notification.email_content = f"""
        <h3>Dues Schedule Creation Failed - Max Retries Exceeded</h3>

        <p>Multiple attempts to create a dues schedule have failed for this member.</p>

        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Member:</td>
                <td style="border: 1px solid #ddd; padding: 8px;">{member_name}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Membership:</td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_data.get('membership', 'N/A')}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Membership Type:</td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_data.get('membership_type', 'N/A')}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Retry Count:</td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_data.get('retry_count', 0)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Last Error:</td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_data.get('last_error', 'N/A')}</td>
            </tr>
        </table>

        <p style="margin-top: 20px; color: #d9534f;">
            <strong>Manual Intervention Required:</strong><br>
            This member's dues schedule must be created manually. Please check the membership type
            configuration and template settings.
        </p>

        <p style="margin-top: 15px;">
            <a href="/app/member/{member_name}" style="background: #007bff; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px;">View Member</a>
            <a href="/app/membership/{retry_data.get('membership', '')}" style="background: #28a745; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; margin-left: 10px;">View Membership</a>
        </p>
        """

        notification.type = "Alert"
        notification.document_type = "Member"
        notification.document_name = member_name
        notification.from_user = "Administrator"

        # Send to administrators
        admin_users = frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User"},
            or_filters=[
                ["role_profile_name", "=", Roles.VERENIGINGEN_ADMIN],
                ["name", "in", frappe.get_roles(Roles.VERENIGINGEN_ADMIN)],
            ],
            pluck="name",
        )

        if not admin_users:
            admin_users = frappe.get_all(
                "User",
                filters={"enabled": 1, "user_type": "System User"},
                or_filters=[["name", "in", frappe.get_roles(Roles.SYSTEM_MANAGER)]],
                pluck="name",
            )

        for admin in admin_users:
            admin_notification = notification.copy()
            admin_notification.for_user = admin

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="insert",
                doc=admin_notification,
                justification=f"Create max retry alert notification for member {member_name} after {retry_data.get('retry_count', 0)} failed attempts - administrative alerting for manual intervention",
                required_permissions=["Notification Log:create"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to create max retry alert for {member_name}: {'; '.join(result.errors)}"
                )

    except Exception as e:
        frappe.logger().error(f"Failed to create max retry alert for {member_name}: {str(e)}")


def _send_enhanced_summary_email(main_result, retry_result):
    """
    DEPRECATED: Send enhanced summary email including retry processing results

    This function is obsolete - retry results are no longer generated.
    Falls back to standard _send_summary_email().
    """
    frappe.logger().warning(
        "[DEPRECATED] _send_enhanced_summary_email() is deprecated. Using _send_summary_email() instead."
    )
    _send_summary_email(main_result)
    return  # No-op for backward compatibility

    # OLD CODE BELOW - UNREACHABLE (kept for reference during migration period)
    """OLD: Send enhanced summary email including retry processing results"""
    try:
        # Get administrators
        admins = frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User"},
            or_filters=[
                ["role_profile_name", "=", Roles.VERENIGINGEN_ADMIN],
                ["name", "in", frappe.get_roles(Roles.VERENIGINGEN_ADMIN)],
            ],
            pluck="email",
        )

        if not admins:
            try:
                settings = frappe.get_single("Verenigingen Settings")
                payments_settings = get_payments_settings()
                # Try to get notification emails from settings
                if (
                    hasattr(settings, "stuck_schedule_notification_emails")
                    and settings.stuck_schedule_notification_emails
                ):
                    admins = [
                        email.strip()
                        for email in settings.stuck_schedule_notification_emails.split(",")
                        if email.strip()
                    ]
                elif (
                    payments_settings
                    and hasattr(payments_settings, "financial_admin_emails")
                    and payments_settings.financial_admin_emails
                ):
                    admins = [
                        email.strip()
                        for email in payments_settings.financial_admin_emails.split(",")
                        if email.strip()
                    ]
                elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                    admins = [settings.member_contact_email]
            except Exception:
                pass

            if not admins:
                frappe.logger().warning(
                    "Enhanced dues schedule auto-creator: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails in Verenigingen Settings or financial_admin_emails in Verenigingen Payments Settings."
                )
                return

        subject = f"Enhanced Dues Schedule Auto-Creation Summary - {today()}"

        total_created = main_result.get("created_count", 0) + retry_result.get("created_count", 0)
        total_errors = main_result.get("error_count", 0) + retry_result.get("error_count", 0)

        message = f"""
        <h3>Enhanced Dues Schedule Auto-Creation Summary</h3>

        <p>The scheduled task for auto-creating missing dues schedules has completed, including retry processing.</p>

        <h4>Main Processing Results:</h4>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Members Found Without Schedules:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{main_result.get("total_members", 0)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>New Schedules Created:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{main_result.get("created_count", 0)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Main Processing Errors:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{main_result.get("error_count", 0)}</td>
            </tr>
        </table>

        <h4>Retry Queue Processing:</h4>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Retry Queue Items Processed:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_result.get("processed_count", 0)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Successful Retries:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_result.get("created_count", 0)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Failed Retries:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{retry_result.get("error_count", 0)}</td>
            </tr>
        </table>

        <h4>Overall Summary:</h4>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Total Schedules Created:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{total_created}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Total Errors:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{total_errors}</td>
            </tr>
        </table>

        <p style="margin-top: 20px;">
        {f'<span style="color: green;">✓ All operations completed successfully!</span>' if total_errors == 0 else ''}
        {f'<span style="color: orange;">⚠ Some operations failed. Check error logs and notifications for details.</span>' if total_errors > 0 else ''}
        </p>

        {f'<h4>Successful Retries:</h4><ul>' + ''.join([f'<li>Member {item["member"]}: Schedule {item["schedule"]} (Retry #{item["retry_count"]})</li>' for item in retry_result.get("successful_retries", [])]) + '</ul>' if retry_result.get("successful_retries") else ''}

        <p style="margin-top: 20px; font-size: 0.9em; color: #666;">
        This is an automated message from the Verenigingen system scheduled task.
        </p>
        """

        # Use EmailService for UI-controllable notifications
        from verenigingen.services.communication.email_service import get_email_service
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        email_service = get_email_service()
        context = {
            "member_name": "System Administrator",
            "notification_message": f"Enhanced dues schedule auto-creation completed. {total_created} schedules created, {total_errors} errors.",
            "payment_reference": f"Dues Schedule Task {today()}",
            "amount": f"{total_created} created",
            "payment_date": str(today()),
            "payment_method": "Scheduled Task",
            "action_required": message,
            "next_steps": (
                "Review any errors in the system logs." if total_errors > 0 else "No action required."
            ),
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=admins,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
            notification_key="dues_schedule_auto_creation_summary",
        )

    except Exception as e:
        frappe.logger().error(f"Error sending enhanced summary email: {str(e)}")


def send_summary_email(created_count, error_count, total_found):
    """Send summary email to administrators about the dues schedule creation"""
    try:
        # Get administrators
        admins = frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User"},
            or_filters=[
                ["role_profile_name", "=", Roles.VERENIGINGEN_ADMIN],
                ["name", "in", frappe.get_roles(Roles.VERENIGINGEN_ADMIN)],
            ],
            pluck="email",
        )

        if not admins:
            try:
                settings = frappe.get_single("Verenigingen Settings")
                payments_settings = get_payments_settings()
                # Try to get notification emails from settings
                if (
                    hasattr(settings, "stuck_schedule_notification_emails")
                    and settings.stuck_schedule_notification_emails
                ):
                    admins = [
                        email.strip()
                        for email in settings.stuck_schedule_notification_emails.split(",")
                        if email.strip()
                    ]
                elif (
                    payments_settings
                    and hasattr(payments_settings, "financial_admin_emails")
                    and payments_settings.financial_admin_emails
                ):
                    admins = [
                        email.strip()
                        for email in payments_settings.financial_admin_emails.split(",")
                        if email.strip()
                    ]
                elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                    admins = [settings.member_contact_email]
            except Exception:
                pass

            if not admins:
                frappe.logger().warning(
                    "Dues schedule auto-creator: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails in Verenigingen Settings or financial_admin_emails in Verenigingen Payments Settings."
                )
                return

        subject = f"Dues Schedule Auto-Creation Summary - {today()}"

        message = f"""
        <h3>Dues Schedule Auto-Creation Summary</h3>

        <p>The scheduled task for auto-creating missing dues schedules has completed.</p>

        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Total Members Found Without Schedules:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{total_found}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Schedules Successfully Created:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{created_count}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;"><strong>Errors Encountered:</strong></td>
                <td style="border: 1px solid #ddd; padding: 8px;">{error_count}</td>
            </tr>
        </table>

        <p style="margin-top: 20px;">
        {f'<span style="color: green;">✓ All schedules created successfully!</span>' if error_count == 0 and created_count == total_found else ''}
        {f'<span style="color: orange;">⚠ Some schedules could not be created. Please check the error logs.</span>' if error_count > 0 else ''}
        </p>

        <p style="margin-top: 20px; font-size: 0.9em; color: #666;">
        This is an automated message from the Verenigingen system.
        </p>
        """

        # Use EmailService for UI-controllable notifications
        from verenigingen.services.communication.email_service import get_email_service
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        email_service = get_email_service()
        context = {
            "member_name": "System Administrator",
            "notification_message": f"Dues schedule auto-creation completed. {created_count} schedules created, {error_count} errors.",
            "payment_reference": f"Dues Schedule Task {today()}",
            "amount": f"{created_count} created",
            "payment_date": str(today()),
            "payment_method": "Scheduled Task",
            "action_required": message,
            "next_steps": (
                "Review any errors in the system logs." if error_count > 0 else "No action required."
            ),
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=admins,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
            notification_key="dues_schedule_auto_creation_summary",
        )

    except Exception as e:
        frappe.logger().error(f"Error sending summary email: {str(e)}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def preview_missing_dues_schedules():
    """Preview members who would get dues schedules created (for testing)"""
    members_without_schedules = frappe.db.sql(
        """
        SELECT
            m.name as membership_name,
            m.member as member_name,
            m.membership_type,
            mem.full_name,
            mt.minimum_amount as membership_type_amount
        FROM `tabMembership` m
        INNER JOIN `tabMember` mem ON m.member = mem.name
        LEFT JOIN `tabMembership Type` mt ON m.membership_type = mt.name
        WHERE
            m.status = 'Active'
            AND m.docstatus = 1
            AND m.membership_type IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM `tabMembership Dues Schedule` mds
                WHERE mds.member = m.member
                AND mds.status = 'Active'
            )
        LIMIT 10
    """,
        as_dict=True,
    )

    return members_without_schedules


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def run_auto_creation_manually():
    """Allow administrators to run the auto-creation manually"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to create dues schedules")

    return auto_create_missing_dues_schedules()


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def auto_create_missing_dues_schedules(preview_mode=False, send_emails=True):
    """Web interface version that matches the expected signature"""
    return auto_create_missing_dues_schedules_enhanced(preview_mode=preview_mode, send_emails=send_emails)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=True):
    """Enhanced version that supports preview mode and returns detailed results"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to create dues schedules")

    # Get members without schedules
    members_without_schedules = frappe.db.sql(
        """
        SELECT
            m.name as membership_name,
            m.member as member_name,
            m.membership_type,
            mem.full_name,
            mem.member_id,
            mt.minimum_amount as membership_type_amount
        FROM `tabMembership` m
        INNER JOIN `tabMember` mem ON m.member = mem.name
        LEFT JOIN `tabMembership Type` mt ON m.membership_type = mt.name
        WHERE
            m.status = 'Active'
            AND m.docstatus = 1
            AND m.membership_type IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM `tabMembership Dues Schedule` mds
                WHERE mds.member = m.member
                AND mds.status = 'Active'
            )
    """,
        as_dict=True,
    )

    result = {
        "total_members": len(members_without_schedules),
        "created_count": 0,
        "error_count": 0,
        "created_schedules": [],
        "errors": [],
        "preview_mode": preview_mode,
    }

    if preview_mode:
        # Just return the members that would be processed
        for member in members_without_schedules:
            result["created_schedules"].append(
                {
                    "member": member.member_name,
                    "member_name": member.full_name,
                    "membership_type": member.membership_type,
                    "dues_rate": _get_validated_dues_rate(member),
                    "billing_frequency": "Monthly",
                }
            )
        return result

    # Actually create the schedules
    for member in members_without_schedules:
        try:
            membership_type_doc = frappe.get_doc("Membership Type", member.membership_type)

            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

            dues_schedule.schedule_name = generate_dues_schedule_name(
                member.member_name, member.membership_type
            )
            dues_schedule.member = member.member_name
            dues_schedule.member_name = member.full_name
            dues_schedule.membership = member.membership_name
            dues_schedule.membership_type = member.membership_type
            dues_schedule.status = "Active"
            # Get billing frequency (and currency) from template if available.
            billing_frequency = "Monthly"  # Explicit default for dues schedule auto-creation
            schedule_currency = None
            if membership_type_doc.dues_schedule_template:
                try:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    # Only use template frequency if it's explicitly set and not empty
                    if template.billing_frequency and template.billing_frequency.strip():
                        billing_frequency = template.billing_frequency
                    if template.currency:
                        schedule_currency = template.currency
                except Exception:
                    pass
            dues_schedule.billing_frequency = billing_frequency
            # Ensure the mandatory currency field is populated (default to EUR for
            # the association rather than relying on the system default currency).
            dues_schedule.currency = schedule_currency or "EUR"

            # Get dues_rate from template, with minimum_amount as floor constraint
            template_dues_rate = 0
            if membership_type_doc.dues_schedule_template:
                try:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    template_dues_rate = _get_template_dues_rate(template)
                except Exception:
                    pass

            # Validate dues rate - require explicit configuration
            dues_rate = _validate_final_dues_rate(template_dues_rate, membership_type_doc)

            # Validate that dues_rate meets minimum_amount constraint
            minimum_amount = getattr(membership_type_doc, "minimum_amount", 0)
            if minimum_amount and dues_rate < minimum_amount:
                dues_rate = minimum_amount

            dues_schedule.dues_rate = dues_rate
            dues_schedule.contribution_mode = "Fixed"  # Auto-created schedules use Fixed mode
            dues_schedule.uses_custom_amount = 1  # Mark as custom amount
            dues_schedule.custom_amount_approved = 1  # Auto-approve for system creation
            dues_schedule.custom_amount_reason = f"Auto-created from membership type {member.membership_type}"
            dues_schedule.custom_amount_approved_by = frappe.session.user
            dues_schedule.custom_amount_approved_date = today()
            dues_schedule.auto_generate = 1
            # Set next invoice date based on billing frequency
            dues_schedule.next_invoice_date = _calculate_next_invoice_date(billing_frequency)
            dues_schedule.notes = f"Auto-created via manual trigger on {today()}"

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            operation_result = secure_document_operation(
                operation="insert",
                doc=dues_schedule,
                justification=f"Auto-create missing dues schedule for member {member.member_name} with membership type {member.membership_type} - automated billing continuity",
                required_permissions=["Membership Dues Schedule:create"],
            )

            if not operation_result.success:
                result["errors"].append(
                    f"Failed to create dues schedule for {member.member_name}: {'; '.join(operation_result.errors)}"
                )
                result["error_count"] += 1
                continue

            # ✅ NEW: Update member fields when creating schedule
            try:
                # Update member's current_dues_schedule and dues_rate
                frappe.db.set_value("Member", member.member_name, "current_dues_schedule", dues_schedule.name)
                frappe.db.set_value("Member", member.member_name, "dues_rate", dues_schedule.dues_rate)
                frappe.db.set_value(
                    "Member", member.member_name, "next_invoice_date", dues_schedule.next_invoice_date
                )

                # Add fee change history entry via the canonical writer (dedup,
                # billing-frequency validation, old_dues_rate default, 50-row cap).
                from verenigingen.services.member.history.member_fee_change_history_service import (
                    get_member_fee_change_history_service,
                )

                member_doc = frappe.get_doc("Member", member.member_name)
                get_member_fee_change_history_service().add_fee_change_to_history(
                    member_doc,
                    {
                        "name": dues_schedule.name,
                        "billing_frequency": dues_schedule.billing_frequency,
                        "dues_rate": dues_schedule.dues_rate,
                        "change_type": "Schedule Created",
                        "reason": f"Auto-created from membership type {member.membership_type}",
                        "changed_by": frappe.session.user,
                    },
                )
                member_doc.save()

            except Exception as sync_error:
                # Don't fail the entire operation if sync fails, just log it
                frappe.log_error(
                    f"Failed to sync member fields for {member.member_name}: {str(sync_error)}",
                    "Auto-Creator Field Sync Error",
                )

            result["created_schedules"].append(
                {
                    "member": member.member_name,
                    "member_name": member.full_name,
                    "schedule_name": dues_schedule.name,
                    "dues_rate": dues_schedule.dues_rate,
                    "billing_frequency": dues_schedule.billing_frequency,
                }
            )
            result["created_count"] += 1

        except Exception as e:
            # NOTE: the SQL row exposes `full_name` (aliased from Member.full_name)
            # and `member_name` (aliased from Membership.member). `member_full_name`
            # does not exist on the row, so referencing it here used to raise
            # AttributeError inside the handler and mask the real error.
            result["errors"].append(f"Error creating schedule for {member.full_name}: {str(e)}")
            result["error_count"] += 1

    if result["created_count"] > 0:
        frappe.db.commit()

    # Send email if requested and not in preview mode
    if send_emails and not preview_mode and result["created_count"] > 0:
        try:
            _send_summary_email(result)
            result["email_sent"] = True
        except Exception as e:
            result["errors"].append(f"Error sending email: {str(e)}")

    return result


def _send_summary_email(result):
    """Send summary email about manual dues schedule creation"""
    admins = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        or_filters=[
            ["role_profile_name", "=", Roles.VERENIGINGEN_ADMIN],
        ],
        pluck="email",
    )

    if not admins:
        try:
            settings = frappe.get_single("Verenigingen Settings")
            payments_settings = get_payments_settings()
            # Try to get notification emails from settings
            if (
                hasattr(settings, "stuck_schedule_notification_emails")
                and settings.stuck_schedule_notification_emails
            ):
                admins = [
                    email.strip()
                    for email in settings.stuck_schedule_notification_emails.split(",")
                    if email.strip()
                ]
            elif (
                payments_settings
                and hasattr(payments_settings, "financial_admin_emails")
                and payments_settings.financial_admin_emails
            ):
                admins = [
                    email.strip()
                    for email in payments_settings.financial_admin_emails.split(",")
                    if email.strip()
                ]
            elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                admins = [settings.member_contact_email]
        except Exception:
            pass

        if not admins:
            frappe.logger().warning(
                "Manual dues schedule creation: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails in Verenigingen Settings or financial_admin_emails in Verenigingen Payments Settings."
            )
            return

    subject = f"Manual Dues Schedule Creation - {today()}"

    message = f"""
    <h3>Manual Dues Schedule Creation Summary</h3>

    <p>Dues schedules were manually created via the admin interface.</p>

    <table style="border-collapse: collapse;">
        <tr>
            <td style="border: 1px solid #ddd; padding: 8px;"><strong>Total Members Processed:</strong></td>
            <td style="border: 1px solid #ddd; padding: 8px;">{result['total_members']}</td>
        </tr>
        <tr>
            <td style="border: 1px solid #ddd; padding: 8px;"><strong>Schedules Created:</strong></td>
            <td style="border: 1px solid #ddd; padding: 8px;">{result['created_count']}</td>
        </tr>
        <tr>
            <td style="border: 1px solid #ddd; padding: 8px;"><strong>Errors:</strong></td>
            <td style="border: 1px solid #ddd; padding: 8px;">{result['error_count']}</td>
        </tr>
    </table>

    <p>Created by: {frappe.session.user}</p>
    """

    try:
        # Use EmailService for UI-controllable notifications
        from verenigingen.services.communication.email_service import get_email_service
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        email_service = get_email_service()
        context = {
            "member_name": "System Administrator",
            "notification_message": f"Manual dues schedule creation completed. {result['created_count']} schedules created by {frappe.session.user}.",
            "payment_reference": f"Manual Creation {today()}",
            "amount": f"{result['created_count']} created",
            "payment_date": str(today()),
            "payment_method": "Manual Admin Action",
            "action_required": message,
            "next_steps": (
                f"Review any errors ({result['error_count']}) in the system logs."
                if result["error_count"] > 0
                else "No action required."
            ),
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=admins,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
            notification_key="dues_schedule_manual_creation",
        )
    except Exception as e:
        frappe.logger().error(f"Error sending manual dues schedule creation email: {str(e)}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_members_without_dues_schedules():
    """Get list of members without active dues schedules"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to create dues schedules")

    members = frappe.db.sql(
        """
        SELECT
            m.name,
            m.member_id,
            m.full_name,
            m.status,
            mb.membership_type,
            mb.status as membership_status
        FROM `tabMember` m
        INNER JOIN `tabMembership` mb ON mb.member = m.name
        LEFT JOIN `tabMembership Dues Schedule` ds ON ds.member = m.name AND ds.status = 'Active'
        WHERE
            mb.status = 'Active'
            AND mb.membership_type IS NOT NULL
            AND mb.membership_type != ''
            AND mb.docstatus = 1
            AND ds.name IS NULL
        ORDER BY m.full_name
    """,
        as_dict=True,
    )

    return members


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_dues_schedule_retry_queue_status():
    """
    DEPRECATED: Get status of the dues schedule retry queue for administrators

    This function is obsolete - retry queue no longer exists.
    Retry logic now uses frappe.enqueue() background jobs.
    """
    frappe.logger().warning(
        "[DEPRECATED] get_dues_schedule_retry_queue_status() is deprecated. "
        "Retry queue no longer exists - use RQ job status instead."
    )
    return {"queue_size": 0, "items": [], "message": "Retry queue no longer exists (deprecated)"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_dues_schedule_retry_queue(member_name: str = None):
    """
    DEPRECATED: Clear retry queue items (all or specific member) - admin only

    This function is obsolete - retry queue no longer exists.
    Retry logic now uses frappe.enqueue() background jobs.
    """
    frappe.logger().warning(
        "[DEPRECATED] clear_dues_schedule_retry_queue() is deprecated. " "Retry queue no longer exists."
    )
    return {"message": "Retry queue no longer exists (deprecated) - no action taken"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def manually_process_retry_queue():
    """
    DEPRECATED: Manually trigger retry queue processing - admin only

    This function is obsolete - retry queue no longer exists.
    Retry logic now uses frappe.enqueue() background jobs automatically.
    """
    frappe.logger().warning(
        "[DEPRECATED] manually_process_retry_queue() is deprecated. "
        "Retry queue no longer exists - retries happen automatically via background jobs."
    )
    return {
        "processed_count": 0,
        "created_count": 0,
        "error_count": 0,
        "successful_retries": [],
        "failed_retries": [],
        "message": "Retry queue no longer exists (deprecated) - retries happen automatically via background jobs",
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_dues_schedules_for_members(members: str, send_emails: bool = False):
    """Create dues schedules for specific members"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to create dues schedules")

    if isinstance(members, str):
        import json

        members = json.loads(members)

    result = {
        "total_members": len(members),
        "created_count": 0,
        "error_count": 0,
        "created_schedules": [],
        "errors": [],
    }

    for member_name in members:
        try:
            # Get member and membership details
            membership = frappe.db.get_value(
                "Membership",
                {"member": member_name, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if not membership:
                result["errors"].append(f"No active membership found for {member_name}")
                result["error_count"] += 1
                continue

            # Get membership type details
            membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)

            # Get dues_rate from template, with minimum_amount as floor constraint
            template_dues_rate = 0
            if membership_type_doc.dues_schedule_template:
                try:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    template_dues_rate = _get_template_dues_rate(template)
                except Exception:
                    pass

            # Validate dues rate - require explicit configuration
            dues_rate = _validate_final_dues_rate(template_dues_rate, membership_type_doc)

            # Validate that dues_rate meets minimum_amount constraint
            minimum_amount = getattr(membership_type_doc, "minimum_amount", 0)
            if minimum_amount and dues_rate < minimum_amount:
                dues_rate = minimum_amount

            # Resolve currency: prefer the template's currency, otherwise default
            # to EUR. Building the doc via frappe.get_doc({...}) does NOT apply the
            # DocType field default, so currency (a mandatory field) must be set
            # explicitly or insert fails with a "currency" mandatory error.
            schedule_currency = "EUR"
            if membership_type_doc.dues_schedule_template:
                template_currency = frappe.db.get_value(
                    "Membership Dues Schedule",
                    membership_type_doc.dues_schedule_template,
                    "currency",
                )
                if template_currency:
                    schedule_currency = template_currency

            # Create dues schedule with new naming pattern
            from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

            schedule_name = generate_dues_schedule_name(member_name, membership.membership_type)
            dues_schedule = frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": schedule_name,
                    "member": member_name,
                    "membership": membership.name,
                    "membership_type": membership.membership_type,
                    "currency": schedule_currency,
                    "dues_rate": dues_rate,
                    "billing_frequency": "Monthly",
                    "status": "Active",
                    "next_invoice_date": _calculate_next_invoice_date("Monthly"),
                    "contribution_mode": "Fixed",  # Auto-created schedules use Fixed mode
                    "uses_custom_amount": 1,  # Mark as custom amount
                    "custom_amount_approved": 1,  # Auto-approve for system creation
                    "custom_amount_reason": f"Auto-created from membership type {membership.membership_type}",
                    "custom_amount_approved_by": frappe.session.user,
                    "custom_amount_approved_date": frappe.utils.today(),
                    "auto_generate": 1,
                    "notes": "Auto-created by dues schedule creator",
                }
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            operation_result = secure_document_operation(
                operation="insert",
                doc=dues_schedule,
                justification=f"Create dues schedule for member {member_name} with membership type {membership.membership_type} - selective member billing setup",
                required_permissions=["Membership Dues Schedule:create"],
            )

            if not operation_result.success:
                result["errors"].append(
                    f"Failed to create dues schedule for {member_name}: {'; '.join(operation_result.errors)}"
                )
                result["error_count"] += 1
                continue

            member_doc = frappe.get_doc("Member", member_name)
            result["created_schedules"].append(
                {
                    "member": member_name,
                    "member_name": member_doc.full_name,
                    "schedule_name": dues_schedule.name,
                    "dues_rate": dues_schedule.dues_rate,
                    "billing_frequency": dues_schedule.billing_frequency,
                }
            )
            result["created_count"] += 1

        except Exception as e:
            result["errors"].append(f"Error creating schedule for {member_name}: {str(e)}")
            result["error_count"] += 1

    frappe.db.commit()

    # Send email if requested
    if send_emails and result["created_count"] > 0:
        try:
            _send_summary_email(result)
            result["email_sent"] = True
        except Exception as e:
            result["errors"].append(f"Error sending email: {str(e)}")

    return result
