# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Scheduled task to auto-create missing dues schedules for members with assigned membership types
"""

import frappe
from frappe.utils import add_days, add_months, add_years, getdate, today


def _calculate_next_invoice_date(billing_frequency):
    """Calculate next invoice date based on billing frequency"""
    if billing_frequency == "Daily":
        return add_days(today(), 1)
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

    This scheduled task ensures billing continuity for members and handles retries from failed hook attempts.
    """
    frappe.logger().info("Starting scheduled auto-creation of missing dues schedules")

    # Process retry queue first
    retry_result = _process_dues_schedule_retry_queue()

    # Call the enhanced version that's defined later in this file
    result = auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=True)

    # Combine results
    total_created = result.get("created_count", 0) + retry_result.get("created_count", 0)
    total_errors = result.get("error_count", 0) + retry_result.get("error_count", 0)

    # Send enhanced summary email if there were activities
    if total_created > 0 or total_errors > 0:
        _send_enhanced_summary_email(result, retry_result)

    return {
        "total_found": result.get("total_members", 0),
        "created": total_created,
        "errors": total_errors,
        "retry_processed": retry_result.get("processed_count", 0),
    }


def _process_dues_schedule_retry_queue():
    """Process the retry queue for failed dues schedule creations"""
    result = {
        "processed_count": 0,
        "created_count": 0,
        "error_count": 0,
        "failed_retries": [],
        "successful_retries": [],
    }

    try:
        # Get retry queue from cache
        retry_queue = frappe.cache().get("dues_schedule_retry_queue") or {}

        if not retry_queue:
            return result

        frappe.logger().info(f"Processing {len(retry_queue)} items from dues schedule retry queue")

        for member_name, retry_data in retry_queue.items():
            try:
                result["processed_count"] += 1

                # Check if member still needs a dues schedule
                existing_schedule = frappe.db.get_value(
                    "Membership Dues Schedule", {"member": member_name, "is_template": 0}, "name"
                )

                if existing_schedule:
                    # Schedule already exists, remove from retry queue
                    current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
                    if member_name in current_queue:
                        del current_queue[member_name]
                        frappe.cache().set("dues_schedule_retry_queue", current_queue)
                    frappe.logger().info(
                        f"Member {member_name} already has dues schedule, removed from retry queue"
                    )
                    continue

                # Check retry count and time limits
                retry_count = retry_data.get("retry_count", 0)
                max_retries = 3

                if retry_count >= max_retries:
                    # Too many retries, create alert and remove from queue
                    _create_max_retry_alert(member_name, retry_data)
                    current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
                    if member_name in current_queue:
                        del current_queue[member_name]
                        frappe.cache().set("dues_schedule_retry_queue", current_queue)
                    result["error_count"] += 1
                    result["failed_retries"].append({"member": member_name, "reason": "Max retries exceeded"})
                    continue

                # Attempt to create dues schedule
                membership_name = retry_data.get("membership")
                membership_type = retry_data.get("membership_type")

                if not membership_name or not membership_type:
                    frappe.logger().error(
                        f"Invalid retry data for member {member_name}: missing membership info"
                    )
                    current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
                    if member_name in current_queue:
                        del current_queue[member_name]
                        frappe.cache().set("dues_schedule_retry_queue", current_queue)
                    continue

                # Try to create the dues schedule
                try:
                    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                        MembershipDuesSchedule,
                    )

                    schedule_name = MembershipDuesSchedule.create_from_template(
                        member_name, membership_type=membership_type, membership_name=membership_name
                    )

                    # Update member record with dues schedule link
                    member = frappe.get_doc("Member", member_name)
                    member.dues_schedule = schedule_name
                    member.save()

                    # Success - remove from retry queue
                    current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
                    if member_name in current_queue:
                        del current_queue[member_name]
                        frappe.cache().set("dues_schedule_retry_queue", current_queue)
                    result["created_count"] += 1
                    result["successful_retries"].append(
                        {"member": member_name, "schedule": schedule_name, "retry_count": retry_count + 1}
                    )

                    frappe.logger().info(
                        f"Successfully created dues schedule {schedule_name} for member {member_name} on retry {retry_count + 1}"
                    )

                except Exception as create_error:
                    # Update retry count and schedule next attempt
                    retry_data["retry_count"] = retry_count + 1
                    retry_data["last_attempt"] = frappe.utils.now()
                    retry_data["last_error"] = str(create_error)

                    current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
                    current_queue[member_name] = retry_data
                    frappe.cache().set("dues_schedule_retry_queue", current_queue)
                    result["error_count"] += 1
                    result["failed_retries"].append(
                        {"member": member_name, "error": str(create_error), "retry_count": retry_count + 1}
                    )

                    frappe.logger().warning(
                        f"Retry {retry_count + 1} failed for member {member_name}: {str(create_error)}"
                    )

            except Exception as process_error:
                frappe.logger().error(
                    f"Error processing retry for member {member_name}: {str(process_error)}"
                )
                result["error_count"] += 1

    except Exception as queue_error:
        frappe.logger().error(f"Error processing dues schedule retry queue: {str(queue_error)}")

    return result


