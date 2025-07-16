#!/usr/bin/env python3
"""
Check scheduler status for subscription processing
"""

import frappe
from frappe.utils import now_datetime, get_datetime, add_days

@frappe.whitelist()
def check_scheduler_and_subscriptions():
    """Check scheduler status and subscription processing"""
    
    # 1. Check if specific member exists
    member = frappe.db.get_value(
        "Member", 
        "Assoc-Member-2025-07-0030", 
        ["name", "status", "membership_start_date", "membership_end_date"],
        as_dict=True
    )
    
    # 2. Check subscriptions for the member
    subscriptions = []
    if member:
        subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member.name},
            fields=["name", "status", "docstatus", "current_invoice_start", "current_invoice_end"]
        )
    
    # 3. Check all active subscriptions in system
    all_active_subscriptions = frappe.db.count("Subscription", {"status": "Active", "docstatus": 1})
    
    # 4. Check recent scheduler logs
    scheduler_logs = frappe.get_all(
        "Scheduled Job Log",
        filters={
            "scheduled_job_type": ["like", "%subscription%"],
            "creation": [">=", add_days(now_datetime(), -7)]
        },
        fields=["name", "scheduled_job_type", "status", "creation", "details"],
        order_by="creation desc",
        limit=10
    )
    
    # 5. Check for recent invoices
    recent_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "creation": [">=", add_days(now_datetime(), -7)],
            "subscription": ["!=", ""]
        },
        fields=["name", "customer", "posting_date", "subscription", "grand_total"],
        order_by="creation desc",
        limit=10
    )
    
    # 6. Check subscription invoice table
    subscription_invoices = frappe.get_all(
        "Subscription Invoice",
        filters={"creation": [">=", add_days(now_datetime(), -7)]},
        fields=["name", "subscription", "document_type", "creation"],
        order_by="creation desc",
        limit=10
    )
    
    # 7. Check error logs
    error_logs = frappe.get_all(
        "Error Log",
        filters={
            "error": ["like", "%subscription%"],
            "creation": [">=", add_days(now_datetime(), -7)]
        },
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=5
    )
    
    return {
        "member": member,
        "member_subscriptions": subscriptions,
        "total_active_subscriptions": all_active_subscriptions,
        "scheduler_logs": scheduler_logs,
        "recent_invoices": recent_invoices,
        "subscription_invoices": subscription_invoices,
        "error_logs": error_logs,
        "timestamp": now_datetime().isoformat()
    }

if __name__ == "__main__":
    print("This script needs to be run through Frappe console")