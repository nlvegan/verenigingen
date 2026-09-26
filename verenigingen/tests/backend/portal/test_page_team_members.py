"""
Tests for the team members portal page
(verenigingen.templates.pages.team_members).

get_context() (reads the team from frappe.form_dict):
- raises PermissionError for Guest (validate_user_logged_in)
- raises DoesNotExistError when the logged-in user has no Member record
- with no `team` param: shows the team selector + available_teams
- with a `team` param: enforces access (team member / same-chapter / admin),
  otherwise raises PermissionError; on success exposes context.team_members
- _get_available_teams_for_user is exercised too.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages import team_members
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.query_counter import count_queries


class TestTeamMembersPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"team-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Team Page Volunteer"
        )
        # A team the volunteer is an active member of.
        self.team = self.create_test_team(team_name="Members Page Team")
        self.team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "volunteer_name": self.volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        self.team.save()

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Team",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Team", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def _ctx_with_team(self, email, team):
        with self.as_user(email):
            ctx = frappe._dict()
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({"team": team} if team is not None else {})
            try:
                team_members.get_context(ctx)
            finally:
                frappe.form_dict = original
        return ctx

    # ---- get_context branches ------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({})
            try:
                with self.assertRaises(frappe.PermissionError):
                    team_members.get_context(ctx)
            finally:
                frappe.form_dict = original

    def test_user_without_member_record_raises(self):
        nomember = f"team-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": nomember,
                "first_name": "No",
                "last_name": "Member",
                "send_welcome_email": 0,
            }
        ).insert()
        with self.assertRaises(frappe.DoesNotExistError):
            self._ctx_with_team(nomember, None)

    def test_no_team_param_shows_selector(self):
        ctx = self._ctx_with_team(self.user_email, None)
        self.assertTrue(ctx.show_team_selector)
        self.assertTrue(any(t.name == self.team.name for t in ctx.available_teams))

    def test_team_member_can_view_members(self):
        ctx = self._ctx_with_team(self.user_email, self.team.name)
        self.assertEqual(ctx.team.name, self.team.name)
        self.assertTrue(any(tm.volunteer == self.volunteer.name for tm in ctx.team_members))
        # display_name falls back to the fetched volunteer_name
        viewed = next(tm for tm in ctx.team_members if tm.volunteer == self.volunteer.name)
        self.assertEqual(viewed.display_name, self.volunteer.volunteer_name)
        self.assertEqual(ctx.current_user_volunteer, self.volunteer.name)

    def test_outsider_is_denied(self):
        """A member who is neither on the team nor in its chapter is blocked."""
        outsider = f"team-outsider-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(outsider)
        with self.assertRaises(frappe.PermissionError):
            self._ctx_with_team(outsider, self.team.name)

    def test_invalid_team_raises(self):
        with self.assertRaises(frappe.PermissionError):
            self._ctx_with_team(self.user_email, "Nonexistent-Team-XYZ")

    def test_unknown_and_foreign_team_return_identical_refusal(self):
        # #1386: an unknown team id and an existing-but-foreign one must be
        # indistinguishable to the caller -- same exception type and message, on
        # both paths. Before the fix, an unknown id raised DoesNotExistError
        # ("Team not found") via validate_entity_exists() while a foreign id
        # raised a differently-worded PermissionError later, once frappe.get_doc
        # had already loaded the document -- an existence oracle over Team ids.
        outsider = f"team-outsider2-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(outsider)

        def _refusal(team_value):
            with self.as_user(outsider):
                ctx = frappe._dict()
                original = frappe.form_dict
                frappe.form_dict = frappe._dict({"team": team_value})
                try:
                    with self.assertRaises(frappe.PermissionError) as cm:
                        team_members.get_context(ctx)
                finally:
                    frappe.form_dict = original
            return str(cm.exception)

        unknown_message = _refusal("Nonexistent-Team-XYZ")
        foreign_message = _refusal(self.team.name)

        self.assertEqual(
            unknown_message,
            foreign_message,
            "unknown-team and foreign-team refusals must render the same message",
        )

    def test_unknown_and_foreign_team_refusals_cost_the_same_queries(self):
        # #1402: #1386 made the two refusals byte-identical in message and
        # exception type, but the *query count* still distinguished them --
        # the Chapter Member existence check only ran once team_data resolved
        # truthy, so a real-but-foreign team (with a chapter) cost one more
        # SQL call than an unknown id. Same class as #1341/#1367: a refusal's
        # cost must not depend on whether the resource exists.
        chapter = self.create_test_chapter(chapter_name="Team Query Parity Chapter")
        self.team.db_set("chapter", chapter.name)

        outsider = f"team-outsider3-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(outsider)

        def _call(team_value):
            with self.as_user(outsider):
                ctx = frappe._dict()
                original = frappe.form_dict
                frappe.form_dict = frappe._dict({"team": team_value})
                try:
                    with self.assertRaises(frappe.PermissionError):
                        team_members.get_context(ctx)
                finally:
                    frappe.form_dict = original

        def _refusal_query_count(team_value):
            with count_queries() as ctr:
                _call(team_value)
            return len(ctr.queries)

        # Warm meta/role/permission caches on BOTH paths first: cold caches (Team
        # meta, role lists, permission query conditions) add SQL noise that has
        # nothing to do with the code path under test, and would swamp a 1-query
        # residue with unrelated first-call cost.
        _call("Nonexistent-Team-XYZ")
        _call(self.team.name)

        unknown_count = _refusal_query_count("Nonexistent-Team-XYZ")
        foreign_count = _refusal_query_count(self.team.name)

        self.assertEqual(
            unknown_count,
            foreign_count,
            "an unknown team id and a real-but-foreign one (with a chapter) must "
            "issue the same number of queries on refusal, or the query count is "
            "itself an existence oracle behind the identical message",
        )

    def test_orphaned_null_parent_row_does_not_grant_access(self):
        # #1426 (found reviewing #1402's fix): {"parent": None} in an exists()
        # filter compiles to `parent IS NULL`, not to an inert/impossible value.
        # `parent` is nullable on both Team Member and Chapter Member, so an
        # orphaned child row with parent IS NULL -- a corrupt state that should
        # never occur, but the column allows it -- would satisfy the Chapter
        # Member existence check for ANY team whose chapter link resolves to
        # None: an unknown team id, or (as here) a real, chapterless team like
        # veg11's Kascommissie/Secretariaat. That would wrongly grant access to
        # whichever member the orphan row references.
        outsider = f"team-outsider4-{frappe.generate_hash()[:8]}@test.invalid"
        outsider_member = self._make_member_with_user(outsider)
        self.assertIsNone(self.team.chapter, "fixture team must be chapterless for this to be meaningful")

        orphan_name = frappe.generate_hash()[:20]
        frappe.db.sql(
            """
            INSERT INTO `tabChapter Member`
                (name, creation, modified, modified_by, owner, docstatus, idx,
                 parent, parentfield, parenttype, member, enabled, status)
            VALUES
                (%(name)s, NOW(), NOW(), 'Administrator', 'Administrator', 0, 0,
                 NULL, 'members', 'Chapter', %(member)s, 1, 'Active')
            """,
            {"name": orphan_name, "member": outsider_member.name},
        )
        try:
            self.assertEqual(
                frappe.db.sql(
                    "SELECT COUNT(*) FROM `tabChapter Member` WHERE name=%s AND parent IS NULL",
                    orphan_name,
                )[0][0],
                1,
                "orphan row must actually have parent IS NULL, or this test proves nothing",
            )

            with self.as_user(outsider):
                ctx = frappe._dict()
                original = frappe.form_dict

                # A real, chapterless team: the orphan's NULL parent must not
                # be mistaken for "this team's chapter".
                frappe.form_dict = frappe._dict({"team": self.team.name})
                try:
                    with self.assertRaises(frappe.PermissionError):
                        team_members.get_context(ctx)
                finally:
                    frappe.form_dict = original

                # An unknown team id: same requirement, for completeness.
                frappe.form_dict = frappe._dict({"team": "Nonexistent-Team-XYZ"})
                try:
                    with self.assertRaises(frappe.PermissionError):
                        team_members.get_context(ctx)
                finally:
                    frappe.form_dict = original
        finally:
            frappe.db.sql("DELETE FROM `tabChapter Member` WHERE name=%s", orphan_name)

    # ---- _get_available_teams_for_user ---------------------------------

    def test_available_teams_for_member(self):
        teams = team_members._get_available_teams_for_user(self.user_email, self.member.name)
        self.assertTrue(any(t.name == self.team.name for t in teams))

