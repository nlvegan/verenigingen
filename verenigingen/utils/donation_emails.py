"""
Email handling for donation system
Sends confirmation emails and ANBI receipts
"""

import frappe
from frappe import _
from frappe.utils import flt, format_date, getdate


def send_donation_confirmation(donation_id):
    """Send donation confirmation email to donor"""
    try:
        donation = frappe.get_doc("Donation", donation_id)
        donor = frappe.get_doc("Donor", donation.donor)

        # Check if donor has email
        donor_email = getattr(donor, "donor_email", "") or getattr(donor, "email", "")
        if not donor_email:
            frappe.log_error(f"No email address for donor {donor.name}", "Donation Email")
            return False

        # Get email template or create default
        template = get_donation_email_template()

        # Prepare email context
        context = get_email_context(donation, donor)

        # Render email content
        subject = frappe.render_template(template.get("subject", ""), context)
        message = frappe.render_template(template.get("message", ""), context)

        # Send email
        frappe.sendmail(
            recipients=[donor_email],
            subject=subject,
            message=message,
            reference_doctype="Donation",
            reference_name=donation.name,
            send_priority=1,
        )

        # Log email sent
        donation.add_comment("Email", "Confirmation email sent to {donor_email}")

        return True

    except Exception as e:
        frappe.log_error(f"Failed to send donation confirmation: {str(e)}", "Donation Email Error")
        return False


def send_payment_confirmation(donation_id):
    """Send payment confirmation email when donation is marked as paid"""
    try:
        donation = frappe.get_doc("Donation", donation_id)
        donor = frappe.get_doc("Donor", donation.donor)

        donor_email = getattr(donor, "donor_email", "") or getattr(donor, "email", "")
        if not donor_email:
            return False

        # Get payment confirmation template
        template = get_payment_confirmation_template()
        context = get_email_context(donation, donor)

        # Add payment-specific context
        context.update(
            {
                "payment_date": format_date(donation.modified),
                "payment_method": donation.payment_method,
                "payment_reference": donation.payment_id or donation.name,
            }
        )

        # Render and send email
        subject = frappe.render_template(template.get("subject", ""), context)
        message = frappe.render_template(template.get("message", ""), context)

        frappe.sendmail(
            recipients=[donor_email],
            subject=subject,
            message=message,
            reference_doctype="Donation",
            reference_name=donation.name,
            send_priority=1,
        )

        # Send ANBI receipt if applicable
        if donation.belastingdienst_reportable and donation.anbi_agreement_number:
            send_anbi_receipt(donation_id)

        donation.add_comment("Email", "Payment confirmation sent to {donor_email}")

        return True

    except Exception as e:
        frappe.log_error(f"Failed to send payment confirmation: {str(e)}", "Payment Email Error")
        return False


def send_anbi_receipt(donation_id):
    """Send ANBI tax deduction receipt"""
    try:
        donation = frappe.get_doc("Donation", donation_id)
        donor = frappe.get_doc("Donor", donation.donor)

        # Only send for ANBI-eligible donations
        if not donation.belastingdienst_reportable or not donation.anbi_agreement_number:
            return False

        donor_email = getattr(donor, "donor_email", "") or getattr(donor, "email", "")
        if not donor_email:
            return False

        # Get ANBI template
        template = get_anbi_receipt_template()
        context = get_email_context(donation, donor)

        # Add ANBI-specific context
        context.update(
            {
                "anbi_number": donation.anbi_agreement_number,
                "anbi_date": format_date(donation.anbi_agreement_date),
                "tax_year": donation.date.year,
                "is_tax_deductible": True,
                "receipt_number": "ANBI-{donation.name}-{donation.date.year}",
            }
        )

        # Render and send email
        subject = frappe.render_template(template.get("subject", ""), context)
        message = frappe.render_template(template.get("message", ""), context)

        # Generate PDF receipt if needed
        pdf_attachment = generate_anbi_receipt_pdf(donation, context)

        frappe.sendmail(
            recipients=[donor_email],
            subject=subject,
            message=message,
            attachments=[pdf_attachment] if pdf_attachment else None,
            reference_doctype="Donation",
            reference_name=donation.name,
            send_priority=1,
        )

        donation.add_comment("Email", f"ANBI receipt sent to {donor.donor_email or donor.email}")

        return True

    except Exception as e:
        frappe.log_error(f"Failed to send ANBI receipt: {str(e)}", "ANBI Receipt Error")
        return False


