import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen.doctype.chapter_role.chapter_role import update_chapters_with_role


class TestChapterRole(FrappeTestCase):
    def setUp(self):
        # Generate a unique identifier using only alphanumeric characters
        self.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

        # Clean up any existing test roles
        self.cleanup_test_data()

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
        self.test_role.insert(ignore_permissions=True)

    def tearDown(self):
        self.cleanup_test_data()

    def cleanup_test_data(self):
        # Delete any test roles
        for role in frappe.get_all(
            "Chapter Role", filters={"role_name": ["like", f"Test Admin Role {self.unique_id}%"]}
        ):
            try:
                frappe.delete_doc("Chapter Role", role.name, force=True)
            except Exception as e:
                print(f"Error cleaning up role {role.name}: {str(e)}")

        # Also clean up any roles with "Chair" in the name
        for role in frappe.get_all(
            "Chapter Role", filters={"role_name": ["like", f"Chair Role%{self.unique_id}%"]}
        ):
            try:
                frappe.delete_doc("Chapter Role", role.name, force=True)
            except Exception as e:
                print(f"Error cleaning up role {role.name}: {str(e)}")

        # Delete any test chapters
        for chapter in frappe.get_all(
            "Chapter", filters={"name": ["like", f"Test Chapter {self.unique_id}%"]}
        ):
            try:
                frappe.delete_doc("Chapter", chapter.name, force=True)
            except Exception as e:
                print(f"Error cleaning up chapter {chapter.name}: {str(e)}")

        # Delete any test members
        for member in frappe.get_all("Member", filters={"email": ["like", f"%{self.unique_id}@example.com"]}):
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception as e:
                print(f"Error cleaning up member {member.name}: {str(e)}")

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
        role1.insert(ignore_permissions=True)

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
        role2.insert(ignore_permissions=True)

        # Verify both roles exist and are marked as chair
        self.assertTrue(role1.is_chair, "First role should be marked as chair")
        self.assertTrue(role2.is_chair, "Second role should be marked as chair")

    def test_update_chapters_with_role(self):
        """Test that updating a role to chair updates chapter heads"""
        # Modify the test to focus on the update_chapters_with_role function

        # Create our test member with a unique name
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": f"Member {self.unique_id}",
                "email": f"test{self.unique_id}@example.com",
            }
        )
        member.insert(ignore_permissions=True)

        # Create test chapter
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test Chapter for Chair Role Test",
                "published": 1,
            }
        )
        chapter.insert(ignore_permissions=True)
        chapter.reload()

        # Add our test member as board member with the test role
        chapter.append(
            "board_members",
            {
                "member": member.name,
                "member_name": member.full_name,
                "email": member.email,
                "chapter_role": self.test_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save()
        chapter.reload()

        # Store the initial state - might be set to the member already due to automatic updates
        initial_chapter_head = chapter.chapter_head

        # Update the role to be chair
        self.test_role.is_chair = 1
        self.test_role.save()

        # Call the update function
        result = update_chapters_with_role(self.test_role.name)

        # Reload chapter to see changes
        chapter.reload()

        # Verify the chapter head is now set to our test member
        # (regardless of what it was before)
        self.assertEqual(
            chapter.chapter_head,
            member.name,
            "Chapter head should be set to the board member after role is marked as chair",
        )

        # Verify that the update function returns correctly
        self.assertEqual(result["chapters_found"], 1, "Should find one chapter with this role")

        # Check if update actually changed anything
        if initial_chapter_head != member.name:
            self.assertEqual(result["chapters_updated"], 1, "Should update one chapter")
        else:
            # If chapter_head was already set to member.name, there was nothing to update
            pass
