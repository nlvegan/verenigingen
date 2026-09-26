"""Regression + chapter-scoping tests for pages/membership_applications/__init__.py
(#1502, follow-up to #1486's item 3).

## The crash (#1502)

Both `get_pending_applications` and `get_application_stats` 500ed for every
caller, including admins, confirmed live on test_site_1 before this fix:

- `get_pending_applications`: `frappe.user.has_role(...)` -- `frappe.user` is a
  LocalProxy over `frappe.local.user`, which nothing in the framework ever
  sets, so this always raised
  `AttributeError: 'NoneType' object has no attribute 'has_role'`.
- `get_application_stats`: raw SQL selected/grouped by `suggested_chapter`,
  which is not a field on the Member DocType --
  `MySQLdb.OperationalError: (1054, "Unknown column 'suggested_chapter'...")`.
- A THIRD, previously undocumented crash in the same file (found while fixing
  the above, confirmed live via a standalone frappe.connect() probe): both
  functions also requested `current_chapter_display` and/or `address_display`
  in `frappe.get_all(fields=[...])`. Both are HTML-fieldtype fields with no DB
  column (verenigingen/verenigingen/doctype/member/member.json), so
  `frappe.get_all` on them raises the same
  `Unknown column '...' in 'SELECT'` OperationalError. Fixing only the two
  named crashes would still leave both endpoints broken on this.

The chapter an application is "for" is not a Member field at all; it lives on
the Chapter Member child table row the application flow writes at submission
time (services/member/approval/application_helpers.py::
create_pending_chapter_membership), mirroring how the already-working sibling
api/membership_application_review.py::get_pending_applications resolves it.

## The scoping requirement (#1486 item 3 / #1365's census)

This page's `recent_approvals`/`recent_rejections` listings were flagged as
app-wide, unscoped per-member listings gated only by the generic
`@standard_api(REPORTING)` MEDIUM tier -- which "Verenigingen Chapter Board
Member", "Verenigingen Volunteer" and "Verenigingen Auditor" all clear on
their own. #1486 could not confirm the leak live because the endpoint 500ed
for everyone; making it work again re-opens that leak unless scoped. Fixed the
same way as #1329's shape (see test_sepa_mandate_diagnostics_chapter_scope.py):
Roles.ADMIN_ROLES sees everything unrestricted; a Chapter Board Member with an
ACTIVE seat sees only their own chapter(s) (resolved via
`permissions._get_board_chapters_for_member()`, not a new definition of "my
chapter's members"); everyone else (no active board seat) sees nothing.

Both endpoints are decorated with `@standard_api(...)`, which -- confirmed
live via the RED run below -- always sets `SecurityLevel.MEDIUM` regardless of
the `operation_type` argument passed (`operation_type` only classifies for
rate-limiting; only `@high_security_api` raises the tier to HIGH). MEDIUM is
cleared by "Verenigingen Chapter Board Member", "Verenigingen Volunteer" AND
"Verenigingen Auditor" role profiles alike (ROLE_PROFILE_SECURITY_MAPPING), so
for BOTH endpoints the "sees nothing" behaviour for a Volunteer/Auditor caller
must come from this file's own scoping code (an empty list / a zeroed stats
dict) -- there is no tier-gate refusal to lean on here.
"""

from frappe.utils import add_days, today

from verenigingen.pages.membership_applications import get_application_stats, get_pending_applications
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin


def _make_pending_applicant(test_case, chapter_name, first_name):
    """A Pending applicant holding an ACTIVE Chapter Member row for `chapter_name`
    (the live equivalent of the removed `suggested_chapter` field)."""
    member = test_case.create_test_member(first_name=first_name)
    test_case.add_member_to_test_chapter(member.name, chapter_name)
    member.reload()
    member.application_status = "Pending"
    member.status = "Pending"
    member.save(ignore_permissions=True)
    member.reload()
    return member


