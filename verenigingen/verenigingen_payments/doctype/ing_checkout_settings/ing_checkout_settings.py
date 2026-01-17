# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import OperationType, public_api


class INGCheckoutSettings(Document):
    """
    Singleton configuration for ING Checkout (Pay.nl) integration.

    Stores API credentials and configuration for:
    - iDEAL payments
    - SEPA Direct Debit
    """

    def validate(self):
        """Validate settings before save."""
        if self.enabled:
            self._validate_credentials()
        self._generate_webhook_url()

    def _validate_credentials(self):
        """Ensure required credentials are provided when enabled."""
        if not self.service_id:
            frappe.throw(_("Service ID is required when integration is enabled"))
        if not self.token_code:
            frappe.throw(_("Token Code is required when integration is enabled"))
        if not self.api_token:
            frappe.throw(_("API Token is required when integration is enabled"))

        # Validate format
        if self.service_id and not self.service_id.startswith("SL-"):
            frappe.throw(_("Service ID must start with 'SL-' (e.g., SL-1234-5678)"))
        if self.token_code and not self.token_code.startswith("AT-"):
            frappe.throw(_("Token Code must start with 'AT-' (e.g., AT-1234-5678)"))

    def _generate_webhook_url(self):
        """Generate the webhook URL for Pay.nl exchange notifications."""
        base_url = get_url()
        self.webhook_url = (
            f"{base_url}/api/method/"
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment"
        )

    def get_api_credentials(self) -> dict:
        """
        Get API credentials for Pay.nl requests.

        Returns:
            dict with token_code, api_token, and service_id
        """
        if not self.enabled:
            frappe.throw(_("ING Checkout integration is not enabled"))

        return {
            "token_code": self.token_code,
            "api_token": self.get_password("api_token"),
            "service_id": self.service_id,
            "sandbox_mode": bool(self.sandbox_mode),
        }

    def get_base_url(self) -> str:
        """
        Get the appropriate API base URL based on sandbox mode.

        Returns:
            API base URL string
        """
        # Pay.nl uses the same endpoints for sandbox/production
        # Sandbox is controlled by the API credentials
        return "https://connect.pay.nl"

    def get_rest_url(self) -> str:
        """
        Get the REST API URL for management operations.

        Returns:
            REST API base URL string
        """
        return "https://rest.pay.nl"


def get_ing_checkout_settings() -> INGCheckoutSettings:
    """
    Get the ING Checkout Settings singleton.

    Returns:
        INGCheckoutSettings document

    Raises:
        frappe.ValidationError if settings not configured
    """
    settings = frappe.get_single("ING Checkout Settings")
    if not settings.enabled:
        frappe.throw(
            _("ING Checkout integration is not enabled. Please configure it in ING Checkout Settings.")
        )
    return settings


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def is_ing_checkout_enabled() -> dict:
    """
    Check if ING Checkout is enabled (for client-side use).

    Returns:
        dict with enabled status
    """
    settings = frappe.get_single("ING Checkout Settings")
    return {"enabled": bool(settings.enabled)}
