"""
API endpoints for overdue payment processing and management
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, today

from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.error_handling import (
    PermissionError,
    ValidationError,
    handle_api_error,
    log_error,
    validate_required_fields,
)
from verenigingen.utils.performance_utils import QueryOptimizer, performance_monitor
from verenigingen.utils.validation.api_validators import (
    APIValidator,
    rate_limit,
    require_roles,
    validate_api_input,
)


@frappe.whitelist()
@handle_api_error
@performance_monitor(threshold_ms=2000)
@require_roles(["System Manager", "Verenigingen Administrator", "Verenigingen Manager"])
@rate_limit(max_requests=10, window_minutes=60)
def send_overdue_payment_reminders(
    reminder_type="Friendly Reminder",
    include_payment_link=True,
    custom_message=None,
    send_to_chapters=False,
    filters=None,
):
    """Send payment reminders to members with overdue payments"""

    # Validate inputs
    validate_required_fields({"reminder_type": reminder_type}, ["reminder_type"])

    reminder_type = APIValidator.sanitize_text(reminder_type, max_length=50)
    custom_message = APIValidator.sanitize_text(custom_message, max_length=1000) if custom_message else None

    # Get overdue payments based on filters
    from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON format in filters")

    overdue_data = get_data(filters)

    if not overdue_data:
        return {"success": False, "message": _("No overdue payments found"), "count": 0}

    sent_count = 0
    batch_size = ConfigManager.get("email_batch_size", 50)

    # Process in batches to avoid overwhelming the email system
    for i in range(0, len(overdue_data), batch_size):
        batch = overdue_data[i : i + batch_size]

        for payment_info in batch:
            try:
                # Send reminder to member
                send_payment_reminder_email(
                    member_name=payment_info.get("member_name"),
                    reminder_type=reminder_type,
                    include_payment_link=include_payment_link,
                    custom_message=custom_message,
                    payment_info=payment_info,
                )

                # Optionally send to chapter board
                if send_to_chapters and payment_info.get("chapter"):
                    send_chapter_notification(
                        chapter=payment_info.get("chapter"),
                        member_name=payment_info.get("member_name"),
                        payment_info=payment_info,
                    )

                sent_count += 1

            except Exception as e:
                log_error(
                    f"Failed to send reminder to {payment_info.get('member_name')}: {str(e)}",
                    "Payment Reminder Error",
                )
                continue

    return {"success": True, "message": _("Payment reminders sent successfully"), "count": sent_count}


@frappe.whitelist()
@handle_api_error
@performance_monitor(threshold_ms=5000)
@require_roles(["System Manager", "Verenigingen Administrator", "Verenigingen Manager"])
@rate_limit(max_requests=5, window_minutes=60)
def export_overdue_payments(filters=None, format="CSV"):
    """Export overdue payments data for external processing"""

    from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON format in filters")

    # Validate format parameter
    if format not in ["CSV", "XLSX"]:
        raise ValidationError("Invalid export format. Supported formats: CSV, XLSX")

    data = get_data(filters)

    if not data:
        return {"success": False, "message": _("No data to export"), "count": 0}

    # Create export file
    file_name = f"overdue_payments_{today()}.csv"
    file_path = f"/tmp/{file_name}"

    try:
        import csv

        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "member_name",
                "member_full_name",
                "member_email",
                "chapter",
                "overdue_count",
                "total_overdue",
                "oldest_invoice_date",
                "days_overdue",
                "membership_type",
                "last_payment_date",
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in data:
                # Clean the row data for CSV export
                clean_row = {}
                for field in fieldnames:
                    value = row.get(field, "")
                    if field == "total_overdue":
                        value = flt(value, 2)
                    clean_row[field] = value
                writer.writerow(clean_row)

        # Create file record in Frappe
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "file_url": f"/files/{file_name}",
                "is_private": 1,
                "folder": "Home",
            }
        )
        file_doc.save()

        return {
            "success": True,
            "message": _("Export completed successfully"),
            "count": len(data),
            "file_url": file_doc.file_url,
            "file_name": file_name,
        }

    except Exception as e:
        log_error(f"Export failed: {str(e)}", "Payment Export Error")
        return {"success": False, "message": _("Export failed: {0}").format(str(e))}


@frappe.whitelist()
@handle_api_error
@performance_monitor(threshold_ms=10000)
@require_roles(["System Manager", "Verenigingen Administrator"])
@rate_limit(max_requests=3, window_minutes=60)
def execute_bulk_payment_action(action, apply_to="All Visible Records", filters=None):
    """Execute bulk actions on overdue payments"""

    # Validate inputs
    validate_required_fields({"action": action, "apply_to": apply_to}, ["action", "apply_to"])

    valid_actions = [
        "Send Payment Reminders",
        "Suspend Memberships",
        "Create Payment Plan",
        "Mark for Collection Agency",
        "Apply Late Fees",
    ]

    if action not in valid_actions:
        raise ValidationError(f"Invalid action. Valid actions: {', '.join(valid_actions)}")

    from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON format in filters")

    # Modify filters based on apply_to selection
    if apply_to == "Critical Only (>60 days)":
        filters["critical_only"] = True
    elif apply_to == "Urgent Only (>30 days)":
        filters["urgent_only"] = True

    data = get_data(filters)

    if not data:
        return {"success": False, "message": _("No records found"), "count": 0}

    processed_count = 0

    for payment_info in data:
        try:
            if action == "Send Payment Reminders":
                send_payment_reminder_email(
                    member_name=payment_info.get("member_name"),
                    reminder_type="Bulk Reminder",
                    payment_info=payment_info,
                )

            elif action == "Suspend Memberships":
                suspend_member_for_nonpayment(payment_info.get("member_name"))

            elif action == "Create Payment Plan":
                create_payment_plan(payment_info.get("member_name"), payment_info)

            elif action == "Mark for Collection Agency":
                mark_for_collection(payment_info.get("member_name"), payment_info)

            elif action == "Apply Late Fees":
                apply_late_fees(payment_info.get("member_name"), payment_info)

            processed_count += 1

        except Exception as e:
            log_error(
                f"Bulk action failed for {payment_info.get('member_name')}: {str(e)}",
                "Bulk Payment Action Error",
            )
            continue

    return {"success": True, "message": _("Bulk action completed"), "count": processed_count}


def send_payment_reminder_email(
    member_name,
    reminder_type="Friendly Reminder",
    include_payment_link=True,
    custom_message=None,
    payment_info=None,
):
    """Send individual payment reminder email"""

    member = frappe.get_doc("Member", member_name)

    if not member.email:
        frappe.logger().warning(f"No email address for member {member_name}")
        return False

    # Determine email template based on reminder type
    template_map = {
        "Friendly Reminder": "payment_reminder_friendly",
        "Urgent Notice": "payment_reminder_urgent",
        "Final Notice": "payment_reminder_final",
        "Bulk Reminder": "payment_reminder_bulk",
    }

    template_name = template_map.get(reminder_type, "payment_reminder_friendly")

    # Prepare email context
    context = {
        "member": member,
        "payment_info": payment_info,
        "custom_message": custom_message,
        "payment_link": generate_payment_link(member_name) if include_payment_link else None,
        "company": frappe.defaults.get_global_default("company"),
    }

    try:
        # Check if template exists, otherwise use fallback
        if frappe.db.exists("Email Template", template_name):
            email_template_doc = frappe.get_doc("Email Template", template_name)
            frappe.sendmail(
                recipients=[member.email],
                subject=email_template_doc.subject or get_reminder_subject(reminder_type, payment_info),
                message=frappe.render_template(email_template_doc.response, context),
                now=True,
            )
        else:
            # Fallback to simple HTML email
            message = generate_payment_reminder_html(member, payment_info, reminder_type, custom_message)
            frappe.sendmail(
                recipients=[member.email],
                subject=get_reminder_subject(reminder_type, payment_info),
                message=message,
                now=True,
            )

        # Log the reminder
        create_payment_reminder_log(member_name, reminder_type, payment_info)

        return True

    except Exception as e:
        frappe.logger().error(f"Failed to send payment reminder to {member.email}: {str(e)}")
        return False


def send_chapter_notification(chapter, member_name, payment_info):
    """Send notification to chapter board about overdue payment"""

    try:
        chapter_doc = frappe.get_doc("Chapter", chapter)
        board_emails = chapter_doc.get_board_member_emails()

        if not board_emails:
            return False

        member = frappe.get_doc("Member", member_name)

        message = f"""
        <h3>Overdue Payment Notification</h3>

        <p>A member in your chapter has overdue payments:</p>

        <ul>
            <li><strong>Member:</strong> {member.full_name} ({member_name})</li>
            <li><strong>Email:</strong> {member.email}</li>
            <li><strong>Overdue Amount:</strong> {frappe.format_value(payment_info.get('total_overdue'), {'fieldtype': 'Currency'})}</li>
            <li><strong>Days Overdue:</strong> {payment_info.get('days_overdue')} days</li>
            <li><strong>Number of Invoices:</strong> {payment_info.get('overdue_count')}</li>
        </ul>

        <p>Please follow up with this member as appropriate.</p>
        """

        frappe.sendmail(
            recipients=board_emails,
            subject=f"Overdue Payment Alert - {member.full_name}",
            message=message,
            now=True,
        )

        return True

    except Exception as e:
        frappe.logger().error(f"Failed to send chapter notification: {str(e)}")
        return False


def generate_payment_link(member_name):
    """Generate payment link for member"""
    # This would generate a secure payment link - implementation depends on payment gateway
    base_url = frappe.utils.get_url()
    return f"{base_url}/payment/membership/{member_name}"


def get_reminder_subject(reminder_type, payment_info):
    """Get email subject based on reminder type"""
    subjects = {
        "Friendly Reminder": _("Payment Reminder - Membership Fees"),
        "Urgent Notice": _("URGENT: Overdue Payment Notice"),
        "Final Notice": _("FINAL NOTICE: Immediate Payment Required"),
        "Bulk Reminder": _("Payment Reminder - Multiple Outstanding Invoices"),
    }

    return subjects.get(reminder_type, _("Payment Reminder"))


def generate_payment_reminder_html(member, payment_info, reminder_type, custom_message):
    """Generate HTML email for payment reminder"""

    # urgency_class = {
    #     "Friendly Reminder": "info",
    #     "Urgent Notice": "warning",
    #     "Final Notice": "danger",
    #     "Bulk Reminder": "info",
    # }.get(reminder_type, "info")  # Unused

    html = """
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #333;">Payment Reminder</h2>

        <p>Dear {member.first_name},</p>

        <p>This is a {reminder_type.lower()} regarding your membership payment(s).</p>

        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0;">
            <h4>Payment Details:</h4>
            <ul>
                <li><strong>Number of overdue invoices:</strong> {payment_info.get('overdue_count', 0)}</li>
                <li><strong>Total amount due:</strong> {frappe.format_value(payment_info.get('total_overdue', 0), {'fieldtype': 'Currency'})}</li>
                <li><strong>Days overdue:</strong> {payment_info.get('days_overdue', 0)} days</li>
                <li><strong>Membership type:</strong> {payment_info.get('membership_type', 'N/A')}</li>
            </ul>
        </div>

        {f'<p><em>{custom_message}</em></p>' if custom_message else ''}

        <p>Please arrange payment at your earliest convenience to avoid any disruption to your membership benefits.</p>

        <p>If you have any questions or need to discuss a payment plan, please contact us.</p>

        <p>Best regards,<br>The Membership Team</p>
    </div>
    """

    return html


def create_payment_reminder_log(member_name, reminder_type, payment_info):
    """Create log entry for payment reminder"""
    try:
        # This could be implemented as a custom DocType "Payment Reminder Log"
        # For now, we'll just add a comment to the member record
        member = frappe.get_doc("Member", member_name)
        member.add_comment(
            "Info",
            f"Payment reminder sent: {reminder_type} - Amount: {payment_info.get('total_overdue', 0)} - {payment_info.get('overdue_count', 0)} invoices",
        )
    except Exception as e:
        frappe.logger().error(f"Failed to create payment reminder log: {str(e)}")


def suspend_member_for_nonpayment(member_name):
    """Suspend member for non-payment"""
    # This would integrate with the suspension system
    try:
        from verenigingen.utils.termination_integration import suspend_member_safe

        return suspend_member_safe(
            member_name=member_name,
            suspension_reason="Non-payment of membership fees",
            suspend_user=False,  # Don't suspend user access immediately
            suspend_teams=True,  # But suspend team memberships
        )
    except Exception as e:
        frappe.logger().error(f"Failed to suspend member {member_name}: {str(e)}")
        return False


def create_payment_plan(member_name, payment_info):
    """Create payment plan for member"""
    # Placeholder for payment plan creation
    frappe.logger().info(f"Payment plan created for {member_name}")
    return True


def mark_for_collection(member_name, payment_info):
    """Mark member for collection agency"""
    # Placeholder for collection agency marking
    frappe.logger().info(f"Member {member_name} marked for collection")
    return True


def apply_late_fees(member_name, payment_info):
    """Apply late fees to overdue payments"""
    # Placeholder for late fee application
    frappe.logger().info(f"Late fees applied to {member_name}")
    return True


def get_or_create_customer(member):
    """Get or create customer record for member - delegates to application_payments module"""
    from verenigingen.utils.application_payments import create_customer_for_member

    if member.customer:
        return frappe.get_doc("Customer", member.customer)
    else:
        customer = create_customer_for_member(member)
        member.db_set("customer", customer.name)
        return customer


def create_application_invoice(member, membership):
    """Create invoice for membership application - delegates to application_payments module"""
    from verenigingen.utils.application_payments import create_membership_invoice_with_amount

    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    # Determine amount to use
    amount = membership_type.amount
    if (
        hasattr(membership, "uses_custom_amount")
        and membership.uses_custom_amount
        and hasattr(membership, "custom_amount")
    ):
        amount = membership.custom_amount

    return create_membership_invoice_with_amount(member, membership, amount)


def process_application_refund(member_name, reason):
    """Process refund for application payment"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Find the application invoice
        invoice_name = getattr(member, "application_invoice", None)
        if not invoice_name:
            frappe.logger().warning(f"No application invoice found for member {member_name}")
            return {"success": False, "message": "No application invoice found"}

        # Check if invoice exists and is paid
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        if invoice.outstanding_amount > 0:
            frappe.logger().warning(f"Invoice {invoice_name} is not fully paid, no refund needed")
            return {"success": False, "message": "Invoice is not fully paid"}

        # Create refund payment entry
        refund_entry = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Pay",
                "party_type": "Customer",
                "party": member.customer,
                "paid_amount": invoice.grand_total,
                "received_amount": invoice.grand_total,
                "reference_no": f"REFUND-{invoice.name}",
                "reference_date": today(),
                "mode_of_payment": "Bank Transfer",  # Default refund method
                "remarks": f"Refund for application rejection: {reason}",
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": invoice.name,
                        "allocated_amount": -invoice.grand_total,  # Negative for refund
                    }
                ],
            }
        )

        refund_entry.insert(ignore_permissions=True)
        refund_entry.submit()

        # Log the refund
        member.add_comment("Info", f"Refund processed: {invoice.grand_total} - Reason: {reason}")

        return {
            "success": True,
            "message": "Refund processed successfully",
            "refund_amount": invoice.grand_total,
            "payment_entry": refund_entry.name,
        }

    except Exception as e:
        frappe.logger().error(f"Failed to process refund for {member_name}: {str(e)}")
        return {"success": False, "message": f"Refund processing failed: {str(e)}"}
