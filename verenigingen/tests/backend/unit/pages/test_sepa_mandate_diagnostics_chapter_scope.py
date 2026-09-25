"""Chapter-scoping tests for sepa_mandate_diagnostics.py's get_mandate_issues (#1329).

Maintainer decision (2026-09-25,
https://github.com/nlvegan/verenigingen/issues/1329#issuecomment-5830712514):

    Chapter Board Members may see mandate issues only for members of the
    chapter(s) they sit on. Staff (Roles.ADMIN_ROLES) keep the full app-wide
    list. Volunteer and Auditor get no access (already covered by the sibling
    test_sepa_mandate_diagnostics_scope.py).

get_mandate_issues() implements this via _mandate_diagnostics_member_scope_sql(),
which reuses permissions._get_board_chapters_for_member() -- the SAME helper
permissions.get_sepa_mandate_permission_query() uses to scope SEPA Mandate's own
get_list() to a board member's chapters -- rather than a second, possibly-divergent
definition of "my chapter's members". That helper resolves "chapters where this
member holds an ACTIVE Chapter Board Member seat" (``cbm.is_active = 1``); it does
not consult ``to_date``, matching board_member_validator.py's own note that an
active row with a past end date is real, tolerated data (a WARNING, not an error) --
this test suite therefore uses ``is_active`` to represent "ended", not ``to_date``.

Fixtures use create_test_board_member()/add_member_to_test_chapter(), the
established helpers in enhanced_test_factory.py that already assemble the full
User -> Member -> Volunteer -> Chapter Board Member chain a real board seat needs
(a hand-built chain is how #1088/#1093-era tests silently tested nothing -- see
those helpers' own docstrings) and the Chapter Member row that determines chapter
membership (NOT Member.current_chapter_display, which is a cached display field
maintained by member_chapter_display_service.py from the same Chapter Member table
-- the permission model reads Chapter Member directly, so this suite does too).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics import (
    get_mandate_issues,
)


def _make_sepa_issue_member(test, first_name):
    """A member that qualifies for the 'sepa_selected_no_mandate' category: SEPA
    Direct Debit selected, no IBAN/account holder, no mandate. Same shape as
    test_sepa_mandate_retry_report_coverage.py's test_execute_sepa_selected_no_mandate."""
    member = test.create_test_member(first_name=first_name)
    frappe.db.set_value(
        "Member",
        member.name,
        {"payment_method": "SEPA Direct Debit", "iban": "", "bank_account_name": ""},
        update_modified=False,
    )
    return member


def _no_mandate_member_ids(result):
    return {m["member_id"] for m in result["issues"]["sepa_selected_no_mandate"]["members"]}


