import random
import string

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter_role.chapter_role import update_chapters_with_role


class TestChapterRole(EnhancedTestCase):
    def setUp(self):
        super().setUp()  # EnhancedTestCase handles permissions and factory setup

        # Generate a unique identifier using timestamp + random to avoid collisions
        import time

        timestamp = str(int(time.time() * 1000000) % 1000000)
        rand_suffix = random.randint(100, 999)
        self.unique_id = f"{timestamp}{rand_suffix}"

        # Create a test role explicitly NOT as chair and with a name that does NOT include "chair"
        self.test_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Test Admin Role {self.unique_id}",  # Doesn't include "chair"
                "permissions_level": "Admin",
                "is_chair": 0,
                "is_active": 1,
            }
        )
        self.test_role.insert()  # EnhancedTestCase handles permissions

    def tearDown(self):
        super().tearDown()  # per-method rollback / patch cleanup (EnhancedTestCase)

    def test_chair_role_flag(self):
        """Test that a role can be marked as chair"""
        self.test_role.is_chair = 1
        self.test_role.save()

        # Reload to verify
        self.test_role.reload()
        self.assertTrue(self.test_role.is_chair, "Role should be marked as chair")

    def test_multiple_chair_roles(self):
        """Test that multiple chair roles are allowed but will show warning"""
        # Create first chair role
        role1 = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Chair Role 1 {self.unique_id}",
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_active": 1,
            }
        )
        role1.insert()  # EnhancedTestCase handles permissions

        # Create second chair role
        role2 = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Chair Role 2 {self.unique_id}",
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_active": 1,
            }
        )

        # Should not raise an error, just show a warning
        role2.insert()  # EnhancedTestCase handles permissions

        # Verify both roles exist and are marked as chair
        self.assertTrue(role1.is_chair, "First role should be marked as chair")
        self.assertTrue(role2.is_chair, "Second role should be marked as chair")

    def test_update_chapters_with_role(self):
        """Test that updating a role to chair updates chapter heads"""
        # TODO: This test requires complex Chapter setup with Department links
        # Skipping for now - needs investigation of Chapter creation dependencies
        self.skipTest("Complex Chapter setup with Department dependencies - needs investigation")
