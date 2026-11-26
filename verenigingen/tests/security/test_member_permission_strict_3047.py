"""#3047: Member.has_permission deliberately does NOT honour doc.flags.ignore_permissions.

Maintainer ruling (2026-11-24): keep refusing. The base Document.has_permission returns True when
the flag is set; the Member override must not. Each flow that needs elevation is fixed explicitly.
This pins the policy so a well-meaning "make it match the base class" change goes red.

Callers are real users: a plain "Verenigingen Member" who does not own the record (no Member rule
that covers it), Guest, and, as the control, a Verenigingen Staff user.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberPermissionStrict3047(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Strict",
            last_name="Perm",
            email=f"strict3047-{frappe.generate_hash(length=8)}0@example.com",
            birth_date="1990-01-01",
        )
        suffix = frappe.generate_hash(length=8)
        self.outsider = f"outsider3047-{suffix}@example.com"
        self.staff = f"staff3047-{suffix}@example.com"
        self.create_test_user_with_roles(email=self.outsider, roles=["Verenigingen Member"])
        self.create_test_user_with_roles(email=self.staff, roles=["Verenigingen Staff"])

    def _build_flagged_member_doc(self):
        doc = frappe.get_doc("Member", self.member.name)
        doc.flags.ignore_permissions = True
        return doc

    def test_flag_does_not_elevate_a_user_without_a_member_rule(self):
        for user in (self.outsider, "Guest"):
            with self.as_user(user):
                doc = self._build_flagged_member_doc()
                self.assertFalse(doc.has_permission("read"), f"{user}: flag must not grant read")
                with self.assertRaises(frappe.PermissionError):
                    doc.check_permission("write")

    def test_insert_with_ignore_permissions_is_still_refused(self):
        with self.as_user(self.outsider):
            doc = frappe.new_doc("Member")
            doc.first_name = "Ins"
            doc.last_name = "Ert"
            doc.email = f"ins3047-{frappe.generate_hash(length=6)}0@example.com"
            doc.birth_date = "1990-01-01"
            with self.assertRaises(frappe.PermissionError):
                doc.insert(ignore_permissions=True)

    def test_control_a_user_with_access_is_allowed(self):
        with self.as_user(self.staff):
            doc = frappe.get_doc("Member", self.member.name)  # NO flag set
            self.assertTrue(doc.has_permission("read"))
            doc.check_permission("read")

    def test_control_unflagged_outsider_is_also_refused(self):
        with self.as_user(self.outsider):
            doc = frappe.get_doc("Member", self.member.name)
            self.assertFalse(doc.has_permission("read"))
