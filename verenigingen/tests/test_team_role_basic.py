#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basic Team Role Smoke Tests

Simple tests to validate Team Role functionality is working correctly
without complex factory dependencies.
"""

import unittest
import frappe
from frappe.utils import today
from frappe.tests.utils import FrappeTestCase


class TestTeamRoleBasic(FrappeTestCase):
    """Basic smoke tests for Team Role functionality"""
    
    def setUp(self):
        super().setUp()
        # Clean up any existing test data
        self.cleanup_test_data()
        self.created_docs = []
    
    def tearDown(self):
        # Clean up created documents
        self.cleanup_test_data()
        super().tearDown()
    
    def cleanup_test_data(self):
        """Clean up test documents"""
        # Clean up teams with test names
        test_teams = frappe.get_all("Team", 
                                  filters={"team_name": ["like", "%Test Team Role%"]})
        for team in test_teams:
            try:
                team_doc = frappe.get_doc("Team", team.name)
                team_doc.team_members = []  # Clear members first
                team_doc.save()
                frappe.delete_doc("Team", team.name)
            except:
                pass
        
        # Clean up test team roles
        test_roles = frappe.get_all("Team Role",
                                  filters={"role_name": ["like", "%Test%"]})
        for role in test_roles:
            try:
                frappe.delete_doc("Team Role", role.name)
            except:
                pass
    
    def track_doc(self, doctype, name):
        """Track document for cleanup"""
        self.created_docs.append({"doctype": doctype, "name": name})
    
    def test_team_role_fixtures_exist(self):
        """Test that required Team Role fixtures exist"""
        print("Testing Team Role fixtures...")
        
        required_roles = ["Team Leader", "Team Member", "Coordinator", "Secretary", "Treasurer"]
        
        for role_name in required_roles:
            exists = frappe.db.exists("Team Role", role_name)
            self.assertTrue(exists, f"Team Role '{role_name}' should exist")
            
            if exists:
                role = frappe.get_doc("Team Role", role_name)
                self.assertEqual(role.is_active, 1, f"{role_name} should be active")
        
        print("✅ Team Role fixtures exist and are active")
    
    def test_team_role_properties(self):
        """Test Team Role properties are set correctly"""
        print("Testing Team Role properties...")
        
        # Test Team Leader properties
        leader = frappe.get_doc("Team Role", "Team Leader")
        self.assertEqual(leader.permissions_level, "Leader")
        self.assertEqual(leader.is_team_leader, 1)
        self.assertEqual(leader.is_unique, 1)
        
        # Test Team Member properties
        member = frappe.get_doc("Team Role", "Team Member")
        self.assertEqual(member.permissions_level, "Basic")
        self.assertEqual(member.is_team_leader, 0)
        self.assertEqual(member.is_unique, 0)
        
        # Test Secretary properties (unique but not leader)
        secretary = frappe.get_doc("Team Role", "Secretary")
        self.assertEqual(secretary.is_unique, 1)
        self.assertEqual(secretary.is_team_leader, 0)
        
        print("✅ Team Role properties are correct")
    
    def test_team_member_field_structure(self):
        """Test Team Member doctype has correct field structure"""
        print("Testing Team Member field structure...")
        
        meta = frappe.get_meta("Team Member")
        
        # Check required fields exist
        required_fields = ["volunteer", "team_role", "role_type", "from_date"]
        for field_name in required_fields:
            field = meta.get_field(field_name)
            self.assertIsNotNone(field, f"Field '{field_name}' should exist in Team Member")
        
        # Check team_role field is Link to Team Role
        team_role_field = meta.get_field("team_role")
        self.assertEqual(team_role_field.fieldtype, "Link")
        self.assertEqual(team_role_field.options, "Team Role")
        self.assertEqual(team_role_field.reqd, 1, "team_role should be required")
        
        # Check role_type is fetch field
        role_type_field = meta.get_field("role_type")
        self.assertEqual(role_type_field.fetch_from, "team_role.role_name")
        
        print("✅ Team Member field structure is correct")
    
    def test_basic_team_creation_with_role(self):
        """Test creating a team with team members using new role system"""
        print("Testing basic team creation with roles...")
        
        # Create a simple team
        team = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team Role Basic",
            "status": "Active",
            "team_type": "Project Team",
            "start_date": today()
        })
        team.insert()
        self.track_doc("Team", team.name)
        
        # Get an existing volunteer to use
        volunteers = frappe.get_all("Volunteer", limit=1)
        if not volunteers:
            self.skipTest("No volunteers available for testing")
        
        volunteer_name = volunteers[0].name
        
        # Add team member with new team_role field
        team.append("team_members", {
            "volunteer": volunteer_name,
            "team_role": "Team Member",  # Link to Team Role
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team.save()
        
        # Verify team member was created correctly
        team.reload()
        self.assertEqual(len(team.team_members), 1)
        
        member = team.team_members[0]
        self.assertEqual(member.team_role, "Team Member")
        self.assertEqual(member.role_type, "Team Member", 
                        "role_type should be fetched from team_role.role_name")
        
        print("✅ Basic team creation with roles working")
    
    def test_unique_role_constraint_basic(self):
        """Test basic unique role constraint"""
        print("Testing unique role constraint...")
        
        # Get existing volunteers
        volunteers = frappe.get_all("Volunteer", limit=2)
        if len(volunteers) < 2:
            self.skipTest("Need at least 2 volunteers for testing")
        
        # Create team
        team = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team Role Unique",
            "status": "Active",
            "team_type": "Project Team", 
            "start_date": today()
        })
        team.insert()
        self.track_doc("Team", team.name)
        
        # Add first team leader - should succeed
        team.append("team_members", {
            "volunteer": volunteers[0].name,
            "team_role": "Team Leader",  # Unique role
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team.save()
        
        # Add second team leader - should fail
        team.append("team_members", {
            "volunteer": volunteers[1].name,
            "team_role": "Team Leader",  # Same unique role
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        # This should raise a validation error
        with self.assertRaises(frappe.ValidationError):
            team.save()
        
        print("✅ Unique role constraint working")
    
    def test_non_unique_role_multiple_assignment(self):
        """Test that non-unique roles can be assigned multiple times"""
        print("Testing non-unique role multiple assignment...")
        
        # Get existing volunteers
        volunteers = frappe.get_all("Volunteer", limit=3)
        if len(volunteers) < 3:
            self.skipTest("Need at least 3 volunteers for testing")
        
        # Create team
        team = frappe.get_doc({
            "doctype": "Team",
            "team_name": "Test Team Role Multiple",
            "status": "Active",
            "team_type": "Project Team",
            "start_date": today()
        })
        team.insert()
        self.track_doc("Team", team.name)
        
        # Add multiple team members with same non-unique role
        for i, volunteer in enumerate(volunteers):
            team.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": "Team Member",  # Non-unique role
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
        
        # This should succeed
        team.save()
        
        # Verify all members were added
        team.reload()
        self.assertEqual(len(team.team_members), 3)
        
        # All should have Team Member role
        for member in team.team_members:
            self.assertEqual(member.team_role, "Team Member")
            self.assertEqual(member.role_type, "Team Member")
        
        print("✅ Non-unique role multiple assignment working")
    
    def test_migration_field_consistency(self):
        """Test that existing data shows field consistency"""
        print("Testing migration field consistency...")
        
        # Check existing teams for field consistency
        teams_with_members = frappe.get_all("Team",
                                          filters={"status": "Active"},
                                          limit=5)
        
        inconsistent_count = 0
        total_members = 0
        
        for team_ref in teams_with_members:
            team = frappe.get_doc("Team", team_ref.name)
            
            for member in team.team_members:
                total_members += 1
                
                if member.is_active:
                    # Should have team_role
                    if not member.team_role:
                        inconsistent_count += 1
                        print(f"⚠️  Member without team_role: {member.volunteer}")
                        continue
                    
                    # team_role should exist
                    if not frappe.db.exists("Team Role", member.team_role):
                        inconsistent_count += 1
                        print(f"⚠️  Invalid team_role reference: {member.team_role}")
                        continue
                    
                    # role_type should match team_role.role_name
                    role_doc = frappe.get_doc("Team Role", member.team_role)
                    if member.role_type != role_doc.role_name:
                        inconsistent_count += 1
                        print(f"⚠️  Mismatched role_type: {member.role_type} != {role_doc.role_name}")
        
        if total_members == 0:
            print("ℹ️  No team members found for consistency testing")
        else:
            consistency_rate = (total_members - inconsistent_count) / total_members * 100
            print(f"ℹ️  Field consistency: {consistency_rate:.1f}% ({total_members - inconsistent_count}/{total_members})")
            
            # Allow up to 10% inconsistency for migration scenarios
            self.assertLessEqual(inconsistent_count / total_members, 0.1,
                               f"Too many inconsistent records: {inconsistent_count}/{total_members}")
        
        print("✅ Migration field consistency acceptable")


if __name__ == "__main__":
    # Enable test mode
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Run the tests
    unittest.main()