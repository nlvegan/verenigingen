import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestChapterHead(FrappeTestCase):
    def setUp(self):
        # Generate a unique identifier using only alphanumeric characters
        self.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

        # Clean up any existing test data
        self.cleanup_test_data()

        # Create test chair role
        self.chair_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Chair {self.unique_id}",
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.chair_role.insert(ignore_permissions=True)

        # Create test regular role
        self.regular_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Secretary {self.unique_id}",
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.regular_role.insert(ignore_permissions=True)

        # Create test members
        self.chair_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Chair",
                "last_name": f"Member {self.unique_id}",
                "email": f"chair{self.unique_id}@example.com",
            }
        )
        self.chair_member.insert(ignore_permissions=True)

        self.regular_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Regular",
                "last_name": f"Member {self.unique_id}",
                "email": f"regular{self.unique_id}@example.com",
            }
        )
        self.regular_member.insert(ignore_permissions=True)

        # Create volunteers for the members
        self.chair_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Chair Volunteer {self.unique_id}",
                "email": f"chairv{self.unique_id}@example.org",
                "member": self.chair_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        self.chair_volunteer.insert(ignore_permissions=True)

        self.regular_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Regular Volunteer {self.unique_id}",
                "email": f"regularv{self.unique_id}@example.org",
                "member": self.regular_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        self.regular_volunteer.insert(ignore_permissions=True)

        # Create test chapter
        self.chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test Chapter for Head Tests",
                "published": 1,
            }
        )
        self.chapter.insert(ignore_permissions=True)

    def tearDown(self):
        self.cleanup_test_data()

    def cleanup_test_data(self):
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

        # Delete any test volunteers
        for volunteer in frappe.get_all(
            "Volunteer", filters={"email": ["like", f"%{self.unique_id}@example.org"]}
        ):
            try:
                frappe.delete_doc("Volunteer", volunteer.name, force=True)
            except Exception as e:
                print(f"Error cleaning up volunteer {volunteer.name}: {str(e)}")

        # Delete any test members
        for member in frappe.get_all("Member", filters={"email": ["like", f"%{self.unique_id}@example.com"]}):
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception as e:
                print(f"Error cleaning up member {member.name}: {str(e)}")

    def test_chapter_head_auto_update(self):
        """Test that chapter head is automatically updated based on chair role"""
        # Initially chapter should have no head
        self.assertIsNone(self.chapter.chapter_head, "Chapter should not have a head initially")

        # Add chair volunteer as board member with chair role
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.chair_volunteer.name,
                "volunteer_name": self.chair_volunteer.volunteer_name,
                "email": self.chair_volunteer.email,
                "chapter_role": self.chair_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()
        self.chapter.reload()

        # Chapter head should now be set to chair member (linked to volunteer)
        self.assertEqual(
            self.chapter.chapter_head,
            self.chair_member.name,
            "Chapter head should be set to member associated with volunteer with chair role",
        )

    def test_chapter_head_role_change(self):
        """Test that chapter head is updated when a role is changed to chair"""
        # Add regular volunteer as board member with regular role
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.regular_volunteer.name,
                "volunteer_name": self.regular_volunteer.volunteer_name,
                "email": self.regular_volunteer.email,
                "chapter_role": self.regular_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()
        self.chapter.reload()

        # Chapter head should not be set because the regular role is not a chair role
        self.assertIsNone(self.chapter.chapter_head, "Chapter head should not be set for regular role")

        # Update regular role to be chair
        self.regular_role.is_chair = 1
        self.regular_role.save()

        # Manually call the update function to ensure the chapters are updated
        # This is needed because hooks might not fire properly in tests
        from verenigingen.verenigingen.doctype.chapter_role.chapter_role import update_chapters_with_role

        update_chapters_with_role(self.regular_role.name)

        # Reload chapter to see changes
        self.chapter.reload()

        # Chapter head should now be set to the regular member
        self.assertEqual(
            self.chapter.chapter_head,
            self.regular_member.name,
            "Chapter head should be updated when role is changed to chair",
        )

    def test_chapter_head_member_change(self):
        """Test that chapter head is updated when board members change"""
        # Add chair volunteer as board member with chair role
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.chair_volunteer.name,
                "volunteer_name": self.chair_volunteer.volunteer_name,
                "email": self.chair_volunteer.email,
                "chapter_role": self.chair_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()
        self.chapter.reload()

        # Chapter head should be set to chair member
        self.assertEqual(
            self.chapter.chapter_head,
            self.chair_member.name,
            "Chapter head should be set to member associated with volunteer with chair role",
        )

        # Deactivate the chair member
        for board_member in self.chapter.board_members:
            if board_member.volunteer == self.chair_volunteer.name:
                board_member.is_active = 0
                board_member.to_date = frappe.utils.today()
                break

        self.chapter.save()

        # Make sure the update_chapter_head method is called
        self.chapter.update_chapter_head()
        self.chapter.save()

        self.chapter.reload()

        # Chapter head should now be None (not set)
        self.assertIsNone(
            self.chapter.chapter_head, "Chapter head should be cleared when chair member is deactivated"
        )

        # Add regular volunteer as new chair
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.regular_volunteer.name,
                "volunteer_name": self.regular_volunteer.volunteer_name,
                "email": self.regular_volunteer.email,
                "chapter_role": self.chair_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()
        self.chapter.reload()

        # Chapter head should now be set to regular member
        self.assertEqual(
            self.chapter.chapter_head,
            self.regular_member.name,
            "Chapter head should be updated to new chair member",
        )

    def test_chapter_head_multiple_chairs(self):
        """Test chapter head selection with multiple chair roles"""
        # Create another chair role
        chair_role2 = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"President {self.unique_id}",
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_unique": 1,
                "is_active": 1,
            }
        )
        chair_role2.insert(ignore_permissions=True)

        # Create another member for the second chair role
        chair_member2 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "President",
                "last_name": f"Member {self.unique_id}",
                "email": f"president{self.unique_id}@example.com",
            }
        )
        chair_member2.insert(ignore_permissions=True)

        # Create volunteer for the second member
        chair_volunteer2 = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"President Volunteer {self.unique_id}",
                "email": f"presidentv{self.unique_id}@example.org",
                "member": chair_member2.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        chair_volunteer2.insert(ignore_permissions=True)

        # Add first chair member
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.chair_volunteer.name,
                "volunteer_name": self.chair_volunteer.volunteer_name,
                "email": self.chair_volunteer.email,
                "chapter_role": self.chair_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )

        # Add second chair member with later date
        tomorrow = frappe.utils.add_days(frappe.utils.today(), 1)
        self.chapter.append(
            "board_members",
            {
                "volunteer": chair_volunteer2.name,
                "volunteer_name": chair_volunteer2.volunteer_name,
                "email": chair_volunteer2.email,
                "chapter_role": chair_role2.name,
                "from_date": tomorrow,
                "is_active": 1,
            },
        )

        self.chapter.save()
        self.chapter.reload()

        # One of the chair members should be set as chapter head
        # In case of multiple chairs, the implementation should be consistent
        # about which one it chooses (typically the first one found)
        self.assertTrue(
            self.chapter.chapter_head in [self.chair_member.name, chair_member2.name],
            "One of the chair members should be set as chapter head",
        )

    def test_role_uniqueness(self):
        """Test that unique roles can only be assigned once"""
        # Add a board member with the unique role (Secretary)
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.chair_volunteer.name,
                "volunteer_name": self.chair_volunteer.volunteer_name,
                "email": self.chair_volunteer.email,
                "chapter_role": self.regular_role.name,  # Secretary role (marked as unique)
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()

        # Now try to add another board member with the same unique role
        # This should raise a validation error
        with self.assertRaises(Exception):
            self.chapter.append(
                "board_members",
                {
                    "volunteer": self.regular_volunteer.name,
                    "volunteer_name": self.regular_volunteer.volunteer_name,
                    "email": self.regular_volunteer.email,
                    "chapter_role": self.regular_role.name,  # Same role (Secretary)
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                },
            )
            self.chapter.save()

    def test_non_unique_role(self):
        """Test that non-unique roles can be assigned multiple times"""
        # Create a non-unique role
        general_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Board Member {self.unique_id}",
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 0,  # Not unique
                "is_active": 1,
            }
        )
        general_role.insert(ignore_permissions=True)

        # Add a board member with the non-unique role
        self.chapter.append(
            "board_members",
            {
                "volunteer": self.chair_volunteer.name,
                "volunteer_name": self.chair_volunteer.volunteer_name,
                "email": self.chair_volunteer.email,
                "chapter_role": general_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter.save()

        # Now add another board member with the same non-unique role
        # This should succeed without error
        try:
            self.chapter.append(
                "board_members",
                {
                    "volunteer": self.regular_volunteer.name,
                    "volunteer_name": self.regular_volunteer.volunteer_name,
                    "email": self.regular_volunteer.email,
                    "chapter_role": general_role.name,  # Same non-unique role
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                },
            )
            self.chapter.save()
            self.chapter.reload()

            # Count board members with this role
            count = 0
            for member in self.chapter.board_members:
                if member.chapter_role == general_role.name and member.is_active:
                    count += 1

            self.assertEqual(count, 2, "Should allow two active board members with the same non-unique role")
        except Exception as e:
            self.fail(f"Failed to add multiple board members with non-unique role: {str(e)}")
