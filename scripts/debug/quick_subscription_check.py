#!/usr/bin/env python3
"""
Quick subscription check - can be run manually
"""

import sys
import os
import json
from datetime import datetime, timedelta

# Add the app path to Python path
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, app_path)

def quick_check():
    """Simple check that can be done without full Frappe context"""
    
    # Get metrics similar to Zabbix integration
    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": []
    }
    
    try:
        # Import frappe and initialize
        import frappe
        frappe.init()
        frappe.connect()
        
        # Check 1: Member exists
        member = frappe.db.get_value(
            "Member", 
            "Assoc-Member-2025-07-0030", 
            ["name", "status", "membership_start_date", "membership_end_date"],
            as_dict=True
        )
        
        results["checks"].append({
            "name": "member_exists",
            "status": "found" if member else "not_found",
            "data": member
        })
        
        # Check 2: Total active subscriptions
        active_subs = frappe.db.count("Subscription", {"status": "Active", "docstatus": 1})
        results["checks"].append({
            "name": "total_active_subscriptions",
            "status": "ok",
            "count": active_subs
        })
        
        # Check 3: Member's subscriptions
        member_subs = []
        if member:
            member_subs = frappe.get_all(
                "Subscription",
                filters={"party": member.name},
                fields=["name", "status", "docstatus", "current_invoice_start", "current_invoice_end"]
            )
        
        results["checks"].append({
            "name": "member_subscriptions",
            "status": "ok",
            "count": len(member_subs),
            "data": member_subs
        })
        
        # Check 4: Recent scheduler runs
        scheduler_runs = frappe.get_all(
            "Scheduled Job Log",
            filters={
                "scheduled_job_type": ["like", "%subscription%"],
                "creation": [">=", datetime.now() - timedelta(days=7)]
            },
            fields=["name", "scheduled_job_type", "status", "creation"],
            order_by="creation desc",
            limit=5
        )
        
        results["checks"].append({
            "name": "scheduler_runs",
            "status": "ok",
            "count": len(scheduler_runs),
            "data": scheduler_runs
        })
        
        # Check 5: Recent invoices
        recent_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "creation": [">=", datetime.now() - timedelta(days=7)],
                "subscription": ["!=", ""]
            },
            fields=["name", "customer", "posting_date", "subscription"],
            order_by="creation desc",
            limit=5
        )
        
        results["checks"].append({
            "name": "recent_subscription_invoices",
            "status": "ok",
            "count": len(recent_invoices),
            "data": recent_invoices
        })
        
        # Check 6: Subscription processing errors
        errors = frappe.get_all(
            "Error Log",
            filters={
                "error": ["like", "%subscription%"],
                "creation": [">=", datetime.now() - timedelta(days=7)]
            },
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=3
        )
        
        results["checks"].append({
            "name": "subscription_errors",
            "status": "ok",
            "count": len(errors),
            "data": errors
        })
        
        # Manual test: Try to process subscriptions
        try:
            from verenigingen.utils.subscription_processing import process_all_subscriptions
            test_result = process_all_subscriptions()
            results["checks"].append({
                "name": "manual_processing_test",
                "status": "success",
                "result": test_result
            })
        except Exception as e:
            results["checks"].append({
                "name": "manual_processing_test",
                "status": "error",
                "error": str(e)
            })
        
        frappe.destroy()
        
    except Exception as e:
        results["checks"].append({
            "name": "general_error",
            "status": "error",
            "error": str(e)
        })
    
    return results

if __name__ == "__main__":
    result = quick_check()
    print(json.dumps(result, indent=2, default=str))