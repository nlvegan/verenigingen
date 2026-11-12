"""
#2196 / #2218: ``BaseManager.create_comment`` wrote the chapter audit Comment with the ACTING
user's ``Comment:create`` check, which only System Manager / Website Manager pass. For anyone
else the audit record was silently dropped (a logger line CI never shows), so the actor an
audit record is about could skip it.

Callers here are a REAL least-privileged board member (``create_test_board_member``, Admin
seat, Verenigingen Chapter Board Member profile), never Administrator.

PROBE SHORTCUT: the Pending Chapter Member row and the Active target row are written as
Administrator (``chapter_doc.append`` / ``add_member_to_test_chapter``) instead of through the
join flow; the actions under test (approve, reject, update, add, remove, bulk add) run as the
board user through the real manager methods.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterAuditComment2196(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    def _audit_member_2196(self, tag):
        uid = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name=tag,
            last_name=f"Audit2196{uid}",
            email=f"audit.2196.{uid}0@test.invalid",
            birth_date="1990-01-01",
        )
        member.db_set("status", "Active")
        return member

    def _pending(self, member):
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append("members", {"member": member.name, "enabled": 1, "status": "Pending"})
        chapter_doc.save()

    def _comments(self):
        return frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Chapter", "reference_name": self.chapter.name},
            pluck="content",
        )

    def _manager(self):
        return frappe.get_doc("Chapter", self.chapter.name).member_manager

    def _as_board(self, fn):
        before = set(self._comments())
        with self.as_user(self.board.user):
            self.assertNotIn("System Manager", frappe.get_roles())
            result = fn()
        new = [c for c in self._comments() if c not in before]
        return result, new

    def test_caller_cannot_write_comment_directly(self):
        """Control: the board user really lacks Comment create, so the elevation is what matters."""
        with self.as_user(self.board.user):
            self.assertFalse(frappe.has_permission("Comment", "create"))

    def _assert_owned_by_board(self, fragment):
        row = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Chapter",
                "reference_name": self.chapter.name,
                "content": ["like", f"%{fragment}%"],
            },
            fields=["owner", "comment_email"],
        )
        self.assertEqual(len(row), 1, row)
        self.assertEqual(row[0].owner, self.board.user)
        self.assertEqual(row[0].comment_email, self.board.user)

    def test_create_comment_as_board_member(self):
        _, new = self._as_board(lambda: self._manager().create_comment("Info", "direct audit 2196"))
        self.assertEqual(new, ["direct audit 2196"])
        self._assert_owned_by_board("direct audit 2196")

    def test_non_chapter_reference_is_not_elevated(self):
        """Control: another document, or a non-Info type, keeps the normal permission path."""
        other = self._audit_member_2196("Other")
        mgr = self._manager()
        # Half-pinned narrowing: each of the doctype and name checks must be exercised with the OTHER
        # one matching, so replacing either with `and True` is caught. The secure insert
        # link-validates the Dynamic Link, so "Member" + this chapter's name is refused for
        # every code path (no such Member) and cannot discriminate. A Role whose name IS this
        # chapter's name can (Region slugs its name, Role keeps it verbatim): it exists, so only
        # the doctype check keeps the write unelevated.
        another_chapter = self.create_test_chapter()
        self.assertNotEqual(another_chapter.name, self.chapter.name)
        same_name_role = frappe.get_doc({"doctype": "Role", "role_name": self.chapter.name}).insert()
        self.addCleanup(frappe.delete_doc, "Role", same_name_role.name, force=True)
        self.assertEqual(same_name_role.name, self.chapter.name)
        for kwargs in (
            {"reference_doctype": "Member", "reference_name": other.name},
            {"reference_doctype": "Chapter", "reference_name": another_chapter.name},
            {"reference_doctype": "Role", "reference_name": self.chapter.name},
            {"comment_type": "Comment"},
        ):
            marker = f"not elevated {frappe.generate_hash(length=6)}"
            ctype = kwargs.pop("comment_type", "Info")
            with self.as_user(self.board.user):
                mgr.create_comment(ctype, marker, **kwargs)
            self.assertFalse(frappe.db.exists("Comment", {"content": marker}), kwargs)

    def test_approve_writes_audit_comment(self):
        member = self._audit_member_2196("Approve")
        self._pending(member)
        result, new = self._as_board(lambda: self._manager().approve_member_request(member.name))
        self.assertTrue(result.get("success"), result)
        self.assertTrue(any("Approved membership request" in c for c in new), new)
        self._assert_owned_by_board("Approved membership request")

    def test_reject_writes_audit_comment(self):
        member = self._audit_member_2196("Reject")
        self._pending(member)
        result, new = self._as_board(
            lambda: self._manager().reject_member_request(member.name, reason="r2196")
        )
        self.assertTrue(result.get("success"), result)
        self.assertTrue(any("Rejected membership request" in c for c in new), new)

    def test_update_writes_audit_comment(self):
        member = self._audit_member_2196("Update")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        result, new = self._as_board(
            lambda: self._manager().update_member_info(member.name, enabled=False)
        )
        self.assertTrue(result.get("success"), result)
        self.assertTrue(any("Updated member" in c for c in new), new)

    def test_add_member_writes_audit_comment(self):
        member = self._audit_member_2196("Add")
        result, new = self._as_board(lambda: self._manager().add_member(member.name, notify=False))
        self.assertTrue(result.get("success"), result)
        self.assertTrue(any("Added member" in c for c in new), new)

    def test_remove_member_writes_audit_comment(self):
        member = self._audit_member_2196("Remove")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        result, new = self._as_board(
            lambda: self._manager().remove_member(member.name, "left 2196", notify=False)
        )
        self.assertTrue(result.get("success"), result)
        self.assertEqual(len(new), 1, new)

    def test_add_board_member_writes_audit_comment(self):
        """board_manager site, as the board user (PROBE SHORTCUT: the volunteer is created as Administrator)."""
        member = self._audit_member_2196("Seat")
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = frappe.db.get_value("Chapter Role", self.board.chapter_role, "name")
        result, new = self._as_board(
            lambda: frappe.get_doc("Chapter", self.chapter.name).board_manager.add_board_member(
                volunteer.name, role, notify=False
            )
        )
        self.assertTrue(result.get("success"), result)
        self.assertTrue(any("Added" in c and "starting" in c for c in new), new)

    def test_refused_comment_leaves_error_log_and_does_not_raise(self):
        """A refused (non-elevated) write is recorded in Error Log and the caller is not broken."""
        other = self._audit_member_2196("Refused")
        before = frappe.db.count("Error Log", {"method": ["like", "Secure Operation Failed%"]})
        with self.as_user(self.board.user):
            self._manager().create_comment("Info", "refused 2196", "Member", other.name)
        after = frappe.db.count("Error Log", {"method": ["like", "Secure Operation Failed%"]})
        self.assertGreater(after, before)

    def test_member_own_leave_writes_audit_comment(self):
        """Real flow for the member-as-subject case (#2196): a member leaves THEIR OWN chapter
        through the whitelisted endpoint. Caller is a real user linked by Member.user with the
        least-privileged profile that clears @high_security_api (a plain Verenigingen Member is
        refused by that tier gate before anything under test); not Chapter:write, not Comment:create.
        """
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
        from verenigingen.verenigingen.doctype.chapter.chapter import leave_chapter

        uid = frappe.generate_hash(length=8)
        email = f"lv2196-{uid}@example.com"
        member = self._audit_member_2196("Leaver")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email)
        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")
        self.add_member_to_test_chapter(member.name, self.chapter.name)

        with self.as_user(email):
            self.assertFalse(frappe.has_permission("Comment", "create"))
        before = set(self._comments())
        with self.as_user(email):
            response = leave_chapter(member.name, self.chapter.name, "moving 2196")
        self.assertEqual(response, {"success": True, "removed": True})
        new = [c for c in self._comments() if c not in before]
        self.assertEqual(len(new), 1, new)
        row = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Chapter", "reference_name": self.chapter.name, "content": new[0]},
            fields=["owner", "comment_type"],
        )
        self.assertEqual((row[0].owner, row[0].comment_type), (email, "Info"))
