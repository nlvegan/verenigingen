# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import unittest

import frappe


class TestVolunteerInterestCategory(unittest.TestCase):
    def setUp(self):
        # Create test categories
        self.create_test_categories()

    def tearDown(self):
        # Clean up test data
        for category in ["Test Parent Category", "Test Child Category", "Test Grandchild"]:
            try:
                frappe.delete_doc("Volunteer Interest Category", category)
            except Exception:
                pass

    def create_test_categories(self):
        """Create test category hierarchy"""
        # Create parent category
        if not frappe.db.exists("Volunteer Interest Category", "Test Parent Category"):
            self.parent_category = frappe.get_doc(
                {
                    "doctype": "Volunteer Interest Category",
                    "category_name": "Test Parent Category",
                    "description": "Test parent category",
                }
            )
            self.parent_category.insert()
        else:
            self.parent_category = frappe.get_doc("Volunteer Interest Category", "Test Parent Category")

        # Create child category
        if not frappe.db.exists("Volunteer Interest Category", "Test Child Category"):
            self.child_category = frappe.get_doc(
                {
                    "doctype": "Volunteer Interest Category",
                    "category_name": "Test Child Category",
                    "description": "Test child category",
                    "parent_category": "Test Parent Category",
                }
            )
            self.child_category.insert()
        else:
            self.child_category = frappe.get_doc("Volunteer Interest Category", "Test Child Category")

    def test_category_creation(self):
        """Test creating a category"""
        category = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": "Test Creation Category",
                "description": "Test category creation",
            }
        )
        category.insert()

        # Verify record was created correctly
        self.assertEqual(category.category_name, "Test Creation Category")
        self.assertEqual(category.description, "Test category creation")

        # Clean up
        frappe.delete_doc("Volunteer Interest Category", category.name)

    def test_parent_child_relationship(self):
        """Test parent-child relationship between categories"""
        # Verify child category has correct parent
        self.assertEqual(self.child_category.parent_category, "Test Parent Category")

        # Create a grandchild category
        grandchild = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": "Test Grandchild",
                "description": "Test grandchild category",
                "parent_category": "Test Child Category",
            }
        )
        grandchild.insert()

        # Verify nested hierarchy
        self.assertEqual(grandchild.parent_category, "Test Child Category")

        # Get parent of grandchild's parent
        parent_of_parent = frappe.get_value(
            "Volunteer Interest Category", grandchild.parent_category, "parent_category"
        )
        self.assertEqual(parent_of_parent, "Test Parent Category")

    def test_circular_reference_prevention(self):
        """Test prevention of circular references in category hierarchy"""
        # Try to set child as parent of parent (should fail)
        with self.assertRaises(Exception):
            self.parent_category.parent_category = "Test Child Category"
            self.parent_category.save()

        # Try to set self as parent (should fail)
        with self.assertRaises(Exception):
            self.child_category.parent_category = "Test Child Category"
            self.child_category.save()

    def test_category_usage_in_volunteer(self):
        """Test using categories in volunteer records"""
        # Create a test volunteer with interests
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Category Test Volunteer",
                "email": "category.test@example.org",
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        )

        # Add parent category as interest
        volunteer.append("interests", {"interest_area": "Test Parent Category"})

        # Add child category as interest
        volunteer.append("interests", {"interest_area": "Test Child Category"})

        volunteer.insert()

        # Verify interests were added
        self.assertEqual(len(volunteer.interests), 2)
        categories = [i.interest_area for i in volunteer.interests]
        self.assertIn("Test Parent Category", categories)
        self.assertIn("Test Child Category", categories)

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name)
