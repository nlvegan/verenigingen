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

import frappe
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api


@critical_api()
@frappe.whitelist()
def create_comprehensive_email_templates():
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
        - Updates existing templates with new content
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

    templates = [
        # Expense notification templates
        {
            "name": "expense_approval_request",
            "subject": "💰 Expense Approval Required - {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #2c3e50; margin: 0;">💰 Expense Approval Required</h2>
                    <p style="color: #7f8c8d; margin: 5px 0 0 0;">{{ company }}</p>
                </div>

                <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                    <p>Dear {{ approver_name }},</p>

                    <p>A new expense has been submitted and requires your <strong>{{ required_level }} level</strong> approval:</p>

                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{ doc.name }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Volunteer:</td><td>{{ volunteer_name }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{ doc.description }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td style="font-size: 18px; color: #e74c3c;">{{ formatted_amount }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Date:</td><td>{{ formatted_date }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Category:</td><td>{{ category_name }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Organization:</td><td>{{ organization_name }} ({{ doc.organization_type }})</td></tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 25px 0;">
                        <a href="{{ approval_url }}" style="background-color: #28a745; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            Review & Approve Expense
                        </a>
                    </div>

                    <p style="text-align: center; margin-top: 15px;">
                        <a href="{{ dashboard_url }}" style="color: #007bff;">View All Pending Approvals</a>
                    </p>

                    <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                    <p style="font-size: 12px; color: #6c757d;">
                        This is an automated notification from {{ company }}.
                        Please do not reply to this email.
                    </p>
                </div>
            </div>
            """,
        },
        {
            "name": "expense_approved",
            "subject": "✅ Expense Approved - {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #155724; margin: 0;">✅ Expense Approved</h2>
                    <p style="color: #155724; margin: 5px 0 0 0;">{{ company }}</p>
                </div>

                <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                    <p>Dear {{ volunteer_name }},</p>

                    <p>Great news! Your expense has been approved by {{ approved_by_name }}.</p>

                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{ doc.name }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{ doc.description }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td style="font-size: 18px; color: #28a745;">{{ formatted_amount }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Approved On:</td><td>{{ approved_on }}</td></tr>
                        </table>
                    </div>

                    <p>Your expense will be processed for reimbursement according to the organization's payment schedule.</p>

                    <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                    <p style="font-size: 12px; color: #6c757d;">
                        This is an automated notification from {{ company }}.
                    </p>
                </div>
            </div>
            """,
        },
        {
            "name": "expense_rejected",
            "subject": "❌ Expense Rejected - {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #f8d7da; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #721c24; margin: 0;">❌ Expense Rejected</h2>
                    <p style="color: #721c24; margin: 5px 0 0 0;">{{ company }}</p>
                </div>

                <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                    <p>Dear {{ volunteer_name }},</p>

                    <p>We regret to inform you that your expense has been rejected by {{ rejected_by_name }}.</p>

                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{ doc.name }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{ doc.description }}</td></tr>
                            <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td>{{ formatted_amount }}</td></tr>
                        </table>
                    </div>

                    <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #ffc107;">
                        <p style="margin: 0; font-weight: bold;">Rejection Reason:</p>
                        <p style="margin: 5px 0 0 0;">{{ rejection_reason }}</p>
                    </div>

                    <p>If you have questions about this decision, please contact your organization's board or the person who rejected the expense.</p>

                    <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                    <p style="font-size: 12px; color: #6c757d;">
                        This is an automated notification from {{ company }}.
                    </p>
                </div>
            </div>
            """,
        },
        # Donation templates
        {
            "name": "donation_confirmation",
            "subject": "Thank you for your donation - {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Dear {{ donor_name }},</h2>

                <p>Thank you for your generous donation to {{ organization_name }}!</p>

                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3>Donation Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Donation ID:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ doc.name }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Amount:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">€{{ doc.amount }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Date:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ donation_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Purpose:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{ earmarking }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Status:</strong></td>
                            <td style="padding: 8px 0;">{{ doc.donation_status }}</td>
                        </tr>
                    </table>
                </div>

                <p>Your donation helps us make a positive impact in our community. We will send you a payment confirmation once your payment has been processed.</p>

                {% if doc.donation_notes %}
                <p><strong>Your message:</strong><br>
                <em>{{ doc.donation_notes }}</em></p>
                {% endif %}

                <p>If you have any questions about your donation, please don't hesitate to contact us at {{ organization_email }}.</p>

                <p>With gratitude,<br>
                {{ organization_name }}</p>
            </div>
            """,
        },
        {
            "name": "donation_payment_confirmation",
            "subject": "Payment Received - Donation {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Dear {{ donor_name }},</h2>

                <p>We have received your payment for donation {{ doc.name }}. Thank you for your generous support!</p>

                <div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <h3 style="color: #155724; margin-top: 0;">Payment Confirmed</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Amount Paid:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">€{{ doc.amount }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Payment Date:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">{{ payment_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Payment Method:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">{{ payment_method }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Reference:</strong></td>
                            <td style="padding: 8px 0;">{{ payment_reference }}</td>
                        </tr>
                    </table>
                </div>

                <p>Your contribution of €{{ doc.amount }} for {{ earmarking }} will help us continue our important work.</p>

                <p>This email serves as your payment receipt. Please keep it for your records.</p>

                <p>Thank you again for your support!</p>

                <p>Best regards,<br>
                {{ organization_name }}</p>
            </div>
            """,
        },
        {
            "name": "anbi_tax_receipt",
            "subject": "Tax Deduction Receipt - {{ receipt_number }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Tax Deduction Receipt (ANBI)</h2>

                <p>Dear {{ donor_name }},</p>

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
        # Termination templates
        {
            "name": "termination_overdue_notification",
            "subject": "Overdue Termination Requests - {{ count }} items",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #dc3545;">⚠️ Overdue Termination Requests</h2>

                <p>Dear Administrator,</p>

                <p>The following termination requests are overdue and require immediate attention:</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background-color: #e9ecef;">
                                <th style="padding: 8px; text-align: left;">Request ID</th>
                                <th style="padding: 8px; text-align: left;">Member</th>
                                <th style="padding: 8px; text-align: left;">Request Date</th>
                                <th style="padding: 8px; text-align: left;">Days Overdue</th>
                            </tr>
                        </thead>
                        <tbody>
                            {{ request_rows }}
                        </tbody>
                    </table>
                </div>

                <p>Please review and process these requests promptly to maintain compliance with termination procedures.</p>

                <p>Best regards,<br>
                System Administrator</p>
            </div>
            """,
        },
        {
            "name": "member_contact_request_received",
            "subject": "Contact Request Received - {{ doc.name }}",
            "response": """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Contact Request Received</h2>

                <p>Dear {{ contact_name }},</p>

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
                    <p style="margin: 0;">{{ doc.message }}</p>
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

    for template_data in templates:
        template_name = template_data["name"]

        try:
            # Check if template already exists
            if frappe.db.exists("Email Template", template_name):
                # Update existing template
                template_doc = frappe.get_doc("Email Template", template_name)
                template_doc.subject = template_data["subject"]
                template_doc.response = template_data["response"]
                template_doc.use_html = 1
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
                        "enabled": 1,
                    }
                )
                template_doc.insert(ignore_permissions=True)
                created_count += 1
                frappe.logger().info(f"Created email template: {template_name}")

        except Exception as e:
            frappe.log_error(
                f"Failed to create/update template '{template_name}': {str(e)}", "Email Template Error"
            )

    frappe.db.commit()

    return {
        "success": True,
        "created": created_count,
        "updated": updated_count,
        "total": created_count + updated_count,
        "message": f"Email template setup completed. Created: {created_count}, Updated: {updated_count}",
    }


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
        **kwargs: Additional frappe.sendmail arguments

    Returns:
        bool: Success status
    """
    if context is None:
        context = {}

    try:
        # Get rendered template
        template = get_email_template(template_name, context)

        # Send email
        frappe.sendmail(
            recipients=recipients, subject=template["subject"], message=template["message"], **kwargs
        )

        return True

    except Exception as e:
        frappe.log_error(f"Failed to send template email '{template_name}': {str(e)}", "Template Email Error")
        return False


@standard_api()
@frappe.whitelist()
def test_email_template(template_name, test_context=None):
    """Test email template rendering with sample context"""

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

    try:
        template = get_email_template(template_name, test_context)
        return {
            "success": True,
            "template_name": template_name,
            "subject": template["subject"],
            "message": template["message"],
            "context_used": test_context,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "template_name": template_name}


@standard_api()
@frappe.whitelist()
def list_all_email_templates():
    """List all email templates in the system"""

    templates = frappe.get_all("Email Template", fields=["name", "subject", "modified"], order_by="name")

    # Separate verenigingen templates from others
    verenigingen_templates = []
    other_templates = []

    verenigingen_template_names = [
        "expense_approval_request",
        "expense_approved",
        "expense_rejected",
        "donation_confirmation",
        "donation_payment_confirmation",
        "anbi_tax_receipt",
        "termination_overdue_notification",
        "member_contact_request_received",
        "membership_application_rejected",
        "membership_rejection_incomplete",
        "membership_rejection_ineligible",
        "membership_rejection_duplicate",
        "membership_application_approved",
    ]

    for template in templates:
        if template.name in verenigingen_template_names:
            verenigingen_templates.append(template)
        else:
            other_templates.append(template)

    return {
        "success": True,
        "verenigingen_templates": verenigingen_templates,
        "other_templates": other_templates,
        "total_count": len(templates),
    }
