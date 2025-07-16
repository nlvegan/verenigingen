#!/usr/bin/env python3
"""
Comprehensive analysis of subscription starvation issue

This script investigates why member "Assoc-Member-2025-07-0030" 
and possibly other members aren't getting invoices generated
despite having active subscriptions.
"""

import json
import sys
import os
from datetime import datetime, timedelta

# Add the app path to Python path
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, app_path)

def run_comprehensive_analysis():
    """Run comprehensive analysis of subscription starvation"""
    
    try:
        import frappe
        from frappe.utils import now_datetime, getdate, add_days
        
        frappe.init()
        frappe.connect()
        
        analysis_results = {
            "timestamp": now_datetime().isoformat(),
            "member_analysis": {},
            "system_analysis": {},
            "subscription_processing": {},
            "scheduler_analysis": {},
            "error_analysis": {},
            "recommendations": []
        }
        
        # 1. MEMBER ANALYSIS
        print("=== MEMBER ANALYSIS ===")
        member_name = "Assoc-Member-2025-07-0030"
        
        # Get member data
        member = frappe.db.get_value(
            "Member", 
            member_name, 
            [
                "name", "status", "membership_start_date", "membership_end_date", 
                "creation", "modified", "email", "first_name", "last_name"
            ],
            as_dict=True
        )
        
        print(f"Member found: {member is not None}")
        if member:
            print(f"Status: {member.status}")
            print(f"Membership dates: {member.membership_start_date} to {member.membership_end_date}")
            analysis_results["member_analysis"]["member"] = member
        else:
            print("Member not found!")
            analysis_results["member_analysis"]["error"] = "Member not found"
            
        # Get member's memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=[
                "name", "status", "membership_type", "start_date", "renewal_date", 
                "subscription", "auto_renew", "creation", "modified"
            ],
            order_by="creation desc"
        )
        
        print(f"Memberships found: {len(memberships)}")
        for membership in memberships:
            print(f"  - {membership.name}: {membership.status}, Auto-renew: {membership.auto_renew}")
            
        analysis_results["member_analysis"]["memberships"] = memberships
        
        # Get member's subscriptions
        subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member_name},
            fields=[
                "name", "status", "docstatus", "current_invoice_start", "current_invoice_end",
                "billing_interval", "billing_interval_count", "generate_invoice_at",
                "creation", "modified", "next_invoice_date"
            ],
            order_by="creation desc"
        )
        
        print(f"Subscriptions found: {len(subscriptions)}")
        for sub in subscriptions:
            print(f"  - {sub.name}: {sub.status}, Current period: {sub.current_invoice_start} to {sub.current_invoice_end}")
            
        analysis_results["member_analysis"]["subscriptions"] = subscriptions
        
        # Get member's invoices
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member_name},
            fields=[
                "name", "posting_date", "status", "grand_total", "subscription", 
                "creation", "docstatus"
            ],
            order_by="posting_date desc"
        )
        
        print(f"Invoices found: {len(invoices)}")
        for inv in invoices:
            print(f"  - {inv.name}: {inv.posting_date}, Status: {inv.status}, Amount: {inv.grand_total}")
            
        analysis_results["member_analysis"]["invoices"] = invoices
        
        # 2. SYSTEM ANALYSIS
        print("\n=== SYSTEM ANALYSIS ===")
        
        # Total active subscriptions
        total_active_subs = frappe.db.count("Subscription", {"status": "Active", "docstatus": 1})
        print(f"Total active subscriptions: {total_active_subs}")
        
        # Total members
        total_members = frappe.db.count("Member")
        active_members = frappe.db.count("Member", {"status": "Active"})
        print(f"Total members: {total_members}, Active: {active_members}")
        
        # Recent invoices
        recent_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "creation": [">=", add_days(now_datetime(), -7)],
                "subscription": ["!=", ""]
            },
            fields=["name", "customer", "posting_date", "subscription", "grand_total"]
        )
        
        print(f"Recent subscription invoices (last 7 days): {len(recent_invoices)}")
        
        analysis_results["system_analysis"] = {
            "total_active_subscriptions": total_active_subs,
            "total_members": total_members,
            "active_members": active_members,
            "recent_invoices_count": len(recent_invoices),
            "recent_invoices": recent_invoices
        }
        
        # 3. SUBSCRIPTION PROCESSING TEST
        print("\n=== SUBSCRIPTION PROCESSING TEST ===")
        
        try:
            from verenigingen.utils.subscription_processing import (
                SubscriptionHandler, 
                process_all_subscriptions
            )
            
            # Test individual subscription processing
            individual_results = []
            for sub in subscriptions:
                if sub.status == "Active":
                    try:
                        handler = SubscriptionHandler(sub.name)
                        should_generate = handler._should_generate_invoice()
                        invoice_exists = handler._invoice_exists_for_period(
                            sub.current_invoice_start, 
                            sub.current_invoice_end
                        )
                        
                        individual_results.append({
                            "subscription": sub.name,
                            "should_generate": should_generate,
                            "invoice_exists": invoice_exists,
                            "current_start": sub.current_invoice_start,
                            "current_end": sub.current_invoice_end
                        })
                        
                    except Exception as e:
                        individual_results.append({
                            "subscription": sub.name,
                            "error": str(e)
                        })
            
            print(f"Individual subscription processing results: {len(individual_results)}")
            for result in individual_results:
                if "error" in result:
                    print(f"  - {result['subscription']}: ERROR - {result['error']}")
                else:
                    print(f"  - {result['subscription']}: Should generate: {result['should_generate']}, Invoice exists: {result['invoice_exists']}")
            
            # Test system-wide processing
            try:
                system_processing_result = process_all_subscriptions()
                print(f"System-wide processing result: {system_processing_result}")
            except Exception as e:
                system_processing_result = {"error": str(e)}
                print(f"System-wide processing error: {e}")
            
            analysis_results["subscription_processing"] = {
                "individual_results": individual_results,
                "system_processing": system_processing_result
            }
            
        except ImportError as e:
            print(f"Could not import subscription processing: {e}")
            analysis_results["subscription_processing"]["error"] = str(e)
        
        # 4. SCHEDULER ANALYSIS
        print("\n=== SCHEDULER ANALYSIS ===")
        
        # Check recent scheduler runs
        scheduler_runs = frappe.get_all(
            "Scheduled Job Log",
            filters={
                "scheduled_job_type": ["like", "%subscription%"],
                "creation": [">=", add_days(now_datetime(), -7)]
            },
            fields=["name", "scheduled_job_type", "status", "creation", "details"],
            order_by="creation desc",
            limit=10
        )
        
        print(f"Recent scheduler runs: {len(scheduler_runs)}")
        for run in scheduler_runs:
            print(f"  - {run.creation}: {run.scheduled_job_type} - {run.status}")
            
        analysis_results["scheduler_analysis"]["recent_runs"] = scheduler_runs
        
        # Check if scheduler is enabled
        scheduler_enabled = frappe.utils.scheduler.is_scheduler_enabled()
        print(f"Scheduler enabled: {scheduler_enabled}")
        analysis_results["scheduler_analysis"]["scheduler_enabled"] = scheduler_enabled
        
        # 5. ERROR ANALYSIS
        print("\n=== ERROR ANALYSIS ===")
        
        # Get recent errors
        errors = frappe.get_all(
            "Error Log",
            filters={
                "error": ["like", "%subscription%"],
                "creation": [">=", add_days(now_datetime(), -7)]
            },
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=10
        )
        
        print(f"Recent subscription errors: {len(errors)}")
        for error in errors:
            print(f"  - {error.creation}: {error.error[:100]}...")
            
        analysis_results["error_analysis"]["recent_errors"] = errors
        
        # 6. RECOMMENDATIONS
        print("\n=== RECOMMENDATIONS ===")
        
        recommendations = []
        
        if not member:
            recommendations.append("Member not found - check if member ID is correct")
        elif member.status != "Active":
            recommendations.append(f"Member status is {member.status}, not Active")
            
        if not subscriptions:
            recommendations.append("No subscriptions found for member")
        elif not any(s.status == "Active" for s in subscriptions):
            recommendations.append("No active subscriptions found for member")
            
        if len(recent_invoices) == 0:
            recommendations.append("No recent subscription invoices generated system-wide")
            
        if len(scheduler_runs) == 0:
            recommendations.append("No recent subscription scheduler runs found")
            
        if not scheduler_enabled:
            recommendations.append("Scheduler is disabled")
            
        if len(errors) > 0:
            recommendations.append(f"Found {len(errors)} subscription-related errors")
            
        analysis_results["recommendations"] = recommendations
        
        for rec in recommendations:
            print(f"  - {rec}")
        
        frappe.destroy()
        
        return analysis_results
        
    except Exception as e:
        print(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

if __name__ == "__main__":
    print("=== SUBSCRIPTION STARVATION ANALYSIS ===")
    print("Investigating why member 'Assoc-Member-2025-07-0030' isn't getting invoices")
    print("="*60)
    
    result = run_comprehensive_analysis()
    
    print("\n=== ANALYSIS COMPLETE ===")
    
    # Write results to file
    output_file = "/tmp/subscription_starvation_analysis.json"
    with open(output_file, "w") as f:
        json.dump(result, indent=2, default=str, fp=f)
    
    print(f"Full analysis saved to: {output_file}")