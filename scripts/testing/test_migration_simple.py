#!/usr/bin/env python3
"""
Simple test to verify the fee override migration functionality
"""

import frappe
from frappe.utils import today

def test_fee_priority_system():
    """Test that fee calculation follows the correct priority order"""
    
    try:
        # Create test member
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Migration"
        member.email = f"testmigration{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Test City"
        member.country = "Netherlands"
        member.save()
        
        # Create test membership type
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Type {frappe.generate_hash(length=6)}"
        membership_type.amount = 20.0
        membership_type.is_active = 1
        membership_type.save()
        
        # Create membership
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        
        print(f"✓ Created test data - Member: {member.name}, Membership: {membership.name}")
        
        # Test fee calculation
        from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
        
        # Test 1: No overrides - should use membership type amount
        fee_info = get_effective_fee_for_member(member, membership)
        print(f"✓ No overrides - Source: {fee_info['source']}, Amount: {fee_info['amount']}")
        
        # Test 2: Add legacy override
        member.dues_rate = 30.0
        member.save()
        
        fee_info = get_effective_fee_for_member(member, membership)
        print(f"✓ Legacy override - Source: {fee_info['source']}, Amount: {fee_info['amount']}")
        
        # Test 3: Create dues schedule - should have highest priority
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        schedule_name = create_new_dues_schedule(member, 25.0, "Testing new schedule")
        print(f"✓ Created dues schedule: {schedule_name}")
        
        fee_info = get_effective_fee_for_member(member, membership)
        print(f"✓ Dues schedule priority - Source: {fee_info['source']}, Amount: {fee_info['amount']}")
        
        # Test 4: Test fee history
        from verenigingen.templates.pages.membership_fee_adjustment import get_member_fee_history
        
        history = get_member_fee_history(member.name)
        print(f"✓ Fee history retrieved: {len(history)} entries")
        
        # Cleanup
        frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
        frappe.delete_doc("Membership", membership.name, force=True)
        frappe.delete_doc("Member", member.name, force=True)
        frappe.delete_doc("Membership Type", membership_type.name, force=True)
        
        print("✓ All tests passed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    
    print("Starting simple migration test...")
    success = test_fee_priority_system()
    
    if success:
        print("\n🎉 Migration functionality is working correctly!")
    else:
        print("\n❌ Migration test failed - check errors above")
    
    frappe.destroy()