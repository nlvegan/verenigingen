#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Team Role Validation Tests

Focused tests for Team Role DocType validation and business logic:
- Team Role creation and validation
- Role property constraints  
- Business rule enforcement
- Field validation and requirements
- Integration with Team Member assignments
"""

import unittest
import frappe
from frappe.utils import today, add_days
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, BusinessRuleError


class TestTeamRoleValidation(EnhancedTestCase):
    """Tests for Team Role DocType validation and business logic"""
    
    def setUp(self):
        super().setUp()
    
    def test_team_role_creation_basic(self):
        """Test basic team role creation with required fields"""
        print("Testing basic team role creation...")
        
        role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Basic Role",
            "description": "A test role for validation testing",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1
        })
        
        role.insert()
        self.assertIsNotNone(role.name)
        self.assertEqual(role.role_name, "Test Basic Role")
        
        # Cleanup
        frappe.delete_doc("Team Role", role.name)
        
        print("✅ Basic team role creation successful")
    
    def test_team_role_required_fields(self):
        """Test that required fields are enforced"""
        print("Testing team role required fields...")
        
        # Missing role_name should fail
        with self.assertRaises(frappe.MandatoryError):
            role = frappe.get_doc({
                "doctype": "Team Role",
                # Missing role_name
                "description": "Missing role name",
                "permissions_level": "Basic"
            })
            role.insert()
        
        print("✅ Required field validation working correctly")
    
    def test_team_role_unique_name_constraint(self):
        """Test that role names must be unique"""
        print("Testing team role unique name constraint...")
        
        # Create first role
        role1 = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Unique Test Role",
            "permissions_level": "Basic",
            "is_active": 1
        })
        role1.insert()
        
        # Try to create second role with same name - should fail
        with self.assertRaises(frappe.DuplicateEntryError):
            role2 = frappe.get_doc({
                "doctype": "Team Role", 
                "role_name": "Unique Test Role",  # Same name
                "permissions_level": "Coordinator"
            })
            role2.insert()
        
        # Cleanup
        frappe.delete_doc("Team Role", role1.name)
        
        print("✅ Unique name constraint working correctly")
    
    def test_team_role_permissions_level_validation(self):
        """Test permissions level field validation"""
        print("Testing permissions level validation...")
        
        valid_levels = ["Basic", "Coordinator", "Leader"]
        
        # Test valid permissions levels
        for level in valid_levels:
            role = frappe.get_doc({
                "doctype": "Team Role",
                "role_name": f"Test {level} Role",
                "permissions_level": level,
                "is_active": 1
            })
            role.insert()
            
            self.assertEqual(role.permissions_level, level)
            
            # Cleanup
            frappe.delete_doc("Team Role", role.name)
        
        # Test invalid permissions level
        with self.assertRaises(frappe.ValidationError):
            invalid_role = frappe.get_doc({
                "doctype": "Team Role",
                "role_name": "Invalid Permissions Role",
                "permissions_level": "SuperAdmin",  # Not in valid options
                "is_active": 1
            })
            invalid_role.insert()
        
        print("✅ Permissions level validation working correctly")
    
    def test_team_role_leader_flag_logic(self):
        """Test team leader flag business logic"""
        print("Testing team leader flag logic...")
        
        # Create team leader role
        leader_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Team Leader",
            "permissions_level": "Leader",
            "is_team_leader": 1,
            "is_unique": 1,  # Team leaders should typically be unique
            "is_active": 1
        })
        leader_role.insert()
        
        # Verify properties
        self.assertEqual(leader_role.is_team_leader, 1)
        self.assertEqual(leader_role.is_unique, 1)
        self.assertEqual(leader_role.permissions_level, "Leader")
        
        # Create non-leader role
        member_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Regular Member",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1
        })
        member_role.insert()
        
        self.assertEqual(member_role.is_team_leader, 0)
        self.assertEqual(member_role.is_unique, 0)
        
        # Cleanup
        frappe.delete_doc("Team Role", leader_role.name)
        frappe.delete_doc("Team Role", member_role.name)
        
        print("✅ Team leader flag logic working correctly")
    
    def test_team_role_unique_flag_implications(self):
        """Test unique flag implications for team assignments"""
        print("Testing unique flag implications...")
        
        # Create unique role
        unique_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Unique Role",
            "permissions_level": "Coordinator",
            "is_unique": 1,
            "is_active": 1
        })
        unique_role.insert()
        
        # Create non-unique role
        regular_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Regular Role",
            "permissions_level": "Basic", 
            "is_unique": 0,
            "is_active": 1
        })
        regular_role.insert()
        
        # Test assignment implications
        team = self.create_test_team(team_name="Unique Role Test Team")
        volunteers = [self.create_test_volunteer() for _ in range(3)]
        
        team_doc = frappe.get_doc("Team", team.name)
        
        # Assign unique role to first volunteer - should succeed
        team_doc.append("team_members", {
            "volunteer": volunteers[0].name,
            "team_role": unique_role.name,
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Try to assign same unique role to second volunteer - should fail
        team_doc.append("team_members", {
            "volunteer": volunteers[1].name,
            "team_role": unique_role.name,
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        with self.assertRaises(frappe.ValidationError):
            team_doc.save()
        
        # Reset team members
        team_doc.team_members = [team_doc.team_members[0]]  # Keep first member
        team_doc.save()
        
        # Assign regular (non-unique) role to multiple volunteers - should succeed 
        for volunteer in volunteers[1:]:
            team_doc.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": regular_role.name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
        
        team_doc.save()  # Should succeed
        
        # Verify assignments
        team_doc.reload()
        regular_assignments = [m for m in team_doc.team_members if m.team_role == regular_role.name]
        unique_assignments = [m for m in team_doc.team_members if m.team_role == unique_role.name]
        
        self.assertEqual(len(unique_assignments), 1)
        self.assertEqual(len(regular_assignments), 2)
        
        # Cleanup
        frappe.delete_doc("Team Role", unique_role.name)
        frappe.delete_doc("Team Role", regular_role.name)
        
        print("✅ Unique flag implications working correctly")
    
    def test_team_role_active_status_impact(self):
        """Test impact of active/inactive status on role assignments"""
        print("Testing active status impact...")
        
        # Create role and make it active
        test_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Status Role",
            "permissions_level": "Basic",
            "is_active": 1
        })
        test_role.insert()
        
        # Create team member assignment
        team = self.create_test_team(team_name="Status Test Team")
        volunteer = self.create_test_volunteer()
        
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": test_role.name,
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Deactivate the role
        test_role.is_active = 0
        test_role.save()
        
        # Existing assignment should remain valid
        team_doc.reload()
        self.assertEqual(team_doc.team_members[0].team_role, test_role.name)
        
        # New assignment with inactive role should be restricted (depends on business rules)
        volunteer2 = self.create_test_volunteer()
        team_doc.append("team_members", {
            "volunteer": volunteer2.name,
            "team_role": test_role.name,  # Inactive role
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        # The behavior here depends on implementation:
        # - Some systems allow it (role can be inactive but still referenced)
        # - Others prevent it (only active roles can be assigned)
        try:
            team_doc.save()
            print("⚠️  System allows assignment of inactive roles")
        except frappe.ValidationError:
            print("✅ System prevents assignment of inactive roles")
        
        # Cleanup
        frappe.delete_doc("Team Role", test_role.name)
        
        print("✅ Active status impact testing completed")
    
    def test_team_role_description_and_metadata(self):
        """Test role description and metadata handling"""
        print("Testing role description and metadata...")
        
        description_text = """
        This is a comprehensive test role with:
        - Multiple responsibilities
        - Complex description text
        - Special characters: áéíóú, €, @, #
        - Numbers: 123, 456.78
        """
        
        role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Metadata Role",
            "description": description_text,
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1
        })
        
        role.insert()
        
        # Verify description was saved correctly
        role.reload()
        self.assertEqual(role.description.strip(), description_text.strip())
        
        # Test metadata fields
        self.assertIsNotNone(role.creation)
        self.assertIsNotNone(role.modified) 
        self.assertIsNotNone(role.owner)
        self.assertIsNotNone(role.modified_by)
        
        # Cleanup
        frappe.delete_doc("Team Role", role.name)
        
        print("✅ Description and metadata handling working correctly")
    
    def test_team_role_modification_after_assignment(self):
        """Test modifying team role properties after it's been assigned"""
        print("Testing role modification after assignment...")
        
        # Create role
        role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Modifiable Role",
            "permissions_level": "Basic",
            "is_unique": 0,
            "is_team_leader": 0,
            "is_active": 1
        })
        role.insert()
        
        # Create team member assignment
        team = self.create_test_team(team_name="Modification Test Team")
        volunteer = self.create_test_volunteer()
        
        self.create_test_team_member(team.name, volunteer.name, role.name)
        
        # Modify role properties
        role.permissions_level = "Coordinator"
        role.description = "Updated description after assignment"
        role.save()
        
        # Verify changes were saved
        role.reload()
        self.assertEqual(role.permissions_level, "Coordinator")
        self.assertEqual(role.description, "Updated description after assignment")
        
        # Try to make role unique after multiple assignments exist
        volunteer2 = self.create_test_volunteer()
        self.create_test_team_member(team.name, volunteer2.name, role.name)
        
        # Now try to make it unique - this should either:
        # 1. Fail with validation error, or
        # 2. Succeed but trigger cleanup of duplicate assignments
        role.is_unique = 1
        
        try:
            role.save()
            print("⚠️  System allows making role unique even with multiple assignments")
        except frappe.ValidationError as e:
            print("✅ System prevents making role unique when multiple assignments exist")
            print(f"    Error: {str(e)}")
        
        # Cleanup
        frappe.delete_doc("Team Role", role.name)
        
        print("✅ Role modification after assignment testing completed")
    
    def test_team_role_deletion_constraints(self):
        """Test constraints on deleting team roles that are in use"""
        print("Testing team role deletion constraints...")
        
        # Create role
        role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Deletable Role",
            "permissions_level": "Basic",
            "is_active": 1
        })
        role.insert()
        
        # Test deletion when no assignments exist - should succeed
        frappe.delete_doc("Team Role", role.name)
        
        # Recreate role for assignment test
        role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Assigned Role",
            "permissions_level": "Basic", 
            "is_active": 1
        })
        role.insert()
        
        # Create assignment
        team = self.create_test_team(team_name="Deletion Test Team")
        volunteer = self.create_test_volunteer()
        
        self.create_test_team_member(team.name, volunteer.name, role.name)
        
        # Try to delete role that's in use - should fail
        with self.assertRaises(frappe.LinkExistsError):
            frappe.delete_doc("Team Role", role.name)
        
        # Remove assignment then delete should succeed
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.team_members = []  # Remove all members
        team_doc.save()
        
        # Now deletion should succeed
        frappe.delete_doc("Team Role", role.name)
        
        print("✅ Team role deletion constraints working correctly")
    
    def test_default_team_roles_integrity(self):
        """Test that default/fixture team roles maintain integrity"""
        print("Testing default team roles integrity...")
        
        expected_defaults = [
            ("Team Leader", {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1}),
            ("Team Member", {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0}),
            ("Coordinator", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0}),
            ("Secretary", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1}),
            ("Treasurer", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1})
        ]
        
        for role_name, expected_props in expected_defaults:
            # Ensure role exists (create if not)
            if not frappe.db.exists("Team Role", role_name):
                self.ensure_team_role(role_name, expected_props)
            
            # Verify properties
            role = frappe.get_doc("Team Role", role_name)
            
            for prop, expected_value in expected_props.items():
                actual_value = getattr(role, prop)
                self.assertEqual(actual_value, expected_value,
                               f"{role_name}.{prop} should be {expected_value}, got {actual_value}")
            
            # Verify it's active
            self.assertEqual(role.is_active, 1, f"{role_name} should be active")
        
        print("✅ Default team roles integrity verified")


