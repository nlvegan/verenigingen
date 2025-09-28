"""
Unified Mollie Payment API

A clean, unified API interface that exposes the new service layer functionality
through properly secured Frappe endpoints. This replaces the scattered webhook
endpoints with a comprehensive API.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    public_api,
    standard_api,
)

from ..exceptions import MolliePaymentError, MollieValidationError, MollieWebhookError
from ..services.webhook_wrapper_service_unified import get_unified_webhook_service


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.PUBLIC)
def handle_payment_webhook():
    """
    Unified webhook handler for all Mollie payment notifications.

    This endpoint handles webhooks for:
    - Single payments (donations)
    - Subscription payments
    - Refunds and chargebacks

    Returns:
        Dict with processing results
    """
    try:
        # Get payment ID from form data BEFORE authentication to avoid losing context
        payment_id = frappe.form_dict.get("id")
        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # Set webhook user context for proper permissions
        from ..utils.webhook_security import authenticate_mollie_webhook

        authenticate_mollie_webhook()

        frappe.logger().info(f"🔔 Webhook received for payment: {payment_id}")

        # Process webhook using UNIFIED service layer - eliminates fragmented idempotency
        service = get_unified_webhook_service()
        # Extract webhook data for processing
        webhook_data = frappe.form_dict or {}
        result = service.process_payment_webhook(payment_id, webhook_data)

        frappe.logger().info(f"✅ Webhook processed successfully: {payment_id}")
        return result

    except (MollieWebhookError, MolliePaymentError) as e:
        frappe.log_error(f"Mollie webhook error: {e}", "Mollie Webhook Error")
        frappe.response.http_status_code = 400
        return {"status": "error", "message": str(e)}

    except Exception as e:
        # Avoid logging during potential database connection issues
        try:
            frappe.log_error(f"Unexpected webhook error: {e}", "Webhook Processing Error")
        except:
            # Database connection may be lost, skip logging
            pass
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal processing error"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def create_donation_payment():
    """
    Create a payment for a donation.

    Expected form data:
    - donation_id: The donation document name
    - amount: Payment amount
    - currency: Payment currency (default: EUR)
    - return_url: URL to redirect after payment
    - method: Optional payment method restriction

    Returns:
        Dict with payment creation results
    """
    try:
        # Get form data
        donation_id = frappe.form_dict.get("donation_id")
        amount = frappe.form_dict.get("amount")
        currency = frappe.form_dict.get("currency", "EUR")
        return_url = frappe.form_dict.get("return_url")
        method = frappe.form_dict.get("method")

        if not donation_id:
            frappe.throw(_("Donation ID is required"))
        if not amount:
            frappe.throw(_("Amount is required"))
        if not return_url:
            frappe.throw(_("Return URL is required"))

        # Get donation document
        donation_doc = frappe.get_doc("Donation", donation_id)

        # Prepare form data for service
        form_data = {"amount": amount, "currency": currency, "return_url": return_url}
        if method:
            form_data["method"] = method

        # Create payment using service layer
        service = CompletePaymentService()
        result = service.create_donation_payment(donation_doc, form_data)

        return result

    except frappe.DoesNotExistError:
        frappe.throw(_("Donation not found"))
    except MollieValidationError as e:
        frappe.throw(_(str(e)))
    except MolliePaymentError as e:
        frappe.log_error(f"Payment creation error: {e}", "Payment Creation Error")
        frappe.throw(_("Failed to create payment. Please try again."))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_subscription():
    """
    Create a customer subscription for recurring payments.

    Expected form data:
    - customer_name: Customer full name
    - customer_email: Customer email address
    - amount: Subscription amount
    - currency: Payment currency (default: EUR)
    - interval: Payment interval (e.g., "1 month", "3 months")
    - description: Subscription description

    Returns:
        Dict with subscription creation results
    """
    try:
        # Get form data
        customer_name = frappe.form_dict.get("customer_name")
        customer_email = frappe.form_dict.get("customer_email")
        amount = frappe.form_dict.get("amount")
        currency = frappe.form_dict.get("currency", "EUR")
        interval = frappe.form_dict.get("interval")
        description = frappe.form_dict.get("description", "Recurring donation")

        if not customer_email:
            frappe.throw(_("Customer email is required"))
        if not amount:
            frappe.throw(_("Amount is required"))
        if not interval:
            frappe.throw(_("Payment interval is required"))

        # Prepare data for service
        customer_data = {"name": customer_name or customer_email, "email": customer_email}

        subscription_data = {
            "amount": {"currency": currency, "value": f"{float(amount):.2f}"},
            "interval": interval,
            "description": description,
        }

        # Create subscription using service layer
        service = CompletePaymentService()
        result = service.create_customer_subscription(customer_data, subscription_data)

        return result

    except MollieValidationError as e:
        frappe.throw(_(str(e)))
    except MolliePaymentError as e:
        frappe.log_error(f"Subscription creation error: {e}", "Subscription Creation Error")
        frappe.throw(_("Failed to create subscription. Please try again."))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_subscription():
    """
    Cancel a subscription.

    Expected form data:
    - customer_id: Mollie customer ID
    - subscription_id: Subscription ID to cancel
    - reason: Cancellation reason (optional)

    Returns:
        Dict with cancellation results
    """
    try:
        customer_id = frappe.form_dict.get("customer_id")
        subscription_id = frappe.form_dict.get("subscription_id")
        reason = frappe.form_dict.get("reason", "Customer request")

        if not customer_id:
            frappe.throw(_("Customer ID is required"))
        if not subscription_id:
            frappe.throw(_("Subscription ID is required"))

        # Cancel subscription using service layer
        service = CompletePaymentService()
        result = service.cancel_subscription(customer_id, subscription_id, reason)

        return result

    except MolliePaymentError as e:
        frappe.log_error(f"Subscription cancellation error: {e}", "Subscription Cancellation Error")
        frappe.throw(_("Failed to cancel subscription. Please try again."))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_payment_status():
    """
    Get the status of a payment.

    Expected form data:
    - payment_id: Mollie payment ID

    Returns:
        Dict with payment status information
    """
    try:
        payment_id = frappe.form_dict.get("payment_id")
        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # Get payment status using service layer
        service = CompletePaymentService()
        result = service.get_payment_status(payment_id)

        return result

    except MolliePaymentError as e:
        frappe.log_error(f"Payment status error: {e}", "Payment Status Error")
        frappe.throw(_("Failed to get payment status. Please try again."))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_client_info():
    """
    Get information about the Mollie client configuration.

    Returns:
        Dict with client configuration information
    """
    try:
        service = CompletePaymentService()
        result = service.get_client_info()
        return result

    except Exception as e:
        frappe.log_error(f"Client info error: {e}", "Client Info Error")
        frappe.throw(_("Failed to get client information"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_webhook_processing():
    """
    Test endpoint for webhook processing (development only).

    Expected form data:
    - payment_id: Test payment ID

    Returns:
        Dict with test results
    """
    try:
        if not frappe.conf.developer_mode:
            frappe.throw(_("Test endpoint only available in developer mode"))

        payment_id = frappe.form_dict.get("payment_id")
        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        frappe.logger().info(f"🧪 Testing webhook processing for: {payment_id}")

        # Test webhook processing
        service = CompletePaymentService()
        result = service.process_webhook(payment_id)

        return {
            "status": "test_success",
            "payment_id": payment_id,
            "result": result,
            "message": "Test webhook processing completed",
        }

    except Exception as e:
        frappe.log_error(f"Test webhook error: {e}", "Test Webhook Error")
        return {"status": "test_error", "message": str(e)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.PUBLIC)
def handle_refund_webhook():
    """
    Handle Mollie refund webhooks.

    This endpoint processes refund notifications from Mollie and creates
    appropriate reverse Payment Entries with donation history updates.

    Returns:
        Dict with refund processing results
    """
    try:
        # Set webhook user context for proper permissions
        from ..utils.webhook_security import authenticate_mollie_webhook

        authenticate_mollie_webhook()

        # Get the raw request body for webhook processing
        webhook_payload = frappe.request.get_data(as_text=True)
        if not webhook_payload:
            frappe.throw(_("Empty webhook payload"))

        frappe.logger().info(f"🔔 Refund webhook received, payload length: {len(webhook_payload)}")

        # Import the webhook wrapper service
        from ..services.webhook_wrapper_service import WebhookWrapperService

        # Process refund webhook using service layer
        service = WebhookWrapperService()
        result = service.process_refund_webhook(webhook_payload)

        frappe.logger().info(f"✅ Refund webhook processed successfully")
        return result

    except (MollieWebhookError, MolliePaymentError) as e:
        frappe.log_error(f"Mollie refund webhook error: {e}", "Mollie Refund Webhook Error")
        frappe.response.http_status_code = 400
        return {"status": "error", "message": str(e)}

    except Exception as e:
        frappe.log_error(f"Unexpected refund webhook error: {e}", "Refund Webhook Processing Error")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal refund processing error"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.PUBLIC)
def handle_chargeback_webhook():
    """
    Handle Mollie chargeback webhooks.

    This endpoint processes chargeback notifications from Mollie and creates
    appropriate reverse Payment Entries with donation history updates.

    Returns:
        Dict with chargeback processing results
    """
    try:
        # Set webhook user context for proper permissions
        from ..utils.webhook_security import authenticate_mollie_webhook

        authenticate_mollie_webhook()

        # Get the raw request body for webhook processing
        webhook_payload = frappe.request.get_data(as_text=True)
        if not webhook_payload:
            frappe.throw(_("Empty webhook payload"))

        frappe.logger().info(f"🔔 Chargeback webhook received, payload length: {len(webhook_payload)}")

        # Import the webhook wrapper service
        from ..services.webhook_wrapper_service import WebhookWrapperService

        # Process chargeback webhook using service layer
        service = WebhookWrapperService()
        result = service.process_chargeback_webhook(webhook_payload)

        frappe.logger().info(f"✅ Chargeback webhook processed successfully")
        return result

    except (MollieWebhookError, MolliePaymentError) as e:
        frappe.log_error(f"Mollie chargeback webhook error: {e}", "Mollie Chargeback Webhook Error")
        frappe.response.http_status_code = 400
        return {"status": "error", "message": str(e)}

    except Exception as e:
        frappe.log_error(f"Unexpected chargeback webhook error: {e}", "Chargeback Webhook Processing Error")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal chargeback processing error"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def initiate_refund():
    """
    Manually initiate a refund for a payment.

    Expected form data:
    - payment_id: Mollie payment ID to refund
    - amount: Refund amount (optional, defaults to full amount)
    - description: Refund description (optional)

    Returns:
        Dict with refund initiation results
    """
    try:
        payment_id = frappe.form_dict.get("payment_id")
        amount = frappe.form_dict.get("amount")
        description = frappe.form_dict.get("description", "Manual refund")

        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # Import the refund service
        from ..services.refund_chargeback_service import RefundChargebackService

        # Prepare refund data
        refund_data = {"description": description}
        if amount:
            refund_data["amount"] = {"currency": "EUR", "value": f"{float(amount):.2f}"}

        # Create refund using service layer
        service = RefundChargebackService()
        refund = service.client.create_refund(payment_id, refund_data)

        return {
            "status": "success",
            "refund_id": refund.id,
            "payment_id": payment_id,
            "amount": refund.amount.value,
            "message": "Refund initiated successfully",
        }

    except MolliePaymentError as e:
        frappe.log_error(f"Refund initiation error: {e}", "Refund Initiation Error")
        frappe.throw(_("Failed to initiate refund. Please try again."))

    except Exception as e:
        frappe.log_error(f"Unexpected refund error: {e}", "Refund Processing Error")
        frappe.throw(_("Internal refund processing error"))
