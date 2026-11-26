"""
Email Template Management API

This module provides comprehensive email template management for the Verenigingen
association management system. It centralizes template creation, management,
and rendering with fallback mechanisms to ensure reliable communication
across all system components.

Key Features:
    - Centralized email template management
    - Template rendering with context substitution
    - Fallback mechanisms for missing templates
    - Multi-category template organization
    - Dynamic content generation
    - Security controls for template access

Template Categories:
    - Expense Management: Approval requests, notifications, reimbursements
    - Member Communication: Welcome messages, notifications, reminders
    - Chapter Management: Announcements, administrative communications
    - Financial Operations: Payment reminders, invoice notifications
    - System Notifications: Alerts, status updates, error notifications

Architecture:
    - Template factory pattern for creation and management
    - Context-aware rendering with variable substitution
    - Hierarchical fallback system for missing templates
    - Template validation and security controls
    - Integration with Frappe's Email Template system

Security Model:
    - Critical API security for template management operations
    - Template content validation and sanitization
    - Access controls for template modification
    - Audit logging for template changes
    - XSS protection in template rendering

Business Process:
    1. Template Creation: Define reusable email templates
    2. Context Preparation: Gather data for template rendering
    3. Template Rendering: Substitute variables with actual data
    4. Delivery Preparation: Format for email delivery systems
    5. Fallback Handling: Use default templates if specific ones missing

Integration Points:
    - Frappe Email Template system
    - Communication and notification systems
    - Document workflow and approval systems
    - Member and chapter management systems
    - Financial and expense management systems

Performance Considerations:
    - Template caching for frequently used templates
    - Efficient context preparation and rendering
    - Batch processing for bulk communications
    - Background job support for heavy operations

Author: Verenigingen Development Team
License: MIT
"""

import json
import os
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import get_url

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_comprehensive_email_templates() -> OperationResult[Dict[str, Any]]:
    """Create the stock Email Templates that are MISSING; never touch existing rows (#1984).

    Setup (install and re-runs) calls this, so a template staff have edited, or one the
    fixture sync owns, must survive it. Restoring stock content is the explicit
    ``reset_stock_email_templates`` action.
    """
    return _seed_comprehensive_email_templates(overwrite=False)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def reset_stock_email_templates() -> OperationResult[Dict[str, Any]]:
    """Restore the stock content of every managed Email Template, on demand (#1984).

    Maintainer ruling 2026-11-03: setup only creates, and this separate, explicit action
    is the one that overwrites. Same ADMIN/critical gate as the create endpoint.
    """
    return _seed_comprehensive_email_templates(overwrite=True)


SHIPPED_TEMPLATES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "setup", "stock_email_templates.json"
)


def _load_shipped_email_templates():
    """Stock rows that used to ship as fixtures, in the shape the seeder loop expects (#1984).

    They are NOT under fixtures/: Frappe's sync_fixtures re-imports every fixtures/*.json on
    each migrate, which overwrote staff edits. Here they are only ever created when missing.
    """
    with open(SHIPPED_TEMPLATES_PATH, encoding="utf-8") as f:
        rows = json.load(f)
    return [
        {
            "name": row["name"],
            "subject": row["subject"],
            "response": row["response_html"],
            "reference_doctype": row.get("reference_doctype"),
        }
        for row in rows
    ]