def _create_max_retry_alert(member_name, retry_data):
    """Create alert when member reaches maximum retry attempts"""
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
                ["role_profile_name", "=", "Verenigingen Administrator"],
                ["name", "in", frappe.get_roles("Verenigingen Administrator")],
            ],
            pluck="name",
        )

        if not admin_users:
            admin_users = frappe.get_all(
                "User",
                filters={"enabled": 1, "user_type": "System User"},
                or_filters=[["name", "in", frappe.get_roles("System Manager")]],
                pluck="name",
            )

        for admin in admin_users:
            admin_notification = notification.copy()
            admin_notification.for_user = admin
            admin_notification.insert(ignore_permissions=True)

    except Exception as e:
        frappe.logger().error(f"Failed to create max retry alert for {member_name}: {str(e)}")


def _send_enhanced_summary_email(main_result, retry_result):
    """Send enhanced summary email including retry processing results"""
    try:
        # Get administrators
        admins = frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User"},
            or_filters=[
                ["role_profile_name", "=", "Verenigingen Administrator"],
                ["name", "in", frappe.get_roles("Verenigingen Administrator")],
            ],
            pluck="email",
        )

        if not admins:
            try:
                settings = frappe.get_single("Verenigingen Settings")
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
                elif hasattr(settings, "financial_admin_emails") and settings.financial_admin_emails:
                    admins = [
                        email.strip() for email in settings.financial_admin_emails.split(",") if email.strip()
                    ]
                elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                    admins = [settings.member_contact_email]
            except Exception:
                pass

            if not admins:
                frappe.logger().warning(
                    "Enhanced dues schedule auto-creator: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails or financial_admin_emails in Verenigingen Settings."
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

        frappe.sendmail(recipients=admins, subject=subject, message=message, delayed=False)

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
                ["role_profile_name", "=", "Verenigingen Administrator"],
                ["name", "in", frappe.get_roles("Verenigingen Administrator")],
            ],
            pluck="email",
        )

        if not admins:
            try:
                settings = frappe.get_single("Verenigingen Settings")
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
                elif hasattr(settings, "financial_admin_emails") and settings.financial_admin_emails:
                    admins = [
                        email.strip() for email in settings.financial_admin_emails.split(",") if email.strip()
                    ]
                elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                    admins = [settings.member_contact_email]
            except Exception:
                pass

            if not admins:
                frappe.logger().warning(
                    "Dues schedule auto-creator: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails or financial_admin_emails in Verenigingen Settings."
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

        frappe.sendmail(recipients=admins, subject=subject, message=message, delayed=False)

    except Exception as e:
        frappe.logger().error(f"Error sending summary email: {str(e)}")


@frappe.whitelist()
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
def run_auto_creation_manually():
    """Allow administrators to run the auto-creation manually"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to create dues schedules")

    return auto_create_missing_dues_schedules()


@frappe.whitelist()
def auto_create_missing_dues_schedules(preview_mode=False, send_emails=True):
    """Web interface version that matches the expected signature"""
    return auto_create_missing_dues_schedules_enhanced(preview_mode=preview_mode, send_emails=send_emails)


@frappe.whitelist()
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
            # Get billing frequency from template if available
            billing_frequency = "Monthly"  # Explicit default for dues schedule auto-creation
            if membership_type_doc.dues_schedule_template:
                try:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    # Only use template frequency if it's explicitly set and not empty
                    if template.billing_frequency and template.billing_frequency.strip():
                        billing_frequency = template.billing_frequency
                except Exception:
                    pass
            dues_schedule.billing_frequency = billing_frequency

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
            dues_schedule.contribution_mode = "Custom"  # Use Custom mode for auto-created
            dues_schedule.uses_custom_amount = 1  # Mark as custom amount
            dues_schedule.custom_amount_approved = 1  # Auto-approve for system creation
            dues_schedule.custom_amount_reason = f"Auto-created from membership type {member.membership_type}"
            dues_schedule.custom_amount_approved_by = frappe.session.user
            dues_schedule.custom_amount_approved_date = today()
            dues_schedule.auto_generate = 1
            # Set next invoice date based on billing frequency
            dues_schedule.next_invoice_date = _calculate_next_invoice_date(billing_frequency)
            dues_schedule.notes = f"Auto-created via manual trigger on {today()}"

            dues_schedule.insert(ignore_permissions=True)

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
            result["errors"].append(f"Error creating schedule for {member.member_full_name}: {str(e)}")
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
            ["role_profile_name", "=", "Verenigingen Administrator"],
        ],
        pluck="email",
    )

    if not admins:
        try:
            settings = frappe.get_single("Verenigingen Settings")
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
            elif hasattr(settings, "financial_admin_emails") and settings.financial_admin_emails:
                admins = [
                    email.strip() for email in settings.financial_admin_emails.split(",") if email.strip()
                ]
            elif hasattr(settings, "member_contact_email") and settings.member_contact_email:
                admins = [settings.member_contact_email]
        except Exception:
            pass

        if not admins:
            frappe.logger().warning(
                "Manual dues schedule creation: No valid admin emails found for notifications. Configure stuck_schedule_notification_emails or financial_admin_emails in Verenigingen Settings."
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
        frappe.sendmail(recipients=admins, subject=subject, message=message, delayed=False)
    except Exception as e:
        frappe.logger().error(f"Error sending manual dues schedule creation email: {str(e)}")


@frappe.whitelist()
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
def get_dues_schedule_retry_queue_status():
    """Get status of the dues schedule retry queue for administrators"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to view dues schedule retry queue")

    try:
        import json

        retry_queue = frappe.cache().get("dues_schedule_retry_queue") or {}

        if not retry_queue:
            return {"queue_size": 0, "items": [], "message": "Retry queue is empty"}

        queue_items = []
        for member_name, retry_data in retry_queue.items():
            try:
                queue_items.append(
                    {
                        "member": member_name,
                        "membership": retry_data.get("membership"),
                        "membership_type": retry_data.get("membership_type"),
                        "retry_count": retry_data.get("retry_count", 0),
                        "last_attempt": retry_data.get("last_attempt"),
                        "last_error": retry_data.get("last_error", "N/A"),
                        "scheduled_by": retry_data.get("scheduled_by", "unknown"),
                    }
                )
            except Exception as e:
                queue_items.append({"member": member_name, "error": f"Invalid retry data: {str(e)}"})

        return {
            "queue_size": len(retry_queue),
            "items": queue_items,
            "message": f"Found {len(retry_queue)} items in retry queue",
        }

    except Exception as e:
        frappe.throw(f"Error accessing retry queue: {str(e)}")