def get_email_context(donation, donor):
    """Get common email context for donation emails"""
    settings = frappe.get_single("Verenigingen Settings")
    company = frappe.get_doc("Company", settings.donation_company)

    # Get earmarking summary
    earmarking = "General Fund"
    if hasattr(donation, "get_earmarking_summary"):
        earmarking = donation.get_earmarking_summary()
    elif donation.donation_purpose_type != "General":
        if donation.donation_purpose_type == "Chapter" and donation.chapter_reference:
            chapter_name = frappe.db.get_value("Chapter", donation.chapter_reference, "name")
            earmarking = f"Chapter: {chapter_name}"
        elif donation.donation_purpose_type == "Campaign" and donation.campaign_reference:
            earmarking = f"Campaign: {donation.campaign_reference}"
        elif donation.donation_purpose_type == "Specific Goal" and donation.specific_goal_description:
            earmarking = f"Specific Goal: {donation.specific_goal_description[:50]}"

    return {
        # Donation details
        "donation_id": donation.name,
        "donation_amount": flt(donation.amount),
        "donation_date": format_date(donation.date),
        "donation_type": donation.donation_type,
        "donation_status": donation.status,
        "earmarking": earmarking,
        "donation_notes": donation.donation_notes or "",
        # Donor details
        "donor_name": donor.donor_name,
        "donor_email": getattr(donor, "donor_email", "") or getattr(donor, "email", ""),
        # Organization details
        "organization_name": company.company_name,
        "organization_email": getattr(settings, "member_contact_email", ""),
        "website_url": frappe.utils.get_url(),
        # Settings
        "enable_chapter_management": settings.enable_chapter_management,
        # Date formatting
        "today": format_date(getdate()),
        "year": getdate().year,
    }


def get_donation_email_template():
    """Get donation confirmation email template"""
    from verenigingen.api.email_template_manager import get_email_template

    # Try to get template using new template manager
    try:
        return get_email_template("donation_confirmation")
    except Exception:
        pass

    # Try to get custom template from Email Template doctype
    try:
        template_doc = frappe.get_doc("Email Template", "donation_confirmation")
        return {"subject": template_doc.subject, "message": template_doc.response}
    except frappe.DoesNotExistError:
        pass

    # Return default template
    return {
        "subject": _("Thank you for your donation - {{donation_id}}"),
        "message": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Dear {{donor_name}},</h2>

            <p>Thank you for your generous donation to {{organization_name}}!</p>

            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3>Donation Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Donation ID:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{donation_id}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Amount:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">€{{donation_amount}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Date:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{donation_date}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Purpose:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{earmarking}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>Status:</strong></td>
                        <td style="padding: 8px 0;">{{donation_status}}</td>
                    </tr>
                </table>
            </div>

            <p>Your donation helps us make a positive impact in our community. We will send you a payment confirmation once your payment has been processed.</p>

            {% if donation_notes %}
            <p><strong>Your message:</strong><br>
            <em>{{donation_notes}}</em></p>
            {% endif %}

            <p>If you have any questions about your donation, please don't hesitate to contact us at {{organization_email}}.</p>

            <p>With gratitude,<br>
            {{organization_name}}</p>
        </div>
        """,
    }


def get_payment_confirmation_template():
    """Get payment confirmation email template"""
    from verenigingen.api.email_template_manager import get_email_template

    # Try to get template using new template manager
    try:
        return get_email_template("donation_payment_confirmation")
    except Exception:
        pass

    try:
        template_doc = frappe.get_doc("Email Template", "donation_payment_confirmation")
        return {"subject": template_doc.subject, "message": template_doc.response}
    except frappe.DoesNotExistError:
        pass

    return {
        "subject": _("Payment Received - Donation {{donation_id}}"),
        "message": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Dear {{donor_name}},</h2>

            <p>We have received your payment for donation {{donation_id}}. Thank you for your generous support!</p>

            <div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
                <h3 style="color: #155724; margin-top: 0;">Payment Confirmed</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Amount Paid:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">€{{donation_amount}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Payment Date:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">{{payment_date}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;"><strong>Payment Method:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #c3e6cb;">{{payment_method}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>Reference:</strong></td>
                        <td style="padding: 8px 0;">{{payment_reference}}</td>
                    </tr>
                </table>
            </div>

            <p>Your contribution of €{{donation_amount}} for {{earmarking}} will help us continue our important work.</p>

            <p>This email serves as your payment receipt. Please keep it for your records.</p>

            <p>Thank you again for your support!</p>

            <p>Best regards,<br>
            {{organization_name}}</p>
        </div>
        """,
    }