def _make_reviewed_applicant(test_case, chapter_name, first_name, *, approved):
    """A member whose application was reviewed (approved or rejected) within
    the last 30 days, still holding a Chapter Member row for `chapter_name`
    (true for an approval; a real rejection deletes this row -- see the
    "opposite harm" note in TestGetApplicationStatsChapterScope below)."""
    member = test_case.create_test_member(first_name=first_name)
    test_case.add_member_to_test_chapter(member.name, chapter_name)
    member.reload()
    member.application_status = "Approved" if approved else "Rejected"
    member.status = "Active" if approved else "Rejected"
    member.review_date = add_days(today(), -1)
    member.reviewed_by = "Administrator"
    member.save(ignore_permissions=True)
    member.reload()
    return member


class TestMembershipApplicationsPageAdminReproduction(EnhancedTestCase):
    """#1502: both endpoints crashed for EVERY caller, including admins. These
    are the direct red/green regression guards, run as the default
    EnhancedTestCase session user (Administrator, who clears every tier)."""

    def test_get_pending_applications_does_not_crash(self):
        """Before the fix: AttributeError from `frappe.user.has_role(...)`."""
        result = get_pending_applications()
        self.assertIsInstance(result, list)

    def test_get_application_stats_does_not_crash(self):
        """Before the fix: MySQLdb.OperationalError on `suggested_chapter`."""
        result = get_application_stats()
        self.assertIn("total_pending", result)
        self.assertIn("pending_by_chapter", result)
        self.assertIn("recent_approvals", result)
        self.assertIn("recent_rejections", result)

    def test_get_pending_applications_surfaces_chapter_via_chapter_member(self):
        """The `suggested_chapter` key in each returned row must still be
        populated (frontend contract: membership_applications.html reads
        `app.suggested_chapter`) -- from the Chapter Member table, not the
        removed Member field."""
        chapter = self.create_test_chapter()
        applicant = _make_pending_applicant(self, chapter.name, "AdminReproChapter")

        result = get_pending_applications()

        row = next(app for app in result if app["name"] == applicant.name)
        self.assertEqual(row["suggested_chapter"], chapter.name)

    def test_get_application_stats_pending_by_chapter_uses_chapter_member(self):
        chapter = self.create_test_chapter()
        _make_pending_applicant(self, chapter.name, "AdminReproStats")

        stats = get_application_stats()

        self.assertGreaterEqual(stats["pending_by_chapter"].get(chapter.name, 0), 1)


class TestGetPendingApplicationsChapterScope(EnhancedTestCase):
    """#1486 item 3: get_pending_applications must not leak cross-chapter
    applications to a Chapter Board Member, and must refuse a caller with no
    board seat outright (HIGH tier, tier gate itself)."""

    def test_board_member_sees_own_chapter_not_other_chapter(self):
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        applicant_a = _make_pending_applicant(self, chapter_a.name, "ScopePendingA")
        applicant_b = _make_pending_applicant(self, chapter_b.name, "ScopePendingB")

        with self.set_user(board.user):
            result = get_pending_applications()

        names = {app["name"] for app in result}
        self.assertIn(applicant_a.name, names)
        self.assertNotIn(
            applicant_b.name, names, "board member of chapter A must not see chapter B's applications"
        )

    def test_explicit_chapter_filter_for_other_chapter_returns_empty(self):
        """The `chapter` query param must not be a bypass: asking for a
        chapter outside the caller's own board seats must not leak it."""
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        self.create_test_board_member(chapter_a.name)
        board = self.create_test_board_member(chapter_a.name, first_name="Board2")
        _make_pending_applicant(self, chapter_b.name, "ScopeFilterOtherB")

        with self.set_user(board.user):
            result = get_pending_applications(chapter=chapter_b.name)

        self.assertEqual(result, [])

    def test_admin_sees_both_chapters(self):
        """Control: an admin's view must not shrink to empty -- proves the
        scoping isn't just "always return nothing"."""
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        applicant_a = _make_pending_applicant(self, chapter_a.name, "ScopeAdminA")
        applicant_b = _make_pending_applicant(self, chapter_b.name, "ScopeAdminB")

        result = get_pending_applications()

        names = {app["name"] for app in result}
        self.assertIn(applicant_a.name, names)
        self.assertIn(applicant_b.name, names)


