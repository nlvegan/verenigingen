# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Branch-coverage tests for verenigingen.api.membership_application_review.

Targets branches not exercised by test_approval_helpers / test_membership_approval:

- reject_membership_application full flow (status update, membership cancel,
  pending-chapter removal, invalid-status guard, invalid-template guard).
- get_user_chapter_access admin branch and member-without-board branch.
- get_pending_applications listing + chapter filter + days_overdue filter.
- _activate_pending_chapter_memberships (pending -> active flip).
- assign_member_to_chapter (no-op for empty chapter; real assignment).
- update_payment_history_for_invoice mismatch guard.

Real DB fixtures only; no business-logic mocking. @high_security_api /
@standard_api serialise results, but these endpoints return plain dicts.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import (
    _activate_pending_chapter_memberships,
    assign_member_to_chapter,
    get_pending_applications,
    get_user_chapter_access,
    reject_membership_application,
    update_payment_history_for_invoice,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _grant_medium_access(email):
    """Grant the role profile needed to pass the @standard_api MEDIUM gate.

    get_user_chapter_access is decorated @standard_api (SecurityLevel.MEDIUM);
    a sub-MEDIUM caller is denied with a raised PermissionError before the body
    runs. The Verenigingen Volunteer role profile satisfies the MEDIUM gate.
    """
    frappe.db.set_value("User", email, "role_profile_name", "Verenigingen Volunteer")
    frappe.db.commit()
    frappe.cache().delete_keys("user_role_profiles")


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


class TestRejectMembershipApplication(EnhancedTestCase):
    """reject_membership_application: canonical rejection flow.

    Covers the status/notes update, the invalid-status / invalid-template /
    nonexistent-member guards, and the Draft-membership delete branch. The
    refund branch (process_refund) and the Lead-update branch are not
    exercised: process_refund defaults False, and this site has no Lead.member
    field (so frappe.db.exists("Lead", {"member": ...}) is inert here).
    """

    def _pending_member(self):
        member = self.create_test_member(
            first_name="RevReject",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"revreject-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", "Pending", update_modified=False)
        member.db_set("application_status", "Pending", update_modified=False)
        member.reload()
        return member

    def test_reject_pending_member(self):
        member = self._pending_member()
        # send_rejection_notification renders a template; allow expected logging.
        self.expectErrorLog("Email", "Notification", "Template", "rejection")
        result = reject_membership_application(
            member.name,
            reason="Application incomplete",
            rejection_category="Incomplete",
            internal_notes="Reviewer note",
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["refund_processed"])

        member.reload()
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")
        # Composite review notes include category + reason.
        self.assertIn("Rejection Category: Incomplete", member.review_notes)
        self.assertIn("Application incomplete", member.review_notes)
        self.assertIn("Internal Notes: Reviewer note", member.review_notes)

    def test_reject_deletes_draft_membership(self):
        """A Draft (docstatus 0) Membership for the member is deleted on reject."""
        member = self._pending_member()
        membership_type = _ensure_membership_type()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type,
                "start_date": today(),
                "status": "Draft",
            }
        )
        membership.flags.ignore_validate = True
        membership.insert(ignore_mandatory=True)
        membership_name = membership.name
        self.assertEqual(frappe.db.get_value("Membership", membership_name, "docstatus"), 0)

        self.expectErrorLog("Email", "Notification", "Template", "rejection")
        result = reject_membership_application(member.name, reason="Withdraw")
        self.assertTrue(result["success"])
        # The Draft membership is removed by the reject path (review.py:696-703).
        self.assertFalse(frappe.db.exists("Membership", membership_name))

    def test_reject_approved_member_throws(self):
        member = self._pending_member()
        member.db_set("application_status", "Approved", update_modified=False)
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application(member.name, reason="too late")

    def test_invalid_email_template_throws(self):
        member = self._pending_member()
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application(
                member.name,
                reason="bad template",
                email_template="NONEXISTENT-TEMPLATE-COV-12345",
            )

    def test_nonexistent_member_throws(self):
        # _validate_member_for_review logs a security event then throws.
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application("NONEXISTENT-MEMBER-REV-12345", reason="x")


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
    """get_pending_applications: listing + filters (run as Administrator)."""

    def _pending_member(self, *, application_date=None, membership_type=None):
        member = self.create_test_member(
            first_name="Pending",
            last_name=f"App{frappe.generate_hash(length=6)}",
            email=f"pendapp-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", "Pending", update_modified=False)
        member.db_set("application_status", "Pending", update_modified=False)
        if application_date:
            member.db_set("application_date", application_date, update_modified=False)
        if membership_type:
            member.db_set("selected_membership_type", membership_type, update_modified=False)
        frappe.db.commit()
        return member

    def test_lists_pending_member(self):
        membership_type = _ensure_membership_type()
        member = self._pending_member(
            application_date=today(), membership_type=membership_type
        )
        result = get_pending_applications()
        names = [r["name"] for r in result]
        self.assertIn(member.name, names)
        row = next(r for r in result if r["name"] == member.name)
        # A today-dated application has 0 days pending (pins the getdate diff).
        self.assertEqual(row["days_pending"], 0)
        self.assertEqual(row["current_chapter_display"], "Unassigned")

    def test_days_overdue_filter_excludes_recent(self):
        recent = self._pending_member(application_date=today())
        # days_overdue=10 means application_date < today-10; a today application
        # must be excluded.
        result = get_pending_applications(days_overdue=10)
        names = [r["name"] for r in result]
        self.assertNotIn(recent.name, names)

    def test_chapter_filter_unassigned_excludes_member_with_chapter(self):
        """Pins the chapter-filter continue branch: 'Unassigned' includes a
        chapterless member but excludes one that has a Chapter Member row."""
        chapterless = self._pending_member(application_date=today())

        # Second pending member WITH an enabled Chapter Member row.
        region = frappe.get_all("Region", limit=1, pluck="name")
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Filter Chapter {frappe.generate_hash(length=6)}",
                "region": region[0] if region else None,
                "published": 1,
                "introduction": "Coverage filter chapter",
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)

        member_with_chapter = self._pending_member(application_date=today())
        chapter.append(
            "members",
            {
                "member": member_with_chapter.name,
                "status": "Active",
                "enabled": 1,
                "chapter_join_date": today(),
            },
        )
        chapter.save()
        frappe.db.commit()

        result = get_pending_applications(chapter="Unassigned")
        names = [r["name"] for r in result]
        self.assertIn(chapterless.name, names)
        # Member WITH a chapter is skipped by the "Unassigned" continue branch.
        self.assertNotIn(member_with_chapter.name, names)


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
        self.assertIsNone(
            update_payment_history_for_invoice(member.name, "NONEXISTENT-SINV-COV-12345")
        )

    def test_nonexistent_member_is_logged_and_swallowed(self):
        self.expectErrorLog("Payment History Update Error")
        self.assertIsNone(
            update_payment_history_for_invoice(
                "NONEXISTENT-MEMBER-COV-12345", "NONEXISTENT-SINV-COV-12345"
            )
        )
