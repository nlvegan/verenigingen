# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Chapter whitelisted API methods
Tests the API endpoints that JavaScript calls
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestChapterWhitelistMethods(VereningingenTestCase):
    """Test Chapter whitelisted API methods as called from JavaScript"""

    def setUp(self):
        """Set up test environment using factory methods"""
        super().setUp()

        # Create test chapter using factory method with unique name
        from frappe.utils import random_string

        self.test_chapter = self.create_test_chapter(
            chapter_name=f"Test Chapter API {random_string(8)}", postal_codes="1000-9999"
        )

        # Create test chapter roles if they don't exist
        self._create_test_chapter_roles()

    # tearDown handled automatically by VereningingenTestCase

    def _create_test_chapter_roles(self):
        """Create test chapter roles for testing"""
        roles = ["Board Member", "President", "Secretary", "Treasurer"]

        for role_name in roles:
            if not frappe.db.exists("Chapter Role", role_name):
                role = frappe.get_doc(
                    {"doctype": "Chapter Role", "role_name": role_name, "is_active": 1, "is_unique": 0}
                )
                role.insert()
                self.track_doc("Chapter Role", role.name)
            elif not frappe.db.get_value("Chapter Role", role_name, "is_active"):
                # The role pre-exists on the site but is inactive; add_board_member
                # rejects inactive roles, so reactivate it for the test. (Without
                # this, the bare exists() guard silently reuses an inactive role and
                # every board-add test errors with "Chapter Role ... is not active".)
                frappe.db.set_value("Chapter Role", role_name, "is_active", 1)

    def test_add_board_member_whitelist(self):
        """Test add_board_member method as called from JavaScript"""
        chapter = self.test_chapter
        member = self.create_test_member()

        # Create volunteer for the member first
        volunteer = self.create_test_volunteer(member=member)

        # Test via API call (simulating JavaScript) - instance method via doc.run_method
        result = chapter.add_board_member(
            volunteer=volunteer.name,
            role="Board Member",
            from_date=today(),
        )

        # The endpoint must report success AND persist the board member, otherwise
        # a regression that silently no-ops (or returns {"success": False}) would
        # have slipped past the old assertion-free version of this test.
        self.assertTrue(result["success"], msg=result)
        chapter.reload()
        active = [
            b
            for b in chapter.board_members
            if b.volunteer == volunteer.name and b.chapter_role == "Board Member" and b.is_active
        ]
        self.assertEqual(len(active), 1, "board member must be persisted as an active row")

    def test_remove_board_member_whitelist(self):
        """Test remove_board_member method"""
        chapter = self.test_chapter
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member)

        # First add a board member via API
        chapter.add_board_member(
            volunteer=volunteer.name,
            role="Treasurer",
            from_date=today(),
        )

        # Remove board member
        result = chapter.remove_board_member(
            volunteer=volunteer.name,
            end_date=today(),
        )

        # remove_board_member must report success AND deactivate the row (is_active=0,
        # to_date set). The old assertIsNotNone passed even if the method silently
        # no-opped and left the volunteer as an active board member.
        self.assertTrue(result["success"], msg=result)
        chapter.reload()
        rows = [b for b in chapter.board_members if b.volunteer == volunteer.name]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].is_active, "board row must be deactivated after removal")

    def test_bulk_remove_board_members_whitelist(self):
        """Test bulk_remove_board_members method"""
        chapter = self.test_chapter

        # Add multiple board members via API, tracking the (volunteer, role, from_date)
        # tuple each row was created with — bulk_remove_board_members matches on all three.
        from_date = today()
        members_added = []
        for i in range(3):
            member = self.create_test_member()
            volunteer = self.create_test_volunteer(member=member)
            members_added.append(volunteer.name)
            chapter.add_board_member(
                volunteer=volunteer.name,
                role="Board Member",
                from_date=from_date,
            )

        # Remove first two members. bulk_remove_board_members expects a list of dicts
        # (volunteer/chapter_role/from_date), NOT bare volunteer strings — the previous
        # test passed strings so nothing was ever removed yet assertIsNotNone still passed.
        result = chapter.bulk_remove_board_members(
            board_members=[
                {"volunteer": v, "chapter_role": "Board Member", "from_date": from_date}
                for v in members_added[:2]
            ],
        )

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["processed"], 2, msg=result)
        chapter.reload()
        remaining = {b.volunteer for b in chapter.board_members if b.is_active}
        # First two removed entirely, third still active
        self.assertNotIn(members_added[0], remaining)
        self.assertNotIn(members_added[1], remaining)
        self.assertIn(members_added[2], remaining)

    def test_bulk_deactivate_board_members_whitelist(self):
        """Test bulk_deactivate_board_members method"""
        chapter = self.test_chapter

        # Add board members via API
        from_date = today()
        members_added = []
        for i in range(2):
            member = self.create_test_member()
            volunteer = self.create_test_volunteer(member=member)
            members_added.append(volunteer.name)
            chapter.add_board_member(
                volunteer=volunteer.name,
                role="Board Member",
                from_date=from_date,
            )

        # Deactivate all board members. Like bulk_remove, this matches on the full
        # (volunteer, chapter_role, from_date) tuple, so pass dicts, not strings.
        result = chapter.bulk_deactivate_board_members(
            board_members=[
                {"volunteer": v, "chapter_role": "Board Member", "from_date": from_date}
                for v in members_added
            ],
        )

        # Deactivate keeps the rows but flips is_active to 0 (unlike bulk_remove).
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["processed"], 2, msg=result)
        chapter.reload()
        for v in members_added:
            rows = [b for b in chapter.board_members if b.volunteer == v]
            self.assertEqual(len(rows), 1, f"row for {v} must be retained, not removed")
            self.assertFalse(rows[0].is_active, f"row for {v} must be deactivated")

    def test_bulk_add_members_whitelist(self):
        """Test bulk_add_members method"""
        chapter = self.test_chapter

        # Create multiple members
        member_data_list = []
        for i in range(3):
            member = self.create_test_member()
            member_data_list.append({"member_id": member.name, "introduction": f"Test member {i}"})

        # Bulk add members. The whitelisted Chapter.bulk_add_members is
        # annotated member_data_list: str, so Frappe's type coercion rejects a
        # raw list — pass the JSON string the HTTP boundary would receive.
        import json

        result = chapter.bulk_add_members(
            member_data_list=json.dumps(member_data_list),
        )

        # All three members must actually be added and appear in the chapter's member
        # list. assertIsNotNone would have passed even if 0 members were processed.
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["processed"], 3, msg=result)
        chapter.reload()
        member_ids = {m.member for m in chapter.members}
        for data in member_data_list:
            self.assertIn(data["member_id"], member_ids)

    def test_send_chapter_newsletter_whitelist(self):
        """Test send_chapter_newsletter method"""
        chapter = self.test_chapter

        # Add members to chapter via API
        added_emails = []
        for i in range(2):
            member = self.create_test_member()
            chapter.add_member(member.name, introduction=f"Test member {i}")
            added_emails.append(member.email)

        chapter.reload()

        # The real behaviour under test is recipient resolution: the "all" filter must
        # collect the emails of the members we just added. Asserting this pins the
        # send-path logic without depending on an SMTP backend or email template.
        recipients = chapter.communication_manager._get_newsletter_recipients("all")
        for email in added_emails:
            self.assertIn(email, recipients, "added member email must be a newsletter recipient")

        # Test newsletter sending end-to-end
        result = chapter.send_chapter_newsletter(
            subject="Test Newsletter",
            content="Test content",
            recipient_filter="all",
        )

        # It must return a structured result dict and must NOT bail out at the
        # "no recipients" guard (we have recipients). Template/SMTP absence in the
        # test env may surface a different error, which is acceptable here.
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertNotEqual(result.get("error"), "No recipients found")

    def test_validate_postal_codes_whitelist(self):
        """Test validate_postal_codes method"""
        chapter = self.test_chapter

        # Add valid postal codes to the text field (not child table)
        chapter.postal_codes = "1234,5678"
        chapter.save()

        # Well-formed codes validate to True.
        self.assertTrue(chapter.validate_postal_codes())

        # A malformed pattern must validate to False (not silently pass). This pins the
        # real branch: validate_postal_codes returns False when the validator rejects.
        # Set in memory only (do NOT save — the document validate() hook would itself
        # reject the invalid pattern before we could exercise the standalone method).
        chapter.postal_codes = "not-a-postal-code!!"
        self.assertFalse(chapter.validate_postal_codes())

    def test_get_board_memberships_whitelist(self):
        """Test get_board_memberships module function"""
        chapter = self.test_chapter
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member)

        # Add board membership via API
        chapter.add_board_member(
            volunteer=volunteer.name,
            role="Secretary",
            from_date=today(),
        )

        # Get board memberships
        memberships = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_board_memberships", member_name=member.name
        )

        # The just-added Secretary membership must be returned for this member/chapter.
        # assertIsInstance(list) passed even when the query returned nothing.
        self.assertIsInstance(memberships, list)
        secretary = [
            m for m in memberships if m.get("chapter_role") == "Secretary" and m.get("parent") == chapter.name
        ]
        self.assertEqual(len(secretary), 1, msg=memberships)

    def test_get_chapter_board_history_whitelist(self):
        """get_chapter_board_history returns active AND inactive board rows.

        The method exists (module function delegating to get_board_members(include_inactive=True)),
        so the old try/except-AttributeError-pass masked any real failure. Assert the
        history includes the deactivated (removed) members, which get_board_members would
        omit if it silently dropped include_inactive.
        """
        chapter = self.test_chapter

        # Add three board members, then remove (deactivate) the first two.
        removed_volunteers = []
        active_volunteer = None
        for i in range(3):
            member = self.create_test_member()
            volunteer = self.create_test_volunteer(member=member)
            chapter.add_board_member(
                volunteer=volunteer.name,
                role="Board Member",
                from_date=add_days(today(), -365 + i * 30),
            )
            if i < 2:
                chapter.remove_board_member(
                    volunteer=volunteer.name,
                    end_date=add_days(today(), -335 + i * 30),
                )
                removed_volunteers.append(volunteer.name)
            else:
                active_volunteer = volunteer.name

        history = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_board_history",
            chapter_name=chapter.name,
        )

        self.assertIsInstance(history, list)
        history_volunteers = {h.get("volunteer") for h in history}
        # All three (active + the two deactivated) must appear in the full history.
        self.assertIn(active_volunteer, history_volunteers)
        for v in removed_volunteers:
            self.assertIn(v, history_volunteers, "inactive board members must be in history")

    def test_get_chapter_stats_whitelist(self):
        """Test get_chapter_stats function - if available"""
        chapter = self.test_chapter

        # Add members and board members via API
        for i in range(5):
            member = self.create_test_member()
            # Add member via API
            chapter.add_member(member.name, introduction=f"Test member {i}")

            if i < 2:  # First 2 as board members
                volunteer = self.create_test_volunteer(member=member)
                chapter.add_board_member(
                    volunteer=volunteer.name,
                    role="Board Member",
                    from_date=today(),
                )

        # get_chapter_stats delegates to Chapter.get_chapter_statistics(); assert the
        # documented summary structure is present (method exists, so no try/except).
        stats = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_stats", chapter_name=chapter.name
        )
        self.assertIsInstance(stats, dict)
        for key in ("board_stats", "member_stats", "communication_stats", "volunteer_integration_stats"):
            self.assertIn(key, stats, msg=stats)

    def test_suggest_chapters_for_member_whitelist(self):
        """suggest_chapters_for_member returns the postal-code-matching chapter.

        The method exists; the old try/except-pass + assertIsInstance(list) passed on an
        empty list. Enable chapter management (the feature-gate the matcher checks) and
        assert the chapter whose postal_codes match the member is actually suggested.
        """
        member = self.create_test_member()
        member.postal_code = "1234"
        member.save()

        from frappe.utils import random_string

        chapter1 = self.create_test_chapter(
            chapter_name=f"Test Chapter 1 {random_string(8)}", postal_codes="1234"
        )
        # get_chapters_by_postal_code only considers published chapters.
        chapter1.published = 1
        chapter1.save()

        original_flag = frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management")
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        try:
            suggestions = frappe.call(
                "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapters_for_member",
                member=member.name,
                postal_code="1234",
            )
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", original_flag)

        self.assertIsInstance(suggestions, list)
        names = [s.get("name") for s in suggestions]
        self.assertIn(chapter1.name, names, msg=f"postal 1234 should suggest {chapter1.name}: {names}")

    def test_assign_member_to_chapter_whitelist(self):
        """assign_member_to_chapter adds the member to the chapter's member list.

        The method exists with signature (member, chapter, note); the old test called it
        with the wrong kwarg names (member_name/chapter_name) inside a try/except that
        swallowed the resulting TypeError, so it asserted nothing.
        """
        chapter = self.test_chapter
        member = self.create_test_member()

        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter",
            member=member.name,
            chapter=chapter.name,
        )

        self.assertTrue(result["success"], msg=result)
        # Member must now be an enabled row on the chapter.
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"parent": chapter.name, "member": member.name, "enabled": 1}),
            "member should be persisted on the chapter after assignment",
        )

    def test_join_leave_chapter_whitelist(self):
        """join_chapter creates a Pending request; leave_chapter disables it.

        Portal join is a request-to-join (pending approval), NOT an immediate active
        membership, so ``added`` is False and the row is status=Pending. leave_chapter
        then disables that row (action=disabled -> removed=True). The old assertIsNotNone
        would have passed on any of these behaviours silently regressing.
        """
        chapter = self.test_chapter
        member = self.create_test_member()

        join_result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.join_chapter",
            member_name=member.name,
            chapter_name=chapter.name,
        )
        self.assertTrue(join_result["success"], msg=join_result)
        # Portal join is a pending request, not an immediate add.
        self.assertFalse(join_result["added"], msg=join_result)
        row = frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter.name, "member": member.name},
            ["status", "enabled"],
            as_dict=True,
        )
        self.assertIsNotNone(row, "join must create a Chapter Member row")
        self.assertEqual(row.status, "Pending", msg=row)

        leave_result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.leave_chapter",
            member_name=member.name,
            chapter_name=chapter.name,
        )
        self.assertTrue(leave_result["success"], msg=leave_result)
        self.assertTrue(leave_result["removed"], msg=leave_result)
        # After leaving, the row is disabled (soft-delete), not enabled.
        self.assertEqual(
            frappe.db.get_value("Chapter Member", {"parent": chapter.name, "member": member.name}, "enabled"),
            0,
            "member row should be disabled after leave",
        )

    def test_board_member_status_field(self):
        """Test the specific board member status field issue from the report"""
        chapter = self.test_chapter
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member)

        # Add board member; row must be created active.
        result = chapter.add_board_member(
            volunteer=volunteer.name,
            role="President",
            from_date=today(),
        )
        self.assertTrue(result["success"], msg=result)
        chapter.reload()
        active = [b for b in chapter.board_members if b.volunteer == volunteer.name and b.is_active]
        self.assertEqual(len(active), 1)

        # Remove flips the is_active status field to 0 (the specific field regression
        # from the report). assertIsNotNone would not have caught a failed status flip.
        result2 = chapter.remove_board_member(
            volunteer=volunteer.name,
            end_date=today(),
        )
        self.assertTrue(result2["success"], msg=result2)
        chapter.reload()
        rows = [b for b in chapter.board_members if b.volunteer == volunteer.name]
        self.assertTrue(all(not b.is_active for b in rows), "President row must be deactivated")

    def test_permission_checks(self):
        """Test permission checks on whitelisted methods"""
        chapter = self.test_chapter
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member)

        # Create a non-admin user
        from frappe.utils import random_string

        test_email = f"test.chapter.{random_string(8)}@example.com"
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": test_email,
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        test_user.insert()
        self.track_doc("User", test_user.name)

        # Test as non-admin user
        with self.as_user(test_email):
            # Should not be able to add board member without permissions
            with self.assertRaises(frappe.PermissionError):
                chapter.add_board_member(
                    volunteer=volunteer.name,
                    role="Board Member",
                    from_date=today(),
                )

    def test_error_handling(self):
        """Removing a non-existent board member raises a specific, message-bearing error.

        Tightened from assertRaises(Exception): a bare Exception would also pass on
        an unrelated AttributeError/KeyError from a refactor that broke the method
        before it ever reached the not-a-board-member guard.
        """
        chapter = self.test_chapter

        with self.assertRaises(frappe.ValidationError) as context:
            chapter.remove_board_member(
                volunteer="non-existent-volunteer",
                end_date=today(),
            )
        self.assertIn("not an active board member", str(context.exception))

    def test_data_integrity(self):
        """The board API allows one volunteer to hold multiple distinct (non-unique) roles.

        Replaces a try/except that passed whether the second add raised OR not (so it
        asserted nothing). Pin the real contract: adding a second, different role
        leaves the volunteer with two active board rows.
        """
        chapter = self.test_chapter
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member)

        chapter.add_board_member(volunteer=volunteer.name, role="Treasurer", from_date=today())
        chapter.add_board_member(volunteer=volunteer.name, role="Secretary", from_date=today())

        chapter.reload()
        active_roles = sorted(
            b.chapter_role for b in chapter.board_members if b.volunteer == volunteer.name and b.is_active
        )
        self.assertEqual(active_roles, ["Secretary", "Treasurer"])
