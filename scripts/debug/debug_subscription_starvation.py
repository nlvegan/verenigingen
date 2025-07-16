#!/usr/bin/env python3
"""
Debug script to investigate subscription starvation issue
Specifically looking at member "Assoc-Member-2025-07-0030" and overall subscription processing
"""

import frappe
from frappe.utils import today, add_days, add_months
from verenigingen.utils.subscription_processing import SubscriptionHandler, process_all_subscriptions


@frappe.whitelist()
def debug_member_subscription_status():
    """Check the subscription status for member Assoc-Member-2025-07-0030"""
    member_name = "Assoc-Member-2025-07-0030"
    
    # Check if member exists
    member = frappe.db.get_value(
        "Member", 
        member_name, 
        ["name", "status", "membership_start_date", "membership_end_date", "creation", "modified"],
        as_dict=True
    )
    
    if not member:
        return {"error": f"Member {member_name} not found"}
    
    # Get member's membership records
    memberships = frappe.get_all(
        "Membership",
        filters={"member": member_name},
        fields=["name", "membership_status", "from_date", "to_date", "creation", "modified"],
        order_by="creation desc"
    )
    
    # Get member's subscriptions
    subscriptions = frappe.get_all(
        "Subscription",
        filters={"party": member_name},
        fields=[
            "name", "status", "docstatus", "current_invoice_start", "current_invoice_end",
            "billing_interval", "billing_interval_count", "generate_invoice_at",
            "creation", "modified"
        ],
        order_by="creation desc"
    )
    
    # Get invoices for the member
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": member_name},
        fields=["name", "posting_date", "status", "grand_total", "subscription", "creation"],
        order_by="posting_date desc"
    )
    
    # Check subscription processing for active subscriptions
    subscription_details = []
    for sub in subscriptions:
        if sub.status == "Active":
            handler = SubscriptionHandler(sub.name)
            should_generate = handler._should_generate_invoice() if handler.subscription else False
            
            # Check if invoice exists for current period
            invoice_exists = False
            if handler.subscription:
                invoice_exists = handler._invoice_exists_for_period(
                    sub.current_invoice_start, sub.current_invoice_end
                )
            
            subscription_details.append({
                "subscription": sub,
                "should_generate_invoice": should_generate,
                "invoice_exists_for_period": invoice_exists,
                "today": today(),
                "days_until_period_end": (sub.current_invoice_end - today()).days if sub.current_invoice_end else None
            })
    
    return {
        "member": member,
        "memberships": memberships,
        "subscriptions": subscriptions,
        "subscription_details": subscription_details,
        "invoices": invoices,
        "total_active_subscriptions": len([s for s in subscriptions if s.status == "Active"])
    }


@frappe.whitelist()
def debug_all_subscription_processing():
    """Debug overall subscription processing across the system"""
    # Get all active subscriptions
    all_subscriptions = frappe.get_all(
        "Subscription",
        filters={"status": "Active", "docstatus": 1},
        fields=[
            "name", "party", "current_invoice_start", "current_invoice_end",
            "billing_interval", "billing_interval_count", "generate_invoice_at",
            "creation", "modified"
        ]
    )
    
    # Process statistics
    needs_processing = []
    processing_errors = []
    
    for sub in all_subscriptions:
        try:
            handler = SubscriptionHandler(sub.name)
            if handler.subscription:
                should_generate = handler._should_generate_invoice()
                if should_generate:
                    needs_processing.append({
                        "subscription": sub.name,
                        "party": sub.party,
                        "current_period_end": sub.current_invoice_end,
                        "days_overdue": (today() - sub.current_invoice_end).days if sub.current_invoice_end else None
                    })
        except Exception as e:
            processing_errors.append({
                "subscription": sub.name,
                "error": str(e)
            })
    
    return {
        "total_active_subscriptions": len(all_subscriptions),
        "needs_processing": needs_processing,
        "needs_processing_count": len(needs_processing),
        "processing_errors": processing_errors,
        "processing_errors_count": len(processing_errors)
    }


@frappe.whitelist()
def run_subscription_processing_test():
    """Test run the subscription processing function"""
    try:
        result = process_all_subscriptions()
        return {"success": True, "result": result}
    except Exception as e:
        frappe.log_error(f"Error in subscription processing test: {str(e)}", "Subscription Processing Test")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_scheduler_logs():
    """Check recent scheduler logs for subscription processing"""
    logs = frappe.get_all(
        "Error Log",
        filters={
            "error": ["like", "%subscription%"],
            "creation": [">=", add_days(today(), -7)]
        },
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=20
    )
    
    return {"scheduler_logs": logs}


@frappe.whitelist()
def comprehensive_subscription_debug():
    """Run comprehensive debug of subscription system"""
    return {
        "member_debug": debug_member_subscription_status(),
        "system_debug": debug_all_subscription_processing(),
        "processing_test": run_subscription_processing_test(),
        "scheduler_logs": check_scheduler_logs()
    }


if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    
    print("=== Subscription Starvation Debug ===")
    result = comprehensive_subscription_debug()
    
    print("\n=== Member Debug ===")
    member_debug = result["member_debug"]
    if "error" in member_debug:
        print(f"Error: {member_debug['error']}")
    else:
        print(f"Member: {member_debug['member']}")
        print(f"Memberships: {len(member_debug['memberships'])}")
        print(f"Subscriptions: {len(member_debug['subscriptions'])}")
        print(f"Active subscriptions: {member_debug['total_active_subscriptions']}")
        print(f"Invoices: {len(member_debug['invoices'])}")
    
    print("\n=== System Debug ===")
    system_debug = result["system_debug"]
    print(f"Total active subscriptions: {system_debug['total_active_subscriptions']}")
    print(f"Subscriptions needing processing: {system_debug['needs_processing_count']}")
    print(f"Processing errors: {system_debug['processing_errors_count']}")
    
    print("\n=== Processing Test ===")
    processing_test = result["processing_test"]
    print(f"Success: {processing_test['success']}")
    if processing_test['success']:
        print(f"Result: {processing_test['result']}")
    else:
        print(f"Error: {processing_test['error']}")
    
    print("\n=== Scheduler Logs ===")
    scheduler_logs = result["scheduler_logs"]
    print(f"Recent subscription-related logs: {len(scheduler_logs['scheduler_logs'])}")
    
    frappe.destroy()