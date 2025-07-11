# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Chapter whitelisted API methods
Tests the API endpoints that JavaScript calls
"""


import frappe
from frappe.utils import add_days, random_string, today

from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestChapterWhitelistMethods(VereningingenUnitTestCase):
    """Test Chapter whitelisted API methods as called from JavaScript"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        try:
            cls.test_env = TestEnvironmentSetup.create_standard_test_environment()
        except Exception:
            cls.test_env = {"chapters": []}

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        try:
            self.builder.cleanup()
        except Exception as e:
            frappe.logger().error(f"Cleanup error in test: {str(e)}")
        super().tearDown()

    def _create_test_chapter(self):
        """Helper to create a test chapter"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "chapter_name": f"Test Chapter {random_string(8)}",
                "chapter_code": random_string(4).upper(),
                "status": "Active",
            }
        )
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)
        return chapter

    def _create_test_member(self):
        """Helper to create a test member"""
        test_data = self.builder.with_member(first_name="Test", last_name="Member").build()
        return test_data["member"]

    def test_add_board_member_whitelist(self):
        """Test add_board_member method as called from JavaScript"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Test via API call (simulating JavaScript)
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
            doc=chapter.as_dict(),
            member=member.name,
            role="Board Member",
            start_date=today(),
        )

        # Verify board member was added
        chapter.reload()
        self.assertEqual(len(chapter.board_members), 1)
        board_member = chapter.board_members[0]
        self.assertEqual(board_member.member, member.name)
        self.assertEqual(board_member.role, "Board Member")
        self.assertEqual(board_member.status, "Active")

    def test_remove_board_member_whitelist(self):
        """Test remove_board_member method"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # First add a board member
        chapter.append(
            "board_members",
            {"member": member.name, "role": "Treasurer", "start_date": today(), "status": "Active"},
        )
        chapter.save(ignore_permissions=True)

        # Remove board member
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.remove_board_member",
            doc=chapter.as_dict(),
            member=member.name,
            end_date=today(),
        )

        # Verify board member was deactivated
        chapter.reload()
        board_member = chapter.board_members[0]
        self.assertEqual(board_member.status, "Inactive")
        self.assertEqual(str(board_member.end_date), today())

    def test_transition_board_role_whitelist(self):
        """Test transition_board_role method"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Add board member with initial role
        chapter.append(
            "board_members",
            {
                "member": member.name,
                "role": "Board Member",
                "start_date": add_days(today(), -90),
                "status": "Active",
            },
        )
        chapter.save(ignore_permissions=True)

        # Transition to new role
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.transition_board_role",
            doc=chapter.as_dict(),
            member=member.name,
            new_role="President",
            transition_date=today(),
        )

        # Verify role transition
        chapter.reload()
        # Should have 2 entries - old inactive, new active
        self.assertEqual(len(chapter.board_members), 2)

        # Old role should be inactive
        old_role = next(bm for bm in chapter.board_members if bm.role == "Board Member")
        self.assertEqual(old_role.status, "Inactive")
        self.assertEqual(str(old_role.end_date), today())

        # New role should be active
        new_role = next(bm for bm in chapter.board_members if bm.role == "President")
        self.assertEqual(new_role.status, "Active")
        self.assertEqual(str(new_role.start_date), today())

    def test_bulk_remove_board_members_whitelist(self):
        """Test bulk_remove_board_members method"""
        chapter = self._create_test_chapter()

        # Add multiple board members
        members = []
        for i in range(3):
            member = self._create_test_member()
            members.append(member.name)
            chapter.append(
                "board_members",
                {"member": member.name, "role": "Board Member", "start_date": today(), "status": "Active"},
            )
        chapter.save(ignore_permissions=True)

        # Remove first two members
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.bulk_remove_board_members",
            doc=chapter.as_dict(),
            member_list=members[:2],
            end_date=today(),
        )

        # Verify bulk removal
        chapter.reload()

        # First two should be inactive
        for i in range(2):
            board_member = next(bm for bm in chapter.board_members if bm.member == members[i])
            self.assertEqual(board_member.status, "Inactive")

        # Third should still be active
        board_member = next(bm for bm in chapter.board_members if bm.member == members[2])
        self.assertEqual(board_member.status, "Active")

    def test_bulk_deactivate_board_members_whitelist(self):
        """Test bulk_deactivate_board_members method"""
        chapter = self._create_test_chapter()

        # Add board members
        for i in range(2):
            member = self._create_test_member()
            chapter.append(
                "board_members",
                {"member": member.name, "role": "Board Member", "start_date": today(), "status": "Active"},
            )
        chapter.save(ignore_permissions=True)

        # Deactivate all board members
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.bulk_deactivate_board_members",
            doc=chapter.as_dict(),
            deactivation_date=today(),
        )

        # Verify all are deactivated
        chapter.reload()
        for board_member in chapter.board_members:
            self.assertEqual(board_member.status, "Inactive")
            self.assertEqual(str(board_member.end_date), today())

    def test_bulk_add_members_whitelist(self):
        """Test bulk_add_members method"""
        chapter = self._create_test_chapter()

        # Create multiple members
        member_names = []
        for i in range(3):
            member = self._create_test_member()
            member_names.append(member.name)

        # Bulk add members
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.bulk_add_members",
            doc=chapter.as_dict(),
            member_list=member_names,
        )

        # Verify members were added
        chapter.reload()
        self.assertEqual(len(chapter.members), 3)

        added_members = [cm.member for cm in chapter.members]
        for member_name in member_names:
            self.assertIn(member_name, added_members)

    def test_send_chapter_newsletter_whitelist(self):
        """Test send_chapter_newsletter method"""
        chapter = self._create_test_chapter()

        # Add members to chapter
        for i in range(2):
            member = self._create_test_member()
            chapter.append("members", {"member": member.name, "join_date": today()})
        chapter.save(ignore_permissions=True)

        # Test newsletter sending
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.send_chapter_newsletter",
            doc=chapter.as_dict(),
            subject="Test Newsletter",
            content="Test content",
            send_to="all_members",
        )

        # Verify result (actual email sending would be mocked in unit tests)
        self.assertIn("recipients", result)
        self.assertEqual(result["recipients"], 2)

    def test_validate_postal_codes_whitelist(self):
        """Test validate_postal_codes method"""
        chapter = self._create_test_chapter()

        # Add postal codes
        chapter.append("postal_codes", {"postal_code": "1234"})
        chapter.append("postal_codes", {"postal_code": "5678"})
        chapter.save(ignore_permissions=True)

        # Validate postal codes
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.validate_postal_codes",
            doc=chapter.as_dict(),
        )

        # Verify validation result
        self.assertIn("valid", result)
        self.assertIn("invalid", result)

    def test_get_board_memberships_whitelist(self):
        """Test get_board_memberships module function"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Add board membership
        chapter.append(
            "board_members",
            {"member": member.name, "role": "Secretary", "start_date": today(), "status": "Active"},
        )
        chapter.save(ignore_permissions=True)

        # Get board memberships
        memberships = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_board_memberships", member_name=member.name
        )

        # Verify membership found
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0]["chapter"], chapter.name)
        self.assertEqual(memberships[0]["role"], "Secretary")

    def test_get_chapter_board_history_whitelist(self):
        """Test get_chapter_board_history function"""
        chapter = self._create_test_chapter()

        # Add historical board members
        for i in range(3):
            member = self._create_test_member()
            chapter.append(
                "board_members",
                {
                    "member": member.name,
                    "role": "Board Member",
                    "start_date": add_days(today(), -365 + i * 30),
                    "end_date": add_days(today(), -335 + i * 30) if i < 2 else None,
                    "status": "Inactive" if i < 2 else "Active",
                },
            )
        chapter.save(ignore_permissions=True)

        # Get board history
        history = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_board_history",
            chapter_name=chapter.name,
            include_inactive=True,
        )

        # Verify history
        self.assertEqual(len(history), 3)
        active_count = sum(1 for h in history if h["status"] == "Active")
        self.assertEqual(active_count, 1)

    def test_get_chapter_stats_whitelist(self):
        """Test get_chapter_stats function"""
        chapter = self._create_test_chapter()

        # Add members and board members
        for i in range(5):
            member = self._create_test_member()
            chapter.append("members", {"member": member.name, "join_date": today()})

            if i < 2:  # First 2 as board members
                chapter.append(
                    "board_members",
                    {
                        "member": member.name,
                        "role": "Board Member",
                        "start_date": today(),
                        "status": "Active",
                    },
                )

        chapter.save(ignore_permissions=True)

        # Get stats
        stats = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_stats", chapter_name=chapter.name
        )

        # Verify stats
        self.assertEqual(stats["total_members"], 5)
        self.assertEqual(stats["active_board_members"], 2)
        self.assertIn("member_growth", stats)

    def test_suggest_chapters_for_member_whitelist(self):
        """Test suggest_chapters_for_member function"""
        member = self._create_test_member()
        member.postal_code = "1234"
        member.save(ignore_permissions=True)

        # Create chapters with postal codes
        chapter1 = self._create_test_chapter()
        chapter1.append("postal_codes", {"postal_code": "1234"})
        chapter1.save(ignore_permissions=True)

        chapter2 = self._create_test_chapter()
        chapter2.append("postal_codes", {"postal_code": "5678"})
        chapter2.save(ignore_permissions=True)

        # Get suggestions
        suggestions = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapters_for_member",
            member_name=member.name,
        )

        # Should suggest chapter1 based on postal code
        self.assertGreaterEqual(len(suggestions), 1)
        suggested_names = [s["name"] for s in suggestions]
        self.assertIn(chapter1.name, suggested_names)

    def test_assign_member_to_chapter_whitelist(self):
        """Test assign_member_to_chapter function"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Assign member to chapter
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter",
            member_name=member.name,
            chapter_name=chapter.name,
        )

        # Verify assignment
        chapter.reload()
        member.reload()

        self.assertEqual(member.primary_chapter, chapter.name)
        member_names = [cm.member for cm in chapter.members]
        self.assertIn(member.name, member_names)

    def test_join_leave_chapter_whitelist(self):
        """Test join_chapter and leave_chapter functions"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Join chapter
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.join_chapter",
            member_name=member.name,
            chapter_name=chapter.name,
        )

        # Verify join
        chapter.reload()
        member_names = [cm.member for cm in chapter.members]
        self.assertIn(member.name, member_names)

        # Leave chapter
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.leave_chapter",
            member_name=member.name,
            chapter_name=chapter.name,
        )

        # Verify leave
        chapter.reload()
        active_members = [cm.member for cm in chapter.members if not cm.leave_date]
        self.assertNotIn(member.name, active_members)

    def test_board_member_status_field(self):
        """Test the specific board member status field issue from the report"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Add board member with status field
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
            doc=chapter.as_dict(),
            member=member.name,
            role="President",
            start_date=today(),
        )

        # Verify status field is set correctly
        chapter.reload()
        board_member = chapter.board_members[0]
        self.assertEqual(board_member.status, "Active")

        # Test status field updates
        frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.remove_board_member",
            doc=chapter.as_dict(),
            member=member.name,
            end_date=today(),
        )

        chapter.reload()
        board_member = chapter.board_members[0]
        self.assertEqual(board_member.status, "Inactive")

    def test_permission_checks(self):
        """Test permission checks on whitelisted methods"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Create a non-admin user
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "test.chapter@example.com",
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        test_user.insert(ignore_permissions=True)
        self.track_doc("User", test_user.name)

        # Test as non-admin user
        with self.as_user("test.chapter@example.com"):
            # Should not be able to add board member without permissions
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
                    doc=chapter.as_dict(),
                    member=member.name,
                    role="Board Member",
                    start_date=today(),
                )

    def test_error_handling(self):
        """Test error handling in whitelisted methods"""
        chapter = self._create_test_chapter()

        # Test removing non-existent board member
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.remove_board_member",
                doc=chapter.as_dict(),
                member="non-existent-member",
                end_date=today(),
            )

        # Test invalid chapter assignment
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter",
                member_name="non-existent-member",
                chapter_name=chapter.name,
            )

    def test_data_integrity(self):
        """Test data integrity in chapter operations"""
        chapter = self._create_test_chapter()
        member = self._create_test_member()

        # Test duplicate board member prevention
        frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
            doc=chapter.as_dict(),
            member=member.name,
            role="Treasurer",
            start_date=today(),
        )

        # Try to add same member again with active role
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.add_board_member",
                doc=chapter.as_dict(),
                member=member.name,
                role="Secretary",
                start_date=today(),
            )
