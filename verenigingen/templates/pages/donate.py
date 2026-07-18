"""
Donation Portal Web Interface and Processing System

This module provides the web interface and backend processing for the public
donation portal, enabling supporters to make both one-time and recurring
donations to the organization. It integrates with Dutch tax compliance
(ANBI) requirements and provides comprehensive donation management capabilities.

Key Features:
    * Public donation form with real-time validation
    * Integration with Dutch ANBI tax reporting requirements
    * Support for one-time and recurring donation workflows
    * Chapter-specific donation routing capabilities
    * Secure payment processing integration
    * Donor information management and privacy compliance
    * Automated receipt generation and distribution

ANBI Compliance:
    Implements Dutch ANBI (Algemeen Nut Beogende Instelling) compliance
    features including minimum reportable amounts, donor information
    collection, and automated reporting capabilities for tax purposes.

User Experience:
    Provides a streamlined donation experience with clear information
    about the organization's mission, transparent fee information,
    and immediate confirmation of donation processing.
"""

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
from verenigingen.utils.secure_operations import (
    secure_document_operation,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    public_api,
)
from verenigingen.utils.validation_utilities import QueryBuilder


def get_context(context):
    """Get context for donation page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Make a Donation")

    # Check if returning from payment (donation_id parameter)
    donation_id = frappe.form_dict.get("donation_id")
    if donation_id:
        try:
            donation = frappe.get_doc("Donation", donation_id)
            context.donation_result = donation

            # Determine payment status for display
            if donation.paid:
                context.payment_status = "success"
                context.title = _("Donation Successful")
            else:
                # Check actual payment status from Mollie if payment_id exists
                if donation.payment_id:
                    # Check payment status from Mollie to get real status
                    try:
                        from verenigingen.verenigingen_payments.mollie.core.client import MollieClient

                        client = MollieClient()
                        payment = client.get_payment(donation.payment_id)

                        if hasattr(payment, "status"):
                            mollie_status = payment.status
                        elif isinstance(payment, dict):
                            mollie_status = payment.get("status", "unknown")
                        else:
                            mollie_status = "unknown"

                        if mollie_status == "paid":
                            context.payment_status = "success"
                            context.title = _("Payment Successful")
                            context.payment_pending_webhook = True  # Webhook hasn't processed yet
                        elif mollie_status in ["open", "pending"]:
                            context.payment_status = "pending"
                            context.title = _("Payment Pending")
                        elif mollie_status in ["failed", "canceled", "expired"]:
                            context.payment_status = "failed"
                            context.title = _("Payment Failed")
                        else:
                            context.payment_status = "pending"
                            context.title = _("Payment Status Unknown")

                    except Exception as e:
                        frappe.log_error(
                            f"Failed to check Mollie payment status for {donation.payment_id}: {str(e)}"
                        )
                        context.payment_status = "pending"
                        context.title = _("Payment Status Unknown")
                else:
                    context.payment_status = "pending"
                    context.title = _("Payment Pending")

        except frappe.DoesNotExistError:
            frappe.log_error(f"Donation {donation_id} not found on return from payment")
            context.payment_status = "error"

    # Get verenigingen settings
    from verenigingen.utils.settings_utils import get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(
            _("Verenigingen Settings not configured. Please run app installation setup."),
            frappe.ValidationError,
        )
    context.settings = {
        "company_name": frappe.get_value("Company", settings.company, "company_name"),
        "enable_chapter_management": settings.enable_chapter_management,
        "organization_email_domain": getattr(settings, "organization_email_domain", ""),
        "anbi_minimum_reportable_amount": flt(getattr(settings, "anbi_minimum_reportable_amount", 500)),
    }

    # Get chapters for earmarking
    chapters = []
    if settings.enable_chapter_management:
        chapters = QueryBuilder.get_all_active_records(
            "Chapter", additional_filters={"published": 1}, fields=["name"], order_by="name"
        )
    context.chapters = chapters

    # Get available donation campaigns
    campaigns = frappe.get_all("Donation Campaign", fields=["name"], order_by="name")
    context.campaigns = campaigns

    # Get donor types for new donor creation (from Select field options)
    donor_types = [
        {"name": "Individual", "donor_type": "Individual"},
        {"name": "Organization", "donor_type": "Organization"},
    ]
    context.donor_types = donor_types
    context.default_donor_type = getattr(settings, "default_donor_type", "Individual")

    # Payment method configuration - build dynamically based on what's available
    from verenigingen.verenigingen_payments.hooks import PaymentHook

    available_methods = PaymentHook.get_available_methods()

    # Map PaymentHook method IDs back to form values and labels
    method_display = {
        PaymentHook.MOLLIE: {
            "value": "Mollie",
            "label": _("Online Payment"),
            "description": _("Pay online with iDEAL, credit card, or other methods"),
        },
        PaymentHook.PONTO: {
            "value": "Ponto",
            "label": _("Bank Payment"),
            "description": _("Pay directly from your bank account"),
        },
        PaymentHook.SEPA: {
            "value": "SEPA Direct Debit",
            "label": _("SEPA Direct Debit"),
            "description": _("Authorize us to collect the donation from your account"),
        },
        PaymentHook.BANK_TRANSFER: {
            "value": "Bank Transfer",
            "label": _("Bank Transfer"),
            "description": _("Transfer money directly to our bank account"),
        },
        PaymentHook.CASH: {
            "value": "Cash",
            "label": _("Cash"),
            "description": _("Pay in cash at our office or events"),
        },
    }

    context.payment_methods = [
        method_display[m["id"]] for m in available_methods if m["id"] in method_display
    ]

    # Check if user is logged in and get existing donor info
    context.user_info = {}
    if frappe.session.user != "Guest":
        user = frappe.get_doc("User", frappe.session.user)
        context.user_info = {
            "email": user.email,
            "full_name": user.get_fullname(),
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

        # Check if user is already a donor
        existing_donor = frappe.db.get_value("Donor", {"donor_email": user.email})
        if existing_donor:
            donor_doc = frappe.get_doc("Donor", existing_donor)
            context.existing_donor = {
                "name": donor_doc.name,
                "donor_name": donor_doc.donor_name,
                "donor_email": donor_doc.donor_email,
                "phone": getattr(donor_doc, "phone", ""),
                "donor_type": donor_doc.donor_type,
            }

    return context


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def submit_donation(**kwargs):
    """Process donation form submission (delegates to PublicDonationService)."""
    return get_public_donation_service().submit(frappe._dict(kwargs))


# process_mollie_subscription function removed - now handled by MolliePaymentService


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_donation_status(donation_id):
    """Get donation status for tracking"""
    if not donation_id:
        return {"error": "Donation ID required"}

    donation = frappe.get_doc("Donation", donation_id)

    return {
        "donation_id": donation.name,
        "amount": donation.amount,
        "status": "Paid" if donation.paid else "Pending",
        "payment_method": donation.mode_of_payment,
        # Donation has no "date" field; the actual fieldname is "donation_date".
        # Accessing donation.date raised AttributeError and crashed this endpoint.
        "date": donation.donation_date,
        "purpose": (
            donation.get_earmarking_summary()
            if hasattr(donation, "get_earmarking_summary")
            else donation.donation_purpose_type
        ),
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def mark_donation_paid(donation_id, payment_reference: str | None = None):
    """Mark donation as paid (for manual processing)"""
    if not frappe.has_permission("Donation", "write"):
        return {"error": "Insufficient permissions"}

    donation = frappe.get_doc("Donation", donation_id)
    donation.paid = 1
    donation.payment_id = payment_reference or f"MANUAL-{frappe.utils.now()}"

    if hasattr(donation, "create_payment_entry"):
        donation.create_payment_entry()

    # Use secure operation for saving
    result = secure_document_operation(
        operation="save",
        doc=donation,
        justification=f"Mark donation {donation_id} as paid - manual payment processing",
        required_permissions=["Donation:write"],
    )

    if not result.success:
        return {"error": f"Failed to mark donation as paid: {'; '.join(result.errors)}"}

    return {"success": True, "message": "Donation marked as paid"}


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def retry_payment(donation_id):
    """Retry payment for a failed donation by redirecting to Mollie payment page"""
    try:
        if not donation_id:
            frappe.throw(_("Donation ID is required"))

        # Get the donation record
        donation = frappe.get_doc("Donation", donation_id)

        # Check if donation exists and belongs to current user (or allow public retry)
        if not donation:
            frappe.throw(_("Donation not found"))

        # Only allow retry for unpaid donations with payment method Mollie
        if donation.paid:
            frappe.throw(_("This donation has already been paid"))

        if donation.mode_of_payment != "Mollie":
            frappe.throw(_("Payment retry is only available for Mollie payments"))

        # Get the donor information for payment retry
        donor = frappe.get_doc("Donor", donation.donor)

        # Prepare form data for retry (similar to original payment creation)
        form_data = {
            "amount": str(donation.amount),
            "currency": "EUR",
            "return_url": f"{frappe.utils.get_url()}/donate?donation_id={donation.name}",
            "donor_name": donor.donor_name,
            "donor_email": donor.donor_email,
            "payment_method": "Mollie",
            "donation_status": donation.status,
        }

        # Process the retry payment using the same method as original submission
        payment_result = get_public_donation_service().process_mollie_payment(donation, form_data)

        # If successful, redirect to payment URL
        if payment_result.get("status") == "redirect_required":
            payment_url = payment_result.get("payment_url") or payment_result.get("checkout_url")
            if payment_url:
                frappe.local.response["type"] = "redirect"
                frappe.local.response["location"] = payment_url
                return

        # If redirect failed, return error
        frappe.throw(_("Failed to create retry payment. Please try again or contact support."))

    except Exception as e:
        frappe.log_error(f"Payment retry error for donation {donation_id}: {str(e)}", "Payment Retry Error")
        frappe.throw(_("Unable to retry payment. Please try again or contact support."))
