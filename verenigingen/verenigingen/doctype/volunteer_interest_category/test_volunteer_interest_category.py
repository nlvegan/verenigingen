# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import random
import time

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerInterestCategory(EnhancedTestCase):
    def setUp(self):
        super().setUp()  # EnhancedTestCase handles permissions and factory setup

        # Generate a unique identifier using timestamp + random to avoid collisions
        timestamp = str(int(time.time() * 1000000) % 1000000)
        rand_suffix = random.randint(100, 999)
        self.unique_id = f"{timestamp}{rand_suffix}"

        # Create test categories
        self.create_test_categories()

    def tearDown(self):
        pass  # EnhancedTestCase handles cleanup automatically via database rollback

    def create_test_categories(self):
        """Create test category hierarchy"""
        # Create parent category with unique ID
        parent_name = f"Test Parent Category {self.unique_id}"
        self.parent_category = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": parent_name,
                "description": "Test parent category",
            }
        )
        self.parent_category.insert()  # EnhancedTestCase handles permissions

        # Create child category with unique ID
        child_name = f"Test Child Category {self.unique_id}"
        self.child_category = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": child_name,
                "description": "Test child category",
                "parent_category": parent_name,
            }
        )
        self.child_category.insert()  # EnhancedTestCase handles permissions

    def test_category_creation(self):
        """Test creating a category"""
        category_name = f"Test Creation Category {self.unique_id}"
        category = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": category_name,
                "description": "Test category creation",
            }
        )
        category.insert()  # EnhancedTestCase handles permissions

        # Verify record was created correctly
        self.assertEqual(category.category_name, category_name)
        self.assertEqual(category.description, "Test category creation")

        # EnhancedTestCase handles cleanup via database rollback

    def test_parent_child_relationship(self):
        """Test parent-child relationship between categories"""
        # Verify child category has correct parent
        parent_name = f"Test Parent Category {self.unique_id}"
        child_name = f"Test Child Category {self.unique_id}"
        self.assertEqual(self.child_category.parent_category, parent_name)

        # Create a grandchild category
        grandchild_name = f"Test Grandchild {self.unique_id}"
        grandchild = frappe.get_doc(
            {
                "doctype": "Volunteer Interest Category",
                "category_name": grandchild_name,
                "description": "Test grandchild category",
                "parent_category": child_name,
            }
        )
        grandchild.insert()  # EnhancedTestCase handles permissions

        # Verify nested hierarchy
        self.assertEqual(grandchild.parent_category, child_name)

        # Get parent of grandchild's parent
        parent_of_parent = frappe.get_value(
            "Volunteer Interest Category", grandchild.parent_category, "parent_category"
        )
        self.assertEqual(parent_of_parent, parent_name)

    def test_circular_reference_prevention(self):
        """Test prevention of circular references in category hierarchy"""
        child_name = f"Test Child Category {self.unique_id}"

        # Try to set child as parent of parent (should fail)
        with self.assertRaises(Exception):
            self.parent_category.parent_category = child_name
            self.parent_category.save()

        # Try to set self as parent (should fail)
        with self.assertRaises(Exception):
            self.child_category.parent_category = child_name
            self.child_category.save()

    def test_category_usage_in_volunteer(self):
        """Test using categories in volunteer records"""
        parent_name = f"Test Parent Category {self.unique_id}"
        child_name = f"Test Child Category {self.unique_id}"

        # Create a test volunteer with interests
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Category Test Volunteer {self.unique_id}",
                "email": f"category.test{self.unique_id}@example.org",
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        )

        # Add parent category as interest
        volunteer.append("interests", {"interest_area": parent_name})

        # Add child category as interest
        volunteer.append("interests", {"interest_area": child_name})

        volunteer.insert()  # EnhancedTestCase handles permissions

        # Verify interests were added
        self.assertEqual(len(volunteer.interests), 2)
        categories = [i.interest_area for i in volunteer.interests]
        self.assertIn(parent_name, categories)
        self.assertIn(child_name, categories)

        # EnhancedTestCase handles cleanup via database rollback
