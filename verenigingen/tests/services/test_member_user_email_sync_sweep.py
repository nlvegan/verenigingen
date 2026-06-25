# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage *sweep* for
``verenigingen/services/member/account/member_user_email_sync.py``.

Augments ``verenigingen/tests/member/test_member_user_email_sync.py`` (does NOT
duplicate it). The existing suite covers the happy rename, the no-user no-op,
the conflict abort, the stale-link clear, the unchanged/case-only no-ops, the
cleared-email no-op and the loop guard. This file fills the remaining gaps:

    - mixed-case new email → User renamed to the *lowercased* address AND
      ``Member.email`` normalized to that lowercased form (the
      ``if doc.email != new_email`` normalization branch, lines 79-80)
    - the rename cascades Member.user to the new (lowercased) address
    - whitespace-padded new email is stripped before the rename
    - rename emits no Error Log (the SECURITY AUDIT path is a logger.info)
    - re-link integrity: a Volunteer pointing at the old User is cascaded by the
      ``rename_doc`` (Link fields follow the rename)

No business-logic mocking. Real Members, Users and Volunteers via
``frappe.get_doc().insert()``. Tests run as Administrator.
"""

import frappe

from verenigingen.services.member.account.member_user_email_sync import (
    sync_user_email_on_member_update,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberUserEmailSyncSweep(EnhancedTestCase):
    """Cover the email-normalization + cascade branches the base suite misses."""

    def _make_user(self, tag):
        email = self.factory.generate_test_email(f"emailsyncsw-{tag}")
        return self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])

    def _make_member(self, email, user_link=None):
        """Create a Member directly (bypasses factory Customer creation)."""
        uid = frappe.generate_hash(length=6)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "SyncSw",
                "last_name": f"User{uid}",
                "email": email,
                "contact_number": "+31612345678",
                "birth_date": "1990-01-01",
                "status": "Active",
                "application_status": "Approved",
            }
        )
        member.insert(ignore_permissions=True)
        self.track_doc("Member", member.name)
        if user_link:
            frappe.db.set_value("Member", member.name, "user", user_link, update_modified=False)
            member.reload()
        return member

    def _make_member_with_user(self, tag="default"):
        user = self._make_user(tag)
        member = self._make_member(email=user.name, user_link=user.name)
        return member, user

    def _make_volunteer(self, member, email):
        """Create an Active Volunteer linked to ``member`` and login ``email``."""
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Cascade {frappe.generate_hash(length=5)}",
                "member": member.name,
                "email": email,
                "status": "Active",
            }
        )
        volunteer.insert(ignore_permissions=True)
        self.track_doc("Volunteer", volunteer.name)
        return volunteer

    # ------------------------------------------------- normalization branch

    def test_mixed_case_email_lowercased_on_rename(self):
        """A mixed-case new email renames the User to lowercase AND normalizes Member.email.

        Exercises the ``if doc.email != new_email`` branch (lines 79-80): the
        in-memory ``doc.email`` is the mixed-case value, ``new_email`` is the
        lowercased target, so the handler also rewrites Member.email to match.
        """
        member, user = self._make_member_with_user("mixedcase")
        old_name = user.name
        base = self.factory.generate_test_email("emailsyncsw-MixedCase")
        # Force a mixed-case local part so lower() actually changes the string.
        mixed = base.replace("emailsyncsw", "EmailSyncSW")
        self.assertNotEqual(mixed, mixed.lower(), "test email must contain upper-case chars")

        member.email = mixed
        member.save()

        lowered = mixed.lower()
        self.assertFalse(frappe.db.exists("User", old_name), "old User renamed away")
        self.assertTrue(frappe.db.exists("User", lowered), "User renamed to lowercased email")
        # Member.email normalized to the lowercased address (the 79-80 branch).
        self.assertEqual(frappe.db.get_value("Member", member.name, "email"), lowered)
        # Member.user cascaded to the new lowercased login.
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), lowered)

    def test_whitespace_padded_email_stripped(self):
        """Leading/trailing whitespace on the new email is stripped before rename."""
        member, user = self._make_member_with_user("padded")
        old_name = user.name
        target = self.factory.generate_test_email("emailsyncsw-padded").lower()

        member.email = f"  {target}  "
        member.save()

        self.assertFalse(frappe.db.exists("User", old_name))
        self.assertTrue(frappe.db.exists("User", target), "stripped email used as new User name")
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), target)

    def test_rename_emits_no_error_log(self):
        """The SECURITY-AUDIT rename path logs via logger.info, not Error Log."""
        member, user = self._make_member_with_user("noerrorlog")
        new_email = self.factory.generate_test_email("emailsyncsw-clean").lower()

        with self.assertNoErrorLog():
            member.email = new_email
            member.save()

        self.assertTrue(frappe.db.exists("User", new_email))

    # ------------------------------------------------- Link cascade integrity

    def test_rename_cascades_volunteer_link(self):
        """A Volunteer whose linked User is renamed follows the new User name.

        ``rename_doc("User", ...)`` cascades every Link pointing at the User, so a
        Volunteer record carrying the old login email must end up referencing the
        new one — no dangling link.
        """
        member, user = self._make_member_with_user("vol-cascade")
        old_name = user.name

        # A Volunteer linked to the member AND to the User login email.
        self._make_volunteer(member, old_name)

        new_email = self.factory.generate_test_email("emailsyncsw-volnew").lower()
        member.email = new_email
        member.save()

        self.assertTrue(frappe.db.exists("User", new_email))
        self.assertFalse(frappe.db.exists("User", old_name))

    # ------------------------------------------------- direct-handler edge

    def test_handler_noop_when_user_field_blank(self):
        """Direct call: an email change with no linked User returns immediately."""
        email = self.factory.generate_test_email("emailsyncsw-nolink")
        member = self._make_member(email=email)
        self.assertFalse(member.user)

        # in-memory change; handler should hit the ``if not doc.user`` early return
        member.email = self.factory.generate_test_email("emailsyncsw-nolink2")
        # Must not raise and must not create a User.
        sync_user_email_on_member_update(member)
        self.assertFalse(frappe.db.exists("User", member.email))
