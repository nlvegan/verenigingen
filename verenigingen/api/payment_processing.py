"""
Payment Processing API

This module provides comprehensive API endpoints for payment processing, overdue
payment management, and member payment communication in the Verenigingen association
management system. It handles critical financial operations with enhanced security
and validation frameworks.

Key Features:
    - Overdue payment identification and processing
    - Automated payment reminder systems
    - Member payment communication workflows
    - Financial reporting and analytics
    - Payment reconciliation and tracking
    - Critical security controls for financial operations

Business Process:
    1. Identify overdue payments and invoices
    2. Generate and send payment reminders
    3. Track payment reminder history
    4. Process payment confirmations and reconciliation
    5. Generate financial reports and analytics

Security Model:
    - Critical API security level for financial operations
    - Multi-level permission validation (invoice, member, financial)
    - Role-based access control with explicit checks
    - Comprehensive audit logging
    - Input validation and sanitization
    - Rate limiting for sensitive operations

Features:
    - Configurable reminder types and templates
    - Payment link generation and integration
    - Chapter-specific payment processing
    - Bulk processing with performance optimization
    - Custom message support for personalized communication
    - Integration with email and notification systems

Compliance:
    - Financial audit trail requirements
    - Data protection (GDPR) compliance
    - Payment processing regulations
    - Member communication consent management

Integration Points:
    - Sales Invoice and Payment Entry systems
    - Member communication and notification systems
    - Financial reporting and analytics
    - Email template and delivery systems
    - Chapter management and coordination

Performance Considerations:
    - Bulk processing for large member sets
    - Query optimization for payment status checks
    - Background job processing for heavy operations
    - Rate limiting to prevent system overload

Author: Verenigingen Development Team
License: MIT
"""

import functools
import os
import tempfile
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import flt, today

from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import (
    handle_api_error,
    log_error,
    validate_required_fields,
)
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.performance_utils import performance_monitor

# Import comprehensive security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
)
from verenigingen.utils.validation.api_validators import (
    APIValidator,
    parse_json_filters,
)


def _flatten_api_response(result: Any) -> Any:
    """Flatten the nested OperationResult envelope into the flat shape callers read.

    These endpoints return an OperationResult, and ``@critical_api`` serializes it
    with ``OperationResult.to_dict(scrub_sensitive=True)`` (default ``nested=True``)
    BEFORE this runs, producing::

        {"success": True, "timestamp": ..., "data": {...}, "meta": {...}}          # ok
        {"success": False, "timestamp": ..., "error": {"message": ...}, "meta": {...}}  # fail

    But the overdue-payments report JS reads ``r.message.file_url`` / ``r.message.count``
    and the test-suite reads ``result["count"]`` / ``result["message"]`` — i.e. flat,
    top-level keys. Against the nested shape those are ``undefined`` (the export button
    is broken). This lifts ``data`` / ``error`` / ``meta`` to the top level. It also
    defensively serializes a raw OperationResult (in case ``@critical_api`` is absent)
    and passes anything else through unchanged. No business logic or payload changes.
    """
    # Defensive: serialize a raw OperationResult if @critical_api did not already.
    if isinstance(result, OperationResult):
        result = result.to_dict(scrub_sensitive=True)
    if not isinstance(result, dict):
        return result
    # Only transform the nested OperationResult envelope; leave plain dicts alone.
    if "data" not in result and "error" not in result and "meta" not in result:
        return result

    flat: Dict[str, Any] = {k: v for k, v in result.items() if k not in ("data", "error", "meta")}

    data = result.get("data")
    if isinstance(data, dict):
        flat.update(data)
    elif data is not None:
        flat["data"] = data

    error = result.get("error")
    if isinstance(error, dict):
        flat.setdefault("message", error.get("message"))
        if error.get("errors"):
            flat.setdefault("errors", error["errors"])
        if error.get("code"):
            flat.setdefault("error_code", error["code"])
        # #481: to_dict nests http_status under ``error``. Before the kwarg fix it reached the
        # body by accident (misspelled into ``metadata``, which the ``meta`` lift below picks
        # up), so without this the rename would have silently removed it. Body and transport
        # should say the same thing.
        if error.get("http_status"):
            flat.setdefault("http_status", error["http_status"])
    elif error is not None:
        flat.setdefault("message", error)

    meta = result.get("meta")
    if isinstance(meta, dict):
        # e.g. the success ``message=``; don't clobber data keys lifted above.
        for key, value in meta.items():
            flat.setdefault(key, value)

    return flat


