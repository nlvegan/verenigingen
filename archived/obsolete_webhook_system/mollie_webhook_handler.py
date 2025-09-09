"""
Mollie Webhook Handler

Provides test and live webhook endpoints that process Mollie payment notifications
and create donation records from payment metadata.
"""

import json
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.archived.obsolete_webhook_system.mollie_webhook_processor import MollieWebhookProcessor
from verenigingen.utils.webhook_security import authenticate_mollie_webhook


@frappe.whitelist()
def handle_mollie_webhook_test():
    """
    Test environment webhook handler for Mollie payments.

    Processes webhook notifications from Mollie's test API and creates
    donation records based on payment metadata.
    """
    return _process_mollie_webhook(environment="test")


@frappe.whitelist()
def handle_mollie_webhook_live():
    """
    Live environment webhook handler for Mollie payments.

    Processes webhook notifications from Mollie's live API and creates
    donation records based on payment metadata.
    """
    return _process_mollie_webhook(environment="live")


def _process_mollie_webhook(environment: str) -> Dict[str, Any]:
    """
    Unified webhook processing logic for both test and live environments.

    Args:
        environment: "test" or "live" to indicate which environment

    Returns:
        Dict with processing status and details
    """
    try:
        # Security verification
        if frappe.session.user == "Guest":
            frappe.set_user("Administrator")

        # Authenticate webhook
        try:
            payload = authenticate_mollie_webhook()
        except Exception as e:
            frappe.log_error(f"Webhook authentication failed ({environment}): {str(e)}", "Webhook Auth Error")
            return {"status": "error", "message": "Authentication failed"}

        # Process webhook with the dedicated processor
        processor = MollieWebhookProcessor(environment=environment)
        result = processor.process_webhook(payload)

        # Log successful processing
        frappe.logger().info(
            "Mollie webhook processed successfully (%s): %s", environment, result.get("payment_id", "unknown")
        )

        return result

    except Exception as e:
        error_msg = f"Webhook processing error ({environment}): {str(e)}"
        frappe.log_error(error_msg + f"\nTraceback: {frappe.get_traceback()}", "Mollie Webhook Error")

        return {
            "status": "error",
            "message": "Webhook processing failed",
            "environment": environment,
            "error_logged": True,
        }


# Additional utility functions for webhook management


@frappe.whitelist()
def get_webhook_status():
    """
    Get webhook processing statistics and health status.

    Useful for monitoring and debugging webhook processing.
    """
    try:
        # Get recent webhook processing logs
        recent_logs = frappe.db.sql(
            """
            SELECT creation, error, seen
            FROM `tabError Log`
            WHERE method LIKE '%mollie_webhook%'
            ORDER BY creation DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get webhook processing counts (would need a webhook log table)
        stats = {
            "recent_errors": len([log for log in recent_logs if log.error]),
            "total_recent": len(recent_logs),
            "last_processed": recent_logs[0]["creation"] if recent_logs else None,
            "webhook_endpoints": {
                "test": frappe.utils.get_url()
                + "/api/method/verenigingen.verenigingen_payments.utils.mollie_webhook_handler.handle_mollie_webhook_test",
                "live": frappe.utils.get_url()
                + "/api/method/verenigingen.verenigingen_payments.utils.mollie_webhook_handler.handle_mollie_webhook_live",
            },
        }

        return {"status": "success", "stats": stats}

    except Exception as e:
        frappe.log_error(f"Webhook status check error: {str(e)}", "Webhook Status Error")
        return {"status": "error", "message": "Failed to get webhook status"}


@frappe.whitelist()
def test_webhook_processor():
    """
    Test the webhook processor with sample data.

    Useful for development and debugging.
    """
    if not frappe.conf.get("developer_mode"):
        return {"status": "error", "message": "Only available in developer mode"}

    sample_webhook_data = {
        "id": "tr_test123456789",
        "resource": "payment",
        "amount": {"currency": "EUR", "value": "25.00"},
        "status": "paid",
        "description": json.dumps(
            {
                "type": "single_donation",
                "donation_id": "test_donation",
                "donor_email": "test@example.com",
                "donor_name": "Test Donor",
                "amount": 25.00,
                "purpose_type": "General",
            }
        ),
        "metadata": {"donation_id": "test_donation", "type": "single_donation"},
    }

    try:
        processor = MollieWebhookProcessor(environment="test")
        result = processor.process_webhook(json.dumps(sample_webhook_data))
        return {"status": "success", "test_result": result}

    except Exception as e:
        return {"status": "error", "message": str(e)}
