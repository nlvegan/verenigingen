"""
#2492 (ruling #2218): ``quick_approve_join_request`` wrote the approving board member's audit
Comment on the MEMBER through ``secure_document_operation`` with the ACTING user's
``Comment:create`` check, which a board member lacks, so the record was dropped (the approval
itself succeeded). The write is now a narrow ``system_operation`` for that one insert.

The caller is a REAL least-privileged board member (``create_test_board_member``, Admin seat),
never Administrator.

PROBE SHORTCUT: the Pending Chapter Member row is appended as Administrator instead of through
``join_chapter``; the approval itself runs as the board user through the whitelisted endpoint.
"""

import frappe

from verenigingen.api.chapter_dashboard_api import quick_approve_join_request
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

CONTENT_MARK = "Member approved via chapter dashboard by"


class TestDashboardJoinAuditComment2492(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Chapter Head"
        )
        uid = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="Dash",
            last_name=f"Audit2492{uid}",
            email=f"audit.2492.{uid}@test.invalid",
            birth_date="1990-01-01",
        )
        self.member.db_set("status", "Active")
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append("members", {"member": self.member.name, "enabled": 1, "status": "Pending"})
        chapter_doc.save()

    def _member_comments(self, member_name=None):
        return frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Member",
                "reference_name": member_name or self.member.name,
                "content": ["like", f"{CONTENT_MARK}%"],
            },
            fields=["owner", "comment_email", "comment_type", "content"],
        )

    def _approve(self):
        with self.as_user(self.board.user):
            self.assertNotIn("System Manager", frappe.get_roles())
            self.assertFalse(frappe.has_permission("Comment", "create"))
            return quick_approve_join_request(self.member.name, self.chapter.name)

    def test_approval_writes_audit_comment_on_member_owned_by_approver(self):
        result = self._approve()
        self.assertTrue(result.get("success"), result)
        self.assertEqual(
            frappe.db.get_value(
                "Chapter Member", {"parent": self.chapter.name, "member": self.member.name}, "status"
            ),
            "Active",
        )
        rows = self._member_comments()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0].comment_type, "Info")
        self.assertEqual(rows[0].owner, self.board.user)
        self.assertEqual(rows[0].comment_email, self.board.user)
        self.assertIn(frappe.utils.get_fullname(self.board.user), rows[0].content)

    def _refused_writes_no_comment(self, board):
        self.expectErrorLog()
        with self.as_user(board.user):
            self.assertNotIn("System Manager", frappe.get_roles())
            try:
                result = quick_approve_join_request(self.member.name, self.chapter.name)
            except frappe.PermissionError:
                result = {"success": False}
            self.assertFalse(result.get("success"), result)
        self.assertEqual(self._member_comments(), [])
        self.assertEqual(
            frappe.db.get_value(
                "Chapter Member", {"parent": self.chapter.name, "member": self.member.name}, "status"
            ),
            "Pending",
        )

    def test_board_member_of_another_chapter_is_refused_and_writes_no_comment(self):
        """Gate-order control: the elevated insert must come AFTER the access gates, so a caller who
        is refused leaves no audit Comment (an early elevated write would pass every approval test)."""
        other_chapter = self.create_test_chapter()
        outsider = self.create_test_board_member(
            other_chapter.name, permissions_level="Admin", role_name="Chapter Head"
        )
        self._refused_writes_no_comment(outsider)

    def test_board_member_without_approve_permission_is_refused_and_writes_no_comment(self):
        """Same control for a seat on THIS chapter whose role lacks can_approve_members."""
        non_approver = self.create_test_board_member(
            self.chapter.name, permissions_level="Basic", role_name="Test NonApprover 2492"
        )
        self._refused_writes_no_comment(non_approver)

    def test_approver_name_markup_is_escaped_in_the_elevated_comment(self):
        """The elevated insert must not let a mention span in the approver's name through."""
        evil = '<span class="mention" data-id="Administrator">x</span>'
        frappe.db.set_value("User", self.board.user, "first_name", evil)
        frappe.local.fullnames = {}  # get_fullname memoises per request
        self.addCleanup(lambda: setattr(frappe.local, "fullnames", {}))
        self.assertIn("mention", frappe.utils.get_fullname(self.board.user))
        result = self._approve()
        self.assertTrue(result.get("success"), result)
        rows = self._member_comments()
        self.assertEqual(len(rows), 1, rows)
        # The markup is stored as inert text: no tag survives for notify_mentions to parse.
        self.assertNotIn("<span", rows[0].content)
        self.assertIn("&lt;span", rows[0].content)

    def test_comment_permissions_are_not_widened(self):
        """Control: after the approval the board user still cannot create a Comment directly, and
        the endpoint's only elevated write is that one audit insert (the Member is untouched)."""
        modified_before = frappe.db.get_value("Member", self.member.name, "modified")
        self._approve()
        with self.as_user(self.board.user):
            self.assertFalse(frappe.has_permission("Comment", "create"))
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(
                    {
                        "doctype": "Comment",
                        "comment_type": "Info",
                        "reference_doctype": "Member",
                        "reference_name": self.member.name,
                        "content": "direct write 2492",
                    }
                ).insert()
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "modified"), modified_before)
        self.assertFalse(frappe.db.exists("Comment", {"content": "direct write 2492"}))
