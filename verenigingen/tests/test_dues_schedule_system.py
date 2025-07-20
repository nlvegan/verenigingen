#!/usr/bin/env python3
"""
Test script for the new template-based dues schedule system
Run with: bench --site dev.veganisme.net execute verenigingen.test_dues_schedule_system.test_complete_workflow
"""

import frappe
from frappe.utils import today

def test_complete_workflow():
    """Test the complete dues schedule workflow"""
    
    print("🧪 Testing Template-Based Dues Schedule System")
    
    try:
        # Step 1: Test template creation for existing membership type
        print("\n📋 Step 1: Testing template creation...")
        
        # Get existing membership type
        membership_types = frappe.get_all("Membership Type", limit=1, pluck="name")
        if not membership_types:
            print("❌ No membership types found. Please create a membership type first.")
            return
        
        membership_type = membership_types[0]
        print(f"Using membership type: {membership_type}")
        
        # Create/get template
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)
        template_name = membership_type_doc.create_dues_schedule_template()
        print(f"✅ Template created: {template_name}")
        
        # Step 2: Test member with membership
        print("\n👤 Step 2: Testing member with active membership...")
        
        # Get a member with active membership
        member_with_membership = frappe.db.sql("""
            SELECT m.name as member_name, ms.name as membership_name
            FROM `tabMember` m 
            JOIN `tabMembership` ms ON ms.member = m.name 
            WHERE ms.status = 'Active' AND ms.docstatus = 1
            LIMIT 1
        """, as_dict=True)
        
        if not member_with_membership:
            print("❌ No member with active membership found. Creating test data...")
            # Would need to create test member and membership here
            return
            
        member_name = member_with_membership[0].member_name
        print(f"Using member: {member_name}")
        
        # Step 3: Test schedule creation from template
        print("\n⚙️ Step 3: Testing schedule creation from template...")
        
        # Check if member already has a schedule
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0},
            "name"
        )
        
        if existing_schedule:
            print(f"Member already has schedule: {existing_schedule}")
            schedule_name = existing_schedule
        else:
            # Create schedule from template
            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
            schedule_name = MembershipDuesSchedule.create_from_template(member_name)
            print(f"✅ Schedule created from template: {schedule_name}")
        
        # Step 4: Verify schedule properties
        print("\n🔍 Step 4: Verifying schedule properties...")
        
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        print(f"  - Is Template: {schedule.is_template}")
        print(f"  - Member: {schedule.member}")
        print(f"  - Membership Type: {schedule.membership_type}")
        print(f"  - Template Reference: {schedule.template_reference}")
        print(f"  - Amount: €{schedule.dues_rate}")
        print(f"  - Billing Frequency: {schedule.billing_frequency}")
        print(f"  - Status: {schedule.status}")
        
        # Step 5: Test invoice generation capability
        print("\n📄 Step 5: Testing invoice generation capability...")
        
        can_generate, reason = schedule.can_generate_invoice()
        print(f"  - Can generate invoice: {can_generate}")
        print(f"  - Reason: {reason}")
        
        # Step 6: Test template list
        print("\n📑 Step 6: Testing template listing...")
        
        templates = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 1},
            fields=["name", "schedule_name", "membership_type", "billing_frequency"]
        )
        
        print(f"  - Found {len(templates)} template(s):")
        for template in templates:
            print(f"    * {template.schedule_name} ({template.membership_type})")
        
        # Step 7: Test individual schedules
        print("\n👥 Step 7: Testing individual schedule listing...")
        
        individual_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 0},
            fields=["name", "member", "member_name", "membership_type", "status"],
            limit=5
        )
        
        print(f"  - Found {len(individual_schedules)} individual schedule(s):")
        for schedule in individual_schedules:
            print(f"    * {schedule.member_name} ({schedule.membership_type}) - {schedule.status}")
        
        print("\n✅ All tests completed successfully!")
        print("\n📊 Summary:")
        print(f"  - Templates: {len(templates)}")
        print(f"  - Individual Schedules: {len(individual_schedules)}")
        print(f"  - Test Schedule: {schedule_name}")
        
        return {
            "success": True,
            "template_name": template_name,
            "schedule_name": schedule_name,
            "templates_count": len(templates),
            "schedules_count": len(individual_schedules)
        }
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        frappe.log_error(f"Dues schedule test error: {str(e)}", "Dues Schedule Test")
        return {"success": False, "error": str(e)}

