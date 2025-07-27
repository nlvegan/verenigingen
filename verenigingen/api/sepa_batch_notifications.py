"""
SEPA Batch Validation Notification System
Handles automated notifications for batch processing validation results
"""

import frappe
from frappe import _
from frappe.utils import get_url_to_form, today

from verenigingen.utils.security.api_security_framework import high_security_api, standard_api
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

        body = f"""
<h2 style="color: #d32f2f;">SEPA Batch Processing Blocked</h2>

<p>SEPA batch processing has been automatically blocked due to critical sequence type errors that violate SEPA compliance requirements.</p>

<h3>Batch Information:</h3>
<ul>
<li><strong>Batch:</strong> {batch.name}</li>
<li><strong>Target Date:</strong> {batch.batch_date}</li>
<li><strong>Total Amount:</strong> €{batch.total_amount:,.2f}</li>
<li><strong>Entry Count:</strong> {batch.entry_count}</li>
<li><strong>Status:</strong> {batch.validation_status}</li>
</ul>

<h3>Critical Errors ({len(errors)}):</h3>
<ul>
"""

        for error in errors:
            body += f"""<li><strong>Invoice {error['invoice']}:</strong> {error['issue']}<br>
                       <em>Expected: {error.get('expected', 'N/A')}, Actual: {error.get('actual', 'N/A')}</em>
                       {f"<br><small>{error.get('reason', '')}</small>" if error.get('reason') else ""}
                       </li>"""

        body += f"""
</ul>

<h3>Required Actions:</h3>
<ol>
<li>Review and correct sequence types in batch <a href="{get_batch_url(batch.name)}">{batch.name}</a></li>
<li>Re-run batch creation after corrections</li>
<li>Monitor submission deadlines:
   <ul>
   <li><strong>FRST transactions:</strong> Must be submitted 5 business days before target date</li>
   <li><strong>RCUR transactions:</strong> Must be submitted 2 business days before target date</li>
   </ul>
</li>
</ol>

<p><em>This is an automated message from the SEPA batch processing system. Please address these issues promptly to avoid payment delays.</em></p>
"""

        frappe.sendmail(recipients=recipients, subject=subject, message=body, priority="high")

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

        body = f"""
<h2 style="color: #f57c00;">SEPA Batch Processed with Warnings</h2>

<p>SEPA batch has been processed successfully but contains sequence type warnings that should be reviewed when convenient.</p>

<h3>Batch Information:</h3>
<ul>
<li><strong>Batch:</strong> {batch.name}</li>
<li><strong>Status:</strong> Ready for submission</li>
<li><strong>Target Date:</strong> {batch.batch_date}</li>
<li><strong>Total Amount:</strong> €{batch.total_amount:,.2f}</li>
<li><strong>Entry Count:</strong> {batch.entry_count}</li>
</ul>

<h3>Warnings ({len(warnings)}):</h3>
<ul>
"""

        for warning in warnings:
            body += f"""<li><strong>Invoice {warning['invoice']}:</strong> {warning['issue']}<br>
                       <em>Expected: {warning.get('expected', 'N/A')}, Actual: {warning.get('actual', 'N/A')}</em>
                       {f"<br><small>{warning.get('reason', '')}</small>" if warning.get('reason') else ""}
                       </li>"""

        body += f"""
</ul>

<p>The batch can be submitted as-is, but please review these items when convenient.</p>

<p><strong>Batch Location:</strong> <a href="{get_batch_url(batch.name)}">{batch.name}</a></p>

<p><em>This is an automated message from the SEPA batch processing system.</em></p>
"""

        frappe.sendmail(recipients=recipients, subject=subject, message=body)

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

        body = f"""
<h2>Daily SEPA Batch Processing Summary</h2>

<p><strong>Date:</strong> {today()}</p>

<h3>Processing Results:</h3>
<ul>
<li><strong>Successfully Processed:</strong> {validation_summary.get('processed', 0)} batches</li>
<li><strong>Processed with Warnings:</strong> {validation_summary.get('processed_with_warnings', 0)} batches</li>
<li><strong>Blocked (Critical Errors):</strong> {validation_summary.get('blocked', 0)} batches</li>
</ul>

<h3>Total Statistics:</h3>
<ul>
<li><strong>Batches Created:</strong> {batch_result.get('batches_created', 0)}</li>
<li><strong>Total Invoices:</strong> {batch_result.get('total_invoices', 0)}</li>
<li><strong>Success Rate:</strong> {((validation_summary.get('processed', 0) + validation_summary.get('processed_with_warnings', 0)) / total_batches * 100):.1f}%</li>
</ul>
"""

        if validation_summary.get("blocked", 0) > 0:
            body += f"""
<div style="background-color: #ffebee; padding: 10px; border-left: 4px solid #d32f2f; margin: 10px 0;">
<strong>⚠️ Attention Required:</strong> {validation_summary['blocked']} batch(es) were blocked due to critical errors and require manual intervention.
</div>
"""

        body += "<p><em>This is an automated daily summary from the SEPA batch processing system.</em></p>"

        frappe.sendmail(recipients=recipients, subject=subject, message=body)

        frappe.logger().info(f"Daily batch summary sent to {len(recipients)} recipients")

    except Exception as e:
        frappe.log_error(f"Error sending daily batch summary: {str(e)}", "Notification System")


def send_system_error_notification(error_message):
    """Send notification for system-level errors"""
    try:
        recipients = get_financial_admin_emails()

        subject = f"🔥 CRITICAL: SEPA Batch System Error - {today()}"

        body = f"""
<h2 style="color: #d32f2f;">Critical SEPA System Error</h2>

<p>The automated SEPA batch processing system has encountered a critical error that prevented batch creation.</p>

<h3>Error Details:</h3>
<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 4px;">{error_message}</pre>

<h3>Required Actions:</h3>
<ol>
<li>Check system logs for detailed error information</li>
<li>Verify SEPA system configuration and dependencies</li>
<li>Run manual batch creation if needed</li>
<li>Contact system administrator if error persists</li>
</ol>

<p><strong>Date/Time:</strong> {frappe.utils.now()}</p>

<p><em>This is an automated error notification from the SEPA batch processing system.</em></p>
"""

        frappe.sendmail(recipients=recipients, subject=subject, message=body, priority="high")

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


@standard_api
@require_sepa_permission(SEPAPermissionLevel.ADMIN, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def test_notification_system():
    """Test the notification system - for development/testing only"""
    try:
        # Test email configuration
        recipients = get_financial_admin_emails()

        subject = "🧪 SEPA Notification System Test"
        body = f"""
<h2>SEPA Notification System Test</h2>

<p>This is a test message to verify the SEPA batch notification system is working correctly.</p>

<h3>System Information:</h3>
<ul>
<li><strong>Site:</strong> {frappe.local.site}</li>
<li><strong>Time:</strong> {frappe.utils.now()}</li>
<li><strong>Recipients Found:</strong> {len(recipients)}</li>
</ul>

<p>If you receive this message, the notification system is configured correctly.</p>
"""

        frappe.sendmail(recipients=recipients, subject=subject, message=body)

        return {
            "success": True,
            "message": f"Test notification sent to {len(recipients)} recipients",
            "recipients": recipients,
        }

    except Exception as e:
        frappe.log_error(f"Error testing notification system: {str(e)}", "Notification System")
        return {"success": False, "error": str(e)}
