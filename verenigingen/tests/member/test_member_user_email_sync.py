"""Tests for Member email change → User rename sync."""

import frappe

from verenigingen.services.member.account.member_user_email_sync import (
    _SYNC_FLAG,
    sync_user_email_on_member_update,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberUserEmailSync(EnhancedTestCase):
    """Verify Member.email changes propagate to the linked User login."""

    def _make_user(self, tag):
        email = self.factory.generate_test_email(f"emailsync-{tag}")
        return self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])

    def _make_member(self, email, user_link=None):
        """Create a Member without triggering Customer creation (bypasses factory)."""
        uid = self.uid if hasattr(self, "uid") else frappe.generate_hash(length=6)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Sync",
                "last_name": f"User{uid}",
                "email": email,
                "contact_number": "+31612345678",
                "birth_date": "1990-01-01",
                "status": "Active",
                "application_status": "Approved",
            }
        )
        member.insert(ignore_permissions=True)
        if user_link:
            frappe.db.set_value("Member", member.name, "user", user_link, update_modified=False)
            member.reload()
        return member

    def _make_member_with_user(self, tag="default"):
        user = self._make_user(tag)
        member = self._make_member(email=user.name, user_link=user.name)
        return member, user

    # --- Happy path ---------------------------------------------------------

    def test_email_change_renames_user(self):
        member, user = self._make_member_with_user("happy")
        old_name = user.name
        new_email = self.factory.generate_test_email("emailsync-new").lower()

        member.email = new_email
        member.save()

        self.assertFalse(frappe.db.exists("User", old_name), "Old User should be renamed away")
        self.assertTrue(frappe.db.exists("User", new_email), "New User should exist after rename")
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), new_email)
        self.assertEqual(frappe.db.get_value("User", new_email, "email"), new_email)

    # --- Edge cases ---------------------------------------------------------

    def test_no_linked_user_is_noop(self):
        email = self.factory.generate_test_email("emailsync-nouser")
        member = self._make_member(email=email)
        self.assertFalse(member.user)

        member.email = self.factory.generate_test_email("emailsync-nl")
        member.save()  # must not raise

    def test_target_email_already_exists_aborts(self):
        member, user = self._make_member_with_user("conflict-src")
        conflict_user = self._make_user("conflict-dst")

        member.email = conflict_user.name
        with self.assertRaises(frappe.ValidationError):
            member.save()

        self.assertTrue(frappe.db.exists("User", user.name))
        self.assertTrue(frappe.db.exists("User", conflict_user.name))

    def test_stale_user_link_is_cleared(self):
        # In practice Frappe's Link validation rejects the Member save before our
        # on_update handler runs, so this case is only reachable by calling the
        # handler directly (e.g. from a migration script). Verify defensive behavior.
        user = self._make_user("ghost-src")
        member = self._make_member(email=user.name, user_link=user.name)
        frappe.delete_doc("User", user.name, ignore_permissions=True, force=True)

        new_email = self.factory.generate_test_email("emailsync-after-ghost").lower()
        member.email = new_email  # in-memory change simulating has_value_changed
        sync_user_email_on_member_update(member)

        self.assertFalse(frappe.db.get_value("Member", member.name, "user"))
        self.assertFalse(frappe.db.exists("User", new_email))

    def test_no_op_when_email_unchanged(self):
        member, user = self._make_member_with_user("unchanged")
        member.first_name = "Renamed"
        member.save()

        self.assertTrue(frappe.db.exists("User", user.name))
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), user.name)

    def test_case_only_change_is_noop(self):
        member, user = self._make_member_with_user("case")

        member.email = user.name.upper()
        member.save()

        self.assertTrue(frappe.db.exists("User", user.name))

    def test_cleared_email_does_not_rename(self):
        member, user = self._make_member_with_user("cleared")

        member.email = ""
        sync_user_email_on_member_update(member)

        self.assertTrue(frappe.db.exists("User", user.name))

    def test_infinite_loop_guard(self):
        member, user = self._make_member_with_user("loop")
        new_email = self.factory.generate_test_email("emailsync-loop")

        frappe.flags[_SYNC_FLAG] = True
        try:
            member.email = new_email
            sync_user_email_on_member_update(member)
        finally:
            frappe.flags[_SYNC_FLAG] = False

        self.assertTrue(frappe.db.exists("User", user.name))
        self.assertFalse(frappe.db.exists("User", new_email))
