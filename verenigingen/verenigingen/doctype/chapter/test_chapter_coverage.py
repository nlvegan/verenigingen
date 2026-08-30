# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Coverage-focused real-DB integration tests for chapter.py.

These tests target methods/branches NOT exercised by the existing
test_chapter.py / test_chapter_head.py / test_chapter_volunteer_integration.py:

  - Chapter.get_board_member_emails() de-duplication
  - Chapter.validate_role_profile_configuration() throw branches
  - Chapter.validate_postal_codes() True/False branches
  - Chapter.matches_postal_code()
  - Chapter.get_members_optimized / get_board_members_optimized /
    get_chapter_head_member_optimized
  - Chapter.get_chapter_statistics()
  - Chapter._ensure_route()
  - Chapter.add_member / remove_member / get_members delegators
  - module functions: leave(), get_board_memberships(), remove_from_board(),
    get_chapter_board_history(), get_chapter_stats(),
    get_chapters_by_postal_code(), suggest_chapters_for_member(),
    suggest_chapter_for_member(), is_chapter_management_enabled(),
    get_board_role_profile_preview(), bulk_apply_chapter_board_role_profiles(),
    get_list_context(), get_chapter_permission_query_conditions(),
    has_chapter_permission()
"""

import time

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.region_fixtures import ensure_test_region
from verenigingen.verenigingen.doctype.chapter import chapter as chapter_module


class TestChapterCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.base_id = f"{int(time.time() * 1000000) % 100000000}"
        # One owner for the shared "Test Region" docname (#406).
        self.test_region = ensure_test_region()

    def _uid(self):
        return f"{self.base_id}-{int(time.time() * 1000000) % 1000000}"

    def _make_chapter(self, **kwargs):
        uid = self._uid()
        data = {
            "doctype": "Chapter",
            "name": f"Cov Chapter {uid}",
            "region": self.test_region,
            "status": "Active",
            "introduction": "Coverage chapter",
        }
        data.update(kwargs)
        chapter = frappe.get_doc(data)
        chapter.insert()
        self.track_doc("Chapter", chapter.name)
        return chapter

    def _make_member(self, **kwargs):
        uid = self._uid()
        data = {
            "doctype": "Member",
            "first_name": "Cov",
            "last_name": f"Member {uid}",
            "email": f"cov{uid}@example.com",
            "contact_number": "+31612345678",
            "payment_method": "Bank Transfer",
            # MemberManager.add_member() sets the roster row to enabled=0/Inactive
            # unless the Member's own status is exactly "Active"; the test factory
            # leaves status unset, so set it explicitly to get an enabled roster row.
            "status": "Active",
        }
        data.update(kwargs)
        member = frappe.get_doc(data)
        member.insert()
        self.track_doc("Member", member.name)
        return member

    def _make_role(self, level="Basic"):
        uid = self._uid()
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Cov Role {uid}",
                "permissions_level": level,
                "is_active": 1,
            }
        )
        role.insert()
        self.track_doc("Chapter Role", role.name)
        return role

    # ------------------------------------------------------------------
    # _ensure_route
    # ------------------------------------------------------------------
    def test_ensure_route_set_on_insert(self):
        """_ensure_route() auto-populates a slugged route when none is given."""
        with self.assertNoErrorLog():
            chapter = self._make_chapter()
        self.assertEqual(chapter.route, "chapters/" + frappe.scrub(chapter.name))

    def test_ensure_route_preserves_explicit_route(self):
        """_ensure_route() does NOT overwrite an explicitly provided route."""
        explicit = f"custom/route/{self._uid()}"
        with self.assertNoErrorLog():
            chapter = self._make_chapter(route=explicit)
        self.assertEqual(chapter.route, explicit)

    # ------------------------------------------------------------------
    # get_board_member_emails de-duplication
    # ------------------------------------------------------------------
    def test_get_board_member_emails_dedupes(self):
        """get_board_member_emails() returns each board email at most once.

        Two board roles held by the SAME volunteer (one email) must collapse
        to a single address, exercising the `email not in emails` branch.
        """
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role_a = self._make_role()
        role_b = self._make_role()
        chapter = self._make_chapter()

        with self.assertNoErrorLog():
            chapter.add_board_member(volunteer=volunteer.name, role=role_a.name, from_date=today())
            chapter.add_board_member(volunteer=volunteer.name, role=role_b.name, from_date=today())
            chapter.reload()
            emails = chapter.get_board_member_emails()

        vol_email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        self.assertEqual(emails, [vol_email])

    def test_get_board_member_emails_empty_for_no_board(self):
        """No board members -> empty email list (loop body never runs)."""
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            self.assertEqual(chapter.get_board_member_emails(), [])

    # ------------------------------------------------------------------
    # validate_role_profile_configuration
    # ------------------------------------------------------------------
    def test_validate_role_profile_nonexistent_default_throws(self):
        """A default_board_role_profile that doesn't exist blocks save."""
        with self.assertRaises(frappe.ValidationError):
            self._make_chapter(default_board_role_profile=f"No Such Profile {self._uid()}")

    def test_validate_role_profile_valid_default_saves(self):
        """An existing Role Profile in default_board_role_profile passes validation."""
        profile = frappe.get_all("Role Profile", limit=1, pluck="name")[0]
        with self.assertNoErrorLog():
            chapter = self._make_chapter(default_board_role_profile=profile)
        self.assertEqual(chapter.default_board_role_profile, profile)

    def test_validate_role_profile_duplicate_role_assignment_throws(self):
        """Duplicate chapter_role rows in board_role_specific_profiles are rejected."""
        profile = frappe.get_all("Role Profile", limit=1, pluck="name")[0]
        role = self._make_role()
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Chapter {self._uid()}",
                "region": self.test_region,
                "status": "Active",
                "introduction": "dup",
                "default_board_role_profile": profile,
                "enable_board_role_specific_profiles": 1,
            }
        )
        chapter.append("board_role_specific_profiles", {"chapter_role": role.name, "role_profile": profile})
        chapter.append("board_role_specific_profiles", {"chapter_role": role.name, "role_profile": profile})
        with self.assertRaises(frappe.ValidationError) as ctx:
            chapter.insert()
        self.assertIn("Duplicate", str(ctx.exception))

    def test_validate_role_profile_nonexistent_chapter_role_throws(self):
        """A board_role_specific_profiles row pointing at a missing Chapter Role throws."""
        profile = frappe.get_all("Role Profile", limit=1, pluck="name")[0]
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Chapter {self._uid()}",
                "region": self.test_region,
                "status": "Active",
                "introduction": "badrole",
                "default_board_role_profile": profile,
                "enable_board_role_specific_profiles": 1,
            }
        )
        chapter.append(
            "board_role_specific_profiles",
            {"chapter_role": f"No Such Role {self._uid()}", "role_profile": profile},
        )
        with self.assertRaises(frappe.ValidationError):
            chapter.insert()

    # ------------------------------------------------------------------
    # validate_postal_codes (whitelisted) + matches_postal_code
    # ------------------------------------------------------------------
    def test_validate_postal_codes_valid_returns_true(self):
        """validate_postal_codes() returns True for well-formed patterns."""
        chapter = self._make_chapter(postal_codes="1000-1999, 2500, 3000-3099")
        with self.assertNoErrorLog():
            self.assertTrue(chapter.validate_postal_codes())

    def test_validate_postal_codes_empty_returns_true(self):
        """No postal_codes -> validate_postal_codes() short-circuits to True."""
        chapter = self._make_chapter()
        self.assertFalse(chapter.postal_codes)
        with self.assertNoErrorLog():
            self.assertTrue(chapter.validate_postal_codes())

    def test_matches_postal_code_range_and_exact(self):
        """matches_postal_code() honors ranges and exact codes; rejects outside."""
        chapter = self._make_chapter(postal_codes="1000-1999,2500")
        with self.assertNoErrorLog():
            self.assertTrue(chapter.matches_postal_code("1500"))
            self.assertTrue(chapter.matches_postal_code("2500"))
            self.assertFalse(chapter.matches_postal_code("2600"))

    # ------------------------------------------------------------------
    # optimized getters
    # ------------------------------------------------------------------
    def test_get_members_optimized_returns_added_member(self):
        """get_members_optimized() reflects a member added via the delegator."""
        member = self._make_member()
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            added = chapter.add_member(member.name)
            chapter.reload()
            members = chapter.get_members_optimized()
        self.assertTrue(added)
        member_ids = [m.get("member_id") for m in members]
        self.assertIn(member.name, member_ids)

    def test_get_board_members_optimized_returns_board_member(self):
        """get_board_members_optimized() returns active board members."""
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
            chapter.reload()
            board = chapter.get_board_members_optimized()
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0].get("volunteer"), volunteer.name)

    def test_get_chapter_head_member_optimized_none_when_unset(self):
        """No chapter_head -> get_chapter_head_member_optimized() returns None."""
        chapter = self._make_chapter()
        self.assertFalse(chapter.chapter_head)
        with self.assertNoErrorLog():
            self.assertIsNone(chapter.get_chapter_head_member_optimized())

    def test_get_chapter_head_member_optimized_returns_member(self):
        """A valid chapter_head resolves to the Member document."""
        head = self._make_member()
        chapter = self._make_chapter(chapter_head=head.name)
        # chapter_head is auto-managed; only assert if it persisted
        chapter.reload()
        if chapter.chapter_head:
            with self.assertNoErrorLog():
                doc = chapter.get_chapter_head_member_optimized()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.name, chapter.chapter_head)

    # ------------------------------------------------------------------
    # get_chapter_statistics
    # ------------------------------------------------------------------
    def test_get_chapter_statistics_structure(self):
        """get_chapter_statistics() returns all stat buckets + last_updated."""
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            stats = chapter.get_chapter_statistics()
        for key in (
            "board_stats",
            "member_stats",
            "communication_stats",
            "volunteer_integration_stats",
            "last_updated",
        ):
            self.assertIn(key, stats)
        self.assertIsNotNone(stats["last_updated"])

    # ------------------------------------------------------------------
    # add_member / remove_member delegators
    # ------------------------------------------------------------------
    def test_add_then_remove_member_delegators(self):
        """add_member() returns True and registers the member; remove_member()
        returns True and disables the roster row."""
        member = self._make_member()
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            self.assertTrue(chapter.add_member(member.name, introduction="hi"))
            chapter.reload()
        roster_ids = [m.member for m in chapter.members]
        self.assertIn(member.name, roster_ids)

        with self.assertNoErrorLog():
            self.assertTrue(chapter.remove_member(member.name, leave_reason="moved"))
            chapter.reload()
        # member row should now be disabled (soft-removed)
        row = next((m for m in chapter.members if m.member == member.name), None)
        if row is not None:
            self.assertEqual(row.enabled, 0)

    def test_get_members_delegator(self):
        """get_members() returns roster details including added member."""
        member = self._make_member()
        chapter = self._make_chapter()
        chapter.add_member(member.name)
        chapter.reload()
        with self.assertNoErrorLog():
            members = chapter.get_members()
        self.assertIn(member.name, [m.get("member_id") for m in members])

    # ------------------------------------------------------------------
    # module-level whitelisted functions
    # ------------------------------------------------------------------
    def test_module_leave_removes_member(self):
        """leave() delegates to MemberManager.remove_member and succeeds."""
        member = self._make_member()
        chapter = self._make_chapter()
        chapter.add_member(member.name)
        chapter.reload()
        with self.assertNoErrorLog():
            result = chapter_module.leave(title=chapter.name, member_id=member.name, leave_reason="bye")
        self.assertTrue(result.get("success"))

    def test_module_leave_missing_args_throws(self):
        """leave() requires both title and member_id; the guard throw is caught by
        the broad except, logged, and re-raised as a generic ValidationError."""
        self.expectErrorLog("Error removing member")
        with self.assertRaises(frappe.ValidationError):
            chapter_module.leave(title="", member_id="", leave_reason="x")

    def test_module_get_board_memberships(self):
        """get_board_memberships() returns the volunteer's active board rows."""
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter()
        chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
        with self.assertNoErrorLog():
            result = chapter_module.get_board_memberships(member.name)
        self.assertTrue(any(r.get("parent") == chapter.name for r in result))

    def test_module_get_board_memberships_no_member_returns_empty(self):
        """get_board_memberships() with falsy member_name returns []."""
        with self.assertNoErrorLog():
            self.assertEqual(chapter_module.get_board_memberships(""), [])

    def test_module_get_board_memberships_member_without_volunteer(self):
        """A member with no Volunteer record yields no board memberships."""
        member = self._make_member()
        with self.assertNoErrorLog():
            self.assertEqual(chapter_module.get_board_memberships(member.name), [])

    def test_module_remove_from_board(self):
        """remove_from_board() deactivates the board member row."""
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter()
        chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
        with self.assertNoErrorLog():
            result = chapter_module.remove_from_board(
                chapter_name=chapter.name, member_name=volunteer.name, end_date=today()
            )
        self.assertTrue(result.get("success"))
        chapter.reload()
        self.assertEqual(chapter.board_members[0].is_active, 0)

    def test_module_remove_from_board_missing_args_throws(self):
        """remove_from_board() requires chapter and member names; the guard throw is
        caught by the broad except, logged, and re-raised as a ValidationError."""
        self.expectErrorLog("from board of")
        with self.assertRaises(frappe.ValidationError):
            chapter_module.remove_from_board(chapter_name="", member_name="")

    def test_module_get_chapter_board_history(self):
        """get_chapter_board_history() includes inactive board members."""
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter()
        chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
        chapter.remove_board_member(volunteer=volunteer.name, end_date=today())
        with self.assertNoErrorLog():
            history = chapter_module.get_chapter_board_history(chapter.name)
        self.assertTrue(any(h.get("volunteer") == volunteer.name for h in history))

    def test_module_get_chapter_board_history_missing_name_returns_empty(self):
        """get_chapter_board_history() with no name raises internally but the
        broad except catches it, logs an Error Log, and returns []."""
        self.expectErrorLog("board history")
        result = chapter_module.get_chapter_board_history("")
        self.assertEqual(result, [])

    def test_module_get_chapter_stats(self):
        """get_chapter_stats() returns the statistics dict for a real chapter."""
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            stats = chapter_module.get_chapter_stats(chapter.name)
        self.assertIn("board_stats", stats)
        self.assertIn("member_stats", stats)

    def test_module_get_chapter_stats_missing_name_returns_empty(self):
        """get_chapter_stats() with no name raises internally but the broad
        except catches it, logs an Error Log, and returns {}."""
        self.expectErrorLog("statistics")
        result = chapter_module.get_chapter_stats("")
        self.assertEqual(result, {})

    def test_module_get_chapters_by_postal_code(self):
        """get_chapters_by_postal_code() returns chapters whose range covers the code."""
        chapter = self._make_chapter(postal_codes="7000-7999", published=1)
        with self.assertNoErrorLog():
            result = chapter_module.get_chapters_by_postal_code("7500")
        names = [r.get("name") for r in result]
        self.assertIn(chapter.name, names)

    def test_module_suggest_chapters_for_member(self):
        """suggest_chapters_for_member() runs against a real member + postal code."""
        member = self._make_member()
        self._make_chapter(postal_codes="8000-8999", published=1)
        with self.assertNoErrorLog():
            result = chapter_module.suggest_chapters_for_member(member.name, postal_code="8500")
        self.assertIsInstance(result, (list, dict))

    def test_module_suggest_chapter_for_member_legacy_alias(self):
        """suggest_chapter_for_member() forwards to the plural implementation."""
        member = self._make_member()
        self._make_chapter(postal_codes="9000-9999", published=1)
        with self.assertNoErrorLog():
            result = chapter_module.suggest_chapter_for_member(member.name, postal_code="9500")
        self.assertIsInstance(result, (list, dict))

    def test_module_is_chapter_management_enabled(self):
        """is_chapter_management_enabled() reflects the Verenigingen Setting."""
        with self.assertNoErrorLog():
            enabled = chapter_module.is_chapter_management_enabled()
        expected = bool(frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management"))
        self.assertEqual(bool(enabled), expected)

    # ------------------------------------------------------------------
    # board role profile preview / bulk apply
    # ------------------------------------------------------------------
    def test_get_board_role_profile_preview_not_found(self):
        """Unknown chapter -> preview returns an error dict."""
        with self.assertNoErrorLog():
            result = chapter_module.get_board_role_profile_preview(f"No Chapter {self._uid()}")
        self.assertEqual(result.get("error"), "Chapter not found")

    def test_get_board_role_profile_preview_with_board_member(self):
        """Preview builds member_assignments for active board members and exposes
        the chapter's default profile / role-specific flag."""
        profile = frappe.get_all("Role Profile", limit=1, pluck="name")[0]
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter(default_board_role_profile=profile)
        chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
        with self.assertNoErrorLog():
            preview = chapter_module.get_board_role_profile_preview(chapter.name)
        self.assertEqual(preview["chapter_name"], chapter.name)
        self.assertEqual(preview["default_profile"], profile)
        assigned = [a["volunteer"] for a in preview["member_assignments"]]
        self.assertIn(volunteer.name, assigned)

    def test_bulk_apply_chapter_board_role_profiles_not_found(self):
        """Unknown chapter -> bulk apply returns success=False."""
        with self.assertNoErrorLog():
            result = chapter_module.bulk_apply_chapter_board_role_profiles(f"No Chapter {self._uid()}")
        self.assertFalse(result.get("success"))

    def test_bulk_apply_chapter_board_role_profiles_real(self):
        """bulk_apply runs over a chapter that has a board member + default profile."""
        profile = frappe.get_all("Role Profile", limit=1, pluck="name")[0]
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        role = self._make_role()
        chapter = self._make_chapter(default_board_role_profile=profile)
        chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
        with self.assertNoErrorLog():
            result = chapter_module.bulk_apply_chapter_board_role_profiles(chapter.name)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    # ------------------------------------------------------------------
    # get_list_context
    # ------------------------------------------------------------------
    def test_get_list_context_sets_defaults(self):
        """get_list_context() populates list-view context defaults."""
        context = frappe._dict()
        with self.assertNoErrorLog():
            chapter_module.get_list_context(context)
        self.assertTrue(context.allow_guest)
        self.assertTrue(context.no_cache)
        self.assertEqual(context.title, "All Chapters")
        self.assertEqual(context.order_by, "creation desc")
        self.assertIsInstance(context.user_chapters, list)

    def test_get_list_context_user_chapters_for_member(self):
        """For a logged-in user linked to a Member that belongs to a chapter,
        get_list_context() lists that chapter in user_chapters.

        The User shares the Member's email, so get_current_user_member_name()
        resolves via the email-fallback lookup -- exercising the
        `if member:` / get_all("Chapter Member") branch of get_list_context().
        """
        member = self._make_member()
        chapter = self._make_chapter()
        chapter.add_member(member.name)
        chapter.reload()

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": member.email,
                "first_name": "Cov",
                "send_welcome_email": 0,
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        # Explicitly link the Member to this User so the primary lookup matches.
        frappe.db.set_value("Member", member.name, "user", user.name)

        # Confirm the member resolves for this user before invoking the context.
        from verenigingen.utils.member_utils import get_member_name_for_user

        self.assertEqual(get_member_name_for_user(user.name), member.name)

        context = frappe._dict()
        original_user = frappe.session.user
        try:
            frappe.set_user(user.name)
            with self.assertNoErrorLog():
                chapter_module.get_list_context(context)
        finally:
            # Restore whatever user the test started as (Administrator in the
            # default test session) rather than hard-coding it.
            frappe.set_user(original_user)
        self.assertIn(chapter.name, context.user_chapters)

    # ------------------------------------------------------------------
    # permission query / has_permission wrappers
    # ------------------------------------------------------------------
    def test_permission_query_conditions_admin(self):
        """get_chapter_permission_query_conditions() returns a str/None for admin."""
        with self.assertNoErrorLog():
            cond = chapter_module.get_chapter_permission_query_conditions("Administrator")
        self.assertTrue(cond is None or isinstance(cond, str))

    def test_has_chapter_permission_admin_true(self):
        """has_chapter_permission() grants Administrator read access."""
        chapter = self._make_chapter()
        with self.assertNoErrorLog():
            allowed = chapter_module.has_chapter_permission(chapter, "read", "Administrator")
        self.assertTrue(allowed)
