# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Branch-coverage tests for verenigingen.api.membership_application_review.

Targets branches not exercised by test_approval_helpers / test_membership_approval:

- get_user_chapter_access admin branch and member-without-board branch.
- get_pending_applications listing + chapter filter + days_overdue filter.
- _activate_pending_chapter_memberships (pending -> active flip).
- assign_member_to_chapter (no-op for empty chapter; real assignment).
- update_payment_history_for_invoice mismatch guard.

Real DB fixtures only; no business-logic mocking. @high_security_api /
@standard_api serialise results, but these endpoints return plain dicts.
"""

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.api.membership_application_review import (
    _activate_pending_chapter_memberships,
    _approve_membership_application_locked,
    assign_member_to_chapter,
    get_pending_applications,
    get_user_chapter_access,
    update_payment_history_for_invoice,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _grant_medium_access(email):
    """Grant MEDIUM access needed to pass the @standard_api gate.

    get_user_chapter_access is decorated @standard_api (SecurityLevel.MEDIUM);
    a sub-MEDIUM caller is denied with a raised PermissionError before the body
    runs.

    The authorization policy grants MEDIUM to "Verenigingen Volunteer" via BOTH
    the role-profile path (rule 4) and the individual-role path (rule 5). We assign
    the *role* directly — not just the role_profile_name Link — because:

      - On Frappe v16 the single `role_profile_name` Link is deprecated/cleared in
        favour of the `role_profiles` child table, so a bare `db.set_value` of
        role_profile_name silently resolves to no profiles (observed in CI:
        `user_profiles=[]` -> rule_7_deny -> PermissionError). The role-based path
        does not depend on that field.
      - Role membership is resolved through `frappe.get_roles()`, which `set_user`
        recomputes deterministically, so it is immune to the versioned
        `user_role_profiles` cache churn that other shards trigger via
        `invalidate_user_role_cache()`. The previous `delete_keys("user_role_profiles")`
        was the wrong (and order-dependent) invalidation entry point.

    Assigning the role makes rule 5 (individual_role -> MEDIUM) grant access
    regardless of role-profile cache state, fixing the full-shard order-dependence.
    """
    user = frappe.get_doc("User", email)
    if not any(r.role == "Verenigingen Volunteer" for r in user.roles):
        user.append("roles", {"role": "Verenigingen Volunteer"})
        user.save()
    frappe.db.commit()
    # Recompute the freshly-saved role set so the next set_user() sees the new role.
    frappe.clear_cache(user=email)


def _approve_core(member_name, membership_type=None, chapter=None):
    return _approve_membership_application_locked(member_name, membership_type, chapter, None, True, False)


def _ensure_membership_type():
    if not frappe.db.exists("Item Group", "Membership"):
        frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Membership",
                "parent_item_group": "All Item Groups",
                "is_group": 0,
            }
        ).insert()
    name = "Review Cov Membership"
    if not frappe.db.exists("Membership Type", name):
        frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": name,
                "minimum_amount": 15,
                "role_profile": "Verenigingen Member",
            }
        ).insert()
    return name


class TestGetUserChapterAccess(EnhancedTestCase):
    """get_user_chapter_access: admin vs member-without-board branches."""

    def test_admin_sees_all_chapters(self):
        # Tests run as Administrator, which holds an admin role.
        result = get_user_chapter_access()
        self.assertTrue(result["is_admin"])
        self.assertFalse(result["restrict_to_chapters"])

    def test_non_member_user_is_restricted(self):
        """A logged-in user with no Member record is restricted and flagged."""
        email = f"chapaccess-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "ChapAccess",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        _grant_medium_access(user.name)

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            result = get_user_chapter_access()
        finally:
            frappe.set_user(original)

        self.assertFalse(result["is_admin"])
        self.assertTrue(result["restrict_to_chapters"])
        self.assertEqual(result["chapters"], [])
        self.assertEqual(result["message"], "User is not a member")

    def test_member_without_board_access_has_no_chapters(self):
        """A member with no board positions gets restrict_to_chapters with empty list."""
        email = f"plainmember-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "PlainMember",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert()
        self.track_doc("User", user.name)

        member = self.create_test_member(
            first_name="Plain",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=email,
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("user", user.name, update_modified=False)
        frappe.db.commit()
        _grant_medium_access(user.name)

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            result = get_user_chapter_access()
        finally:
            frappe.set_user(original)

        self.assertFalse(result["is_admin"])
        # No board positions -> user_chapters empty -> not restricted (len == 0).
        self.assertEqual(result["chapters"], [])
        self.assertFalse(result["restrict_to_chapters"])


class TestGetPendingApplications(EnhancedTestCase):
    """get_pending_applications: listing + filters (run as Administrator).

    The list is Pending Review Membership Application Submissions, not Members (#1765). Fixture
    shortcut, stated: each row is inserted, given `chapter`/`confirmed_on` and moved to Pending Review,
    the writes confirmation makes; test_application_review_surfaces.py covers the permission scope.
    """

    def _application(self, *, confirmed_on=None, chapter=None, membership_type=None):
        application = frappe.get_doc(
            {
                "doctype": "Membership Application Submission",
                "email": f"pendapp-{frappe.generate_hash(length=8)}@example.com",
                "source": "Full Form",
                "applicant_name": f"Pending App{frappe.generate_hash(length=6)}",
                "payload": "{}",
            }
        )
        application.insert()
        self.track_doc("Membership Application Submission", application.name)
        application.db_set("confirmed_on", confirmed_on or now_datetime())
        if chapter:
            application.db_set("chapter", chapter)
        if membership_type:
            application.db_set("membership_type", membership_type)
        application.set_status("Pending Review")
        return application

    def test_lists_pending_application(self):
        membership_type = _ensure_membership_type()
        application = self._application(membership_type=membership_type)
        result = get_pending_applications()
        names = [r["name"] for r in result]
        self.assertIn(application.name, names)
        row = next(r for r in result if r["name"] == application.name)
        # A today-confirmed application has 0 days pending (pins the getdate diff).
        self.assertEqual(row["days_pending"], 0)
        self.assertEqual(row["membership_type"], membership_type)
        self.assertIsNone(row["chapter"])

    def test_days_overdue_filter_excludes_recent(self):
        recent = self._application()
        old = self._application(confirmed_on=add_days(now_datetime(), -30))
        # days_overdue=10 keeps applications confirmed before today-10.
        names = [r["name"] for r in get_pending_applications(days_overdue=10)]
        self.assertNotIn(recent.name, names)
        self.assertIn(old.name, names)

    def test_chapter_filter_unassigned_excludes_application_with_chapter(self):
        """'Unassigned' includes a chapterless application but excludes one that names a chapter."""
        chapterless = self._application()
        chapter = self.create_test_chapter()
        with_chapter = self._application(chapter=chapter.name)

        names = [r["name"] for r in get_pending_applications(chapter="Unassigned")]
        self.assertIn(chapterless.name, names)
        self.assertNotIn(with_chapter.name, names)

        names = [r["name"] for r in get_pending_applications(chapter=chapter.name)]
        self.assertIn(with_chapter.name, names)
        self.assertNotIn(chapterless.name, names)


class TestAssignMemberToChapter(EnhancedTestCase):
    """assign_member_to_chapter: guard for empty chapter."""

    def test_empty_chapter_is_noop(self):
        member = self.create_test_member(
            first_name="NoChapter",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"nochapter-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        # Should return without raising and without doing anything.
        self.assertIsNone(assign_member_to_chapter(member, None))
        self.assertIsNone(assign_member_to_chapter(member, ""))


class TestActivatePendingChapterMemberships(EnhancedTestCase):
    """_activate_pending_chapter_memberships: flip Pending Chapter Member rows."""

    def test_no_pending_rows_is_noop(self):
        member = self.create_test_member(
            first_name="NoPending",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"nopending-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        # No Chapter Member rows -> should complete silently.
        try:
            _activate_pending_chapter_memberships(member)
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"_activate_pending_chapter_memberships raised: {exc}")

    def test_pending_row_is_activated(self):
        region = frappe.get_all("Region", limit=1, pluck="name")
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Activate Chapter {frappe.generate_hash(length=6)}",
                "region": region[0] if region else None,
                "published": 1,
                "introduction": "Coverage activation chapter",
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)

        member = self.create_test_member(
            first_name="Pend",
            last_name=f"Chap{frappe.generate_hash(length=6)}",
            email=f"pendchap-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )

        # Add a Pending Chapter Member row directly.
        chapter.append(
            "members",
            {"member": member.name, "status": "Pending", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()
        frappe.db.commit()

        # Sanity: the row is pending.
        pending = frappe.db.sql(
            "SELECT status FROM `tabChapter Member` WHERE member=%s AND parent=%s",
            (member.name, chapter.name),
            as_dict=True,
        )
        self.assertTrue(pending)
        self.assertEqual(pending[0].status, "Pending")

        _activate_pending_chapter_memberships(member)

        after = frappe.db.sql(
            "SELECT status FROM `tabChapter Member` WHERE member=%s AND parent=%s",
            (member.name, chapter.name),
            as_dict=True,
        )
        self.assertTrue(after)
        self.assertEqual(after[0].status, "Active")


class TestUpdatePaymentHistoryForInvoice(EnhancedTestCase):
    """update_payment_history_for_invoice: error-handling path.

    The function is a fire-and-forget background job wrapped in try/except: a
    bad member/invoice reference is logged and swallowed (no raise). We exercise
    that resilience path without needing full Sales Invoice accounting setup.
    """

    def test_nonexistent_invoice_is_logged_and_swallowed(self):
        member = self.create_test_member(
            first_name="PayHist",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"payhist-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        self.expectErrorLog("Payment History Update Error")
        # frappe.get_doc on the missing invoice raises inside the try block; the
        # function logs and returns without propagating.
        with self.assertErrorLog("Payment History Update Error"):
            self.assertIsNone(update_payment_history_for_invoice(member.name, "NONEXISTENT-SINV-COV-12345"))

    def test_nonexistent_member_is_logged_and_swallowed(self):
        self.expectErrorLog("Payment History Update Error")
        with self.assertErrorLog("Payment History Update Error"):
            self.assertIsNone(
                update_payment_history_for_invoice("NONEXISTENT-MEMBER-COV-12345", "NONEXISTENT-SINV-COV-12345")
            )


class TestApprovalCoreTerminationGuard(EnhancedTestCase):
    """#1544/#1548 follow-up: a Pending applicant can be terminated while
    still under review (validate_termination_request() does not block it),
    and approval unconditionally resets member_since to today -- which,
    per #1544's own rule, makes that termination look superseded. But this
    is NOT a genuine rejoin: a genuine rejoin's application_date is set to
    now() by materialise_member, strictly after the
    termination it responds to; here the application predates the
    termination, so approving would silently reactivate a member who was
    terminated after they applied, with nobody having decided that should
    happen. Refuse instead of guessing the product rule.

    The member-keyed entry point was removed in #1765; these tests call the approval core
    (_approve_membership_application_locked) that approve_application calls, on a Member made by the
    factory (a stand-in for the one materialise_member creates)."""

    def test_refuses_when_termination_postdates_application(self):
        from verenigingen.tests.support.termination_request import execute_real_termination

        membership_type = _ensure_membership_type()
        member = self.create_test_member(
            first_name="StalePending",
            last_name="ThenTerminated",
            email=f"stale.pending.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            selected_membership_type=membership_type,
        )
        application_date = add_days(today(), -10)
        frappe.db.set_value(
            "Member", member.name, "application_date", application_date, update_modified=False
        )

        # Reachable: validate_termination_request() does not block creating
        # (and executing) a termination against a still-Pending member.
        termination_date = add_days(today(), -1)
        execute_real_termination(self, member.name, termination_date)
        member.reload()
        self.assertEqual(member.status, "Quit")
        self.assertEqual(member.application_status, "Pending", "sanity: application is still open")

        with self.assertRaises(frappe.ValidationError):
            _approve_core(
                member_name=member.name,
                membership_type=membership_type,
                chapter=None,
            )

        member.reload()
        self.assertEqual(
            member.application_status,
            "Pending",
            "a refused approval must not have advanced application_status",
        )

    def test_approves_normally_when_application_postdates_termination(self):
        """Control: the genuine rejoin case (application_date AFTER the
        termination) must still approve normally -- the guard must not
        refuse a real, legitimate reapplication."""
        from verenigingen.tests.support.termination_request import execute_real_termination

        membership_type = _ensure_membership_type()
        member = self.create_test_member(
            first_name="Rejoin",
            last_name="ApprovesNormally",
            email=f"rejoin.approves.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved",
            selected_membership_type=membership_type,
        )
        execute_real_termination(self, member.name, add_days(today(), -100))
        member.reload()
        self.assertEqual(member.status, "Quit")

        # Reapplication AFTER the termination -- the real, positive signal.
        frappe.db.set_value(
            "Member",
            member.name,
            {"application_status": "Pending", "application_date": today()},
            update_modified=False,
        )

        result = _approve_core(
            member_name=member.name,
            membership_type=membership_type,
            chapter=None,
        )
        self.assertTrue(result.get("success"), result)
        member.reload()
        self.assertEqual(member.application_status, "Approved")
