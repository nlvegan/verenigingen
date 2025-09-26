"""
Mollie Payment API Endpoints

API endpoints for creating and managing Mollie payments.
"""

from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def create_payment(donation_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a Mollie payment for a donation.

    Args:
        donation_data: Payment data including amount, donor information, etc.

    Returns:
        Dict containing payment creation result
    """
    try:
        if not donation_data:
            donation_data = frappe.local.form_dict

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Create payment
        result = service.create_payment(donation_data)

        frappe.logger().info(f"Mollie payment created successfully")

        return {"status": "success", "payment_data": result}

    except Exception as e:
        frappe.logger().error(f"Mollie payment creation failed: {e}")
        frappe.log_error(f"Mollie payment creation failed: {str(e)}", "Mollie Payment API")

        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def get_payment_status(payment_id: str) -> Dict[str, Any]:
    """
    Get the status of a Mollie payment.

    Args:
        payment_id: Mollie payment ID

    Returns:
        Dict containing payment status information
    """
    try:
        if not payment_id:
            payment_id = frappe.local.form_dict.get("payment_id")

        if not payment_id:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Payment ID is required"}

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Get payment status
        payment_data = service.get_payment(payment_id)

        return {"status": "success", "payment": payment_data}

    except Exception as e:
        frappe.logger().error(f"Failed to get Mollie payment status: {e}")
        frappe.log_error(f"Failed to get Mollie payment status: {str(e)}", "Mollie Payment API")

        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}
