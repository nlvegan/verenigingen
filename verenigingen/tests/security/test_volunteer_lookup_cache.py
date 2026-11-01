"""#1902: the member->volunteer lookup behind every project permission decision must not
outlive the link it reports.

``get_volunteer_for_user`` used to be a process-wide ``lru_cache`` keyed by user only: no
site, no TTL, never cleared outside tests. Unlinking a Volunteer's user (or a Volunteer that
did not exist yet when the lookup first ran) kept answering from the first result.
"""

import frappe

from verenigingen.tests.security.test_project_permissions_coverage import _ProjectPermBase
from verenigingen.utils.project_permissions import (
    get_project_permission_query_conditions,
    get_volunteer_for_user,
)


class TestVolunteerLookupCache(_ProjectPermBase):
    def _volunteer_on_team_with_project(self):
        member, user_email = self._make_member_with_user("Lookup", "Cache")
        volunteer = self._make_volunteer(member)
        suffix = frappe.generate_hash(length=6)
        role = self._make_team_role(f"Lookup Leader {suffix}")
        team = self._make_team(f"Lookup Team {suffix}")
        self._add_team_member(team, volunteer, role)
        self._make_project("Lookup Team Project", custom_team=team.name)
        return member, user_email, volunteer

    def test_unlinking_the_user_is_seen_by_the_next_permission_decision(self):
        """Real flow: Member.save() with the user cleared (no direct DB write)."""
        member, user_email, volunteer = self._volunteer_on_team_with_project()
        self.assertEqual(get_volunteer_for_user(user_email), (member.name, volunteer.name))
        self.assertNotEqual(get_project_permission_query_conditions(user_email), "1=0")

        member.reload()
        member.user = None
        member.save()

        self.assertEqual(get_volunteer_for_user(user_email), (None, None))
        self.assertEqual(get_project_permission_query_conditions(user_email), "1=0")

    def test_a_volunteer_created_after_a_negative_lookup_is_seen(self):
        """A (member, None) answer must not stick once the Volunteer is inserted."""
        member, user_email = self._make_member_with_user("Late", "Volunteer")
        self.assertEqual(get_volunteer_for_user(user_email), (member.name, None))

        volunteer = self._make_volunteer(member)

        self.assertEqual(get_volunteer_for_user(user_email), (member.name, volunteer.name))

    def test_a_deleted_volunteer_is_not_served_from_the_memo(self):
        member, user_email = self._make_member_with_user("Gone", "Volunteer")
        volunteer = self._make_volunteer(member)
        self.assertEqual(get_volunteer_for_user(user_email), (member.name, volunteer.name))

        frappe.delete_doc("Volunteer", volunteer.name, force=True)

        self.assertEqual(get_volunteer_for_user(user_email), (member.name, None))

    def test_a_deleted_member_is_not_served_from_the_memo(self):
        member, user_email = self._make_member_with_user("Gone", "Member")
        self.assertEqual(get_volunteer_for_user(user_email), (member.name, None))

        frappe.delete_doc("Member", member.name, force=True)

        self.assertEqual(get_volunteer_for_user(user_email), (None, None))

    def test_memo_does_not_survive_a_request_boundary(self):
        """Probe shortcut: a raw ``db.set_value`` stands in for ANOTHER worker unlinking the
        user (its hooks cannot reach this process), and ``frappe.local.cache = {}`` stands in
        for the per-request reset Frappe performs in ``frappe.init``."""
        member, user_email = self._make_member_with_user("Boundary", "Cache")
        volunteer = self._make_volunteer(member)
        self.assertEqual(get_volunteer_for_user(user_email), (member.name, volunteer.name))

        frappe.db.set_value("Member", member.name, "user", None)
        frappe.local.cache = {}  # Mock justified: execution-context reset, what frappe.init does per request

        self.assertEqual(get_volunteer_for_user(user_email), (None, None))

    def test_repeat_reads_in_one_request_cost_one_query(self):
        """Counts real SELECTs via the server's own Com_select counter (no patching)."""
        member, user_email = self._make_member_with_user("Count", "Cache")
        self._make_volunteer(member)

        def selects():
            return int(frappe.db.sql("SHOW SESSION STATUS LIKE 'Com_select'")[0][1])

        frappe.local.cache = {}  # Mock justified: execution-context reset, what frappe.init does per request
        before = selects()
        for _ in range(5):
            get_volunteer_for_user(user_email)
        self.assertEqual(selects() - before, 1)
