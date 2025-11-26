"""
Check webhook processing logs
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_webhook_logs(payment_id="tr_RguKBdskXAwRhRYACAfEJ") -> OperationResult[Dict[str, Any]]:
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
        except Exception:
            donation_status = {"error": _("Donation not found")}

        data = {
            "payment_id": payment_id,
            "specific_logs": specific_logs,
            "recent_logs": recent_summary,
            "donation_status": donation_status,
        }

        message = _("Webhook logs retrieved for payment {0}").format(payment_id)
        if specific_logs:
            message = _("Found {0} webhook logs for payment {1}").format(len(specific_logs), payment_id)

        return OperationResult.ok(data, message=message)

    except Exception as e:
        frappe.log_error(
            title=_("Webhook Logs Check Failed"),
            message=traceback.format_exc(),
        )
        return OperationResult.fail(
            _("Failed to retrieve webhook logs"),
            errors=[str(e)],
            context={"payment_id": payment_id, "traceback": traceback.format_exc()},
        )
