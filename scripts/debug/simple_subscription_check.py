#!/usr/bin/env python3
"""
Simple subscription check that uses direct database queries
"""

import json
from datetime import datetime, timedelta

def simple_database_check():
    """Simple database check without requiring full Frappe context"""
    
    try:
        import frappe
        frappe.init()
        frappe.connect()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "member_check": {},
            "subscription_check": {},
            "invoice_check": {},
            "scheduler_check": {}
        }
        
        member_name = "Assoc-Member-2025-07-0030"
        
        # Direct database queries
        
        # 1. Check member
        member_query = """
        SELECT name, status, membership_start_date, membership_end_date, 
               creation, modified, email, first_name, last_name
        FROM `tabMember` 
        WHERE name = %s
        """
        
        member_result = frappe.db.sql(member_query, (member_name,), as_dict=True)
        results["member_check"]["member"] = member_result[0] if member_result else None
        
        # 2. Check memberships
        membership_query = """
        SELECT name, status, membership_type, start_date, renewal_date, 
               subscription, auto_renew, creation, modified
        FROM `tabMembership` 
        WHERE member = %s
        ORDER BY creation DESC
        """
        
        membership_result = frappe.db.sql(membership_query, (member_name,), as_dict=True)
        results["member_check"]["memberships"] = membership_result
        
        # 3. Check subscriptions
        subscription_query = """
        SELECT name, status, docstatus, current_invoice_start, current_invoice_end,
               billing_interval, billing_interval_count, generate_invoice_at,
               creation, modified
        FROM `tabSubscription` 
        WHERE party = %s
        ORDER BY creation DESC
        """
        
        subscription_result = frappe.db.sql(subscription_query, (member_name,), as_dict=True)
        results["subscription_check"]["member_subscriptions"] = subscription_result
        
        # 4. Check all active subscriptions
        active_subs_query = """
        SELECT COUNT(*) as count
        FROM `tabSubscription` 
        WHERE status = 'Active' AND docstatus = 1
        """
        
        active_subs_result = frappe.db.sql(active_subs_query, as_dict=True)
        results["subscription_check"]["total_active"] = active_subs_result[0]["count"] if active_subs_result else 0
        
        # 5. Check recent invoices
        recent_invoices_query = """
        SELECT name, customer, posting_date, subscription, grand_total, status
        FROM `tabSales Invoice` 
        WHERE customer = %s 
        ORDER BY posting_date DESC
        LIMIT 10
        """
        
        invoice_result = frappe.db.sql(recent_invoices_query, (member_name,), as_dict=True)
        results["invoice_check"]["member_invoices"] = invoice_result
        
        # 6. Check recent system-wide subscription invoices
        system_invoices_query = """
        SELECT name, customer, posting_date, subscription, grand_total
        FROM `tabSales Invoice` 
        WHERE subscription IS NOT NULL 
        AND subscription != ''
        AND creation >= %s
        ORDER BY creation DESC
        LIMIT 10
        """
        
        week_ago = datetime.now() - timedelta(days=7)
        system_invoice_result = frappe.db.sql(system_invoices_query, (week_ago,), as_dict=True)
        results["invoice_check"]["recent_system_invoices"] = system_invoice_result
        
        # 7. Check scheduler logs
        scheduler_query = """
        SELECT name, scheduled_job_type, status, creation, details
        FROM `tabScheduled Job Log` 
        WHERE scheduled_job_type LIKE '%subscription%'
        AND creation >= %s
        ORDER BY creation DESC
        LIMIT 10
        """
        
        scheduler_result = frappe.db.sql(scheduler_query, (week_ago,), as_dict=True)
        results["scheduler_check"]["recent_runs"] = scheduler_result
        
        # 8. Check error logs
        error_query = """
        SELECT name, error, creation
        FROM `tabError Log` 
        WHERE error LIKE '%subscription%'
        AND creation >= %s
        ORDER BY creation DESC
        LIMIT 5
        """
        
        error_result = frappe.db.sql(error_query, (week_ago,), as_dict=True)
        results["scheduler_check"]["recent_errors"] = error_result
        
        # Analysis
        analysis = []
        
        member_data = results["member_check"]["member"]
        if not member_data:
            analysis.append("❌ Member not found")
        else:
            analysis.append(f"✅ Member found: {member_data['status']}")
            
        memberships = results["member_check"]["memberships"]
        if not memberships:
            analysis.append("❌ No memberships found")
        else:
            active_memberships = [m for m in memberships if m["status"] == "Active"]
            analysis.append(f"✅ {len(memberships)} memberships, {len(active_memberships)} active")
            
        subscriptions = results["subscription_check"]["member_subscriptions"]
        if not subscriptions:
            analysis.append("❌ No subscriptions found")
        else:
            active_subscriptions = [s for s in subscriptions if s["status"] == "Active"]
            analysis.append(f"✅ {len(subscriptions)} subscriptions, {len(active_subscriptions)} active")
            
        total_active = results["subscription_check"]["total_active"]
        analysis.append(f"ℹ️  Total active subscriptions system-wide: {total_active}")
        
        member_invoices = results["invoice_check"]["member_invoices"]
        analysis.append(f"ℹ️  Member invoices: {len(member_invoices)}")
        
        system_invoices = results["invoice_check"]["recent_system_invoices"]
        analysis.append(f"ℹ️  Recent system subscription invoices: {len(system_invoices)}")
        
        scheduler_runs = results["scheduler_check"]["recent_runs"]
        analysis.append(f"ℹ️  Recent scheduler runs: {len(scheduler_runs)}")
        
        errors = results["scheduler_check"]["recent_errors"]
        if errors:
            analysis.append(f"⚠️  Recent errors: {len(errors)}")
        
        results["analysis"] = analysis
        
        frappe.destroy()
        return results
        
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

if __name__ == "__main__":
    print("=== SIMPLE SUBSCRIPTION CHECK ===")
    result = simple_database_check()
    
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print("Analysis:")
        for analysis_item in result.get("analysis", []):
            print(f"  {analysis_item}")
        
        print(f"\nDetailed results saved to: /tmp/simple_subscription_check.json")
        with open("/tmp/simple_subscription_check.json", "w") as f:
            json.dump(result, f, indent=2, default=str)