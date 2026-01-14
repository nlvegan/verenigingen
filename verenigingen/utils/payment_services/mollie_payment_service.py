"""
Mollie Payment Service - Compatibility Layer

This module provides backward compatibility for the original mollie_payment_service.py
while redirecting to the new service layer architecture.
"""

from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.verenigingen_payments.mollie.exceptions import (
    MollieAPIError,
    MolliePaymentError,
    MollieValidationError,
)
from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import CompletePaymentService


class MolliePaymentService:
    """
    Backward compatibility wrapper for the original MolliePaymentService.

    This class maintains the original API while delegating to the new service layer.
    """

    def __init__(self, mollie_settings=None):
        """Initialize with backward compatibility."""
        self.mollie_settings = mollie_settings
        self._complete_service = CompletePaymentService()

    def create_single_payment(self, donation_doc: Any, form_data: Dict[str, Any]) -> Any:
        """
        Create single payment using new service layer.

        Args:
            donation_doc: Donation document instance
            form_data: Form data from frontend

        Returns:
            Payment creation result from service layer
        """
        return self._complete_service.create_donation_payment(donation_doc, form_data)

    def create_payment(self, payment_data: Dict[str, Any]) -> Any:
        """
        Create payment from dictionary data.

        This method handles the case where payment_data is a dict that may contain
        either a donation document reference or the complete payment information.

        Args:
            payment_data: Payment information dict. Should contain either:
                - 'donation' or 'donation_name': Name of existing Donation document
                - Or direct payment fields for CompletePaymentService

        Returns:
            Payment creation result

        Raises:
            frappe.ValidationError: If required fields are missing
        """
        # Extract donation reference if present
        donation_name = payment_data.get("donation") or payment_data.get("donation_name")

        if donation_name:
            # Load the donation document and delegate to create_single_payment
            try:
                donation_doc = frappe.get_doc("Donation", donation_name)
                # Use remaining payment_data as form_data
                form_data = {k: v for k, v in payment_data.items() if k not in ("donation", "donation_name")}
                return self.create_single_payment(donation_doc, form_data)
            except frappe.DoesNotExistError:
                frappe.log_error(
                    f"Donation {donation_name} not found for payment creation",
                    "Mollie Payment Service",
                )
                return {
                    "status": "error",
                    "message": _("Donation not found: {0}").format(donation_name),
                }

        # No donation reference found - return validation error
        # The Mollie payment flow requires a Donation document for proper tracking
        frappe.log_error(
            f"Payment creation attempted without donation reference. Data keys: {list(payment_data.keys())}",
            "Mollie Payment Service",
        )
        return {
            "status": "error",
            "message": _("A donation reference is required. Include 'donation' or 'donation_name' in payment data."),
        }

    def get_payment(self, payment_id: str) -> Any:
        """Get payment using new service layer."""
        return self._complete_service.client.get_payment(payment_id)

    def process_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process webhook using new service layer.

        Args:
            webhook_data: Webhook payload from Mollie. Should contain 'id' field
                with the payment ID.

        Returns:
            Webhook processing result
        """
        # Extract payment ID from webhook data
        payment_id = webhook_data.get("id") or webhook_data.get("payment_id")

        if not payment_id:
            frappe.log_error(
                f"Webhook data missing payment ID: {webhook_data}",
                "Mollie Webhook Processing",
            )
            return {
                "status": "error",
                "message": _("Missing payment ID in webhook data"),
            }

        return self._complete_service.process_webhook(payment_id, webhook_data)

    def create_refund(self, payment_id: str, amount: float, description: str = "") -> Dict[str, Any]:
        """
        Create a refund for a payment.

        Args:
            payment_id: Mollie payment ID
            amount: Refund amount
            description: Refund description

        Returns:
            Dict with refund status and details
        """
        # Validate inputs
        if not payment_id:
            return {
                "status": "error",
                "message": _("Payment ID is required"),
                "payment_id": payment_id,
            }

        if amount <= 0:
            return {
                "status": "error",
                "message": _("Refund amount must be positive"),
                "payment_id": payment_id,
            }

        try:
            # Build refund data according to Mollie API format
            refund_data = {"amount": {"currency": "EUR", "value": f"{amount:.2f}"}}

            if description:
                refund_data["description"] = description

            # Use the client from the complete service layer
            refund = self._complete_service.client.create_refund(payment_id, refund_data)

            # Handle different response types (object vs dict)
            if hasattr(refund, "id"):
                refund_id = refund.id
            elif isinstance(refund, dict):
                refund_id = refund.get("id")
            else:
                refund_id = str(refund)

            return {
                "status": "success",
                "refund_id": refund_id,
                "amount": amount,
                "payment_id": payment_id,
            }

        except MollieValidationError as e:
            frappe.log_error(
                f"Validation error creating refund for {payment_id}: {e}",
                "Mollie Refund Validation",
            )
            return {
                "status": "error",
                "message": _("Invalid refund request: {0}").format(str(e)),
                "payment_id": payment_id,
            }

        except MollieAPIError as e:
            frappe.log_error(
                f"Mollie API error creating refund for {payment_id}: {e}",
                "Mollie Refund API Error",
            )
            return {
                "status": "error",
                "message": _("Payment provider error: {0}").format(str(e)),
                "payment_id": payment_id,
            }

        except MolliePaymentError as e:
            frappe.log_error(
                f"Payment error creating refund for {payment_id}: {e}",
                "Mollie Refund Payment Error",
            )
            return {
                "status": "error",
                "message": _("Refund processing error: {0}").format(str(e)),
                "payment_id": payment_id,
            }

        except Exception as e:
            # Catch-all for unexpected errors - log full details for debugging
            frappe.log_error(
                f"Unexpected error creating refund for {payment_id}: {type(e).__name__}: {e}",
                "Mollie Refund Unexpected Error",
            )
            return {
                "status": "error",
                "message": _("An unexpected error occurred while processing the refund"),
                "payment_id": payment_id,
            }


def get_mollie_gateway_settings():
    """
    DEPRECATED - DO NOT USE. This function has zero production callers.

    Get Mollie gateway settings for backward compatibility.

    Deprecation Notice:
        This function is deprecated and will be removed in the next major release.
        Use MollieConfigurationService via get_mollie_config() instead for non-password fields,
        or access the DocType controller directly for password field access.

    Returns:
        Mollie Settings document or None

    Raises:
        DeprecationWarning: Always raised to alert about deprecated usage
    """
    import warnings

    # Log security alert for dead code access
    frappe.log_error(
        f"SECURITY ALERT: Deprecated get_mollie_gateway_settings() called by {frappe.session.user}. "
        f"This function has zero production callers and should not be used.",
        "Deprecated Function Access",
    )

    # Raise deprecation warning
    warnings.warn(
        "get_mollie_gateway_settings() is deprecated and will be removed in v2.0. "
        "Use MollieConfigurationService.get_mollie_config() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    try:
        return frappe.get_single("Mollie Settings")
    except Exception as e:
        frappe.log_error(f"Failed to get Mollie settings: {e}", "Mollie Compatibility")
        return None


def process_mollie_payment(payment_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process Mollie payment using new service layer.

    Args:
        payment_data: Payment information

    Returns:
        Payment processing result
    """
    try:
        service = MolliePaymentService()
        return service.create_payment(payment_data)
    except Exception as e:
        frappe.log_error(f"Payment processing failed: {e}", "Mollie Compatibility")
        return {"status": "error", "message": str(e)}


# Backward compatibility exports
__all__ = ["MolliePaymentService", "get_mollie_gateway_settings", "process_mollie_payment"]
