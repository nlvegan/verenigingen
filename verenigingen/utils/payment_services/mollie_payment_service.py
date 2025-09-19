"""
Mollie Payment Service - Compatibility Layer

This module provides backward compatibility for the original mollie_payment_service.py
while redirecting to the new service layer architecture.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.integrations.mollie.services.complete_payment_service import CompletePaymentService

# Import from new service layer
from verenigingen.integrations.mollie.services.payment_service import PaymentService as NewPaymentService


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


def get_mollie_gateway_settings():
    """
    Get Mollie gateway settings for backward compatibility.

    Returns:
        Mollie Settings document or None
    """
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