class TestGetMandateIssuesChapterScope(EnhancedTestCase):
    def test_board_member_sees_own_chapter_not_other_chapter(self):
        """Core scenario: a board member of chapter A sees chapter A's member and
        does NOT see chapter B's member."""
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        member_in_a = _make_sepa_issue_member(self, "ScopeInA")
        self.add_member_to_test_chapter(member_in_a.name, chapter_a.name)

        member_in_b = _make_sepa_issue_member(self, "ScopeInB")
        self.add_member_to_test_chapter(member_in_b.name, chapter_b.name)

        with self.set_user(board.user):
            result = get_mandate_issues()

        member_ids = _no_mandate_member_ids(result)
        self.assertIn(member_in_a.name, member_ids)
        self.assertNotIn(member_in_b.name, member_ids)

    def test_member_with_no_chapter_invisible_to_board_visible_to_admin(self):
        """Opposite-harm case: a member with NO Chapter Member row at all must not
        leak to a board member (it matches no chapter's IN-list) but must still be
        visible to an admin/staff caller (the app-wide list must not shrink for a
        member simply because they have no chapter)."""
        chapter_a = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        unaffiliated = _make_sepa_issue_member(self, "ScopeNoChapter")
        # Deliberately do NOT call add_member_to_test_chapter for this member.

        with self.set_user(board.user):
            board_result = get_mandate_issues()
        self.assertNotIn(unaffiliated.name, _no_mandate_member_ids(board_result))

        # Administrator is the default test-session user; EnhancedTestCase does not
        # switch users unless told to, so this runs as admin without a set_user block.
        admin_result = get_mandate_issues()
        self.assertIn(unaffiliated.name, _no_mandate_member_ids(admin_result))

    def test_member_in_two_chapters_visible_via_either(self):
        """Opposite-harm case: a member belonging to chapter A AND chapter C must
        still be visible to chapter A's board member -- membership in an
        additional, unrelated chapter must not exclude them."""
        chapter_a = self.create_test_chapter()
        chapter_c = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        member_in_both = _make_sepa_issue_member(self, "ScopeInBoth")
        self.add_member_to_test_chapter(member_in_both.name, chapter_a.name)
        self.add_member_to_test_chapter(member_in_both.name, chapter_c.name)

        with self.set_user(board.user):
            result = get_mandate_issues()

        self.assertIn(member_in_both.name, _no_mandate_member_ids(result))

    def test_board_member_of_multiple_chapters_sees_both(self):
        """A board member seated on TWO chapters sees members of both."""
        chapter_a = self.create_test_chapter()
        chapter_d = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        # Seat the SAME volunteer on a second chapter (chapter_d), reusing the
        # Chapter Role create_test_board_member already created.
        chapter_d_doc = frappe.get_doc("Chapter", chapter_d.name)
        chapter_d_doc.append(
            "board_members",
            {
                "volunteer": board.volunteer,
                "chapter_role": board.chapter_role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_d_doc.save()

        member_in_a = _make_sepa_issue_member(self, "ScopeMultiA")
        self.add_member_to_test_chapter(member_in_a.name, chapter_a.name)
        member_in_d = _make_sepa_issue_member(self, "ScopeMultiD")
        self.add_member_to_test_chapter(member_in_d.name, chapter_d.name)

        with self.set_user(board.user):
            result = get_mandate_issues()

        member_ids = _no_mandate_member_ids(result)
        self.assertIn(member_in_a.name, member_ids)
        self.assertIn(member_in_d.name, member_ids)

    def test_only_seat_ended_role_revoked_and_access_refused(self):
        """Ending a board member's ONLY seat (is_active -> 0) does not just empty
        their per-chapter scope -- Chapter.on_update's BoardManager re-evaluates
        every board member's role assignment whenever board_members changes
        (chapter_board_member.py's withdraw_board_member_role_if_unseated(), run
        from the PARENT's on_update, not the child row's own hooks -- see that
        function's docstring), and finding no other active seat, revokes
        'Verenigingen Chapter Board Member' from the user entirely. So the
        end-to-end outcome of ending someone's only seat is a hard refusal at
        _ensure_mandate_diagnostics_access(), which is an even stronger "sees
        nothing" than an empty result."""
        chapter_a = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        member_in_a = _make_sepa_issue_member(self, "ScopeEndedOnlySeat")
        self.add_member_to_test_chapter(member_in_a.name, chapter_a.name)

        # Confirm the seat grants visibility BEFORE ending it (control).
        with self.set_user(board.user):
            before = get_mandate_issues()
        self.assertIn(member_in_a.name, _no_mandate_member_ids(before))

        chapter_doc = frappe.get_doc("Chapter", chapter_a.name)
        seat = next(row for row in chapter_doc.board_members if row.volunteer == board.volunteer)
        seat.is_active = 0
        chapter_doc.save()

        self.assertNotIn(
            "Verenigingen Chapter Board Member",
            frappe.get_roles(board.user),
            "ending the only seat is expected to revoke the role via BoardManager",
        )
        with self.set_user(board.user):
            with self.assertRaises(frappe.PermissionError):
                get_mandate_issues()

    def test_ended_seat_excluded_while_other_active_seat_still_visible(self):
        """Isolates the SCOPE check (not the role gate) for an ended seat: a board
        member holds an active seat on chapter A and an ENDED seat on chapter E.
        Since chapter A keeps them seated, 'Verenigingen Chapter Board Member' is
        retained (withdraw_board_member_role_if_unseated finds the other active
        seat), so this reaches _mandate_diagnostics_member_scope_sql() rather than
        being refused outright -- and the ended chapter E seat must contribute NO
        chapters, so chapter E's member stays invisible while chapter A's member
        remains visible."""
        chapter_a = self.create_test_chapter()
        chapter_e = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        chapter_e_doc = frappe.get_doc("Chapter", chapter_e.name)
        chapter_e_doc.append(
            "board_members",
            {
                "volunteer": board.volunteer,
                "chapter_role": board.chapter_role,
                "from_date": frappe.utils.add_days(frappe.utils.today(), -30),
                "to_date": frappe.utils.add_days(frappe.utils.today(), -1),
                "is_active": 0,
            },
        )
        chapter_e_doc.save()

        self.assertIn(
            "Verenigingen Chapter Board Member",
            frappe.get_roles(board.user),
            "test setup: chapter A's still-active seat must keep the role held",
        )

        member_in_a = _make_sepa_issue_member(self, "ScopeSeatEndedA")
        self.add_member_to_test_chapter(member_in_a.name, chapter_a.name)
        member_in_e = _make_sepa_issue_member(self, "ScopeSeatEndedE")
        self.add_member_to_test_chapter(member_in_e.name, chapter_e.name)

        with self.set_user(board.user):
            result = get_mandate_issues()

        member_ids = _no_mandate_member_ids(result)
        self.assertIn(member_in_a.name, member_ids)
        self.assertNotIn(member_in_e.name, member_ids)
