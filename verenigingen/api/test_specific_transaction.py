"""
Test specific transaction webhook
"""

import hashlib
import hmac
import json

import frappe
import requests

from verenigingen.utils.security_decorators import development_only


@frappe.whitelist()
@development_only()
def test_transaction_webhook(payment_id="tr_RguKBdskXAwRhRYACAfEJ"):
    """Test webhook for specific transaction"""

    # Check current donation status
    try:
        donation = frappe.get_doc("Donation", "Assoc-Dnt-2025-01135")
        current_status = {
            "paid": donation.paid,
            "payment_id": donation.get("payment_id"),
            "amount": donation.amount,
        }
    except:
        current_status = {"error": "Donation not found"}

    # Get webhook secret from Mollie Settings
    settings = frappe.get_single("Mollie Settings")
    webhook_secret = settings.get_webhook_secret()

    if not webhook_secret:
        return {"error": "No webhook secret configured", "current_status": current_status}

    # Create test payload
    payload = json.dumps({"id": payment_id})

    # Generate HMAC signature
    signature = hmac.new(webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    signature_header = f"sha256={signature}"

    # Make signed request
    headers = {"Content-Type": "application/json", "X-Mollie-Signature": signature_header}

    url = "https://dev.veganisme.net/api/method/verenigingen.utils.payment_gateways.mollie_payment_webhook"

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=30)

        return {
            "before_webhook": current_status,
            "webhook_response": {"status_code": response.status_code, "response_text": response.text[:1000]},
            "payment_id": payment_id,
        }
    except Exception as e:
        return {"error": str(e), "current_status": current_status}
