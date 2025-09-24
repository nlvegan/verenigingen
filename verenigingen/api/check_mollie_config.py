"""
Check Mollie configuration and webhook secret
"""

import frappe


@frappe.whitelist()
def check_mollie_config():
    """Check Mollie Settings configuration"""

    try:
        settings = frappe.get_single("Mollie Settings")

        # Get webhook secret (this calls the method that should return the secret)
        webhook_secret = settings.get_webhook_secret()

        config_info = {
            "test_mode": settings.get("test_mode"),
            "has_webhook_secret": bool(webhook_secret),
            "webhook_secret_length": len(webhook_secret) if webhook_secret else 0,
            "webhook_secret_preview": webhook_secret[:10] + "..." if webhook_secret else None,
            "testing_webhook_url": settings.get("testing_webhook_url"),
            "live_webhook_url": settings.get("live_webhook_url"),
            "has_test_secret_key": bool(settings.get("testing_webhook_secret_key")),
            "has_live_secret_key": bool(settings.get("live_webhook_secret_key")),
        }

        return config_info

    except Exception as e:
        return {"error": str(e)}
