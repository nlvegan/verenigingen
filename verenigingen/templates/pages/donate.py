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
from frappe.utils import flt, getdate

from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_document_operation,
    secure_user_context,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    public_api,
)
from verenigingen.utils.validation_utilities import QueryBuilder
from verenigingen.verenigingen_payments.hooks import PaymentHook


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
    """Process donation form submission"""
    try:
        # Parse form data
        form_data = frappe._dict(kwargs)

        # Validate required fields
        required_fields = ["donor_name", "donor_email", "amount", "payment_method"]
        for field in required_fields:
            if not form_data.get(field):
                return {"success": False, "message": _("Missing required field: {0}").format(field)}

        # Validate email format
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, form_data.donor_email):
            return {"success": False, "message": _("Invalid email address")}

        # Validate amount
        amount = flt(form_data.amount)
        if amount <= 0:
            return {"success": False, "message": _("Donation amount must be greater than zero")}

        # Create or get donor
        donor = get_or_create_donor(form_data)
        if not donor:
            return {"success": False, "message": _("Failed to create donor record")}

        # For Mollie payments: payment-first flow (no donation created yet)
        if form_data.get("payment_method") == "Mollie":
            try:
                # Create draft donation (not submitted) with metadata for payment
                donation = create_draft_donation_for_payment(donor, form_data)
                if not donation:
                    return {"success": False, "message": _("Failed to create donation record")}

                # Process Mollie payment (creates payment, donation will be submitted by webhook)
                payment_result = process_mollie_payment(donation, form_data)

                # Wrap result in expected format for frontend
                if payment_result.get("status") in ["redirect_required", "subscription_redirect_required"]:
                    return {"success": True, "donation_id": donation.name, "payment_info": payment_result}
                else:
                    return {
                        "success": False,
                        "message": payment_result.get("message", _("Payment setup failed")),
                        "info": payment_result.get("info", _("Please try again")),
                    }

            except Exception as e:
                frappe.log_error(
                    f"Mollie payment processing error for donation {donation.name if 'donation' in locals() else 'unknown'}: {str(e)}",
                    "Mollie Payment Error",
                )
                return {
                    "success": False,
                    "message": _("Payment setup temporarily unavailable"),
                    "info": _("Please try again or contact support"),
                }

        # For non-Mollie payments: traditional flow (create donation then process payment)
        else:
            # Create donation
            donation = create_donation_record(donor, form_data)
            if not donation:
                return {"success": False, "message": _("Failed to create donation record")}

            # Process payment based on method
            try:
                payment_result = process_payment_method(donation, form_data)
            except Exception:
                # Return partial success response - donation created but payment setup failed
                return {
                    "success": False,  # Overall process failed due to payment setup
                    "donation_created": True,  # But donation record was created
                    "donation_id": donation.name,
                    "message": _("Donation record created but payment setup failed"),
                    "payment_info": {
                        "status": "error",
                        "message": "Payment setup failed. Please try again or contact support.",
                        "info": "Your donation is recorded, but payment needs to be completed separately",
                    },
                }

        return {
            "success": True,
            "donation_created": True,
            "donation_id": donation.name,
            "message": _("Donation submitted successfully"),
            "payment_info": payment_result,
        }

    except Exception as e:
        frappe.log_error(f"Donation submission error: {str(e)}", "Donation Form Error")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "message": _("An error occurred while processing your donation. Please try again."),
            "debug_error": str(e),
        }


def get_or_create_donor(form_data):
    """Get existing donor or create new one.

    Thin delegate to DonationDonorService.get_or_create_from_public_form —
    see that method for the actual implementation. Kept as a delegate (not
    removed) so any remaining internal caller keeps working; it is fully
    removed once ``submit_donation`` moves to the service layer.
    """
    from verenigingen.services.donation.donor_service import get_donation_donor_service

    return get_donation_donor_service(None).get_or_create_from_public_form(form_data)


