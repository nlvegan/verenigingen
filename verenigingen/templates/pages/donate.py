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

from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_document_operation,
    secure_user_context,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
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


def _save_donation_as_system_user(doc, operation, operation_context, description):
    """Save or insert a donation/donor document using system user context.

    PUBLIC DONATION FLOW: Guests lack roles in ESCALATION_ALLOWED_ROLES so
    secure_document_operation(allow_system_user=True) fails for them.  This
    helper switches to the configured system user via secure_user_context()
    instead — the same pattern used for donor creation elsewhere in this file.

    Args:
        doc: Document to save/insert.
        operation: "insert" or "save".
        operation_context: Context key for get_system_user_for_operation().
        description: Human-readable description for the audit trail.

    Raises:
        Exception: Re-raises after logging so callers can handle it.
    """
    system_user = get_system_user_for_operation(operation_context)
    with secure_user_context(system_user, description):
        getattr(doc, operation)()
        frappe.db.commit()


def get_or_create_donor(form_data):
    """Get existing donor or create new one"""
    # Check if donor exists by email
    existing_donor = frappe.db.get_value("Donor", {"donor_email": form_data.donor_email})

    if existing_donor:
        # Update existing donor with any new information
        donor_doc = frappe.get_doc("Donor", existing_donor)
        if form_data.get("donor_phone") and not donor_doc.phone:
            donor_doc.phone = form_data.donor_phone

            # PUBLIC DONATION FLOW: Use secure context for updating donor records
            try:
                system_user = get_system_user_for_operation("public_donation_donor_update")
                with secure_user_context(
                    system_user, f"Updating donor phone for public donation: {existing_donor}"
                ):
                    donor_doc.save()
                    frappe.db.commit()
                frappe.logger().info(
                    f"Updated donor {existing_donor} with phone information from public donation form"
                )
            except Exception as e:
                frappe.log_error(
                    f"Failed to update donor information: {str(e)}", "Public Donation - Donor Update Error"
                )
                # Continue with donation processing even if phone update fails
        return donor_doc
    else:
        # Create new donor with explicit donor type fallback
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        if not settings:
            frappe.throw(_("Unable to load system settings"), frappe.ValidationError)
        donor_type = form_data.get("donor_type")
        if not donor_type:
            donor_type = getattr(settings, "default_donor_type", None)

        # Ensure donor_type is not None (fallback to Individual)
        if not donor_type:
            donor_type = "Individual"

        donor_doc = frappe.new_doc("Donor")
        donor_doc.update(
            {
                "donor_name": form_data.donor_name,
                "donor_email": form_data.donor_email,
                "phone": form_data.get("donor_phone", ""),
                "address": form_data.get("donor_address", ""),
                "donor_type": donor_type,
                "contact_person": form_data.donor_name,  # Use same name as contact person
                "donor_category": "Regular Donor",  # Default category
            }
        )

        # PUBLIC DONATION FLOW: Use configured system user for creating public donation records
        # This ensures proper permissions and ownership using the secure operations framework
        try:
            system_user = get_system_user_for_operation("public_donation_donor_creation")
            with secure_user_context(
                system_user, f"Creating donor for public donation: {form_data.donor_email}"
            ):
                donor_doc.insert()
                frappe.db.commit()

                # Set owner to system user for consistent ownership
                frappe.db.set_value("Donor", donor_doc.name, "owner", system_user)
                frappe.db.commit()

            frappe.logger().info(
                f"Created donor record for public donation: {form_data.donor_name} ({form_data.donor_email})"
            )
            return donor_doc

        except Exception as e:
            frappe.log_error(
                f"Failed to create donor record for public donation: {str(e)}",
                "Public Donation - Donor Creation Error",
            )
            frappe.throw(_("Unable to process donation: Failed to create donor record"))


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
        "status": map_donation_status(form_data.get("donation_status", "One-time")),
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
        _save_donation_as_system_user(
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
        _save_donation_as_system_user(
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
        _save_donation_as_system_user(
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
        _save_donation_as_system_user(
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
            _save_donation_as_system_user(
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
        _save_donation_as_system_user(
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


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_donation_system():
    """Test the donation system components"""

    results = {"status": "success", "tests": []}

    # Test 2: Check donor types (using hardcoded options)
    try:
        donor_types = [
            {"name": "Individual", "donor_type": "Individual"},
            {"name": "Organization", "donor_type": "Organization"},
        ]
        results["tests"].append(
            {"name": "Donor Types", "status": "pass", "count": len(donor_types), "details": donor_types}
        )
    except Exception as e:
        results["tests"].append({"name": "Donor Types", "status": "fail", "error": str(e)})

    # Test 3: Check Verenigingen Settings
    try:
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        if not settings:
            frappe.throw(_("Unable to load system settings"), frappe.ValidationError)
        results["tests"].append(
            {
                "name": "Settings",
                "status": "pass",
                "details": {
                    "default_donor_type": getattr(settings, "default_donor_type", None),
                    "anbi_minimum_amount": getattr(settings, "anbi_minimum_reportable_amount", None),
                    "chapter_management": getattr(settings, "enable_chapter_management", None),
                },
            }
        )
    except Exception as e:
        results["tests"].append({"name": "Settings", "status": "fail", "error": str(e)})

    # Test 4: Test donation page context
    try:
        context = frappe._dict()
        get_context(context)
        results["tests"].append(
            {
                "name": "Page Context",
                "status": "pass",
                "details": {
                    "payment_methods": len(context.get("payment_methods", [])),
                    "donor_types": len(context.get("donor_types", [])),
                    "chapters": len(context.get("chapters", [])),
                },
            }
        )
    except Exception as e:
        results["tests"].append({"name": "Page Context", "status": "fail", "error": str(e)})

    # Test 5: Test payment gateway components
    try:
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        supported_methods = PaymentGatewayFactory.get_supported_methods()
        results["tests"].append({"name": "Payment Gateways", "status": "pass", "methods": supported_methods})
    except Exception as e:
        results["tests"].append({"name": "Payment Gateways", "status": "fail", "error": str(e)})

    # Test 6: Test email utilities
    try:
        from verenigingen.utils.donation_emails import get_donation_email_template

        template = get_donation_email_template()
        results["tests"].append(
            {"name": "Email System", "status": "pass", "has_template": bool(template.get("subject"))}
        )
    except Exception as e:
        results["tests"].append({"name": "Email System", "status": "fail", "error": str(e)})

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_donation_submission():
    """Test the donation submission flow with sample data"""

    # Sample donation data
    test_data = {
        "donor_name": "Test Donor",
        "donor_email": "test@example.com",
        "donor_phone": "+31612345678",
        "donor_type": "Individual",
        "amount": "50.00",
        "donation_status": "One-time",
        "payment_method": "Bank Transfer",
        "donation_purpose_type": "General",
        "donation_notes": "Test donation from system test",
    }

    try:
        # Test the submission function
        result = submit_donation(**test_data)

        if result.get("success"):
            # Verify the donation was created
            donation_id = result.get("donation_id")
            donation_doc = frappe.get_doc("Donation", donation_id)

            # Check if donation is in submitted status
            status_text = {0: "DRAFT", 1: "SUBMITTED", 2: "CANCELLED"}.get(donation_doc.docstatus, "UNKNOWN")

            # Clean up the test donation (cancel first since it's submitted)
            if donation_doc.docstatus == 1:
                donation_doc.cancel()
            frappe.delete_doc("Donation", donation_id)

            # Check if a donor was created and clean it up too
            test_donor = frappe.db.get_value("Donor", {"donor_email": "test@example.com"})
            if test_donor:
                frappe.delete_doc("Donor", test_donor)

            return {
                "status": "success",
                "message": "Donation submission test passed",
                "donation_created": True,
                "donation_status": status_text,
                "docstatus": donation_doc.docstatus,
                "payment_info": result.get("payment_info", {}),
                "cleanup": "completed",
            }
        else:
            return {
                "status": "fail",
                "message": result.get("message", "Unknown error"),
                "donation_created": False,
            }

    except Exception as e:
        return {"status": "error", "message": str(e), "donation_created": False}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_doctype_access():
    """Test if verenigingen doctypes are accessible"""

    results = {"tests": [], "summary": ""}

    # Test doctypes
    doctypes_to_test = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_test:
        test_result = {"doctype": doctype_name, "tests": []}

        try:
            # Test 1: Can we access the doctype meta?
            meta = frappe.get_meta(doctype_name)
            test_result["tests"].append(f"✓ Meta accessible - app={meta.app}, module={meta.module}")

            # Test 2: Can we create a new document?
            frappe.new_doc(doctype_name)
            test_result["tests"].append("✓ Can create new document")

            # Test 3: Can we get list (empty is OK)?
            try:
                records = frappe.get_all(doctype_name, limit=1)
                test_result["tests"].append(f"✓ get_all works - found {len(records)} records")
            except Exception as e:
                test_result["tests"].append(f"✗ get_all failed: {e}")

            # Test 4: Check permissions
            has_perm = frappe.has_permission(doctype_name, "read")
            test_result["tests"].append(f"✓ Read permission: {has_perm}")

        except Exception as e:
            test_result["tests"].append(f"✗ Failed: {e}")

        results["tests"].append(test_result)

    # Check if DocType records exist in database
    db_check = []
    for doctype_name in doctypes_to_test:
        try:
            record = frappe.db.get_value("DocType", doctype_name, ["app", "module"], as_dict=True)
            if record:
                db_check.append(f"{doctype_name}: app={record.app}, module={record.module}")
            else:
                db_check.append(f"{doctype_name}: NOT FOUND in DocType table")
        except Exception as e:
            db_check.append(f"{doctype_name}: Error - {e}")

    results["database_check"] = db_check
    results["summary"] = "If all tests show ✓, the doctypes should be accessible in the interface."

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def create_test_data():
    """Create some test data for doctype accessibility testing"""

    results = {"created": [], "errors": []}

    try:
        # Create test Chapter (skip if complex requirements)
        try:
            if not frappe.db.exists("Chapter", "Test Chapter"):
                # First check if Region doctype exists
                if frappe.db.exists("DocType", "Region"):
                    # Try to get or create a test region
                    test_region = frappe.db.get_value("Region", limit=1)
                    if not test_region:
                        # Skip chapter creation if no regions exist
                        results["created"].append("Chapter: Skipped (no regions available)")
                    else:
                        doc = frappe.get_doc(
                            {
                                "doctype": "Chapter",
                                "name": "Test Chapter",
                                "region": test_region,
                                "postal_codes": "1000-1099",
                            }
                        )
                        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                        result = secure_document_operation(
                            operation="insert",
                            doc=doc,
                            justification="Create test Chapter 'Test Chapter' for system testing and chapter functionality",
                            required_permissions=["Chapter:create"],
                        )

                        if result.success:
                            results["created"].append("Chapter: Test Chapter")
                        else:
                            results["errors"].append(f"Failed to create Chapter: {'; '.join(result.errors)}")
                else:
                    results["created"].append("Chapter: Skipped (Region doctype not found)")
        except Exception as e:
            results["created"].append(f"Chapter: Failed - {str(e)}")

        # Create test Donor
        if not frappe.db.exists("Donor", {"donor_email": "test@example.com"}):
            doc = frappe.get_doc(
                {
                    "doctype": "Donor",
                    "donor_name": "Test Donor",
                    "donor_email": "test@example.com",
                    "phone": "+31612345678",
                    "donor_type": "Individual",
                    "contact_person": "Test Donor",
                    "contact_person_address": "Test Address",
                    "donor_category": "Regular Donor",
                }
            )
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="insert",
                doc=doc,
                justification="Create test Donor 'Test Donor' for system testing and donation form functionality",
                required_permissions=["Donor:create"],
            )

            if result.success:
                results["created"].append("Donor: Test Donor")
            else:
                results["errors"].append(f"Failed to create Donor: {'; '.join(result.errors)}")

        results["success"] = True

    except Exception as e:
        results["errors"].append(str(e))
        results["success"] = False

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_awesome_bar_search():
    """Test awesome bar search functionality specifically"""

    results = {"tests": [], "search_results": {}}

    # Test the actual awesome bar search function
    doctypes_to_test = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_test:
        test_result = {"doctype": doctype_name, "results": []}

        try:
            # Test 1: Check if doctype appears in global search
            from frappe.desk.search import search_link

            # Search for the doctype name itself
            search_results = search_link(doctype="DocType", txt=doctype_name, query=doctype_name, limit=10)
            test_result["results"].append(f"DocType search: {len(search_results)} results")

            # Test 2: Search for records within the doctype
            if frappe.db.count(doctype_name) > 0:
                record_search = search_link(doctype=doctype_name, txt="", query="", limit=10)
                test_result["results"].append(f"Record search: {len(record_search)} results")
            else:
                test_result["results"].append("Record search: No records to search")

            # Test 3: Check doctype visibility settings
            meta = frappe.get_meta(doctype_name)
            visibility_info = {
                "hidden": getattr(meta, "hidden", False),
                "issingle": getattr(meta, "issingle", False),
                "istable": getattr(meta, "istable", False),
                "search_fields": getattr(meta, "search_fields", ""),
                "title_field": getattr(meta, "title_field", ""),
                "show_name_in_global_search": getattr(meta, "show_name_in_global_search", False),
            }
            test_result["results"].append(f"Visibility: {visibility_info}")

        except Exception as e:
            test_result["results"].append(f"Error: {str(e)}")

        results["tests"].append(test_result)

    # Test 4: Check what doctypes ARE appearing in awesome bar
    try:
        all_visible_doctypes = frappe.db.sql(
            """
            SELECT name, app, module, hidden, issingle, istable
            FROM tabDocType
            WHERE app IS NOT NULL
            AND hidden = 0
            AND istable = 0
            AND module = 'Verenigingen'
            ORDER BY name
        """,
            as_dict=True,
        )

        results["verenigingen_doctypes"] = all_visible_doctypes

    except Exception as e:
        results["verenigingen_doctypes"] = f"Error: {str(e)}"

    # Test 5: Check global search configuration
    try:
        # Check if there are any search restrictions
        from verenigingen.utils.settings_utils import get_system_settings

        search_settings = get_system_settings()
        results["search_config"] = {
            "global_search_enabled": getattr(search_settings, "enable_global_search", True)
        }
    except Exception as e:
        results["search_config"] = f"Error: {str(e)}"

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_list_view_access():
    """Test direct list view access for doctypes"""

    results = {"tests": [], "summary": ""}

    # Test doctypes
    doctypes_to_test = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_test:
        test_result = {"doctype": doctype_name, "results": []}

        try:
            # Test 1: Check if we can get the list view
            from frappe.desk.listview import get_list_settings

            list_settings = get_list_settings(doctype_name)
            test_result["results"].append(f"✓ List settings accessible: {bool(list_settings)}")

            # Test 2: Check meta for list view fields
            meta = frappe.get_meta(doctype_name)
            list_fields = [f.fieldname for f in meta.fields if f.in_list_view]
            test_result["results"].append(
                f"✓ List view fields: {len(list_fields)} fields ({', '.join(list_fields[:3])}{'...' if len(list_fields) > 3 else ''})"
            )

            # Test 3: Check if doctype has custom list view
            custom_listview_path = f"verenigingen/verenigingen/doctype/{doctype_name.lower().replace(' ', '_')}/{doctype_name.lower().replace(' ', '_')}_list.js"
            test_result["results"].append(f"Custom list view expected at: {custom_listview_path}")

            # Test 4: Check permissions for list view
            has_read = frappe.has_permission(doctype_name, "read")
            has_select = frappe.has_permission(doctype_name, "select")
            test_result["results"].append(f"✓ Permissions - read: {has_read}, select: {has_select}")

            # Test 5: Try to simulate a list view call
            try:
                test_data = frappe.get_list(doctype_name, fields=["name"], limit=1, order_by="creation desc")
                test_result["results"].append(f"✓ get_list works: {len(test_data)} records")
            except Exception as e:
                test_result["results"].append(f"✗ get_list failed: {str(e)}")

        except Exception as e:
            test_result["results"].append(f"✗ Error: {str(e)}")

        results["tests"].append(test_result)

    # Test 6: Check overall list view system
    try:
        # Check if list view system is working for a known doctype
        user_list = frappe.get_list("User", fields=["name"], limit=1)
        results[
            "system_check"
        ] = f"✓ List view system working (User doctype accessible: {len(user_list)} records)"
    except Exception as e:
        results["system_check"] = f"✗ List view system issue: {str(e)}"

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_direct_url_access():
    """Test if we can generate the correct URLs for doctype list views"""

    results = {"url_tests": [], "summary": ""}

    doctypes_to_test = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_test:
        url_info = {"doctype": doctype_name}

        try:
            # Generate the expected list view URL
            url_doctype = doctype_name.lower().replace(" ", "-")
            expected_url = f"/app/{url_doctype}"
            url_info["expected_url"] = expected_url

            # Check if doctype can be found by URL name
            try:
                # This simulates what happens when you visit /app/chapter
                from frappe.desk.listview import get_list_settings

                settings = get_list_settings(doctype_name)
                url_info["list_settings"] = "Found" if settings else "Not found"
            except Exception as e:
                url_info["list_settings"] = f"Error: {str(e)}"

            # Check if we can create the doctype reference URL
            try:
                from frappe.utils import get_url_to_list

                list_url = get_url_to_list(doctype_name)
                url_info["frappe_list_url"] = list_url
            except Exception as e:
                url_info["frappe_list_url"] = f"Error: {str(e)}"

        except Exception as e:
            url_info["error"] = str(e)

        results["url_tests"].append(url_info)

    # Test if we can manually construct what the list view should return
    try:
        from frappe.desk.listview import get_list_settings, get_meta_json

        test_doctype = "Donation"
        meta_json = get_meta_json(test_doctype)
        results["meta_test"] = {
            "doctype": test_doctype,
            "meta_available": bool(meta_json),
            "meta_fields_count": len(meta_json.get("fields", [])) if meta_json else 0,
        }

    except Exception as e:
        results["meta_test"] = f"Error: {str(e)}"

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_doctype_routing():
    """Debug the doctype routing issue in detail"""

    results = {"debug_info": [], "routing_test": ""}

    doctypes_to_test = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_test:
        debug_info = {"doctype": doctype_name, "checks": []}

        try:
            # Check 1: Does the doctype exist in tabDocType?
            dt_exists = frappe.db.exists("DocType", doctype_name)
            debug_info["checks"].append(f"DocType exists: {dt_exists}")

            # Check 2: What is the module assignment?
            dt_info = frappe.db.get_value(
                "DocType", doctype_name, ["module", "istable", "issingle"], as_dict=True
            )
            debug_info["checks"].append(f"App info: {dt_info}")

            # Check 3: Does frappe.get_meta work?
            try:
                meta = frappe.get_meta(doctype_name)
                debug_info["checks"].append(f"Meta accessible: True, module={meta.module}")
            except Exception as e:
                debug_info["checks"].append(f"Meta error: {str(e)}")

            # Check 4: What happens with desk.page routing?
            try:
                # This is what happens when you click a workspace link
                pass

                # The error suggests it's looking for a Page, let's see what happens
                page_name = doctype_name.lower()
                page_exists = frappe.db.exists("Page", page_name)
                debug_info["checks"].append(f"Page '{page_name}' exists: {page_exists}")

                # Check the actual URL that would be generated
                url_name = doctype_name.lower().replace(" ", "-")
                debug_info["checks"].append(f"Expected URL: /app/{url_name}")

            except Exception as e:
                debug_info["checks"].append(f"Desk page error: {str(e)}")

            # Check 5: Test the actual workspace link
            try:
                workspace_link = frappe.db.get_value(
                    "Workspace Link",
                    {"parent": "Verenigingen", "link_to": doctype_name},
                    ["link_type", "link_to", "label"],
                    as_dict=True,
                )
                debug_info["checks"].append(f"Workspace link: {workspace_link}")
            except Exception as e:
                debug_info["checks"].append(f"Workspace link error: {str(e)}")

        except Exception as e:
            debug_info["checks"].append(f"General error: {str(e)}")

        results["debug_info"].append(debug_info)

    # Test the routing system more directly
    try:
        # Check what pages actually exist in the system
        existing_pages = frappe.db.sql(
            """
            SELECT name, page_name, title, module
            FROM tabPage
            WHERE name IN ('chapter', 'donor', 'donation-type', 'donation')
            OR page_name IN ('chapter', 'donor', 'donation-type', 'donation')
        """,
            as_dict=True,
        )

        results["existing_pages"] = existing_pages

        # Check how Frappe resolves URLs
        test_urls = ["/app/chapter", "/app/donor", "/app/donation-type", "/app/donation"]
        results["url_resolution"] = []

        for url in test_urls:
            try:
                # This is a simplified version of what Frappe does internally
                path_parts = url.strip("/").split("/")
                if len(path_parts) >= 2 and path_parts[0] == "app":
                    route_name = path_parts[1]

                    # Check if it's a Page first (this might be the issue)
                    page_exists = frappe.db.exists("Page", route_name)

                    # Check if it matches a DocType
                    doctype_candidates = frappe.db.sql(
                        """
                        SELECT name FROM tabDocType
                        WHERE LOWER(REPLACE(name, ' ', '-')) = %s
                        AND istable = 0 AND issingle = 0
                    """,
                        route_name,
                        as_dict=True,
                    )

                    results["url_resolution"].append(
                        {
                            "url": url,
                            "route_name": route_name,
                            "page_exists": page_exists,
                            "doctype_candidates": doctype_candidates,
                        }
                    )
            except Exception as e:
                results["url_resolution"].append({"url": url, "error": str(e)})

    except Exception as e:
        results["routing_test"] = f"Error: {str(e)}"

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def force_doctype_sync():
    """Force sync doctypes to ensure they're properly registered"""

    results = {"sync_results": [], "errors": []}

    doctypes_to_sync = ["Chapter", "Donor", "Donation"]

    try:
        # First, let's try to force sync these doctypes
        for doctype_name in doctypes_to_sync:
            try:
                # Get the doctype document and force reload it
                doc = frappe.get_doc("DocType", doctype_name)

                # Force reload the meta
                frappe.clear_cache(doctype=doctype_name)

                # Re-register the doctype
                from frappe.model.sync import sync_for

                sync_for(doc.module)

                results["sync_results"].append(f"✓ Synced {doctype_name}")

            except Exception as e:
                results["errors"].append(f"✗ Failed to sync {doctype_name}: {str(e)}")

        # Try to recreate the list view settings
        frappe.clear_cache()

        # Force reload all doctypes for the app

        app_path = frappe.get_app_path("verenigingen")

        results["sync_results"].append("✓ Cleared all caches")
        results["sync_results"].append(f"✓ App path: {app_path}")

    except Exception as e:
        results["errors"].append(f"General sync error: {str(e)}")

    # Test if the sync worked
    try:
        for doctype_name in doctypes_to_sync:
            # Test if we can access it now
            frappe.get_meta(doctype_name)
            count = frappe.db.count(doctype_name)
            results["sync_results"].append(f"✓ {doctype_name}: meta OK, {count} records")

    except Exception as e:
        results["errors"].append(f"Post-sync test error: {str(e)}")

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_workspace_links():
    """Test what happens when we simulate clicking workspace links"""

    results = {"tests": []}

    # Test all verenigingen workspace links
    workspace_links = frappe.get_all(
        "Workspace Link",
        filters={"parent": "Verenigingen", "link_type": "DocType"},
        fields=["link_to", "label", "type"],
    )

    for link in workspace_links:
        test_result = {"doctype": link.link_to, "label": link.label}

        try:
            # This simulates what happens when clicking a workspace link
            # The frontend makes a call to get the doctype list

            # Test 1: Can we get the list?
            records = frappe.get_list(link.link_to, limit=1)
            test_result["get_list"] = f"✓ Success ({len(records)} found)"

            # Test 2: Can we get the meta?
            meta = frappe.get_meta(link.link_to)
            test_result["get_meta"] = f"✓ Success (module: {meta.module})"

            # Test 3: Check if it has web view enabled
            dt_info = frappe.db.get_value(
                "DocType", link.link_to, ["has_web_view", "allow_guest_to_view"], as_dict=True
            )
            test_result[
                "web_view"
            ] = f"has_web_view: {dt_info.has_web_view}, allow_guest: {dt_info.allow_guest_to_view}"

            # Test 4: Check permissions
            has_read = frappe.has_permission(link.link_to, "read")
            test_result["permissions"] = f"read: {has_read}"

        except Exception as e:
            test_result["error"] = str(e)

        results["tests"].append(test_result)

    return results


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


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_frontend_routing():
    """Debug what the frontend is actually requesting"""

    results = {"debug_info": {}}

    # Check current state after our fixes
    doctypes_to_check = ["Chapter", "Donor", "Donation"]

    for doctype_name in doctypes_to_check:
        info = {"doctype": doctype_name}

        try:
            # Get current doctype settings
            dt_info = frappe.db.get_value(
                "DocType",
                doctype_name,
                ["has_web_view", "allow_guest_to_view", "route", "is_published_field"],
                as_dict=True,
            )

            info["settings"] = dt_info

            # Check if route field exists and has value
            if hasattr(frappe.get_meta(doctype_name), "has_field"):
                meta = frappe.get_meta(doctype_name)
                has_route_field = bool([f for f in meta.fields if f.fieldname == "route"])
                info["has_route_field"] = has_route_field

                # If it has route field, check if any records have routes set
                if has_route_field:
                    routes_count = frappe.db.count(doctype_name, {"route": ["!=", ""]})
                    info["records_with_routes"] = routes_count

            # Check URL patterns that might conflict
            expected_url = doctype_name.lower().replace(" ", "-")
            info["expected_url"] = f"/app/{expected_url}"

            # Test the exact error condition
            try:
                # This is what's failing - trying to get a Page
                page_exists = frappe.db.exists("Page", expected_url)
                info["conflicting_page"] = page_exists
            except Exception as e:
                info["page_check_error"] = str(e)

        except Exception as e:
            info["error"] = str(e)

        results["debug_info"][doctype_name] = info

    # Check if there are any cached routes that might conflict
    try:
        # Check website route rules that might conflict
        website_routes = frappe.db.sql(
            """
            SELECT name, route, ref_doctype
            FROM `tabWebsite Route`
            WHERE route IN ('chapter', 'donor', 'donation-type', 'donation')
        """,
            as_dict=True,
        )

        results["website_routes"] = website_routes

    except Exception as e:
        results["website_routes_error"] = str(e)

    # Provide debugging instructions for browser console
    results["browser_debug_instructions"] = {
        "step1": "Open browser dev console (F12)",
        "step2": "Go to Network tab",
        "step3": "Click on Chapter workspace link",
        "step4": "Look for the failing request in Network tab",
        "step5": "Check the request URL and response",
        "javascript_debug": "In console, run: frappe.route_options = {}; frappe.set_route('List', 'Chapter');",
    }

    return results


def map_donation_status(status_value):
    """Map form donation status to DocType status values"""
    status_mapping = {
        "One-time donation": "One-time",
        "Monthly recurring": "Recurring",
        "Promised donation": "Promised",
        "One-time": "One-time",  # Direct mapping
        "Recurring": "Recurring",  # Direct mapping
        "Promised": "Promised",  # Direct mapping
    }
    return status_mapping.get(status_value, "One-time")
