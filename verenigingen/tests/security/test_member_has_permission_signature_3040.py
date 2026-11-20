# -*- coding: utf-8 -*-
"""
#3040: ``Member.has_permission`` must accept the ``debug`` keyword that Frappe's
``File.has_permission`` passes (``ref_doc.has_permission("read", debug=debug, user=user)``).
Before the fix a non-admin, non-owner read of a private File attached to a Member raised
``TypeError`` (HTTP 500) instead of returning a bool.

Three real callers read the same private File (owner Administrator) attached to a Member:
- staff   (role Verenigingen Staff)        -> allowed (existing rule)
- owner   (the Member's own linked user)   -> allowed
- other   (another member's linked user)   -> refused (False / 403), never a 500

PROBE SHORTCUTS: the staff user carries the Staff ROLE directly rather than via a staff
Team (the Member rule only reads roles); ``Member.user`` is linked with ``db.set_value``.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberHasPermissionSignature3040(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        tag = frappe.generate_hash(length=6)
        self.owner_user = self.create_test_user_with_roles(
            email=f"sig3040-owner-{tag}@example.com", roles=["Verenigingen Member"]
        ).name
        self.other_user = self.create_test_user_with_roles(
            email=f"sig3040-other-{tag}@example.com", roles=["Verenigingen Member"]
        ).name
        self.staff_user = self.create_test_user_with_roles(
            email=f"sig3040-staff-{tag}@example.com", roles=["Verenigingen Staff"]
        ).name
        self.member = self.create_test_member(email=f"sig3040-m-{tag}@example.com")
        other_member = self.create_test_member(email=f"sig3040-o-{tag}@example.com")
        frappe.db.set_value("Member", self.member.name, "user", self.owner_user, update_modified=False)
        frappe.db.set_value("Member", other_member.name, "user", self.other_user, update_modified=False)
        for user in (self.owner_user, self.other_user, self.staff_user):
            frappe.clear_cache(user=user)
        self.file_name = self._private_file_on(self.member.name, tag)

    def _private_file_on(self, member_name, tag):
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"sig3040-{tag}.txt",
                "content": b"secret",
                "is_private": 1,
                "attached_to_doctype": "Member",
                "attached_to_name": member_name,
            }
        ).insert()  # tests run as Administrator
        self.track_doc("File", file_doc.name)
        self.assertEqual(file_doc.owner, "Administrator")
        return file_doc.name

    def _file_read(self, user):
        prior_user = frappe.session.user
        frappe.set_user(user)
        try:
            return frappe.get_doc("File", self.file_name).has_permission("read")
        finally:
            frappe.set_user(prior_user)

    def test_staff_reads_member_attached_private_file(self):
        self.assertTrue(self._file_read(self.staff_user))

    def test_member_reads_own_attached_private_file(self):
        self.assertTrue(self._file_read(self.owner_user))

    def test_member_refused_on_another_members_attached_private_file(self):
        self.assertFalse(self._file_read(self.other_user))

    def test_member_has_permission_accepts_debug_and_user_keywords(self):
        member = frappe.get_doc("Member", self.member.name)
        self.assertTrue(member.has_permission("read", debug=False, user=self.staff_user))
        self.assertFalse(member.has_permission("read", debug=True, user=self.other_user))
        self.assertTrue(member.has_permission(permtype="read", user=self.owner_user))

    def test_http_download_of_private_file(self):
        """Real WSGI login + private-file download: 200 owner/staff, 403 other member (never 500)."""
        import frappe.app
        from frappe.utils.password import update_password
        from werkzeug.test import Client
        from werkzeug.wrappers import Response

        password = f"Sig3040-{frappe.generate_hash(length=8)}!x"
        for user in (self.owner_user, self.staff_user, self.other_user):
            update_password(user, password)
        frappe.db.commit()  # Mock justified: the WSGI request uses its own connection and must see the fixtures
        url = frappe.db.get_value("File", self.file_name, "file_url")
        site_host = {"Host": frappe.local.site}
        statuses = {}
        for label, user in (("owner", self.owner_user), ("staff", self.staff_user), ("other", self.other_user)):
            client = Client(frappe.app.application, Response)
            login = client.post(
                "/api/method/login", data={"usr": user, "pwd": password}, headers=site_host
            )
            self.assertEqual(login.status_code, 200, login.get_data(as_text=True)[:300])
            statuses[label] = client.get(url, headers=site_host).status_code
        self.assertEqual(statuses, {"owner": 200, "staff": 200, "other": 403})
