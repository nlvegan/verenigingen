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


def auto_create_missing_dues_schedules_scheduled():
    """
    Scheduled task version - Auto-create missing dues schedules for members who have:
    1. An active membership with a membership type
    2. No active dues schedule

    This scheduled task ensures billing continuity for members.
    """
    frappe.logger().info("Starting scheduled auto-creation of missing dues schedules")

    # Call the enhanced version that's defined later in this file
    result = auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=True)

    return {
        "total_found": result.get("total_members", 0),
        "created": result.get("created_count", 0),
        "errors": result.get("error_count", 0),
    }


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
            # Fallback to configured creation user from Verenigingen Settings
            try:
                settings = frappe.get_single("Verenigingen Settings")
                creation_user = getattr(settings, "creation_user", None)
                if creation_user:
                    admins = [creation_user]
                else:
                    admins = ["Administrator"]  # Final fallback
            except Exception:
                admins = ["Administrator"]  # Final fallback

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
                    "dues_rate": member.membership_type_amount or 0,
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
            billing_frequency = "Monthly"  # Better default than Annual
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
                    template_dues_rate = template.dues_rate or template.suggested_amount or 0
                except Exception:
                    pass

            # Use template amount if available, otherwise fall back to minimum_amount as last resort
            dues_rate = template_dues_rate or getattr(membership_type_doc, "minimum_amount", 0)

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
        # Fallback to configured creation user from Verenigingen Settings
        try:
            settings = frappe.get_single("Verenigingen Settings")
            creation_user = getattr(settings, "creation_user", None)
            if creation_user:
                admins = [creation_user]
            else:
                admins = ["Administrator"]  # Final fallback
        except Exception:
            admins = ["Administrator"]  # Final fallback

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

    frappe.sendmail(recipients=admins, subject=subject, message=message, delayed=False)


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
                    template_dues_rate = template.dues_rate or template.suggested_amount or 0
                except Exception:
                    pass

            # Use template amount if available, otherwise fall back to minimum_amount as last resort
            dues_rate = template_dues_rate or getattr(membership_type_doc, "minimum_amount", 0)

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
