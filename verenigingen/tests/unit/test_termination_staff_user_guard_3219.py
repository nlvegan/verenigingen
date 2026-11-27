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

from verenigingen.services.termination import termination_integration as ti
from verenigingen.tests.support.termination_request import execute_real_termination
from verenigingen.tests.utils.base import VereningingenTestCase

STAFF_TITLE = "Termination: staff user account NOT deactivated"
SYNC_TITLE = "Termination: staff user role profile NOT recalculated"
EMPLOYEE_TITLE = "Termination: staff user's Employee record NOT updated"
FAILED_CHECK_TITLE = "Termination: user account NOT deactivated, staff check failed"
BOARD_TITLE = "Termination: staff user's board role NOT withdrawn"


class TestTerminationStaffUserGuard3219(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog(STAFF_TITLE, FAILED_CHECK_TITLE, SYNC_TITLE, EMPLOYEE_TITLE, BOARD_TITLE)
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

    # -- the role-profile sync that follows (#692) must not re-derive a staff user's roles --

    def _make_active_volunteer_3219(self):
        # Volunteer insert queues an Account Creation Request nothing here needs (#2338).
        was_set = "skip_volunteer_account_creation" in frappe.flags
        before = frappe.flags.get("skip_volunteer_account_creation")
        frappe.flags.update({"skip_volunteer_account_creation": True})

        def restore():
            if was_set:
                frappe.flags.update({"skip_volunteer_account_creation": before})
            else:
                frappe.flags.pop("skip_volunteer_account_creation", None)

        self.addCleanup(restore)
        return self.create_test_volunteer(member=self.member.name)

    def test_a_staff_user_who_is_a_volunteer_keeps_roles_through_the_profile_sync(self):
        """System Manager held DIRECTLY (no profile) + Active Volunteer: the refused deactivation
        was followed by sync_user_role_profile, which swapped the roles for the volunteer profile's."""
        email = self._make_linked_user_3219(roles=("System Manager",))
        self._make_active_volunteer_3219()
        before = self._account_state_3219(email)
        self.assertEqual(before["profiles"], [])

        request = self._expel_member_3219()

        self.assertEqual(self._account_state_3219(email), before)
        self.assertTrue(
            any("NOT recalculated" in e for e in self._audit_errors_3219(request)),
            self._audit_errors_3219(request),
        )

    def test_the_profile_sync_fails_closed_when_the_staff_check_errors(self):
        """Fault injected: the classifier raises. Ordinary user + volunteer; the sync must not run."""
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        self._make_active_volunteer_3219()
        from verenigingen.services.member.account.member_role_service import MemberRoleService

        with patch.object(MemberRoleService, "_is_staff_account", side_effect=RuntimeError("db hiccup")):
            with patch(
                "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile"
            ) as sync:
                self._expel_member_3219()
        sync.assert_not_called()

    def test_control_an_ordinary_volunteer_user_still_gets_the_profile_sync(self):
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        self._make_active_volunteer_3219()
        with patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            return_value={"success": True, "changed": False},
        ) as sync:
            self._expel_member_3219()
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], email)

    # -- the ToDo audience fallback ------------------------------------------------------

    def test_with_no_other_system_manager_the_alert_goes_to_administrator(self):
        email = self._make_linked_user_3219(roles=("System Manager",))
        with patch.object(ti, "_staff_alert_recipients", return_value=[]):
            self._expel_member_3219()
        todos = self._refusal_todos_3219(email)
        self.assertTrue(todos)
        self.assertEqual({t.allocated_to for t in todos}, {"Administrator"})

    def _make_plain_user_3219(self, role):
        email = f"alert3219-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Alert3219",
                "enabled": 1,
                "send_welcome_email": 0,
            }
        )
        user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        return email

    def test_the_alert_goes_to_verenigingen_administrators_not_system_managers(self):
        """Part 4 ruling. Real rows: one Verenigingen Administrator, one System-Manager-only user,
        and the terminated user, who holds BOTH roles and must never be a recipient."""
        admin_user = self._make_plain_user_3219("Verenigingen Administrator")
        sysmgr_only = self._make_plain_user_3219("System Manager")
        target = self._make_linked_user_3219(roles=("System Manager", "Verenigingen Administrator"))
        recipients = ti._staff_alert_recipients(target)
        self.assertIn(admin_user, recipients)
        self.assertNotIn(sysmgr_only, recipients)
        self.assertNotIn(target, recipients)
        self._expel_member_3219()
        allocated = {t.allocated_to for t in self._refusal_todos_3219(target)}
        self.assertIn(admin_user, allocated)
        self.assertNotIn(sysmgr_only, allocated)
        self.assertNotIn(target, allocated)

    def test_a_disabled_verenigingen_administrator_gets_no_alert(self):
        admin_user = self._make_plain_user_3219("Verenigingen Administrator")
        frappe.db.set_value("User", admin_user, "enabled", 0)
        self.assertNotIn(admin_user, ti._staff_alert_recipients("nobody@example.com"))

    # -- round 3: the steps BEFORE the deactivate step, and the Employee step --------------

    def _seat_volunteer_and_team_3219(self, volunteer):
        """A real board seat (through Chapter.save, so the deferred profile sync fires) and a team row."""
        role = "Test Board Role 3219"
        if not frappe.db.exists("Chapter Role", role):
            frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role,
                    "permissions_level": "Admin",
                    "is_active": 1,
                }
            ).insert()
        chapter = frappe.get_doc("Chapter", self.create_test_chapter().name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save()
        team_doc = frappe.get_doc("Team", self.factory.create_test_team().name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": self.factory.get_or_create_team_role("Team Member").name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save()
        return chapter

    def _grant_system_manager_3219(self, email):
        """After the seat: seating rewrites a user's roles to the profile-derived set (reviewer's trap)."""
        user = frappe.get_doc("User", email)
        user.role_profiles = []
        user.append("roles", {"role": "System Manager"})
        user.save(ignore_permissions=True)

    def _make_employee_3219(self, email):
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Emp{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": get_eur_test_company(),
                "user_id": email,
            }
        ).insert(ignore_permissions=True)
        return employee.name

    def test_a_board_seat_does_not_strip_a_staff_user_before_the_deactivate_step(self):
        """F5. Staff user (System Manager held directly, granted AFTER the seat) + seat + team row +
        Active Volunteer. Ending the seat re-derived roles and dropped System Manager before the
        deactivate step looked, so it classified the user as ordinary and disabled it."""
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        volunteer = self._make_active_volunteer_3219()
        self._seat_volunteer_and_team_3219(volunteer)
        self._grant_system_manager_3219(email)
        before = self._account_state_3219(email)
        self.assertIn("System Manager", before["roles"])
        self.assertEqual(before["profiles"], [])
        board_log_before = frappe.db.count("Error Log", {"method": BOARD_TITLE})

        request = self._expel_member_3219()

        self.assertEqual(self._account_state_3219(email), before)
        self.assertTrue(
            any(email in e and "NOT deactivated" in e for e in self._audit_errors_3219(request)),
            self._audit_errors_3219(request),
        )
        self.assertFalse(any("Deactivated user account" in a.details for a in request.audit_trail))
        # Nit: the skipped board-role withdrawal leaves its own trace.
        self.assertGreater(frappe.db.count("Error Log", {"method": BOARD_TITLE}), board_log_before)

    def test_a_staff_user_with_a_linked_employee_keeps_both(self):
        """F6 / ruling part 3: ERPNext disables the User when its Employee leaves."""
        email = self._make_linked_user_3219(roles=("System Manager",))
        employee = self._make_employee_3219(email)
        before = self._account_state_3219(email)

        request = self._expel_member_3219()

        self.assertEqual(frappe.db.get_value("Employee", employee, "status"), "Active")
        self.assertEqual(self._account_state_3219(email), before)
        self.assertEqual(before["enabled"], 1)
        self.assertGreater(frappe.db.count("Error Log", {"method": EMPLOYEE_TITLE}), 0)
        self.assertTrue(
            any("Employee record" in e and "NOT updated" in e for e in self._audit_errors_3219(request)),
            self._audit_errors_3219(request),
        )

    def test_control_an_ordinary_seated_volunteer_with_an_employee_is_still_stripped(self):
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        volunteer = self._make_active_volunteer_3219()
        self._seat_volunteer_and_team_3219(volunteer)
        # Seating a volunteer on a board gives its user an Employee (profile with the Employee role).
        employee = frappe.db.get_value("Employee", {"user_id": email}, "name")
        self.assertTrue(employee, "fixture must really link an Employee to the user")
        self.assertEqual(frappe.db.get_value("Employee", employee, "status"), "Active")
        before = self._account_state_3219(email)
        self.assertIn("Verenigingen Chapter Board Member", before["roles"])

        request = self._expel_member_3219()

        self.assertEqual(frappe.db.get_value("Employee", employee, "status"), "Left")
        state = self._account_state_3219(email)
        self.assertEqual(state["enabled"], 0)
        # The volunteer sync downgrades to the plain member profile; the board and employee
        # roles that the seat conferred are gone.
        self.assertNotIn("Verenigingen Chapter Board Member", state["roles"])
        self.assertNotIn("Employee", state["roles"])
        self.assertFalse(self._refusal_todos_3219(email))
        self.assertFalse(any("NOT" in e for e in self._audit_errors_3219(request)))

    # -- round 4 (F7): the second entry point, execute_safe_termination ------------------

    def _expel_via_safe_api_3219(self):
        from verenigingen.api.termination_api import execute_safe_termination

        return execute_safe_termination(self.member.name, "Expulsion", frappe.utils.today())

    def test_execute_safe_termination_keeps_a_seated_staff_user(self):
        """F7. Same shape as the F5 test, through the whitelisted API (it does not use
        TerminationExecutor): seat + team row + Active Volunteer + Employee, SM granted after the seat."""
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        volunteer = self._make_active_volunteer_3219()
        self._seat_volunteer_and_team_3219(volunteer)
        self._grant_system_manager_3219(email)
        before = self._account_state_3219(email)
        self.assertIn("System Manager", before["roles"])
        self.assertEqual(before["enabled"], 1)

        result = self._expel_via_safe_api_3219()

        self.assertEqual(self._account_state_3219(email), before)
        self.assertFalse(result["success"], result)
        self.assertTrue(
            any(email in e and "NOT deactivated" in e for e in result["errors"]), result["errors"]
        )
        self.assertNotIn("Deactivated user account", result["actions_taken"])

    def test_control_execute_safe_termination_still_deactivates_an_ordinary_seated_user(self):
        email = self._make_linked_user_3219(roles=("Verenigingen Member",))
        volunteer = self._make_active_volunteer_3219()
        self._seat_volunteer_and_team_3219(volunteer)

        result = self._expel_via_safe_api_3219()

        self.assertEqual(self._account_state_3219(email)["enabled"], 0)
        self.assertIn("Deactivated user account", result["actions_taken"])
        self.assertFalse(any("NOT" in e for e in result["errors"]), result["errors"])

    def test_execute_safe_termination_refuses_a_staff_user_without_a_seat(self):
        """The no-seat control: this path was already right and must stay so."""
        email = self._make_linked_user_3219(roles=("System Manager",))
        before = self._account_state_3219(email)

        result = self._expel_via_safe_api_3219()

        self.assertEqual(self._account_state_3219(email), before)
        self.assertTrue(any("NOT deactivated" in e for e in result["errors"]), result["errors"])

    def test_the_protection_flag_is_restored_after_the_context(self):
        self.assertNotIn(ti.PROTECTED_USERS_FLAG, frappe.flags)
        with ti.termination_user_protection(self.member.name):
            self.assertIn(ti.PROTECTED_USERS_FLAG, frappe.flags)
        self.assertNotIn(ti.PROTECTED_USERS_FLAG, frappe.flags)