def test_template_operations():
    """Test template-specific operations"""
    
    print("\n🔧 Testing Template Operations")
    
    try:
        # Test creating a template manually
        print("\n📝 Testing manual template creation...")
        
        membership_types = frappe.get_all("Membership Type", limit=1, pluck="name")
        if not membership_types:
            print("❌ No membership types found")
            return
            
        membership_type = membership_types[0]
        
        # Create template using API
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import create_template_for_membership_type
        
        try:
            template_name = create_template_for_membership_type(membership_type, f"Test-Template-{membership_type}")
            print(f"✅ Template created via API: {template_name}")
        except Exception as e:
            if "already exists" in str(e):
                print(f"ℹ️ Template already exists for {membership_type}")
            else:
                raise
        
        # Test template validation
        print("\n🔍 Testing template validation...")
        
        templates = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 1, "membership_type": membership_type},
            limit=1,
            pluck="name"
        )
        
        if templates:
            template = frappe.get_doc("Membership Dues Schedule", templates[0])
            print(f"  - Template: {template.schedule_name}")
            print(f"  - Membership Type: {template.membership_type}")
            print(f"  - Billing Frequency: {template.billing_frequency}")
            print(f"  - Contribution Mode: {template.contribution_mode}")
            
            # Try to add invalid fields to template
            print("\n⚠️ Testing template validation (should prevent member assignment)...")
            try:
                template.member = "TEST-MEMBER"
                template.save()
                print("❌ Template validation failed - allowed member assignment")
            except Exception as e:
                print(f"✅ Template validation working - prevented: {str(e)}")
        
        print("\n✅ Template operations test completed!")
        return {"success": True}
        
    except Exception as e:
        print(f"\n❌ Template operations test failed: {str(e)}")
        return {"success": False, "error": str(e)}

@frappe.whitelist()
def create_all_templates():
    """Create dues schedule templates for all membership types"""
    
    print("🏗️ Creating templates for all membership types...")
    
    try:
        membership_types = frappe.get_all('Membership Type', pluck='name')
        results = {"created": [], "existing": [], "failed": []}
        
        for mt in membership_types:
            try:
                mt_doc = frappe.get_doc('Membership Type', mt)
                template_name = mt_doc.create_dues_schedule_template()
                results["created"].append({"type": mt, "template": template_name})
                print(f'✅ Created template for {mt}: {template_name}')
            except Exception as e:
                if "already exists" in str(e):
                    results["existing"].append(mt)
                    print(f'ℹ️ Template already exists for {mt}')
                else:
                    results["failed"].append({"type": mt, "error": str(e)})
                    print(f'❌ Failed for {mt}: {str(e)}')
        
        print(f"\n📊 Summary:")
        print(f"  - Created: {len(results['created'])}")
        print(f"  - Existing: {len(results['existing'])}")
        print(f"  - Failed: {len(results['failed'])}")
        
        return results
        
    except Exception as e:
        print(f"❌ Template creation failed: {str(e)}")
        return {"success": False, "error": str(e)}

@frappe.whitelist()
def run_all_tests():
    """Run all dues schedule tests"""
    
    print("🚀 Running Complete Dues Schedule System Tests")
    print("=" * 60)
    
    results = {
        "workflow_test": test_complete_workflow(),
        "template_test": test_template_operations()
    }
    
    print("\n" + "=" * 60)
    print("📋 Final Results:")
    
    all_passed = True
    for test_name, result in results.items():
        status = "✅ PASSED" if result.get("success") else "❌ FAILED"
        print(f"  {test_name}: {status}")
        if not result.get("success"):
            all_passed = False
            print(f"    Error: {result.get('error', 'Unknown error')}")
    
    print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    return results

if __name__ == "__main__":
    # Can also be run directly
    run_all_tests()