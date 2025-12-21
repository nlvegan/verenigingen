"""
Mollie Payment Service - Compatibility Layer

This module provides backward compatibility for the original mollie_payment_service.py
while redirecting to the new service layer architecture.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import CompletePaymentService

# Import from new service layer
from verenigingen.verenigingen_payments.mollie.services.payment_service import (
    PaymentService as NewPaymentService,
)


class MolliePaymentService:
    """
    Backward compatibility wrapper for the original MolliePaymentService.

    This class maintains the original API while delegating to the new service layer.
    """

    def __init__(self, mollie_settings=None):
        """Initialize with backward compatibility."""
        self.mollie_settings = mollie_settings
        self._new_service = NewPaymentService()
        self._complete_service = CompletePaymentService()

    def create_single_payment(self, donation_doc: Any, form_data: Dict[str, Any]) -> Any:
        """Create single payment using new service layer."""
        return self._new_service.create_single_payment(donation_doc, form_data)

    def create_payment(self, payment_data: Dict[str, Any]) -> Any:
        """Create payment using new service layer."""
        return self._new_service.create_single_payment(payment_data)

    def get_payment(self, payment_id: str) -> Any:
        """Get payment using new service layer."""
        return self._new_service.client.get_payment(payment_id)

    def process_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process webhook using new service layer."""
        return self._complete_service.process_payment_webhook(webhook_data)

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
        try:
            # This method is designed to be mockable in tests
            # When mocked, the test should return the expected structure directly
            # When not mocked, it calls the real Mollie client

            # Build refund data according to Mollie API format
            refund_data = {"amount": {"currency": "EUR", "value": f"{amount:.2f}"}}

            if description:
                refund_data["description"] = description

            # Use the client from the new service layer
            refund = self._new_service.client.create_refund(payment_id, refund_data)

            # Handle different response types (object vs dict)
            if hasattr(refund, "id"):
                refund_id = refund.id
            elif isinstance(refund, dict):
                refund_id = refund.get("id")
            else:
                # Fallback for unexpected types
                refund_id = str(refund)

            # Return standardized response
            return {
                "status": "success",
                "refund_id": refund_id,
                "amount": amount,
                "payment_id": payment_id,
            }
        except Exception as e:
            frappe.log_error(f"Failed to create refund for {payment_id}: {e}", "Mollie Refund")
            return {"status": "error", "message": str(e), "payment_id": payment_id}


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
