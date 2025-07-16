#!/usr/bin/env python3
"""
Test subscription metrics to see what Zabbix is reporting
"""

import frappe

@frappe.whitelist()
def test_subscription_metrics():
    """Test the subscription metrics function"""
    
    try:
        # Import the monitoring function
        from verenigingen.monitoring.zabbix_integration import get_subscription_metrics
        
        # Get metrics
        metrics = get_subscription_metrics()
        
        # Also check raw database counts
        raw_data = {}
        
        # Check active subscriptions
        raw_data["active_subscriptions"] = frappe.db.count("Subscription", {"status": "Active"})
        
        # Check sales invoices with subscriptions today
        from datetime import datetime
        today = datetime.now().date()
        raw_data["sales_invoices_today"] = frappe.db.sql("""
            SELECT COUNT(DISTINCT subscription) 
            FROM `tabSales Invoice`
            WHERE DATE(creation) = %s
            AND subscription IS NOT NULL
            AND subscription != ''
        """, (today,))[0][0]
        
        # Check all sales invoices with subscriptions
        raw_data["total_subscription_invoices"] = frappe.db.sql("""
            SELECT COUNT(*) 
            FROM `tabSales Invoice`
            WHERE subscription IS NOT NULL
            AND subscription != ''
        """)[0][0]
        
        # Check scheduler logs
        raw_data["scheduler_logs"] = frappe.get_all("Scheduled Job Log",
            filters={"scheduled_job_type": ["like", "%process_all_subscription%"]},
            fields=["name", "status", "creation"],
            order_by="creation desc",
            limit=5)
        
        return {
            "metrics": metrics,
            "raw_data": raw_data,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    print("Run via: bench --site [site] execute verenigingen.scripts.debug.test_subscription_metrics.test_subscription_metrics")