#!/usr/bin/env python3

import frappe


def create_comprehensive_email_templates():
    """Create all email templates used throughout the verenigingen app"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

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
                print(f"   ✓ Updated email template: {template_name}")
            else:
                # Create new template
                template_doc = frappe.get_doc(
                    {
                        "doctype": "Email Template",
                        "name": template_name,
                        "subject": template_data["subject"],
                        "use_html": 1,
                        "response": template_data["response"],
                    }
                )
                template_doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created email template: {template_name}")

        except Exception as e:
            print(f"   ❌ Failed to create/update template '{template_name}': {str(e)}")

    try:
        frappe.db.commit()
        print(f"\n✅ Email template setup completed:")
        print(f"   Created: {created_count} templates")
        print(f"   Updated: {updated_count} templates")
        print(f"   Total: {created_count + updated_count} templates processed")

        # Show all email templates
        all_templates = frappe.get_all("Email Template", fields=["name", "subject"], order_by="name")
        print(f"\n📧 All Email Templates in system ({len(all_templates)} total):")
        for template in all_templates:
            print(f"   - {template.name}: {template.subject}")

    except Exception as e:
        print(f"❌ Error committing templates: {str(e)}")

    frappe.destroy()
    return {"created": created_count, "updated": updated_count}


if __name__ == "__main__":
    create_comprehensive_email_templates()
