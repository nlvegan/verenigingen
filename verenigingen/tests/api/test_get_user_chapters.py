"""
Integration tests for verenigingen/api/get_user_chapters.py

Covers get_user_chapter_data(), a @public_api(PUBLIC) +
@frappe.whitelist(allow_guest=True) endpoint returning an OperationResult.

IMPORTANT — return shape: the @public_api decorator serialises the returned
OperationResult into a NESTED dict. Calling the function directly (as these
tests do) yields on success:

    {"success": True, "timestamp": ..., "data": {...}, "meta": {...}}

with the real payload under "data" (keys: user, member, chapters,
user_chapters). These tests assert against that observed nested shape.

The endpoint is user-scoped: it resolves the member for frappe.session.user and
reports per-chapter membership status, so tests exercise it as guest, as a
member-user with a chapter, as a member-user without chapters, and as a
user with no member record.
"""

import frappe

from verenigingen.api.get_user_chapters import get_user_chapter_data
from verenigingen.tests.utils.base import VereningingenTestCase


class TestGetUserChapterData(VereningingenTestCase):
    """Real integration tests for the user chapter data endpoint."""

    def _make_test_user(self, email):
        """Create (and track) a real enabled User to act as in as_user()."""
        if frappe.db.exists("User", email):
            return email
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Chapter",
                "last_name": "Tester",
                "send_welcome_email": 0,
                "enabled": 1,
                "user_type": "Website User",
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return email

    def _persist_member_user_link(self, member_name, email):
        """Link a Member to a User via a direct column write (no doc hooks)."""
        frappe.db.set_value("Member", member_name, "user", email, update_modified=False)

    def _add_member_to_chapter(self, chapter, member_name, status="Active", enabled=1):
        """Append a Chapter Member row through the parent Chapter document."""
        chapter.append(
            "members",
            {"member": member_name, "status": status, "enabled": enabled},
        )
        chapter.save()

    def _get_payload(self):
        """Call endpoint, assert nested success envelope, return data dict."""
        result = get_user_chapter_data()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"Endpoint failed: {result}")
        self.assertIn("data", result)
        return result["data"]

    def test_guest_user_gets_empty_membership(self):
        """Guest sessions get an empty, member-less payload."""
        with self.as_user("Guest"):
            data = self._get_payload()
        self.assertEqual(data["user"], "Guest")
        self.assertIsNone(data["member"])
        self.assertEqual(data["chapters"], [])
        self.assertEqual(data["user_chapters"], [])

    def test_member_user_with_chapter_membership(self):
        """A member who belongs to a published chapter has it flagged as a member."""
        email = "chapter_member_a@example.test"
        self._make_test_user(email)
        member = self.create_test_member(
            first_name="Alice", last_name="Member", email=email
        )
        self._persist_member_user_link(member.name, email)

        chapter = self.create_test_chapter(published=1)
        self._add_member_to_chapter(chapter, member.name, status="Active")

        with self.as_user(email):
            data = self._get_payload()

        self.assertEqual(data["member"], member.name)
        self.assertIn(chapter.name, data["user_chapters"])

        # The chapter row itself must be flagged is_member and not is_pending
        row = next(c for c in data["chapters"] if c["name"] == chapter.name)
        self.assertEqual(row["is_member"], 1)
        self.assertEqual(row["is_pending"], 0)

    def test_member_user_without_any_chapter(self):
        """A member in no chapter still sees published chapters, but as non-member."""
        email = "chapter_member_b@example.test"
        self._make_test_user(email)
        member = self.create_test_member(
            first_name="Bob", last_name="Member", email=email
        )
        self._persist_member_user_link(member.name, email)

        # A published chapter exists that the member is NOT part of
        other_chapter = self.create_test_chapter(published=1)

        with self.as_user(email):
            data = self._get_payload()

        self.assertEqual(data["member"], member.name)
        self.assertEqual(data["user_chapters"], [])
        # The published chapter is listed but flagged as not-a-member
        row = next(
            (c for c in data["chapters"] if c["name"] == other_chapter.name), None
        )
        self.assertIsNotNone(row, "Published chapter should be listed")
        self.assertEqual(row["is_member"], 0)

    def test_pending_membership_is_not_active_member(self):
        """A pending chapter membership is flagged is_pending, not is_member."""
        email = "chapter_member_c@example.test"
        self._make_test_user(email)
        member = self.create_test_member(
            first_name="Carol", last_name="Member", email=email
        )
        self._persist_member_user_link(member.name, email)

        chapter = self.create_test_chapter(published=1)
        self._add_member_to_chapter(chapter, member.name, status="Pending")

        with self.as_user(email):
            data = self._get_payload()

        # Pending membership must NOT count as an active chapter membership
        self.assertNotIn(chapter.name, data["user_chapters"])
        row = next(c for c in data["chapters"] if c["name"] == chapter.name)
        self.assertEqual(row["is_member"], 0)
        self.assertEqual(row["is_pending"], 1)

    def test_disabled_membership_not_counted(self):
        """A disabled Chapter Member row does not count as an active membership."""
        email = "chapter_member_d@example.test"
        self._make_test_user(email)
        member = self.create_test_member(
            first_name="Dave", last_name="Member", email=email
        )
        self._persist_member_user_link(member.name, email)

        chapter = self.create_test_chapter(published=1)
        self._add_member_to_chapter(
            chapter, member.name, status="Active", enabled=0
        )

        with self.as_user(email):
            data = self._get_payload()

        self.assertNotIn(chapter.name, data["user_chapters"])
        row = next(c for c in data["chapters"] if c["name"] == chapter.name)
        self.assertEqual(row["is_member"], 0)

    def test_user_without_member_record(self):
        """A user with no Member record gets chapters listed but member=None."""
        email = "no_member_user@example.test"
        self._make_test_user(email)

        # Ensure at least one published chapter exists in the system
        chapter = self.create_test_chapter(published=1)

        with self.as_user(email):
            data = self._get_payload()

        self.assertIsNone(data["member"])
        self.assertEqual(data["user_chapters"], [])
        # Published chapters are still listed, all flagged non-member
        names = [c["name"] for c in data["chapters"]]
        self.assertIn(chapter.name, names)
        for c in data["chapters"]:
            self.assertEqual(c["is_member"], 0)
            self.assertEqual(c["is_pending"], 0)

    def test_unpublished_chapter_not_listed(self):
        """Unpublished chapters are excluded from the listing entirely."""
        email = "chapter_member_e@example.test"
        self._make_test_user(email)
        member = self.create_test_member(
            first_name="Eve", last_name="Member", email=email
        )
        self._persist_member_user_link(member.name, email)

        # Member is in an UNPUBLISHED chapter
        chapter = self.create_test_chapter(published=0)
        self._add_member_to_chapter(chapter, member.name, status="Active")

        with self.as_user(email):
            data = self._get_payload()

        names = [c["name"] for c in data["chapters"]]
        self.assertNotIn(chapter.name, names)
        self.assertNotIn(chapter.name, data["user_chapters"])
