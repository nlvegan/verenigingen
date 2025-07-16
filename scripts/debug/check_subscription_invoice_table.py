#!/usr/bin/env python3
"""
Check the Subscription Invoice table to understand why subscriptions show "0 processed"
"""

import json
from datetime import datetime

def check_subscription_invoice_table():
    """Check the Subscription Invoice table structure and data"""
    
    try:
        import frappe
        frappe.init()
        frappe.connect()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "table_exists": False,
            "table_structure": [],
            "recent_records": [],
            "total_records": 0,
            "today_records": 0,
            "analysis": []
        }
        
        # Check if table exists
        try:
            table_exists = frappe.db.sql("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE() 
                AND table_name = 'tabSubscription Invoice'
            """)[0][0] > 0
            
            results["table_exists"] = table_exists
            
            if table_exists:
                # Get table structure
                structure = frappe.db.sql("""
                    DESCRIBE `tabSubscription Invoice`
                """, as_dict=True)
                
                results["table_structure"] = structure
                
                # Get total record count
                total_count = frappe.db.sql("""
                    SELECT COUNT(*) FROM `tabSubscription Invoice`
                """)[0][0]
                
                results["total_records"] = total_count
                
                # Get today's records
                today_count = frappe.db.sql("""
                    SELECT COUNT(DISTINCT subscription) 
                    FROM `tabSubscription Invoice`
                    WHERE creation >= CURDATE()
                """)[0][0]
                
                results["today_records"] = today_count
                
                # Get recent records
                recent_records = frappe.db.sql("""
                    SELECT name, subscription, document_type, creation, modified
                    FROM `tabSubscription Invoice`
                    ORDER BY creation DESC
                    LIMIT 10
                """, as_dict=True)
                
                results["recent_records"] = recent_records
                
                # Analysis
                results["analysis"].append(f"✅ Subscription Invoice table exists")
                results["analysis"].append(f"📊 Total records: {total_count}")
                results["analysis"].append(f"📊 Records created today: {today_count}")
                results["analysis"].append(f"📊 Recent records: {len(recent_records)}")
                
                if total_count == 0:
                    results["analysis"].append("❌ No subscription invoice records found")
                elif today_count == 0:
                    results["analysis"].append("⚠️  No subscription invoices processed today")
                else:
                    results["analysis"].append("✅ Subscription invoices found for today")
                    
            else:
                results["analysis"].append("❌ Subscription Invoice table does not exist")
                
        except Exception as e:
            results["analysis"].append(f"❌ Error checking table: {str(e)}")
            
        # Check alternative: Look for Sales Invoices with subscriptions
        try:
            sales_invoices_with_subs = frappe.db.sql("""
                SELECT COUNT(*) 
                FROM `tabSales Invoice` 
                WHERE subscription IS NOT NULL 
                AND subscription != ''
                AND creation >= CURDATE()
            """)[0][0]
            
            results["sales_invoices_with_subscriptions_today"] = sales_invoices_with_subs
            results["analysis"].append(f"📊 Sales invoices with subscriptions today: {sales_invoices_with_subs}")
            
        except Exception as e:
            results["analysis"].append(f"❌ Error checking sales invoices: {str(e)}")
        
        # Check if there are any subscriptions that should be processed
        try:
            active_subscriptions = frappe.db.sql("""
                SELECT COUNT(*) 
                FROM `tabSubscription` 
                WHERE status = 'Active' 
                AND docstatus = 1
            """)[0][0]
            
            results["active_subscriptions"] = active_subscriptions
            results["analysis"].append(f"📊 Active subscriptions: {active_subscriptions}")
            
        except Exception as e:
            results["analysis"].append(f"❌ Error checking active subscriptions: {str(e)}")
        
        # Check scheduler logs for subscription processing
        try:
            scheduler_logs = frappe.db.sql("""
                SELECT name, scheduled_job_type, status, creation
                FROM `tabScheduled Job Log`
                WHERE scheduled_job_type LIKE '%subscription%'
                AND creation >= CURDATE()
                ORDER BY creation DESC
            """, as_dict=True)
            
            results["scheduler_logs_today"] = scheduler_logs
            results["analysis"].append(f"📊 Scheduler logs today: {len(scheduler_logs)}")
            
        except Exception as e:
            results["analysis"].append(f"❌ Error checking scheduler logs: {str(e)}")
        
        frappe.destroy()
        return results
        
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

if __name__ == "__main__":
    print("=== SUBSCRIPTION INVOICE TABLE CHECK ===")
    result = check_subscription_invoice_table()
    
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print("Analysis:")
        for analysis_item in result.get("analysis", []):
            print(f"  {analysis_item}")
        
        print(f"\nDetailed results saved to: /tmp/subscription_invoice_check.json")
        with open("/tmp/subscription_invoice_check.json", "w") as f:
            json.dump(result, f, indent=2, default=str)