def get_anbi_receipt_template():
    """Get ANBI tax deduction receipt template"""
    from verenigingen.api.email_template_manager import get_email_template

    # Try to get template using new template manager
    try:
        return get_email_template("anbi_tax_receipt")
    except Exception:
        pass

    try:
        template_doc = frappe.get_doc("Email Template", "anbi_tax_receipt")
        return {"subject": template_doc.subject, "message": template_doc.response}
    except frappe.DoesNotExistError:
        pass

    return {
        "subject": _("Tax Deduction Receipt - {{receipt_number}}"),
        "message": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Tax Deduction Receipt (ANBI)</h2>

            <p>Dear {{donor_name}},</p>

            <p>This receipt confirms your tax-deductible donation under ANBI regulations.</p>

            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border: 2px solid #007bff;">
                <h3 style="color: #007bff; margin-top: 0;">Official Tax Receipt</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Receipt Number:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{receipt_number}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>ANBI Agreement:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{anbi_number}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Donation Amount:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>€{{donation_amount}}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>Donation Date:</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{{donation_date}}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>Tax Year:</strong></td>
                        <td style="padding: 8px 0;">{{tax_year}}</td>
                    </tr>
                </table>
            </div>

            <p><strong>Important:</strong> This donation is eligible for tax deduction under Dutch ANBI regulations. Please keep this receipt for your tax filing.</p>

            <p>{{organization_name}} is recognized as an ANBI (Algemeen Nut Beogende Instelling) organization, making your donation tax-deductible in the Netherlands.</p>

            <p>If you need any additional documentation for your tax filing, please contact us at {{organization_email}}.</p>

            <p>Thank you for your continued support.</p>

            <p>Best regards,<br>
            {{organization_name}}</p>
        </div>
        """,
    }


def generate_anbi_receipt_pdf(donation, context):
    """Generate PDF receipt for ANBI donations"""
    try:
        # This would generate a formal PDF receipt
        # For now, return None - PDF generation can be added later
        return None

    except Exception as e:
        frappe.log_error(f"PDF generation failed: {str(e)}", "ANBI PDF Error")
        return None


# Hook functions to automatically send emails
def donation_on_submit(doc, method):
    """Send confirmation email when donation is submitted"""
    if doc.doctype == "Donation":
        frappe.enqueue(send_donation_confirmation, donation_id=doc.name, queue="short", timeout=300)


def donation_payment_received(doc, method):
    """Send payment confirmation when donation is marked as paid"""
    if doc.doctype == "Donation" and doc.paid and doc.has_value_changed("paid"):
        frappe.enqueue(send_payment_confirmation, donation_id=doc.name, queue="short", timeout=300)


# Utility functions
@frappe.whitelist()
def resend_donation_confirmation(donation_id):
    """Manually resend donation confirmation email"""
    if not frappe.has_permission("Donation", "read", donation_id):
        frappe.throw(_("No permission to access this donation"))

    success = send_donation_confirmation(donation_id)

    if success:
        frappe.msgprint(_("Confirmation email sent successfully"))
    else:
        frappe.msgprint(_("Failed to send confirmation email"), indicator="red")


@frappe.whitelist()
def resend_payment_confirmation(donation_id):
    """Manually resend payment confirmation email"""
    if not frappe.has_permission("Donation", "write", donation_id):
        frappe.throw(_("No permission to access this donation"))

    success = send_payment_confirmation(donation_id)

    if success:
        frappe.msgprint(_("Payment confirmation email sent successfully"))
    else:
        frappe.msgprint(_("Failed to send payment confirmation email"), indicator="red")


@frappe.whitelist()
def send_anbi_receipt_manual(donation_id):
    """Manually send ANBI receipt"""
    if not frappe.has_permission("Donation", "write", donation_id):
        frappe.throw(_("No permission to access this donation"))

    success = send_anbi_receipt(donation_id)

    if success:
        frappe.msgprint(_("ANBI receipt sent successfully"))
    else:
        frappe.msgprint(_("Failed to send ANBI receipt"), indicator="red")
