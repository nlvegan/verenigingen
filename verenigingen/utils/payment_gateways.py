"""
Payment Gateway Utilities - Redirect Handler

LEGACY REDIRECTS: These endpoints redirect old webhook URLs to the new simple webhook handler.
The old complex webhook handler has been archived due to broken donation creation logic.
"""

import frappe

from verenigingen.integrations.mollie.api.simple_donation_webhook import handle_payment_first_donation


@frappe.whitelist(allow_guest=True)
def mollie_subscription_webhook():
    """
    LEGACY REDIRECT: Old subscription webhook endpoint

    Redirects to the new simple webhook handler that properly handles:
    - Donation creation from payment metadata
    - Payment history updates
    - Refund processing (partial and full)
    """
    frappe.logger().info("⚠️ Legacy subscription webhook called - redirecting to simple handler")
    frappe.logger().info(
        f"🔄 Request headers: {dict(frappe.request.headers) if frappe.request else 'No request'}"
    )

    payload = frappe.request.get_data(as_text=True) if frappe.request else ""
    frappe.logger().info(f"🔄 Payload preview: {payload[:200]}...")

    # Redirect to the working simple webhook handler
    return handle_payment_first_donation()


@frappe.whitelist(allow_guest=True)
def mollie_payment_webhook():
    """
    Webhook endpoint for one-time payments

    Alternative webhook URL for Mollie dashboard configuration.
    Forwards to the same unified webhook handler.
    """
    frappe.logger().info("🔄 Payment webhook endpoint called")
    frappe.logger().info(
        f"🔄 Request headers: {dict(frappe.request.headers) if frappe.request else 'No request'}"
    )

    payload = frappe.request.get_data(as_text=True) if frappe.request else ""
    frappe.logger().info(f"🔄 Payment webhook payload preview: {payload[:200]}...")

    # Redirect to the working webhook handler
    from verenigingen.integrations.mollie.api.payment_webhook import (
        handle_mollie_payment_webhook as working_handler,
    )

    return working_handler()


@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Simplified Mollie webhook handler for existing donations"""
    frappe.logger().info("🔄 Main Mollie webhook redirecting to service handler")
    from verenigingen.api.mollie_donation_webhook import handle_mollie_payment_webhook

    return handle_mollie_payment_webhook()
