"""
SEPA Batch Validation Notification System
Handles automated notifications for batch processing validation results
"""

import frappe
from frappe import _
from frappe.utils import get_url_to_form, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
)


def get_financial_admin_emails():
    """Get email addresses for financial administrators"""
    try:
        settings = frappe.get_single("Verenigingen Settings")

        # Get from settings if available
        if hasattr(settings, "financial_admin_emails") and settings.financial_admin_emails:
            return [email.strip() for email in settings.financial_admin_emails.split(",")]

        # Fallback: get users with Financial Admin roles
        financial_admins = frappe.get_all(
            "Has Role",
            filters={"role": ["in", ["System Manager", "Verenigingen Administrator", "Accounts Manager"]]},
            fields=["parent"],
        )

        if financial_admins:
            emails = []
            for admin in financial_admins:
                user_email = frappe.db.get_value("User", admin.parent, "email")
                if user_email:
                    emails.append(user_email)
            return emails

        # Final fallback: Administrator
        return [frappe.db.get_value("User", "Administrator", "email") or "admin@example.com"]

    except Exception as e:
        frappe.log_error(f"Error getting financial admin emails: {str(e)}", "Notification System")
        return ["admin@example.com"]


def send_critical_batch_notification(batch, errors):
    """Send urgent notification for blocked batches"""
    try:
        recipients = get_financial_admin_emails()

        subject = f"🚨 URGENT: SEPA Batch {batch.name} Blocked - Manual Intervention Required"

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Format error details for template
        error_details = []
        for error in errors:
            error_details.append(
                f"Invoice {error['invoice']}: {error['issue']} (Expected: {error.get('expected', 'N/A')}, Actual: {error.get('actual', 'N/A')})"
            )

        context = {
            "member_name": "Financial Administrator",
            "notification_message": f"SEPA batch processing has been automatically blocked due to {len(errors)} critical sequence type errors that violate SEPA compliance requirements.",
            "payment_reference": batch.name,
            "amount": f"€{batch.total_amount:,.2f}",
            "payment_date": str(batch.batch_date),
            "payment_method": "SEPA Direct Debit",
            "action_required": f"Review and correct sequence types in batch {batch.name}. Critical errors: {'; '.join(error_details[:3])}{'...' if len(error_details) > 3 else ''}",
            "next_steps": "Re-run batch creation after corrections. Monitor submission deadlines: FRST transactions must be submitted 5 business days before target date, RCUR transactions must be submitted 2 business days before target date.",
            "company": frappe.defaults.get_global_default("company") or "Verenigingen",
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype="Direct Debit Batch",
            reference_name=batch.name,
            priority="high",
        )

        frappe.logger().info(
            f"Critical batch notification sent for {batch.name} to {len(recipients)} recipients"
        )

    except Exception as e:
        frappe.log_error(
            f"Error sending critical batch notification for {batch.name}: {str(e)}", "Notification System"
        )


def send_batch_warning_notification(batch, warnings):
    """Send informational notification for processed batches with warnings"""
    try:
        recipients = get_financial_admin_emails()

        subject = f"ℹ️ SEPA Batch {batch.name} Processed with Warnings"

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Format warning details for template
        warning_details = []
        for warning in warnings:
            warning_details.append(
                f"Invoice {warning['invoice']}: {warning['issue']} (Expected: {warning.get('expected', 'N/A')}, Actual: {warning.get('actual', 'N/A')})"
            )

        context = {
            "member_name": "Financial Administrator",
            "notification_message": f"SEPA batch has been processed successfully but contains {len(warnings)} sequence type warnings that should be reviewed when convenient.",
            "payment_reference": batch.name,
            "amount": f"€{batch.total_amount:,.2f}",
            "payment_date": str(batch.batch_date),
            "payment_method": "SEPA Direct Debit",
            "next_steps": f"The batch can be submitted as-is, but please review these warnings: {'; '.join(warning_details[:3])}{'...' if len(warning_details) > 3 else ''}",
            "company": frappe.defaults.get_global_default("company") or "Verenigingen",
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype="Direct Debit Batch",
            reference_name=batch.name,
        )

        frappe.logger().info(
            f"Warning batch notification sent for {batch.name} to {len(recipients)} recipients"
        )

    except Exception as e:
        frappe.log_error(
            f"Error sending warning batch notification for {batch.name}: {str(e)}", "Notification System"
        )


