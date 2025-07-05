# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

import random
import unittest

import frappe
from frappe.utils import today

if not hasattr(unittest, "skip_test_for_test_record_creation"):

    def skip_test_for_test_record_creation(cls):
        """Decorator to skip automatic test record creation"""
        return cls

    # Add to unittest module
    unittest.skip_test_for_test_record_creation = skip_test_for_test_record_creation


class VereningingenTestCase(unittest.TestCase):
    """Base test class for Verenigingen tests with helpful utility methods"""

    @classmethod
    def setUpClass(cls):
        """Set up common test environment"""
        super().setUpClass()
        # Disable automatic test record creation
        frappe.flags.make_test_records = False

    # Common helper methods can go here
    def create_test_member(self, email=None):
        """Create a test member record with unique name"""
        # Generate a random string for uniqueness - using only alphanumeric characters
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        unique_id = "".join(random.choice(chars) for _ in range(8))

        if not email:
            email = f"test{unique_id}@example.com"

        if frappe.db.exists("Member", {"email": email}):
            frappe.delete_doc("Member", frappe.db.get_value("Member", {"email": email}, "name"))

        # Use the unique_id in the name to ensure uniqueness, without special characters
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": f"Test{unique_id[:4]}",
                "last_name": f"Member{unique_id[4:]}",
                "email": email,
            }
        )
        member.insert(ignore_permissions=True)
        return member

    def create_test_volunteer(self, member=None):
        """Create a test volunteer record"""
        if not member:
            member = self.create_test_member()

        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test Volunteer {frappe.utils.random_string(5)}",
                "email": f"test.volunteer.{frappe.utils.random_string(5)}@example.org",
                "member": member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        volunteer.insert(ignore_permissions=True)
        return volunteer
