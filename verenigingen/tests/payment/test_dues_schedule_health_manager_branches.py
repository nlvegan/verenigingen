"""
Branch-coverage tests for ``dues_schedule_health_manager.py``.

The existing ``test_dues_schedule_health_manager.py`` covers the priority-1/priority-5
hierarchy, transaction safety, custom-rate preservation and field sync. This suite fills
the gaps:

- ``get_dues_rate_from_priority_hierarchy`` priority 2 (fee_change_history),
  priority 3 (active dues schedule) and priority 4 (application_custom_fee).
- ``reconstruct_dues_schedule`` full happy path (creates schedule + fee history) and
  the no-dues-rate failure branch.
- ``reconstruct_missing_membership`` "already has active membership" branch and the
  "no membership type" failure branch.
- ``validate_custom_rate_preservation`` "no preserve" branch.
- ``comprehensive_dues_health_maintenance`` scheduled job aggregation.
- ``sync_all_member_fields`` continue_on_error and processing_summary.

Real DB fixtures via Enhanced Test Factory; expected values derived from created data.
"""

import unittest

import frappe

from verenigingen.services.billing.dues_schedule_health_manager import (
    DuesScheduleHealthManager,
    comprehensive_dues_health_maintenance,
    sync_all_member_fields,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists


class TestPriorityHierarchyBranches(EnhancedTestCase):
    """Cover priority levels 2, 3, 4 of get_dues_rate_from_priority_hierarchy."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)
        self.manager = DuesScheduleHealthManager()

    def _cancel_auto_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def test_priority2_fee_change_history(self):
        # dues_rate=0 forces past priority 1; a fee_change_history row with a rate
        # is the priority-2 source.
        member = self.create_test_member(first_name="FeeHist", last_name="Test", birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "dues_rate", 0)

        member_doc = frappe.get_doc("Member", member.name)
        row = member_doc.append("fee_change_history", {})
        row.change_date = frappe.utils.now()
        row.new_dues_rate = 42.0
        row.billing_frequency = "Quarterly"
        row.change_type = "Fee Change"
        row.reason = "Test fee change for priority-2 coverage"
        row.changed_by = frappe.session.user
        member_doc.save()

        result = self.manager.get_dues_rate_from_priority_hierarchy(member.name)
        self.assertEqual(result["dues_rate"], 42.0)
        self.assertEqual(result["source"], "fee_change_history")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["billing_frequency"], "Quarterly")

    def test_priority3_active_dues_schedule(self):
        # No dues_rate, no fee history -> priority 3 reads an Active dues schedule.
        member = self.create_test_member(first_name="ActSched", last_name="Test", birth_date="1990-01-01")
        self.create_test_membership(member.name, "Monthly Membership")
        self._cancel_auto_schedules(member.name)

        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"P3 Schedule - {member.name}",
                "member": member.name,
                "member_name": member.full_name,
                "membership_type": "Monthly Membership",
                "currency": "EUR",
                "dues_rate": 33.0,
                "status": "Active",
                "billing_frequency": "Monthly",
            }
        )
        schedule.insert()

        # Membership submit auto-appends a fee_change_history row (template default
        # rate) which would win at priority 2; clear it so priority 3 (active
        # schedule) is the reached source.
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.set("fee_change_history", [])
        member_doc.save()

        frappe.db.set_value("Member", member.name, "dues_rate", 0)
        result = self.manager.get_dues_rate_from_priority_hierarchy(member.name)
        self.assertEqual(result["dues_rate"], 33.0)
        self.assertEqual(result["source"], "active_dues_schedule")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["billing_frequency"], "Monthly")

    def test_priority4_application_custom_fee(self):
        # No dues_rate / fee history / active schedule -> priority 4 uses
        # application_custom_fee.
        member = self.create_test_member(first_name="AppFee", last_name="Test", birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "dues_rate", 0)
        frappe.db.set_value("Member", member.name, "application_custom_fee", 27.5)

        result = self.manager.get_dues_rate_from_priority_hierarchy(member.name)
        self.assertEqual(result["dues_rate"], 27.5)
        self.assertEqual(result["source"], "application_custom_fee")
        self.assertEqual(result["confidence"], "medium")

    def test_none_found_when_no_source(self):
        # No source anywhere -> none_found.
        member = self.create_test_member(first_name="NoSource", last_name="Test", birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "dues_rate", 0)
        frappe.db.set_value("Member", member.name, "application_custom_fee", 0)
        frappe.db.set_value("Member", member.name, "selected_membership_type", None)
        frappe.db.set_value("Member", member.name, "current_membership_type", None)
        frappe.db.set_value("Member", member.name, "current_membership_plan", None)

        result = self.manager.get_dues_rate_from_priority_hierarchy(member.name)
        self.assertIsNone(result["dues_rate"])
        self.assertEqual(result["source"], "none_found")
        self.assertEqual(result["confidence"], "none")
        self.assertIn("error", result)


class TestReconstructMissingMembershipBranches(EnhancedTestCase):
    """Cover reconstruct_missing_membership branches."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)
        self.manager = DuesScheduleHealthManager()

    def test_existing_active_membership_syncs_plan(self):
        # Member already has an active membership but current_membership_plan unset:
        # the method should set it and increment fields_synchronized.
        member = self.create_test_member(first_name="HasMemb", last_name="Test", birth_date="1990-01-01")
        membership = self.create_test_membership(member.name, "Monthly Membership")
        frappe.db.set_value("Member", member.name, "current_membership_plan", None)

        result = self.manager.reconstruct_missing_membership(member.name)
        self.assertEqual(result, membership.name)
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "current_membership_plan"), membership.name
        )
        self.assertGreaterEqual(self.manager.results["fields_synchronized"], 1)

    def test_no_membership_type_records_error(self):
        # No active membership and no membership type fields -> error, returns None.
        member = self.create_test_member(first_name="NoType", last_name="Test", birth_date="1990-01-01")
        # Remove any membership auto-created and clear type fields.
        for m in frappe.get_all("Membership", filters={"member": member.name}, pluck="name"):
            frappe.db.set_value("Membership", m, "docstatus", 0)
            frappe.delete_doc("Membership", m, force=True)
        frappe.db.set_value("Member", member.name, "selected_membership_type", None)
        frappe.db.set_value("Member", member.name, "current_membership_type", None)

        result = self.manager.reconstruct_missing_membership(member.name)
        self.assertIsNone(result)
        self.assertTrue(
            any("no membership type found" in e for e in self.manager.results["errors"]),
            self.manager.results["errors"],
        )


