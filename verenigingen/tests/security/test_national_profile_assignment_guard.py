"""Direct assignment of a privileged Role Profile needs an administrator (#1654).

Policy (maintainer, 2026-10-12): the Verenigingen Treasurer profile (payroll access
after #1606) is NATIONAL only. It is obtained through the national_board_chapter
mapping (#1616) or by a deliberate assignment by a System Manager or Verenigingen
Administrator, never by a heuristic and never by a holder of another national profile.

Before this fix:
  * get_recommended_role_profile() recommended Treasurer for every Staff user holding
    Accounts User, and the shipped Staff profile itself carries Accounts User.
  * the ADMIN-tier endpoints let holders of the Treasurer / National Board Member
    profiles (both CRITICAL in ROLE_PROFILE_SECURITY_MAPPING) assign ANY profile,
    "Verenigingen Administrator" (System Manager) included.

Entry points are driven the way the dispatcher drives them: frappe.is_whitelisted(fn),
then fn(...) under frappe.set_user(<real user holding the real profile>).

Probe shortcut, stated: the chapter / team mapping fixtures are saved through the real
document save as Administrator (national_board_chapter set), so the mapping is the one
an administrator could legitimately configure.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

TREASURER = "Verenigingen Treasurer"
NBM = "Verenigingen National Board Member"
ADMIN_PROFILE = "Verenigingen Administrator"


class TestNationalProfileAssignmentGuard(VereningingenTestCase):
    def _make_user_holding_profile(self, profile, extra_roles=()):
        email = f"np1654-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "NP",
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in extra_roles],
                "role_profiles": [{"role_profile": profile}] if profile else [],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user.name

    def _profiles_of(self, email):
        return set(frappe.get_all("User Role Profile", filters={"parent": email}, pluck="role_profile"))

    def _call_as(self, actor, fn, *args, **kwargs):
        """Dispatcher-shaped call: whitelist check, then the function as `actor`."""
        frappe.is_whitelisted(fn)  # raises PermissionError when the dispatcher would refuse it
        previous = frappe.session.user
        frappe.set_user(actor)
        try:
            return fn(*args, **kwargs)
        finally:
            frappe.set_user(previous)

    def _assert_assignment_refused(self, actor, profile, fn, *args):
        """One exception type and the specific message for the reason: a national profile
        is refused as such, any other as a roles-held refusal. Both name the profile."""
        with self.assertRaises(frappe.PermissionError) as ctx:
            self._call_as(actor, fn, *args)
        reason = (
            "can only be assigned by a system manager"
            if profile in (TREASURER, NBM)
            else "grants roles you do not hold"
        )
        message = str(ctx.exception).lower()
        self.assertIn(f"'{profile}'".lower(), message)
        self.assertIn(reason, message)

    # -- the heuristic ------------------------------------------------------

    def _staff_member_with_accounts_user(self):
        email = f"np1654-s-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=[Roles.VERENIGINGEN_STAFF, "Accounts User"])
        self.create_test_member(user=email, chapter=False)
        return email

    def test_the_staff_profile_really_carries_accounts_user(self):
        """Control: the premise of the heuristic bug. If this fails the tests below prove nothing."""
        roles = frappe.get_all("Has Role", filters={"parent": "Verenigingen Staff"}, pluck="role")
        self.assertIn("Accounts User", roles)

    def test_auto_assign_never_hands_out_the_treasurer_profile(self):
        from verenigingen.setup.role_profile_setup import auto_assign_role_profiles

        email = self._staff_member_with_accounts_user()
        self.assertNotIn(TREASURER, self._profiles_of(email))

        auto_assign_role_profiles()  # tests run as Administrator

        self.assertEqual(self._profiles_of(email), {"Verenigingen Staff"})

    def test_the_cli_ladder_never_hands_out_the_treasurer_profile(self):
        from verenigingen.setup.role_profile_setup import setup_role_profiles_cli

        email = self._staff_member_with_accounts_user()
        try:
            setup_role_profiles_cli()
            # read BEFORE the rollback: user saves after the CLI's last commit are
            # uncommitted, and a rollback first would make this pass vacuously
            profiles = self._profiles_of(email)
        finally:
            frappe.db.rollback()
        self.assertEqual(profiles, {"Verenigingen Staff"})

    # -- assign_role_profile_to_user ---------------------------------------

    def test_a_treasurer_holder_cannot_assign_a_privileged_profile(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        actor = self._make_user_holding_profile(TREASURER)
        for target_profile in (ADMIN_PROFILE, "Verenigingen System Administrator", NBM, TREASURER):
            victim = self._make_user_holding_profile(None)
            self._assert_assignment_refused(actor, target_profile, assign_role_profile_to_user, victim, target_profile)
            self.assertNotIn(target_profile, self._profiles_of(victim), target_profile)

    def test_a_national_board_member_cannot_assign_a_privileged_profile(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, TREASURER, assign_role_profile_to_user, victim, TREASURER)
        self.assertNotIn(TREASURER, self._profiles_of(victim))

    def test_an_ordinary_profile_can_still_be_assigned_by_the_same_actor(self):
        """Control: the guard refuses privileged profiles, not the whole endpoint."""
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        actor = self._make_user_holding_profile(TREASURER)
        victim = self._make_user_holding_profile(None)
        self._call_as(actor, assign_role_profile_to_user, victim, "Verenigingen Member")
        self.assertIn("Verenigingen Member", self._profiles_of(victim))

    def test_an_administrator_can_deliberately_assign_the_treasurer_profile(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        for actor in ("Administrator", self._make_user_holding_profile(ADMIN_PROFILE)):
            victim = self._make_user_holding_profile(None)
            self._call_as(actor, assign_role_profile_to_user, victim, TREASURER)
            self.assertIn(TREASURER, self._profiles_of(victim), actor)

    def _profile_granting(self, *roles):
        name = f"NP1654 {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Role Profile", "role_profile": name, "roles": [{"role": r} for r in roles]}
        ).insert()
        self.track_doc("Role Profile", name)
        return name

    def test_a_profile_granting_roles_the_actor_lacks_is_refused(self):
        """HR Manager is Treasurer-only (#1606 ruling) and the stock "HR" / "Accounts" profiles
        grant it / Accounts Manager. Neither actor holds the role, so neither may hand it out."""
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        hr = self._profile_granting("HR Manager")
        accounts = self._profile_granting("Accounts Manager")
        for actor_profile, target in ((NBM, hr), (TREASURER, hr), (NBM, accounts)):
            actor_roles = set(frappe.get_all("Has Role", filters={"parent": actor_profile}, pluck="role"))
            self.assertNotIn(frappe.db.get_value("Has Role", {"parent": target}, "role"), actor_roles)
            actor = self._make_user_holding_profile(actor_profile)
            victim = self._make_user_holding_profile(None)
            self._assert_assignment_refused(actor, target, assign_role_profile_to_user, victim, target)
            self.assertNotIn(target, self._profiles_of(victim), (actor_profile, target))

    def test_the_unheld_role_need_not_be_the_first_one_in_the_profile(self):
        """Mutant guard: only the first granted role is compared. Projects User (held by NBM)
        comes first, HR Manager (not held) second."""
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        mixed = self._profile_granting("Projects User", "HR Manager")
        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, mixed, assign_role_profile_to_user, victim, mixed)
        self.assertNotIn(mixed, self._profiles_of(victim))

    def test_a_national_profile_is_refused_even_to_an_actor_holding_every_role_it_grants(self):
        """The roles-held rule alone would let this through, so the national refusal is
        pinned separately: a test-created profile named like the real one is not possible, so
        the actor is given the whole role set of the real profile directly."""
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        granted = frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": NBM}, pluck="role")
        actor = self._make_user_holding_profile(None, extra_roles=granted)
        # Control: the actor holds every role bar Employee / Employee Self Service, which User
        # validation strips without an Employee record and which #1649/#1661 exempts from the
        # roles-held rule. So the roles-held rule cannot be what refuses below; the message
        # asserted below ("can only be assigned") is the national refusal's.
        self.assertFalse(set(granted) - set(frappe.get_roles(actor)) - {"Employee", "Employee Self Service"})
        victim = self._make_user_holding_profile(None)
        # Reach the ADMIN tier through a CRITICAL profile whose roles are all granted too.
        actor_doc = frappe.get_doc("User", actor)
        actor_doc.append("role_profiles", {"role_profile": NBM})
        actor_doc.save()
        self._assert_assignment_refused(actor, NBM, assign_role_profile_to_user, victim, NBM)
        self.assertNotIn(NBM, self._profiles_of(victim))

    def test_the_stock_hr_profile_is_refused_to_a_national_board_member(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        if not frappe.db.exists("Role Profile", "HR"):
            self.skipTest("stock ERPNext 'HR' Role Profile is not installed on this site")
        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, "HR", assign_role_profile_to_user, victim, "HR")

    def test_a_profile_whose_roles_the_actor_all_holds_can_be_assigned(self):
        """Control for the test above, with a real profile built from roles NBM holds."""
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        held = self._profile_granting("Projects User", "Expense Approver")
        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._call_as(actor, assign_role_profile_to_user, victim, held)
        self.assertIn(held, self._profiles_of(victim))

    def test_the_chapter_and_team_endpoints_refuse_a_mapped_profile_the_actor_cannot_hold(self):
        from verenigingen.utils.team_role_profile_manager import assign_team_role_profile

        hr = self._profile_granting("HR Manager")
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        doc = frappe.get_doc("Team", team.name)
        doc.enable_role_profiles = 1
        doc.default_role_profile = hr
        doc.save()
        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, hr, assign_team_role_profile, victim, team.name)
        self.assertNotIn(hr, self._profiles_of(victim))

    # -- chapter / team assignment endpoints -------------------------------

    def _national_chapter_mapped_to(self, profile):
        chapter = self.create_test_chapter(
            chapter_name=f"Natl {frappe.generate_hash(length=6)}", postal_codes="1000-1999", published=1
        )
        old = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", old)
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter.name)
        doc = frappe.get_doc("Chapter", chapter.name)
        doc.default_board_role_profile = profile
        doc.save()
        return chapter.name

    def test_a_national_board_member_cannot_hand_out_the_national_profile_via_the_chapter_endpoint(self):
        from verenigingen.services.chapter.chapter_role_profile_manager import (
            assign_chapter_board_role_profile,
        )

        chapter = self._national_chapter_mapped_to(TREASURER)
        actor = self._make_user_holding_profile(NBM)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, TREASURER, assign_chapter_board_role_profile, victim, chapter)
        self.assertNotIn(TREASURER, self._profiles_of(victim))

    def test_an_administrator_can_use_the_chapter_endpoint(self):
        from verenigingen.services.chapter.chapter_role_profile_manager import (
            assign_chapter_board_role_profile,
        )

        chapter = self._national_chapter_mapped_to(TREASURER)
        victim = self._make_user_holding_profile(None)
        result = self._call_as("Administrator", assign_chapter_board_role_profile, victim, chapter)
        self.assertTrue(result.get("success"), result)
        self.assertIn(TREASURER, self._profiles_of(victim))

    def test_a_treasurer_holder_cannot_hand_out_a_team_profile_granting_system_manager(self):
        from verenigingen.utils.team_role_profile_manager import assign_team_role_profile

        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        doc = frappe.get_doc("Team", team.name)
        doc.enable_role_profiles = 1
        doc.default_role_profile = ADMIN_PROFILE
        doc.save()
        actor = self._make_user_holding_profile(TREASURER)
        victim = self._make_user_holding_profile(None)
        self._assert_assignment_refused(actor, ADMIN_PROFILE, assign_team_role_profile, victim, team.name)
        self.assertNotIn(ADMIN_PROFILE, self._profiles_of(victim))
