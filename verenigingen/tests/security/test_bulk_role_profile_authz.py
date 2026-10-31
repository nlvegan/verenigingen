"""The bulk role-profile endpoints need authority over THAT team / chapter (#1686).

bulk_assign_team_role_profiles and bulk_assign_chapter_board_role_profiles (and the
chapter.py wrapper bulk_apply_chapter_board_role_profiles) were gated only by the ADMIN
security tier. A holder of the Treasurer profile (clears the tier, measured in #1659) could
run them for any team or chapter. The authority reused is the one the sibling remove_*
endpoints already use (#1615): System Manager / Verenigingen Administrator, or write
permission on that Team / Chapter. Unknown and forbidden entities are refused identically.

Probe shortcuts, stated: the seated member's Team Member row / the chapter's
default_board_role_profile are set with db.set_value AFTER seating, so that the bulk call
has a real change to make (saving the parent runs the seating sync itself and would hide
what the endpoint does). Each test asserts that pre-state as a control, and the admin
control proves the call really changes it.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

TREASURER = "Verenigingen Treasurer"
ADMIN_PROFILE = "Verenigingen Administrator"
AUDITOR = "Verenigingen Auditor"
REFUSAL = "do not have permission to change role profiles"


class TestBulkRoleProfileAuthz(VereningingenTestCase):
    def _user(self, profile=None, roles=()):
        email = f"bulk1686-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Bulk",
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in roles],
                "role_profiles": [{"role_profile": profile}] if profile else [],
            }
        ).insert()
        self.track_doc("User", user.name)
        return user.name

    def _profiles_of(self, email):
        return set(frappe.get_all("User Role Profile", filters={"parent": email}, pluck="role_profile"))

    def _call_as(self, actor, fn, *args):
        frappe.is_whitelisted(fn)  # the dispatcher's gate
        previous = frappe.session.user
        frappe.set_user(actor)
        try:
            return fn(*args)
        finally:
            frappe.set_user(previous)

    def _seat_on_team(self, team_name, status, actor_user=None):
        user = actor_user or self._user()
        member = self.create_test_member(user=user, chapter=False)
        volunteer = self.create_test_volunteer(member=member.name)
        doc = frappe.get_doc("Team", team_name)
        doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": status,
            },
        )
        doc.save()
        return user, doc.team_members[-1].name

    def _pending_team(self):
        """A team mapped to AUDITOR whose one member would gain AUDITOR on a bulk run."""
        frappe.db.set_single_value("Verenigingen Settings", "creation_user", "Administrator")
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        doc = frappe.get_doc("Team", team.name)
        doc.enable_role_profiles = 1
        doc.default_role_profile = AUDITOR
        doc.save()
        victim, row = self._seat_on_team(team.name, "Inactive")
        frappe.db.set_value("Team Member", row, "status", "Active")  # probe shortcut
        self.assertNotIn(AUDITOR, self._profiles_of(victim), "control: not held yet")
        return team.name, victim

    # -- team ----------------------------------------------------------------

    def test_a_treasurer_outside_the_team_cannot_bulk_assign_its_profiles(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, victim = self._pending_team()
        attacker = self._user(TREASURER)

        with self.assertRaisesRegex(frappe.PermissionError, REFUSAL):
            self._call_as(attacker, bulk_assign_team_role_profiles, team)

        self.assertNotIn(AUDITOR, self._profiles_of(victim))

    def test_an_administrator_still_bulk_assigns_and_it_changes_the_member(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, victim = self._pending_team()
        admin = self._user(ADMIN_PROFILE)

        result = self._call_as(admin, bulk_assign_team_role_profiles, team)

        self.assertTrue(result.get("success"), result)
        self.assertIn(AUDITOR, self._profiles_of(victim))

    def test_a_team_lead_may_bulk_assign_their_own_team_but_not_another(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        own, own_victim = self._pending_team()
        other, other_victim = self._pending_team()
        lead = self._user()
        self._seat_on_team(own, "Active", actor_user=lead)
        # Probe shortcut: saving the team to seat the lead reset the victim's row; flip it back.
        frappe.db.set_value("Team Member", {"parent": own, "status": "Inactive"}, "status", "Active")
        # Probe shortcut: seating on a mapped team ran the sync, which REPLACED the lead's direct
        # roles with the team profile (#1685); hand back what a real team lead holds.
        lead_doc = frappe.get_doc("User", lead)
        lead_doc.set("role_profiles", [{"role_profile": TREASURER}])
        lead_doc.save()
        # A role profile REPLACES direct roles on save, so the Team Lead role is written after it.
        frappe.get_doc(
            {
                "doctype": "Has Role",
                "parent": lead,
                "parenttype": "User",
                "parentfield": "roles",
                "role": "Team Lead",
            }
        ).insert()
        frappe.clear_cache(user=lead)

        with self.assertRaisesRegex(frappe.PermissionError, REFUSAL):
            self._call_as(lead, bulk_assign_team_role_profiles, other)
        self.assertNotIn(AUDITOR, self._profiles_of(other_victim))

        result = self._call_as(lead, bulk_assign_team_role_profiles, own)
        self.assertTrue(result.get("success"), result)
        self.assertIn(AUDITOR, self._profiles_of(own_victim), result)

    def test_unknown_and_forbidden_teams_are_refused_identically(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, _victim = self._pending_team()
        attacker = self._user(TREASURER)
        seen = []
        for name in (team, "No Such Team " + frappe.generate_hash(length=6)):
            frappe.local.message_log = []  # Mock justified: execution-context reset, as in PR #1436 (trim before the call)
            with self.assertRaises(frappe.PermissionError) as caught:
                self._call_as(attacker, bulk_assign_team_role_profiles, name)
            log = [{k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log]
            seen.append((type(caught.exception), str(caught.exception), log))
        self.assertEqual(seen[0], seen[1])