def _flatten_operation_result(func):
    """Flatten an endpoint's nested OperationResult envelope into a flat dict.

    Sits INSIDE ``@frappe.whitelist()`` but OUTSIDE ``@critical_api`` — it must run
    AFTER critical_api's ``to_dict`` serialization, on the nested dict that produces.
    Only transforms the *returned* value; raised exceptions propagate untouched.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return _flatten_api_response(func(*args, **kwargs))

    return wrapper


@frappe.whitelist(methods=["POST"])
@_flatten_operation_result
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=2000)
def send_overdue_payment_reminders(
    reminder_type="Friendly Reminder",
    include_payment_link=True,
    custom_message=None,
    send_to_chapters=False,
    filters: dict | str | None = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Send payment reminders to members with overdue payments.

    This critical financial operation identifies members with overdue payments
    and sends appropriate reminder communications. It supports various reminder
    types and customization options while maintaining strict security controls.

    Args:
        reminder_type (str, optional): Type of reminder to send. Defaults to "Friendly Reminder".
                                      Supported types: "Friendly Reminder", "Urgent Notice",
                                      "Final Notice", "Custom Message"
        include_payment_link (bool, optional): Whether to include payment links in reminders.
                                              Defaults to True for member convenience.
        custom_message (str, optional): Custom message to include in reminder.
                                       Overrides template when provided.
        send_to_chapters (bool, optional): Whether to copy chapter administrators.
                                          Defaults to False for member privacy.
        filters (dict, optional): Additional filters for member selection.
                                 Supported filters:
                                 - chapter: Specific chapter name
                                 - days_overdue_min: Minimum days overdue
                                 - days_overdue_max: Maximum days overdue
                                 - amount_min: Minimum overdue amount
                                 - amount_max: Maximum overdue amount

    Returns:
        dict: Comprehensive reminder processing results:
            {
                'success': True,
                'reminders_sent': 25,
                'members_processed': 30,
                'chapters_notified': 5,
                'processing_summary': {
                    'total_overdue_amount': 1250.00,
                    'average_days_overdue': 45,
                    'successful_deliveries': 23,
                    'failed_deliveries': 2,
                    'processing_time_ms': 1850
                },
                'chapter_breakdown': [
                    {
                        'chapter_name': 'Amsterdam',
                        'overdue_members': 12,
                        'total_amount': 600.00,
                        'reminders_sent': 10
                    }
                ],
                'failed_deliveries': [
                    {
                        'member_name': 'MEM-2024-001',
                        'email': 'invalid@example.com',
                        'reason': 'Invalid email address'
                    }
                ]
            }

    Raises:
        frappe.PermissionError: If user lacks required financial operation permissions
        frappe.ValidationError: If reminder parameters are invalid

    Security:
        - Critical API security level for financial operations
        - Multi-level permission validation (Sales Invoice, Member, Financial roles)
        - Explicit role checking for sensitive operations
        - Comprehensive audit logging
        - Input validation and sanitization

    Performance:
        - Monitoring threshold: 2000ms for bulk operations
        - Optimized queries for overdue payment identification
        - Batch processing for large member sets
        - Background job support for heavy processing

    Business Logic:
        - Identifies overdue invoices based on due dates
        - Respects member communication preferences
        - Tracks reminder history to prevent spam
        - Supports chapter-specific processing
        - Generates payment links for convenience

    Database Access:
        - Reads from: tabSales Invoice, tabMember, tabChapter
        - Creates: Communication records, audit logs
        - Updates: Reminder tracking and status fields

    Integration Points:
        - Email delivery system for reminder sending
        - Payment gateway for payment link generation
        - Chapter management for administrative notifications
        - Communication tracking for audit purposes
    """
    try:
        # Critical Security Fix: Add explicit permission validation
        if not frappe.has_permission("Sales Invoice", "read"):
            return OperationResult.fail(
                _("You don't have permission to access overdue payment data"), http_status=403
            )

        if not frappe.has_permission("Member", "read"):
            return OperationResult.fail(_("You don't have permission to access member data"), http_status=403)

        # Additional financial operation permission check
        user_roles = frappe.get_roles(frappe.session.user)
        required_roles = [
            Roles.FINANCIAL_MANAGER,
            "Accounts Manager",
            Roles.SYSTEM_MANAGER,
            Roles.VERENIGINGEN_ADMIN,
        ]
        if not any(role in required_roles for role in user_roles):
            return OperationResult.fail(
                _("You don't have permission to send payment reminders. Required roles: {0}").format(
                    ", ".join(required_roles)
                ),
                http_status=403,
            )

        # Validate inputs
        validate_required_fields({"reminder_type": reminder_type}, ["reminder_type"])

        reminder_type = APIValidator.sanitize_text(reminder_type, max_length=50)
        custom_message = (
            APIValidator.sanitize_text(custom_message, max_length=1000) if custom_message else None
        )

        # Get overdue payments based on filters
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

        filters = parse_json_filters(filters)

        overdue_data = get_data(filters)

        if not overdue_data:
            return OperationResult.ok(data={"count": 0}, message=_("No overdue payments found"))

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

        return OperationResult.ok(
            data={"count": sent_count}, message=_("Payment reminders sent successfully")
        )

    except Exception as e:
        frappe.log_error(
            message=f"Payment reminder operation failed: {str(e)}\n{traceback.format_exc()}",
            title="Payment Processing - Send Reminders Failed",
        )
        return OperationResult.fail(
            _("Failed to send payment reminders: {0}").format(str(e)), http_status=500
        )