def send_daily_batch_summary(validation_summary, batch_result):
    """Send daily summary of batch processing results"""
    try:
        recipients = get_financial_admin_emails()

        total_batches = sum(validation_summary.values())
        if total_batches == 0:
            return  # No batches to report

        subject = f"📊 Daily SEPA Batch Summary - {today()}"

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        status_summary = f"Successfully Processed: {validation_summary.get('processed', 0)} batches, With Warnings: {validation_summary.get('processed_with_warnings', 0)} batches, Blocked: {validation_summary.get('blocked', 0)} batches"

        context = {
            "member_name": "Financial Administrator",
            "notification_message": f"Daily SEPA batch processing summary for {today()}. Total batches: {total_batches}",
            "payment_reference": f"Daily Summary {today()}",
            "amount": f"{batch_result.get('total_invoices', 0)} invoices processed",
            "payment_date": today(),
            "payment_method": "SEPA Batch Processing",
            "next_steps": f"Processing Results: {status_summary}. Batches Created: {batch_result.get('batches_created', 0)}. Success Rate: {((validation_summary.get('processed', 0) + validation_summary.get('processed_with_warnings', 0)) / total_batches * 100):.1f}%",
            "action_required": (
                f"{validation_summary.get('blocked', 0)} batch(es) require manual intervention"
                if validation_summary.get("blocked", 0) > 0
                else None
            ),
            "company": frappe.defaults.get_global_default("company") or "Verenigingen",
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
        )

        frappe.logger().info(f"Daily batch summary sent to {len(recipients)} recipients")

    except Exception as e:
        frappe.log_error(f"Error sending daily batch summary: {str(e)}", "Notification System")


def send_system_error_notification(error_message):
    """Send notification for system-level errors"""
    try:
        recipients = get_financial_admin_emails()

        subject = f"🔥 CRITICAL: SEPA Batch System Error - {today()}"

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "member_name": "System Administrator",
            "notification_message": "The automated SEPA batch processing system has encountered a critical error that prevented batch creation.",
            "payment_reference": f"System Error {today()}",
            "amount": "N/A",
            "payment_date": str(frappe.utils.now()),
            "payment_method": "SEPA System",
            "action_required": f"Critical system error: {error_message[:200]}{'...' if len(error_message) > 200 else ''}",
            "next_steps": "Check system logs for detailed error information. Verify SEPA system configuration and dependencies. Run manual batch creation if needed. Contact system administrator if error persists.",
            "company": frappe.defaults.get_global_default("company") or "Verenigingen",
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
            priority="high",
        )

        frappe.logger().error(f"System error notification sent: {error_message}")

    except Exception as e:
        frappe.log_error(f"Error sending system error notification: {str(e)}", "Notification System")


def get_batch_url(batch_name):
    """Get URL to batch document"""
    try:
        return get_url_to_form("Direct Debit Batch", batch_name)
    except Exception:
        return f"{frappe.utils.get_url()}/app/direct-debit-batch/{batch_name}"


def handle_automated_batch_validation(batch, critical_errors, warnings):
    """Handle validation results in automated context"""
    try:
        if critical_errors:
            # BLOCK: Critical SEPA compliance issues
            batch.db_set("status", "Validation Failed")
            batch.add_comment(
                "System",
                f"Automated processing blocked: {len(critical_errors)} critical sequence type errors",
            )

            # Send urgent notification
            send_critical_batch_notification(batch, critical_errors)
            return {"action": "blocked", "requires_intervention": True}

        elif warnings:
            # PROCEED WITH WARNING: Minor issues, but notify
            batch.add_comment(
                "System", f"Processed with {len(warnings)} sequence type warnings - review recommended"
            )

            # Send informational notification
            send_batch_warning_notification(batch, warnings)
            return {"action": "processed_with_warnings", "requires_intervention": False}

        else:
            # PROCEED: No issues
            batch.add_comment("System", "Sequence type validation passed - no issues found")
            return {"action": "processed", "requires_intervention": False}

    except Exception as e:
        frappe.log_error(
            f"Error handling automated batch validation for {batch.name}: {str(e)}",
            "Batch Validation Handler",
        )
        return {"action": "error", "requires_intervention": True}


@standard_api(operation_type=OperationType.FINANCIAL)
@require_sepa_permission(SEPAPermissionLevel.ADMIN, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def test_notification_system():
    """Test the notification system - for development/testing only"""
    try:
        # Test email configuration
        recipients = get_financial_admin_emails()

        subject = "🧪 SEPA Notification System Test"

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "member_name": "System Administrator",
            "notification_message": "This is a test message to verify the SEPA batch notification system is working correctly.",
            "payment_reference": f"Test {frappe.utils.now()}",
            "amount": "N/A",
            "payment_date": str(frappe.utils.now()),
            "payment_method": "SEPA Notification Test",
            "next_steps": f"System Information: Site: {frappe.local.site}, Recipients Found: {len(recipients)}. If you receive this message, the notification system is configured correctly.",
            "company": frappe.defaults.get_global_default("company") or "Verenigingen",
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype=None,
            reference_name=None,
        )

        return {
            "success": True,
            "message": f"Test notification sent to {len(recipients)} recipients",
            "recipients": recipients,
        }

    except Exception as e:
        frappe.log_error(f"Error testing notification system: {str(e)}", "Notification System")
        return {"success": False, "error": str(e)}
