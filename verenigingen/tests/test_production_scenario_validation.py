#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Production Scenario Validation Tests

These tests validate scenarios that commonly occur in production but
might not be covered by standard unit tests.
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestProductionScenarios(VereningingenTestCase):
    """Test common production scenarios that caused issues"""

    def test_volunteer_duplicate_names(self):
        """Test volunteer creation with identical names (real-world scenario)"""
        # Create two members with identical names (common in reality)
        member1 = self.create_test_member(
            first_name="John", 
            last_name="Smith",
            email="john.smith.1@example.com"
        )
        member2 = self.create_test_member(
            first_name="John", 
            last_name="Smith", 
            email="john.smith.2@example.com"
        )
        
        # Both volunteers should be created successfully
        vol1 = self.create_test_volunteer(member=member1.name)
        vol2 = self.create_test_volunteer(member=member2.name)
        
        # Verify they have different document names despite same volunteer_name
        self.assertNotEqual(vol1.name, vol2.name, 
                          "Volunteers with same names should have unique document names")
        
        # Verify both volunteers exist and are valid
        self.assertTrue(frappe.db.exists("Volunteer", vol1.name))
        self.assertTrue(frappe.db.exists("Volunteer", vol2.name))
        
        # Test the new autoname format
        self.assertTrue(vol1.name.startswith("VOL-"), 
                       f"Volunteer name should start with VOL-, got: {vol1.name}")
        self.assertTrue(vol2.name.startswith("VOL-"), 
                       f"Volunteer name should start with VOL-, got: {vol2.name}")

    def test_membership_dues_template_field_access(self):
        """Test that membership type code doesn't access non-existent template fields"""
        # Create a membership type with dues schedule template
        template = self.create_test_dues_schedule(is_template=1)
        
        membership_type = frappe.get_doc("Membership Type", template.membership_type)
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        
        # This should not raise AttributeError for maximum_amount
        try:
            options = membership_type.get_contribution_options()
            
            # Verify all required fields are present
            self.assertIn("maximum", options)
            self.assertIsInstance(options["maximum"], (int, float))
            self.assertGreater(options["maximum"], 0)
            
        except AttributeError as e:
            if "maximum_amount" in str(e):
                self.fail(f"Code tried to access non-existent template.maximum_amount field: {e}")
            else:
                raise

    def test_common_name_scenarios(self):
        """Test volunteer creation with common names that could cause collisions"""
        common_names = [
            ("John", "Smith"), ("Mary", "Johnson"), ("James", "Williams"),
            ("Patricia", "Brown"), ("Robert", "Jones"), ("Jennifer", "Garcia"),
            ("Michael", "Davis"), ("Linda", "Rodriguez"), ("David", "Martinez"),
            ("Barbara", "Hernandez")
        ]
        
        created_volunteers = []
        
        for first_name, last_name in common_names:
            # Create member
            member = self.create_test_member(
                first_name=first_name,
                last_name=last_name,
                email=f"{first_name.lower()}.{last_name.lower()}.{len(created_volunteers)}@example.com"
            )
            
            # Create volunteer - should succeed even with common names
            volunteer = self.create_test_volunteer(member=member.name)
            created_volunteers.append(volunteer)
        
        # Verify all volunteers were created successfully
        self.assertEqual(len(created_volunteers), len(common_names))
        
        # Verify all have unique document names
        volunteer_names = [v.name for v in created_volunteers]
        unique_names = set(volunteer_names)
        self.assertEqual(len(volunteer_names), len(unique_names), 
                        "All volunteers should have unique document names")

    def test_edge_case_name_scenarios(self):
        """Test volunteer creation with edge case names"""
        edge_cases = [
            # Skip empty names as they're required fields
            # {"first_name": "", "last_name": "SingleName"},  # first_name is required
            # {"first_name": "Single", "last_name": ""},      # last_name is required
            {"first_name": "Very", "last_name": "Long Name With Spaces"},
            {"first_name": "Special-Chars", "last_name": "O'Connor"},
            {"first_name": "Unicode", "last_name": "Müller"},
        ]
        
        for i, name_data in enumerate(edge_cases):
            with self.subTest(scenario=name_data):
                # Create member with edge case name
                member = self.create_test_member(
                    first_name=name_data["first_name"],
                    last_name=name_data["last_name"],
                    email=f"edge.case.{i}@example.com"
                )
                
                # Volunteer creation should handle edge cases gracefully
                volunteer = self.create_test_volunteer(member=member.name)
                
                # Verify volunteer was created
                self.assertTrue(frappe.db.exists("Volunteer", volunteer.name))
                self.assertTrue(volunteer.name.startswith("VOL-"))

    def test_template_field_completeness(self):
        """Test that all template fields referenced in code actually exist"""
        template = self.create_test_dues_schedule(is_template=1)
        
        # Get the template document
        template_doc = frappe.get_doc("Membership Dues Schedule", template.name)
        
        # Fields that the code tries to access - verify they exist
        required_fields = [
            "contribution_mode",
            "minimum_amount", 
            "suggested_amount",
            # Note: maximum_amount was removed as it doesn't exist
        ]
        
        for field in required_fields:
            self.assertTrue(hasattr(template_doc, field), 
                          f"Template should have field '{field}' that code tries to access")

    def test_application_workflow_name_handling(self):
        """Test the full application workflow with realistic names"""
        # Create a membership type first
        membership_type = self.create_test_membership_type()
        
        # Simulate a realistic application
        application_data = {
            "first_name": "Maria",
            "last_name": "Rodriguez", 
            "email": "maria.rodriguez.test@example.com",
            "birth_date": "1990-05-15",
            "interested_in_volunteering": 1,
            "selected_membership_type": membership_type.name
        }
        
        # Create member through application process (similar to production)
        from verenigingen.utils.application_helpers import generate_application_id, create_member_from_application
        
        app_id = generate_application_id()
        
        # Create member from application
        member = create_member_from_application(application_data, app_id)
        self.track_doc("Member", member.name)
        
        # Verify member was created successfully
        self.assertEqual(member.first_name, "Maria")
        self.assertEqual(member.last_name, "Rodriguez")
        self.assertEqual(member.application_id, app_id)
        
        # If interested in volunteering, volunteer record should be created
        if application_data["interested_in_volunteering"]:
            from verenigingen.utils.application_helpers import create_volunteer_record
            volunteer = create_volunteer_record(member)
            
            if volunteer:
                self.track_doc("Volunteer", volunteer.name)
                # Verify volunteer uses new naming convention
                self.assertTrue(volunteer.name.startswith("VOL-"))
                
    def test_system_health_check(self):
        """Monitor system health and check for recent error patterns"""
        from frappe.utils import add_days
        
        # Check for frequent error patterns in the last hour
        one_hour_ago = add_days(frappe.utils.now(), -1/24)
        
        error_patterns = frappe.db.sql('''
            SELECT SUBSTRING(error, 1, 100) as pattern, COUNT(*) as count
            FROM `tabError Log` 
            WHERE creation >= %s
            GROUP BY pattern
            HAVING count > 2
            ORDER BY count DESC
            LIMIT 5
        ''', (one_hour_ago,), as_dict=True)
        
        if error_patterns:
            pattern_summary = []
            for p in error_patterns:
                pattern_summary.append(f"- {p.pattern[:80]}... ({p.count} occurrences)")
            
            # Log warning but don't fail test (for now)
            warning_msg = f"High-frequency error patterns detected:\n" + "\n".join(pattern_summary)
            frappe.logger().warning(warning_msg)
            print(f"SYSTEM HEALTH WARNING: {warning_msg}")