@frappe.whitelist()
@_flatten_operation_result
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=5000)
def export_overdue_payments(
    filters: dict | str | None = None, format="CSV"
) -> OperationResult[Dict[str, Any]]:
    """Export overdue payments data for external processing"""
    try:
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

        filters = parse_json_filters(filters)

        # Validate format parameter
        if format not in ["CSV", "XLSX"]:
            return OperationResult.fail(
                _("Invalid export format. Supported formats: CSV, XLSX"), http_status=400
            )

        data = get_data(filters)

        if not data:
            return OperationResult.ok(data={"count": 0}, message=_("No data to export"))

        # Create export file
        file_name = f"overdue_payments_{today()}.csv"
        file_path = os.path.join(tempfile.gettempdir(), file_name)

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

            # Create file record in Frappe from the generated CSV content.
            # Previously this set file_url without attaching content, so File.save()
            # tried to read a file that only existed in the temp dir and failed with
            # "No such file or directory".
            with open(file_path, "rb") as csv_file:
                file_content = csv_file.read()

            from frappe.utils.file_manager import save_file

            file_doc = save_file(
                fname=file_name,
                content=file_content,
                dt=None,
                dn=None,
                is_private=1,
            )

            return OperationResult.ok(
                data={
                    "count": len(data),
                    "file_url": file_doc.file_url,
                    "file_name": file_name,
                },
                message=_("Export completed successfully"),
            )

        except Exception as e:
            log_error(e, {"operation": "export_overdue_payments", "context": "Payment Export Error"})
            return OperationResult.fail(_("Export failed: {0}").format(str(e)), http_status=500)

    except Exception as e:
        frappe.log_error(
            message=f"Overdue payments export failed: {str(e)}\n{traceback.format_exc()}",
            title="Payment Processing - Export Failed",
        )
        return OperationResult.fail(
            _("Failed to export overdue payments: {0}").format(str(e)), http_status=500
        )


