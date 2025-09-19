"""
Mollie Sync API Endpoints

API endpoints for synchronizing data between Mollie and the local system.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, standard_api

from ..core.mollie_client import MollieClient
from ..core.mollie_exceptions import MollieIntegrationError
from ..services.payment_service import PaymentService
from ..services.subscription_service import SubscriptionService
from ..utils.audit import log_mollie_security_event


@frappe.whitelist(methods=["POST"])
@standard_api(operation_type=OperationType.FINANCIAL_SYNC)
def sync_payment_status(payment_id: str) -> Dict[str, Any]:
    """
    Synchronize payment status with Mollie.

    Args:
        payment_id: Mollie payment ID to sync

    Returns:
        Sync result with updated payment information
    """
    try:
        if not payment_id:
            raise MollieIntegrationError("Payment ID is required")

        payment_service = PaymentService()

        # Get current payment status from Mollie
        payment_status = payment_service.get_payment_status(payment_id)

        # Update local records if payment is completed
        processing_result = None
        if payment_status["is_paid"]:
            processing_result = payment_service.process_payment_completion(payment_id)

        return {
            "status": "success",
            "payment_id": payment_id,
            "payment_status": payment_status,
            "processing_result": processing_result,
            "synced_at": now_datetime(),
        }

    except Exception as e:
        frappe.log_error(f"Error syncing payment status for {payment_id}: {e}", "Mollie Payment Sync")
        raise MollieIntegrationError(f"Failed to sync payment status: {e}")


@frappe.whitelist(methods=["POST"])
@standard_api(operation_type=OperationType.FINANCIAL_SYNC)
def sync_subscription_status(customer_id: str, subscription_id: str) -> Dict[str, Any]:
    """
    Synchronize subscription status with Mollie.

    Args:
        customer_id: Mollie customer ID
        subscription_id: Mollie subscription ID

    Returns:
        Sync result with updated subscription information
    """
    try:
        if not customer_id or not subscription_id:
            raise MollieIntegrationError("Customer ID and Subscription ID are required")

        subscription_service = SubscriptionService()

        # Get current subscription status from Mollie
        subscription_status = subscription_service.get_subscription_status(customer_id, subscription_id)

        # Update local records based on status
        local_updates = _update_local_subscription_records(subscription_status)

        return {
            "status": "success",
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "subscription_status": subscription_status,
            "local_updates": local_updates,
            "synced_at": now_datetime(),
        }

    except Exception as e:
        frappe.log_error(
            f"Error syncing subscription status for {subscription_id}: {e}", "Mollie Subscription Sync"
        )
        raise MollieIntegrationError(f"Failed to sync subscription status: {e}")


@frappe.whitelist(methods=["POST"])
@standard_api(operation_type=OperationType.FINANCIAL_SYNC)
def sync_customer_payments(customer_id: str, limit: int = 50) -> Dict[str, Any]:
    """
    Synchronize all payments for a customer.

    Args:
        customer_id: Mollie customer ID
        limit: Maximum number of payments to sync

    Returns:
        Sync result with payment information
    """
    try:
        if not customer_id:
            raise MollieIntegrationError("Customer ID is required")

        client = MollieClient()

        # Get customer payments from Mollie
        payments = client.list_customer_payments(customer_id, limit=limit)

        # Process each payment
        sync_results = []
        for payment in payments:
            try:
                payment_data = {
                    "id": payment.id,
                    "amount": float(payment.amount.amount),
                    "currency": payment.amount.currency,
                    "status": payment.status,
                    "paid_at": payment.paid_at,
                    "method": payment.method,
                    "description": payment.description,
                }

                # Check if we need to process this payment
                if payment.is_paid:
                    # Check if already processed locally
                    existing_log = frappe.db.exists(
                        "Mollie Audit Log",
                        {"event_type": "payment_completed", "event_data": ("like", f"%{payment.id}%")},
                    )

                    if not existing_log:
                        # Process the payment
                        payment_service = PaymentService()
                        processing_result = payment_service.process_payment_completion(payment.id)
                        payment_data["processing_result"] = processing_result

                sync_results.append(payment_data)

            except Exception as e:
                frappe.log_error(
                    f"Error processing payment {payment.id} during sync: {e}", "Customer Payment Sync"
                )
                sync_results.append({"id": payment.id, "error": str(e)})

        return {
            "status": "success",
            "customer_id": customer_id,
            "payments_synced": len(sync_results),
            "payments": sync_results,
            "synced_at": now_datetime(),
        }

    except Exception as e:
        frappe.log_error(f"Error syncing customer payments for {customer_id}: {e}", "Mollie Customer Sync")
        raise MollieIntegrationError(f"Failed to sync customer payments: {e}")


@frappe.whitelist(methods=["POST"])
@standard_api(operation_type=OperationType.FINANCIAL_SYNC)
def sync_member_subscriptions(member_id: str) -> Dict[str, Any]:
    """
    Synchronize subscriptions for a specific member.

    Args:
        member_id: Frappe member document ID

    Returns:
        Sync result with subscription information
    """
    try:
        if not member_id:
            raise MollieIntegrationError("Member ID is required")

        # Get member record
        member = frappe.get_doc("Member", member_id)

        if not member.mollie_customer_id:
            return {
                "status": "skipped",
                "message": "Member has no Mollie customer ID",
                "member_id": member_id,
            }

        subscription_service = SubscriptionService()

        # Get member's subscriptions
        subscriptions = subscription_service.list_member_subscriptions(member_id)

        # Sync each subscription
        sync_results = []
        for subscription in subscriptions:
            try:
                # Get latest status from Mollie
                status = subscription_service.get_subscription_status(
                    member.mollie_customer_id, subscription["id"]
                )

                # Update local records
                local_updates = _update_member_subscription_status(member, status)

                sync_results.append(
                    {"subscription_id": subscription["id"], "status": status, "local_updates": local_updates}
                )

            except Exception as e:
                frappe.log_error(
                    f"Error syncing subscription {subscription['id']}: {e}", "Member Subscription Sync"
                )
                sync_results.append({"subscription_id": subscription["id"], "error": str(e)})

        return {
            "status": "success",
            "member_id": member_id,
            "subscriptions_synced": len(sync_results),
            "subscriptions": sync_results,
            "synced_at": now_datetime(),
        }

    except Exception as e:
        frappe.log_error(
            f"Error syncing member subscriptions for {member_id}: {e}", "Member Subscription Sync"
        )
        raise MollieIntegrationError(f"Failed to sync member subscriptions: {e}")


@frappe.whitelist(methods=["POST"])
@standard_api(operation_type=OperationType.SYSTEM_MAINTENANCE)
def bulk_sync_recent_payments(hours: int = 24) -> Dict[str, Any]:
    """
    Bulk synchronize recent payments.

    Args:
        hours: Number of hours back to sync (default: 24)

    Returns:
        Bulk sync results
    """
    try:
        # Security check - limit bulk operations to reasonable timeframes
        if hours > 168:  # 1 week
            log_mollie_security_event(
                "bulk_sync_limit_exceeded",
                f"Bulk sync requested for {hours} hours (max: 168)",
                {"requested_hours": hours, "user": frappe.session.user},
                "warning",
            )
            hours = 168

        # Get recent payment IDs from audit logs
        from frappe.utils import add_hours

        cutoff_time = add_hours(now_datetime(), -hours)

        recent_payment_logs = frappe.db.sql(
            """
            SELECT DISTINCT
                JSON_UNQUOTE(JSON_EXTRACT(event_data, '$.payment_id')) as payment_id
            FROM `tabMollie Audit Log`
            WHERE event_category = 'payment'
            AND event_type = 'payment_created'
            AND timestamp >= %(cutoff_time)s
            AND JSON_UNQUOTE(JSON_EXTRACT(event_data, '$.payment_id')) IS NOT NULL
        """,
            {"cutoff_time": cutoff_time},
            as_dict=True,
        )

        # Sync each payment
        payment_service = PaymentService()
        sync_results = {"synced": 0, "errors": 0, "skipped": 0, "details": []}

        for log in recent_payment_logs:
            payment_id = log.payment_id
            if not payment_id:
                continue

            try:
                # Check current status
                payment_status = payment_service.get_payment_status(payment_id)

                result = {"payment_id": payment_id, "status": payment_status["status"]}

                # Process if completed and not already processed
                if payment_status["is_paid"]:
                    # Check if already processed
                    completed_log = frappe.db.exists(
                        "Mollie Audit Log",
                        {"event_type": "payment_completed", "event_data": ("like", f"%{payment_id}%")},
                    )

                    if not completed_log:
                        processing_result = payment_service.process_payment_completion(payment_id)
                        result["processing_result"] = processing_result
                        sync_results["synced"] += 1
                    else:
                        result["already_processed"] = True
                        sync_results["skipped"] += 1
                else:
                    result["not_completed"] = True
                    sync_results["skipped"] += 1

                sync_results["details"].append(result)

            except Exception as e:
                frappe.log_error(f"Error in bulk sync for payment {payment_id}: {e}", "Bulk Payment Sync")
                sync_results["errors"] += 1
                sync_results["details"].append({"payment_id": payment_id, "error": str(e)})

        return {
            "status": "completed",
            "timeframe_hours": hours,
            "results": sync_results,
            "synced_at": now_datetime(),
        }

    except Exception as e:
        frappe.log_error(f"Error in bulk payment sync: {e}", "Bulk Payment Sync")
        raise MollieIntegrationError(f"Failed to perform bulk sync: {e}")


def _update_local_subscription_records(subscription_status: Dict[str, Any]) -> Dict[str, Any]:
    """Update local subscription records based on Mollie status."""
    updates = {"updated_records": 0, "errors": []}

    try:
        subscription_id = subscription_status["id"]
        customer_id = subscription_status["customer_id"]

        # Find member with this subscription
        members = frappe.db.get_all(
            "Member", {"mollie_customer_id": customer_id, "mollie_subscription_id": subscription_id}, ["name"]
        )

        for member_record in members:
            try:
                member = frappe.get_doc("Member", member_record.name)
                member.subscription_status = subscription_status["status"]
                member.next_payment_date = subscription_status.get("next_payment_date")
                member.save(ignore_permissions=True)
                updates["updated_records"] += 1

            except Exception as e:
                updates["errors"].append(f"Failed to update member {member_record.name}: {e}")

    except Exception as e:
        updates["errors"].append(f"General error updating records: {e}")

    return updates


def _update_member_subscription_status(member, subscription_status: Dict[str, Any]) -> Dict[str, Any]:
    """Update member subscription status."""
    try:
        member.subscription_status = subscription_status["status"]
        member.next_payment_date = subscription_status.get("next_payment_date")
        member.save(ignore_permissions=True)

        return {
            "updated": True,
            "status": subscription_status["status"],
            "next_payment_date": subscription_status.get("next_payment_date"),
        }

    except Exception as e:
        return {"updated": False, "error": str(e)}
