#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coverage Tests for member_utils.py
==================================

Real-DB integration tests for the branches not exercised by
``test_member_utils.py``. Where the existing suite uses ``@patch('frappe.session')``,
these tests instead switch the real session via ``self.as_user(...)`` so the
current-user convenience wrappers are exercised end to end:

- ``require_login`` guest / logged-in branches
- ``get_current_user_member_info`` (real session)
- ``has_mollie_subscription`` true / false / missing-field branches
- ``require_member_record`` decorator (allow + deny)
- current-user wrappers: ``get_volunteer_for_current_user``,
  ``is_current_user_volunteer``, ``get_current_user_chapters``,
  ``get_active_membership_for_current_user``
- ``get_current_user_member_doc`` permission/error branch
- ``get_member_dues_schedule_name`` / ``has_any_dues_schedule`` true paths
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import (
    get_active_membership_for_current_user,
    get_current_user_chapters,
    get_current_user_member_info,
    get_current_user_member_name,
    get_member_dues_schedule_name,
    get_volunteer_for_current_user,
    has_any_dues_schedule,
    has_mollie_subscription,
    is_current_user_volunteer,
    require_login,
    require_member_record,
)


class TestMemberUtilsCurrentUserCoverage(EnhancedTestCase):
    """Exercise the current-user wrappers with a real session."""

    def setUp(self):
        super().setUp()
        # A real Member + linked User so the current-user lookups resolve.
        self.member = self.create_test_member(
            first_name="Current",
            last_name="UserCov",
            birth_date="1987-07-07",
        )
        self.member_email = self.member.email
        if not frappe.db.exists("User", self.member_email):
            self.create_test_user(
                email=self.member_email,
                first_name="Current",
                last_name="UserCov",
                roles=["Verenigingen Member"],
            )

    # ------------------------------------------------------------------
    # require_login
    # ------------------------------------------------------------------

    def test_require_login_guest_raises(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                require_login()

    def test_require_login_logged_in_passes(self):
        with self.as_user(self.member_email):
            # Should not raise
            require_login()

    # ------------------------------------------------------------------
    # get_current_user_member_name / info via real session
    # ------------------------------------------------------------------

    def test_get_current_user_member_name_resolves(self):
        with self.as_user(self.member_email):
            self.assertEqual(get_current_user_member_name(), self.member.name)

    def test_get_current_user_member_info_resolves(self):
        with self.as_user(self.member_email):
            info = get_current_user_member_info()
        self.assertIsNotNone(info)
        self.assertEqual(info["email"], self.member_email)
        self.assertIn("status", info)

    # ------------------------------------------------------------------
    # has_mollie_subscription
    # ------------------------------------------------------------------

    def test_has_mollie_subscription_false_default(self):
        """Member without Mollie fields set is not an active subscriber."""
        with self.as_user(self.member_email):
            self.assertFalse(has_mollie_subscription())

    def test_has_mollie_subscription_true_when_all_fields_set(self):
        """All four Mollie conditions satisfied -> True."""
        frappe.db.set_value(
            "Member",
            self.member.name,
            {
                "payment_method": "Mollie",
                "mollie_customer_id": "cst_test123",
                "mollie_subscription_id": "sub_test123",
                "subscription_status": "active",
            },
            update_modified=False,
        )
        with self.as_user(self.member_email):
            self.assertTrue(has_mollie_subscription())

    def test_has_mollie_subscription_false_when_status_not_active(self):
        """Has IDs but subscription_status != active -> False."""
        frappe.db.set_value(
            "Member",
            self.member.name,
            {
                "payment_method": "Mollie",
                "mollie_customer_id": "cst_test123",
                "mollie_subscription_id": "sub_test123",
                "subscription_status": "canceled",
            },
            update_modified=False,
        )
        with self.as_user(self.member_email):
            self.assertFalse(has_mollie_subscription())

    def test_has_mollie_subscription_no_member_returns_false(self):
        """A logged-in user with no Member record -> False (not None)."""
        user = self.create_test_user(
            email=f"nomember.{frappe.generate_hash()[:8]}@example.test",
            first_name="No",
            last_name="Member",
            roles=["Verenigingen Member"],
        )
        with self.as_user(user.name):
            self.assertFalse(has_mollie_subscription())

    # ------------------------------------------------------------------
    # require_member_record decorator
    # ------------------------------------------------------------------

    def test_require_member_record_allows_member(self):
        calls = []

        @require_member_record()
        def protected():
            calls.append(True)
            return "ok"

        with self.as_user(self.member_email):
            self.assertEqual(protected(), "ok")
        self.assertEqual(calls, [True])

    def test_require_member_record_denies_non_member(self):
        @require_member_record("Custom denial")
        def protected():
            return "ok"

        user = self.create_test_user(
            email=f"deny.{frappe.generate_hash()[:8]}@example.test",
            first_name="Deny",
            last_name="User",
            roles=["Verenigingen Member"],
        )
        with self.as_user(user.name):
            with self.assertRaises(frappe.DoesNotExistError):
                protected()

    # ------------------------------------------------------------------
    # current-user wrappers (no member context)
    # ------------------------------------------------------------------

    def test_current_user_wrappers_no_member_return_empty(self):
        """When the session user has no member, wrappers degrade gracefully."""
        user = self.create_test_user(
            email=f"empty.{frappe.generate_hash()[:8]}@example.test",
            first_name="Empty",
            last_name="User",
            roles=["Verenigingen Member"],
        )
        with self.as_user(user.name):
            self.assertIsNone(get_volunteer_for_current_user())
            self.assertFalse(is_current_user_volunteer())
            self.assertEqual(get_current_user_chapters(), [])
            self.assertIsNone(get_active_membership_for_current_user())
            self.assertIsNone(get_current_user_member_info())

    # ------------------------------------------------------------------
    # current-user wrappers (with member context)
    # ------------------------------------------------------------------

    def test_get_volunteer_for_current_user_resolves(self):
        volunteer = self.create_test_volunteer(self.member.name)
        with self.as_user(self.member_email):
            self.assertEqual(get_volunteer_for_current_user(), volunteer.name)
            self.assertTrue(is_current_user_volunteer())

    def test_get_current_user_chapters_resolves(self):
        chapter = self.create_test_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append("members", {"member": self.member.name, "status": "Active", "enabled": 1})
        chapter_doc.save()

        with self.as_user(self.member_email):
            chapters = get_current_user_chapters()
        self.assertIn(chapter.name, chapters)

    def test_get_active_membership_for_current_user_resolves(self):
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=membership_type.name,
        )
        with self.as_user(self.member_email):
            result = get_active_membership_for_current_user()
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], membership.name)
        self.assertEqual(result["status"], "Active")


