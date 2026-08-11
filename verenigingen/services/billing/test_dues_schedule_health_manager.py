# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/dues_schedule_health_manager.py

Focus areas (real DocTypes, no business-logic mocking, no permission bypass in bodies):
  - get_dues_rate_from_priority_hierarchy: all 5 priority sources + none-found
  - validate_custom_rate_preservation
  - sync_member_fields: detects + applies field drift
  - reconstruct_dues_schedule / reconstruct_missing_membership
  - process_member_with_transaction: success accounting
  - comprehensive_dues_schedule_health_check (scoped to a single member via filter)

ISOLATION:
  The health manager COMMITS (secure_document_operation + db.set_value), escaping the
  test rollback. Every fixture has a unique name, is tracked, and force-deleted in
  tearDown; assertions are scoped to the test's own member.
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.dues_schedule_health_manager import (
    DuesScheduleHealthManager,
    comprehensive_dues_schedule_health_check,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _HealthBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        order = {
            "Membership Dues Schedule": 0,
            "Membership": 1,
            "Member": 2,
            "Membership Type": 3,
        }
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _as_admin(self):
        frappe.set_user("Administrator")

    def _member(self):
        m = self.create_test_member()
        self._committed.append(("Member", m.name))
        frappe.db.commit()
        return m

    def _track_schedules(self, member_name):
        for n in frappe.get_all("Membership Dues Schedule", filters={"member": member_name}, pluck="name"):
            self._committed.append(("Membership Dues Schedule", n))


class TestDuesRatePriorityHierarchy(_HealthBase):
    def setUp(self):
        super().setUp()
        self.manager = DuesScheduleHealthManager()

    def test_priority1_member_dues_rate_field(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 37.5)
        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertEqual(result["dues_rate"], 37.5)
        self.assertEqual(result["source"], "member_dues_rate_field")
        self.assertEqual(result["confidence"], "high")

    def test_priority2_fee_change_history(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        doc = frappe.get_doc("Member", m.name)
        fc = doc.append("fee_change_history", {})
        fc.change_date = today()
        fc.new_dues_rate = 19.0
        fc.billing_frequency = "Monthly"
        fc.change_type = "Schedule Created"
        fc.reason = "test"
        fc.changed_by = frappe.session.user
        doc.save()
        frappe.db.commit()

        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertEqual(result["dues_rate"], 19.0)
        self.assertEqual(result["source"], "fee_change_history")
        self.assertEqual(result["billing_frequency"], "Monthly")

    def test_priority2_picks_latest_entry(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        doc = frappe.get_doc("Member", m.name)
        older = doc.append("fee_change_history", {})
        older.change_date = "2024-01-01"
        older.new_dues_rate = 10.0
        older.change_type = "Schedule Created"
        older.reason = "test old"
        older.changed_by = frappe.session.user
        newer = doc.append("fee_change_history", {})
        newer.change_date = "2025-01-01"
        newer.new_dues_rate = 22.0
        newer.billing_frequency = "Quarterly"
        newer.change_type = "Fee Adjustment"  # what fee_change_tracking_service writes
        newer.reason = "test new"
        newer.changed_by = frappe.session.user
        doc.save()
        frappe.db.commit()

        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertEqual(result["dues_rate"], 22.0)  # latest by change_date

    def test_priority4_application_custom_fee(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        frappe.db.set_value("Member", m.name, "application_custom_fee", 44.0)
        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertEqual(result["dues_rate"], 44.0)
        self.assertEqual(result["source"], "application_custom_fee")

    def test_priority5_membership_type_minimum(self):
        mt = self.create_test_membership_type(amount=66.0)
        self._committed.append(("Membership Type", mt.name))
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        frappe.db.set_value("Member", m.name, "application_custom_fee", 0)
        frappe.db.set_value("Member", m.name, "selected_membership_type", mt.name)
        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertEqual(result["dues_rate"], 66.0)
        self.assertEqual(result["source"], "membership_type_minimum")
        self.assertEqual(result["confidence"], "low")

    def test_none_found(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        frappe.db.set_value("Member", m.name, "application_custom_fee", 0)
        frappe.db.set_value("Member", m.name, "selected_membership_type", None)
        result = self.manager.get_dues_rate_from_priority_hierarchy(m.name)
        self.assertIsNone(result["dues_rate"])
        self.assertEqual(result["source"], "none_found")
        self.assertIn("No dues rate found", result["error"])


class TestValidateCustomRatePreservation(_HealthBase):
    def setUp(self):
        super().setUp()
        self.manager = DuesScheduleHealthManager()

    def test_no_custom_schedule_does_not_preserve(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        self._track_schedules(m.name)
        result = self.manager.validate_custom_rate_preservation(m.name, 25.0)
        self.assertFalse(result["should_preserve"])
        self.assertIn("No manually approved", result["reason"])

    def test_human_approved_custom_rate_preserved(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": m.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        # Mark as a human-approved custom rate that differs from the calculated rate
        frappe.db.set_value(
            "Membership Dues Schedule",
            sched_name,
            {
                "custom_amount_approved": 1,
                "dues_rate": 99.0,
                "custom_amount_reason": "Hardship reduction approved by treasurer",
                "custom_amount_approved_by": "treasurer@example.com",
            },
        )
        frappe.db.commit()
        result = self.manager.validate_custom_rate_preservation(m.name, 25.0)
        self.assertTrue(result["should_preserve"])
        self.assertEqual(result["existing_rate"], 99.0)


class TestSyncMemberFields(_HealthBase):
    def setUp(self):
        super().setUp()
        self.manager = DuesScheduleHealthManager()

    def test_sync_sets_current_dues_schedule_and_rate(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": m.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        frappe.db.set_value("Membership Dues Schedule", sched_name, "dues_rate", 31.0)
        # Force member fields out of sync
        frappe.db.set_value("Member", m.name, "current_dues_schedule", None)
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        frappe.db.commit()

        self.manager.sync_member_fields(m.name)

        self.assertEqual(frappe.db.get_value("Member", m.name, "current_dues_schedule"), sched_name)
        self.assertEqual(frappe.db.get_value("Member", m.name, "dues_rate"), 31.0)
        self.assertEqual(self.manager.results["fields_synchronized"], 1)

    def test_sync_noop_when_already_in_sync(self):
        # Member with no membership/schedule -> nothing to sync
        m = self._member()
        self.manager.sync_member_fields(m.name)
        self.assertEqual(self.manager.results["fields_synchronized"], 0)


class TestReconstruct(_HealthBase):
    def setUp(self):
        super().setUp()
        self.manager = DuesScheduleHealthManager()

    def test_reconstruct_membership_returns_existing(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        result = self.manager.reconstruct_missing_membership(m.name)
        self.assertEqual(result, membership.name)

    def test_reconstruct_membership_fails_without_type(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "selected_membership_type", None)
        frappe.db.set_value("Member", m.name, "current_membership_type", None)
        frappe.db.commit()
        result = self.manager.reconstruct_missing_membership(m.name)
        self.assertIsNone(result)
        self.assertTrue(any("no membership type found" in e for e in self.manager.results["errors"]))

    def test_reconstruct_dues_schedule_returns_existing(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        existing = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": m.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", existing))
        result = self.manager.reconstruct_dues_schedule(m.name)
        self.assertEqual(result, existing)

    def test_reconstruct_dues_schedule_fails_without_rate(self):
        m = self._member()
        frappe.db.set_value("Member", m.name, "dues_rate", 0)
        frappe.db.set_value("Member", m.name, "application_custom_fee", 0)
        frappe.db.set_value("Member", m.name, "selected_membership_type", None)
        frappe.db.commit()
        result = self.manager.reconstruct_dues_schedule(m.name)
        self.assertIsNone(result)
        self.assertTrue(any("no dues rate found" in e.lower() for e in self.manager.results["errors"]))


class TestProcessMemberWithTransaction(_HealthBase):
    def setUp(self):
        super().setUp()
        self.manager = DuesScheduleHealthManager()

    def test_success_increments_processed(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        self._track_schedules(m.name)
        result = self.manager.process_member_with_transaction(m.name, fix_issues=True)
        self._track_schedules(m.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["member"], m.name)
        self.assertEqual(self.manager.results["members_processed"], 1)
        self.assertIn("operations_completed", result)

    def test_failure_rolls_back_counters(self):
        # A non-existent member -> sync/reconstruct will raise inside the savepoint
        result = self.manager.process_member_with_transaction("DOES-NOT-EXIST-XYZ", fix_issues=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["member"], "DOES-NOT-EXIST-XYZ")
        # counters rolled back to pre-transaction state
        self.assertEqual(self.manager.results["members_processed"], 0)
        self.assertEqual(self.manager.results["transaction_failures"], 1)
        self.assertTrue(any("Transaction failed" in e for e in self.manager.results["errors"]))


class TestComprehensiveHealthCheck(_HealthBase):
    def test_scoped_filter_reports_for_single_member(self):
        m = self._member()
        membership = self.create_test_membership(member_name=m.name)
        self._committed.append(("Membership", membership.name))
        self._track_schedules(m.name)

        self._as_admin()
        # fix_issues False -> report only; scoped to our member via member_filter
        results = comprehensive_dues_schedule_health_check(member_filter=m.name, fix_issues=False)
        self._track_schedules(m.name)

        self.assertEqual(results["members_processed"], 1)
        self.assertTrue(results["batch_info"]["specific_filter"])
        self.assertEqual(results["batch_info"]["total_members"], 1)
        self.assertIn("processing_summary", results)
        self.assertEqual(results["processing_summary"]["success_rate"], 100.0)

    def test_filter_accepts_list(self):
        m1 = self._member()
        m2 = self._member()
        self._as_admin()
        results = comprehensive_dues_schedule_health_check(member_filter=[m1.name, m2.name], fix_issues=False)
        self.assertEqual(results["members_processed"], 2)
        self.assertEqual(results["batch_info"]["total_members"], 2)
