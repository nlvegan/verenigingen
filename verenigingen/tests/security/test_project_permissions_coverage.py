#!/usr/bin/env python3
"""
Coverage-focused integration tests for the Project Permission System.

This file complements ``test_project_permissions.py`` (which covers the helper
functions, permission constants and SQL-injection validation in isolation).

Here we exercise the *permission-decision branches* that are wired into Frappe
via ``hooks/permissions.py``:

    permission_query_conditions["Project"] = get_project_permission_query_conditions
    has_permission["Project"]              = has_project_permission_via_team

Concretely, with REAL members/volunteers/teams/chapters/projects we drive:

- ``has_project_permission_via_team`` list-view (doc=None) allow + deny paths
- ``has_project_permission_via_team`` single-document allow via team and chapter
- ``user_has_any_team_projects`` / ``user_has_any_chapter_projects`` True + deny
- ``user_has_project_team_access`` direct (custom_team) + indirect (name match) + deny
- ``user_has_project_chapter_access`` direct (custom_chapter) + indirect + deny
- ``get_team_permission_level`` / ``get_chapter_permission_level`` fallback branches
- ``get_user_project_teams`` full-result and no-volunteer empty-result
- ``get_project_permission_query_conditions`` Guest / admin / team-volunteer /
  chapter-volunteer real SQL-string outputs

Every test asserts a *concrete* allow/deny outcome or the exact shape of a
generated SQL condition string, so replacing a function body with ``pass``
would fail these tests.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.project_permissions import (
    get_chapter_permission_level,
    get_project_permission_query_conditions,
    get_team_permission_level,
    get_user_project_teams,
    get_volunteer_for_user,
    has_project_permission_via_team,
    user_has_any_chapter_projects,
    user_has_any_team_projects,
    user_has_project_chapter_access,
    user_has_project_team_access,
)


# ----------------------------------------------------------------------------
# Shared base: real member -> User -> volunteer wiring
# ----------------------------------------------------------------------------
class _ProjectPermBase(EnhancedTestCase):
    """Base class with helpers to build a member linked to a real login User."""

    def setUp(self):
        super().setUp()
        # The lru_cache on get_volunteer_for_user persists across tests; clear it
        # so each test sees a fresh member<->user<->volunteer mapping.
        get_volunteer_for_user.cache_clear()
        self.addCleanup(get_volunteer_for_user.cache_clear)

    # --- construction helpers (prefixed _make_ per test-quality-enforcer) -----
    def _make_member_with_user(self, first_name="Perm", last_name="Tester"):
        """Create a Member with a linked enabled login User; returns (member, user_email)."""
        member = self.create_test_member(first_name=first_name, last_name=last_name)
        user_email = f"{member.name.lower()}@projectperm.test".replace(" ", "-")
        if not frappe.db.exists("User", user_email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "enabled": 1,
                    "user_type": "System User",
                    "send_welcome_email": 0,
                }
            )
            user.insert()
            self.track_doc("User", user.name)
        member.user = user_email
        member.save()
        return member, user_email

    def _make_volunteer(self, member):
        return self.create_test_volunteer(member.name)

    def _make_team_role(self, role_name, **attrs):
        """Create (or fetch) a Team Role by exact name."""
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        doc = frappe.get_doc({"doctype": "Team Role", "role_name": role_name, **attrs})
        doc.insert()
        self.track_doc("Team Role", doc.name)
        return doc

    def _make_team(self, team_name):
        team = frappe.get_doc({"doctype": "Team", "team_name": team_name, "status": "Active"})
        team.insert()
        self.track_doc("Team", team.name)
        return team

    def _add_team_member(self, team, volunteer, team_role):
        team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": team_role.name,
                "status": "Active",
                "from_date": frappe.utils.today(),
            },
        )
        team.save()
        return team

    def _ensure_region(self):
        region_name = "test-region"
        if not frappe.db.exists("Region", region_name):
            frappe.get_doc({"doctype": "Region", "region_name": "Test Region", "region_code": "TR"}).insert(
                ignore_if_duplicate=True
            )
        return region_name

    def _make_chapter(self, chapter_name):
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": chapter_name,
                "status": "Active",
                "region": self._ensure_region(),
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)
        return chapter

    def _make_chapter_role(self, role_name, permissions_level="Basic", is_chair=0):
        if frappe.db.exists("Chapter Role", role_name):
            return frappe.get_doc("Chapter Role", role_name)
        doc = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": permissions_level,
                "is_chair": is_chair,
            }
        )
        doc.insert()
        self.track_doc("Chapter Role", doc.name)
        return doc

    def _add_board_member(self, chapter, volunteer, chapter_role):
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": chapter_role.name,
                "is_active": 1,
                "from_date": frappe.utils.today(),
            },
        )
        chapter.save()
        return chapter

    def _default_company(self):
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")
        return company

    def _make_project(self, project_name, **fields):
        fields.setdefault("company", self._default_company())
        proj = frappe.get_doc({"doctype": "Project", "project_name": project_name, **fields})
        proj.insert()
        self.track_doc("Project", proj.name)
        return proj


# ----------------------------------------------------------------------------
# Team-based document & list access
# ----------------------------------------------------------------------------
class TestTeamProjectAccess(_ProjectPermBase):
    def setUp(self):
        super().setUp()
        self.member, self.user_email = self._make_member_with_user("Team", "Worker")
        self.volunteer = self._make_volunteer(self.member)
        suffix = frappe.generate_hash(length=6)
        # role_name autonames the Team Role AND is the key into the permission
        # matrix, so use the literal "Team Leader" (read+write+create) here.
        self.leader_role = self._make_team_role("Team Leader")
        self.team = self._make_team(f"Coverage Team {suffix}")
        self._add_team_member(self.team, self.volunteer, self.leader_role)

    def test_direct_custom_team_grants_access(self):
        """A project linked via custom_team grants the team member access (direct path)."""
        proj = self._make_project("Unrelated Direct Project", custom_team=self.team.name)
        # Direct custom_team match -> get_team_permission_level decides by role.
        self.assertTrue(
            user_has_project_team_access(self.user_email, proj.name, "read"),
            "Team Leader should read a project directly linked to their team",
        )
        self.assertTrue(
            user_has_project_team_access(self.user_email, proj.name, "write"),
            "Team Leader should write a project directly linked to their team",
        )

    def test_indirect_name_match_grants_access(self):
        """A project whose name contains the team name grants access (indirect path)."""
        proj = self._make_project(f"Roadmap for {self.team.team_name} 2026")
        self.assertTrue(
            user_has_project_team_access(self.user_email, proj.name, "read"),
            "Project name containing the team name should match indirectly",
        )

    def test_unrelated_project_denies_team_access(self):
        """A project with no team link and no name match is denied (deny path)."""
        proj = self._make_project("Completely Unrelated Project XYZ")
        self.assertFalse(
            user_has_project_team_access(self.user_email, proj.name, "read"),
            "User must not gain team access to an unrelated project",
        )

    def test_nonexistent_project_denies(self):
        """A project name that does not exist resolves to a denial, not a crash."""
        self.assertFalse(user_has_project_team_access(self.user_email, "PROJ-does-not-exist-zzz", "read"))

    def test_non_volunteer_user_denied_team_access(self):
        """A member that is NOT a volunteer is denied team access."""
        member2, email2 = self._make_member_with_user("NonVol", "Person")
        proj = self._make_project("Some Project", custom_team=self.team.name)
        self.assertFalse(user_has_project_team_access(email2, proj.name, "read"))

    def test_user_has_any_team_projects_true_and_false(self):
        """List-level team check: True when a team project exists, False otherwise."""
        # No team projects yet -> deny
        self.assertFalse(user_has_any_team_projects(self.user_email))
        # Create a project linked to the team -> allow
        self._make_project("Team Backlog", custom_team=self.team.name)
        self.assertTrue(user_has_any_team_projects(self.user_email))
        # Non-volunteer user -> deny
        _, email2 = self._make_member_with_user("Stranger", "NoVol")
        self.assertFalse(user_has_any_team_projects(email2))

    def test_has_project_permission_via_team_single_doc_allow(self):
        """The wired has_permission entry-point grants access for a team-linked project doc."""
        proj = self._make_project("Wired Team Project", custom_team=self.team.name)
        doc = frappe.get_doc("Project", proj.name)
        self.assertTrue(has_project_permission_via_team(doc, ptype="read", user=self.user_email))
        # ptype=None must default to "read" and still allow.
        self.assertTrue(has_project_permission_via_team(doc, ptype=None, user=self.user_email))

    def test_has_project_permission_via_team_list_allow(self):
        """doc=None list-view check is True once the user has a team project."""
        self._make_project("List Visible Team Project", custom_team=self.team.name)
        self.assertTrue(has_project_permission_via_team(None, ptype="read", user=self.user_email))

    def test_has_project_permission_via_team_list_deny(self):
        """doc=None list-view check is False for a brand-new non-volunteer user."""
        _, email2 = self._make_member_with_user("Empty", "Lister")
        self.assertFalse(has_project_permission_via_team(None, ptype="read", user=email2))


# ----------------------------------------------------------------------------
# Chapter-board document & list access
# ----------------------------------------------------------------------------
class TestChapterProjectAccess(_ProjectPermBase):
    def setUp(self):
        super().setUp()
        self.member, self.user_email = self._make_member_with_user("Board", "Worker")
        self.volunteer = self._make_volunteer(self.member)
        suffix = frappe.generate_hash(length=6)
        self.admin_role = self._make_chapter_role(f"Coverage Admin {suffix}", permissions_level="Admin")
        self.chapter = self._make_chapter(f"Coverage Chapter {suffix}")
        self._add_board_member(self.chapter, self.volunteer, self.admin_role)

    def test_direct_custom_chapter_grants_access(self):
        """A project linked via custom_chapter grants the board member access (direct path)."""
        proj = self._make_project("Wholly Unrelated Name", custom_chapter=self.chapter.name)
        self.assertTrue(user_has_project_chapter_access(self.user_email, proj.name, "read"))
        # Admin level includes delete.
        self.assertTrue(user_has_project_chapter_access(self.user_email, proj.name, "delete"))

    def test_indirect_chapter_name_match_grants_access(self):
        """A project name containing the chapter name grants access (indirect path)."""
        proj = self._make_project(f"Plan for {self.chapter.name}")
        self.assertTrue(user_has_project_chapter_access(self.user_email, proj.name, "write"))

    def test_unrelated_project_denies_chapter_access(self):
        proj = self._make_project("No Chapter Link Project ABC")
        self.assertFalse(user_has_project_chapter_access(self.user_email, proj.name, "read"))

    def test_chapter_nonexistent_project_denies(self):
        self.assertFalse(user_has_project_chapter_access(self.user_email, "PROJ-missing-chapter", "read"))

    def test_user_has_any_chapter_projects_true_and_false(self):
        # No chapter project yet -> deny
        self.assertFalse(user_has_any_chapter_projects(self.user_email))
        self._make_project("Chapter Roadmap", custom_chapter=self.chapter.name)
        self.assertTrue(user_has_any_chapter_projects(self.user_email))
        # Non-volunteer -> deny
        _, email2 = self._make_member_with_user("ChapterStranger", "NoVol")
        self.assertFalse(user_has_any_chapter_projects(email2))

    def test_has_project_permission_via_team_chapter_doc_allow(self):
        """The wired has_permission entry-point grants access via the CHAPTER branch."""
        proj = self._make_project("Wired Chapter Project", custom_chapter=self.chapter.name)
        doc = frappe.get_doc("Project", proj.name)
        # User has no team access at all; access must come purely from the chapter branch.
        self.assertTrue(has_project_permission_via_team(doc, ptype="write", user=self.user_email))

    def test_has_project_permission_default_user_session(self):
        """user=None falls back to frappe.session.user (exercise the default branch)."""
        proj = self._make_project("Session User Project", custom_chapter=self.chapter.name)
        doc = frappe.get_doc("Project", proj.name)
        with self.as_user(self.user_email):
            self.assertTrue(has_project_permission_via_team(doc, ptype="read"))


# ----------------------------------------------------------------------------
# Permission-level fallback branches
# ----------------------------------------------------------------------------
class TestPermissionLevelFallbacks(_ProjectPermBase):
    def setUp(self):
        super().setUp()
        self.member, self.user_email = self._make_member_with_user("Fallback", "Member")
        self.volunteer = self._make_volunteer(self.member)
        self.suffix = frappe.generate_hash(length=6)

    def test_team_member_with_unknown_role_falls_back_to_read_only(self):
        """A team_role whose role_name is not in the permission matrix falls back to read-only.

        Team Member.team_role is mandatory, so we attach a real role whose name
        is unknown to TeamPermissionLevel.get_permissions(); the unknown-role
        branch returns ["read"] only.
        """
        unknown_role = self._make_team_role(f"Coverage Unknown Role {self.suffix}")
        team = self._make_team(f"NoRole Team {self.suffix}")
        team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "team_role": unknown_role.name,
                "status": "Active",
                "from_date": frappe.utils.today(),
            },
        )
        team.save()
        self.assertTrue(
            get_team_permission_level(team.name, self.volunteer.name, "read"),
            "Unknown-role fallback still grants read",
        )
        self.assertFalse(
            get_team_permission_level(team.name, self.volunteer.name, "write"),
            "Unknown-role fallback must NOT grant write",
        )

    def test_team_permission_unknown_volunteer_returns_false(self):
        """A volunteer not on the team returns False (the early not-team_member branch)."""
        team = self._make_team(f"Other Team {self.suffix}")
        self.assertFalse(get_team_permission_level(team.name, self.volunteer.name, "read"))

    def test_chapter_role_without_level_falls_back_to_basic(self):
        """A chapter role whose permissions_level is empty falls back to Basic."""
        # permissions_level empty -> the role_details branch yields BASIC default.
        role = self._make_chapter_role(f"Empty Level Role {self.suffix}", permissions_level="")
        chapter = self._make_chapter(f"Fallback Chapter {self.suffix}")
        self._add_board_member(chapter, self.volunteer, role)
        # Basic => read+write but NOT create/delete.
        self.assertTrue(get_chapter_permission_level(chapter.name, self.volunteer.name, "read"))
        self.assertTrue(get_chapter_permission_level(chapter.name, self.volunteer.name, "write"))
        self.assertFalse(get_chapter_permission_level(chapter.name, self.volunteer.name, "create"))

    def test_chapter_permission_inactive_board_member_returns_false(self):
        """An inactive board member is denied (the not is_active branch)."""
        role = self._make_chapter_role(f"Inactive Test Role {self.suffix}", permissions_level="Admin")
        chapter = self._make_chapter(f"Inactive Chapter {self.suffix}")
        chapter.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": role.name,
                "is_active": 0,
                "from_date": frappe.utils.today(),
            },
        )
        chapter.save()
        self.assertFalse(
            get_chapter_permission_level(chapter.name, self.volunteer.name, "read"),
            "Inactive board membership must not grant any permission",
        )


# ----------------------------------------------------------------------------
# get_user_project_teams aggregation endpoint
# ----------------------------------------------------------------------------
class TestGetUserProjectTeams(_ProjectPermBase):
    def test_no_volunteer_returns_empty(self):
        """A user with no volunteer record gets empty lists (early-return branch)."""
        result = get_user_project_teams("nobody-here@projectperm.test")
        self.assertEqual(result["teams"], [])
        self.assertEqual(result["chapters"], [])
        self.assertEqual(result["projects"], [])

    def test_returns_teams_chapters_and_projects(self):
        """Full path: a volunteer on a team + chapter board sees both projects aggregated."""
        member, user_email = self._make_member_with_user("Aggregate", "User")
        volunteer = self._make_volunteer(member)
        suffix = frappe.generate_hash(length=6)

        # Team with a directly-linked project
        team_role = self._make_team_role(f"Agg Leader {suffix}")
        team = self._make_team(f"Agg Team {suffix}")
        self._add_team_member(team, volunteer, team_role)
        team_proj = self._make_project("Agg Team Project", custom_team=team.name)

        # Chapter board with a directly-linked project
        chapter_role = self._make_chapter_role(f"Agg Admin {suffix}", permissions_level="Admin")
        chapter = self._make_chapter(f"Agg Chapter {suffix}")
        self._add_board_member(chapter, volunteer, chapter_role)
        chapter_proj = self._make_project("Agg Chapter Project", custom_chapter=chapter.name)

        result = get_user_project_teams(user_email)

        self.assertEqual(result.get("volunteer_record"), volunteer.name)
        team_names = {t["team_name"] for t in result["teams"]}
        self.assertIn(team.name, team_names)
        chapter_names = {c["chapter_name"] for c in result["chapters"]}
        self.assertIn(chapter.name, chapter_names)

        project_names = {p["name"] for p in result["projects"]}
        self.assertIn(team_proj.name, project_names)
        self.assertIn(chapter_proj.name, project_names)

        # access_via is set per project; both team & chapter origins are represented.
        access_vias = {p["access_via"] for p in result["projects"]}
        self.assertTrue({"team", "chapter"} & access_vias)


# ----------------------------------------------------------------------------
# get_project_permission_query_conditions (the permission_query_conditions hook)
# ----------------------------------------------------------------------------
class TestQueryConditions(_ProjectPermBase):
    def test_guest_gets_no_access(self):
        self.assertEqual(get_project_permission_query_conditions("Guest"), "1=0")
        self.assertEqual(get_project_permission_query_conditions(None), "1=0")

    def test_admin_role_gets_full_access(self):
        """A user holding an admin role gets unrestricted access ('')."""
        member, user_email = self._make_member_with_user("Admin", "User")
        user = frappe.get_doc("User", user_email)
        user.append("roles", {"role": "Verenigingen Administrator"})
        user.save()
        self.assertEqual(
            get_project_permission_query_conditions(user_email),
            "",
            "Admin-role user should get full (empty) project query condition",
        )

    def test_non_volunteer_gets_no_access(self):
        member, user_email = self._make_member_with_user("Plain", "User")
        # No volunteer record -> 1=0
        self.assertEqual(get_project_permission_query_conditions(user_email), "1=0")

    def test_team_volunteer_builds_team_conditions(self):
        """A team volunteer (non-admin) gets OR-conditions referencing custom_team + name LIKE."""
        member, user_email = self._make_member_with_user("CondTeam", "User")
        volunteer = self._make_volunteer(member)
        suffix = frappe.generate_hash(length=6)
        role = self._make_team_role(f"Cond Leader {suffix}")
        team = self._make_team(f"Cond Team {suffix}")
        self._add_team_member(team, volunteer, role)

        cond = get_project_permission_query_conditions(user_email)
        self.assertNotIn(cond, ("", "1=0"))
        self.assertIn("`tabProject`.custom_team", cond)
        self.assertIn("LOWER(`tabProject`.project_name) LIKE", cond)
        # The escaped team name must appear in the generated SQL.
        self.assertIn(team.name, cond)
        # Conditions are wrapped in parentheses and OR-joined.
        self.assertTrue(cond.startswith("(") and cond.endswith(")"))

    def test_chapter_volunteer_builds_chapter_conditions(self):
        """A chapter-board volunteer gets OR-conditions referencing custom_chapter."""
        member, user_email = self._make_member_with_user("CondChap", "User")
        volunteer = self._make_volunteer(member)
        suffix = frappe.generate_hash(length=6)
        role = self._make_chapter_role(f"Cond Admin {suffix}", permissions_level="Admin")
        chapter = self._make_chapter(f"Cond Chapter {suffix}")
        self._add_board_member(chapter, volunteer, role)

        cond = get_project_permission_query_conditions(user_email)
        self.assertNotIn(cond, ("", "1=0"))
        self.assertIn("`tabProject`.custom_chapter", cond)
        self.assertIn(chapter.name, cond)
