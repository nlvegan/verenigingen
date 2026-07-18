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
from frappe.utils import flt, getdate

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_document_operation,
    secure_user_context,
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
        secure_document_operation(allow_system_user=True) fails for them.  This
        helper switches to the configured system user via secure_user_context()
        instead — the same pattern used for donor creation elsewhere.
        """
        system_user = get_system_user_for_operation(operation_context)
        with secure_user_context(system_user, description):
            getattr(doc, operation)()
            frappe.db.commit()


_service_instance = None


def get_public_donation_service() -> PublicDonationService:
    """Get or create the PublicDonationService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = PublicDonationService()
    return _service_instance
