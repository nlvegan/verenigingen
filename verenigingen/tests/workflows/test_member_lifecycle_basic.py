# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Basic Member Lifecycle Test
Tests the core member journey without complex dependencies
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, today, random_string


class TestMemberLifecycleBasic(FrappeTestCase):
    """
    Basic Member Lifecycle Test
    
    Tests key stages:
    1. Member Creation
    2. User Account Creation
    3. Membership Creation
    4. Volunteer Registration
    5. Status Changes (Active -> Suspended -> Terminated)
    """
    
    def test_basic_member_lifecycle(self):
        """Test basic member lifecycle flow"""
        
        print("\n🚀 Starting Basic Member Lifecycle Test")
        
        # Stage 1: Create Member
        print("\n📝 Stage 1: Create Member")
        test_id = random_string(8)
        
        # Use existing chapter or skip chapter assignment
        existing_chapters = frappe.get_all("Chapter", limit=1)
        chapter = existing_chapters[0].name if existing_chapters else None
        
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "BasicTest",
            "last_name": f"Member{test_id}",
            "email": f"basic.test.{test_id}@example.com",
            "phone": "+31612345678",
            "birth_date": "1990-01-01",
            "status": "Active",
            "chapter": chapter
        })
        member.insert(ignore_permissions=True)
        
        # Verify member created
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.name)
        print(f"✅ Member created: {member.name}")
        
        # Stage 2: Create User Account
        print("\n👤 Stage 2: Create User Account")
        user = frappe.get_doc({
            "doctype": "User",
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "enabled": 1,
            "new_password": random_string(10),
            "send_welcome_email": 0
        })
        # Add role if it exists
        if frappe.db.exists("Role", "Verenigingen Member"):
            user.append("roles", {"role": "Verenigingen Member"})
        user.insert(ignore_permissions=True)
        
        # Link user to member
        member.reload()
        member.user = user.name
        member.save(ignore_permissions=True)
        
        # Verify user created and linked
        self.assertEqual(member.user, user.name)
        print(f"✅ User account created: {user.name}")
        
        # Stage 3: Create Membership
        print("\n🎫 Stage 3: Create Membership")
        
        # Use existing membership type
        membership_types = frappe.get_all("Membership Type", limit=1)
        if not membership_types:
            print("⚠️  No membership types found, skipping membership creation")
            membership = None
        else:
            membership_type = frappe.get_doc("Membership Type", membership_types[0].name)
            
            membership = frappe.get_doc({
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.membership_type_name,
                "start_date": today(),
                "renewal_date": add_months(today(), 12),
                "status": "Active"
            })
            membership.insert(ignore_permissions=True)
            membership.submit()
            
            # Verify membership
            self.assertEqual(membership.status, "Active")
            self.assertEqual(membership.member, member.name)
            print(f"✅ Membership created: {membership.name}")
        
        # Stage 4: Create Volunteer Record
        print("\n🤝 Stage 4: Create Volunteer Record")
        volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": member.full_name,
            "email": member.email,
            "member": member.name,
            "status": "Active",
            "start_date": today()
        })
        volunteer.insert(ignore_permissions=True)
        
        # Verify volunteer
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.member, member.name)
        print(f"✅ Volunteer record created: {volunteer.name}")
        
        # Stage 5: Test Status Changes
        print("\n🔄 Stage 5: Test Status Changes")
        
        # Suspend member
        member.reload()
        member.status = "Suspended"
        member.save(ignore_permissions=True)
        self.assertEqual(member.status, "Suspended")
        print("✅ Member suspended")
        
        # Reactivate member
        member.status = "Active"
        member.save(ignore_permissions=True)
        self.assertEqual(member.status, "Active")
        print("✅ Member reactivated")
        
        # Terminate member
        member.status = "Terminated"
        member.save(ignore_permissions=True)
        self.assertEqual(member.status, "Terminated")
        print("✅ Member terminated")
        
        print("\n🎉 Basic Member Lifecycle Test Complete!")
        
        # Cleanup
        try:
            if membership:
                membership.cancel()
                frappe.delete_doc("Membership", membership.name, force=True)
            frappe.delete_doc("Volunteer", volunteer.name, force=True)
            frappe.delete_doc("User", user.name, force=True)
            frappe.delete_doc("Member", member.name, force=True)
        except:
            pass  # Ignore cleanup errors in test