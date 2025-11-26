"""
Mollie Payment API Endpoints

API endpoints for creating and managing Mollie payments.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
def create_payment(donation_data: Dict[str, Any] = None) -> OperationResult[Dict[str, Any]]:
    """
    Create a Mollie payment for a donation.

    Args:
        donation_data: Payment data including amount, donor information, etc.

    Returns:
        OperationResult containing payment creation result
    """
    try:
        if not donation_data:
            donation_data = frappe.local.form_dict

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Create payment
        result = service.create_payment(donation_data)

        frappe.logger().info("Mollie payment created successfully")

        return OperationResult.ok({"payment_data": result}, message=_("Mollie payment created successfully"))

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Mollie payment creation failed: {error_msg}\n{traceback.format_exc()}")
        frappe.log_error(
            title="Mollie Payment API",
            message=f"Mollie payment creation failed: {error_msg}\n{traceback.format_exc()}",
        )

        return OperationResult.fail(
            error=_("Failed to create Mollie payment: {0}").format(error_msg), http_status=500
        )


@critical_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_payment_status(payment_id: str) -> OperationResult[Dict[str, Any]]:
    """
    Get the status of a Mollie payment.

    Args:
        payment_id: Mollie payment ID

    Returns:
        OperationResult containing payment status information
    """
    try:
        if not payment_id:
            payment_id = frappe.local.form_dict.get("payment_id")

        if not payment_id:
            return OperationResult.fail(error=_("Payment ID is required"), http_status=400)

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Get payment status
        payment_data = service.get_payment(payment_id)

        return OperationResult.ok(
            {"payment": payment_data}, message=_("Payment status retrieved successfully")
        )

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Failed to get Mollie payment status: {error_msg}\n{traceback.format_exc()}")
        frappe.log_error(
            title="Mollie Payment API",
            message=f"Failed to get Mollie payment status: {error_msg}\n{traceback.format_exc()}",
        )

        return OperationResult.fail(
            error=_("Failed to retrieve payment status: {0}").format(error_msg), http_status=500
        )
