#!/usr/bin/env python3
"""
Proof of Concept: Membership Dues System
Test the new architecture before full implementation
"""

import frappe
from frappe.utils import today, add_days, getdate


@frappe.whitelist()
def test_dues_system_poc():
    """Test the membership dues system with a single member"""
    
    results = {
        "test_member": None,
        "test_schedule": None,
        "test_invoice": None,
        "errors": []
    }
    
    try:
        # 1. Find a test member (or create one)
        test_member = find_or_create_test_member()
        results["test_member"] = test_member
        
        # 2. Create a test dues schedule
        schedule_name = create_test_dues_schedule(test_member)
        results["test_schedule"] = schedule_name
        
        # 3. Test invoice generation
        invoice = test_invoice_generation(schedule_name)
        results["test_invoice"] = invoice
        
        # 4. Test the scheduled job
        job_results = test_scheduled_job()
        results["job_test"] = job_results
        
        return {
            "success": True,
            "results": results,
            "message": "POC completed successfully!"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": results
        }


def find_or_create_test_member():
    """Find or create a test member for POC"""
    
    # Look for existing test member
    test_member = frappe.db.get_value("Member", 
        {"email": ["like", "%test-dues-poc%"]}, "name")
    
    if test_member:
        return test_member
        
    # Create new test member
    member = frappe.new_doc("Member")
    member.first_name = "Test"
    member.last_name = "Dues POC"
    member.email = "test-dues-poc@example.com"
    member.member_type = "Individual"
    member.membership_type = frappe.db.get_value("Membership Type", 
        {"name": ["like", "%"]}, "name") or "Standard"
    member.insert()
    
    # Create membership for the member
    membership = frappe.new_doc("Membership")
    membership.member = member.name
    membership.membership_type = member.membership_type
    membership.start_date = today()
    membership.insert()
    
    return member.name


def create_test_dues_schedule(member_name):
    """Create a test dues schedule"""
    
    # Get membership
    membership = frappe.db.get_value("Membership", 
        {"member": member_name}, "name")
    
    if not membership:
        frappe.throw(f"No membership found for {member_name}")
    
    # Create schedule
    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
    
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.member = member_name
    schedule.membership = membership
    schedule.billing_frequency = "Monthly"
    schedule.amount = 25.00  # Test amount
    schedule.next_invoice_date = today()
    schedule.invoice_days_before = 0  # Generate immediately
    schedule.test_mode = 1  # Test mode
    schedule.auto_generate = 1
    schedule.status = "Active"
    schedule.insert()
    
    return schedule.name


def test_invoice_generation(schedule_name):
    """Test invoice generation for a schedule"""
    
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
    
    # Check if can generate
    can_generate, reason = schedule.can_generate_invoice()
    print(f"Can generate invoice: {can_generate} - {reason}")
    
    # Generate invoice
    invoice = schedule.generate_invoice(force=True)
    print(f"Generated invoice: {invoice}")
    
    return invoice


def test_scheduled_job():
    """Test the scheduled job"""
    
    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import generate_dues_invoices
    
    # Run in test mode
    results = generate_dues_invoices(test_mode=True)
    
    return results


@frappe.whitelist()
def compare_with_subscription(member_name):
    """Compare dues system with existing subscription system"""
    
    comparison = {
        "member": member_name,
        "subscription_system": {},
        "dues_system": {},
        "analysis": []
    }
    
    # Get subscription data
    subscriptions = frappe.get_all("Subscription",
        filters={"party": member_name},
        fields=["name", "status", "current_invoice_start", "current_invoice_end"]
    )
    
    if subscriptions:
        sub = subscriptions[0]
        comparison["subscription_system"] = {
            "subscription_id": sub.name,
            "status": sub.status,
            "current_period": f"{sub.current_invoice_start} to {sub.current_invoice_end}",
            "can_process": "Unknown - would need to try"
        }
    
    # Get dues schedule data
    schedules = frappe.get_all("Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "status", "next_invoice_date", "last_invoice_date", "amount"]
    )
    
    if schedules:
        schedule = schedules[0]
        comparison["dues_system"] = {
            "schedule_id": schedule.name,
            "status": schedule.status,
            "next_invoice": schedule.next_invoice_date,
            "last_invoice": schedule.last_invoice_date,
            "amount": schedule.amount
        }
    
    # Analysis
    if subscriptions and schedules:
        comparison["analysis"].append("Member has both subscription and dues schedule")
        comparison["analysis"].append("Can run both systems in parallel for testing")
    elif subscriptions and not schedules:
        comparison["analysis"].append("Member only has subscription - ready for migration")
    elif not subscriptions and schedules:
        comparison["analysis"].append("Member only has dues schedule - new system working")
    else:
        comparison["analysis"].append("Member has neither - needs setup")
    
    return comparison


@frappe.whitelist()
def migrate_single_subscription(subscription_name, test_mode=True):
    """Migrate a single subscription to dues schedule"""
    
    sub = frappe.get_doc("Subscription", subscription_name)
    
    # Find related membership
    membership = frappe.db.get_value("Membership", 
        {"member": sub.party}, "name")
    
    if not membership:
        return {
            "success": False,
            "error": f"No membership found for {sub.party}"
        }
    
    # Determine billing frequency from subscription
    billing_frequency = "Annual"  # Default
    if hasattr(sub, "billing_interval"):
        interval_map = {
            "Month": "Monthly",
            "Year": "Annual"
        }
        billing_frequency = interval_map.get(sub.billing_interval, "Annual")
    
    # Get amount from subscription plans
    amount = 0
    if sub.plans:
        amount = sum(plan.qty * frappe.db.get_value("Subscription Plan", 
            plan.plan, "cost") or 0 for plan in sub.plans)
    
    if test_mode:
        return {
            "success": True,
            "test_mode": True,
            "would_create": {
                "member": sub.party,
                "membership": membership,
                "billing_frequency": billing_frequency,
                "amount": amount,
                "next_invoice_date": sub.current_invoice_end
            }
        }
    
    # Create actual dues schedule
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.member = sub.party
    schedule.membership = membership
    schedule.billing_frequency = billing_frequency
    schedule.amount = amount
    schedule.next_invoice_date = sub.current_invoice_end
    schedule.auto_generate = 1
    schedule.status = "Active"
    schedule.notes = f"Migrated from subscription {subscription_name}"
    schedule.insert()
    
    # Optionally cancel the subscription
    # sub.cancel()
    
    return {
        "success": True,
        "schedule_created": schedule.name,
        "subscription": subscription_name
    }


if __name__ == "__main__":
    print("Run via bench: bench --site [site] execute vereinigingen.scripts.membership_dues_poc.test_dues_system_poc")