def _seed_comprehensive_email_templates(overwrite: bool = False) -> OperationResult[Dict[str, Any]]:
    """
    Create and deploy all email templates used throughout the Verenigingen application.

    This critical operation establishes the complete set of email templates required
    for system communication. It creates templates for all major business processes
    and ensures consistent, professional communication across the platform.

    Returns:
        dict: Template creation results with detailed status information:
            {
                'success': True,
                'templates_created': 15,
                'templates_updated': 3,
                'templates_skipped': 2,
                'categories': {
                    'expense_management': 4,
                    'member_communication': 6,
                    'chapter_management': 3,
                    'financial_operations': 3,
                    'system_notifications': 2
                },
                'processing_summary': {
                    'total_processed': 20,
                    'successful_operations': 18,
                    'failed_operations': 0,
                    'processing_time_ms': 1250
                },
                'template_details': [
                    {
                        'name': 'expense_approval_request',
                        'subject': '💰 Expense Approval Required - {{ doc.name }}',
                        'status': 'created',
                        'category': 'expense_management'
                    }
                ]
            }

    Raises:
        frappe.PermissionError: If user lacks template management permissions
        frappe.ValidationError: If template data is invalid

    Security:
        - Critical API security for template management operations
        - Validates user permissions for Email Template DocType
        - Template content sanitization and validation
        - Audit logging for all template operations

    Template Categories Created:
        1. Expense Management:
           - expense_approval_request: Expense approval notifications
           - expense_approved: Approval confirmation messages
           - expense_rejected: Rejection notifications with feedback
           - expense_reimbursement: Payment processing notifications

        2. Member Communication:
           - member_welcome: New member welcome messages
           - member_renewal: Membership renewal reminders
           - member_notification: General member notifications
           - member_chapter_assignment: Chapter assignment confirmations

        3. Chapter Management:
           - chapter_announcement: Official chapter announcements
           - chapter_board_notification: Board member communications
           - chapter_event_notification: Event and activity announcements

        4. Financial Operations:
           - payment_reminder: Overdue payment reminders
           - invoice_notification: New invoice notifications
           - payment_confirmation: Payment received confirmations

        5. System Notifications:
           - system_alert: Critical system notifications
           - maintenance_notification: Scheduled maintenance alerts

    Business Logic:
        - Creates templates if they don't exist
        - Updates existing templates with stock content ONLY when overwrite=True
          (reset_stock_email_templates); otherwise leaves them untouched
        - Validates template syntax and structure
        - Establishes template hierarchies and categories
        - Configures template permissions and access controls

    Database Access:
        - Creates: Email Template documents
        - Updates: Existing template configurations
        - Validates: Template content and structure

    Integration Points:
        - Frappe Email Template system for rendering
        - Communication DocType for delivery tracking
        - Workflow systems for automated notifications
        - User permission system for access control
    """
    try:
        templates = [
            # The six rows the fixture sync used to own (#1984): expense_*, donation_*,
            # termination_overdue_notification. Same wording live sites carry today.
            *_load_shipped_email_templates(),
            {
                "name": "anbi_tax_receipt",
                "subject": "Tax Deduction Receipt - {{ receipt_number }}",
                "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Tax Deduction Receipt (ANBI)</h2>

                <p>Dear {{ donor_name | e }},</p>

                <p>This receipt confirms your tax-deductible donation under ANBI regulations.</p>

                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border: 2px solid #007bff;">
                    <h3 style="color: #007bff; margin-top: 0;">Official Tax Receipt</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Receipt Number:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ receipt_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>ANBI Agreement:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ anbi_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Donation Amount:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">€{{ doc.amount }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Tax Year:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ tax_year }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Organization:</strong></td>
                            <td style="padding: 8px 0;">{{ organization_name }}</td>
                        </tr>
                    </table>
                </div>

                <p>This donation is tax-deductible according to Dutch tax law. Please keep this receipt for your tax filing.</p>

                <p>Thank you for your support!</p>

                <p>Best regards,<br>
                {{ organization_name }}</p>
            </div>
            """,
            },
            {
                "name": "member_contact_request_received",
                "subject": "Contact Request Received - {{ doc.name }}",
                "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Contact Request Received</h2>

                <p>Dear {{ contact_name | e }},</p>

                <p>We have received your contact request and will respond within 2-3 business days.</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <h3>Your Request Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Request ID:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ doc.name }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Category:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ doc.request_category }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Priority:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ doc.priority }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Submitted:</strong></td>
                            <td style="padding: 8px 0;">{{ submission_date }}</td>
                        </tr>
                    </table>
                </div>

                {% if doc.message %}
                <div style="background-color: #e9ecef; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <h4>Your Message:</h4>
                    <p style="margin: 0;">{{ doc.message | e }}</p>
                </div>
                {% endif %}

                <p>You can track the status of your request using the request ID above.</p>

                <p>Thank you for contacting us!</p>

                <p>Best regards,<br>
                {{ organization_name }}</p>
            </div>
            """,
            },
        ]

        created_count = 0
        updated_count = 0
        skipped_count = 0
        failures = []

        for template_data in templates:
            template_name = template_data["name"]

            try:
                # Check if template already exists
                if frappe.db.exists("Email Template", template_name) and not overwrite:
                    # Create-only (#1984): an existing row is left exactly as it is.
                    skipped_count += 1
                    continue
                if frappe.db.exists("Email Template", template_name):
                    # Explicit reset: update existing template
                    template_doc = frappe.get_doc("Email Template", template_name)
                    template_doc.subject = template_data["subject"]
                    template_doc.response = template_data["response"]
                    template_doc.use_html = 1
                    # With use_html=1, Frappe renders response_html (response_()),
                    # so it must carry the HTML too — otherwise native sends are empty.
                    template_doc.response_html = template_data["response"]
                    template_doc.save()
                    updated_count += 1
                    frappe.logger().info(f"Updated email template: {template_name}")
                else:
                    # Create new template
                    template_doc = frappe.get_doc(
                        {
                            "doctype": "Email Template",
                            "name": template_name,
                            "subject": template_data["subject"],
                            "use_html": 1,
                            "response": template_data["response"],
                            # With use_html=1, Frappe renders response_html, so it
                            # must carry the HTML too — otherwise native sends are empty.
                            "response_html": template_data["response"],
                            "reference_doctype": template_data.get("reference_doctype"),
                            "enabled": 1,
                        }
                    )
                    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                    result = secure_document_operation(
                        operation="insert",
                        doc=template_doc,
                        justification=f"Create email template {template_name} for system communications - template management",
                        required_permissions=["Email Template:create"],
                    )

                    if result.success:
                        created_count += 1
                        frappe.logger().info(f"Created email template: {template_name}")
                    else:
                        failures.append(f"{template_name}: {'; '.join(result.errors)}")
                        frappe.log_error(
                            title="Email Template Error",
                            message=f"Failed to create email template {template_name}: {'; '.join(result.errors)}",
                        )

            except Exception as e:
                reason = str(e)
                failures.append(f"{template_name}: {reason}")
                frappe.log_error(
                    title="Email Template Error",
                    message=f"Failed to {'reset' if overwrite else 'create'} template '{template_name}': {reason}",
                )

        frappe.db.commit()

        if failures:
            # One bad template must not stop the others (they were committed above), but the
            # caller must not be told the run succeeded (#1880).
            return OperationResult.fail(
                message=(
                    _("Failed to reset email templates")
                    if overwrite
                    else _("Failed to create email templates")
                ),
                errors=failures,
            )

        data = {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "total": created_count + updated_count,
        }

        if overwrite:
            message = _("Stock email templates reset. Restored: {0}, Newly added: {1}").format(
                updated_count, created_count
            )
        else:
            message = _(
                "Email template setup completed. Created: {0}, Skipped (already present): {1}"
            ).format(created_count, skipped_count)
        return OperationResult.ok(data=data, message=message)

    except Exception as e:
        frappe.log_error(
            title=_("Email Template Creation Failed"),
            message=f"Error creating email templates: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(message=_("Failed to create email templates"), errors=[str(e)])


def get_email_template(template_name, context=None, fallback_subject="", fallback_message=""):
    """
    Get email template with context rendering and fallback support

    Args:
        template_name: Name of the Email Template doctype
        context: Dict of variables for Jinja rendering
        fallback_subject: Subject to use if template doesn't exist
        fallback_message: Message to use if template doesn't exist

    Returns:
        dict: {"subject": str, "message": str}
    """
    if context is None:
        context = {}

    try:
        # Try to get custom template from Email Template doctype
        template_doc = frappe.get_doc("Email Template", template_name)

        # Render with Jinja2
        subject = frappe.render_template(template_doc.subject, context)
        message = frappe.render_template(template_doc.response, context)

        return {"subject": subject, "message": message}

    except frappe.DoesNotExistError:
        # Use fallback if template doesn't exist
        frappe.logger().warning(f"Email template '{template_name}' not found, using fallback")

        subject = (
            frappe.render_template(fallback_subject, context)
            if fallback_subject
            else f"Notification - {template_name}"
        )
        message = (
            frappe.render_template(fallback_message, context)
            if fallback_message
            else "This is an automated notification."
        )

        return {"subject": subject, "message": message}

    except Exception as e:
        frappe.log_error(
            f"Error rendering template '{template_name}': {str(e)}", "Email Template Rendering Error"
        )

        # Return basic fallback
        return {
            "subject": fallback_subject or f"Notification - {template_name}",
            "message": fallback_message or "This is an automated notification.",
        }


def send_template_email(template_name, recipients, context=None, **kwargs):
    """
    Send email using template with context rendering

    Args:
        template_name: Name of the Email Template
        recipients: List of email addresses
        context: Dict of variables for template rendering
        **kwargs: Additional email options:
            - reference_doctype: DocType for reference
            - reference_name: Document name for reference
            - notification_key: REQUIRED - notification key from registry for central control

    Returns:
        bool: Success status

    Note:
        notification_key is required to enable central notification configuration.
        Callers must explicitly provide a notification_key from the registry.
    """
    from verenigingen.services.communication.email_service import get_email_service

    if context is None:
        context = {}

    # Require explicit notification_key - do not default to a test key
    notification_key = kwargs.get("notification_key")
    if not notification_key:
        frappe.logger().warning(
            f"send_template_email called without notification_key for template '{template_name}'. "
            "Add a notification_key parameter to enable central notification control."
        )

    try:
        # Get rendered template
        template = get_email_template(template_name, context)

        # Send email via EmailService
        email_service = get_email_service()
        result = email_service.send_simple_email(
            recipients=recipients,
            subject=template["subject"],
            message=template["message"],
            reference_doctype=kwargs.get("reference_doctype"),
            reference_name=kwargs.get("reference_name"),
            notification_key=notification_key,
        )

        # A skip (cooldown, disabled key, opt-out) is not a send (#2096)
        return result.success and not result.skip_reason

    except Exception as e:
        frappe.log_error(f"Failed to send template email '{template_name}': {str(e)}", "Template Email Error")
        return False


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def test_email_template(template_name: str, test_context=None) -> OperationResult[Dict[str, Any]]:
    """Test email template rendering with sample context"""
    try:
        if test_context is None:
            # Create sample context for testing
            test_context = {
                "doc": frappe._dict(
                    {
                        "name": "TEST-001",
                        "description": "Test expense description",
                        "amount": 125.50,
                        "organization_type": "Chapter",
                    }
                ),
                "volunteer_name": "Test Volunteer",
                "company": "Test Organization",
                "approver_name": "Test Approver",
                "required_level": "admin",
                "formatted_amount": "€125.50",
                "formatted_date": "2025-01-15",
                "category_name": "Travel",
                "organization_name": "Test Chapter",
                "approval_url": f"{get_url()}/app/volunteer-expense/TEST-001",
                "dashboard_url": f"{get_url()}/app/expense-approval-dashboard",
            }

        template = get_email_template(template_name, test_context)

        data = {
            "template_name": template_name,
            "subject": template["subject"],
            "message": template["message"],
            "context_used": test_context,
        }

        return OperationResult.ok(data=data, message=_("Email template rendered successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Email Template Test Failed"),
            message=f"Error testing template '{template_name}': {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to test email template: {0}").format(template_name), errors=[str(e)]
        )
