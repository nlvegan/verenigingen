"""
Real-integration tests for the Chapter doctype controller
``verenigingen/verenigingen/doctype/chapter/chapter.py``.

The Chapter controller mostly delegates to specialized managers (board /
member / communication / volunteer-integration) and to extracted service
classes. This suite exercises:

  * the thin delegate methods on the ``Chapter`` document (``get_member_role``,
    ``can_view_member_payments``, ``get_active_board_roles``, ``get_members``,
    ``get_communication_history`` and the ``*_optimized`` family), and
  * the module-level whitelisted endpoints (``leave``, ``remove_from_board``,
    ``get_chapter_stats``, ``get_chapters_by_postal_code``,
    ``get_chapter_board_history``, ``get_board_memberships``,
    ``get_board_role_profile_preview``, ``bulk_apply_chapter_board_role_profiles``,
    ``is_chapter_management_enabled``, ``get_list_context``,
    ``get_chapter_permission_query_conditions`` ...).

All Chapters/Members/Volunteers/board members are created via the real test
factory (no business-logic mocking) and the suite runs as Administrator, so the
permission gates on the whitelisted endpoints are satisfied and their happy
paths are reachable. Each test resolves managers via ``chapter.member_manager``
etc. to mirror the production call path.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter import chapter as chapter_mod


class TestChapterController(VereningingenTestCase):
    """Exercise the Chapter controller delegate methods and module endpoints."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Ctrl Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="Ctrl",
            last_name="Primary",
            email=f"ctrl.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------------ helpers

    def _reload_chapter(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_board(self, permissions_level="Basic", is_chair=0, first="Board"):
        """Create a real volunteer + chapter role and seat them on self.chapter.

        Returns (member, volunteer, role_name).
        """
        member = self.create_test_member(
            first_name=first,
            last_name="Ctrl",
            email=f"ctrl.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        # NOTE: pass member= (the link field). member_name= would land in the
        # Volunteer.volunteer_name display field and leave .member auto-created.
        volunteer = self.create_test_volunteer(member=member.name)
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": permissions_level,
                "is_chair": is_chair,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        self.add_board_member_to_chapter(
            self.chapter, volunteer, role_name, email=member.email
        )
        self._reload_chapter()
        return member, volunteer, role_name

    # ============================================================= delegates: board

    def test_get_member_role_returns_seated_role(self):
        board_member, _vol, role_name = self._make_board()
        self.assertEqual(self.chapter.get_member_role(member_name=board_member.name), role_name)

    def test_get_member_role_non_board_member_is_none(self):
        self.assertIsNone(self.chapter.get_member_role(member_name=self.member.name))

    def test_is_board_member_delegation(self):
        board_member, _vol, _role = self._make_board()
        self.assertTrue(self.chapter.is_board_member(member_name=board_member.name))
        self.assertFalse(self.chapter.is_board_member(member_name=self.member.name))

    def test_can_view_member_payments_basic_role_denied(self):
        # A Basic-permission role cannot view payments.
        board_member, _vol, _role = self._make_board(permissions_level="Basic")
        self.assertFalse(self.chapter.can_view_member_payments(member_name=board_member.name))

    def test_can_view_member_payments_financial_role_allowed(self):
        board_member, _vol, _role = self._make_board(permissions_level="Financial")
        self.assertTrue(self.chapter.can_view_member_payments(member_name=board_member.name))

    def test_can_view_member_payments_non_board_denied(self):
        self.assertFalse(self.chapter.can_view_member_payments(member_name=self.member.name))

    def test_get_active_board_roles(self):
        board_member, _vol, role_name = self._make_board()
        roles = self.chapter.get_active_board_roles()
        self.assertIn(role_name, roles)
        self.assertEqual(roles[role_name]["member"], board_member.name)

    def test_get_active_board_roles_empty_when_no_board(self):
        self.assertEqual(self.chapter.get_active_board_roles(), {})

    def test_get_board_members_and_emails(self):
        board_member, volunteer, _role = self._make_board()
        members = self.chapter.get_board_members()
        self.assertTrue(any(m["member"] == board_member.name for m in members))

        # The board-member row's email is sourced from the seated Volunteer record
        # (the additions hook resolves it), so assert against the volunteer email.
        emails = self.chapter.get_board_member_emails()
        vol_email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        self.assertIn(vol_email, emails)

    def test_get_board_members_optimized(self):
        board_member, _vol, _role = self._make_board()
        members = self.chapter.get_board_members_optimized()
        self.assertTrue(any(m["member"] == board_member.name for m in members))

    # ============================================================ delegates: member

    def test_get_members_delegation(self):
        self.chapter.member_manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        members = self.chapter.get_members()
        ids = {m["member_id"] for m in members}
        self.assertIn(self.member.name, ids)
        # get_members(with_details=True) -> rows carry an email.
        row = next(m for m in members if m["member_id"] == self.member.name)
        self.assertEqual(row["email"], self.member.email)

    def test_get_members_optimized(self):
        self.chapter.member_manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        members = self.chapter.get_members_optimized()
        self.assertTrue(any(m["member_id"] == self.member.name for m in members))

    def test_add_and_remove_member_return_bool(self):
        # The Chapter.add_member / remove_member wrappers collapse the manager's
        # result dict to a bool.
        self.assertTrue(self.chapter.add_member(self.member.name))
        self._reload_chapter()
        self.assertTrue(self.chapter.remove_member(self.member.name, leave_reason="left"))

    # ===================================================== delegates: communication

    def test_get_communication_history_returns_list(self):
        history = self.chapter.get_communication_history(limit=5)
        self.assertIsInstance(history, list)

    # =================================================== delegates: chapter head / chair

    def test_get_chapter_chair_optimized_none_without_chair(self):
        # No chair-role board member seated -> no chair resolved.
        self.assertIsNone(self.chapter.get_chapter_chair_optimized())

    def test_get_chapter_chair_optimized_finds_chair(self):
        board_member, _vol, _role = self._make_board(is_chair=1, first="Chair")
        chair = self.chapter.get_chapter_chair_optimized()
        # The chair query resolves the seated chair's member.
        self.assertEqual(chair, board_member.name)

    def test_get_chapter_head_member_optimized_none_when_unset(self):
        # Fresh chapter has no chapter_head set.
        self._reload_chapter()
        self.assertIsNone(self.chapter.get_chapter_head_member_optimized())

    def test_get_chapter_head_member_optimized_loads_member(self):
        frappe.db.set_value("Chapter", self.chapter.name, "chapter_head", self.member.name)
        self._reload_chapter()
        head = self.chapter.get_chapter_head_member_optimized()
        self.assertIsNotNone(head)
        self.assertEqual(head.name, self.member.name)

    # ======================================================= validation: postal / role

    def test_validate_postal_codes_valid(self):
        self.assertTrue(self.chapter.validate_postal_codes())

    def test_validate_postal_codes_empty_is_valid(self):
        frappe.db.set_value("Chapter", self.chapter.name, "postal_codes", "")
        self._reload_chapter()
        self.assertTrue(self.chapter.validate_postal_codes())

    def test_matches_postal_code(self):
        self.assertTrue(self.chapter.matches_postal_code("1234"))

    def test_validate_role_profile_configuration_missing_profile_throws(self):
        self.chapter.default_board_role_profile = "No Such Role Profile XYZ"
        with self.assertRaises(frappe.ValidationError):
            self.chapter.validate_role_profile_configuration()

    def test_validate_role_profile_configuration_ok_when_unset(self):
        # default_board_role_profile is empty on a fresh chapter -> no throw.
        self._reload_chapter()
        self.chapter.validate_role_profile_configuration()  # must not raise

    # ================================================ statistics / dashboard delegates

    def test_get_chapter_statistics_shape(self):
        stats = self.chapter.get_chapter_statistics()
        for key in (
            "board_stats",
            "member_stats",
            "communication_stats",
            "volunteer_integration_stats",
            "last_updated",
        ):
            self.assertIn(key, stats)

    # ===================================================== module endpoint: leave

    def test_endpoint_leave_removes_member(self):
        self.chapter.member_manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = chapter_mod.leave(
            title=self.chapter.name, member_id=self.member.name, leave_reason="moving"
        )
        self.assertTrue(result.get("success"))
        self._reload_chapter()
        row = self.chapter.member_manager._find_chapter_member(self.member.name)
        # Default removal disables the row rather than deleting it.
        self.assertFalse(row.enabled)

    def test_endpoint_leave_requires_params(self):
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.leave(title="", member_id="", leave_reason="x")

    def test_endpoint_leave_unknown_chapter_throws(self):
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.leave(
                title="NONEXISTENT-CHAPTER-XYZ", member_id=self.member.name, leave_reason="x"
            )

    # ============================================== module endpoint: remove_from_board

    def test_endpoint_remove_from_board(self):
        _board_member, volunteer, _role = self._make_board()
        result = chapter_mod.remove_from_board(
            chapter_name=self.chapter.name, member_name=volunteer.name, end_date=today()
        )
        self.assertTrue(result.get("success"))
        self._reload_chapter()
        # Volunteer should no longer be an active board member.
        self.assertFalse(self.chapter.is_board_member(volunteer_name=volunteer.name))

    def test_endpoint_remove_from_board_requires_params(self):
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.remove_from_board(chapter_name="", member_name="")

    def test_endpoint_remove_from_board_unknown_chapter_throws(self):
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.remove_from_board(
                chapter_name="NONEXISTENT-CHAPTER-XYZ", member_name="whatever"
            )

    # ================================================ module endpoint: get_chapter_stats

    def test_endpoint_get_chapter_stats(self):
        stats = chapter_mod.get_chapter_stats(self.chapter.name)
        self.assertIn("board_stats", stats)
        self.assertIn("member_stats", stats)

    def test_endpoint_get_chapter_stats_requires_name(self):
        # The "name is required" throw is raised inside the try/except and is
        # swallowed by the broad ``except Exception`` -> an empty dict is returned.
        self.assertEqual(chapter_mod.get_chapter_stats(""), {})

    def test_endpoint_get_chapter_stats_unknown_raises(self):
        # An unknown chapter hits the dedicated ``except DoesNotExistError`` branch
        # which re-throws a "not found" ValidationError.
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.get_chapter_stats("NONEXISTENT-CHAPTER-XYZ")

    # ===================================== module endpoint: get_chapters_by_postal_code

    def test_endpoint_get_chapters_by_postal_code_match(self):
        result = chapter_mod.get_chapters_by_postal_code("1234")
        self.assertTrue(any(c.get("name") == self.chapter.name for c in result))

    def test_endpoint_get_chapters_by_postal_code_no_match(self):
        # A chapter scoped to a narrow range should not match an out-of-range code.
        narrow = self.create_test_chapter(
            chapter_name=f"Narrow {frappe.generate_hash(length=6)}",
            postal_codes="2000-2099",
            published=1,
        )
        result = chapter_mod.get_chapters_by_postal_code("9000")
        self.assertFalse(any(c.get("name") == narrow.name for c in result))

    # ===================================== module endpoint: get_chapter_board_history

    def test_endpoint_get_chapter_board_history(self):
        board_member, _vol, _role = self._make_board()
        history = chapter_mod.get_chapter_board_history(self.chapter.name)
        self.assertTrue(any(m["member"] == board_member.name for m in history))

    def test_endpoint_get_chapter_board_history_requires_name(self):
        # "name is required" throw is swallowed by the broad ``except Exception``,
        # leaving an empty list.
        self.assertEqual(chapter_mod.get_chapter_board_history(""), [])

    def test_endpoint_get_chapter_board_history_unknown_raises(self):
        # Unknown chapter hits the ``except DoesNotExistError`` branch -> re-throw.
        with self.assertRaises(frappe.ValidationError):
            chapter_mod.get_chapter_board_history("NONEXISTENT-CHAPTER-XYZ")

    # ========================================= module endpoint: get_board_memberships

    def test_endpoint_get_board_memberships(self):
        board_member, _vol, role_name = self._make_board()
        memberships = chapter_mod.get_board_memberships(board_member.name)
        self.assertTrue(
            any(m["parent"] == self.chapter.name and m["chapter_role"] == role_name for m in memberships)
        )

    def test_endpoint_get_board_memberships_empty_member(self):
        self.assertEqual(chapter_mod.get_board_memberships(""), [])

    def test_endpoint_get_board_memberships_member_without_volunteer(self):
        # self.member has no Volunteer record -> no board memberships.
        self.assertEqual(chapter_mod.get_board_memberships(self.member.name), [])

    # ================================== module endpoint: get_board_role_profile_preview

    def test_endpoint_get_board_role_profile_preview(self):
        board_member, _vol, role_name = self._make_board()
        preview = chapter_mod.get_board_role_profile_preview(self.chapter.name)
        self.assertEqual(preview["chapter_name"], self.chapter.name)
        self.assertIn("member_assignments", preview)
        self.assertTrue(
            any(a["chapter_role"] == role_name for a in preview["member_assignments"])
        )

    def test_endpoint_get_board_role_profile_preview_unknown_chapter(self):
        result = chapter_mod.get_board_role_profile_preview("NONEXISTENT-CHAPTER-XYZ")
        self.assertIn("error", result)

    # =========================== module endpoint: bulk_apply_chapter_board_role_profiles

    def test_endpoint_bulk_apply_board_role_profiles(self):
        self._make_board()
        result = chapter_mod.bulk_apply_chapter_board_role_profiles(self.chapter.name)
        self.assertIn("success", result)

    def test_endpoint_bulk_apply_board_role_profiles_unknown_chapter(self):
        result = chapter_mod.bulk_apply_chapter_board_role_profiles("NONEXISTENT-CHAPTER-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    # =============================== module endpoint: is_chapter_management_enabled

    def test_is_chapter_management_enabled_reflects_setting(self):
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        self.assertTrue(chapter_mod.is_chapter_management_enabled())
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 0)
        self.assertFalse(chapter_mod.is_chapter_management_enabled())

    # ===================================================== module: get_list_context

    def test_get_list_context_sets_defaults(self):
        context = frappe._dict()
        chapter_mod.get_list_context(context)
        self.assertTrue(context.allow_guest)
        self.assertEqual(context.title, "All Chapters")
        self.assertIsInstance(context.user_chapters, list)

    # ============================ module: get_chapter_permission_query_conditions

    def test_permission_query_conditions_admin_unrestricted(self):
        # Administrator is an admin user -> empty (no) restriction.
        self.assertEqual(
            chapter_mod.get_chapter_permission_query_conditions("Administrator"), ""
        )

    def test_permission_query_conditions_regular_user_published_only(self):
        user = self.create_test_user(
            f"ctrl.regular.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        conditions = chapter_mod.get_chapter_permission_query_conditions(user.name)
        self.assertIn("published = 1", conditions)

    # ===================================== module: get_user_accessible_chapters_optimized

    def test_get_user_accessible_chapters_optimized_for_board_member(self):
        board_member, _vol, _role = self._make_board()
        # Link the board member's Member record to a real User so the query can join.
        user = self.create_test_user(
            f"ctrl.access.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        frappe.db.set_value("Member", board_member.name, "user", user.name)
        # Deprecated wrapper still returns this user's chapters.
        chapters = chapter_mod.get_user_accessible_chapters_optimized(user.name)
        self.assertIn(self.chapter.name, chapters)

    def test_get_user_accessible_chapters_optimized_no_chapters(self):
        user = self.create_test_user(
            f"ctrl.none.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        self.assertEqual(chapter_mod.get_user_accessible_chapters_optimized(user.name), [])