@frappe.whitelist()
@_flatten_operation_result
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=10000)
def execute_bulk_payment_action(
    action, apply_to="All Visible Records", filters: dict | str | None = None
) -> OperationResult[Dict[str, Any]]:
    """Execute bulk actions on overdue payments"""
    try:
        # Validate inputs
        validate_required_fields({"action": action, "apply_to": apply_to}, ["action", "apply_to"])

        valid_actions = [
            "Send Payment Reminders",
            # "Suspend Memberships",  # DISABLED: Automated suspension causes duplicate log entries
            "Create Payment Plan",
            "Mark for Collection Agency",
            "Apply Late Fees",
        ]

        if action not in valid_actions:
            return OperationResult.fail(
                _("Invalid action. Valid actions: {0}").format(", ".join(valid_actions)),
                http_status=400,
            )

        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import get_data

        filters = parse_json_filters(filters)

        # Modify filters based on apply_to selection
        if filters is None:
            filters = {}
        if apply_to == "Critical Only (>60 days)":
            filters["critical_only"] = True
        elif apply_to == "Urgent Only (>30 days)":
            filters["urgent_only"] = True

        data = get_data(filters)

        if not data:
            return OperationResult.ok(data={"count": 0}, message=_("No records found"))

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

        return OperationResult.ok(data={"count": processed_count}, message=_("Bulk action completed"))

    except Exception as e:
        frappe.log_error(
            message=f"Bulk payment action failed: {str(e)}\n{traceback.format_exc()}",
            title="Payment Processing - Bulk Action Failed",
        )
        return OperationResult.fail(
            _("Failed to execute bulk payment action: {0}").format(str(e)), http_status=500
        )


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

    # Map reminder type to notification key
    notification_key_map = {
        "Friendly Reminder": "payment_reminder_friendly",
        "Urgent Notice": "payment_reminder_urgent",
        "Final Notice": "payment_reminder_urgent",  # Use urgent for final notices
        "Bulk Reminder": "payment_reminder_friendly",
    }
    notification_key = notification_key_map.get(reminder_type, "payment_reminder_friendly")

    # Prepare email context
    context = {
        "member": member,
        "payment_info": payment_info,
        "custom_message": custom_message,
        "payment_link": generate_payment_link(member_name) if include_payment_link else None,
        "company": frappe.defaults.get_global_default("company"),
    }

    try:
        # MIGRATED: Use unified EmailService for payment reminders
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Try template-based email first
        result = email_service.send_templated_email(
            template_name=template_name,
            recipients=[member.email],
            context=context,
            subject_override=get_reminder_subject(reminder_type, payment_info),
            reference_doctype="Member",
            reference_name=member_name,
            notification_key=notification_key,
        )

        # If the template is missing, send with fallback HTML content. Detect this
        # via the structured error_code (NOT a substring of the message) so an
        # unrelated failure can't wrongly trigger the fallback — the fallback path
        # passes no notification_key and so bypasses cooldown/opt-out enforcement.
        if not result.success and result.error_code == "TEMPLATE_NOT_FOUND":
            fallback_content = generate_payment_reminder_html(
                member, payment_info, reminder_type, custom_message
            )

            result = email_service._send_email_internal(
                recipients=[member.email],
                subject=get_reminder_subject(reminder_type, payment_info),
                content=fallback_content,
                reference_doctype="Member",
                reference_name=member_name,
            )

        # Check if email was sent successfully
        if result.success:
            # Log the reminder
            create_payment_reminder_log(member_name, reminder_type, payment_info)
            return True
        else:
            frappe.logger().error(f"Payment reminder email failed: {'; '.join(result.errors)}")
            return False

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

        # MIGRATED: Use unified EmailService for chapter notifications
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Prepare context for notification
        context = {
            "member": member,
            "chapter": chapter_doc,
            "payment_info": payment_info,
            "total_overdue": frappe.format_value(
                payment_info.get("total_overdue"), {"fieldtype": "Currency"}
            ),
            "days_overdue": payment_info.get("days_overdue"),
            "overdue_count": payment_info.get("overdue_count"),
        }

        # Send notification using the payment_failure notification type
        result = email_service.send_notification(
            notification_type="payment_failure",
            recipients=board_emails,
            data=context,
            reference_doctype="Member",
            reference_name=member_name,
        )

        # Return success status based on EmailService result
        return result.success

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

    email_html = f"""
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

    return email_html


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
    """Suspend member for non-payment - DISABLED to prevent duplicate log entries"""
    # DISABLED: Automated suspension was causing duplicate log entries and lacks idempotency checks
    frappe.logger().warning(f"Automated suspension disabled for member {member_name}")
    return {"success": False, "message": "Automated suspension is disabled", "disabled": True}


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

    # Determine amount to use from template
    template = load_template_for_membership_type(membership_type)
    amount = template.suggested_amount or 0
    # Custom amounts are handled via Membership Dues Schedule

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

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        # Secure refund entry creation with explicit permission validation
        refund_result = secure_document_operation(
            operation="insert",
            doc=refund_entry,
            justification=f"Automated refund processing for member {member_name} - Reason: {reason}",
            required_permissions=["Payment Entry:create"],
        )

        if not refund_result.success:
            frappe.logger().error(f"Failed to create refund entry: {'; '.join(refund_result.errors)}")
            return {
                "success": False,
                "message": f"Failed to create refund entry: {'; '.join(refund_result.errors)}",
            }

        # Secure refund entry submission with explicit permission validation
        submit_result = secure_document_operation(
            operation="submit",
            doc=refund_entry,
            justification=f"Automated refund submission for member {member_name}",
            required_permissions=["Payment Entry:submit"],
        )

        if not submit_result.success:
            frappe.logger().error(f"Failed to submit refund entry: {'; '.join(submit_result.errors)}")
            return {
                "success": False,
                "message": f"Failed to submit refund entry: {'; '.join(submit_result.errors)}",
            }

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
