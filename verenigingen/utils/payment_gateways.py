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
    Handles ping events directly, forwards others to unified handler.
    """
    frappe.logger().info("🔄 Payment webhook endpoint called")

    # CRITICAL: Log ALL raw webhook data BEFORE any processing
    try:
        headers = dict(frappe.request.headers) if frappe.request else {}
        payload = frappe.request.get_data(as_text=True) if frappe.request else ""
        form_data = frappe.local.form_dict or {}

        # Create comprehensive raw webhook log
        raw_webhook_data = {
            "timestamp": frappe.utils.now(),
            "headers": headers,
            "raw_payload": payload,
            "form_data": form_data,
            "method": frappe.request.method if frappe.request else None,
            "url": frappe.request.url if frappe.request else None,
            "content_type": frappe.request.content_type if frappe.request else None,
        }

        # Log to both frappe.log AND create a debug file
        frappe.logger().error(f"🔍 RAW WEBHOOK DATA: {frappe.as_json(raw_webhook_data)}")

        # Also save to Error Log for persistence
        frappe.log_error(
            title=f"Raw Webhook Debug - {frappe.utils.now()}",
            message=f"Raw webhook data:\n{frappe.as_json(raw_webhook_data, indent=2)}",
        )

        frappe.logger().info(f"🔄 Request headers: {headers}")
        frappe.logger().info(f"🔄 Payment webhook payload preview: {payload[:200]}...")

    except Exception as e:
        frappe.logger().error(f"❌ Failed to log raw webhook data: {e}")

    # Check for ping events AFTER logging raw data
    # Handle JSON ping events
    if payload:
        try:
            webhook_data = frappe.parse_json(payload)
            if webhook_data.get("resource") == "event" and webhook_data.get("type") == "hook.ping":
                frappe.logger().info("✅ Webhook ping event received - responding with success")
                # Log ping-specific data
                frappe.logger().error(f"🏓 PING EVENT RAW DATA: {frappe.as_json(raw_webhook_data)}")
                return {"status": "success", "message": "Webhook ping received"}
        except:
            pass  # Not JSON, continue to regular processing

    # Handle form data ping events
    form_data = frappe.local.form_dict or {}
    if form_data.get("type") == "hook.ping":
        frappe.logger().info("✅ Webhook ping event received (form data) - responding with success")
        # Log ping-specific data
        frappe.logger().error(f"🏓 PING EVENT RAW DATA: {frappe.as_json(raw_webhook_data)}")
        return {"status": "success", "message": "Webhook ping received"}

    # Handle different webhook formats from Mollie
    # Payment webhooks: form data without signatures
    # Event webhooks: JSON with signatures

    if headers.get("Content-Type") == "application/x-www-form-urlencoded":
        # This is a payment webhook (form data, no signature expected)
        frappe.logger().info("🔧 Processing form data payment webhook (no signature required)")
        from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

        return handle_payment_webhook()
    else:
        # This is a JSON webhook (event/ping, signature required)
        frappe.logger().info("🔧 Processing JSON event webhook (signature required)")
        from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

        return handle_payment_webhook()


@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Simplified Mollie webhook handler for existing donations"""
    frappe.logger().info("🔄 Main Mollie webhook redirecting to unified API")
    from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

    return handle_payment_webhook()