def create_draft_donation_for_payment(donor, form_data):
    """Create draft donation record for payment-first flow (not submitted until webhook)"""
    from verenigingen.utils.settings_utils import get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(
            _("Verenigingen Settings not configured. Please run app installation setup."),
            frappe.ValidationError,
        )

    # Determine purpose and earmarking
    purpose_type = form_data.get("donation_purpose_type", "General")

    donation_doc = frappe.new_doc("Donation")
    donation_data = {
        "company": settings.company,
        "donor": donor.name,
        "donation_date": getdate(),
        "amount": flt(form_data.amount),
        "mode_of_payment": form_data.get("payment_method"),
        "status": "Promised",  # All Mollie payments start as promised until payment confirmation
        "donation_purpose_type": purpose_type,
        "donation_notes": form_data.get("donation_notes", ""),
        "paid": 0,  # Will be marked paid by webhook
    }

    # Set purpose-specific fields based on purpose type
    if purpose_type == "Campaign" and form_data.get("campaign_reference"):
        donation_data["campaign"] = form_data["campaign_reference"]
    elif purpose_type == "Chapter" and form_data.get("chapter_reference"):
        donation_data["chapter_reference"] = form_data["chapter_reference"]
    elif purpose_type == "Specific Goal" and form_data.get("specific_goal_description"):
        donation_data["specific_goal_description"] = form_data["specific_goal_description"]

    donation_doc.update(donation_data)

    # Validate the donation
    donation_doc.validate()

    # PUBLIC DONATION FLOW: Save as DRAFT using secure context (webhook will submit after payment)
    try:
        system_user = get_system_user_for_operation("public_donation_draft_creation")
        with secure_user_context(
            system_user, f"Creating draft donation for public donation: {donor.donor_email}"
        ):
            donation_doc.flags.ignore_mandatory = False  # Keep data validation
            donation_doc.insert()
            frappe.db.commit()

        frappe.logger().info(
            f"Created draft donation for public donation: {donor.donor_name} amount €{form_data.amount}"
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to create draft donation: {str(e)}", "Public Donation - Draft Creation Error"
        )
        frappe.throw(_("Unable to process donation: Failed to create donation record"))

    return donation_doc


def create_donation_record(donor, form_data):
    """Create donation record"""
    from verenigingen.utils.settings_utils import get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(
            _("Verenigingen Settings not configured. Please run app installation setup."),
            frappe.ValidationError,
        )

    # Determine purpose and earmarking
    purpose_type = form_data.get("donation_purpose_type", "General")

    donation_doc = frappe.new_doc("Donation")
    donation_data = {
        "company": settings.company,
        "donor": donor.name,
        "donation_date": getdate(),
        "amount": flt(form_data.amount),
        # Set mode_of_payment from form data - it's a required field
        "mode_of_payment": form_data.get("payment_method"),
        "status": get_public_donation_service().map_donation_status(
            form_data.get("donation_status", "One-time")
        ),
        "donation_purpose_type": purpose_type,
        "donation_notes": form_data.get("donation_notes", ""),
        "paid": 0,  # Will be marked paid after payment processing
    }

    # Set purpose-specific fields based on purpose type
    if purpose_type == "Campaign" and form_data.get("campaign_reference"):
        campaign_ref = form_data.get("campaign_reference")
        # Only set campaign field if it's a valid Donation Campaign
        if frappe.db.exists("Donation Campaign", campaign_ref):
            donation_data["campaign"] = campaign_ref
        else:
            # If campaign doesn't exist, combine it with user notes for visibility
            # This preserves user intent while keeping the notes field primarily for user content
            user_notes = donation_data.get("donation_notes", "")
            if user_notes:
                donation_data["donation_notes"] = f"Campaign: {campaign_ref}\n\n{user_notes}"
            else:
                donation_data["donation_notes"] = f"Campaign: {campaign_ref}"

    if purpose_type == "Chapter" and form_data.get("chapter_reference"):
        donation_data["chapter_reference"] = form_data.get("chapter_reference")

    if purpose_type == "Specific Goal":
        # For specific goals, save the goal description in its proper field
        if form_data.get("specific_goal_description"):
            donation_data["specific_goal_description"] = form_data.get("specific_goal_description")

        # The donation_notes field already contains user's additional notes from form_data
        # No need to manipulate it further - it stays as-is for user notes

    donation_doc.update(donation_data)

    # Handle ANBI agreement if provided
    if form_data.get("anbi_agreement_number"):
        donation_doc.anbi_agreement_number = form_data.anbi_agreement_number
        donation_doc.anbi_agreement_date = getdate(form_data.get("anbi_agreement_date", getdate()))

    try:
        get_public_donation_service()._save_donation_as_system_user(
            donation_doc,
            "insert",
            "public_donation_creation",
            f"Creating donation for public donation: {donor.donor_email} amount €{form_data.amount}",
        )
    except Exception as e:
        frappe.log_error(
            message=f"Failed to create donation record: {str(e)}",
            title="Donation Creation Security",
        )
        frappe.throw(_("Unable to process donation: Failed to create donation record"))

    # Donation records are no longer submittable - they remain as saved documents
    # Payment processing will update the donation with payment details via webhook

    return donation_doc


