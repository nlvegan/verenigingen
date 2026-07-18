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
