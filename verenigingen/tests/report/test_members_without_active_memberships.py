"""
Real-integration tests for the *Members Without Active Memberships* script
report (``verenigingen/verenigingen/report/members_without_active_memberships/``).

The report lists Members who do NOT currently have an Active (submitted)
Membership. It supports status filters (member_status / include_suspended /
include_terminated), a chapter filter, and an optional dues-schedule
enrichment branch.

These tests seed real Members, Memberships, Chapters and Membership Dues
Schedules via the factory and call ``execute(filters)`` / ``get_data`` /
``get_report_summary`` directly. No business logic is mocked; tests run as
Administrator.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.members_without_active_memberships import (
    members_without_active_memberships as report,
)


class TestMembersWithoutActiveMembershipsReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member(self, status="Active", chapter=False, **kwargs):
        member = self.create_test_member(
            first_name="NoActive",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"noactive.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            chapter=chapter,
            **kwargs,
        )
        member.reload()
        return member

    def _active_membership(self, member):
        """Create + submit an Active membership so the member is EXCLUDED."""
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        membership.submit()
        # Ensure status is Active (submitting sets it via set_status).
        if frappe.db.get_value("Membership", membership.name, "status") != "Active":
            frappe.db.set_value("Membership", membership.name, "status", "Active")
        return membership

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns({})
        self.assertEqual(len(columns), 11)
        self.assertIn("Link/Member", columns[0])
        self.assertIn("Link/Membership", columns[5])

    def test_get_columns_with_chapter_filter_inserts_chapter_column(self):
        columns = report.get_columns({"chapter": "SomeChapter"})
        self.assertEqual(len(columns), 12)
        self.assertTrue(any("Link/Chapter" in c for c in columns))

    def test_get_columns_with_dues_schedule_info_extends(self):
        columns = report.get_columns({"include_dues_schedule_info": 1})
        self.assertEqual(len(columns), 17)
        self.assertTrue(any("Dues Schedule Status" in c for c in columns))
        self.assertTrue(any("Currency" in c for c in columns))

    # ------------------------------------------------------ core inclusion

    def test_member_without_membership_appears(self):
        member = self._member()
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 11)
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row, "a member with no membership at all must appear")
        self.assertEqual(row["member_status"], "Active")
        self.assertIsNone(row["last_membership_id"])

    def test_member_with_active_membership_is_excluded(self):
        member = self._member()
        self._active_membership(member)
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        ids = {r["member_id"] for r in data}
        self.assertNotIn(member.name, ids, "members WITH an active membership must be excluded")

    def test_member_with_expired_membership_appears_with_last_membership(self):
        # A submitted-but-Expired membership (docstatus=1, status != Active) keeps
        # the member in the report and surfaces as the "last membership".
        member = self._member()
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
            status="Active",
        )
        membership.submit()
        # Flip to Expired in-place (docstatus stays 1 so the last-membership join sees it).
        frappe.db.set_value(
            "Membership",
            membership.name,
            {"status": "Expired", "cancellation_date": add_days(today(), -5)},
        )

        with self.assertNoErrorLog():
            columns, data = report.execute({})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row, "member with no ACTIVE membership must appear")
        self.assertEqual(row["last_membership_id"], membership.name)
        self.assertEqual(row["last_membership_status"], "Expired")
        self.assertIsNotNone(row["last_membership_end"])
        self.assertGreaterEqual(row["days_since_last_membership"], 0)

    def test_orphaned_active_membership_with_null_member_does_not_empty_report(self):
        # Regression for the real-data failure on veg11: an Active Membership row
        # whose `member` link is NULL/empty poisons the exclusion subquery
        # (`m.name NOT IN (... NULL ...)` is NULL -> never TRUE), which silently
        # drops EVERY row from the report. The report must still list members
        # that have no active membership despite such orphaned rows existing.
        member = self._member()

        # Create a real submitted Active membership, then orphan it by nulling
        # the member link directly in the DB (the field is reqd=1, so we cannot
        # insert a NULL-member row via the ORM). This reproduces the exact
        # condition seen in production data.
        orphan_owner = self._member()
        orphan = self._active_membership(orphan_owner)
        frappe.db.set_value("Membership", orphan.name, "member", None, update_modified=False)
        self.assertIsNone(
            frappe.db.get_value("Membership", orphan.name, "member"),
            "precondition: orphaned membership must have a NULL member link",
        )

        try:
            with self.assertNoErrorLog():
                columns, data = report.execute({})

            ids = {r["member_id"] for r in data}
            self.assertIn(
                member.name,
                ids,
                "an orphaned Active membership with NULL member must NOT empty the report",
            )
        finally:
            # Restore the member link so the framework can cancel/delete the
            # (submitted, Active) row in tearDown; otherwise the orphan leaks
            # into the shared veg11 dataset and poisons later report runs.
            frappe.db.set_value(
                "Membership", orphan.name, "member", orphan_owner.name, update_modified=False
            )

    def test_none_filters_executes(self):
        member = self._member()
        with self.assertNoErrorLog():
            columns, data = report.execute(None)
        self.assertEqual(len(columns), 11)
        self.assertIn(member.name, {r["member_id"] for r in data})

    # ------------------------------------------------------ status filters

    def test_member_status_filter_restricts_to_status(self):
        active = self._member(status="Active")
        suspended = self._member(status="Suspended")
        with self.assertNoErrorLog():
            columns, data = report.execute({"member_status": "Suspended"})
        ids = {r["member_id"] for r in data}
        self.assertIn(suspended.name, ids)
        self.assertNotIn(active.name, ids)

    def test_default_excludes_suspended(self):
        suspended = self._member(status="Suspended")
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertNotIn(suspended.name, {r["member_id"] for r in data})

    def test_include_suspended_filter(self):
        suspended = self._member(status="Suspended")
        with self.assertNoErrorLog():
            columns, data = report.execute({"include_suspended": 1})
        self.assertIn(suspended.name, {r["member_id"] for r in data})

    def test_default_excludes_quit(self):
        quit_member = self._member(status="Quit")
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertNotIn(quit_member.name, {r["member_id"] for r in data})

    def test_include_terminated_filter_includes_quit(self):
        quit_member = self._member(status="Quit")
        with self.assertNoErrorLog():
            columns, data = report.execute({"include_terminated": 1})
        self.assertIn(quit_member.name, {r["member_id"] for r in data})

    def test_deceased_always_excluded(self):
        deceased = self._member(status="Deceased")
        with self.assertNoErrorLog():
            # Even with both include flags, Deceased is hard-excluded.
            columns, data = report.execute(
                {"include_suspended": 1, "include_terminated": 1}
            )
        self.assertNotIn(deceased.name, {r["member_id"] for r in data})

    # ------------------------------------------------------ chapter filter

    def test_chapter_filter_restricts_to_chapter_members(self):
        chapter = self.create_test_chapter()
        in_chapter = self._member(chapter=chapter.name)
        out_chapter = self._member(chapter=False)

        with self.assertNoErrorLog():
            columns, data = report.execute({"chapter": chapter.name})
        ids = {r["member_id"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)
        # Chapter column is present in the row data.
        row = next(r for r in data if r["member_id"] == in_chapter.name)
        self.assertEqual(row["chapter"], chapter.name)

    # ------------------------------------------------ dues schedule branch

    def test_dues_schedule_info_no_schedule(self):
        member = self._member()
        with self.assertNoErrorLog():
            columns, data = report.execute({"include_dues_schedule_info": 1})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["dues_schedule_status"], "None")
        self.assertIn("No Schedule", row["coverage_status"])
        self.assertEqual(row["days_overdue"], 0)

    def test_dues_schedule_info_with_overdue_schedule(self):
        # A member without an active *membership* can still have an active dues
        # schedule row. Submit a membership (creates an active schedule), then
        # flip the membership to Expired in-place so the member appears in the
        # report while the schedule stays Active.
        member = self._member()
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, status="Active"
        )
        membership.submit()
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active", "is_template": 0},
            "name",
        )
        frappe.db.set_value("Membership", membership.name, "status", "Expired")
        self.assertTrue(schedule_name, "submitting membership should create a dues schedule")
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule_name,
            {
                "next_invoice_date": add_days(today(), -20),
                "billing_frequency": "Monthly",
                "dues_rate": 12.0,
                "auto_generate": 1,
            },
        )

        with self.assertNoErrorLog():
            columns, data = report.execute({"include_dues_schedule_info": 1})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["dues_schedule_status"], "Active")
        self.assertGreater(row["days_overdue"], 7)
        self.assertIn("Critical Gap", row["coverage_status"])
        self.assertEqual(row["billing_frequency"], "Monthly")

    # --------------------------------------------------------- summary API

    def test_get_report_summary_counts_by_status(self):
        active = self._member(status="Active")
        with self.assertNoErrorLog():
            summary = report.get_report_summary({})
        self.assertGreaterEqual(summary["total"], 1)
        self.assertIn("by_status", summary)
        self.assertGreaterEqual(summary["by_status"].get("Active", 0), 1)

    def test_get_data_empty_when_no_members_match(self):
        # An impossible member_status value yields zero rows -> empty data branch.
        with self.assertNoErrorLog():
            data = report.get_data({"member_status": "__no_such_status__"})
        self.assertEqual(data, [])

    def test_get_report_summary_with_dues_schedule_summary(self):
        self._member()
        with self.assertNoErrorLog():
            summary = report.get_report_summary({"include_dues_schedule_info": 1})
        self.assertIn("dues_schedule_summary", summary)
        self.assertIn("coverage_percentage", summary["dues_schedule_summary"])

    # ------------------------------------------------- pure helper coverage

    def test_validate_doctype_fields_true_for_existing(self):
        self.assertTrue(report.validate_doctype_fields("Member", ["name", "status", "email"]))

    def test_validate_doctype_fields_false_for_missing(self):
        self.assertFalse(
            report.validate_doctype_fields("Member", ["definitely_not_a_real_field_xyz"])
        )

    def test_validate_doctype_fields_accepts_child_table_parent(self):
        # Regression: "parent" is an implicit child-table column not present in
        # meta.fields. Validation must accept it, otherwise the chapter filter
        # (which validates Chapter Member.parent) silently returns no rows.
        self.assertTrue(
            report.validate_doctype_fields(
                "Chapter Member", ["member", "parent", "enabled", "status"]
            )
        )

    def test_get_dues_schedule_summary_estimates_overdue(self):
        rows = [
            {
                "dues_schedule_status": "Active",
                "days_overdue": 10,
                "dues_rate": 30.0,
                "billing_frequency": "Daily",
            },
            {
                "dues_schedule_status": "None",
                "days_overdue": 0,
            },
        ]
        summary = report.get_dues_schedule_summary(rows)
        self.assertEqual(summary["total_members"], 2)
        self.assertEqual(summary["members_with_schedules"], 1)
        self.assertEqual(summary["overdue_schedules"], 1)
        self.assertEqual(summary["critical_schedules"], 1)
        self.assertEqual(summary["estimated_overdue_amount"], 300.0)  # 30 * 10 daily
