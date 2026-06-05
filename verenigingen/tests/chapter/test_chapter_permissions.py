"""
Test Chapter Permission Model

Validates that:
1. Board members can only access their own chapters (row-level security)
2. Board members cannot delete chapters
3. Regular members can view but not edit chapters
4. Child table permissions work correctly
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterPermissions(EnhancedTestCase):
    """Test Chapter permission model and row-level security"""

    def setUp(self):
        """Set up test data with chapters and board members"""
        super().setUp()

        frappe.set_user("Administrator")

        # Create two chapters using Enhanced Test Factory
        self.chapter1 = self.create_test_chapter()
        self.chapter2 = self.create_test_chapter()

        # Create board member for chapter 1
        self.member1 = self.create_test_member(first_name="Board", last_name="Member1")
        self.user1 = self.create_test_user(self.member1.email, ["Verenigingen Chapter Board Member"])
        self.member1.user = self.user1.name
        self.member1.save()
        self.volunteer1 = self.create_test_volunteer(self.member1.name)

        # Add as board member
        self.chapter1.append(
            "board_members",
            {
                "volunteer": self.volunteer1.name,
                "chapter_role": self._get_test_chapter_role(),
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter1.save()
        self._ensure_board_member_role(self.user1.name)

        # Create board member for chapter 2
        self.member2 = self.create_test_member(first_name="Board", last_name="Member2")
        self.user2 = self.create_test_user(self.member2.email, ["Verenigingen Chapter Board Member"])
        self.member2.user = self.user2.name
        self.member2.save()
        self.volunteer2 = self.create_test_volunteer(self.member2.name)

        # Add as board member
        self.chapter2.append(
            "board_members",
            {
                "volunteer": self.volunteer2.name,
                "chapter_role": self._get_test_chapter_role(),
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        self.chapter2.save()
        self._ensure_board_member_role(self.user2.name)

        # Create regular member
        self.regular_member = self.create_test_member(first_name="Regular", last_name="Member")
        self.regular_user = self.create_test_user(self.regular_member.email, ["Verenigingen Member"])
        self.regular_member.user = self.regular_user.name
        self.regular_member.save()

    def _ensure_board_member_role(self, user_name):
        """Re-assert the Chapter Board Member role on a user.

        Creating a Volunteer for the member triggers synchronous account
        provisioning (member_role_service), which does `user.roles = []` and
        reassigns only member/volunteer roles. In production the board role is
        granted by the board-join workflow *after* provisioning; this helper
        replicates that ordering so row-level board permissions apply.
        """
        frappe.set_user("Administrator")
        user = frappe.get_doc("User", user_name)
        if "Verenigingen Chapter Board Member" not in [r.role for r in user.roles]:
            user.append("roles", {"role": "Verenigingen Chapter Board Member"})
            user.save()
            frappe.db.commit()
        # Drop any cached role set for this user so subsequent permission checks
        # (run under frappe.set_user(user_name)) see the freshly-added role.
        frappe.clear_cache(user=user_name)

    def _get_test_chapter_role(self):
        """Get or create a test chapter role"""
        role_name = "Test Board Role"
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.set_user("Administrator")
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "is_active": 1,
                }
            )
            role.insert()
        return role_name

    def test_board_member_can_access_own_chapter(self):
        """Board members can access their own chapter"""
        frappe.set_user(self.user1.name)

        # Should be able to read their own chapter
        doc = frappe.get_doc("Chapter", self.chapter1.name)
        self.assertEqual(doc.name, self.chapter1.name)

        # Should be able to modify a permlevel-0 field. (chapter_split_percentage
        # is permlevel 1 - board members lack permlevel-1 write, so writes to it
        # are silently dropped rather than persisted.)
        doc.postal_codes = "1000-1099"
        doc.save()
        doc.reload()
        self.assertEqual(doc.postal_codes, "1000-1099")

    def test_board_member_cannot_access_other_chapter(self):
        """Board members cannot access chapters they're not on the board of"""
        frappe.set_user(self.user1.name)

        # Should NOT be able to access chapter 2
        with self.assertRaises(frappe.PermissionError):
            doc = frappe.get_doc("Chapter", self.chapter2.name)
            doc.check_permission("read")

    def test_board_member_cannot_delete_chapter(self):
        """Board members cannot delete chapters"""
        frappe.set_user(self.user1.name)

        doc = frappe.get_doc("Chapter", self.chapter1.name)

        # Should NOT have delete permission
        self.assertFalse(doc.has_permission("delete"))

        # Attempting to delete should fail
        with self.assertRaises(frappe.PermissionError):
            doc.delete()

    def test_regular_member_can_view_chapter(self):
        """Regular members can view chapters (read-only)"""
        frappe.set_user(self.regular_user.name)

        # Should be able to read
        doc = frappe.get_doc("Chapter", self.chapter1.name)
        self.assertEqual(doc.name, self.chapter1.name)

        # Should NOT have write permission
        self.assertFalse(doc.has_permission("write"))

    def test_regular_member_cannot_edit_chapter(self):
        """Regular members cannot edit chapters"""
        frappe.set_user(self.regular_user.name)

        doc = frappe.get_doc("Chapter", self.chapter1.name)
        doc.chapter_split_percentage = 20

        # Attempting to save should fail
        with self.assertRaises(frappe.PermissionError):
            doc.save()

    def test_child_table_board_members_accessible(self):
        """Board members can view and edit board_members child table"""
        frappe.set_user(self.user1.name)

        doc = frappe.get_doc("Chapter", self.chapter1.name)

        # Should see board members
        self.assertGreater(len(doc.board_members), 0)
        self.assertEqual(doc.board_members[0].volunteer, self.volunteer1.name)

        # Should be able to add a new board member
        frappe.set_user("Administrator")
        new_member = self.create_test_member(
            first_name="New", last_name="Board"
        )
        new_volunteer = self.create_test_volunteer(new_member.name)

        frappe.set_user(self.user1.name)

        doc.append(
            "board_members",
            {
                "volunteer": new_volunteer.name,
                "chapter_role": self._get_test_chapter_role(),
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        doc.save()

        # Verify it was saved
        doc.reload()
        self.assertEqual(len(doc.board_members), 2)

    def test_child_table_members_accessible(self):
        """Board members can view and edit members child table"""
        frappe.set_user("Administrator")

        # Add a member to the chapter
        test_member = self.create_test_member(
            first_name="Chapter", last_name="Member"
        )

        frappe.set_user(self.user1.name)
        doc = frappe.get_doc("Chapter", self.chapter1.name)
        initial_count = len(doc.members)

        doc.append(
            "members",
            {
                "member": test_member.name,
                "chapter_join_date": frappe.utils.today(),
                "enabled": 1,
                "status": "Active",
            },
        )
        doc.save()

        # Reload and verify
        doc.reload()
        self.assertEqual(len(doc.members), initial_count + 1)
        # Check that our member is in the list
        member_names = [m.member for m in doc.members]
        self.assertIn(test_member.name, member_names)

    def test_administrator_has_full_access(self):
        """Administrators can access all chapters"""
        frappe.set_user("Administrator")

        # Can access both chapters
        doc1 = frappe.get_doc("Chapter", self.chapter1.name)
        doc2 = frappe.get_doc("Chapter", self.chapter2.name)

        self.assertEqual(doc1.name, self.chapter1.name)
        self.assertEqual(doc2.name, self.chapter2.name)

        # Can delete
        self.assertTrue(doc1.has_permission("delete"))
        self.assertTrue(doc2.has_permission("delete"))
