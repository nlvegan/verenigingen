"""The bulk role-profile endpoints need authority over THAT team, or are admin-only (#1686).

bulk_assign_team_role_profiles and the chapter board bulk endpoints were gated only by the
ADMIN security tier, so a holder of the Treasurer profile (clears the tier, measured in
#1659) could run them for any team or chapter.

Team: the authority of the sibling remove_* endpoints (#1615): System Manager / Verenigingen
Administrator, or write permission on that Team (the Team Lead role AND team scope; a plain
team member has no Team write). Chapter board bulk endpoints: maintainer ruling 2026-10-31,
ADMIN-ONLY (System Manager / Verenigingen Administrator); Treasurer, National Board Member
and Staff are refused. Unknown and forbidden entities are refused identically.

Probe shortcuts, stated: the seated member's Team Member row / the chapter's
default_board_role_profile are set with db.set_value AFTER seating, so that the bulk call
has a real change to make (saving the parent runs the seating sync itself and would hide
what the endpoint does). Each test asserts that pre-state as a control, and the admin
control proves the call really changes it.
"""

import frappe

from verenigingen.tests.security import test_national_profile_assignment_guard as sibling
from verenigingen.tests.utils.base import VereningingenTestCase

TREASURER = "Verenigingen Treasurer"
ADMIN_PROFILE = "Verenigingen Administrator"
AUDITOR = "Verenigingen Auditor"
REFUSAL = "do not have permission to change role profiles"
NBM = "Verenigingen National Board Member"


# Reused from the sibling module (imported as a module so its TestCase is not collected twice).
def _sibling_call_as(test, actor, fn, *args):
    return sibling.TestNationalProfileAssignmentGuard._call_as(test, actor, fn, *args)


def _sibling_profiles_of(test, email):
    return sibling.TestNationalProfileAssignmentGuard._profiles_of(test, email)


class TestBulkRoleProfileAuthz(VereningingenTestCase):
    def _make_bulk1686_actor(self, profile=None, roles=()):
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

    def _seat_on_team(self, team_name, status, actor_user=None):
        user = actor_user or self._make_bulk1686_actor()
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
        self.assertNotIn(AUDITOR, _sibling_profiles_of(self, victim), "control: not held yet")
        return team.name, victim

    # -- team ----------------------------------------------------------------

    def test_a_treasurer_outside_the_team_cannot_bulk_assign_its_profiles(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, victim = self._pending_team()
        attacker = self._make_bulk1686_actor(TREASURER)

        with self.assertRaisesRegex(frappe.PermissionError, REFUSAL):
            _sibling_call_as(self, attacker, bulk_assign_team_role_profiles, team)

        self.assertNotIn(AUDITOR, _sibling_profiles_of(self, victim))

    def test_an_administrator_still_bulk_assigns_and_it_changes_the_member(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, victim = self._pending_team()
        admin = self._make_bulk1686_actor(ADMIN_PROFILE)

        result = _sibling_call_as(self, admin, bulk_assign_team_role_profiles, team)

        self.assertTrue(result.get("success"), result)
        self.assertIn(AUDITOR, _sibling_profiles_of(self, victim))

    def test_a_team_lead_may_bulk_assign_their_own_team_but_not_another(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        own, own_victim = self._pending_team()
        other, other_victim = self._pending_team()
        lead = self._make_bulk1686_actor()
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
            _sibling_call_as(self, lead, bulk_assign_team_role_profiles, other)
        self.assertNotIn(AUDITOR, _sibling_profiles_of(self, other_victim))

        result = _sibling_call_as(self, lead, bulk_assign_team_role_profiles, own)
        self.assertTrue(result.get("success"), result)
        self.assertIn(AUDITOR, _sibling_profiles_of(self, own_victim), result)

    def test_unknown_and_forbidden_teams_are_refused_identically(self):
        from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

        team, _victim = self._pending_team()
        attacker = self._make_bulk1686_actor(TREASURER)
        seen = []
        for name in (team, "No Such Team " + frappe.generate_hash(length=6)):
            frappe.local.message_log = []  # Mock justified: execution-context reset, as in PR #1436 (trim before the call)
            with self.assertRaises(frappe.PermissionError) as caught:
                _sibling_call_as(self, attacker, bulk_assign_team_role_profiles, name)
            log = [{k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log]
            seen.append((type(caught.exception), str(caught.exception), log))
        self.assertEqual(seen[0], seen[1])

    # -- chapter board (admin-only) -------------------------------------------

    def _pending_chapter(self):
        chapter = self.create_test_chapter(
            chapter_name=f"Bulk1686 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        email = f"bulk1686c-{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Bulk", last_name="Seat", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        role = f"Secretary {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", role)
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role, email=email)
        frappe.db.set_value("Chapter", chapter.name, "default_board_role_profile", AUDITOR)  # probe shortcut
        self.assertNotIn(AUDITOR, _sibling_profiles_of(self, user.name), "control: not held yet")
        return chapter.name, user.name

    def _chapter_endpoints(self):
        from verenigingen.services.chapter.chapter_role_profile_manager import (
            bulk_assign_chapter_board_role_profiles,
        )
        from verenigingen.verenigingen.doctype.chapter.chapter import bulk_apply_chapter_board_role_profiles

        return (bulk_assign_chapter_board_role_profiles, bulk_apply_chapter_board_role_profiles)

    def test_treasurer_and_national_board_callers_cannot_bulk_assign_a_chapter(self):
        chapter, victim = self._pending_chapter()
        for profile in (TREASURER, NBM):
            actor = self._make_bulk1686_actor(profile)
            for fn in self._chapter_endpoints():
                with self.subTest(profile=profile, endpoint=fn.__name__):
                    with self.assertRaisesRegex(frappe.PermissionError, REFUSAL):
                        _sibling_call_as(self, actor, fn, chapter)
                    self.assertNotIn(AUDITOR, _sibling_profiles_of(self, victim))

    def test_an_administrator_bulk_assigns_a_chapter_and_it_changes_the_member(self):
        service_fn, wrapper_fn = self._chapter_endpoints()
        for fn in (service_fn, wrapper_fn):
            with self.subTest(endpoint=fn.__name__):
                chapter, victim = self._pending_chapter()
                admin = self._make_bulk1686_actor(ADMIN_PROFILE)

                result = _sibling_call_as(self, admin, fn, chapter)

                self.assertTrue(result.get("success"), result)
                self.assertIn(AUDITOR, _sibling_profiles_of(self, victim))

    def test_unknown_and_forbidden_chapters_are_refused_identically(self):
        chapter, _victim = self._pending_chapter()
        attacker = self._make_bulk1686_actor(TREASURER)
        for fn in self._chapter_endpoints():
            with self.subTest(endpoint=fn.__name__):
                seen = []
                for name in (chapter, "No Such Chapter " + frappe.generate_hash(length=6)):
                    frappe.local.message_log = []  # Mock justified: execution-context reset (trim before call)
                    with self.assertRaises(frappe.PermissionError) as caught:
                        _sibling_call_as(self, attacker, fn, name)
                    log = [
                        {k: v for k, v in m.items() if k != "__frappe_exc_id"}
                        for m in frappe.local.message_log
                    ]
                    seen.append((type(caught.exception), str(caught.exception), log))
                self.assertEqual(seen[0], seen[1])