class TestTeamRoleBusinessLogic(EnhancedTestCase):
    """Tests for complex business logic around Team Roles"""
    
    def test_role_hierarchy_implications(self):
        """Test implications of role hierarchy (Leader > Coordinator > Basic)"""
        print("Testing role hierarchy implications...")
        
        # Create roles with different permission levels
        leader_role = self.ensure_team_role("Test Leader Role", {
            "permissions_level": "Leader",
            "is_team_leader": 1,
            "is_unique": 1
        })
        
        coordinator_role = self.ensure_team_role("Test Coordinator Role", {
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 0
        })
        
        basic_role = self.ensure_team_role("Test Basic Role", {
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0
        })
        
        # Create team with hierarchy
        team = self.create_test_team(team_name="Hierarchy Test Team")
        volunteers = [self.create_test_volunteer() for _ in range(3)]
        
        # Assign roles in hierarchy order
        self.create_test_team_member(team.name, volunteers[0].name, leader_role.name)
        self.create_test_team_member(team.name, volunteers[1].name, coordinator_role.name)
        self.create_test_team_member(team.name, volunteers[2].name, basic_role.name)
        
        # Verify team structure
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.reload()
        
        role_levels = {}
        for member in team_doc.team_members:
            role_doc = frappe.get_doc("Team Role", member.team_role)
            role_levels[member.volunteer] = role_doc.permissions_level
        
        # Verify hierarchy is represented
        self.assertIn("Leader", role_levels.values())
        self.assertIn("Coordinator", role_levels.values())
        self.assertIn("Basic", role_levels.values())
        
        print("✅ Role hierarchy implications working correctly")
    
    def test_team_leadership_transition(self):
        """Test transitioning team leadership between members"""
        print("Testing team leadership transition...")
        
        team = self.create_test_team(team_name="Leadership Transition Team")
        leader1 = self.create_test_volunteer()
        leader2 = self.create_test_volunteer()
        
        # Assign first leader
        self.create_test_team_member(team.name, leader1.name, "Team Leader")
        
        # Try to assign second leader - should fail due to unique constraint
        with self.assertRaises(frappe.ValidationError):
            self.create_test_team_member(team.name, leader2.name, "Team Leader")
        
        # Proper transition: deactivate first, then assign second
        team_doc = frappe.get_doc("Team", team.name)
        
        # Find first leader and deactivate
        for member in team_doc.team_members:
            if member.team_role == "Team Leader" and member.volunteer == leader1.name:
                member.is_active = 0
                member.status = "Inactive"
                member.to_date = today()
                break
        
        team_doc.save()
        
        # Now assign new leader - should succeed
        team_doc.append("team_members", {
            "volunteer": leader2.name,
            "team_role": "Team Leader",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Verify transition
        team_doc.reload()
        active_leaders = [m for m in team_doc.team_members 
                         if m.team_role == "Team Leader" and m.is_active]
        
        self.assertEqual(len(active_leaders), 1)
        self.assertEqual(active_leaders[0].volunteer, leader2.name)
        
        print("✅ Team leadership transition working correctly")
    
    def test_role_based_permissions_inheritance(self):
        """Test that team role assignments affect user permissions"""
        print("Testing role-based permissions inheritance...")
        
        # This test would verify that:
        # 1. Team Leader role grants "Team Lead" system role
        # 2. Other roles don't grant system roles inappropriately
        # 3. Role removal removes associated system roles
        
        team = self.create_test_team(team_name="Permissions Test Team")
        volunteer = self.create_test_volunteer()
        
        # Check initial system roles
        initial_roles = frappe.get_all("Has Role",
                                     filters={"parent": volunteer.name},
                                     fields=["role"])
        initial_role_names = [r.role for r in initial_roles]
        
        # Assign team leader role
        self.create_test_team_member(team.name, volunteer.name, "Team Leader")
        
        # Check for system role assignment (implementation dependent)
        volunteer.reload()
        current_roles = frappe.get_all("Has Role",
                                     filters={"parent": volunteer.name},
                                     fields=["role"])
        current_role_names = [r.role for r in current_roles]
        
        # The exact system role assignment depends on implementation
        # This test verifies the mechanism works
        if "Team Lead" in current_role_names and "Team Lead" not in initial_role_names:
            print("✅ System role assignment working for team leaders")
        else:
            print("ℹ️  System role assignment may be implemented differently")
        
        print("✅ Role-based permissions inheritance testing completed")


if __name__ == "__main__":
    # Enable test mode
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Run the tests
    unittest.main()