@frappe.whitelist()
def clear_dues_schedule_retry_queue(member_name=None):
    """Clear retry queue items (all or specific member) - admin only"""
    if not frappe.has_permission("System Manager"):
        frappe.throw("Only System Managers can clear the retry queue")

    try:
        if member_name:
            # Clear specific member
            current_queue = frappe.cache().get("dues_schedule_retry_queue") or {}
            if member_name in current_queue:
                del current_queue[member_name]
                frappe.cache().set("dues_schedule_retry_queue", current_queue)
            return {"message": f"Cleared retry queue for member {member_name}"}
        else:
            # Clear entire queue
            frappe.cache().delete_value("dues_schedule_retry_queue")
            return {"message": "Cleared entire retry queue"}

    except Exception as e:
        frappe.throw(f"Error clearing retry queue: {str(e)}")


@frappe.whitelist()
def manually_process_retry_queue():
    """Manually trigger retry queue processing - admin only"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw("You don't have permission to process retry queue")

    frappe.logger().info("Manual retry queue processing triggered by user: " + frappe.session.user)

    result = _process_dues_schedule_retry_queue()

    return {
        "processed_count": result.get("processed_count", 0),
        "created_count": result.get("created_count", 0),
        "error_count": result.get("error_count", 0),
        "successful_retries": result.get("successful_retries", []),
        "failed_retries": result.get("failed_retries", []),
        "message": f"Processed {result.get('processed_count', 0)} items from retry queue. "
        f"Created {result.get('created_count', 0)} schedules, "
        f"{result.get('error_count', 0)} errors.",
    }


@frappe.whitelist()
def create_dues_schedules_for_members(members, send_emails=False):
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
                    "dues_rate": dues_rate,
                    "billing_frequency": "Monthly",
                    "status": "Active",
                    "next_invoice_date": _calculate_next_invoice_date("Monthly"),
                    "contribution_mode": "Custom",  # Use Custom mode for auto-created
                    "uses_custom_amount": 1,  # Mark as custom amount
                    "custom_amount_approved": 1,  # Auto-approve for system creation
                    "custom_amount_reason": f"Auto-created from membership type {membership.membership_type}",
                    "custom_amount_approved_by": frappe.session.user,
                    "custom_amount_approved_date": frappe.utils.today(),
                    "auto_generate": 1,
                    "notes": "Auto-created by dues schedule creator",
                }
            )

            dues_schedule.insert(ignore_permissions=True)

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
