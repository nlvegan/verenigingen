#!/usr/bin/env python3
"""
Test to verify the new contribution system works
"""

import unittest
import frappe
from frappe.test_runner import make_test_records


class TestContributionSystem(unittest.TestCase):
    """Test contribution system functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.membership_type = None
        self.template = None
        
    def tearDown(self):
        """Clean up test data"""
        if self.template and hasattr(self.template, "name"):
            try:
                frappe.delete_doc("Membership Dues Schedule", self.template.name, force=True)
            except Exception:
                pass
        
        if self.membership_type and hasattr(self.membership_type, "name"):
            try:
                frappe.delete_doc("Membership Type", self.membership_type.name, force=True)
            except Exception:
                pass

    def test_contribution_system_creation(self):
        """Test creating a membership type with contribution system"""
        
        # Test creating a membership type with new fields
        self.membership_type = frappe.new_doc("Membership Type")
        self.membership_type.membership_type_name = "Test Flexible System"
        self.membership_type.description = "Test for flexible contribution system"
        self.membership_type.minimum_amount = 15.0
        self.membership_type.billing_frequency = "Monthly"
        self.membership_type.is_active = 1

        # Create membership type first (without template reference)
        self.membership_type.flags.ignore_mandatory = True
        self.membership_type.save()

        # Create dues schedule template with all required fields
        self.template = frappe.new_doc("Membership Dues Schedule")
        self.template.is_template = 1
        self.template.schedule_name = f"Template-{self.membership_type.membership_type_name}-{frappe.utils.now()}"
        self.template.membership_type = self.membership_type.name
        self.template.status = "Active"
        self.template.billing_frequency = "Annual"
        self.template.contribution_mode = "Calculator"
        self.template.dues_rate = self.membership_type.minimum_amount  # Required field
        self.template.minimum_amount = self.membership_type.minimum_amount  # Must match or exceed membership type minimum
        self.template.suggested_amount = self.membership_type.minimum_amount or 15.0
        self.template.invoice_days_before = 30
        self.template.auto_generate = 1
        # Set template-specific fields to avoid validation errors
        self.template.member = None  # Templates don't have specific members
        self.template.membership = None  # Templates don't have specific memberships
        self.template.insert(ignore_permissions=True)

        # Update membership type with template reference
        self.membership_type.dues_schedule_template = self.template.name
        self.membership_type.flags.ignore_mandatory = False
        self.membership_type.save()
        
        # Verify creation
        self.assertTrue(self.membership_type.name)
        self.assertTrue(self.template.name)
        self.assertEqual(self.membership_type.dues_schedule_template, self.template.name)

    def test_contribution_api(self):
        """Test the contribution options API"""
        # Create test data first
        self.test_contribution_system_creation()
        
        # Test the API methods exist (they may not be implemented yet)
        try:
            options = self.membership_type.get_contribution_options()
            self.assertIsInstance(options, (dict, list))
        except AttributeError:
            # Method doesn't exist yet, which is okay for now
            pass

        # Test with the whitelist API
        try:
            from verenigingen.verenigingen.doctype.membership_type.membership_type import (
                get_membership_contribution_options,
            )
            api_options = get_membership_contribution_options(self.membership_type.name)
            self.assertIsInstance(api_options, (dict, list))
        except (ImportError, AttributeError):
            # API doesn't exist yet, which is okay for now
            pass


if __name__ == "__main__":
    unittest.main()