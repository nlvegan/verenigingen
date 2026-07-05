# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/fee_change_tracking_service.py

Covers the change-detection branches of handle_schedule_update and
handle_new_schedule that were previously uncovered: the dues-rate-change
recording path, the status -> Cancelled path, the Paused -> Active resume path,
and the handle_new_schedule initial-fee recording. Recording is delegated to
FeeChangeRecordingService, which writes a Member Fee Change History child row;
we assert the real row appears on the member.

Real documents only — no mocking of the recording service or the ORM. The
handle_* methods compare a schedule against its _doc_before_save snapshot, so we
populate that snapshot with a genuine in-memory copy of the schedule.

ISOLATION: a real Member + Membership + Membership Dues Schedule are created and
force-deleted in tearDown; the recording service commits child rows on the
member, so deletion cascades clean them up.
"""

import frappe

from verenigingen.services.billing.fee_change_tracking_service import (
    FeeChangeTrackingService,
    get_fee_change_tracking_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFeeChangeTrackingServiceBranches(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._tracked = []
        self.svc = get_fee_change_tracking_service()

    def tearDown(self):
        for doctype, name in reversed(self._tracked):
            if frappe.db.exists(doctype, name):
                try:
                    doc = frappe.get_doc(doctype, name)
                    if getattr(doc, "docstatus", 0) == 1:
                        doc.cancel()
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------
    def _make_schedule(self, amount=10.0, status="Active"):
        # Background fixtures via the shared factory (EnhancedTestCase). A low
        # minimum_amount keeps the type permissive so the custom dues_rate below
        # always validates.
        mt = self.create_test_membership_type(membership_type_name="FCT-Type", minimum_amount=0.01)
        self._tracked.append(("Membership Type", mt.name))

        member = self.create_test_member()
        self._tracked.append(("Member", member.name))

        # skip_dues_schedule_creation suppresses the on_submit hook, so our
        # schedule below is the only one — no auto-created schedule to deactivate.
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=mt.name,
            skip_dues_schedule_creation=True,
        )
        self._tracked.append(("Membership", membership.name))

        ds = frappe.new_doc("Membership Dues Schedule")
        ds.schedule_name = f"FCT-{member.name}-{frappe.generate_hash(length=8)}"
        ds.member = member.name
        ds.membership = membership.name
        ds.membership_type = mt.name
        ds.currency = "EUR"
        ds.contribution_mode = "Fixed"
        ds.dues_rate = amount
        ds.uses_custom_amount = 1
        ds.custom_amount_approved = 1
        ds.billing_frequency = "Monthly"
        ds.payment_method = "Bank Transfer"
        ds.status = status
        ds.save()
        self._tracked.append(("Membership Dues Schedule", ds.name))
        return member, ds

    def _fee_change_rows(self, member_name, change_type=None):
        filters = {"parent": member_name, "parenttype": "Member"}
        if change_type:
            filters["change_type"] = change_type
        return frappe.get_all(
            "Member Fee Change History", filters=filters, fields=["change_type", "new_dues_rate"]
        )

    def _persist_doc(self, doc):
        """Save a test doc through the real save pipeline."""
        doc.save(ignore_permissions=True)
        return doc

    # ==================================================================
    def test_singleton_factory(self):
        self.assertIsInstance(get_fee_change_tracking_service(), FeeChangeTrackingService)

    def test_handle_schedule_update_records_dues_rate_change(self):
        """A dues_rate change between _doc_before_save and the current schedule is
        recorded as a 'Fee Adjustment' and the member's denormalized dues_rate is
        synced to the new value."""
        member, ds = self._make_schedule(amount=10.0)
        before = frappe.get_doc("Membership Dues Schedule", ds.name)  # snapshot at 10.0

        ds.dues_rate = 25.0
        ds.custom_amount_reason = "Annual increase"
        ds._doc_before_save = before
        self.svc.handle_schedule_update(ds)
        frappe.db.commit()

        rows = self._fee_change_rows(member.name, change_type="Fee Adjustment")
        self.assertTrue(rows, "a Fee Adjustment history row should have been recorded")
        # Member denormalized rate mirrored to the new schedule rate.
        self.assertEqual(float(frappe.db.get_value("Member", member.name, "dues_rate")), 25.0)

    def test_handle_schedule_update_records_cancellation(self):
        """A status transition to Cancelled records a 'Schedule Cancelled' entry
        with new_amount 0."""
        member, ds = self._make_schedule(amount=18.0, status="Active")
        before = frappe.get_doc("Membership Dues Schedule", ds.name)

        ds.status = "Cancelled"
        ds._doc_before_save = before
        self.svc.handle_schedule_update(ds)
        frappe.db.commit()

        rows = self._fee_change_rows(member.name, change_type="Schedule Cancelled")
        self.assertTrue(rows, "a Schedule Cancelled history row should have been recorded")
        self.assertEqual(float(rows[0]["new_dues_rate"]), 0.0)

    def test_handle_schedule_update_records_resume(self):
        """A status transition Paused -> Active records a 'Schedule Resumed' entry
        restoring the dues rate."""
        member, ds = self._make_schedule(amount=22.0, status="Paused")
        before = frappe.get_doc("Membership Dues Schedule", ds.name)  # status Paused
        # While paused the member's effective dues rate is 0; the recording
        # service's "already at target" filter would otherwise skip the resume
        # record if the member were already mirrored to 22.0.
        frappe.db.set_value("Member", member.name, "dues_rate", 0)
        # Schedule creation may have recorded an initial 0 -> 22 entry; the
        # resume record is also 0 -> 22, which the dedup window would merge.
        # Clear prior history so the resume branch produces a fresh row.
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.fee_change_history = []
        self._persist_doc(member_doc)
        frappe.db.commit()

        ds.status = "Active"
        ds._doc_before_save = before
        self.svc.handle_schedule_update(ds)
        frappe.db.commit()

        rows = self._fee_change_rows(member.name, change_type="Schedule Resumed")
        self.assertTrue(rows, "a Schedule Resumed history row should have been recorded")
        self.assertEqual(float(rows[0]["new_dues_rate"]), 22.0)

    def test_handle_new_schedule_records_initial_fee(self):
        """handle_new_schedule records a 'New Schedule' entry with the initial
        dues rate and syncs the member's dues_rate."""
        member, ds = self._make_schedule(amount=14.0)
        # Ensure member starts at a different rate so the sync is observable.
        frappe.db.set_value("Member", member.name, "dues_rate", 0)

        self.svc.handle_new_schedule(ds)
        frappe.db.commit()

        rows = self._fee_change_rows(member.name, change_type="New Schedule")
        self.assertTrue(rows, "a New Schedule history row should have been recorded")
        self.assertEqual(float(rows[0]["new_dues_rate"]), 14.0)
        self.assertEqual(float(frappe.db.get_value("Member", member.name, "dues_rate")), 14.0)
