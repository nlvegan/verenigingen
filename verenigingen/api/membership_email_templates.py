"""
Default email template creation for membership application management.

Creates standard rejection and approval email templates used by the
membership review workflow. Called from setup and admin UI.
Extracted from membership_application_review.py for separation of concerns.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import critical_api


@frappe.whitelist()
@critical_api()  # System configuration management
def create_default_email_templates():
    """Create default email templates for membership application management"""
    if not frappe.has_permission("Email Template", "create"):
        frappe.throw(_("You don't have permission to create email templates"))

    templates = []

    # 1. General rejection template
    if not frappe.db.exists("Email Template", "membership_application_rejected"):
        rejection_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_rejected",
                "subject": "Membership Application Update - {{ member_name }}",
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review, we regret to inform you that your membership application has not been approved at this time.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Reason:</strong> {{ reason }}</p>
</div>

<p>If you have any questions or would like to discuss this decision, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        rejection_template.insert()
        templates.append("membership_application_rejected")

    # 2. Incomplete information rejection
    if not frappe.db.exists("Email Template", "membership_rejection_incomplete"):
        incomplete_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_incomplete",
                "subject": "Membership Application - Additional Information Required - {{ member_name }}",
                "response": """
<h3>Membership Application - Additional Information Required</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have reviewed your membership application, but unfortunately we need additional information to proceed with your application.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Missing Information:</strong> {{ reason }}</p>
</div>

<p>You are welcome to submit a new application with the complete information at any time. We encourage you to reapply once you have the required documentation or details.</p>

<p>If you have any questions about what information is needed, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        incomplete_template.insert()
        templates.append("membership_rejection_incomplete")

    # 3. Ineligible rejection
    if not frappe.db.exists("Email Template", "membership_rejection_ineligible"):
        ineligible_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_ineligible",
                "subject": "Membership Application Update - {{ member_name }}",
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review of your application, we regret to inform you that you do not currently meet the eligibility requirements for membership.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>We encourage you to review our membership requirements and consider reapplying in the future if your circumstances change.</p>

<p>If you have any questions about our membership criteria, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        ineligible_template.insert()
        templates.append("membership_rejection_ineligible")

    # 4. Duplicate application rejection
    if not frappe.db.exists("Email Template", "membership_rejection_duplicate"):
        duplicate_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_duplicate",
                "subject": "Membership Application - Duplicate Detected - {{ member_name }}",
                "response": """
<h3>Membership Application - Duplicate Application</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have detected that you have already submitted a membership application or are already a member of our association.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>If you believe this is an error or if you need assistance with your existing membership, please contact us immediately.</p>

<p>If you have any questions, please don't hesitate to reach out.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        duplicate_template.insert()
        templates.append("membership_rejection_duplicate")

    # Also create approval template if it doesn't exist
    if not frappe.db.exists("Email Template", "membership_application_approved"):
        approval_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_approved",
                "subject": "Membership Application Approved - Payment Required - {{ member_name }}",
                "response": """
<h2>🎉 Membership Application Approved!</h2>

<p>Dear {{ first_name }},</p>

<p>Congratulations! Your membership application has been approved.</p>

<div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <h4>Application Details:</h4>
    <ul>
        <li><strong>Application ID:</strong> {{ application_id }}</li>
        <li><strong>Membership Type:</strong> {{ membership_type.membership_type_name }}</li>
        <li><strong>Fee Amount:</strong> {{ payment_amount }}</li>
    </ul>
</div>

<p>To complete your membership, please pay the membership fee using the link below:</p>

<div style="text-align: center; margin: 20px 0;">
    <a href="{{ payment_url }}" style="background-color: #4CAF50; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
        Pay Membership Fee
    </a>
</div>

<p>Your membership will be activated immediately after payment confirmation.</p>

<p>If you have any questions, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        approval_template.insert()
        templates.append("membership_application_approved")

    # Note: Frappe automatically commits template creation

    return {"success": True, "message": f"Created {len(templates)} email templates", "templates": templates}
