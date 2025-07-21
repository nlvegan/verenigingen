#!/usr/bin/env python3
"""
Test script to verify volunteer creation works when user account already exists
"""

import frappe
from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member


class TestVolunteerCreationFix(VereningingenTestCase):
    """Test volunteer creation with existing user accounts using proper test framework"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        frappe.set_user("Administrator")

    def test_volunteer_creation_with_existing_user(self):
        """Test that volunteer record can be created even when member has existing user account"""
        
        # Create test member using factory method
        test_member = self.create_test_member(
            first_name="Test",
            last_name="VolunteerCreation",
            email=f"test.volunteer.creation.{frappe.utils.random_string(5)}@example.com"
        )
        
        # Create user account for member using factory method
        test_user = self.create_test_user(
            email=test_member.email,
            roles=["Member"]
        )
        
        # Link user to member
        test_member.user = test_user.name
        test_member.save()
        
        print(f"✅ Created test member {test_member.name} with user account {test_user.name}")
        
        # Test volunteer creation - this should work without throwing an error
        volunteer = create_volunteer_from_member(test_member.name)
        
        # Verify volunteer was created successfully
        self.assertIsNotNone(volunteer, "Volunteer should be created successfully")
        self.assertEqual(volunteer.member, test_member.name, "Volunteer should be linked to member")
        
        print(f"✅ SUCCESS: Volunteer record created: {volunteer.name}")
        print(f"   Volunteer name: {volunteer.volunteer_name}")
        print(f"   Organization email: {volunteer.email}")
        print(f"   Member keeps personal user: {test_member.user}")
        
        # Verify the volunteer record
        volunteer.reload()
        print(f"   Volunteer status: {volunteer.status}")
        print(f"   Volunteer member link: {volunteer.member}")
        
        if volunteer.user:
            print(f"   Volunteer organization user: {volunteer.user}")
        else:
            print("   No organization user created (expected if email generation failed)")
            
        # Member should still have their original user account
        test_member.reload()
        self.assertEqual(test_member.user, test_user.name, "Member should keep original user account")
        
        # Track volunteer for automatic cleanup
        self.track_doc("Volunteer", volunteer.name)
        
    def test_volunteer_creation_database_query_scenario(self):
        """Test scenario that mimics finding existing members with users but no volunteer records"""
        
        # Create multiple test members with user accounts
        test_members = []
        for i in range(2):
            member = self.create_test_member(
                first_name=f"Database",
                last_name=f"Test{i}",
                email=f"database.test{i}.{frappe.utils.random_string(5)}@example.com"
            )
            
            user = self.create_test_user(
                email=member.email,
                roles=["Member"]
            )
            
            member.user = user.name
            member.save()
            test_members.append(member)
        
        # Test volunteer creation for each member
        for member in test_members:
            volunteer = create_volunteer_from_member(member.name)
            
            self.assertIsNotNone(volunteer, f"Volunteer should be created for member {member.name}")
            self.assertEqual(volunteer.member, member.name, "Volunteer should be linked correctly")
            
            # Track for automatic cleanup
            self.track_doc("Volunteer", volunteer.name)
            
            print(f"✅ Created volunteer {volunteer.name} for member {member.full_name}")


def run_volunteer_creation_fix_tests():
    """Run volunteer creation fix tests"""
    import unittest
    
    print("👤 Running Volunteer Creation Fix Tests...")
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVolunteerCreationFix)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All volunteer creation fix tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for failure in result.failures:
            print(f"FAIL: {failure[0]}")
            print(f"  {failure[1]}")
        for error in result.errors:
            print(f"ERROR: {error[0]}")
            print(f"  {error[1]}")
        return False


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    run_volunteer_creation_fix_tests()
    frappe.destroy()
