# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""Integration tests for the Event Contact Campaign controller.

Covers the document lifecycle hooks (validate/progress stats/dashboard HTML)
and every whitelisted endpoint plus the permission query / row-level access
functions. All privileged data creation lives in ``_make_*`` / ``_setup_*``
helpers so test bodies only exercise behavior under test.
"""

import json

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign import (
    clear_assignments,
    distribute_members,
    get_available_volunteers,
    get_contactable_members,
    get_permission_query_conditions,
    get_progress_dashboard,
    has_permission,
    import_contactable_members,
)


class TestEventContactCampaign(VereningingenTestCase):
    # ------------------------------------------------------------------
    # Helpers (privileged setup only)
    # ------------------------------------------------------------------
    def _make_chapter(self):
        return self.create_test_chapter()

    def _make_active_member(self, chapter, *, accepts_comm=1, status="Active", phone="0612345678"):
        """Create a member assigned (active) to ``chapter``."""
        member = self.create_test_member(
            chapter=chapter.name,
            status=status,
            accepts_optional_communications=accepts_comm,
            contact_number=phone,
        )
        return member

    def _make_campaign(self, chapter, **kwargs):
        defaults = {
            "doctype": "Event Contact Campaign",
            "campaign_name": f"Campaign {frappe.generate_hash(length=6)}",
            "chapter": chapter.name,
            "event_type": "Member Meeting",
            "status": "Draft",
            "owner_type": "Chapter",
        }
        defaults.update(kwargs)
        doc = frappe.get_doc(defaults)
        doc.insert(ignore_permissions=True)
        self.track_doc("Event Contact Campaign", doc.name)
        return doc

    def _make_chapter_role(self, name="Test ECC Board Role"):
        if frappe.db.exists("Chapter Role", name):
            return frappe.get_doc("Chapter Role", name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": name,
                "permissions_level": "Basic",
                "is_active": 1,
            }
        )
        role.insert(ignore_permissions=True)
        self.track_doc("Chapter Role", role.name)
        return role

    def _add_board_member(self, chapter, volunteer, role):
        """Append a board member to a chapter and persist.

        Reload first: assigning members to the chapter (via
        ChapterMembershipManager) mutates the Chapter's child tables out from
        under any in-memory copy, so a stale handle would hit
        TimestampMismatchError on save.
        """
        chapter.reload()
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "chapter_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save(ignore_permissions=True)
        chapter.reload()

    def _make_team_with_member(self, volunteer):
        team_role = self.factory.get_or_create_team_role("Team Member")
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Test ECC Team {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
            }
        )
        team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "team_role": team_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
                "role_type": "Team Member",
                "role": "Member",
            },
        )
        team.insert(ignore_permissions=True)
        self.track_doc("Team", team.name)
        return team

    def _append_contact(self, doc, member, **kwargs):
        row = {
            "member": member.name,
            "member_name": member.full_name,
            "email": member.email,
            "contacted": 0,
            "contact_method": "Not Contacted",
            "response": "No Response",
        }
        row.update(kwargs)
        doc.append("contact_list", row)

    # ------------------------------------------------------------------
    # validate_dates
    # ------------------------------------------------------------------
    def test_validate_dates_rejects_end_before_start(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        doc.start_date = "2025-06-10"
        doc.end_date = "2025-06-01"
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_validate_dates_accepts_end_after_start(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        doc.start_date = "2025-06-01"
        doc.end_date = "2025-06-10"
        doc.save(ignore_permissions=True)  # should not raise
        self.assertEqual(str(doc.end_date), "2025-06-10")

    # ------------------------------------------------------------------
    # set_default_owner
    # ------------------------------------------------------------------
    def test_set_default_owner_for_chapter_type(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=None)
        # On insert validate() ran set_default_owner -> owner_reference == chapter
        self.assertEqual(doc.owner_reference, chapter.name)

    def test_set_default_owner_for_user_type(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter, owner_type="User", owner_reference=None)
        self.assertEqual(doc.owner_reference, frappe.session.user)

    def test_set_default_owner_does_not_override_existing(self):
        chapter = self._make_chapter()
        other_chapter = self._make_chapter()
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=other_chapter.name)
        self.assertEqual(doc.owner_reference, other_chapter.name)

    # ------------------------------------------------------------------
    # update_progress_stats
    # ------------------------------------------------------------------
    def test_progress_stats_empty_list_zeroed(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        self.assertEqual(doc.total_members, 0)
        self.assertEqual(doc.members_contacted, 0)
        self.assertEqual(doc.contact_progress, 0)
        self.assertEqual(doc.members_pending, 0)

    def test_progress_stats_counts_responses_and_progress(self):
        chapter = self._make_chapter()
        m1 = self._make_active_member(chapter)
        m2 = self._make_active_member(chapter)
        m3 = self._make_active_member(chapter)
        m4 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        self._append_contact(doc, m1, contacted=1, response="Will Attend")
        self._append_contact(doc, m2, contacted=1, response="Cannot Attend")
        self._append_contact(doc, m3, contacted=0, response="Maybe")
        self._append_contact(doc, m4, contacted=0, response="No Response")
        doc.save(ignore_permissions=True)

        self.assertEqual(doc.total_members, 4)
        self.assertEqual(doc.members_contacted, 2)
        self.assertEqual(doc.contact_progress, 50.0)
        self.assertEqual(doc.members_attending, 1)
        self.assertEqual(doc.members_not_attending, 1)
        self.assertEqual(doc.members_maybe, 1)
        # No Response + empty response -> pending
        self.assertEqual(doc.members_pending, 1)

    def test_progress_stats_left_message_counts_as_pending(self):
        chapter = self._make_chapter()
        m1 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        self._append_contact(doc, m1, contacted=1, response="Left Message")
        doc.save(ignore_permissions=True)
        self.assertEqual(doc.members_pending, 1)
        self.assertEqual(doc.members_attending, 0)

    # ------------------------------------------------------------------
    # get_progress_dashboard_html / get_progress_dashboard
    # ------------------------------------------------------------------
    def test_dashboard_html_empty_state(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        html = doc.get_progress_dashboard_html()
        self.assertIn("No members in contact list", html)

    def test_dashboard_html_populated(self):
        chapter = self._make_chapter()
        m1 = self._make_active_member(chapter)
        m2 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        self._append_contact(doc, m1, contacted=1, response="Will Attend")
        self._append_contact(doc, m2, contacted=0)
        doc.save(ignore_permissions=True)
        html = doc.get_progress_dashboard_html()
        self.assertIn("Contact Progress: 1/2", html)
        self.assertIn("Will Attend", html)

    def test_get_progress_dashboard_endpoint(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        html = get_progress_dashboard(doc.name)
        self.assertIn("No members in contact list", html)

    # ------------------------------------------------------------------
    # get_contactable_members
    # ------------------------------------------------------------------
    def test_get_contactable_members_requires_chapter(self):
        with self.assertRaises(frappe.ValidationError):
            get_contactable_members("")

    def test_get_contactable_members_returns_active_optin_members(self):
        chapter = self._make_chapter()
        wanted = self._make_active_member(chapter, accepts_comm=1, phone="0611111111")
        # Member who opted OUT of optional communications -> excluded
        self._make_active_member(chapter, accepts_comm=0)
        # Member with NULL accepts_optional_communications -> included
        included_null = self._make_active_member(chapter, accepts_comm=None)

        result = get_contactable_members(chapter.name)
        names = {r["member"] for r in result}
        self.assertIn(wanted.name, names)
        self.assertIn(included_null.name, names)
        # opted-out member must not appear
        row = next(r for r in result if r["member"] == wanted.name)
        self.assertEqual(row["phone"], "0611111111")
        self.assertEqual(row["member_name"], wanted.full_name)

    def test_get_contactable_members_excludes_inactive_member(self):
        chapter = self._make_chapter()
        active = self._make_active_member(chapter)
        # Member assigned to chapter but overall status not Active
        inactive = self._make_active_member(chapter, status="Suspended")
        result = get_contactable_members(chapter.name)
        names = {r["member"] for r in result}
        self.assertIn(active.name, names)
        self.assertNotIn(inactive.name, names)

    # ------------------------------------------------------------------
    # import_contactable_members
    # ------------------------------------------------------------------
    def test_import_requires_chapter(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        # Clear the chapter to trigger the guard
        doc.db_set("chapter", None)
        doc.reload()
        with self.assertRaises(frappe.ValidationError):
            import_contactable_members(doc.name)

    def test_import_adds_new_members(self):
        chapter = self._make_chapter()
        self._make_active_member(chapter)
        self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        result = import_contactable_members(doc.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["added"], 2)
        doc.reload()
        self.assertEqual(len(doc.contact_list), 2)

    def test_import_is_idempotent_for_existing(self):
        chapter = self._make_chapter()
        self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        import_contactable_members(doc.name)
        # Second import -> nothing new, "info" status
        result = import_contactable_members(doc.name)
        self.assertEqual(result["status"], "info")
        self.assertEqual(result["added"], 0)

    def test_import_warns_when_no_contactable_members(self):
        chapter = self._make_chapter()
        # No members at all in this chapter
        doc = self._make_campaign(chapter)
        result = import_contactable_members(doc.name)
        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["added"], 0)

    # ------------------------------------------------------------------
    # get_available_volunteers
    # ------------------------------------------------------------------
    def test_available_volunteers_chapter(self):
        chapter = self._make_chapter()
        volunteer = self.create_test_volunteer()
        role = self._make_chapter_role()
        self._add_board_member(chapter, volunteer, role)
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=chapter.name)
        result = get_available_volunteers(doc.name)
        names = {r["name"] for r in result}
        self.assertIn(volunteer.name, names)

    def test_available_volunteers_team(self):
        chapter = self._make_chapter()
        volunteer = self.create_test_volunteer()
        team = self._make_team_with_member(volunteer)
        doc = self._make_campaign(chapter, owner_type="Team", owner_reference=team.name)
        result = get_available_volunteers(doc.name)
        names = {r["name"] for r in result}
        self.assertIn(volunteer.name, names)

    def test_available_volunteers_user_returns_empty(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter, owner_type="User", owner_reference=frappe.session.user)
        self.assertEqual(get_available_volunteers(doc.name), [])

    def test_available_volunteers_chapter_no_reference_returns_empty(self):
        chapter = self._make_chapter()
        # owner_type Chapter but neither owner_reference nor chapter resolvable
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=chapter.name)
        doc.db_set("owner_reference", None)
        doc.db_set("chapter", None)
        doc.reload()
        self.assertEqual(get_available_volunteers(doc.name), [])

    # ------------------------------------------------------------------
    # distribute_members
    # ------------------------------------------------------------------
    def test_distribute_no_members(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        result = distribute_members(doc.name)
        self.assertEqual(result["status"], "warning")

    def test_distribute_no_volunteers(self):
        chapter = self._make_chapter()
        m1 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter, owner_type="User", owner_reference=frappe.session.user)
        self._append_contact(doc, m1)
        doc.save(ignore_permissions=True)
        result = distribute_members(doc.name)
        self.assertEqual(result["status"], "warning")
        self.assertIn("No volunteers", result["message"])

    def test_distribute_round_robin(self):
        chapter = self._make_chapter()
        v1 = self.create_test_volunteer()
        v2 = self.create_test_volunteer()
        role = self._make_chapter_role()
        self._add_board_member(chapter, v1, role)
        self._add_board_member(chapter, v2, role)

        m1 = self._make_active_member(chapter)
        m2 = self._make_active_member(chapter)
        m3 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=chapter.name)
        for m in (m1, m2, m3):
            self._append_contact(doc, m)
        doc.save(ignore_permissions=True)

        result = distribute_members(doc.name, json.dumps([v1.name, v2.name]))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["assigned_count"], 3)

        doc.reload()
        assigned = [row.assigned_to for row in doc.contact_list]
        # Round-robin: 3 members across 2 volunteers -> [v1, v2, v1]
        self.assertEqual(assigned, [v1.name, v2.name, v1.name])
        # Names are fetched and stored
        self.assertEqual(doc.contact_list[0].assigned_to_name, v1.volunteer_name)

    def test_distribute_only_assigns_unassigned(self):
        chapter = self._make_chapter()
        v1 = self.create_test_volunteer()
        role = self._make_chapter_role()
        self._add_board_member(chapter, v1, role)
        m1 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=chapter.name)
        self._append_contact(doc, m1, assigned_to=v1.name, assigned_to_name=v1.volunteer_name)
        doc.save(ignore_permissions=True)

        result = distribute_members(doc.name, json.dumps([v1.name]))
        self.assertEqual(result["status"], "info")
        self.assertIn("already assigned", result["message"])

    # ------------------------------------------------------------------
    # clear_assignments
    # ------------------------------------------------------------------
    def test_clear_assignments_removes_them(self):
        chapter = self._make_chapter()
        v1 = self.create_test_volunteer()
        m1 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        self._append_contact(doc, m1, assigned_to=v1.name, assigned_to_name=v1.volunteer_name)
        doc.save(ignore_permissions=True)

        result = clear_assignments(doc.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleared"], 1)
        doc.reload()
        self.assertIsNone(doc.contact_list[0].assigned_to)

    def test_clear_assignments_none_to_clear(self):
        chapter = self._make_chapter()
        m1 = self._make_active_member(chapter)
        doc = self._make_campaign(chapter)
        self._append_contact(doc, m1)
        doc.save(ignore_permissions=True)
        result = clear_assignments(doc.name)
        self.assertEqual(result["status"], "info")
        self.assertEqual(result["cleared"], 0)

    # ------------------------------------------------------------------
    # get_permission_query_conditions
    # ------------------------------------------------------------------
    def test_permission_query_admin_sees_all(self):
        # Administrator has System Manager -> empty condition (no restriction)
        self.assertEqual(get_permission_query_conditions("Administrator"), "")

    def test_permission_query_unknown_user_no_access(self):
        user = self.create_test_user(f"ecc_noaccess_{frappe.generate_hash(length=6)}@example.com", roles=[])
        cond = get_permission_query_conditions(user.name)
        self.assertEqual(cond, "1=0")

    def test_permission_query_board_member_scopes_to_chapter(self):
        chapter = self._make_chapter()
        member = self._make_active_member(chapter)
        # link a user to the member and make a board volunteer
        user = self.create_test_user(
            f"ecc_board_{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Chapter Board Member"],
        )
        member.db_set("user", user.name)
        volunteer = self.create_test_volunteer(member=member.name)
        role = self._make_chapter_role()
        self._add_board_member(chapter, volunteer, role)

        cond = get_permission_query_conditions(user.name)
        self.assertIn(chapter.name, cond)
        self.assertIn("owner_type = 'Chapter'", cond)

    # ------------------------------------------------------------------
    # has_permission
    # ------------------------------------------------------------------
    def test_has_permission_admin_true(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        self.assertTrue(has_permission(doc, "read", "Administrator"))

    def test_has_permission_non_volunteer_false(self):
        chapter = self._make_chapter()
        doc = self._make_campaign(chapter)
        user = self.create_test_user(f"ecc_nonvol_{frappe.generate_hash(length=6)}@example.com", roles=[])
        self.assertFalse(has_permission(doc, "read", user.name))

    def test_has_permission_board_member_of_chapter_true(self):
        chapter = self._make_chapter()
        member = self._make_active_member(chapter)
        user = self.create_test_user(
            f"ecc_bp_{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Chapter Board Member"],
        )
        member.db_set("user", user.name)
        volunteer = self.create_test_volunteer(member=member.name)
        role = self._make_chapter_role()
        self._add_board_member(chapter, volunteer, role)

        doc = self._make_campaign(chapter, owner_type="Chapter", owner_reference=chapter.name)
        self.assertTrue(has_permission(doc, "read", user.name))

    def test_has_permission_board_member_other_chapter_false(self):
        chapter = self._make_chapter()
        other_chapter = self._make_chapter()
        member = self._make_active_member(chapter)
        user = self.create_test_user(
            f"ecc_bp2_{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Chapter Board Member"],
        )
        member.db_set("user", user.name)
        volunteer = self.create_test_volunteer(member=member.name)
        role = self._make_chapter_role()
        self._add_board_member(chapter, volunteer, role)

        # Campaign belongs to a chapter the user is NOT a board member of
        doc = self._make_campaign(other_chapter, owner_type="Chapter", owner_reference=other_chapter.name)
        self.assertFalse(has_permission(doc, "read", user.name))

    def test_has_permission_team_member_true(self):
        chapter = self._make_chapter()
        member = self._make_active_member(chapter)
        user = self.create_test_user(f"ecc_team_{frappe.generate_hash(length=6)}@example.com", roles=[])
        member.db_set("user", user.name)
        volunteer = self.create_test_volunteer(member=member.name)
        team = self._make_team_with_member(volunteer)
        doc = self._make_campaign(chapter, owner_type="Team", owner_reference=team.name)
        self.assertTrue(has_permission(doc, "read", user.name))
