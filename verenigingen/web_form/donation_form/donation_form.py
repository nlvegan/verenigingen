"""
Donation Web Form Handler
Processes donations submitted through the public web form
"""

import frappe
from frappe import _


def get_context(context):
    """Add context for the donation form"""
    context.no_cache = 1

    # Get campaign list if any active campaigns
    context.campaigns = get_active_campaigns()

    # Get chapters for selection
    context.chapters = get_active_chapters()

    # Check if user is logged in and has existing donor record
    if frappe.session.user != "Guest":
        context.existing_donor = get_existing_donor()


def get_active_campaigns():
    """Get list of active fundraising campaigns"""
    # This is a placeholder - would need Campaign doctype
    return []


def get_active_chapters():
    """Get list of active chapters that accept donations"""
    return frappe.get_all(
        "Chapter", filters={"is_group": 0}, fields=["name", "chapter_name"], order_by="chapter_name"
    )


def get_existing_donor():
    """Get existing donor record for logged-in user"""
    if frappe.session.user == "Guest":
        return None

    donor = frappe.db.get_value(
        "Donor",
        {"donor_email": frappe.session.user},
        ["name", "donor_name", "phone", "donor_type"],
        as_dict=True,
    )

    return donor


@frappe.whitelist(allow_guest=True)
def process_donation_form(data):
    """Process the donation form submission"""
    try:
        # Parse the data
        donation_data = frappe.parse_json(data) if isinstance(data, str) else data

        # Get or create donor
        donor = get_or_create_donor(donation_data)

        # Create donation record
        donation = create_donation(donor, donation_data)

        # Handle periodic agreement if requested
        if donation_data.get("create_periodic_agreement"):
            create_periodic_agreement_from_donation(donor, donation_data)

        # Send confirmation email
        send_donation_confirmation(donation)

        return {"success": True, "donation_id": donation.name, "message": _("Thank you for your donation!")}

    except Exception as e:
        frappe.log_error(f"Donation form error: {str(e)}", "Donation Form Error")
        return {
            "success": False,
            "message": _("An error occurred processing your donation. Please try again."),
        }


def get_or_create_donor(data):
    """Get existing donor or create new one"""
    # Check if donor exists by email
    existing_donor = frappe.db.get_value("Donor", {"donor_email": data.get("donor_email")}, "name")

    if existing_donor:
        # Update phone if provided
        if data.get("donor_phone"):
            frappe.db.set_value("Donor", existing_donor, "phone", data.get("donor_phone"))
        return existing_donor

    # Create new donor
    donor = frappe.new_doc("Donor")
    donor.donor_name = data.get("donor_name")
    donor.donor_email = data.get("donor_email")
    donor.phone = data.get("donor_phone") or ""
    donor.donor_type = data.get("donor_type", "Individual")
    donor.insert(ignore_permissions=True)

    return donor.name


def create_donation(donor, data):
    """Create donation record"""
    from verenigingen.verenigingen.doctype.donation.donation import get_company_for_donations

    donation = frappe.new_doc("Donation")
    donation.donor = donor
    donation.date = data.get("date") or frappe.utils.today()
    donation.amount = float(data.get("amount"))
    donation.payment_method = data.get("payment_method")
    donation.donation_status = data.get("donation_status", "One-time")
    donation.donation_purpose_type = data.get("donation_purpose_type", "General")

    # Set recurring frequency if applicable
    if donation.donation_status == "Recurring":
        donation.recurring_frequency = data.get("recurring_frequency")

    # Set purpose-specific fields
    if donation.donation_purpose_type == "Campaign":
        donation.campaign_reference = data.get("campaign_reference")
    elif donation.donation_purpose_type == "Chapter":
        donation.chapter_reference = data.get("chapter_reference")
    elif donation.donation_purpose_type == "Specific Goal":
        donation.specific_goal_description = data.get("specific_goal_description")

    # Set notes
    if data.get("donation_notes"):
        donation.donation_notes = data.get("donation_notes")

    # Handle anonymous donation
    if data.get("anonymous_donation"):
        donation.donation_notes = (donation.donation_notes or "") + "\n[Anonymous Donation Requested]"

    # Set company
    donation.company = get_company_for_donations()

    # Set default donation type
    if not hasattr(donation, "donation_type") or not donation.donation_type:
        donation.donation_type = (
            frappe.db.get_single_value("Verenigingen Settings", "default_donation_type") or "General"
        )

    donation.insert(ignore_permissions=True)

    # Submit if payment method is not requiring further action
    if data.get("payment_method") not in ["SEPA Direct Debit", "Mollie"]:
        donation.submit()

    return donation


