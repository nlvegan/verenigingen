import unittest
import uuid

import frappe
from frappe.utils import cint, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# FIXME: sync_chapter_board_members does not exist in volunteer.volunteer
# from verenigingen.verenigingen.doctype.volunteer.volunteer import sync_chapter_board_members


class TestChapterVolunteerIntegration(EnhancedTestCase):
    # Logical role -> flags. The docnames are built per run in
    # create_test_chapter_roles(); see the note there on why they are scoped.
    ROLE_SPECS = [
        {"key": "Chair", "is_chair": 1, "is_unique": 1},
        {"key": "Secretary", "is_unique": 1},
        {"key": "Treasurer", "is_unique": 1},
        {"key": "New Role", "is_unique": 0},
    ]

    def setUp(self):
        # Create a unique identifier for this test run
        super().setUp()
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
                self.test_chapter.save()  # EnhancedTestCase handles permissions properly
            except Exception as e:
                print(f"Error clearing board members: {e}")

        # Delete test volunteers
        for volunteer in self.test_volunteers:
            try:
                frappe.delete_doc("Volunteer", volunteer, force=True)
            except Exception as e:
                print(f"Error deleting volunteer {volunteer}: {e}")

        # Delete test members
        for member in self.test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception as e:
                print(f"Error deleting member {member.name}: {e}")

        # Delete the chapter
        if hasattr(self, "test_chapter") and self.test_chapter:
            try:
                frappe.delete_doc("Chapter", self.test_chapter.name, force=True)
            except Exception as e:
                print(f"Error deleting chapter {self.test_chapter.name}: {e}")

        # Delete the chapter head member and volunteer
        if hasattr(self, "chapter_head_member") and self.chapter_head_member:
            try:
                frappe.delete_doc("Member", self.chapter_head_member.name, force=True)
            except Exception as e:
                print(f"Error deleting chapter head {self.chapter_head_member.name}: {e}")

        if hasattr(self, "chapter_head_volunteer") and self.chapter_head_volunteer:
            try:
                frappe.delete_doc("Volunteer", self.chapter_head_volunteer.name, force=True)
            except Exception as e:
                print(f"Error deleting chapter head volunteer {self.chapter_head_volunteer.name}: {e}")

        # Delete chapter roles -- only the ones THIS run created. The bare names
        # ("Chair", ...) are global master data other modules build and link to,
        # and this loop force-deleted them by name whether or not it had created
        # them. Measured: the delete does succeed on an unlinked Chapter Role,
        # but inside the harness it is undone by the teardown rollback, so no
        # stranding was observed -- scoping the loop closes a latent hazard, not
        # a demonstrated one. The demonstrated half of #1272 is the read
        # direction, in create_test_chapter_roles() below.
        for role in getattr(self, "board_roles", {}).values():
            try:
                if frappe.db.exists("Chapter Role", role):
                    frappe.delete_doc("Chapter Role", role, force=True)
            except Exception as e:
                print(f"Error deleting role {role}: {e}")
        super().tearDown()

    def create_test_chapter_roles(self):
        """Create this run's own chapter roles, under names no co-tenant can claim.

        Chapter Role is autonamed ``field:role_name``, so a bare name like
        "Chair" is a GLOBAL key. This module needs Chair/Secretary/Treasurer to
        carry ``is_unique=1``, but at least five other test modules create a
        "Chair" leaving ``is_unique`` at its 0 default. Whichever ran first in the shard
        won the name, the get-or-create here then skipped creation, and
        test_duplicate_roles_validation asserted on a flag nobody had set --
        failing with "Exception not raised" on code the branch never touched
        (#1272). Role uniqueness is enforced from the ``is_unique`` FLAG
        (board_member_validator._get_unique_roles), never from the role's name,
        so a run-scoped name is behaviour-identical for what these tests assert.
        """
        self.board_roles = {}

        for spec in self.ROLE_SPECS:
            role_name = f"{spec['key']} {self.test_id[:8]}"
            frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Admin",
                    "is_chair": spec.get("is_chair", 0),
                    "is_unique": spec.get("is_unique", 0),
                    "is_active": 1,
                }
            ).insert()  # EnhancedTestCase handles permissions properly
            self.board_roles[spec["key"]] = role_name

    def create_test_chapter(self):
        # NOTE: Intentionally local — complex multi-doc setup (member+volunteer+board head)
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
        self.chapter_head_member.insert()  # EnhancedTestCase handles permissions properly

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
        self.chapter_head_volunteer.insert()  # EnhancedTestCase handles permissions properly

        # Generate a unique name for the test chapter
        test_chapter_name = f"TestChapter{self.test_id[:8]}"

        # Ensure the referenced Region master exists (idempotent). Region
        # autoname is field:region_name (slugified), so match on the slugified
        # docname to avoid a PRIMARY-key clash with a pre-existing Region.
        region_docname = "testregion"
        if not frappe.db.exists("Region", region_docname):
            frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": "TestRegion",
                    "region_code": "TSTR",
                    "country": "Netherlands",
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True)

        # Create the chapter
        self.test_chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": test_chapter_name,
                "chapter_head": self.chapter_head_member.name,
                "region": region_docname,
                "introduction": "Test chapter for integration tests",
            }
        )
        self.test_chapter.insert()  # EnhancedTestCase handles permissions properly

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
            member.insert()  # EnhancedTestCase handles permissions properly
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
            volunteer.insert()  # EnhancedTestCase handles permissions properly
            self.test_volunteers.append(volunteer.name)

    def add_board_members_to_chapter(self):
        """Add test volunteers as board members to test chapter"""
        # Define board roles (this run's own, see create_test_chapter_roles)
        roles = [self.board_roles[key] for key in ("Chair", "Secretary", "Treasurer")]

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

        self.test_chapter.save()  # EnhancedTestCase handles permissions properly

    def test_board_assignments_sync(self):
        """Test syncing board positions to volunteer assignments"""
        # Add board members to chapter
        self.add_board_members_to_chapter()

        # FIXME: sync_chapter_board_members does not exist
        # sync_chapter_board_members()

        # Reload volunteer to get latest data
        volunteer = frappe.get_doc("Volunteer", self.test_volunteers[0])

        # Get aggregated assignments - the proper way to check assignments
        assignments = volunteer.get_aggregated_assignments()

        # Check if there's a board assignment for this chapter.
        # The assignment service reports source_doctype as the child-table
        # DocType and exposes the human-readable parent type as
        # source_doctype_display ("Chapter").
        has_board_assignment = False
        for assignment in assignments:
            if (
                assignment.get("source_type") == "Board Position"
                and assignment.get("source_doctype_display") == "Chapter"
                and assignment.get("source_name") == self.test_chapter.name
            ):
                has_board_assignment = True
                break

        self.assertTrue(has_board_assignment, "Volunteer should have a board position assignment")

    def test_board_roles_are_run_scoped_and_carry_their_declared_flags(self):
        """Control for #1272: the roles these tests assert on must be this run's own.

        `Chapter Role` is autonamed ``field:role_name``, so the bare names this
        module used to take ("Chair", "Secretary", "Treasurer", "New Role") are
        global keys that any co-tenant in the shard can create first -- and at
        least five of them do, leaving ``is_unique`` at its 0 default. That
        silently disarmed test_duplicate_roles_validation, which then failed with
        "Exception not raised" on a branch that touched none of this code.

        Revert create_test_chapter_roles() to the bare-name get-or-create and
        this reddens on the first assertion with no co-tenant needed, and on the
        flag assertion when one is present. It also pins the tearDown contract:
        tearDown drops exactly ``self.board_roles``, so run-scoped names are what
        keep it from aiming a force-delete at a globally-named role this module
        did not create.
        """
        for spec in self.ROLE_SPECS:
            key = spec["key"]
            role_name = self.board_roles[key]

            self.assertNotEqual(
                role_name,
                key,
                f"Board role {key!r} must be run-scoped, not the global name any "
                f"other test module can claim or delete",
            )

            flags = frappe.db.get_value("Chapter Role", role_name, ["is_unique", "is_chair"], as_dict=True)
            self.assertIsNotNone(flags, f"Chapter Role {role_name!r} was not created")
            self.assertEqual(
                cint(flags.is_unique),
                spec.get("is_unique", 0),
                f"{role_name!r} does not carry the is_unique this module declared for {key!r}",
            )
            self.assertEqual(
                cint(flags.is_chair),
                spec.get("is_chair", 0),
                f"{role_name!r} does not carry the is_chair this module declared for {key!r}",
            )

    def test_duplicate_roles_validation(self):
        """Test validation of duplicate unique roles"""
        # Add first board member with Chair role (unique)
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteers[0],
                "volunteer_name": frappe.get_value("Volunteer", self.test_volunteers[0], "volunteer_name"),
                "email": frappe.get_value("Volunteer", self.test_volunteers[0], "email"),
                "chapter_role": self.board_roles["Chair"],  # Unique role
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save()  # EnhancedTestCase handles permissions properly

        # Try to add another board member with same unique role
        # This should fail validation
        with self.assertRaises(Exception):
            self.test_chapter.append(
                "board_members",
                {
                    "volunteer": self.test_volunteers[1],
                    "volunteer_name": frappe.get_value(
                        "Volunteer", self.test_volunteers[1], "volunteer_name"
                    ),
                    "email": frappe.get_value("Volunteer", self.test_volunteers[1], "email"),
                    "chapter_role": self.board_roles["Chair"],  # Same unique role
                    "from_date": today(),
                    "is_active": 1,
                },
            )
            self.test_chapter.save()  # EnhancedTestCase handles permissions properly

    def test_non_unique_roles(self):
        """Test that non-unique roles can be assigned to multiple people"""
        # Add first board member with non-unique role
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteers[0],
                "volunteer_name": frappe.get_value("Volunteer", self.test_volunteers[0], "volunteer_name"),
                "email": frappe.get_value("Volunteer", self.test_volunteers[0], "email"),
                "chapter_role": self.board_roles["New Role"],  # Non-unique role
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save()  # EnhancedTestCase handles permissions properly

        # Add another board member with same non-unique role
        # This should succeed
        try:
            self.test_chapter.append(
                "board_members",
                {
                    "volunteer": self.test_volunteers[1],
                    "volunteer_name": frappe.get_value(
                        "Volunteer", self.test_volunteers[1], "volunteer_name"
                    ),
                    "email": frappe.get_value("Volunteer", self.test_volunteers[1], "email"),
                    "chapter_role": self.board_roles["New Role"],  # Same non-unique role
                    "from_date": today(),
                    "is_active": 1,
                },
            )
            self.test_chapter.save()  # EnhancedTestCase handles permissions properly

            # Count board members with this role
            count = 0
            for member in self.test_chapter.board_members:
                if member.chapter_role == self.board_roles["New Role"] and member.is_active:
                    count += 1

            self.assertEqual(count, 2, "Should allow two active board members with the same non-unique role")
        except Exception as e:
            self.fail(f"Failed to add multiple board members with non-unique role: {str(e)}")
