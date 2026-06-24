"""
Integration coverage for ``services/volunteer/expense_approver_service.py``.

The existing ``tests/volunteer/test_volunteer_service_coverage.py``
(``TestExpenseApproverService``) already covers the *negative* / empty branches
(no board, no chapters, no teams, Administrator fallback, lazy load, factory
function). This module fills the uncovered *positive* paths that actually
resolve an approver:

  * ``get_board_financial_approver`` — finds an active board member holding a
    financial role whose volunteer maps to an enabled User, assigns the Expense
    Approver role, and returns the email.
  * ``ensure_user_has_expense_approver_role`` — appends the role (and the no-op
    when already present).
  * ``_get_chapter_member_approver`` — resolves through the volunteer's chapter
    membership to that chapter's board treasurer.
  * ``_get_team_member_approver`` — resolves through the volunteer's team to the
    team's chapter board approver (batch-fetch path).
  * ``_get_national_board_approver`` — national-board member routed to another
    national board financial officer.
  * ``_get_fallback_approver`` — first enabled non-Administrator user.
  * ``get_expense_approver`` end-to-end priority + the Administrator
    safe-fallback on internal error.

Real Member / Volunteer / Chapter / Chapter Board Member / Team / User fixtures
are built via the canonical factory. The board-member volunteer's ``email`` is
pinned to a real, enabled User so the approver-resolution succeeds
deterministically (the approver lookup requires ``frappe.db.exists("User", …)``
to be true and the user enabled). No business-logic mocking.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseApproverServicePositivePaths(EnhancedTestCase):
    """Positive approver-resolution paths for VolunteerExpenseApproverService."""

    def setUp(self):
        super().setUp()
        # The financial-role priority list keys off Chapter Role names; make sure
        # the named roles the service searches for exist.
        for role_name in ("Treasurer", "Financial Officer", "Secretary"):
            self.factory.ensure_chapter_role(role_name)
        self.member = self.create_test_member(first_name="ApprPos", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def tearDown(self):
        self._clear_assignment_cache()
        super().tearDown()

    @staticmethod
    def _clear_assignment_cache():
        if hasattr(frappe.local, "_volunteer_assignment_cache"):
            delattr(frappe.local, "_volunteer_assignment_cache")

    # ------------------------------------------------------------------ helpers
    def _service(self, volunteer_name=None):
        from verenigingen.services.volunteer.expense_approver_service import (
            VolunteerExpenseApproverService,
        )

        return VolunteerExpenseApproverService(volunteer_name or self.volunteer.name)

    def _make_user(self, prefix="board"):
        """Create a real, enabled, tracked User (factory helper)."""
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "Boarduser",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return user

    def _make_board_volunteer_with_user(self, prefix="boardvol"):
        """A Volunteer whose ``email`` is pinned to a real enabled User account."""
        user = self._make_user(prefix)
        member = self.create_test_member(first_name="Board", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        # Pin the volunteer's email to the real User so the approver lookup
        # (frappe.db.exists("User", email) + user.enabled) resolves.
        frappe.db.set_value("Volunteer", volunteer.name, "email", user.email, update_modified=False)
        volunteer.reload()
        return volunteer, user

    def _ensure_chapter(self, hint):
        return self.ensure_test_chapter(f"ApprChap{hint}{frappe.generate_hash(length=4)}")

    def _add_board_member(self, chapter_name, volunteer_name, role="Treasurer"):
        """Append an active board member with a financial chapter_role."""
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save()
        return chapter

    def _add_chapter_member(self, chapter_name, member_name):
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("members", {"member": member_name, "enabled": 1})
        chapter.save()
        return chapter

    # ==================================================================
    # get_board_financial_approver — positive resolution
    # ==================================================================
    def test_board_financial_approver_resolves_treasurer(self):
        chapter = self._ensure_chapter("BFA")
        board_vol, board_user = self._make_board_volunteer_with_user("treas")
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        svc = self._service()
        approver = svc.get_board_financial_approver(chapter.name)
        self.assertEqual(approver, board_user.email)
        # Side effect: the approver user now holds the Expense Approver role.
        self.assertTrue(
            frappe.db.exists(
                "Has Role", {"parent": board_user.name, "role": "Expense Approver", "parenttype": "User"}
            ),
            "resolving a board approver must grant them the Expense Approver role",
        )

    def test_board_financial_approver_excludes_self(self):
        """A board treasurer cannot approve their own expense; exclude_volunteer
        filters them out -> None when they are the only board member."""
        chapter = self._ensure_chapter("BFAself")
        board_vol, _user = self._make_board_volunteer_with_user("selftreas")
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        svc = self._service(board_vol.name)
        # Only board member is the excluded volunteer -> no approver.
        self.assertIsNone(
            svc.get_board_financial_approver(chapter.name, exclude_volunteer=board_vol.name)
        )

    def test_board_financial_approver_skips_disabled_user(self):
        """A board member whose User is disabled is skipped -> None."""
        chapter = self._ensure_chapter("BFAdisabled")
        board_vol, board_user = self._make_board_volunteer_with_user("disabled")
        frappe.db.set_value("User", board_user.name, "enabled", 0)
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        svc = self._service()
        self.assertIsNone(svc.get_board_financial_approver(chapter.name))

    def test_board_financial_approver_role_priority_treasurer_first(self):
        """With both a Treasurer and a Secretary on the board, the Treasurer
        (higher priority) is returned."""
        chapter = self._ensure_chapter("BFAprio")
        treas_vol, treas_user = self._make_board_volunteer_with_user("priotreas")
        sec_vol, _sec_user = self._make_board_volunteer_with_user("priosec")
        self._add_board_member(chapter.name, sec_vol.name, role="Secretary")
        self._add_board_member(chapter.name, treas_vol.name, role="Treasurer")

        svc = self._service()
        self.assertEqual(svc.get_board_financial_approver(chapter.name), treas_user.email)

    # ==================================================================
    # ensure_user_has_expense_approver_role
    # ==================================================================
    def test_ensure_role_appends_when_missing(self):
        user = self._make_user("needsrole")
        self.assertFalse(
            frappe.db.exists(
                "Has Role", {"parent": user.name, "role": "Expense Approver", "parenttype": "User"}
            )
        )
        svc = self._service()
        with self.assertNoErrorLog():
            svc.ensure_user_has_expense_approver_role(user.name)
        self.assertTrue(
            frappe.db.exists(
                "Has Role", {"parent": user.name, "role": "Expense Approver", "parenttype": "User"}
            )
        )

    def test_ensure_role_noop_when_present(self):
        """Calling twice does not duplicate the role nor error."""
        user = self._make_user("hasrole")
        svc = self._service()
        with self.assertNoErrorLog():
            svc.ensure_user_has_expense_approver_role(user.name)
            svc.ensure_user_has_expense_approver_role(user.name)
        rows = frappe.get_all(
            "Has Role",
            filters={"parent": user.name, "role": "Expense Approver", "parenttype": "User"},
        )
        self.assertEqual(len(rows), 1, "role must not be duplicated on repeat calls")

    # ==================================================================
    # _get_chapter_member_approver — positive
    # ==================================================================
    def test_chapter_member_approver_resolves_through_membership(self):
        """The subject volunteer is a chapter member; the chapter's board
        treasurer is returned as the approver."""
        chapter = self._ensure_chapter("CMA")
        # Subject volunteer is a member of this chapter.
        self._add_chapter_member(chapter.name, self.member.name)
        # A different volunteer is the chapter's treasurer.
        board_vol, board_user = self._make_board_volunteer_with_user("cmatreas")
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        svc = self._service()
        svc._load_volunteer()
        self.assertEqual(svc._get_chapter_member_approver(), board_user.email)

    def test_chapter_member_approver_none_when_member_link_missing(self):
        """Volunteer without a member link short-circuits to None."""
        frappe.db.set_value("Volunteer", self.volunteer.name, "member", None, update_modified=False)
        svc = self._service()
        svc._load_volunteer()
        self.assertIsNone(svc._get_chapter_member_approver())

    # ==================================================================
    # _get_team_member_approver — positive (batch-fetch path)
    # ==================================================================
    def test_team_member_approver_resolves_through_team_chapter(self):
        """The subject volunteer is on a team whose chapter has a board treasurer;
        that treasurer is returned (exercises the optimized batch fetch)."""
        chapter = self._ensure_chapter("TMA")
        board_vol, board_user = self._make_board_volunteer_with_user("tmatreas")
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        team = self.create_test_team(team_name="ApprTeam")
        frappe.db.set_value("Team", team.name, "chapter", chapter.name, update_modified=False)
        self.create_test_team_member(team.name, self.volunteer.name)

        svc = self._service()
        self.assertEqual(svc._get_team_member_approver(), board_user.email)

    def test_team_member_approver_none_when_team_has_no_chapter(self):
        """A team membership whose team has no chapter -> None (no resolution)."""
        team = self.create_test_team(team_name="ApprTeamNoChap")
        frappe.db.set_value("Team", team.name, "chapter", None, update_modified=False)
        self.create_test_team_member(team.name, self.volunteer.name)
        svc = self._service()
        self.assertIsNone(svc._get_team_member_approver())

    # ==================================================================
    # _get_national_board_approver — positive
    # ==================================================================
    def test_national_board_approver_routes_to_other_officer(self):
        """A national-board member is routed to ANOTHER national board financial
        officer (cannot self-approve)."""
        national_chapter = self._ensure_chapter("Natl")
        # Subject volunteer is on the national board.
        self._add_board_member(national_chapter.name, self.volunteer.name, role="Secretary")
        # Another volunteer is the national board treasurer (the approver).
        other_vol, other_user = self._make_board_volunteer_with_user("natltreas")
        self._add_board_member(national_chapter.name, other_vol.name, role="Treasurer")

        # Point Verenigingen Settings at this chapter as the national board.
        prev = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national_chapter.name)
        try:
            svc = self._service()
            svc._load_volunteer()
            self.assertEqual(svc._get_national_board_approver(), other_user.email)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", prev)

    def test_national_board_approver_none_when_not_on_board(self):
        """A volunteer NOT on the national board -> None from this branch."""
        national_chapter = self._ensure_chapter("NatlNo")
        prev = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national_chapter.name)
        try:
            svc = self._service()
            svc._load_volunteer()
            self.assertIsNone(svc._get_national_board_approver())
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", prev)

    # ==================================================================
    # _get_fallback_approver
    # ==================================================================
    def test_fallback_approver_returns_enabled_nonadmin_user(self):
        """The fallback returns the earliest-created enabled non-Administrator
        user and grants them the Expense Approver role."""
        svc = self._service()
        with self.assertNoErrorLog():
            approver = svc._get_fallback_approver()
        self.assertIsNotNone(approver)
        self.assertNotEqual(approver, "Administrator")
        self.assertTrue(frappe.db.get_value("User", approver, "enabled"))
        self.assertTrue(
            frappe.db.exists(
                "Has Role", {"parent": approver, "role": "Expense Approver", "parenttype": "User"}
            )
        )

    # ==================================================================
    # get_expense_approver — end-to-end priority + safe fallback
    # ==================================================================
    def test_get_expense_approver_prefers_chapter_over_fallback(self):
        """End-to-end: a chapter member with a chapter treasurer resolves to that
        treasurer (priority 2), not the generic system fallback."""
        chapter = self._ensure_chapter("E2E")
        self._add_chapter_member(chapter.name, self.member.name)
        board_vol, board_user = self._make_board_volunteer_with_user("e2etreas")
        self._add_board_member(chapter.name, board_vol.name, role="Treasurer")

        svc = self._service()
        self.assertEqual(svc.get_expense_approver(), board_user.email)

    def test_get_expense_approver_administrator_safe_fallback_on_error(self):
        """If volunteer resolution blows up internally, get_expense_approver
        swallows and returns the Administrator safe fallback (never raises)."""
        # A non-existent volunteer name makes _load_volunteer raise inside the
        # try/except -> the documented Administrator safe fallback.
        svc = self._service("VOL-DOES-NOT-EXIST-XYZ")
        self.assertEqual(svc.get_expense_approver(), "Administrator")
