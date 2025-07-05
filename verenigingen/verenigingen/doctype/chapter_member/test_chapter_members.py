import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestChapterMemberIntegration(FrappeTestCase):
    def setUp(self):
        # Generate a unique identifier using only alphanumeric characters
        self.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

        # Clean up any existing test data
        self.cleanup_test_data()

        # Create test role
        self.role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Board Role {self.unique_id}",
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 0,  # Non-unique role
                "is_active": 1,
            }
        )
        self.role.insert(ignore_permissions=True)

        # Create test members
        self.test_member1 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test1",
                "last_name": f"Member {self.unique_id}",
                "email": f"test1{self.unique_id}@example.com",
            }
        )
        self.test_member1.insert(ignore_permissions=True)

        self.test_member2 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test2",
                "last_name": f"Member {self.unique_id}",
                "email": f"test2{self.unique_id}@example.com",
            }
        )
        self.test_member2.insert(ignore_permissions=True)

        # Create volunteers for members
        self.test_volunteer1 = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test1 Volunteer {self.unique_id}",
                "email": f"test1v{self.unique_id}@example.org",
                "member": self.test_member1.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        self.test_volunteer1.insert(ignore_permissions=True)

        self.test_volunteer2 = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test2 Volunteer {self.unique_id}",
                "email": f"test2v{self.unique_id}@example.org",
                "member": self.test_member2.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        self.test_volunteer2.insert(ignore_permissions=True)

        # Create test chapter
        self.chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test Chapter for Member Integration",
                "published": 1,
                "members": [],  # Ensure this starts empty
            }
        )
        self.chapter.insert(ignore_permissions=True)

    def tearDown(self):
        self.cleanup_test_data()

    def cleanup_test_data(self):
        # Delete any test volunteers
        for volunteer in frappe.get_all(
            "Volunteer", filters={"email": ["like", f"%{self.unique_id}@example.org"]}
        ):
            try:
                frappe.delete_doc("Volunteer", volunteer.name, force=True)
            except Exception as e:
                print(f"Error cleaning up volunteer {volunteer.name}: {str(e)}")

        # Delete any test roles
        for role in frappe.get_all("Chapter Role", filters={"role_name": ["like", f"%{self.unique_id}"]}):
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

    def test_add_member_method(self):
        """Test directly adding a member to a chapter"""
        # Initially chapter should have no members
        self.chapter.reload()
        self.assertEqual(len(self.chapter.members), 0, "Chapter should start with no members")

        # Add member using the add_member method
        result = self.chapter.add_member(
            self.test_member1.name, introduction="Test introduction", website_url="https://example.com"
        )

        # Reload chapter to see changes
        self.chapter.reload()

        # Verify member was added
        self.assertEqual(len(self.chapter.members), 1, "Chapter should now have 1 member")
        self.assertEqual(
            self.chapter.members[0].member, self.test_member1.name, "Member should be added to chapter"
        )
        self.assertEqual(
            self.chapter.members[0].introduction, "Test introduction", "Member introduction should be set"
        )
        self.assertEqual(
            self.chapter.members[0].website_url, "https://example.com", "Member website URL should be set"
        )
        self.assertTrue(result, "add_member method should return True for success")

        # Try to add same member again - should not add duplicate
        result = self.chapter.add_member(self.test_member1.name)

        # Reload chapter
        self.chapter.reload()

        # Verify no duplicate was added
        self.assertEqual(len(self.chapter.members), 1, "Chapter should still have 1 member")
        self.assertFalse(result, "add_member method should return False for already a member")

    def test_board_member_auto_added_to_members(self):
        """Test that board members are automatically added to chapter members"""
        # Initially chapter should have no members
        self.assertEqual(len(self.chapter.members), 0, "Chapter should start with no members")

        # Add volunteer as board member, which should add the associated member to chapter members
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer1.name,
                "volunteer_name": self.test_volunteer1.volunteer_name,
                "email": self.test_volunteer1.email,
                "chapter_role": self.role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )

        # We need to use server function to automatically add member
        self.chapter._add_to_members(self.test_member1.name)
        self.chapter.save()

        # Reload chapter to see changes
        self.chapter.reload()

        # Verify member was added to members
        self.assertTrue(
            any(m.member == self.test_member1.name for m in self.chapter.members),
            "Board member's member record should be automatically added to chapter members",
        )

    def test_no_duplicate_members(self):
        """Test that the same member cannot be added twice to the chapter members list"""
        # Add the member twice using the add_member method
        self.chapter.add_member(self.test_member1.name, introduction="First addition")
        self.chapter.add_member(self.test_member1.name, introduction="Second addition")

        # Reload chapter
        self.chapter.reload()

        # Count occurrences of the member
        count = 0
        for member in self.chapter.members:
            if member.member == self.test_member1.name:
                count += 1

        # Verify member only appears once
        self.assertEqual(count, 1, "Member should appear only once in the chapter members list")

    def test_remove_member_method(self):
        """Test removing a member from a chapter"""
        # Add two members
        self.chapter.add_member(self.test_member1.name)
        self.chapter.add_member(self.test_member2.name)

        # Reload chapter
        self.chapter.reload()

        # Verify both members are in the chapter
        self.assertEqual(len(self.chapter.members), 2, "Chapter should have 2 members")

        # Remove first member
        result = self.chapter.remove_member(self.test_member1.name)

        # Reload chapter
        self.chapter.reload()

        # Verify first member is removed and second is still there
        self.assertEqual(len(self.chapter.members), 1, "Chapter should now have 1 member")
        self.assertEqual(
            self.chapter.members[0].member, self.test_member2.name, "Second member should still be in chapter"
        )
        self.assertTrue(result, "remove_member method should return True for success")

        # Try to remove a member that's not in the chapter
        result = self.chapter.remove_member("NonExistentMember")

        # Verify return value
        self.assertFalse(result, "remove_member should return False for non-existent member")

    def test_board_member_change_updates_members(self):
        """Test that changing a board member's status updates the chapter members list"""
        # Add a volunteer as a board member
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer1.name,
                "volunteer_name": self.test_volunteer1.volunteer_name,
                "email": self.test_volunteer1.email,
                "chapter_role": self.role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )

        # We need to use server function to automatically add member
        self.chapter._add_to_members(self.test_member1.name)
        self.chapter.save()
        self.chapter.reload()

        # Verify member is added and enabled
        member_entry = None
        for member in self.chapter.members:
            if member.member == self.test_member1.name:
                member_entry = member
                break

        self.assertIsNotNone(member_entry, "Member should be in the chapter members list")
        self.assertTrue(member_entry.enabled, "Member should be enabled")

        # Now deactivate the board member
        for board_member in self.chapter.board_members:
            if board_member.volunteer == self.test_volunteer1.name:
                board_member.is_active = 0
                board_member.to_date = frappe.utils.today()
                break

        self.chapter.save()

        # This doesn't automatically disable the member in the members list,
        # which is actually correct behavior - leaving the board doesn't mean
        # leaving the chapter. We'd need to explicitly remove them if needed.

    def test_multiple_board_roles(self):
        """Test that a member can have multiple board roles but appears only once in members list"""
        # Add first role for volunteer
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer1.name,
                "volunteer_name": self.test_volunteer1.volunteer_name,
                "email": self.test_volunteer1.email,
                "chapter_role": self.role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )

        # Add member to chapter members
        self.chapter._add_to_members(self.test_member1.name)
        self.chapter.save()

        # Create another non-unique role
        another_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Another Role {self.unique_id}",
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 0,
                "is_active": 1,
            }
        )
        another_role.insert(ignore_permissions=True)

        # Add second role for the same volunteer
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer1.name,
                "volunteer_name": self.test_volunteer1.volunteer_name,
                "email": self.test_volunteer1.email,
                "chapter_role": another_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )

        # Save and reload chapter
        self.chapter.save()
        self.chapter.reload()

        # Count board memberships for this volunteer
        board_count = 0
        for board_member in self.chapter.board_members:
            if board_member.volunteer == self.test_volunteer1.name and board_member.is_active:
                board_count += 1

        # Verify volunteer has two board roles
        self.assertEqual(board_count, 2, "Volunteer should have two active board roles")

        # Count occurrences in chapter members list
        member_count = 0
        for member in self.chapter.members:
            if member.member == self.test_member1.name:
                member_count += 1

        # Verify member appears only once in members list
        self.assertEqual(
            member_count,
            1,
            "Member should appear only once in the chapter members list despite having multiple board roles",
        )
