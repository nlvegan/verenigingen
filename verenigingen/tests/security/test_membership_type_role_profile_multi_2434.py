"""#2434: membership_type_role_profile must read and write the ``role_profiles`` child table.

Probed on test_site_5 (Frappe 16.55.2) before the fix, driving real User saves:

- the write at ``role_profile_name = X`` is NOT a no-op in the normal case: User's
  ``move_role_profile_name_to_role_profiles`` appends X (empty table or not). The issue's
  "suspected write no-op" did not hold there.
- the read saw only the FIRST profile, so a user holding X as a later profile was told
  "assigned successfully" and re-saved for nothing.
- a stale mirror (``role_profile_name == X`` with no child row) is read as "already has X"
  while the user holds nothing: nothing is ever written.

Probe shortcut: the stale mirror is built with ``db.set_value`` on the deprecated column
(legacy data from before the child table); every other user is built by a real User insert.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.membership_type_role_profile import assign_membership_type_role_profile

PROFILE = "Verenigingen Auditor"
OTHER = "Verenigingen Staff"


class TestMembershipTypeRoleProfileMulti2434(EnhancedTestCase):
    def _user(self, profiles):
        email = f"mtrp2434-{frappe.generate_hash(length=8)}@example.com"
        doc = frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "Mtrp", "send_welcome_email": 0}
        )
        for name in profiles:
            doc.append("role_profiles", {"role_profile": name})
        doc.insert()
        self.addCleanup(frappe.delete_doc, "User", email, force=True)
        return email

    def _type(self):
        name = f"MTRP2434 {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": name,
                "is_active": 1,
                "minimum_amount": 5,
                "role_profile": PROFILE,
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "Membership Type", name, force=True)
        return name

    @staticmethod
    def _held(user):
        return set(
            frappe.get_all("User Role Profile", filters={"parent": user, "parenttype": "User"}, pluck="role_profile")
        )

    def test_a_later_profile_counts_as_already_held(self):
        user = self._user([OTHER, PROFILE])
        self.assertEqual(frappe.db.get_value("User", user, "role_profile_name"), OTHER, "fixture: PROFILE is later")
        before = frappe.db.get_value("User", user, "modified")

        result = assign_membership_type_role_profile(user, self._type())

        self.assertTrue(result.get("already_assigned"), result)
        self.assertEqual(frappe.db.get_value("User", user, "modified"), before, "no redundant save")

    def test_a_stale_mirror_without_a_child_row_still_gets_the_profile(self):
        user = self._user([])
        frappe.db.set_value("User", user, "role_profile_name", PROFILE, update_modified=False)  # legacy mirror
        self.assertEqual(self._held(user), set(), "fixture: no child row")

        result = assign_membership_type_role_profile(user, self._type())

        self.assertTrue(result.get("success"), result)
        self.assertFalse(result.get("already_assigned"), result)
        self.assertIn(PROFILE, self._held(user))

    def test_assigning_keeps_the_profiles_the_user_already_holds(self):
        """Control: the new profile is ADDED beside Staff, not swapped for it."""
        user = self._user([OTHER])

        result = assign_membership_type_role_profile(user, self._type())

        self.assertTrue(result.get("success"), result)
        self.assertFalse(result.get("already_assigned"), result)
        self.assertEqual(self._held(user), {OTHER, PROFILE})
