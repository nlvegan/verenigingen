"""
Test webhook with proper signature
"""

import hashlib
import hmac
import json

import frappe
import requests


@frappe.whitelist()
def test_signed_webhook():
    """Test webhook with proper signature"""

    # Get webhook secret from Mollie Settings
    settings = frappe.get_single("Mollie Settings")
    webhook_secret = settings.get_webhook_secret()

    if not webhook_secret:
        return {"error": "No webhook secret configured"}

    # Create test payload
    payload = json.dumps({"id": "tr_KgP5YCCuzpFjesmk6GeEJ"})

    # Generate HMAC signature
    signature = hmac.new(webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    signature_header = f"sha256={signature}"

    # Make signed request
    headers = {"Content-Type": "application/json", "X-Mollie-Signature": signature_header}

    url = "https://dev.veganisme.net/api/method/verenigingen.utils.payment_gateways.mollie_payment_webhook?env=test"

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=30)

        return {
            "status_code": response.status_code,
            "response_text": response.text[:1000],  # Truncate for readability
            "signature_used": signature_header[:30] + "...",
            "payload": payload,
        }
    except Exception as e:
        return {"error": str(e)}