def create_periodic_agreement_from_donation(donor, data):
    """Create a periodic donation agreement if requested"""
    from verenigingen.api.periodic_donation_operations import create_periodic_agreement

    # For web form, we'll create a draft agreement
    # The donor will need to complete the process separately

    result = create_periodic_agreement(
        donor=donor,
        annual_amount=float(data.get("amount")) * 12,  # Assuming monthly
        payment_frequency=data.get("recurring_frequency", "Monthly"),
        payment_method=data.get("payment_method"),
        agreement_type="Private Written",
    )

    if result.get("success"):
        # Send information about next steps
        send_periodic_agreement_info(donor, result.get("agreement"))


def send_donation_confirmation(donation):
    """Send confirmation email to donor"""
    try:
        donor = frappe.get_doc("Donor", donation.donor)

        if donor.donor_email:
            frappe.sendmail(
                recipients=[donor.donor_email],
                subject=_("Thank you for your donation"),
                message=get_confirmation_email_content(donation, donor),
                reference_doctype="Donation",
                reference_name=donation.name,
            )
    except Exception as e:
        frappe.log_error(f"Failed to send donation confirmation: {str(e)}", "Donation Email Error")


def get_confirmation_email_content(donation, donor):
    """Get donation confirmation email content"""
    return f"""
    <p>Dear {donor.donor_name},</p>

    <p>Thank you for your generous donation of €{donation.amount:.2f}.</p>

    <p><strong>Donation Details:</strong></p>
    <ul>
        <li>Reference: {donation.name}</li>
        <li>Date: {frappe.utils.formatdate(donation.date)}</li>
        <li>Amount: €{donation.amount:.2f}</li>
        <li>Payment Method: {donation.payment_method}</li>
    </ul>

    <p>As an ANBI-registered organization, your donation is tax-deductible.
    You will receive an official receipt for tax purposes.</p>

    <p>If you have any questions, please don't hesitate to contact us.</p>

    <p>With gratitude,<br>
    Your Organization</p>
    """


def send_periodic_agreement_info(donor_name, agreement_name):
    """Send information about periodic donation agreement"""
    try:
        donor = frappe.get_doc("Donor", donor_name)
        agreement = frappe.get_doc("Periodic Donation Agreement", agreement_name)

        if donor.donor_email:
            frappe.sendmail(
                recipients=[donor.donor_email],
                subject=_("Periodic Donation Agreement - Next Steps"),
                message=f"""
                <p>Dear {donor.donor_name},</p>

                <p>Thank you for your interest in setting up a periodic donation agreement.</p>

                <p>We have created a draft agreement (Reference: {agreement.agreement_number})
                based on your donation preferences.</p>

                <p><strong>Next Steps:</strong></p>
                <ol>
                    <li>We will send you the agreement document for review and signature</li>
                    <li>Once signed, return the document to us</li>
                    <li>We will activate your periodic donation agreement</li>
                    <li>You will enjoy maximum tax benefits for your donations</li>
                </ol>

                <p>The agreement will be for a 5-year period as required by Dutch tax law
                for ANBI periodic donations.</p>

                <p>We will contact you within 2 business days with the agreement documents.</p>

                <p>Thank you for your commitment to supporting our cause!</p>

                <p>With gratitude,<br>
                Your Organization</p>
                """,
                reference_doctype="Periodic Donation Agreement",
                reference_name=agreement.name,
            )
    except Exception as e:
        frappe.log_error(f"Failed to send agreement info: {str(e)}", "Agreement Email Error")