class TestGetPendingApplicationsVolunteerRefused(MemberOwnershipProbeMixin, EnhancedTestCase):
    def test_volunteer_sees_no_pending_applications(self):
        """"Verenigingen Volunteer" clears the bare MEDIUM tier
        (`@standard_api` always uses MEDIUM regardless of `operation_type` --
        confirmed live) but holds no active board seat, so this file's own
        scoping code must return an empty list rather than the app-wide one."""
        chapter = self.create_test_chapter()
        _make_pending_applicant(self, chapter.name, "PendingAppsVolunteerVictim")

        user_email, _member = self._user_linked_to_own_member(
            "PendingAppsVolunteerAttacker", "Verenigingen Member", "Verenigingen Volunteer"
        )

        with self.set_user(user_email):
            result = get_pending_applications()

        self.assertEqual(result, [])


class TestGetApplicationStatsChapterScope(EnhancedTestCase):
    """#1486 item 3: get_application_stats's REPORTING/MEDIUM tier is cleared
    by Chapter Board Member, Volunteer AND Auditor role profiles, so the
    "sees nothing" behaviour for the latter two must come from this file's
    own scoping code (an empty/zeroed stats dict), not from the tier gate."""

    def test_board_member_pending_by_chapter_excludes_other_chapter(self):
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        _make_pending_applicant(self, chapter_a.name, "ScopeStatsA")
        _make_pending_applicant(self, chapter_b.name, "ScopeStatsB")

        with self.set_user(board.user):
            stats = get_application_stats()

        self.assertIn(chapter_a.name, stats["pending_by_chapter"])
        self.assertNotIn(
            chapter_b.name,
            stats["pending_by_chapter"],
            "board member of chapter A must not see chapter B's pending count",
        )
        self.assertEqual(stats["total_pending"], 1)

    def test_board_member_recent_approvals_excludes_other_chapter(self):
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        board = self.create_test_board_member(chapter_a.name)

        approved_a = _make_reviewed_applicant(self, chapter_a.name, "ScopeApprovedA", approved=True)
        approved_b = _make_reviewed_applicant(self, chapter_b.name, "ScopeApprovedB", approved=True)

        with self.set_user(board.user):
            stats = get_application_stats()

        names = {row["full_name"] for row in stats["recent_approvals"]}
        self.assertIn(approved_a.full_name, names)
        self.assertNotIn(
            approved_b.full_name,
            names,
            "board member of chapter A must not see chapter B's recent approvals",
        )
        # The frontend (membership_applications.html) reads
        # stats.recent_approvals[i].current_chapter_display for display.
        row_a = next(r for r in stats["recent_approvals"] if r["full_name"] == approved_a.full_name)
        self.assertEqual(row_a["current_chapter_display"], chapter_a.name)

    def test_volunteer_sees_all_zero_stats(self):
        """A Volunteer clears the bare MEDIUM tier but holds no active board
        seat -- must see an empty/zeroed stats dict, not another chapter's
        data and not a raised exception (MEDIUM is legitimately cleared)."""
        chapter = self.create_test_chapter()
        _make_pending_applicant(self, chapter.name, "ScopeStatsVolunteer")

        user_email, _member = MemberOwnershipProbeMixin._user_linked_to_own_member(
            self, "StatsVolunteerAttacker", "Verenigingen Member", "Verenigingen Volunteer"
        )

        with self.set_user(user_email):
            stats = get_application_stats()

        self.assertEqual(stats["total_pending"], 0)
        self.assertEqual(stats["pending_by_chapter"], {})
        self.assertEqual(stats["recent_approvals"], [])
        self.assertEqual(stats["recent_rejections"], [])

    def test_admin_sees_both_chapters(self):
        """Control: an admin's view must not shrink to empty."""
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        _make_pending_applicant(self, chapter_a.name, "ScopeStatsAdminA")
        _make_pending_applicant(self, chapter_b.name, "ScopeStatsAdminB")

        stats = get_application_stats()

        self.assertIn(chapter_a.name, stats["pending_by_chapter"])
        self.assertIn(chapter_b.name, stats["pending_by_chapter"])
        self.assertEqual(stats["total_pending"], 2)
