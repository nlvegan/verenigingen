#!/usr/bin/env python3
"""
Subscription Diagnostic Functions
Quick diagnostics for subscription processing issues
"""

from datetime import datetime, timedelta

import frappe


@frappe.whitelist()
def check_member_subscription_status(member_name="Assoc-Member-2025-07-0030"):
    """Check subscription processing status for a specific member"""

    results = {
        "timestamp": datetime.now().isoformat(),
        "member_name": member_name,
        "member_check": {},
        "subscription_check": {},
        "invoice_check": {},
        "processing_test": {},
    }

    # 1. Check member exists
    member = frappe.db.get_value(
        "Member",
        member_name,
        ["name", "status", "current_membership_start", "current_membership_end", "member_since"],
        as_dict=True,
    )
    results["member_check"]["member"] = member

    # 2. Check member's subscriptions
    subscriptions = frappe.get_all(
        "Subscription",
        filters={"party": member_name},
        fields=["name", "status", "docstatus", "current_invoice_start", "current_invoice_end"],
    )
    results["subscription_check"]["subscriptions"] = subscriptions

    # 3. Check member's invoices
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": member_name},
        fields=["name", "posting_date", "subscription", "grand_total", "status"],
        order_by="posting_date desc",
    )
    results["invoice_check"]["invoices"] = invoices

    # 4. Check if any subscriptions should generate invoices
    for subscription in subscriptions:
        if subscription.get("status") == "Active":
            try:
                from verenigingen.utils.subscription_processing import SubscriptionHandler

                handler = SubscriptionHandler(subscription["name"])
                should_generate = handler._should_generate_invoice()
                results["subscription_check"][subscription["name"]] = {
                    "should_generate_invoice": should_generate
                }
            except Exception as e:
                results["subscription_check"][subscription["name"]] = {"error": str(e)}

    # 5. Check system-wide subscription processing
    today = datetime.now().date()
    today_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"creation": [">=", today], "subscription": ["!=", ""]},
        fields=["name", "customer", "subscription", "creation"],
    )
    results["processing_test"]["today_invoices"] = today_invoices

    return results


@frappe.whitelist()
def get_subscription_system_status():
    """Get overall subscription system status"""

    results = {"timestamp": datetime.now().isoformat(), "system_status": {}}

    # Check active subscriptions
    active_subscriptions = frappe.db.count("Subscription", {"status": "Active"})
    results["system_status"]["active_subscriptions"] = active_subscriptions

    # Check sales invoices with subscriptions today
    today = datetime.now().date()
    today_subscription_invoices = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM `tabSales Invoice`
        WHERE DATE(creation) = %s
        AND subscription IS NOT NULL
        AND subscription != ''
    """,
        (today,),
    )[0][0]
    results["system_status"]["today_subscription_invoices"] = today_subscription_invoices

    # Check total subscription invoices
    total_subscription_invoices = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM `tabSales Invoice`
        WHERE subscription IS NOT NULL
        AND subscription != ''
    """
    )[0][0]
    results["system_status"]["total_subscription_invoices"] = total_subscription_invoices

    # Check scheduler logs
    scheduler_logs = frappe.get_all(
        "Scheduled Job Log",
        filters={"scheduled_job_type": ["like", "%process_all_subscription%"]},
        fields=["name", "status", "creation"],
        order_by="creation desc",
        limit=10,
    )
    results["system_status"]["scheduler_logs"] = scheduler_logs

    return results


@frappe.whitelist()
def check_scheduler_logs():
    """Check recent scheduler logs for subscription processing"""

    # Get recent scheduler logs
    logs = frappe.get_all(
        "Scheduled Job Log",
        filters={"creation": [">=", datetime.now().date() - timedelta(days=7)]},
        fields=["name", "scheduled_job_type", "status", "creation"],
        order_by="creation desc",
        limit=50,
    )

    # Filter for subscription-related logs
    subscription_logs = []
    for log in logs:
        if "subscription" in log.get("scheduled_job_type", "").lower():
            subscription_logs.append(log)

    return {
        "timestamp": datetime.now().isoformat(),
        "subscription_logs": subscription_logs,
        "all_recent_logs": logs,
    }


@frappe.whitelist()
def test_specific_subscription(subscription_name):
    """Test processing a specific subscription"""
    try:
        from verenigingen.utils.subscription_processing import SubscriptionHandler

        handler = SubscriptionHandler(subscription_name)
        should_generate = handler._should_generate_invoice()

        # Get subscription details
        subscription = frappe.get_doc("Subscription", subscription_name)

        # Try to process it
        result = handler.process_subscription()

        return {
            "subscription": subscription_name,
            "subscription_details": {
                "status": subscription.status,
                "current_invoice_start": subscription.current_invoice_start,
                "current_invoice_end": subscription.current_invoice_end,
                "party": subscription.party,
            },
            "should_generate": should_generate,
            "processing_result": result,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {"subscription": subscription_name, "error": str(e), "timestamp": datetime.now().isoformat()}
