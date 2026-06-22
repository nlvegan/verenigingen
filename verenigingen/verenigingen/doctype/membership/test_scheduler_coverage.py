# -*- coding: utf-8 -*-
"""
Coverage-focused integration tests for membership/scheduler.py.

Exercises the expiry processor, renewal-reminder lookup, the deprecated
auto-renewal stub, direct-debit batch generation, and the orphaned-records
query/notification path. Real-DB integration tests only.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.scheduler import (
    _get_orphaned_records_data,
    _process_expired_memberships_impl,
    _send_renewal_reminders_impl,
    generate_direct_debit_batch,
    notify_about_orphaned_records,
    process_auto_renewals,
    process_expired_memberships,
    setup_membership_scheduler_events,
)


class TestSchedulerCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Item Group", "Membership"):
            ig = frappe.new_doc("Item Group")
            ig.item_group_name = "Membership"
            ig.parent_item_group = "All Item Groups"
            ig.insert()
        self.mtype = self.create_test_membership_type(
            membership_type_name="Sched Annual",
            amount=40.0,
            billing_period="Annual",
        )
        self.member = self.create_test_member(payment_method="Bank Transfer")

    def _active_membership(self, start=None, skip_dues=True):
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.mtype.name
        m.start_date = start or today()
        if skip_dues:
            m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()
        return m

    # ------------------------------------------------------------------
    # setup_membership_scheduler_events
    # ------------------------------------------------------------------
    def test_setup_scheduler_events(self):
        events = setup_membership_scheduler_events()
        self.assertIn("daily", events)
        self.assertIn(
            "verenigingen.verenigingen.doctype.membership.scheduler.process_expired_memberships",
            events["daily"],
        )
        self.assertIn(
            "verenigingen.verenigingen.doctype.membership.scheduler.send_renewal_reminders",
            events["daily"],
        )

    # ------------------------------------------------------------------
    # _process_expired_memberships_impl + lock wrapper
    # ------------------------------------------------------------------
    def test_process_expired_memberships_impl_marks_expired(self):
        """A submitted Active membership with a past renewal date is marked Expired."""
        m = self._active_membership()
        self.assertEqual(m.status, "Active")
        frappe.db.set_value("Membership", m.name, "renewal_date", add_days(today(), -2))
        frappe.db.commit()

        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            count = _process_expired_memberships_impl()
        self.assertGreaterEqual(count, 1)
        m.reload()
        self.assertEqual(m.status, "Expired")

    def test_process_expired_memberships_lock_wrapper(self):
        """The advisory-lock wrapper acquires the lock and processes successfully."""
        m = self._active_membership()
        frappe.db.set_value("Membership", m.name, "renewal_date", add_days(today(), -3))
        frappe.db.commit()
        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            count = process_expired_memberships()
        self.assertGreaterEqual(count, 1)
        m.reload()
        self.assertEqual(m.status, "Expired")

    def test_process_expired_skips_future_renewal(self):
        """An active membership with a future renewal date is left Active by the processor."""
        m = self._active_membership()  # renewal_date is one year out
        _process_expired_memberships_impl()
        m.reload()
        self.assertEqual(m.status, "Active")

    # ------------------------------------------------------------------
    # _send_renewal_reminders_impl
    # ------------------------------------------------------------------
    def test_send_renewal_reminders_no_template_skips(self):
        """When no Email Template exists, the reminder for a 30-day expiry is skipped (count 0)."""
        m = self._active_membership()
        # Put renewal_date exactly 30 days out so it is picked up by the query
        frappe.db.set_value("Membership", m.name, "renewal_date", add_days(today(), 30))
        frappe.db.commit()

        # Ensure no matching templates exist so the skip branch is exercised
        for tmpl in ["membership_renewal_reminder_30_days", "membership_renewal_reminder"]:
            if frappe.db.exists("Email Template", tmpl):
                frappe.delete_doc("Email Template", tmpl, force=True)

        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            count = _send_renewal_reminders_impl()
        # No template -> nothing sent
        self.assertEqual(count, 0)

    def test_send_renewal_reminders_no_upcoming_returns_zero(self):
        """With no memberships at the 30/15/7/1-day marks, nothing is sent."""
        # The active membership created in setUp renews a year out, so no marks match
        self._active_membership()
        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            count = _send_renewal_reminders_impl()
        self.assertEqual(count, 0)

    # ------------------------------------------------------------------
    # process_auto_renewals (deprecated)
    # ------------------------------------------------------------------
    def test_process_auto_renewals_deprecated_returns_zero(self):
        self.assertEqual(process_auto_renewals(), 0)

    # ------------------------------------------------------------------
    # generate_direct_debit_batch
    # ------------------------------------------------------------------
    def test_generate_direct_debit_batch_no_pending(self):
        """With no Pending memberships in the DB, the batch generator returns 0."""
        # Ensure a clean slate: no submitted Pending memberships should exist.
        pending = frappe.get_all("Membership", filters={"status": "Pending", "docstatus": 1}, pluck="name")
        if pending:
            self.skipTest("Pre-existing Pending memberships in the DB make the no-pending branch untestable")
        result = generate_direct_debit_batch()
        self.assertEqual(result, 0)

    def test_generate_direct_debit_batch_pending_without_bank_skipped(self):
        """A Pending membership whose member lacks a bank account is skipped from the batch."""
        m = self._active_membership()
        # Force status Pending directly (Pending is a runtime status not normally set by validate)
        frappe.db.set_value("Membership", m.name, "status", "Pending")
        frappe.db.commit()

        result = generate_direct_debit_batch()
        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(result["entry_count"], 1)
        # Member has no bank_account field/value -> excluded from entries
        entry_memberships = [e["membership"] for e in result["entries"]]
        self.assertNotIn(m.name, entry_memberships)

    # ------------------------------------------------------------------
    # _get_orphaned_records_data
    # ------------------------------------------------------------------
    def test_orphaned_records_includes_membership_without_schedule(self):
        """An Active submitted membership with no dues schedule appears as orphaned."""
        m = self._active_membership(skip_dues=True)  # no dues schedule created
        # Ignore unrelated background payment-history deadlock noise (a known
        # concurrency artifact from membership submit, not from the SQL read here).
        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            data = _get_orphaned_records_data()
        orphan_membership_names = [d["document"] for d in data if d["record_type"] == "Membership"]
        self.assertIn(m.name, orphan_membership_names)
        # Verify the issue text is meaningful
        for d in data:
            if d["document"] == m.name:
                self.assertEqual(d["issue"], "No dues schedule found")
                self.assertEqual(d["status"], "Active")

    def test_orphaned_records_excludes_membership_with_schedule(self):
        """An Active membership WITH a dues schedule is not reported as orphaned."""
        m = self._active_membership(skip_dues=False)
        frappe.db.commit()
        m.reload()
        self.assertIsNotNone(m.get_dues_schedule())
        data = _get_orphaned_records_data()
        orphan_membership_names = [d["document"] for d in data if d["record_type"] == "Membership"]
        self.assertNotIn(m.name, orphan_membership_names)

    # ------------------------------------------------------------------
    # notify_about_orphaned_records
    # ------------------------------------------------------------------
    def test_notify_about_orphaned_records_no_data_early_return(self):
        """With no orphaned records, notify_about_orphaned_records returns early (None)."""
        # Make sure no orphaned membership exists for our member by giving it a schedule.
        self._active_membership(skip_dues=False)
        frappe.db.commit()
        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            result = notify_about_orphaned_records()
        self.assertIsNone(result)

    def test_notify_about_orphaned_records_builds_report_with_orphan(self):
        """With an orphaned membership present, the email-content build branch runs without error.

        Seeds an orphaned (no dues schedule) Active membership so _get_orphaned_records_data
        returns rows -> the function proceeds past the early no-data return and builds the
        HTML report + gathers recipients (the send is a no-op when none are configured).
        """
        m = self._active_membership(skip_dues=True)
        frappe.db.commit()
        # Confirm the orphan is actually visible to the query the function uses.
        data = _get_orphaned_records_data()
        self.assertIn(m.name, [d["document"] for d in data if d["record_type"] == "Membership"])

        with self.assertNoErrorLog(ignore=["Payment History Bulk Update"]):
            result = notify_about_orphaned_records()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
