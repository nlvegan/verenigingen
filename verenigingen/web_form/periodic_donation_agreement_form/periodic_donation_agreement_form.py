"""
Periodic Donation Agreement Web Form Handler
Handles the creation of periodic donation agreements through web forms
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def get_context(context):
    """Add context for the periodic donation agreement form"""
    context.no_cache = 1

    # Require login for this form
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to create a periodic donation agreement"), frappe.PermissionError)

    # Get or create donor record
    context.donor = get_or_create_donor_for_user()

    if not context.donor:
        frappe.throw(_("Unable to create donor profile. Please contact support."))


def get_or_create_donor_for_user():
    """Get existing donor or create one for logged-in user"""
    if frappe.session.user == "Guest":
        return None

    # Check if donor exists
    donor = frappe.db.get_value(
        "Donor",
        {"donor_email": frappe.session.user},
        ["name", "donor_name", "phone", "donor_type", "anbi_consent"],
        as_dict=True,
    )

    if donor:
        return donor

    # Create new donor from user
    user = frappe.get_doc("User", frappe.session.user)

    donor_doc = frappe.new_doc("Donor")
    donor_doc.donor_name = user.full_name or user.email
    donor_doc.donor_email = user.email
    donor_doc.donor_type = "Individual"
    donor_doc.insert(ignore_permissions=True)

    return {
        "name": donor_doc.name,
        "donor_name": donor_doc.donor_name,
        "donor_type": donor_doc.donor_type,
        "anbi_consent": 0,
    }


@frappe.whitelist()
def calculate_payment_amount(annual_amount, payment_frequency):
    """Calculate payment amount based on annual amount and frequency"""
    annual = flt(annual_amount)

    if payment_frequency == "Monthly":
        return annual / 12
    elif payment_frequency == "Quarterly":
        return annual / 4
    elif payment_frequency == "Annually":
        return annual

    return 0


@frappe.whitelist()
def validate_bsn(bsn):
    """Validate BSN format and checksum"""
    from verenigingen.api.anbi_operations import validate_bsn as validate_bsn_api

    result = validate_bsn_api(bsn)
    return result


@frappe.whitelist()
def process_agreement_form(data):
    """Process the periodic donation agreement form submission"""
    try:
        # Parse data
        form_data = frappe.parse_json(data) if isinstance(data, str) else data

        # Validate required fields
        validate_agreement_form_data(form_data)

        # Get donor
        donor = form_data.get("donor")
        if not donor:
            donor = get_or_create_donor_for_user()["name"]

        # Update donor with BSN if provided and consented
        if form_data.get("bsn_for_agreement") and form_data.get("bsn_consent"):
            update_donor_bsn(donor, form_data.get("bsn_for_agreement"))

        # Create SEPA mandate if needed
        sepa_mandate = None
        if form_data.get("payment_method") == "SEPA Direct Debit":
            sepa_mandate = create_sepa_mandate_for_agreement(
                donor, form_data.get("sepa_iban"), form_data.get("sepa_account_holder")
            )

        # Create agreement
        agreement = create_agreement_from_form(donor, form_data, sepa_mandate)

        # Handle document upload
        if form_data.get("agreement_document"):
            attach_document_to_agreement(agreement, form_data.get("agreement_document"))

        # Send confirmation
        send_agreement_submission_confirmation(agreement)

        return {
            "success": True,
            "agreement": agreement.name,
            "agreement_number": agreement.agreement_number,
            "message": _("Your periodic donation agreement has been submitted successfully!"),
        }

    except Exception as e:
        frappe.log_error(f"Agreement form error: {str(e)}", "Agreement Form Error")
        return {"success": False, "message": str(e)}


def validate_agreement_form_data(data):
    """Validate form data before processing"""
    required_fields = [
        "agreement_type",
        "start_date",
        "annual_amount",
        "payment_frequency",
        "payment_method",
        "accept_five_year_term",
        "accept_terms",
    ]

    for field in required_fields:
        if not data.get(field):
            frappe.throw(_("Please fill all required fields"))

    # Validate terms acceptance
    if not data.get("accept_five_year_term") or not data.get("accept_terms"):
        frappe.throw(_("Please accept all terms and conditions"))

    # Validate SEPA fields if SEPA selected
    if data.get("payment_method") == "SEPA Direct Debit":
        if not data.get("sepa_iban") or not data.get("sepa_account_holder"):
            frappe.throw(_("IBAN and Account Holder Name are required for SEPA Direct Debit"))


def update_donor_bsn(donor_name, bsn):
    """Update donor BSN with consent"""
    from verenigingen.api.anbi_operations import update_donor_tax_identifiers

    # Validate BSN first
    validation = validate_bsn(bsn)
    if not validation.get("valid"):
        frappe.throw(_("Invalid BSN: {0}").format(validation.get("message")))

    # Update using ANBI operations API
    result = update_donor_tax_identifiers(donor=donor_name, bsn=bsn, verification_method="Web Form")

    if not result.get("success"):
        frappe.log_error(f"Failed to update BSN: {result.get('message')}", "BSN Update Error")


def create_sepa_mandate_for_agreement(donor, iban, account_holder):
    """Create SEPA mandate for the agreement"""
    # Check if mandate already exists
    existing = frappe.db.get_value("SEPA Mandate", {"donor": donor, "iban": iban, "status": "Active"}, "name")

    if existing:
        return existing

    # Create new mandate
    mandate = frappe.new_doc("SEPA Mandate")
    mandate.donor = donor
    mandate.iban = iban
    mandate.account_holder_name = account_holder
    mandate.mandate_type = "RCUR"  # Recurring
    mandate.status = "Pending"  # Will be activated with agreement
    mandate.valid_from = frappe.utils.today()

    # Auto-generate mandate ID
    mandate.mandate_id = generate_mandate_id()

    # Derive BIC if possible
    if iban.startswith("NL"):
        from verenigingen.utils.sepa_utils import derive_bic_from_iban

        mandate.bic = derive_bic_from_iban(iban)

    mandate.insert(ignore_permissions=True)

    return mandate.name


def generate_mandate_id():
    """Generate unique SEPA mandate ID"""
    import random
    import string

    prefix = "MNDT"
    timestamp = frappe.utils.now_datetime().strftime("%Y%m%d%H%M%S")
    random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))

    return f"{prefix}-{timestamp}-{random_suffix}"


def create_agreement_from_form(donor, form_data, sepa_mandate=None):
    """Create periodic donation agreement from form data"""
    agreement = frappe.new_doc("Periodic Donation Agreement")

    agreement.donor = donor
    agreement.agreement_type = form_data.get("agreement_type")
    agreement.start_date = form_data.get("start_date")
    agreement.annual_amount = flt(form_data.get("annual_amount"))
    agreement.payment_frequency = form_data.get("payment_frequency")
    agreement.payment_method = form_data.get("payment_method")
    agreement.status = "Draft"  # Will be activated after verification

    if sepa_mandate:
        agreement.sepa_mandate = sepa_mandate

    # Auto-calculate end date and payment amount
    agreement.calculate_end_date()
    agreement.calculate_payment_amount()

    # Set submission metadata
    agreement.donor_signature_received = 0  # Not yet, just submitted
    agreement.agreement_date = frappe.utils.today()

    agreement.insert(ignore_permissions=True)

    return agreement


def attach_document_to_agreement(agreement, file_url):
    """Attach uploaded document to agreement"""
    if not file_url:
        return

    try:
        # Update agreement with document
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "agreement_document", file_url)

        # If document is uploaded, mark signature as received
        frappe.db.set_value(
            "Periodic Donation Agreement",
            agreement.name,
            {"donor_signature_received": 1, "signed_date": frappe.utils.today()},
        )

    except Exception as e:
        frappe.log_error(f"Failed to attach document: {str(e)}", "Agreement Attachment Error")


def send_agreement_submission_confirmation(agreement):
    """Send confirmation email for agreement submission"""
    try:
        donor = frappe.get_doc("Donor", agreement.donor)

        if donor.donor_email:
            frappe.sendmail(
                recipients=[donor.donor_email],
                subject=_("Periodic Donation Agreement Submitted - {0}").format(agreement.agreement_number),
                message=get_submission_email_content(agreement, donor),
                reference_doctype="Periodic Donation Agreement",
                reference_name=agreement.name,
            )
    except Exception as e:
        frappe.log_error(f"Failed to send submission confirmation: {str(e)}", "Agreement Email Error")


def get_submission_email_content(agreement, donor):
    """Get email content for agreement submission"""
    return f"""
    <p>Dear {donor.donor_name},</p>

    <p>Thank you for submitting your periodic donation agreement.</p>

    <h3>Agreement Details:</h3>
    <ul>
        <li><strong>Agreement Number:</strong> {agreement.agreement_number}</li>
        <li><strong>Agreement Type:</strong> {agreement.agreement_type}</li>
        <li><strong>Start Date:</strong> {frappe.utils.formatdate(agreement.start_date)}</li>
        <li><strong>End Date:</strong> {frappe.utils.formatdate(agreement.end_date)}</li>
        <li><strong>Annual Amount:</strong> €{agreement.annual_amount:,.2f}</li>
        <li><strong>Payment Frequency:</strong> {agreement.payment_frequency}</li>
        <li><strong>Payment Amount:</strong> €{agreement.payment_amount:,.2f} per {agreement.payment_frequency.lower()}</li>
    </ul>

    <h3>Next Steps:</h3>
    <ol>
        <li>We will review your agreement within 2 business days</li>
        <li>If you haven't uploaded a signed agreement, we will send you the document for signature</li>
        <li>Once all documentation is complete, we will activate your agreement</li>
        <li>You will receive confirmation when your agreement is active</li>
    </ol>

    <p>Your periodic donations will be fully tax-deductible under Dutch ANBI regulations.</p>

    <p>If you have any questions, please contact us.</p>

    <p>With gratitude,<br>
    Your Organization</p>
    """


@frappe.whitelist()
def get_agreement_terms():
    """Get terms and conditions for periodic donation agreements"""
    return """
    <h4>Terms and Conditions for Periodic Donation Agreement</h4>

    <ol>
        <li><strong>Duration:</strong> This agreement is valid for a minimum period of 5 years
        from the start date to qualify for ANBI tax benefits.</li>

        <li><strong>Tax Benefits:</strong> Periodic donations are fully tax-deductible without
        threshold or maximum limits under Dutch tax law.</li>

        <li><strong>Payment Obligations:</strong> You commit to making regular donations according
        to the agreed frequency and amount.</li>

        <li><strong>Modifications:</strong> Changes to the agreement require written consent from
        both parties.</li>

        <li><strong>Cancellation:</strong> Early termination is possible but may affect the tax
        deductibility of previous donations.</li>

        <li><strong>Privacy:</strong> Your personal data will be processed in accordance with GDPR
        and used only for donation administration and tax reporting.</li>

        <li><strong>ANBI Status:</strong> Our organization maintains ANBI status. If this status
        changes, we will inform you immediately.</li>
    </ol>

    <p>By accepting these terms, you confirm your commitment to this periodic donation agreement.</p>
    """