class TestReconstructDuesSchedule(EnhancedTestCase):
    """Cover reconstruct_dues_schedule happy path and failure branch."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)
        self.manager = DuesScheduleHealthManager()

    def _cancel_auto_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def test_reconstruct_returns_existing_active_schedule(self):
        # When an active schedule already exists, the method returns it unchanged.
        member = self.create_test_member(first_name="ExistSched", last_name="Test", birth_date="1990-01-01")
        self.create_test_membership(member.name, "Monthly Membership")

        existing = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active", "is_template": 0},
            pluck="name",
        )
        self.assertTrue(existing, "membership submit should auto-create a schedule")

        result = self.manager.reconstruct_dues_schedule(member.name)
        self.assertEqual(result, existing[0])

    def test_reconstruct_full_creation_path(self):
        # Member with a dues_rate and an active (submitted) membership but NO active
        # schedule: reconstruct creates the schedule, updates member fields and
        # appends a fee_change_history "Schedule Created" row.
        #
        # NOTE: The Membership Dues Schedule controller requires the linked membership
        # to be active/submitted. reconstruct_missing_membership only inserts a Draft
        # membership, so a from-scratch reconstruction (no membership at all) cannot
        # produce a schedule until a reviewer submits the membership. We therefore keep
        # the factory's submitted membership and only remove the auto-created schedule.
        member = self.create_test_member(
            first_name="MakeSched",
            last_name="Test",
            birth_date="1990-01-01",
            selected_membership_type="Monthly Membership",
        )
        self.create_test_membership(member.name, "Monthly Membership")
        self._cancel_auto_schedules(member.name)
        frappe.db.set_value("Member", member.name, "dues_rate", 36.0)
        # Clear the fee_change_history rows so the "Schedule Created" assertion below
        # isolates the row appended by reconstruct.
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.set("fee_change_history", [])
        member_doc.save()

        schedule_name = self.manager.reconstruct_dues_schedule(member.name)
        self.assertIsNotNone(schedule_name, f"errors: {self.manager.results['errors']}")

        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(schedule.member, member.name)
        self.assertEqual(schedule.dues_rate, 36.0)
        self.assertEqual(schedule.status, "Active")
        self.assertEqual(schedule.contribution_mode, "Fixed")

        # Member fields updated.
        member_doc = frappe.get_doc("Member", member.name)
        self.assertEqual(member_doc.current_dues_schedule, schedule_name)
        self.assertEqual(member_doc.dues_rate, 36.0)

        # Fee history row recorded via the canonical writer (which the reconstruct
        # path now delegates to). old_dues_rate is populated (defaults to 0) rather
        # than left NULL as the former direct-append bypass did.
        history = [h for h in member_doc.fee_change_history if h.change_type == "Schedule Created"]
        self.assertTrue(history)
        self.assertEqual(history[-1].dues_schedule, schedule_name)
        self.assertEqual(history[-1].old_dues_rate, 0)

        # Results counters reflect the creation.
        self.assertGreaterEqual(self.manager.results["schedules_created"], 1)

    def test_reconstruct_fails_when_no_dues_rate(self):
        # No dues rate in any source -> reconstruct records an error and returns None.
        member = self.create_test_member(first_name="NoRate", last_name="Test", birth_date="1990-01-01")
        self._cancel_auto_schedules(member.name)
        for m in frappe.get_all("Membership", filters={"member": member.name}, pluck="name"):
            frappe.db.set_value("Membership", m, "docstatus", 0)
            frappe.delete_doc("Membership", m, force=True)
        frappe.db.set_value("Member", member.name, "dues_rate", 0)
        frappe.db.set_value("Member", member.name, "application_custom_fee", 0)
        frappe.db.set_value("Member", member.name, "selected_membership_type", None)
        frappe.db.set_value("Member", member.name, "current_membership_type", None)
        frappe.db.set_value("Member", member.name, "current_membership_plan", None)

        result = self.manager.reconstruct_dues_schedule(member.name)
        self.assertIsNone(result)
        self.assertTrue(
            any("Cannot reconstruct dues schedule" in e for e in self.manager.results["errors"]),
            self.manager.results["errors"],
        )


class TestCustomRatePreservationNoPreserve(EnhancedTestCase):
    """Cover the should_preserve=False branch of validate_custom_rate_preservation."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)
        self.manager = DuesScheduleHealthManager()

    def test_no_custom_schedules_returns_no_preserve(self):
        member = self.create_test_member(first_name="NoCustom", last_name="Test", birth_date="1990-01-01")
        result = self.manager.validate_custom_rate_preservation(member.name, 25.0)
        self.assertFalse(result["should_preserve"])
        self.assertIsNone(result["existing_rate"])
        self.assertIn("No manually approved", result["reason"])

    def test_system_approved_custom_rate_not_preserved(self):
        # A custom-approved schedule approved by Administrator with a "reconstructed"
        # reason is treated as system-created -> not preserved.
        member = self.create_test_member(first_name="SysCustom", last_name="Test", birth_date="1990-01-01")
        self.create_test_membership(member.name, "Monthly Membership")
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Sys Custom - {member.name}",
                "member": member.name,
                "member_name": member.full_name,
                "membership_type": "Monthly Membership",
                "currency": "EUR",
                "dues_rate": 50.0,
                "custom_amount_approved": 1,
                "custom_amount_approved_by": "Administrator",
                "custom_amount_reason": "auto-created reconstructed via health check",
                "status": "Active",
                "billing_frequency": "Monthly",
            }
        )
        schedule.insert()

        result = self.manager.validate_custom_rate_preservation(member.name, 25.0)
        self.assertFalse(result["should_preserve"])


