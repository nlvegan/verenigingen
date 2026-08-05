# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Tests for chapter_permission_service.get_user_board_chapters().

This helper decides which chapters the board-facing portal pages
(/chapter_dashboard and /volunteer/skills) let a user act on. It was previously
copy-pasted into both pages and the copies had silently diverged on their admin
role set: volunteer/skills.py included Verenigingen Staff, chapter_dashboard.py
did not, so a staff member who was not a board member saw every chapter on one
page and none on the other (docs/audits/2026-07-17-portal-pages-code-quality-audit.md,
LIVE-1).

Both pages now share this one implementation and staff is treated as an
administrator on both. Note this is deliberately broader than
ChapterPermissionService.get_permission_query_conditions(), which still limits
staff to published chapters in list views.

Real data, no business-logic mocking.
"""

import frappe

from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestGetUserBoardChapters(EnhancedTestCase):
    """Role-driven behaviour of the shared board-chapter lookup."""

    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=8)

        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST Board Chapters {run}",
            region="Test Region Board",
        )

        # Board member: member -> volunteer -> active Chapter Board Member row.
        self.board_email = f"bc-board-{run}@example.com"
        self.board_member = self.create_test_member(
            first_name="Board", last_name="Chapters", email=self.board_email, birth_date="1985-01-01"
        )
        self.board_member.db_set("status", "Active")
        self.board_member.db_set("user", self._ensure_user(self.board_email, "Board"))
        self.volunteer = self.create_test_volunteer(member_name=self.board_member.name)

        self._ensure_chapter_role("Chapter Head")
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": "Chapter Head",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

        # Staff member who is deliberately NOT a board member anywhere.
        #
        # The role alone is not enough to model a real staff user: the API security
        # framework authorizes on Frappe ROLE PROFILES, not roles
        # (authorization_policy.ROLE_PROFILE_SECURITY_MAPPING keyed by profile name,
        # resolved via AuthorizationEngine.get_user_role_profiles). Every enabled
        # Verenigingen Staff user on production carries role_profile_name
        # "Verenigingen Staff"; without it the @high_security_api endpoints deny with
        # "Your profiles: none" and the staff-access tests below would pass for the
        # wrong reason.
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        self.staff_email = f"bc-staff-{run}@example.com"
        self.staff_member = self.create_test_member(
            first_name="Staff", last_name="Chapters", email=self.staff_email, birth_date="1986-01-01"
        )
        self.staff_member.db_set("user", self._ensure_user(self.staff_email, "Staff", "Verenigingen Staff"))
        # Assert rather than `if exists`: a skipped assignment would leave the staff tests
        # silently exercising a profile-less user, which the security framework denies for a
        # reason unrelated to what they assert.
        self.assertTrue(
            frappe.db.exists("Role Profile", "Verenigingen Staff"),
            "Role Profile 'Verenigingen Staff' must exist - the staff tests below depend on it",
        )
        assign_role_profile_to_user(self.staff_email, "Verenigingen Staff")

    def _ensure_user(self, email, first_name, extra_role=None):
        if not frappe.db.exists("User", email):
            roles = [{"role": "Verenigingen Member"}]
            if extra_role:
                roles.append({"role": extra_role})
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": first_name,
                    "send_welcome_email": 0,
                    "roles": roles,
                }
            ).insert(ignore_permissions=True)
        return email

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert(
                ignore_permissions=True
            )

    def _create_active_board_member(self, chapter_name, volunteer_name, role="Chapter Head"):
        """Attach an active board row. Privileged data creation belongs in a helper,
        not a test body - test-quality-enforcer rejects ignore_permissions there."""
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

    def _names(self, rows):
        return {r.get("chapter_name") for r in rows}

    # ------------------------------------------------------------------
    # The divergence this consolidation fixed
    # ------------------------------------------------------------------

    def test_staff_who_is_not_a_board_member_sees_all_chapters(self):
        """Verenigingen Staff short-circuits to every chapter.

        This is the behaviour that used to differ per page: staff saw all chapters
        on /volunteer/skills and none on /chapter_dashboard. Asserts the full count,
        not just membership - a partial grant is also wrong.
        """
        with self.as_user(self.staff_email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))
        self.assertEqual(len(chapters), frappe.db.count("Chapter"))

    def test_staff_result_is_not_limited_to_board_membership(self):
        """The staff grant must not fall through to the board-member walk.

        The staff user holds no Chapter Board Member row, so without the
        short-circuit this would be empty.
        """
        with self.as_user(self.staff_email):
            staff_chapters = get_user_board_chapters()
        with self.as_user(self.board_email):
            board_chapters = get_user_board_chapters()

        self.assertGreater(len(staff_chapters), len(board_chapters))

    def test_both_portal_pages_use_this_one_implementation(self):
        """Regression guard against the copy-paste re-appearing.

        The two pages previously defined their own get_user_board_chapters and
        drifted apart on the admin role set. Importing the same object is what
        keeps them from diverging again.
        """
        from verenigingen.templates.pages.chapter_dashboard import (
            get_user_board_chapters as dashboard_fn,
        )
        from verenigingen.templates.pages.volunteer.skills import (
            get_user_board_chapters as skills_fn,
        )

        self.assertIs(dashboard_fn, get_user_board_chapters)
        self.assertIs(skills_fn, get_user_board_chapters)

    # ------------------------------------------------------------------
    # Authorization scope of the staff grant (owner decision, 2026-07-17)
    # ------------------------------------------------------------------

    def test_staff_may_read_chapter_member_emails(self):
        """Staff act as read-only administrators over every chapter.

        This helper is the only chapter gate for eight whitelisted read endpoints in
        api/chapter_dashboard_api.py - the security decorators gate on tier, not
        chapter, and authorization_policy.py grants staff HIGH/MEDIUM/LOW. Including
        staff here therefore opens member-email access across all chapters. That is an
        explicit decision; this pins it so it cannot change by accident.

        Asserts the seeded member's address is actually returned. `assertIsInstance(
        ..., list)` would pass on an empty list from a chapter with no members, and so
        would not demonstrate the exposure it claims to pin.
        """
        from verenigingen.api.chapter_dashboard_api import get_chapter_member_emails
        from verenigingen.utils.performance_utils import CacheManager

        # get_chapter_member_emails is @cached(ttl=300) with a user-agnostic key, so a
        # warm entry from another test would return without consulting the gate and
        # this test would pass without exercising staff access at all.
        CacheManager._cache.clear()
        CacheManager._cache_ttl.clear()

        # The board fixture already registers this member as an active Chapter Member,
        # so the chapter has a known address to find.
        self.assertTrue(
            frappe.db.exists(
                "Chapter Member",
                {"parent": self.chapter.name, "member": self.board_member.name, "enabled": 1},
            ),
            "fixture precondition: the board member must be an active chapter member",
        )

        with self.as_user(self.staff_email):
            emails = get_chapter_member_emails(self.chapter.name)

        self.assertIsInstance(emails, list)
        self.assertIn(self.board_email, emails)

    def test_staff_may_not_approve_members(self):
        """The safety property that keeps the staff grant read-only.

        quick_approve_member takes a SECOND gate - get_user_board_role(), which has no
        staff branch and returns None - so staff are denied despite seeing every
        chapter. If someone ever adds staff to get_user_board_role's admin
        short-circuit, this fails, and that is the point.

        The denial is a RETURN value, not an exception: @handle_api_error converts the
        frappe.throw into an OperationResult/dict. Asserting assertRaises here would
        fail even though access is correctly denied.
        """
        from verenigingen.api.chapter_dashboard_api import quick_approve_member

        with self.as_user(self.staff_email):
            result = quick_approve_member(member_name=self.board_member.name, chapter_name=self.chapter.name)

        payload = result.to_dict() if hasattr(result, "to_dict") else result
        self.assertFalse(payload.get("success"))
        self.assertIn("permission", str(payload).lower())

    def test_staff_have_no_board_role(self):
        """get_user_board_role() must stay staff-free - it is what denies mutations."""
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_role

        with self.as_user(self.staff_email):
            self.assertIsNone(get_user_board_role(self.chapter.name))

    def test_member_emails_are_not_served_from_another_users_warm_cache(self):
        """A warm cache must not bypass the chapter check (SEC-1 regression).

        get_chapter_member_emails once had @cached(ttl=300) as its INNERMOST decorator,
        so a cache hit returned before the in-body chapter check ran. The cache key
        carries no user and CacheManager._cache is process-wide, so once any authorized
        caller warmed a chapter, every user clearing the HIGH tier read that chapter's
        member emails for five minutes. Demonstrated on production data with a board
        member of another chapter: 110 addresses.

        The fix caches only the chapter-scoped query (_fetch_chapter_member_emails) and
        keeps the access check in the whitelisted caller. This test warms the cache as an
        authorized user, then asserts an unauthorized one is still refused.
        """
        from verenigingen.api.chapter_dashboard_api import get_chapter_member_emails
        from verenigingen.utils.performance_utils import CacheManager

        CacheManager._cache.clear()
        CacheManager._cache_ttl.clear()

        # Warm the cache as staff, who legitimately have access.
        with self.as_user(self.staff_email):
            warm = get_chapter_member_emails(self.chapter.name)
        self.assertIn(self.board_email, warm)

        # The probe must CLEAR the HIGH tier yet hold no chapter rights - otherwise
        # @high_security_api refuses it before the chapter check and the cache bypass is
        # never exercised (a plain member is rejected at the tier gate, so it proves
        # nothing here). In production that principal is a board member of a DIFFERENT
        # chapter, which is how this leak was demonstrated on real data; the test sites
        # carry no "Verenigingen Chapter Board Member" role profile, and Treasurer /
        # National Board Member both include the Verenigingen Staff role, which would make
        # the probe an administrator. "Verenigingen Webhook User" clears HIGH
        # (authorization_policy.py) and grants no admin, staff or board role.
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        outsider = f"bc-outsider-{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(
            first_name="Outsider", last_name="Chapters", email=outsider, birth_date="1991-01-01"
        )
        member.db_set("user", self._ensure_user(outsider, "Outsider"))
        self.assertTrue(frappe.db.exists("Role Profile", "Verenigingen Webhook User"))
        assign_role_profile_to_user(outsider, "Verenigingen Webhook User")

        with self.as_user(outsider):
            self.assertEqual(get_user_board_chapters(), [], "probe must hold no chapter rights")
            result = get_chapter_member_emails(self.chapter.name)

        self.assertNotIsInstance(
            result, list, f"warm cache leaked emails to an unauthorized user: {result!r}"
        )

    # ------------------------------------------------------------------
    # Behaviour preserved for everyone else
    # ------------------------------------------------------------------

    def test_board_member_sees_only_their_chapter(self):
        """Exactly their own chapter - not a superset.

        assertIn would pass if a bug handed board members every chapter, which is
        the very failure this consolidation could introduce.
        """
        with self.as_user(self.board_email):
            chapters = get_user_board_chapters()

        self.assertEqual(self._names(chapters), {self.chapter.name})

    def test_board_member_rows_carry_role_fields(self):
        """chapter_dashboard.html reads more than chapter_name on the board path."""
        with self.as_user(self.board_email):
            chapters = get_user_board_chapters()

        row = next(c for c in chapters if c.get("chapter_name") == self.chapter.name)
        self.assertEqual(row.get("chapter_role"), "Chapter Head")
        self.assertEqual(row.get("is_active"), 1)
        self.assertIn("region", row)

    def test_plain_member_sees_no_chapters(self):
        email = f"bc-plain-{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(
            first_name="Plain", last_name="Chapters", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", self._ensure_user(email, "Plain"))

        with self.as_user(email):
            self.assertEqual(get_user_board_chapters(), [])

    def test_user_without_member_record_sees_no_chapters(self):
        email = f"bc-nomember-{frappe.generate_hash(length=8)}@example.com"
        self._ensure_user(email, "NoMember")

        with self.as_user(email):
            self.assertEqual(get_user_board_chapters(), [])

    def test_admin_sees_all_chapters(self):
        admin = self.ensure_test_admin_user()
        with self.as_user(admin.email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))
        self.assertEqual(len(chapters), frappe.db.count("Chapter"))

    def test_explicit_user_argument_is_honoured(self):
        """The helper resolves the passed user, not just the session user."""
        with self.as_user(self.board_email):
            as_plain = get_user_board_chapters(user=f"nobody-{frappe.generate_hash(length=6)}@example.com")

        self.assertEqual(as_plain, [])

    # ------------------------------------------------------------------
    # An empty result must mean "no chapters", never "the query broke"
    # ------------------------------------------------------------------

    def test_board_member_whose_login_user_differs_from_member_email(self):
        """Resolve the member the way the rest of the app does: user field first.

        The board ROLE grant resolves through get_member_name_for_user()
        (utils/member_utils.py, via permissions.assign_chapter_board_role), which
        tries Member.user first and falls back to Member.email. This helper
        resolved by Member.email ALONE, so a board member whose login user differs
        from their contact email was granted the Chapter Board Member role and then
        told they had no chapters - role present, access denied.

        That is not hypothetical bookkeeping: this helper is the only chapter gate
        for eight whitelisted endpoints and both board portal pages, and the two
        fields legitimately diverge in production whenever a member's login account
        is not their contact address.
        """
        login_email = f"bc-login-{frappe.generate_hash(length=8)}@example.com"
        contact_email = f"bc-contact-{frappe.generate_hash(length=8)}@example.com"

        member = self.create_test_member(
            first_name="Split", last_name="Identity", email=contact_email, birth_date="1988-01-01"
        )
        member.db_set("status", "Active")
        member.db_set("user", self._ensure_user(login_email, "Split"))
        volunteer = self.create_test_volunteer(member_name=member.name)
        self._create_active_board_member(self.chapter.name, volunteer.name)

        with self.as_user(login_email):
            chapters = get_user_board_chapters()

        self.assertIn(
            self.chapter.name,
            self._names(chapters),
            "a board member whose Member.user differs from Member.email must still "
            f"see their chapter; got {chapters!r}",
        )

    def test_volunteer_with_no_board_rows_sees_no_chapters(self):
        """The genuine empty case: a volunteer holding no Chapter Board Member row.

        Pairs with the test below. Together they pin the distinction that matters:
        [] is a real answer about access, and an infrastructure failure is not
        allowed to imitate it.
        """
        email = f"bc-vol-{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(
            first_name="Vol", last_name="Chapters", email=email, birth_date="1991-01-01"
        )
        member.db_set("user", self._ensure_user(email, "Vol"))
        self.create_test_volunteer(member_name=member.name)

        with self.as_user(email):
            self.assertEqual(get_user_board_chapters(), [])

    def test_query_failure_propagates_instead_of_reading_as_no_access(self):
        """A broken query must raise, not return [].

        This helper is the only chapter gate for eight whitelisted read endpoints
        (see its docstring), so returning [] on error silently reports "no access"
        for what is actually an outage. The failure that really occurs here is a
        MariaDB deadlock (1213) - see
        docs/plans/2026-06-09-order-dependence-tail-handoff.md - which rolls the
        transaction back and takes any frappe.log_error() row with it, leaving no
        trace anywhere. It also leaves the transaction dead, so continuing to issue
        queries against it is not meaningful.
        """
        from unittest.mock import patch

        from verenigingen.utils.constants import Roles

        deadlock = Exception("(1213, 'Deadlock found when trying to get lock; try restarting transaction')")
        real_from = frappe.qb.from_
        board_seen = []

        def fail_only_the_board_query(table, *args, **kwargs):
            """Break the board lookup and nothing else.

            Failing every query would make this test pass for the wrong reason:
            frappe.log_error() writes an Error Log row through the same builder, so
            a blanket patch escapes from the logging call and looks like the
            propagation being asserted here even when the error is still swallowed.
            """
            if getattr(table, "get_table_name", lambda: None)() == "tabChapter Board Member":
                board_seen.append(True)
                raise deadlock
            return real_from(table, *args, **kwargs)

        # Captured BEFORE patching. get_user_board_chapters() has three returns that
        # run before the query under test - the admin/staff short-circuit and the two
        # not-found early returns - and all three are silent. Without these locals a
        # miss reports only "Exception not raised", which is indistinguishable from
        # the swallow bug this test exists to catch. That cost a full CI-log and
        # artifact investigation on 2026-08-05 to rule out; see the memory topic file
        # board-chapters-deadlock-flake-2026-07-27.
        member = frappe.db.get_value("Member", {"email": self.board_email}, "name")
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name") if member else None
        admin_roles = sorted(set(frappe.get_roles(self.board_email)) & Roles.ADMIN_ROLES)

        # Passed explicitly rather than via self.as_user(): every branch of the helper
        # resolves from this argument (frappe.get_all does not check permissions), so
        # the session switch adds nothing here except a way for the test to miss the
        # branch it is aiming at. test_explicit_user_argument_is_honoured pins the
        # argument path; test_board_member_sees_only_their_chapter pins the session one.
        #
        # Patches the query builder, not the permission decision: a deadlock cannot
        # be provoked deterministically from a test, and the branch under test is
        # exactly the one that runs when the database misbehaves.
        raised = None
        with patch("frappe.qb.from_", side_effect=fail_only_the_board_query):
            try:
                get_user_board_chapters(user=self.board_email)
            except Exception as exc:  # noqa: BLE001 - identity is asserted below
                raised = exc

        diag = f"member={member} volunteer={volunteer} admin_roles={admin_roles} raised={raised!r}"
        self.assertTrue(board_seen, f"never reached the board query; {diag}")
        self.assertIsNotNone(raised, f"board query ran but the error was swallowed; {diag}")
        self.assertIn("1213", str(raised), diag)
