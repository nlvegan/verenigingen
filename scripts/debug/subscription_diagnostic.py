#!/usr/bin/env python3
"""
Subscription Diagnostic Script
Checks subscription processing status and runs manual tests
"""

import frappe
from datetime import datetime, timedelta

@frappe.whitelist()
def check_subscription_status():
    """Check subscription processing status"""
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "member_check": {},
        "subscription_check": {},
        "invoice_check": {},
        "processing_test": {}
    }
    
    member_name = "Assoc-Member-2025-07-0030"
    
    # 1. Check member exists
    member = frappe.db.get_value("Member", member_name, 
        ["name", "status", "membership_start_date", "membership_end_date"], 
        as_dict=True)
    results["member_check"]["member"] = member
    
    # 2. Check member's subscriptions
    subscriptions = frappe.get_all("Subscription", 
        filters={"party": member_name}, 
        fields=["name", "status", "docstatus", "current_invoice_start", "current_invoice_end"])
    results["subscription_check"]["subscriptions"] = subscriptions
    
    # 3. Check member's invoices
    invoices = frappe.get_all("Sales Invoice",
        filters={"customer": member_name},
        fields=["name", "posting_date", "subscription", "grand_total", "status"])
    results["invoice_check"]["invoices"] = invoices
    
    # 4. Check system-wide subscription processing
    today = datetime.now().date()
    today_invoices = frappe.get_all("Sales Invoice",
        filters={
            "creation": [">=", today],
            "subscription": ["!=", ""]
        },
        fields=["name", "customer", "subscription", "creation"])
    results["processing_test"]["today_invoices"] = today_invoices
    
    # 5. Test manual processing
    try:
        from verenigingen.utils.subscription_processing import process_all_subscriptions
        
        # Run manual processing
        processing_result = process_all_subscriptions()
        results["processing_test"]["manual_result"] = processing_result
        
    except Exception as e:
        results["processing_test"]["error"] = str(e)
    
    return results

@frappe.whitelist()
def test_individual_subscription(subscription_name):
    """Test processing a specific subscription"""
    try:
        from verenigingen.utils.subscription_processing import SubscriptionHandler
        
        handler = SubscriptionHandler(subscription_name)
        should_generate = handler._should_generate_invoice()
        
        # Try to process it
        result = handler.process_subscription()
        
        return {
            "subscription": subscription_name,
            "should_generate": should_generate,
            "processing_result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "subscription": subscription_name,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    # For standalone execution
    print("This script should be run via Frappe framework")
    print("Use: bench --site [site] execute vereinigungen.scripts.debug.subscription_diagnostic.check_subscription_status")