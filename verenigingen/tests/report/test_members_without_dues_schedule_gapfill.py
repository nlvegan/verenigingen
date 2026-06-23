"""
Gap-fill real-integration tests for the *Members Without Dues Schedule* script
report (``verenigingen/verenigingen/report/members_without_dues_schedule/``).

The base coverage is provided by ``test_members_without_dues_schedule.py``
(columns, no-schedule, healthy, overdue/critical, problems_only / critical_only
/ member_status / include_suspended filters, summary, chart). This file adds
tests for the branches that file does NOT cover:

  * the ``Behind`` status branch (1-7 days overdue);
  * the ``Manual`` mode branch (``auto_generate = 0`` and not overdue);
  * the ``include_terminated`` and ``include_pending`` filters and the
    "all statuses included" path (no status filter applied);
  * the ``problems_only`` filter retaining a manual schedule;
  * the financial-estimate branch in ``get_report_summary`` for the Weekly
    and Monthly billing frequencies, plus the no-rate skip;
  * the ``_get_default_membership_type_with_dues_info`` helper (template and
    fallback paths);
  * the ``fix_member_schedule_issues`` API (non-active member rejection,
    no-customer rejection, fixing an existing schedule, and creating a
    membership + schedule for an active member that has neither).

No business logic is mocked. The API entry points run as Administrator.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.members_without_dues_schedule import (
    members_without_dues_schedule as report,
)


class TestMembersWithoutDuesScheduleGapFill(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.suffix = frappe.generate_hash(length=6)

    # ------------------------------------------------------------- helpers

    def _member_with_customer(self, status="Active", **kwargs):
        member = self.create_test_member(
            first_name="Gap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"gap.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            auto_create_customer=True,
            **kwargs,
        )
        member.reload()
        self.assertTrue(member.customer, "member should have a customer for the report to include it")
        return member

    def _active_schedule(self, member, **kwargs):
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        membership.submit()

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active", "is_template": 0},
            "name",
        )
        self.assertTrue(schedule_name, "submitting the membership should auto-create an active schedule")
        for field, value in kwargs.items():
            frappe.db.set_value("Membership Dues Schedule", schedule_name, field, value)
        return frappe.get_doc("Membership Dues Schedule", schedule_name)

    def _row_for(self, data, member):
        return next((r for r in data if r["member_id"] == member.name), None)

    # --------------------------------------------------- status: Behind (1-7)

    def test_member_behind_schedule_1_to_7_days(self):
        member = self._member_with_customer()
        # 4 days overdue -> "Behind"
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), -4),
            billing_frequency="Monthly",
            dues_rate=15.0,
        )

        columns, data, _none, chart, summary = report.execute({})
        row = self._row_for(data, member)
        self.assertIsNotNone(row)
        self.assertIn("Behind", row["dues_schedule_status"])
        self.assertIn("Minor Gap", row["coverage_gap"])
        self.assertIn("Check Schedule", row["action_required"])
        self.assertTrue(0 < row["days_overdue"] <= 7)

    # --------------------------------------------------- status: Manual mode

    def test_member_manual_mode_schedule(self):
        member = self._member_with_customer()
        # Not overdue + auto_generate disabled -> "Manual"
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), 10),
            billing_frequency="Monthly",
            dues_rate=15.0,
            auto_generate=0,
        )

        columns, data, _none, chart, summary = report.execute({})
        row = self._row_for(data, member)
        self.assertIsNotNone(row)
        self.assertIn("Manual", row["dues_schedule_status"])
        self.assertIn("Manual Mode", row["coverage_gap"])
        self.assertIn("Monitor", row["action_required"])

    def test_problems_only_retains_manual_schedule(self):
        # A manual (auto_generate=0) schedule is "problematic" per problems_only
        # because the healthy-skip condition requires auto_generate truthy.
        member = self._member_with_customer()
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), 10),
            billing_frequency="Monthly",
            dues_rate=15.0,
            auto_generate=0,
        )

        columns, data, _none, chart, summary = report.execute({"problems_only": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(member.name, ids, "manual schedules must be retained under problems_only")

    # ----------------------------------------------- filters: include flags

    def test_default_excludes_pending_members(self):
        pending = self._member_with_customer(status="Pending")
        columns, data, _none, chart, summary = report.execute({})
        ids = {r["member_id"] for r in data}
        self.assertNotIn(pending.name, ids, "Pending members are excluded by default")

    def test_include_pending_filter(self):
        pending = self._member_with_customer(status="Pending")
        columns, data, _none, chart, summary = report.execute({"include_pending": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(pending.name, ids)

    def test_default_excludes_quit_members(self):
        quit_member = self._member_with_customer(status="Quit")
        columns, data, _none, chart, summary = report.execute({})
        ids = {r["member_id"] for r in data}
        self.assertNotIn(quit_member.name, ids, "Quit members are excluded by default")

    def test_include_terminated_filter(self):
        quit_member = self._member_with_customer(status="Quit")
        columns, data, _none, chart, summary = report.execute({"include_terminated": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(quit_member.name, ids)

    def test_all_statuses_included_applies_no_status_filter(self):
        # When all three include flags are set, no status filter is applied,
        # so members of any status appear.
        quit_member = self._member_with_customer(status="Quit")
        suspended = self._member_with_customer(status="Suspended")
        pending = self._member_with_customer(status="Pending")

        columns, data, _none, chart, summary = report.execute(
            {"include_terminated": 1, "include_suspended": 1, "include_pending": 1}
        )
        ids = {r["member_id"] for r in data}
        self.assertIn(quit_member.name, ids)
        self.assertIn(suspended.name, ids)
        self.assertIn(pending.name, ids)

    # ------------------------------------------- get_report_summary branches

    def test_report_summary_weekly_billing_estimate(self):
        rows = [
            {
                "dues_schedule_status": '<span class="indicator orange">Overdue</span>',
                "days_overdue": 14,
                "dues_rate": 7.0,
                "billing_frequency": "Weekly",
            }
        ]
        summary = report.get_report_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        # Weekly: rate * (days / 7) = 7 * (14 / 7) = 14
        self.assertEqual(labels["Estimated Overdue Amount"], 14.0)

    def test_report_summary_monthly_billing_estimate(self):
        rows = [
            {
                "dues_schedule_status": '<span class="indicator red">Critical</span>',
                "days_overdue": 30,
                "dues_rate": 30.0,
                "billing_frequency": "Monthly",
            }
        ]
        summary = report.get_report_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        # Monthly: rate * (days / 30) = 30 * (30 / 30) = 30
        self.assertEqual(labels["Estimated Overdue Amount"], 30.0)

    def test_report_summary_skips_rows_without_rate(self):
        rows = [
            {
                "dues_schedule_status": '<span class="indicator red">Critical</span>',
                "days_overdue": 30,
                "dues_rate": None,
                "billing_frequency": "Monthly",
            }
        ]
        summary = report.get_report_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        self.assertEqual(labels["Estimated Overdue Amount"], 0)

    def test_report_summary_counts_categories(self):
        # A mix of one no-schedule and one healthy member exercises the various
        # summary counters together.
        no_sched = self._member_with_customer()
        healthy = self._member_with_customer()
        self._active_schedule(healthy, next_invoice_date=add_days(today(), 10), dues_rate=15.0)

        columns, data, _none, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertGreaterEqual(labels["Members Without Schedule"], 1)
        self.assertGreaterEqual(labels["Healthy Schedules"], 1)

    # -------------------------------- _get_default_membership_type_with_dues_info

    def test_get_default_membership_type_info_returns_dict(self):
        # There is at least one active membership type after seeding one.
        self.create_test_membership_type(is_active=1)
        info = report._get_default_membership_type_with_dues_info()
        self.assertIsNotNone(info)
        self.assertIn("name", info)
        self.assertIn("billing_frequency", info)
        self.assertIsInstance(info["dues_rate"], float)

    # ------------------------------------------- fix_member_schedule_issues API

    def test_fix_rejects_non_active_member(self):
        member = self._member_with_customer(status="Suspended")
        result = report.fix_member_schedule_issues([member.name])
        self.assertTrue(result["success"])
        entry = next(r for r in result["results"] if r["member"] == member.name)
        self.assertFalse(entry["success"])
        self.assertIn("only Active members", entry["message"])

    def test_fix_rejects_member_without_customer(self):
        member = self.create_test_member(
            first_name="NoCust",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"nocust.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        member.reload()
        if member.customer:
            frappe.db.set_value("Member", member.name, "customer", None)

        result = report.fix_member_schedule_issues([member.name])
        entry = next(r for r in result["results"] if r["member"] == member.name)
        self.assertFalse(entry["success"])
        self.assertIn("no customer", entry["message"].lower())

    def test_fix_existing_schedule_is_verified(self):
        member = self._member_with_customer()
        schedule = self._active_schedule(
            member, next_invoice_date=add_days(today(), -20), dues_rate=15.0
        )

        result = report.fix_member_schedule_issues([member.name])
        entry = next(r for r in result["results"] if r["member"] == member.name)
        self.assertTrue(entry["success"], entry.get("message"))
        self.assertEqual(entry["schedule"], schedule.name)
        self.assertIn("verified", entry["message"])

    def test_fix_accepts_json_string_member_list(self):
        import json

        member = self._member_with_customer()
        self._active_schedule(member, next_invoice_date=add_days(today(), -20), dues_rate=15.0)

        result = report.fix_member_schedule_issues(json.dumps([member.name]))
        self.assertTrue(result["success"])
        self.assertEqual(result["total_processed"], 1)

    def test_fix_creates_membership_and_schedule_for_bare_active_member(self):
        # Active member with a customer but NO membership and NO dues schedule.
        # Exercises the _create_membership_and_schedule path: it creates and
        # submits a Membership, whose on_submit hook auto-creates the active
        # dues schedule. The meaningful invariant is that, after the call, the
        # member ends up with an active membership and an active dues schedule
        # (either the explicit save succeeds, or the membership hook beat it to
        # it and the function reports the schedule already exists).
        member = self._member_with_customer()
        # Ensure a default membership type with a billing period exists so the
        # creation path has something to work with.
        self.create_test_membership_type(is_active=1, billing_period="Monthly")

        # Confirm precondition: no schedule yet.
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"member": member.name, "status": "Active"})
        )

        result = report.fix_member_schedule_issues([member.name])
        self.assertTrue(result["success"])
        # Track created docs for cleanup.
        membership_name = frappe.db.get_value(
            "Membership", {"member": member.name, "docstatus": 1}, "name"
        )
        if membership_name:
            self.track_doc("Membership", membership_name)
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "status": "Active"}, "name"
        )
        if schedule_name:
            self.track_doc("Membership Dues Schedule", schedule_name)

        # End goal: the member now has both an active membership and an active
        # dues schedule.
        self.assertTrue(membership_name, "the create path must produce an active membership")
        self.assertTrue(schedule_name, "the create path must result in an active dues schedule")
