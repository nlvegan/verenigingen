# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for member_status_service.

Covers application-status defaulting, status/membership-status synchronization
against real Membership records, status-transition validation, colour mapping,
is_application_member and status summaries.
"""

import unittest

import frappe
from frappe.utils import add_days, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.core.member_status_service import (
    get_member_status_color,
    get_member_status_summary,
    is_application_member,
    set_member_application_status_defaults,
    sync_member_status_fields,
    update_member_membership_status,
    validate_status_transition,
)


class TestApplicationStatusDefaults(EnhancedTestCase):
    def test_csv_import_flag_skips_setting(self):
        """CSV-imported members keep their existing application_status untouched."""
        member = self.create_test_member(
            first_name="Status",
            last_name="Csv",
            email="status.csv@example.com",
        )
        member._csv_import = True
        member.application_status = "Approved"
        result = set_member_application_status_defaults(member)
        self.assertTrue(result.success)
        self.assertTrue(result.metadata.get("skipped"))
        self.assertEqual(member.application_status, "Approved")

    def test_existing_member_without_status_defaults_approved(self):
        """A persisted member with no application_status becomes Approved."""
        member = self.create_test_member(
            first_name="Status",
            last_name="Existing",
            email="status.existing@example.com",
        )
        member.application_status = ""
        result = set_member_application_status_defaults(member)
        self.assertTrue(result.success)
        self.assertEqual(member.application_status, "Approved")


class TestMembershipStatusComputation(EnhancedTestCase):
    """update_member_membership_status reflects real Membership data."""

    def _type(self):
        return self.create_test_membership_type().name

    def test_no_membership_is_lapsed(self):
        member = self.create_test_member(
            first_name="MS",
            last_name="Lapsed",
            email="ms.lapsed@example.com",
        )
        status = update_member_membership_status(member)
        self.assertEqual(status, "Lapsed")
        self.assertEqual(member.membership_status, "Lapsed")

    def test_active_membership_future_renewal_is_active(self):
        member = self.create_test_member(
            first_name="MS",
            last_name="Active",
            email="ms.active@example.com",
        )
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._type(),
            start_date=add_days(today(), -10),
            status="Active",
        )
        frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), 365))
        status = update_member_membership_status(member)
        self.assertEqual(status, "Active")

    def test_past_renewal_is_expired(self):
        member = self.create_test_member(
            first_name="MS",
            last_name="Expired",
            email="ms.expired@example.com",
        )
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._type(),
            start_date=add_days(today(), -400),
            status="Active",
        )
        frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), -30))
        status = update_member_membership_status(member)
        self.assertEqual(status, "Expired")

    def test_sync_status_fields_returns_all_three(self):
        member = self.create_test_member(
            first_name="MS",
            last_name="Sync",
            email="ms.sync@example.com",
        )
        result = sync_member_status_fields(member)
        self.assertTrue(result.success)
        self.assertIn("status", result.data)
        self.assertIn("application_status", result.data)
        self.assertIn("membership_status", result.data)
        # No membership -> Lapsed
        self.assertEqual(result.data["membership_status"], "Lapsed")


class TestStatusTransitionValidation(EnhancedTestCase):
    """validate_status_transition allowed-transition matrix."""

    def _doc(self, status):
        return frappe._dict(status=status)

    def test_pending_to_active_allowed(self):
        result = validate_status_transition(self._doc("Pending"), "Active")
        self.assertTrue(result["valid"])

    def test_active_to_pending_not_allowed(self):
        result = validate_status_transition(self._doc("Active"), "Pending")
        self.assertFalse(result["valid"])
        self.assertIn("Cannot transition", result["message"])

    def test_quit_is_terminal(self):
        result = validate_status_transition(self._doc("Quit"), "Active")
        self.assertFalse(result["valid"])

    def test_empty_status_to_active_allowed(self):
        result = validate_status_transition(self._doc(""), "Active")
        self.assertTrue(result["valid"])

    def test_unknown_status_rejected(self):
        result = validate_status_transition(self._doc("Bogus"), "Active")
        self.assertFalse(result["valid"])
        self.assertIn("Unknown current status", result["message"])


class TestStatusHelpers(EnhancedTestCase):
    def test_status_color_mapping(self):
        self.assertEqual(get_member_status_color("Active"), "success")
        self.assertEqual(get_member_status_color("Quit"), "danger")
        self.assertEqual(get_member_status_color("Expired"), "warning")
        # Unknown falls back to secondary
        self.assertEqual(get_member_status_color("Nonexistent"), "secondary")

    def test_is_application_member_true_with_application_id(self):
        doc = frappe._dict(application_id="APP-20250101-0001")
        self.assertTrue(is_application_member(doc))

    def test_is_application_member_false_without_application_id(self):
        doc = frappe._dict(application_id=None)
        self.assertFalse(is_application_member(doc))

    def test_status_summary_structure(self):
        member = self.create_test_member(
            first_name="Sum",
            last_name="Mary",
            email="sum.mary@example.com",
        )
        summary = get_member_status_summary(member)
        self.assertEqual(summary["member_name"], member.name)
        self.assertEqual(summary["full_name"], member.full_name)
        self.assertEqual(summary["status_color"], get_member_status_color(member.status))
        self.assertIn("membership_status", summary)


if __name__ == "__main__":
    unittest.main()
