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

import json
import os
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# The WSGI app runs on its own connection, so its fixtures must be committed. That is done in
# a SUBPROCESS that owns its connection and removes everything in `finally`, never in the test
# process (a bare commit there would grow the order-dependence baseline).
_PROBE = r"""
import json, sys, uuid
import frappe

SITE = sys.argv[1]
TAG = uuid.uuid4().hex[:6]
PWD = "Pr0be-" + uuid.uuid4().hex
frappe.init(site=SITE)
frappe.connect()
made = []
out = {}
try:
    frappe.set_user("Administrator")

    def mk_user(label, role):
        email = "p3040-%s-%s@example.com" % (label, TAG)
        u = frappe.new_doc("User")
        u.email, u.first_name, u.send_welcome_email = email, "P3040" + label, 0
        u.append("roles", {"role": role})
        u.new_password = PWD
        u.insert(ignore_permissions=True)
        made.append(("User", email))
        return email

    def mk_member(label, user):
        m = frappe.get_doc({"doctype": "Member", "first_name": "P3040" + label, "last_name": "Probe",
            "email": "m-%s-%s@example.com" % (label, TAG), "birth_date": "1990-01-01",
            "payment_method": "Bank Transfer"}).insert(ignore_permissions=True)
        made.append(("Member", m.name))
        if user:
            frappe.db.set_value("Member", m.name, "user", user, update_modified=False)
        return m.name

    owner = mk_user("owner", "Verenigingen Member")
    other = mk_user("other", "Verenigingen Member")
    staff = mk_user("staff", "Verenigingen Staff")
    member = mk_member("a", owner)
    mk_member("b", other)
    f = frappe.get_doc({"doctype": "File", "file_name": "p3040-%s.txt" % TAG, "content": b"secret",
        "is_private": 1, "attached_to_doctype": "Member", "attached_to_name": member}).insert()
    made.append(("File", f.name))
    url = f.file_url
    frappe.db.commit()
    frappe.destroy()

    import frappe.app
    from werkzeug.test import Client
    H = {"X-Frappe-Site-Name": SITE}
    for label, user in (("owner", owner), ("staff", staff), ("other", other)):
        c = Client(frappe.app.application)
        login = c.post("/api/method/login", data={"usr": user, "pwd": PWD}, headers=H)
        out[label] = [login.status_code, c.get(url, headers=H).status_code]
finally:
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")
    for dt, name in reversed(made):
        try:
            frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
        except Exception as e:
            out.setdefault("cleanup_errors", []).append("%s %s: %s" % (dt, name, e))
    frappe.db.commit()
    frappe.destroy()
print("RESULT" + json.dumps(out))
"""


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

    def test_permtype_reaches_has_member_permission(self):
        """The permission type is forwarded, not replaced by 'read'. A service account (Webhook
        User role) defers to its Member DocPerm, which grants read but not delete, so the answer
        depends on the type; it must equal the module rule's answer for each type."""
        from verenigingen.permissions import has_member_permission

        webhook_user = self.create_test_user_with_roles(
            email=f"sig3040-hook-{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Webhook User"],
        ).name
        frappe.clear_cache(user=webhook_user)
        member = frappe.get_doc("Member", self.member.name)
        expected = {
            ptype: bool(has_member_permission(member, webhook_user, ptype))
            for ptype in ("read", "write", "delete")
        }
        # control: the real rule must distinguish the types, else forwarding is untestable
        self.assertEqual(len(set(expected.values())), 2, expected)
        actual = {
            ptype: member.has_permission(ptype, user=webhook_user) for ptype in ("read", "write", "delete")
        }
        self.assertEqual(actual, expected)


class TestMemberAttachedFileDownload3040(EnhancedTestCase):
    """No setUp fixtures on purpose: uncommitted rows here would hold naming-series locks the
    probe subprocess (its own connection) then waits on."""

    def test_http_download_of_private_file(self):
        """Real WSGI login + private-file download (subprocess): 200 owner/staff, 403 other, never 500."""
        result = subprocess.run(
            [sys.executable, "-c", _PROBE, frappe.local.site],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        lines = [x for x in result.stdout.splitlines() if x.startswith("RESULT")]
        self.assertTrue(lines, f"probe printed no RESULT: {result.stdout[-500:]} {result.stderr[-1500:]}")
        out = json.loads(lines[0][len("RESULT") :])
        self.assertNotIn("cleanup_errors", out)
        self.assertEqual(out, {"owner": [200, 200], "staff": [200, 200], "other": [200, 403]})
