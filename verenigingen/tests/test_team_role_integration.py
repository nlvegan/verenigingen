#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Team Role Integration Tests

Tests the complete Team Role functionality including:
- Unique role validation per team
- Team leader system role assignment
- Migration data integrity
- Concurrent role assignment prevention
- Performance with large datasets
- Edge cases and error handling
"""

import unittest
from unittest.mock import patch
import frappe
from frappe.utils import today, add_days, now_datetime
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, BusinessRuleError


class TestTeamRoleIntegration(EnhancedTestCase):
    """Comprehensive tests for Team Role functionality"""
    
    def setUp(self):
        super().setUp()
        # Ensure all required Team Role fixtures exist
        self._ensure_team_role_fixtures()
        
    def _ensure_team_role_fixtures(self):
        """Ensure all required team roles exist for testing"""
        required_roles = [
            ("Team Leader", {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1}),
            ("Team Member", {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0}),
            ("Coordinator", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0}),
            ("Secretary", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1}),
            ("Treasurer", {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1})
        ]
        
        for role_name, attributes in required_roles:
            if not frappe.db.exists("Team Role", role_name):
                self.ensure_team_role(role_name, attributes)
    
    def test_unique_role_validation_per_team(self):
        """Test that unique roles can only be assigned once per team"""
        print("Testing unique role validation per team...")
        
        # Create team and volunteers
        team = self.create_test_team(team_name="Unique Role Test Team")
        volunteer1 = self.create_test_volunteer()
        volunteer2 = self.create_test_volunteer()
        
        # First assignment should succeed
        member1 = self.create_test_team_member(
            team.name, 
            volunteer1.name, 
            "Team Leader"
        )
        self.assertIsNotNone(member1)
        
        # Second assignment of same unique role should fail
        with self.assertRaises(frappe.ValidationError):
            self.create_test_team_member(
                team.name,
                volunteer2.name, 
                "Team Leader"
            )
        
        print("✅ Unique role validation working correctly")
    
    def test_unique_roles_across_different_teams(self):
        """Test that same unique role can be assigned in different teams"""
        print("Testing unique roles across different teams...")
        
        # Create two different teams
        team1 = self.create_test_team(team_name="Team One")
        team2 = self.create_test_team(team_name="Team Two")
        
        volunteer1 = self.create_test_volunteer()
        volunteer2 = self.create_test_volunteer()
        
        # Assign same unique role to both teams - should succeed
        member1 = self.create_test_team_member(team1.name, volunteer1.name, "Secretary")
        member2 = self.create_test_team_member(team2.name, volunteer2.name, "Secretary")
        
        self.assertIsNotNone(member1)
        self.assertIsNotNone(member2)
        
        print("✅ Same unique role can be assigned across different teams")
    
    def test_non_unique_role_multiple_assignments(self):
        """Test that non-unique roles can be assigned multiple times per team"""
        print("Testing non-unique role multiple assignments...")
        
        team = self.create_test_team(team_name="Multi Member Test Team")
        volunteers = [self.create_test_volunteer() for _ in range(3)]
        
        # Assign same non-unique role multiple times - should all succeed
        members = []
        for volunteer in volunteers:
            member = self.create_test_team_member(
                team.name, 
                volunteer.name, 
                "Team Member"
            )
            members.append(member)
        
        self.assertEqual(len(members), 3)
        
        # Also test Coordinator role (non-unique)
        volunteer4 = self.create_test_volunteer()
        coordinator = self.create_test_team_member(
            team.name,
            volunteer4.name,
            "Coordinator"
        )
        self.assertIsNotNone(coordinator)
        
        print("✅ Non-unique roles can be assigned multiple times per team")
    
    def test_team_leader_system_role_assignment(self):
        """Test that team leaders get proper system role assignment"""
        print("Testing team leader system role assignment...")
        
        team = self.create_test_team(team_name="Leadership Test Team")
        volunteer = self.create_test_volunteer()
        
        # Check initial system roles
        initial_roles = frappe.get_all("Has Role", 
                                     filters={"parent": volunteer.name},
                                     fields=["role"])
        initial_role_names = [r.role for r in initial_roles]
        
        # Assign team leader role
        team_member = self.create_test_team_member(
            team.name,
            volunteer.name, 
            "Team Leader"
        )
        
        # Check that system role was assigned
        volunteer.reload()
        current_roles = frappe.get_all("Has Role",
                                     filters={"parent": volunteer.name},
                                     fields=["role"])
        current_role_names = [r.role for r in current_roles]
        
        # Should have team lead role now
        if "Team Lead" not in initial_role_names:
            self.assertIn("Team Lead", current_role_names, 
                         "Team leader should receive Team Lead system role")
        
        print("✅ Team leader system role assignment working")
    
    def test_role_change_validation(self):
        """Test changing team member roles and validation"""
        print("Testing role change validation...")
        
        team = self.create_test_team(team_name="Role Change Test Team")
        volunteer = self.create_test_volunteer()
        
        # Start with basic team member
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Change to unique role - should succeed if no conflicts
        team_doc.team_members[0].team_role = "Treasurer"
        team_doc.save()
        
        # Add another member
        volunteer2 = self.create_test_volunteer()
        team_doc.append("team_members", {
            "volunteer": volunteer2.name,
            "team_role": "Team Member", 
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Try to change second member to same unique role - should fail
        team_doc.team_members[1].team_role = "Treasurer"
        with self.assertRaises(frappe.ValidationError):
            team_doc.save()
        
        print("✅ Role change validation working correctly")
    
    def test_inactive_member_role_validation(self):
        """Test that inactive members don't block unique role assignments"""
        print("Testing inactive member role validation...")
        
        team = self.create_test_team(team_name="Inactive Test Team")
        volunteer1 = self.create_test_volunteer()
        volunteer2 = self.create_test_volunteer()
        
        # Create team member with unique role
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer1.name,
            "team_role": "Secretary",
            "from_date": today(),
            "is_active": 0,  # Make inactive
            "status": "Inactive"
        })
        team_doc.save()
        
        # Should be able to assign same unique role to active member
        team_doc.append("team_members", {
            "volunteer": volunteer2.name,
            "team_role": "Secretary", 
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()  # Should succeed since first member is inactive
        
        print("✅ Inactive members don't block unique role assignments")
    
    def test_team_role_field_integration(self):
        """Test integration between team_role Link field and role_type fetch field"""
        print("Testing team role field integration...")
        
        team = self.create_test_team(team_name="Field Integration Test Team")
        volunteer = self.create_test_volunteer()
        
        # Create team member
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": "Coordinator",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Check that role_type is automatically fetched
        team_doc.reload()
        member = team_doc.team_members[0]
        
        self.assertEqual(member.team_role, "Coordinator")
        self.assertEqual(member.role_type, "Coordinator", 
                        "role_type should be fetched from team_role.role_name")
        
        print("✅ Team role field integration working correctly")
    
    def test_migration_data_integrity(self):
        """Test that migrated data maintains functionality"""
        print("Testing migration data integrity...")
        
        # This test assumes migration has already run
        # Check that existing teams have proper team_role references
        
        teams_with_members = frappe.get_all("Team", 
                                          filters={"status": "Active"},
                                          limit=5)
        
        for team_ref in teams_with_members:
            team = frappe.get_doc("Team", team_ref.name)
            
            for member in team.team_members:
                if member.is_active:
                    # Should have valid team_role reference
                    self.assertTrue(member.team_role, 
                                  f"Active team member should have team_role: {member}")
                    
                    # team_role should exist
                    self.assertTrue(frappe.db.exists("Team Role", member.team_role),
                                  f"Team role should exist: {member.team_role}")
                    
                    # role_type should be fetched correctly
                    if member.role_type:
                        role_doc = frappe.get_doc("Team Role", member.team_role) 
                        self.assertEqual(member.role_type, role_doc.role_name,
                                      "role_type should match team_role.role_name")
        
        print("✅ Migration data integrity validated")
    
    def test_performance_with_large_team(self):
        """Test performance with teams containing many members"""
        print("Testing performance with large team...")
        
        team = self.create_test_team(team_name="Large Performance Test Team")
        
        # Create multiple volunteers and team members
        member_count = 50
        volunteers = [self.create_test_volunteer() for _ in range(member_count)]
        
        # Time the team member creation
        import time
        start_time = time.time()
        
        team_doc = frappe.get_doc("Team", team.name)
        for i, volunteer in enumerate(volunteers):
            # Distribute roles (mostly Team Member, some Coordinators)
            role_name = "Coordinator" if i % 10 == 0 else "Team Member"
            
            team_doc.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": role_name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
        
        team_doc.save()
        end_time = time.time()
        
        duration = end_time - start_time
        self.assertLess(duration, 30.0, 
                       f"Large team creation should complete within 30 seconds (took {duration:.2f}s)")
        
        # Verify all members were added correctly
        team_doc.reload()
        self.assertEqual(len(team_doc.team_members), member_count)
        
        print(f"✅ Large team performance test passed ({duration:.2f}s for {member_count} members)")
    
    def test_concurrent_unique_role_assignment_prevention(self):
        """Test prevention of concurrent unique role assignments"""
        print("Testing concurrent unique role assignment prevention...")
        
        team = self.create_test_team(team_name="Concurrency Test Team")
        volunteer1 = self.create_test_volunteer()
        volunteer2 = self.create_test_volunteer()
        
        # Simulate concurrent assignment attempts
        # In real scenario, this would be two separate processes
        
        team_doc1 = frappe.get_doc("Team", team.name)
        team_doc2 = frappe.get_doc("Team", team.name)
        
        # Both try to add Secretary role
        team_doc1.append("team_members", {
            "volunteer": volunteer1.name,
            "team_role": "Secretary",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        team_doc2.append("team_members", {
            "volunteer": volunteer2.name,
            "team_role": "Secretary",
            "from_date": today(), 
            "is_active": 1,
            "status": "Active"
        })
        
        # First save should succeed
        team_doc1.save()
        
        # Second save should fail due to unique constraint
        with self.assertRaises(frappe.ValidationError):
            team_doc2.save()
        
        print("✅ Concurrent unique role assignment prevention working")
    
    def test_team_role_permissions_integration(self):
        """Test integration with permissions system"""
        print("Testing team role permissions integration...")
        
        # Get team roles with different permission levels
        leader_role = frappe.get_doc("Team Role", "Team Leader")
        member_role = frappe.get_doc("Team Role", "Team Member")
        coordinator_role = frappe.get_doc("Team Role", "Coordinator")
        
        # Verify permission levels are set correctly
        self.assertEqual(leader_role.permissions_level, "Leader")
        self.assertEqual(member_role.permissions_level, "Basic")
        self.assertEqual(coordinator_role.permissions_level, "Coordinator")
        
        # Verify team leader flag
        self.assertEqual(leader_role.is_team_leader, 1)
        self.assertEqual(member_role.is_team_leader, 0)
        self.assertEqual(coordinator_role.is_team_leader, 0)
        
        print("✅ Team role permissions integration validated")
    
    def test_error_handling_edge_cases(self):
        """Test error handling for various edge cases"""
        print("Testing error handling edge cases...")
        
        team = self.create_test_team(team_name="Error Handling Test Team")
        volunteer = self.create_test_volunteer()
        
        # Test with invalid team role
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": "Nonexistent Role",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        with self.assertRaises(frappe.LinkValidationError):
            team_doc.save()
        
        # Test with missing required fields
        team_doc.team_members = []  # Clear previous
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            # Missing team_role - should fail
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        with self.assertRaises(frappe.MandatoryError):
            team_doc.save()
        
        print("✅ Error handling for edge cases working correctly")
    
    def test_team_role_audit_trail(self):
        """Test audit trail for team role changes"""
        print("Testing team role audit trail...")
        
        team = self.create_test_team(team_name="Audit Trail Test Team")
        volunteer = self.create_test_volunteer()
        
        # Create initial team member
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append("team_members", {
            "volunteer": volunteer.name,
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        team_doc.save()
        
        # Check that version history is created
        versions = frappe.get_all("Version", 
                                filters={"ref_doctype": "Team", "docname": team.name},
                                order_by="creation desc",
                                limit=1)
        
        self.assertTrue(len(versions) > 0, "Team changes should create version history")
        
        # Change role and verify new version
        team_doc.team_members[0].team_role = "Coordinator"
        team_doc.save()
        
        updated_versions = frappe.get_all("Version",
                                        filters={"ref_doctype": "Team", "docname": team.name},
                                        order_by="creation desc",
                                        limit=2)
        
        self.assertTrue(len(updated_versions) > len(versions), 
                       "Role changes should create additional version history")
        
        print("✅ Team role audit trail working correctly")


class TestTeamRoleEdgeCases(EnhancedTestCase):
    """Test edge cases and boundary conditions for Team Role functionality"""
    
    def setUp(self):
        super().setUp()
        # Ensure team role fixtures
        required_roles = ["Team Leader", "Team Member", "Secretary", "Treasurer", "Coordinator"]
        for role in required_roles:
            if not frappe.db.exists("Team Role", role):
                self.ensure_team_role(role)
    
    def test_team_role_deactivation_impact(self):
        """Test impact of deactivating team roles"""
        print("Testing team role deactivation impact...")
        
        # Create custom team role for testing
        test_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Test Custom Role",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1
        })
        test_role.insert()
        
        # Create team member with this role
        team = self.create_test_team(team_name="Deactivation Test Team")
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
        
        # Existing assignments should still work
        team_doc.reload()
        self.assertEqual(team_doc.team_members[0].team_role, test_role.name)
        
        # New assignments with deactivated role should fail
        volunteer2 = self.create_test_volunteer()
        team_doc.append("team_members", {
            "volunteer": volunteer2.name,
            "team_role": test_role.name,
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        })
        
        # This should validate and potentially warn about inactive role
        # (Implementation depends on business rules)
        try:
            team_doc.save()
            print("⚠️  System allows assignment of inactive roles (may be by design)")
        except frappe.ValidationError:
            print("✅ System prevents assignment of inactive roles")
        
        # Cleanup
        frappe.delete_doc("Team Role", test_role.name)
    
    def test_bulk_role_assignments(self):
        """Test bulk assignment of roles to multiple team members"""
        print("Testing bulk role assignments...")
        
        team = self.create_test_team(team_name="Bulk Assignment Test Team")
        volunteers = [self.create_test_volunteer() for _ in range(10)]
        
        # Bulk assign different roles
        team_doc = frappe.get_doc("Team", team.name)
        
        role_cycle = ["Team Member", "Coordinator", "Team Member", "Team Member", "Coordinator"]
        
        for i, volunteer in enumerate(volunteers):
            role_name = role_cycle[i % len(role_cycle)]
            team_doc.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": role_name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
        
        # Save all at once
        team_doc.save()
        
        # Verify all were saved correctly
        team_doc.reload()
        self.assertEqual(len(team_doc.team_members), 10)
        
        # Check role distribution
        coordinator_count = sum(1 for m in team_doc.team_members if m.team_role == "Coordinator")
        member_count = sum(1 for m in team_doc.team_members if m.team_role == "Team Member")
        
        self.assertEqual(coordinator_count, 4)  # 2 * 2 (cycle repeats twice)
        self.assertEqual(member_count, 6)       # 3 * 2 (cycle repeats twice)
        
        print("✅ Bulk role assignments working correctly")
    
    def test_role_modification_with_existing_assignments(self):
        """Test modifying team role properties with existing assignments"""
        print("Testing role modification with existing assignments...")
        
        # Create custom role for testing
        custom_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": "Modifiable Test Role",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1
        })
        custom_role.insert()
        
        # Create team members with this role
        team = self.create_test_team(team_name="Role Modification Test Team")
        volunteers = [self.create_test_volunteer() for _ in range(3)]
        
        team_doc = frappe.get_doc("Team", team.name)
        for volunteer in volunteers:
            team_doc.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": custom_role.name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
        team_doc.save()
        
        # Modify role to be unique - should trigger validation for existing assignments
        custom_role.is_unique = 1
        
        try:
            custom_role.save()
            # If save succeeds, check that only one assignment remains active
            team_doc.reload()
            active_count = sum(1 for m in team_doc.team_members 
                             if m.team_role == custom_role.name and m.is_active)
            
            if active_count > 1:
                print("⚠️  System allows multiple assignments of newly unique role")
            else:
                print("✅ System handled unique role modification correctly")
                
        except frappe.ValidationError:
            print("✅ System prevents making role unique when multiple assignments exist")
        
        # Cleanup
        frappe.delete_doc("Team Role", custom_role.name)
    
    def test_cross_team_volunteer_roles(self):
        """Test volunteer with roles in multiple teams"""
        print("Testing cross-team volunteer roles...")
        
        # Create multiple teams
        teams = [
            self.create_test_team(team_name="Cross Team Test 1"),
            self.create_test_team(team_name="Cross Team Test 2"),
            self.create_test_team(team_name="Cross Team Test 3")
        ]
        
        # Single volunteer in multiple teams with different roles
        volunteer = self.create_test_volunteer()
        
        roles = ["Team Leader", "Secretary", "Coordinator"]  # All different roles
        
        for team, role in zip(teams, roles):
            team_doc = frappe.get_doc("Team", team.name)
            team_doc.append("team_members", {
                "volunteer": volunteer.name,
                "team_role": role,
                "from_date": today(),
                "is_active": 1,
                "status": "Active"
            })
            team_doc.save()
        
        # Verify volunteer appears in all teams
        volunteer_teams = frappe.db.sql("""
            SELECT parent, team_role 
            FROM `tabTeam Member` 
            WHERE volunteer = %s AND is_active = 1
        """, [volunteer.name], as_dict=True)
        
        self.assertEqual(len(volunteer_teams), 3)
        
        # Verify different roles in each team
        assigned_roles = [vt.team_role for vt in volunteer_teams]
        self.assertEqual(set(assigned_roles), set(roles))
        
        print("✅ Cross-team volunteer roles working correctly")


if __name__ == "__main__":
    # Enable test mode
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Run the tests
    unittest.main()