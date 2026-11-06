"""#2069: ChapterMembershipManager.join_chapter / leave_chapter authorise the caller by Member.user ONLY.

#1853 (maintainer ruling 2026-11-01) removed the Member.email fallback from the self-service
join paths; the manager's `user_email == member.email` check was missed. A logged-in user whose
email equals a Member's email, with Member.user unset or pointing elsewhere, must not join or
leave on that Member's behalf.

Fixture note: the unlinked state is built by clearing Member.user with db_set (the state of a
legacy record whose email matches a User); that is the state under test, not a stand-in for a
flow. Callers are plain "Verenigingen Member" users, never Administrator, except the control.

No test drives `Chapter.leave_chapter` (the whitelisted endpoint): measured on test_site_7, it
answers success False ("Not allowed via controller permission check") even for the LINKED member
with the Chapter Board Member profile, on develop code too, so an email-only caller's refusal there
proves nothing. The manager-level leave tests carry the check.
"""

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter

REFUSAL = "You don't have permission to perform this action"


class TestChapterMembershipManagerUserLink(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2069 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2069"
        )
        self.linked = self._user_and_member_2069(linked=True)
        self.unlinked = self._user_and_member_2069(linked=False)

    def _user_and_member_2069(self, linked):
        email = f"mm2069-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Mm", last_name="Link" if linked else "Email", email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email if linked else None)
        # Least-privileged caller that clears @high_security_api on the whitelisted endpoints (#1862);
        # without a profile the tier gate refuses BEFORE the check under test runs.
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")
        return frappe._dict(member=member, user=email)

    def _chapter_member_row_2069(self, member):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter.name, "member": member.name},
            ["status", "enabled"],
            as_dict=True,
        )

    def test_join_refuses_user_matching_only_by_email(self):
        result = ChapterMembershipManager.join_chapter(
            member_id=self.unlinked.member.name,
            chapter_name=self.chapter.name,
            introduction="hi",
            user_email=self.unlinked.user,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], REFUSAL)
        self.assertIsNone(self._chapter_member_row_2069(self.unlinked.member))

    def test_join_refuses_member_user_pointing_at_someone_else(self):
        # Member.user points at a different user while the email matches the caller.
        other_user = f"other2069-{frappe.generate_hash()[:8]}@example.com"
        self.create_test_user_with_roles(email=other_user, roles=["Verenigingen Member"])
        self.unlinked.member.db_set("user", other_user)
        result = ChapterMembershipManager.join_chapter(
            member_id=self.unlinked.member.name,
            chapter_name=self.chapter.name,
            introduction="hi",
            user_email=self.unlinked.user,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], REFUSAL)
        self.assertIsNone(self._chapter_member_row_2069(self.unlinked.member))

    def test_join_via_whitelisted_endpoint_refuses_email_only_user(self):
        with self.as_user(self.unlinked.user):
            response = join_chapter(
                member_name=self.unlinked.member.name,
                chapter_name=self.chapter.name,
                introduction="hi",
            )
        self.assertEqual(response, {"success": False, "added": False})
        self.assertIsNone(self._chapter_member_row_2069(self.unlinked.member))

    def test_linked_member_can_still_join(self):
        """Control: the linked user's request writes its Pending row."""
        result = ChapterMembershipManager.join_chapter(
            member_id=self.linked.member.name,
            chapter_name=self.chapter.name,
            introduction="hi",
            user_email=self.linked.user,
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(self._chapter_member_row_2069(self.linked.member).status, "Pending")

    def test_administrator_is_still_exempt(self):
        result = ChapterMembershipManager.join_chapter(
            member_id=self.unlinked.member.name,
            chapter_name=self.chapter.name,
            introduction="hi",
            user_email="Administrator",
        )
        self.assertTrue(result["success"], result)

    def test_leave_refuses_user_matching_only_by_email(self):
        self.add_member_to_test_chapter(self.unlinked.member.name, self.chapter.name)
        result = ChapterMembershipManager.leave_chapter(
            member_id=self.unlinked.member.name,
            chapter_name=self.chapter.name,
            leave_reason="x",
            user_email=self.unlinked.user,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], REFUSAL)
        row = self._chapter_member_row_2069(self.unlinked.member)
        self.assertEqual((row.status, row.enabled), ("Active", 1))

    def test_linked_member_can_still_leave(self):
        """Control: a row exists for the wrong behaviour to find, and the linked user leaves it."""
        self.add_member_to_test_chapter(self.linked.member.name, self.chapter.name)
        result = ChapterMembershipManager.leave_chapter(
            member_id=self.linked.member.name,
            chapter_name=self.chapter.name,
            leave_reason="x",
            user_email=self.linked.user,
        )
        self.assertTrue(result["success"], result)
        row = self._chapter_member_row_2069(self.linked.member)
        self.assertEqual(row.enabled, 0)
