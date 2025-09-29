"""
Payment Gateway Utilities - Redirect Handler

LEGACY REDIRECTS: These endpoints redirect old webhook URLs to the new simple webhook handler.
The old complex webhook handler has been archived due to broken donation creation logic.
"""

import frappe

from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook


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

    # Redirect to the unified webhook handler
    return handle_payment_webhook()


@frappe.whitelist(allow_guest=True)
def mollie_payment_webhook():
    """
    Webhook endpoint for one-time payments

    Alternative webhook URL for Mollie dashboard configuration.
    Handles ping events directly, forwards others to unified handler.
    """
    try:
        frappe.logger().info("🔄 Payment webhook endpoint called")

        # STEP 1: Normalize webhook data - handle text/plain webhooks from Mollie
        # Get content type and payload safely
        content_type = str(frappe.request.content_type) if frappe.request else "None"

        # If text/plain, extract payment ID from raw body and normalize to form_dict
        if content_type == "text/plain":
            payload = frappe.request.get_data(as_text=True) if frappe.request else ""
            if payload and payload.strip().startswith("tr_"):
                frappe.logger().info(f"🔧 Normalizing text/plain webhook: {payload.strip()}")
                if not frappe.local.form_dict:
                    frappe.local.form_dict = {}
                frappe.local.form_dict["id"] = payload.strip()

        # STEP 2: Get normalized payment ID
        form_data = frappe.local.form_dict or {}
        payment_id = form_data.get("id")

        frappe.logger().info(f"🔄 Content-Type: {content_type}, Payment ID: {payment_id}")

        # Handle ping events
        if form_data.get("type") == "hook.ping":
            frappe.logger().info("✅ Webhook ping event received")
            return {"status": "success", "message": "Webhook ping received"}

        # Validate payment ID
        if not payment_id:
            frappe.logger().error("❌ No payment ID found in webhook")
            return {"status": "error", "message": "Payment ID is required"}

        # STEP 3: Forward to unified handler with clean parameter
        frappe.logger().info(f"🔧 Forwarding payment {payment_id} to unified handler")
        from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

        return handle_payment_webhook(payment_id=payment_id)

    except Exception as e:
        frappe.logger().error(f"❌ Webhook error: {e}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Simplified Mollie webhook handler for existing donations"""
    frappe.logger().info("🔄 Main Mollie webhook redirecting to unified API")
    from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

    return handle_payment_webhook()