def process_payment_method(donation, form_data):
    """
    Process payment based on selected method using PaymentHook.

    This function delegates to the unified PaymentHook service while maintaining
    backward compatibility with the existing response format.
    """
    payment_method = form_data.payment_method

    # Map form payment method names to PaymentHook method IDs
    method_mapping = {
        "Bank Transfer": PaymentHook.BANK_TRANSFER,
        "SEPA Direct Debit": PaymentHook.SEPA,
        "Mollie": PaymentHook.MOLLIE,
        "Ponto": PaymentHook.PONTO,
        "Cash": PaymentHook.CASH,
    }

    hook_method = method_mapping.get(payment_method)
    if not hook_method:
        return {"status": "pending", "message": _("Payment method not yet implemented")}

    # Update donation's mode_of_payment before processing
    donation.mode_of_payment = payment_method
    try:
        get_public_donation_service()._save_donation_as_system_user(
            donation,
            "save",
            "public_donation_payment_update",
            f"Update donation {donation.name} with {payment_method} payment method",
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to update donation payment method: {str(e)}",
            "Donation Payment Method Update Error",
        )
        return {
            "status": "error",
            "message": _("Failed to process payment method"),
            "info": _("Please try again or contact support"),
        }

    # Build payer info from form data
    payer_info = {
        "email": form_data.get("donor_email"),
        "name": form_data.get("donor_name"),
        "iban": form_data.get("donor_iban"),
        "account_holder": form_data.get("account_holder") or form_data.get("donor_name"),
    }

    # Determine if recurring
    is_recurring = form_data.get("is_recurring") or form_data.get("donation_type") == "Recurring"
    interval = form_data.get("subscription_interval") or form_data.get("recurring_interval")

    # Build redirect URLs
    redirect_urls = {
        "success": form_data.get("success_url") or "/donation-success",
        "cancel": form_data.get("cancel_url") or "/donate",
    }

    # Call PaymentHook
    result = PaymentHook.initiate_payment(
        method=hook_method,
        amount=float(donation.amount),
        reference_doctype="Donation",
        reference_name=donation.name,
        payer_info=payer_info,
        redirect_urls=redirect_urls,
        recurring=is_recurring,
        interval=interval,
    )

    # Convert PaymentHook response to backward-compatible format
    return _convert_payment_hook_response(result)


def _convert_payment_hook_response(result: dict) -> dict:
    """
    Convert PaymentHook response format to backward-compatible format.

    PaymentHook returns:
        {"success": True, "action": "redirect", "data": {...}, "payment_id": "...", "message": "..."}

    Old format expected:
        {"status": "redirect_required", "payment_url": "...", "message": "..."}
    """
    from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentAction

    if not result.get("success"):
        return {
            "status": "error",
            "message": result.get("message", _("Payment processing failed")),
            "info": _("Please try again or contact support"),
        }

    action = result.get("action")
    data = result.get("data", {})

    # Map actions back to old status values
    if action == PaymentAction.REDIRECT:
        return {
            "status": "redirect_required",
            "payment_url": data.get("url"),
            "checkout_url": data.get("url"),  # Alias for compatibility
            "payment_id": result.get("payment_id"),
            "expires_at": data.get("expires_at"),
            "message": result.get("message"),
        }

    elif action == PaymentAction.MANDATE_FORM:
        return {
            "status": "mandate_required",
            "mandate_id": data.get("mandate_id"),
            "collection_date": data.get("collection_date"),
            "next_step": "sepa_mandate_form",
            "message": result.get("message"),
            "info": _("You will be redirected to set up a SEPA mandate"),
        }

    elif action == PaymentAction.SHOW_INSTRUCTIONS:
        # Could be bank transfer or cash
        if data.get("bank_details"):
            return {
                "status": "awaiting_transfer",
                "bank_details": data.get("bank_details"),
                "payment_reference": data.get("payment_reference"),
                "instructions": data.get("instructions"),
                "message": result.get("message"),
            }
        else:
            return {
                "status": "cash_pending",
                "reference": data.get("reference"),
                "instructions": data.get("instructions"),
                "contact_email": data.get("contact_email"),
                "office_hours": data.get("office_hours"),
                "message": result.get("message"),
            }

    # Fallback
    return {
        "status": "pending",
        "message": result.get("message", _("Payment initiated")),
        "data": data,
    }


def process_bank_transfer(donation, form_data):
    """Handle bank transfer payment"""
    donation.mode_of_payment = "Bank Transfer"
    try:
        get_public_donation_service()._save_donation_as_system_user(
            donation,
            "save",
            "public_donation_payment_update",
            f"Update donation {donation.name} with Bank Transfer payment method",
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to update donation with payment method: {str(e)}",
            "Donation Payment Method Update Error",
        )
        return {
            "status": "error",
            "message": _("Failed to process payment method"),
            "info": _("Please try again or contact support"),
        }

    from verenigingen.utils.settings_utils import get_payments_settings, get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(_("Unable to load system settings"), frappe.ValidationError)
    payments_settings = get_payments_settings()
    company = frappe.get_doc("Company", settings.company)

    # Generate payment reference
    payment_reference = f"DON-{donation.name}"

    # Get bank details from payments settings
    bank_details = {
        "account_holder": company.company_name,
        "iban": getattr(payments_settings, "company_iban", "NL00 BANK 0000 0000 00"),
        "bic": getattr(payments_settings, "company_bic", "BANKBIC2A"),
        "reference": payment_reference,
        "amount": donation.amount,
    }

    return {
        "status": "awaiting_transfer",
        "message": _("Please transfer the amount to our bank account"),
        "bank_details": bank_details,
        "instructions": _("Include the reference number in your transfer description"),
    }


