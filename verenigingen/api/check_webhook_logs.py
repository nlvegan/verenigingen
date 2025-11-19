"""
Check webhook processing logs
"""

import frappe


@frappe.whitelist()
def check_webhook_logs(payment_id="tr_RguKBdskXAwRhRYACAfEJ"):
    """Check webhook logs for specific payment"""

    try:
        # Check for specific payment logs
        logs = frappe.get_all(
            "Webhook Processing Log",
            filters={"webhook_id": payment_id},
            fields=["name", "webhook_id", "status", "error_details", "creation"],
            order_by="creation desc",
        )

        specific_logs = []
        for log in logs:
            log_doc = frappe.get_doc("Webhook Processing Log", log.name)
            specific_logs.append(
                {
                    "name": log.name,
                    "status": log.status,
                    "error": log.error_details,
                    "created": str(log.creation),
                    "raw_payload": getattr(log_doc, "raw_payload", None),
                    "processing_result": getattr(log_doc, "processing_result", None),
                }
            )

        # Check recent logs
        recent_logs = frappe.get_all(
            "Webhook Processing Log",
            fields=["name", "webhook_id", "status", "error_details", "creation"],
            order_by="creation desc",
            limit=10,
        )

        recent_summary = []
        for log in recent_logs:
            recent_summary.append(
                {
                    "name": log.name,
                    "webhook_id": log.webhook_id,
                    "status": log.status,
                    "error": log.error_details,
                    "created": str(log.creation),
                }
            )

        # Check donation status
        donation_status = None
        try:
            donation = frappe.get_doc("Donation", "Assoc-Dnt-2025-01135")
            donation_status = {
                "paid": donation.paid,
                "payment_id": donation.get("payment_id"),
                "amount": donation.amount,
                "status": donation.docstatus,
            }
        except:
            donation_status = {"error": "Donation not found"}

        return {
            "payment_id": payment_id,
            "specific_logs": specific_logs,
            "recent_logs": recent_summary,
            "donation_status": donation_status,
        }

    except Exception as e:
        return {"error": str(e)}