class TestComprehensiveHealthMaintenance(EnhancedTestCase):
    """Cover the comprehensive_dues_health_maintenance scheduled job aggregation."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)

    def test_maintenance_aggregates_results(self):
        # A couple of members so the maintenance job has data to process.
        for i in range(2):
            self.create_test_member(first_name=f"Maint{i}", last_name="Test", birth_date="1990-01-01")

        result = comprehensive_dues_health_maintenance()

        # On success the job returns the aggregate dict (not a {"success": False}).
        self.assertNotIn("success", result)
        self.assertIn("field_sync_results", result)
        self.assertIn("missing_membership_results", result)
        self.assertIn("stuck_schedule_results", result)
        self.assertIn("total_errors", result)
        self.assertIn("summary", result)
        # total_errors must equal the sum of the three sub-result error lists -- this
        # pins the aggregation logic, not just structural key presence.
        expected_total = (
            len(result["field_sync_results"].get("errors", []))
            + len(result["missing_membership_results"].get("errors", []))
            + len(result["stuck_schedule_results"].get("errors", []))
        )
        self.assertEqual(result["total_errors"], expected_total)
        # summary is always a string (the join of summary_parts, or "No issues found").
        self.assertIsInstance(result["summary"], str)


class TestSyncAllMemberFieldsBranches(EnhancedTestCase):
    """Cover sync_all_member_fields summary and limited-batch processing."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Monthly Membership", amount=5.0)

    def test_sync_all_processing_summary_keys(self):
        for i in range(3):
            self.create_test_member(first_name=f"SyncSum{i}", last_name="Test", birth_date="1990-01-01")

        result = sync_all_member_fields(batch_size=2, max_members=3, continue_on_error=True)

        self.assertGreaterEqual(result["members_processed"], 3)
        summary = result["processing_summary"]
        self.assertIn("success_rate", summary)
        self.assertIn("transaction_failure_rate", summary)
        self.assertIn("synchronization_rate", summary)
        # No failures expected on clean fixtures.
        self.assertEqual(result["transaction_failures"], 0)
        self.assertEqual(summary["success_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
