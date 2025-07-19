#!/usr/bin/env python3
"""
Simple validation script to test fee calculation functions
"""

import frappe
from frappe.utils import today

@frappe.whitelist()
def test_fee_calculation():
    """Test fee calculation priority system"""
    
    # Test the fee calculation function with a simple example
    try:
        # Create a simple test member
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Fee"
        member.email = f"testfee{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Test City"
        member.country = "Netherlands"
        member.save()
        
        # Create a test membership type
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Fee Type {frappe.generate_hash(length=6)}"
        membership_type.amount = 20.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        membership_type.save()
        
        # Test fee calculation import
        from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
        
        # Create a simple membership object
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        
        # Test the fee calculation
        fee_info = get_effective_fee_for_member(member, membership)
        
        # Clean up
        frappe.delete_doc("Membership", membership.name, force=True)
        frappe.delete_doc("Member", member.name, force=True)
        frappe.delete_doc("Membership Type", membership_type.name, force=True)
        
        return {
            "success": True,
            "fee_info": fee_info,
            "message": "Fee calculation test passed successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Fee calculation test failed"
        }

@frappe.whitelist()
def test_dues_schedule_creation():
    """Test creating a dues schedule"""
    
    try:
        # Test basic dues schedule creation
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        # Create test member and membership
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Dues"
        member.email = f"testdues{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Test City"
        member.country = "Netherlands"
        member.save()
        
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Dues Type {frappe.generate_hash(length=6)}"
        membership_type.amount = 20.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        membership_type.save()
        
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        
        # Test creating dues schedule
        schedule_name = create_new_dues_schedule(member, 25.0, "Test reason")
        
        # Verify schedule was created
        schedule_exists = frappe.db.exists("Membership Dues Schedule", schedule_name)
        
        # Clean up
        if schedule_exists:
            frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
        frappe.delete_doc("Membership", membership.name, force=True)
        frappe.delete_doc("Member", member.name, force=True)
        frappe.delete_doc("Membership Type", membership_type.name, force=True)
        
        return {
            "success": True,
            "schedule_name": schedule_name,
            "schedule_exists": schedule_exists,
            "message": "Dues schedule creation test passed"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Dues schedule creation test failed"
        }

@frappe.whitelist()
def run_all_tests():
    """Run all migration tests"""
    
    results = {
        "fee_calculation": test_fee_calculation(),
        "dues_schedule_creation": test_dues_schedule_creation()
    }
    
    # Summary
    passed = sum(1 for r in results.values() if r["success"])
    total = len(results)
    
    results["summary"] = {
        "passed": passed,
        "total": total,
        "success_rate": f"{passed}/{total}",
        "overall_success": passed == total
    }
    
    return results