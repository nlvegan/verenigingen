"""A termination must never strip or disable a staff user (#3219).

`deactivate_user_account_safe` used to disable the linked User and, for a disciplinary type,
replace its roles with Guest and clear its role profiles, whoever the user was. Ruling
(maintainer, 2026-11-27): staff means `MemberRoleService._is_staff_account` (Administrator or
a System Manager holder) and nothing else; a refused user is left COMPLETELY untouched
(roles, role profiles AND `enabled`), the refusal is recorded (Error Log + ToDo for staff +
the termination's own audit trail), and the termination otherwise proceeds. Seated Treasurers
and National Board members (Verenigingen Staff WITHOUT System Manager) are not protected.

Every test drives the REAL flow (`execute_real_termination`, a disciplinary "Expulsion" through
`TerminationExecutionService`). Probe shortcuts, stated: `Member.user` is set with
`db.set_value` to link the fixture user (the linking flows are #3217's territory), and the
fail-closed test injects the fault by patching `MemberRoleService._is_staff_account` to raise.
The Administrator account itself is deliberately not used as a fixture: on a red run it would be
stripped on the test site.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.support.termination_request import execute_real_termination
from verenigingen.tests.utils.base import VereningingenTestCase

STAFF_TITLE = "Termination: staff user account NOT deactivated"
FAILED_CHECK_TITLE = "Termination: user account NOT deactivated, staff check failed"


class TestTerminationStaffUserGuard3219(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog(STAFF_TITLE, FAILED_CHECK_TITLE)
        self.member = self.create_test_member()

    def _make_linked_user_3219(self, role_profile=None, roles=()):
        email = f"staff3219-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Guard3219",
                "enabled": 1,
                "send_welcome_email": 0,
            }
        )
        if role_profile:
            user.append("role_profiles", {"role_profile": role_profile})
        for role in roles:
            user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        frappe.db.set_value("Member", self.member.name, "user", email)
        return email

    def _account_state_3219(self, email):
        frappe.clear_cache(user=email)
        user = frappe.get_doc("User", email)
        return {
            "enabled": user.enabled,
            "roles": sorted(frappe.get_all("Has Role", filters={"parent": email}, pluck="role")),
            "profiles": sorted(row.role_profile for row in user.role_profiles),
        }

    def _expel_member_3219(self):
        return execute_real_termination(self, self.member.name, frappe.utils.today(), "Expulsion")

    def _audit_errors_3219(self, request):
        return [r.details for r in request.audit_trail if r.action == "System Update Error"]

    def _refusal_todos_3219(self, email):
        return frappe.get_all(
            "ToDo",
            filters={"reference_type": "Member", "reference_name": self.member.name},
            fields=["name", "description", "allocated_to", "status"],
        )

    # -- the red: a System Manager holder who is not Administrator ----------------------

    def test_a_system_manager_user_is_left_untouched_and_the_refusal_is_recorded(self):
        email = self._make_linked_user_3219(roles=("System Manager", "Verenigingen Member"))
        before = self._account_state_3219(email)
        self.assertIn("System Manager", before["roles"])
        log_before = frappe.db.count("Error Log", {"method": STAFF_TITLE})

        request = self._expel_member_3219()

        self.assertEqual(self._account_state_3219(email), before, "a staff user's account was changed")
        self.assertEqual(frappe.db.count("Error Log", {"method": STAFF_TITLE}), log_before + 1)
        todos = self._refusal_todos_3219(email)
        self.assertTrue(todos, "no ToDo alerts staff to the refusal")
        self.assertTrue(all(email in t.description and t.status == "Open" for t in todos))
        self.assertTrue(
            all(t.allocated_to != email for t in todos), "the terminated user is not the alert's audience"
        )
        # The termination still proceeds, and says the user step was refused.
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Banned")
        self.assertTrue(
            any(email in e and "NOT deactivated" in e for e in self._audit_errors_3219(request)),
            self._audit_errors_3219(request),
        )
        self.assertFalse(any("Deactivated user account" in a.details for a in request.audit_trail))

    def test_a_staff_user_on_a_role_profile_keeps_the_profile(self):
        """The #925 shape: the profile is where a re-derivation would restore roles from."""
        email = self._make_linked_user_3219(role_profile="Verenigingen Administrator")
        before = self._account_state_3219(email)
        self.assertIn("System Manager", before["roles"])
        self.assertEqual(before["profiles"], ["Verenigingen Administrator"])

        self._expel_member_3219()

        self.assertEqual(self._account_state_3219(email), before)

    def test_it_fails_closed_when_the_staff_check_errors(self):
        """Fault injected: the classifier raises. An ordinary user is used on purpose, so the
        only thing that can stop the strip is the fail-closed branch."""
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        before = self._account_state_3219(email)
        from verenigingen.services.member.account.member_role_service import MemberRoleService

        with patch.object(MemberRoleService, "_is_staff_account", side_effect=RuntimeError("db hiccup")):
            request = self._expel_member_3219()

        self.assertEqual(self._account_state_3219(email), before)
        self.assertEqual(frappe.db.count("Error Log", {"method": FAILED_CHECK_TITLE}) > 0, True)
        self.assertTrue(self._refusal_todos_3219(email))
        self.assertTrue(any("NOT deactivated" in e for e in self._audit_errors_3219(request)))

    # -- controls: the ruling leaves these as they were ---------------------------------

    def test_control_an_ordinary_member_user_is_still_deactivated_and_stripped(self):
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))

        request = self._expel_member_3219()

        state = self._account_state_3219(email)
        self.assertEqual(state["enabled"], 0)
        self.assertNotIn("Verenigingen Member", state["roles"])
        self.assertFalse(self._refusal_todos_3219(email))
        self.assertFalse(self._audit_errors_3219(request))
        self.assertTrue(any("Deactivated user account" in a.details for a in request.audit_trail))

    def test_control_a_treasurer_profile_user_without_system_manager_is_still_stripped(self):
        """Ruling part 2: seated Treasurers / National Board members are NOT protected."""
        email = self._make_linked_user_3219(role_profile="Verenigingen Treasurer")
        before = self._account_state_3219(email)
        self.assertIn("Verenigingen Staff", before["roles"], "fixture must really hold the staff role")
        self.assertNotIn("System Manager", before["roles"])

        self._expel_member_3219()

        state = self._account_state_3219(email)
        self.assertEqual(state["enabled"], 0)
        self.assertEqual(state["profiles"], [])
        self.assertNotIn("Verenigingen Staff", state["roles"])
        self.assertFalse(self._refusal_todos_3219(email))
