#!/usr/bin/env python3
"""
Check scheduler status for dues schedule processing
"""

import frappe
from frappe.utils import now_datetime, get_datetime, add_days

@frappe.whitelist()
def check_scheduler_and_dues_schedules():
    """Check scheduler status and dues schedule processing"""
    
    # 1. Check if specific member exists
    member = frappe.db.get_value(
        "Member", 
        "Assoc-Member-2025-07-0030", 
        ["name", "status"],
        as_dict=True
    )
    
    # 2. Check dues schedules for the member
    dues_schedules = []
    if member:
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name},
            fields=["name", "status", "docstatus", "next_invoice_date", "last_invoice_date"]
        )
    
    # 3. Check all active dues schedules in system
    all_active_dues_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active", "docstatus": 1})
    
    # 4. Check recent scheduler logs
    scheduler_logs = frappe.get_all(
        "Scheduled Job Log",
        filters={
            "scheduled_job_type": ["like", "%dues_schedule%"],
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
            "membership_dues_schedule_display": ["!=", ""]
        },
        fields=["name", "customer", "posting_date", "membership_dues_schedule_display", "grand_total"],
        order_by="creation desc",
        limit=10
    )
    
    # 6. Check dues schedule invoice tracking
    dues_schedule_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "creation": [">=", add_days(now_datetime(), -7)],
            "membership_dues_schedule_display": ["!=", ""]
        },
        fields=["name", "membership_dues_schedule_display", "docstatus", "creation"],
        order_by="creation desc",
        limit=10
    )
    
    # 7. Check error logs
    error_logs = frappe.get_all(
        "Error Log",
        filters={
            "error": ["like", "%dues_schedule%"],
            "creation": [">=", add_days(now_datetime(), -7)]
        },
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=5
    )
    
    return {
        "member": member,
        "member_dues_schedules": dues_schedules,
        "total_active_dues_schedules": all_active_dues_schedules,
        "scheduler_logs": scheduler_logs,
        "recent_invoices": recent_invoices,
        "dues_schedule_invoices": dues_schedule_invoices,
        "error_logs": error_logs,
        "timestamp": now_datetime().isoformat()
    }

if __name__ == "__main__":
    print("This script needs to be run through Frappe console")