def process_sepa_direct_debit(donation, form_data):
    """Handle SEPA direct debit setup"""
    donation.mode_of_payment = "SEPA Direct Debit"
    try:
        get_public_donation_service()._save_donation_as_system_user(
            donation,
            "save",
            "public_donation_payment_update",
            f"Update donation {donation.name} with SEPA Direct Debit payment method",
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to update donation with payment method: {str(e)}",
            "Donation Payment Method Update Error",
        )
        return {
            "status": "error",
            "message": _("Failed to process payment method"),
            "info": _("Please try again or contact support"),
        }

    # Would integrate with existing SEPA mandate system
    return {
        "status": "mandate_required",
        "message": _("SEPA mandate setup required"),
        "next_step": "sepa_mandate_form",
        "info": _("You will be redirected to set up a SEPA mandate for future collections"),
    }


def process_mollie_payment(donation, form_data):
    """Handle Mollie payment using the enhanced service layer architecture"""
    try:
        from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
            CompletePaymentService,
        )

        donation.mode_of_payment = "Mollie"
        try:
            get_public_donation_service()._save_donation_as_system_user(
                donation,
                "save",
                "public_donation_payment_update",
                f"Update donation {donation.name} with Mollie payment method",
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to update donation with payment method: {str(e)}",
                "Donation Payment Method Update Error",
            )
            return {
                "status": "error",
                "message": _("Failed to process payment method"),
                "info": _("Please try again or contact support"),
            }

        # Initialize enhanced payment service
        payment_service = CompletePaymentService()

        # Prepare form data for the new service
        payment_form_data = {
            "amount": str(donation.amount),
            "currency": "EUR",
            "return_url": f"{frappe.utils.get_url()}/donate?donation_id={donation.name}",
            "description": f"Donation to {frappe.get_single('Verenigingen Settings').company_name or frappe.get_value('Company', frappe.db.get_single_value('Verenigingen Settings', 'company'), 'company_name') or 'organization'}",
        }

        # Add payment method preference if specified
        if form_data.get("payment_method_preference"):
            payment_form_data["method"] = form_data["payment_method_preference"]

        # Check if this is a recurring donation (subscription)
        is_recurring = form_data.get("donation_status") == "Recurring"

        if is_recurring:
            # For recurring donations, use the dedicated recurring payment method that follows legacy pattern
            payment_form_data.update(
                {
                    "donor_email": form_data.get("email", ""),
                    "donor_name": f"{form_data.get('first_name', '')} {form_data.get('last_name', '')}".strip(),
                    "subscription_interval": form_data.get("recurring_interval", "1 month"),
                    "locale": "nl_NL",
                }
            )

            # Use the new recurring payment method that creates customer first
            result = payment_service.create_recurring_donation_payment(donation, payment_form_data)
        else:
            # Create single payment using enhanced service
            result = payment_service.create_donation_payment(donation, payment_form_data)

        return result

    except Exception as e:
        frappe.log_error(
            f"Enhanced Mollie payment processing error for donation {donation.name}: {str(e)}\nFull traceback: {frappe.get_traceback()}",
            "Enhanced Mollie Payment Error",
        )
        return {
            "status": "error",
            "message": _("Payment provider temporarily unavailable"),
            "info": _("Please try again later or use a different payment method"),
        }


# process_mollie_subscription function removed - now handled by MolliePaymentService


def process_cash_payment(donation, form_data):
    """Handle cash payment"""
    donation.mode_of_payment = "Cash"
    try:
        get_public_donation_service()._save_donation_as_system_user(
            donation,
            "save",
            "public_donation_payment_update",
            f"Update donation {donation.name} with Cash payment method",
        )
    except Exception as e:
        frappe.log_error(
            f"Failed to update donation with payment method: {str(e)}",
            "Donation Payment Method Update Error",
        )
        return {
            "status": "error",
            "message": _("Failed to process payment method"),
            "info": _("Please try again or contact support"),
        }

    return {
        "status": "cash_pending",
        "message": _("Cash payment registered"),
        "info": _("Please bring the cash to our office or pay at our next event"),
        "contact_info": _("Contact us for payment arrangements"),
    }


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
        payment_result = process_mollie_payment(donation, form_data)

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
