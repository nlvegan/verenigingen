import unittest
import uuid

import frappe
from frappe.utils import today

from verenigingen.verenigingen.doctype.volunteer.volunteer import sync_chapter_board_members


class TestChapterVolunteerIntegration(unittest.TestCase):
    def setUp(self):
        # Create a unique identifier for this test run
        self.test_id = str(uuid.uuid4()).replace("-", "")[:12]

        # Test data
        self.test_members = []
        self.test_volunteers = []

        # Create test data in the right order
        self.create_test_chapter_roles()
        self.create_test_chapter()
        self.create_test_members_and_volunteers()

    def tearDown(self):
        # Clean up test data in reverse order to avoid link errors
        # First clear board members from chapter
        if hasattr(self, "test_chapter") and self.test_chapter:
            try:
                self.test_chapter = frappe.get_doc("Chapter", self.test_chapter.name)
                self.test_chapter.board_members = []
                self.test_chapter.save(ignore_permissions=True)
            except Exception as e:
                print(f"Error clearing board members: {e}")

        # Delete test volunteers
        for volunteer in self.test_volunteers:
            try:
                frappe.delete_doc("Volunteer", volunteer, force=True, ignore_permissions=True)
            except Exception as e:
                print(f"Error deleting volunteer {volunteer}: {e}")

        # Delete test members
        for member in self.test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True)
            except Exception as e:
                print(f"Error deleting member {member.name}: {e}")

        # Delete the chapter
        if hasattr(self, "test_chapter") and self.test_chapter:
            try:
                frappe.delete_doc("Chapter", self.test_chapter.name, force=True, ignore_permissions=True)
            except Exception as e:
                print(f"Error deleting chapter {self.test_chapter.name}: {e}")

        # Delete the chapter head member and volunteer
        if hasattr(self, "chapter_head_member") and self.chapter_head_member:
            try:
                frappe.delete_doc(
                    "Member", self.chapter_head_member.name, force=True, ignore_permissions=True
                )
            except Exception as e:
                print(f"Error deleting chapter head {self.chapter_head_member.name}: {e}")

        if hasattr(self, "chapter_head_volunteer") and self.chapter_head_volunteer:
            try:
                frappe.delete_doc(
                    "Verenigingen Volunteer",
                    self.chapter_head_volunteer.name,
                    force=True,
                    ignore_permissions=True,
                )
            except Exception as e:
                print(f"Error deleting chapter head volunteer {self.chapter_head_volunteer.name}: {e}")

        # Delete chapter roles
        for role in ["Chair", "Secretary", "Treasurer", "New Role"]:
            try:
                if frappe.db.exists("Chapter Role", role):
                    frappe.delete_doc("Chapter Role", role, force=True, ignore_permissions=True)
            except Exception as e:
                print(f"Error deleting role {role}: {e}")

    def create_test_chapter_roles(self):
        """Create test chapter roles for use in board memberships"""
        roles = [
            {"name": "Chair", "is_chair": 1, "is_unique": 1},
            {"name": "Secretary", "is_unique": 1},
            {"name": "Treasurer", "is_unique": 1},
            {"name": "New Role", "is_unique": 0},
        ]

        for role_data in roles:
            if not frappe.db.exists("Chapter Role", role_data["name"]):
                role_doc = frappe.get_doc(
                    {
                        "doctype": "Chapter Role",
                        "name": role_data["name"],
                        "role_name": role_data["name"],
                        "permissions_level": "Admin",
                        "is_chair": role_data.get("is_chair", 0),
                        "is_unique": role_data.get("is_unique", 0),
                        "is_active": 1,
                    }
                )
                role_doc.insert(ignore_permissions=True)

    def create_test_chapter(self):
        """Create a test chapter with unique name using UUID"""
        # Create a member for chapter head with unique email
        head_email = f"chapterhead{self.test_id}@example.com"

        # Create a new chapter head
        self.chapter_head_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Chapter",
                "last_name": f"Head{self.test_id[:8]}",
                "email": head_email,
            }
        )
        self.chapter_head_member.insert(ignore_permissions=True)

        # Create volunteer for chapter head
        self.chapter_head_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Chapter Head Volunteer {self.test_id[:8]}",
                "email": f"chapterheadv{self.test_id[:8]}@example.org",
                "member": self.chapter_head_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        self.chapter_head_volunteer.insert(ignore_permissions=True)

        # Generate a unique name for the test chapter
        test_chapter_name = f"TestChapter{self.test_id[:8]}"

        # Create the chapter
        self.test_chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": test_chapter_name,
                "chapter_head": self.chapter_head_member.name,
                "region": "TestRegion",
                "introduction": "Test chapter for integration tests",
            }
        )
        self.test_chapter.insert(ignore_permissions=True)

        return self.test_chapter

    def create_test_members_and_volunteers(self):
        """Create test members and volunteers with unique names using UUID"""
        for i in range(3):
            # Unique email with UUID
            email = f"boardmember{i}{self.test_id}@example.com"

            # Create member with unique name
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": f"Board{i}",
                    "last_name": f"Test{self.test_id[:6]}{i}",  # Using UUID for uniqueness
                    "email": email,
                }
            )
            member.insert(ignore_permissions=True)
            self.test_members.append(member)

            # Create volunteer for member
            volunteer_name = f"TestVol{i}{self.test_id[:6]}"
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": volunteer_name,
                    "email": f"{volunteer_name.lower()}@example.org",
                    "member": member.name,
                    "status": "Active",
                    "start_date": today(),
                }
            )
            volunteer.insert(ignore_permissions=True)
            self.test_volunteers.append(volunteer.name)

    def add_board_members_to_chapter(self):
        """Add test volunteers as board members to test chapter"""
        # Define board roles
        roles = ["Chair", "Secretary", "Treasurer"]

        # Add each volunteer with a role
        for i, volunteer_name in enumerate(self.test_volunteers):
            role = roles[i % len(roles)]

            # Verify the role exists
            if not frappe.db.exists("Chapter Role", role):
                frappe.throw(f"Test chapter role {role} does not exist")

            # Get volunteer details
            volunteer = frappe.get_doc("Volunteer", volunteer_name)

            self.test_chapter.append(
                "board_members",
                {
                    "volunteer": volunteer_name,
                    "volunteer_name": volunteer.volunteer_name,
                    "email": volunteer.email,
                    "chapter_role": role,
                    "from_date": today(),
                    "is_active": 1,
                },
            )

        self.test_chapter.save(ignore_permissions=True)

    def test_board_assignments_sync(self):
        """Test syncing board positions to volunteer assignments"""
        # Add board members to chapter
        self.add_board_members_to_chapter()

        # Run the sync function
        sync_chapter_board_members()

        # Reload volunteer to get latest data
        volunteer = frappe.get_doc("Volunteer", self.test_volunteers[0])

        # Get aggregated assignments - the proper way to check assignments
        assignments = volunteer.get_aggregated_assignments()

        # Check if there's a board assignment for this chapter
        has_board_assignment = False
        for assignment in assignments:
            if (
                assignment.get("source_type") == "Board Position"
                and assignment.get("source_doctype") == "Chapter"
                and assignment.get("source_name") == self.test_chapter.name
            ):
                has_board_assignment = True
                break

        self.assertTrue(has_board_assignment, "Volunteer should have a board position assignment")

    def test_duplicate_roles_validation(self):
        """Test validation of duplicate unique roles"""
        # Add first board member with Chair role (unique)
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteers[0],
                "volunteer_name": frappe.get_value(
                    "Verenigingen Volunteer", self.test_volunteers[0], "volunteer_name"
                ),
                "email": frappe.get_value("Volunteer", self.test_volunteers[0], "email"),
                "chapter_role": "Chair",  # Unique role
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save(ignore_permissions=True)

        # Try to add another board member with same unique role
        # This should fail validation
        with self.assertRaises(Exception):
            self.test_chapter.append(
                "board_members",
                {
                    "volunteer": self.test_volunteers[1],
                    "volunteer_name": frappe.get_value(
                        "Verenigingen Volunteer", self.test_volunteers[1], "volunteer_name"
                    ),
                    "email": frappe.get_value("Volunteer", self.test_volunteers[1], "email"),
                    "chapter_role": "Chair",  # Same unique role
                    "from_date": today(),
                    "is_active": 1,
                },
            )
            self.test_chapter.save(ignore_permissions=True)

    def test_non_unique_roles(self):
        """Test that non-unique roles can be assigned to multiple people"""
        # Add first board member with non-unique role
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteers[0],
                "volunteer_name": frappe.get_value(
                    "Verenigingen Volunteer", self.test_volunteers[0], "volunteer_name"
                ),
                "email": frappe.get_value("Volunteer", self.test_volunteers[0], "email"),
                "chapter_role": "New Role",  # Non-unique role
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save(ignore_permissions=True)

        # Add another board member with same non-unique role
        # This should succeed
        try:
            self.test_chapter.append(
                "board_members",
                {
                    "volunteer": self.test_volunteers[1],
                    "volunteer_name": frappe.get_value(
                        "Verenigingen Volunteer", self.test_volunteers[1], "volunteer_name"
                    ),
                    "email": frappe.get_value("Volunteer", self.test_volunteers[1], "email"),
                    "chapter_role": "New Role",  # Same non-unique role
                    "from_date": today(),
                    "is_active": 1,
                },
            )
            self.test_chapter.save(ignore_permissions=True)

            # Count board members with this role
            count = 0
            for member in self.test_chapter.board_members:
                if member.chapter_role == "New Role" and member.is_active:
                    count += 1

            self.assertEqual(count, 2, "Should allow two active board members with the same non-unique role")
        except Exception as e:
            self.fail(f"Failed to add multiple board members with non-unique role: {str(e)}")
