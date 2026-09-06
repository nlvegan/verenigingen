"""
Public Donation Service

Business logic for the public donation portal (`templates/pages/donate.py`),
extracted from the page controller. Handles donation orchestration, creation,
payment dispatch, and the secure guest-donation write helpers.

PaymentHook / Mollie imports are function-level (not module-top) to avoid a
load-order cycle: the Donation DocType controller imports services.donation.*.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.secure_operations import (
    save_as_system_user,
    secure_document_operation,
)


class PublicDonationService(StatelessService):
    """Business logic for the public donation portal page."""

    def __init__(self):
        super().__init__(service_name="PublicDonationService")

    @staticmethod
    def map_donation_status(status_value):
        """Map form donation status to DocType status values"""
        status_mapping = {
            "One-time donation": "One-time",
            "Monthly recurring": "Recurring",
            "Promised donation": "Promised",
            "One-time": "One-time",
            "Recurring": "Recurring",
            "Promised": "Promised",
        }
        return status_mapping.get(status_value, "One-time")

    def create_donation(self, donor, form_data, *, draft=False):
        """Create a Donation from public-form data.

        draft=True  -> Mollie payment-first flow: status 'Promised', campaign set
                       directly, explicit validate(), info log (mirrors the old
                       create_draft_donation_for_payment).
        draft=False -> traditional flow: status from map_donation_status, campaign
                       existence-checked with notes-fallback, ANBI fields (mirrors
                       the old create_donation_record).
        """
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        if not settings:
            frappe.throw(
                _("Verenigingen Settings not configured. Please run app installation setup."),
                frappe.ValidationError,
            )

        purpose_type = form_data.get("donation_purpose_type", "General")
        donation_doc = frappe.new_doc("Donation")
        donation_data = {
            "company": settings.company,
            "donor": donor.name,
            "donation_date": getdate(),
            "amount": flt(form_data.amount),
            "mode_of_payment": form_data.get("payment_method"),
            "status": (
                "Promised"
                if draft
                else self.map_donation_status(form_data.get("donation_status", "One-time"))
            ),
            "donation_purpose_type": purpose_type,
            "donation_notes": form_data.get("donation_notes", ""),
            # get_top_donors() already filters `anonymous = 0` (donation_campaign.py),
            # but nothing on either public form set the field, so it was always 0 --
            # an anonymous donor showed up in the campaign's top-donor list anyway.
            "anonymous": cint(form_data.get("anonymous", 0)),
            "paid": 0,
        }

        if draft:
            if purpose_type == "Campaign" and form_data.get("campaign_reference"):
                donation_data["campaign"] = form_data["campaign_reference"]
            elif purpose_type == "Chapter" and form_data.get("chapter_reference"):
                donation_data["chapter_reference"] = form_data["chapter_reference"]
            elif purpose_type == "Specific Goal" and form_data.get("specific_goal_description"):
                donation_data["specific_goal_description"] = form_data["specific_goal_description"]
        else:
            if purpose_type == "Campaign" and form_data.get("campaign_reference"):
                campaign_ref = form_data.get("campaign_reference")
                if frappe.db.exists("Donation Campaign", campaign_ref):
                    donation_data["campaign"] = campaign_ref
                else:
                    user_notes = donation_data.get("donation_notes", "")
                    donation_data["donation_notes"] = (
                        f"Campaign: {campaign_ref}\n\n{user_notes}"
                        if user_notes
                        else f"Campaign: {campaign_ref}"
                    )
            if purpose_type == "Chapter" and form_data.get("chapter_reference"):
                donation_data["chapter_reference"] = form_data.get("chapter_reference")
            if purpose_type == "Specific Goal" and form_data.get("specific_goal_description"):
                donation_data["specific_goal_description"] = form_data.get("specific_goal_description")

        donation_doc.update(donation_data)

        if not draft and form_data.get("anbi_agreement_number"):
            donation_doc.anbi_agreement_number = form_data.anbi_agreement_number
            donation_doc.anbi_agreement_date = getdate(form_data.get("anbi_agreement_date", getdate()))

        if draft:
            donation_doc.validate()  # preserve the explicit pre-insert validate() of the old draft path

        try:
            self._save_donation_as_system_user(
                donation_doc,
                "insert",
                "public_donation_draft_creation" if draft else "public_donation_creation",
                (
                    f"Creating draft donation for public donation: {donor.donor_email}"
                    if draft
                    else f"Creating donation for public donation: {donor.donor_email} amount €{form_data.amount}"
                ),
            )
        except Exception as e:
            if draft:
                frappe.log_error(
                    f"Failed to create draft donation: {str(e)}", "Public Donation - Draft Creation Error"
                )
            else:
                frappe.log_error(
                    message=f"Failed to create donation record: {str(e)}",
                    title="Donation Creation Security",
                )
            frappe.throw(_("Unable to process donation: Failed to create donation record"))

        if draft:
            frappe.logger().info(
                f"Created draft donation for public donation: {donor.donor_name} amount €{form_data.amount}"
            )

        return donation_doc

    def _save_donation_as_system_user(self, doc, operation, operation_context, description):
        """Save or insert a donation/donor document using system user context.

        PUBLIC DONATION FLOW: Guests lack roles in ESCALATION_ALLOWED_ROLES so
        secure_document_operation(allow_system_user=True) fails for them. See
        verenigingen.utils.secure_operations.save_as_system_user for why.
        """
        save_as_system_user(doc, operation, operation_context, description)

    def process_payment_method(self, donation, form_data):
        """
        Process payment based on selected method using PaymentHook.

        This function delegates to the unified PaymentHook service while maintaining
        backward compatibility with the existing response format.
        """
        from verenigingen.verenigingen_payments.hooks import PaymentHook

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
            self._save_donation_as_system_user(
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
        return self._convert_payment_hook_response(result)

    def _convert_payment_hook_response(self, result: dict) -> dict:
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

    def submit(self, form_data):
        """Process donation form submission (moved from donate.py:submit_donation).

        Orchestrates validation, donor resolution, and payment-method dispatch
        (Mollie payment-first flow vs. traditional create-then-pay flow) for
        the public donation form endpoint.
        """
        try:
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
            from verenigingen.services.donation.donor_service import get_donation_donor_service

            donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
            if not donor:
                return {"success": False, "message": _("Failed to create donor record")}

            # For Mollie payments: payment-first flow (no donation created yet)
            if form_data.get("payment_method") == "Mollie":
                try:
                    # Create draft donation (not submitted) with metadata for payment
                    donation = self.create_donation(donor, form_data, draft=True)
                    if not donation:
                        return {"success": False, "message": _("Failed to create donation record")}

                    # Process Mollie payment (creates payment, donation will be submitted by webhook)
                    payment_result = self.process_mollie_payment(donation, form_data)

                    # Wrap result in expected format for frontend
                    if payment_result.get("status") in [
                        "redirect_required",
                        "subscription_redirect_required",
                    ]:
                        return {
                            "success": True,
                            "donation_id": donation.name,
                            "payment_info": payment_result,
                        }
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
                donation = self.create_donation(donor, form_data, draft=False)
                if not donation:
                    return {"success": False, "message": _("Failed to create donation record")}

                # Process payment based on method
                try:
                    payment_result = self.process_payment_method(donation, form_data)
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

    def resolve_return_payment_status(self, donation):
        """Determine payment status/title for a donor returning from payment.

        Moved verbatim from donate.py:get_context (the donation.paid /
        donation.payment_id / Mollie-client branch). Returns a dict the
        controller applies to `context`; the frappe.DoesNotExistError
        handling for a missing donation stays in get_context itself.
        """
        if donation.paid:
            return {"payment_status": "success", "title": _("Donation Successful")}

        if not donation.payment_id:
            return {"payment_status": "pending", "title": _("Payment Pending")}

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
                return {
                    "payment_status": "success",
                    "title": _("Payment Successful"),
                    "payment_pending_webhook": True,  # Webhook hasn't processed yet
                }
            elif mollie_status in ["open", "pending"]:
                return {"payment_status": "pending", "title": _("Payment Pending")}
            elif mollie_status in ["failed", "canceled", "expired"]:
                return {"payment_status": "failed", "title": _("Payment Failed")}
            else:
                return {"payment_status": "pending", "title": _("Payment Status Unknown")}

        except Exception as e:
            frappe.log_error(f"Failed to check Mollie payment status for {donation.payment_id}: {str(e)}")
            return {"payment_status": "pending", "title": _("Payment Status Unknown")}

    def get_donation_status_data(self, donation_id):
        """Get donation status for tracking (moved from donate.py:get_donation_status)."""
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

    def mark_donation_paid_impl(self, donation_id, payment_reference=None):
        """Mark donation as paid (moved from donate.py:mark_donation_paid)."""
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

    def retry_payment_impl(self, donation_id):
        """Retry payment for a failed donation (moved from donate.py:retry_payment).

        Returns the payment_url on success; raises otherwise (the outer
        except wraps every failure, including "no redirect obtained", into
        the generic "Unable to retry payment" error, matching the original
        endpoint's behavior).
        """
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
            payment_result = self.process_mollie_payment(donation, form_data)

            # If successful, return the payment URL
            if payment_result.get("status") == "redirect_required":
                payment_url = payment_result.get("payment_url") or payment_result.get("checkout_url")
                if payment_url:
                    return payment_url

            # If redirect failed, raise so the except below wraps it consistently
            frappe.throw(_("Failed to create retry payment. Please try again or contact support."))

        except Exception as e:
            frappe.log_error(
                f"Payment retry error for donation {donation_id}: {str(e)}", "Payment Retry Error"
            )
            frappe.throw(_("Unable to retry payment. Please try again or contact support."))

    def process_mollie_payment(self, donation, form_data):
        """Handle Mollie payment using the enhanced service layer architecture"""
        try:
            from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
                CompletePaymentService,
            )

            donation.mode_of_payment = "Mollie"
            try:
                self._save_donation_as_system_user(
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
                        # donate.html posts `donor_email` / `donor_name` (the
                        # form collects input `name=` attributes, and those are
                        # the names). `email`/`first_name`/`last_name` are posted
                        # by nothing -- donate.py puts them in the PAGE CONTEXT to
                        # prefill the fields, which never reaches form_data. So
                        # this built the Mollie customer with an empty email and
                        # an empty name for every recurring donation. Same defect
                        # as the interval below, same file, one loop later.
                        "donor_email": form_data.get("donor_email") or form_data.get("email", ""),
                        "donor_name": (
                            form_data.get("donor_name")
                            or f"{form_data.get('first_name', '')} {form_data.get('last_name', '')}".strip()
                        ),
                        # donate.html posts `subscription_interval` (the hidden input the
                        # frequency buttons write). Reading only `recurring_interval` --
                        # a key nothing sends -- meant every recurring donation fell to
                        # the "1 month" default, so a quarterly or annual donor was
                        # billed monthly. Same precedence as line 210.
                        "subscription_interval": form_data.get("subscription_interval")
                        or form_data.get("recurring_interval", "1 month"),
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


_service_instance = None


def get_public_donation_service() -> PublicDonationService:
    """Get or create the PublicDonationService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = PublicDonationService()
    return _service_instance
