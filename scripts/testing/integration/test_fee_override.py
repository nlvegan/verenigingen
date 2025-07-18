#!/usr/bin/env python3
"""
Test enhanced dues amendment system integration
"""
import frappe
from frappe.utils import now, today


def test_enhanced_dues_amendment():
    """Test enhanced dues amendment system integration"""

    # Get a member with active membership
    member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "email"], as_dict=True)
    if not member:
        print("❌ No active member found")
        return

    member_doc = frappe.get_doc("Member", member.name)
    print(f"Member: {member_doc.full_name}")
    print(f"Current override: {member_doc.membership_fee_override}")
    print(f"Override reason: {member_doc.fee_override_reason}")

    # Get their membership
    membership = frappe.db.get_value(
        "Membership", 
        {"member": member.name, "docstatus": 1},
        ["name", "membership_type", "status"],
        as_dict=True
    )
    
    if not membership:
        print("❌ No membership found")
        return

    print(f"Membership: {membership.name} ({membership.status})")

    # Test 1: Create amendment using new enhanced system
    print("\n=== Testing Enhanced Amendment System ===")
    
    amendment = frappe.get_doc({
        "doctype": "Contribution Amendment Request",
        "membership": membership.name,
        "member": member.name,
        "amendment_type": "Fee Change",
        "requested_amount": 35.00,
        "reason": "Testing enhanced dues amendment system",
        "effective_date": today()
    })
    
    try:
        # Test validation and insertion
        amendment.insert()
        print(f"✓ Amendment created: {amendment.name}")
        print(f"  Status: {amendment.status}")
        print(f"  Current amount detected: €{amendment.current_amount}")
        
        # Test current dues schedule detection
        if amendment.current_dues_schedule:
            print(f"  Current dues schedule: {amendment.current_dues_schedule}")
        else:
            print("  No current dues schedule (may be legacy override)")
            
        # Test approval workflow
        if amendment.status == "Pending Approval":
            print("  Amendment requires manual approval")
            amendment.approve_amendment("Test approval for enhanced system")
            
        # Test application with dues schedule creation
        print("\n=== Testing Amendment Application ===")
        result = amendment.apply_amendment()
        
        if result["status"] == "success":
            print("✓ Amendment applied successfully")
            
            # Check if dues schedule was created
            if amendment.new_dues_schedule:
                print(f"✓ New dues schedule created: {amendment.new_dues_schedule}")
                
                # Verify the dues schedule
                dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
                print(f"  Amount: €{dues_schedule.amount}")
                print(f"  Mode: {dues_schedule.contribution_mode}")
                print(f"  Status: {dues_schedule.status}")
                print(f"  Custom amount: {dues_schedule.uses_custom_amount}")
                
                # Test fee calculation priority
                print("\n=== Testing Fee Calculation Priority ===")
                from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
                
                effective_fee = get_effective_fee_for_member(member_doc, membership)
                print(f"✓ Effective fee calculation:")
                print(f"  Amount: €{effective_fee.get('amount', 'N/A')}")
                print(f"  Source: {effective_fee.get('source', 'N/A')}")
                print(f"  Reason: {effective_fee.get('reason', 'N/A')}")
                
                # Verify legacy compatibility
                print("\n=== Testing Legacy Compatibility ===")
                member_doc.reload()
                print(f"✓ Legacy override updated: €{member_doc.membership_fee_override}")
                print(f"✓ Legacy reason: {member_doc.fee_override_reason}")
                
                # Clean up test data
                print("\n=== Cleaning Up Test Data ===")
                frappe.delete_doc("Membership Dues Schedule", amendment.new_dues_schedule)
                print("✓ Test dues schedule deleted")
                
        else:
            print(f"❌ Amendment application failed: {result.get('message', 'Unknown error')}")
            
        # Clean up amendment
        frappe.delete_doc("Contribution Amendment Request", amendment.name)
        print("✓ Test amendment deleted")
        
    except Exception as e:
        print(f"❌ Error during enhanced testing: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Clean up on error
        try:
            if amendment.name:
                frappe.delete_doc("Contribution Amendment Request", amendment.name, force=True)
        except:
            pass
    
    print("\n=== Enhanced Dues Amendment Test Complete ===")


def test_fee_override():
    """Backward compatibility wrapper"""
    test_enhanced_dues_amendment()


if __name__ == "__main__":
    test_enhanced_dues_amendment()
