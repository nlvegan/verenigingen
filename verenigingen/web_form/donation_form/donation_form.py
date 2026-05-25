"""
Donation Web Form Handler
Processes donations submitted through the public web form
"""

import frappe
from frappe import _

from verenigingen.services.communication.email_service import get_email_service


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
    return frappe.get_all("Chapter", filters={"published": 1}, fields=["name", "region"], order_by="name")


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

        # Import validation utilities
        from verenigingen.utils.validation.api_validators import APIValidator

        # Pre-validate critical fields to provide better error messages
        if not donation_data.get("donor_email"):
            frappe.throw(_("Email address is required"))

        try:
            APIValidator.validate_email(donation_data.get("donor_email"), required=True)
        except Exception as e:
            frappe.throw(_("Invalid email address: {0}").format(str(e)))

        if donation_data.get("donor_phone"):
            try:
                APIValidator.validate_phone(donation_data.get("donor_phone"), required=False)
            except Exception as e:
                frappe.throw(_("Invalid phone number: {0}").format(str(e)))

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
    # Import validation utilities
    from verenigingen.utils.validation.api_validators import APIValidator

    # Validate email address
    validated_email = APIValidator.validate_email(data.get("donor_email"), required=True)

    # Validate phone number if provided
    validated_phone = None
    if data.get("donor_phone"):
        validated_phone = APIValidator.validate_phone(data.get("donor_phone"), required=False)

    # Check if donor exists by email using cached lookup
    from verenigingen.services.donation.donor_service import get_donor_by_email

    existing_donor_doc = get_donor_by_email(validated_email)

    if existing_donor_doc:
        # Update phone if provided and validated
        if validated_phone:
            frappe.db.set_value("Donor", existing_donor_doc.name, "phone", validated_phone)
        return existing_donor_doc.name

    # Create new donor
    donor = frappe.new_doc("Donor")
    donor.donor_name = data.get("donor_name")
    donor.donor_email = validated_email
    donor.phone = validated_phone or ""
    donor.donor_type = data.get("donor_type", "Individual")

    # CORRECTED SECURE VERSION: Use proper secure operations for public form submissions
    from verenigingen.utils.secure_operations import secure_document_operation

    result = secure_document_operation(
        operation="insert",
        doc=donor,
        justification="Create donor record from public donation form - public fundraising system",
        required_permissions=["Donor:create"],
        override_user="Administrator",  # Use system context for public forms
    )

    if not result.success:
        frappe.log_error(f"Failed to create donor from donation form: {'; '.join(result.errors)}")
        frappe.throw(_("Unable to process donation. Please try again or contact support."))

    donor = result.document

    return donor.name


def create_donation(donor, data):
    """Create donation record"""
    from verenigingen.verenigingen.doctype.donation.donation import get_company_for_donations

    donation = frappe.new_doc("Donation")
    donation.donor = donor
    # Donation schema uses donation_date + mode_of_payment, not date + payment_method.
    # Accept either input key for backward compat with form payloads.
    donation.donation_date = data.get("donation_date") or data.get("date") or frappe.utils.today()
    donation.amount = float(data.get("amount"))
    donation.mode_of_payment = data.get("mode_of_payment") or data.get("payment_method")
    donation.status = data.get("donation_status", "One-time")
    donation.donation_purpose_type = data.get("donation_purpose_type", "General")

    # Set recurring frequency if applicable
    if donation.status == "Recurring":
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
        donation.donation_type = _get_validated_donation_type()

    # CORRECTED SECURE VERSION: Use proper secure operations for public form submissions
    from verenigingen.utils.secure_operations import secure_document_operation

    result = secure_document_operation(
        operation="insert",
        doc=donation,
        justification="Create donation record from public donation form - public fundraising system",
        required_permissions=["Donation:create"],
        override_user="Administrator",  # Use system context for public forms
    )

    if not result.success:
        frappe.log_error(f"Failed to create donation from donation form: {'; '.join(result.errors)}")
        frappe.throw(_("Unable to process donation. Please try again or contact support."))

    donation = result.document

    # Submit if payment method is not requiring further action.
    # Read from the doc (canonical) rather than the input payload — handles
    # both old (payment_method) and new (mode_of_payment) input keys.
    if donation.mode_of_payment not in ["SEPA Direct Debit", "Mollie"]:
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
        payment_method=data.get("mode_of_payment") or data.get("payment_method"),
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
            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=[donor.donor_email],
                subject=_("Thank you for your donation"),
                message=get_confirmation_email_content(donation, donor),
                reference_doctype="Donation",
                reference_name=donation.name,
                notification_key="donation_confirmation",
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
        <li>Date: {frappe.utils.formatdate(donation.donation_date)}</li>
        <li>Amount: €{donation.amount:.2f}</li>
        <li>Payment Method: {donation.mode_of_payment}</li>
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
            email_service = get_email_service()
            email_service.send_simple_email(
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
                notification_key="periodic_donation_confirmation",
            )
    except Exception as e:
        frappe.log_error(f"Failed to send agreement info: {str(e)}", "Agreement Email Error")


def _get_validated_donation_type():
    """Get validated donation type - DEPRECATED: Donation Type DocType was removed"""
    # Donation Type DocType was removed - return None for backwards compatibility
    return None