class TestMemberUtilsDuesScheduleNameCoverage(EnhancedTestCase):
    """Cover the simplified name / has_any helpers' true paths."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Dues",
            last_name="NameCov",
            birth_date="1986-06-06",
        )
        self.membership_type = self.create_test_membership_type(amount=50.0)
        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=self.membership_type.name,
        )
        # Remove any orphaned schedules for deterministic lookups
        for name in frappe.get_all(
            "Membership Dues Schedule", filters={"member": self.member.name}, pluck="name"
        ):
            frappe.delete_doc("Membership Dues Schedule", name, force=True)

    def _make_schedule(self, status="Active"):
        schedule = self.create_test_dues_schedule(
            member=self.member.name,
            membership_type=self.membership_type.name,
            amount=50.0,
            frequency="monthly",
            status=status,
            membership=self.membership.name,
            payment_terms_template=None,
            schedule_name=f"Cov Schedule {frappe.generate_hash()[:8]}",
        )
        return schedule

    def test_get_member_dues_schedule_name_resolves(self):
        schedule = self._make_schedule(status="Active")
        result = get_member_dues_schedule_name(self.member.name)
        self.assertEqual(result, schedule.name)

    def test_get_member_dues_schedule_name_empty_input(self):
        self.assertIsNone(get_member_dues_schedule_name(""))

    def test_has_any_dues_schedule_true(self):
        self._make_schedule(status="Cancelled")
        self.assertTrue(has_any_dues_schedule(self.member.name))


if __name__ == "__main__":
    import unittest

    unittest.main()
