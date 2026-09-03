"""
Periodic Donation Agreement Web Form Handler
Handles the creation of periodic donation agreements through web forms

Security Features:
- Authentication required (guest access blocked)
- Rate limiting to prevent abuse (5 submissions per hour per user)
- Donor derived from authenticated user, not form data
- Audit logging of all form submissions
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    self_service_api,
    utility_api,
)

# Rate limiting configuration
RATE_LIMIT_SUBMISSIONS_PER_HOUR = 5
RATE_LIMIT_CACHE_PREFIX = "agreement_form_rate_limit"


def check_rate_limit():
    """Check if user has exceeded rate limit for agreement submissions.

    Returns:
        bool: True if within limit, raises exception if exceeded
    """
    if frappe.session.user == "Guest":
        return True  # Guest check happens elsewhere

    cache_key = f"{RATE_LIMIT_CACHE_PREFIX}:{frappe.session.user}"
    current_count = frappe.cache().get(cache_key) or 0

    if current_count >= RATE_LIMIT_SUBMISSIONS_PER_HOUR:
        frappe.log_error(
            f"Rate limit exceeded for user {frappe.session.user} on agreement form",
            "Agreement Form Rate Limit",
        )
        frappe.throw(
            _("You have submitted too many agreements recently. Please try again later."),
            frappe.RateLimitExceededError,
        )

    return True


def increment_rate_limit():
    """Increment rate limit counter after successful submission."""
    if frappe.session.user == "Guest":
        return

    cache_key = f"{RATE_LIMIT_CACHE_PREFIX}:{frappe.session.user}"
    current_count = frappe.cache().get(cache_key) or 0

    # Set count with 1 hour expiry
    frappe.cache().set(cache_key, current_count + 1, expires_in_sec=3600)


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
    # SECURITY JUSTIFICATION: ignore_permissions=True is acceptable here because:
    # 1. User is authenticated (Guest blocked at get_context)
    # 2. Donor is linked to authenticated user's email (line 49)
    # 3. Users cannot create donors for others (email derived from session)
    donor_doc.insert(ignore_permissions=True)

    return {
        "name": donor_doc.name,
        "donor_name": donor_doc.donor_name,
        "donor_type": donor_doc.donor_type,
        "anbi_consent": 0,
    }


@frappe.whitelist()
@utility_api
def calculate_payment_amount(annual_amount, payment_frequency: str):
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
@utility_api
def validate_bsn(bsn: str):
    """Validate BSN format and checksum"""
    from verenigingen.api.anbi_operations import validate_bsn as validate_bsn_api

    result = validate_bsn_api(bsn)
    return result


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def process_agreement_form(data):
    """Process the periodic donation agreement form submission

    Security: This endpoint is authenticated-only (no allow_guest).
    The donor is always resolved from the logged-in user, never from
    untrusted form data, to prevent users creating agreements for others.
    Rate limited to prevent abuse.
    """
    try:
        # SECURITY: Check rate limit before processing
        check_rate_limit()

        # Parse data
        form_data = frappe.parse_json(data) if isinstance(data, str) else data

        # Validate required fields
        validate_agreement_form_data(form_data)

        # SECURITY: Always derive donor from authenticated user, never from form data
        # This prevents authenticated users from creating agreements for other donors
        user_donor = get_or_create_donor_for_user()
        if not user_donor:
            frappe.throw(_("Unable to find or create your donor profile"))
        donor = user_donor["name"]

        # Update donor with BSN if provided and consented
        if form_data.get("bsn_for_agreement") and form_data.get("bsn_consent"):
            update_donor_bsn(donor, form_data.get("bsn_for_agreement"))

        # Create agreement
        agreement = create_agreement_from_form(donor, form_data)

        # Handle document upload
        if form_data.get("agreement_document"):
            attach_document_to_agreement(agreement, form_data.get("agreement_document"))

        # Send confirmation
        send_agreement_submission_confirmation(agreement)

        # SECURITY: Increment rate limit counter after successful submission
        increment_rate_limit()

        # Audit log for compliance
        frappe.log_error(
            f"Agreement form submitted: {agreement.name} by user {frappe.session.user}",
            "Agreement Form Audit",
        )

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

    # Reject an unrecognized payment_method here too (#744), before any
    # donor/agreement side effects run below in process_agreement_form --
    # the actual mapping happens again in create_agreement_from_form, this
    # call is for its throw-only validation. Without this, a bad value would
    # only be caught later, after get_or_create_donor_for_user() and
    # update_donor_bsn() had already run.
    from verenigingen.api.periodic_donation_operations import map_periodic_agreement_payment_method

    map_periodic_agreement_payment_method(data.get("payment_method"))

    # SEPA Direct Debit is not currently supported through this form (#762):
    # the SEPA mandate this form used to create linked a Donor name into the
    # Member-only "member" field, used an invalid status, and set a
    # nonexistent field -- and even a spec-compliant, memberless mandate
    # would never be picked up by the SEPA collection pipeline, which
    # resolves every mandate by Member (see verenigingen_payments/utils/
    # mandate_candidates.py and services/sepa_batch_processor.py). Refusing
    # loudly up front -- before any donor/agreement side effects run -- beats
    # creating an agreement whose direct debit will never actually collect.
    if data.get("payment_method") == "SEPA Direct Debit":
        frappe.throw(
            _(
                "SEPA Direct Debit is not currently available for periodic donation "
                "agreements submitted through this form. Please choose Bank Transfer "
                "or Other, or contact us to arrange a direct debit mandate."
            ),
            title=_("Payment Method Not Available"),
        )


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


def create_agreement_from_form(donor, form_data):
    """Create periodic donation agreement from form data"""
    from verenigingen.api.periodic_donation_operations import map_periodic_agreement_payment_method

    agreement = frappe.new_doc("Periodic Donation Agreement")

    agreement.donor = donor
    agreement.agreement_type = form_data.get("agreement_type")
    agreement.start_date = form_data.get("start_date")
    agreement.annual_amount = flt(form_data.get("annual_amount"))
    agreement.payment_frequency = form_data.get("payment_frequency")
    agreement.payment_method = map_periodic_agreement_payment_method(form_data.get("payment_method"))
    agreement.status = "Draft"  # Will be activated after verification

    # Auto-calculate end date and payment amount
    agreement.calculate_end_date()
    agreement.calculate_payment_amount()

    # Set submission metadata
    agreement.donor_signature_received = 0  # Not yet, just submitted
    agreement.agreement_date = frappe.utils.today()

    # Security: Authenticated user creating agreement for own donor record - rate limited, Draft status
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
            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=[donor.donor_email],
                subject=_("Periodic Donation Agreement Submitted - {0}").format(agreement.agreement_number),
                message=get_submission_email_content(agreement, donor),
                reference_doctype="Periodic Donation Agreement",
                reference_name=agreement.name,
                notification_key="periodic_donation_confirmation",
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
@utility_api
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
