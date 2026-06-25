# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/dues_schedule_lifecycle_service.py

Covers pause/resume/cancel and status-transition validation, including the
invalid-transition rejection paths.

Lifecycle methods call schedule_doc.save(), so each test creates a REAL, saved
Membership Dues Schedule attached to a real Member + active Membership (via the
factory). Saves commit (after_insert hooks touch the member), so fixtures are
uniquely named, tracked, and force-deleted in tearDown.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.billing.dues_schedule_lifecycle_service import (
    DuesScheduleLifecycleService,
    get_dues_schedule_lifecycle_service,
)
from verenigingen.utils.exceptions import InvalidStatusTransitionError
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesScheduleLifecycleService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.svc = DuesScheduleLifecycleService()
        self._committed_docs = []

    def tearDown(self):
        order = {
            "Membership Dues Schedule": 0,
            "Membership": 1,
            "Member": 2,
            "Membership Type": 3,
        }
        for doctype, name in sorted(self._committed_docs, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixtures: a real Active schedule for a member with active membership
    # ------------------------------------------------------------------
    def _make_membership_type(self, minimum_amount=10.0):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"DSLS-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Lifecycle service test type"
        mt.is_active = 1
        mt.contribution_mode = "Fixed Amount"
        mt.minimum_amount = minimum_amount
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": mt.name},
            "name",
        )
        if template:
            self._committed_docs.append(("Membership Dues Schedule", template))
            tdoc = frappe.get_doc("Membership Dues Schedule", template)
            tdoc.suggested_amount = minimum_amount
            tdoc.dues_rate = minimum_amount
            tdoc.minimum_amount = minimum_amount
            tdoc.currency = "EUR"
            tdoc.save(ignore_permissions=True)
        frappe.db.commit()
        return mt

    def _make_active_schedule(self, dues_rate=10.0):
        mt = self._make_membership_type(minimum_amount=dues_rate)
        member = frappe.new_doc("Member")
        member.first_name = "Lifecycle"
        member.last_name = f"M{frappe.generate_hash(length=6)}"
        member.email = f"dsls.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.birth_date = "1990-01-01"
        member.save()
        frappe.db.commit()
        self._committed_docs.append(("Member", member.name))

        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = mt.name
        membership.start_date = today()
        membership.status = "Active"
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)
        self._committed_docs.append(("Membership", membership.name))
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        # Cancel any auto-created schedule so we control schedule state precisely.
        for nm in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", nm))
            frappe.db.set_value("Membership Dues Schedule", nm, "status", "Cancelled")

        sched = frappe.new_doc("Membership Dues Schedule")
        sched.is_template = 0
        sched.schedule_name = f"DSLS-Sched-{frappe.generate_hash(length=8)}"
        sched.member = member.name
        sched.membership = membership.name
        sched.membership_type = mt.name
        sched.currency = "EUR"
        sched.dues_rate = dues_rate
        sched.billing_frequency = "Monthly"
        sched.contribution_mode = "Fixed"
        sched.status = "Active"
        sched.next_invoice_date = add_days(today(), 30)
        sched.insert(ignore_permissions=True)
        frappe.db.commit()
        self._committed_docs.append(("Membership Dues Schedule", sched.name))
        return sched

    # ==================================================================
    # pause_schedule
    # ==================================================================
    def test_pause_active_schedule_sets_paused_and_records_reason(self):
        sched = self._make_active_schedule()
        self.svc.pause_schedule(sched, reason="Member requested pause")
        self.assertEqual(sched.status, "Paused")
        self.assertIn("Member requested pause", sched.notes)
        # Persisted.
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", sched.name, "status"), "Paused")

    def test_pause_non_active_schedule_raises(self):
        sched = self._make_active_schedule()
        self.svc.cancel_schedule(sched, reason="terminate")
        with self.assertRaises(InvalidStatusTransitionError) as cm:
            self.svc.pause_schedule(sched)
        self.assertIn("Cannot pause", str(cm.exception))

    # ==================================================================
    # resume_schedule
    # ==================================================================
    def test_resume_paused_schedule_reactivates_with_new_date(self):
        sched = self._make_active_schedule()
        self.svc.pause_schedule(sched, reason="hold")
        new_date = add_days(today(), 45)
        self.svc.resume_schedule(sched, new_next_date=new_date)
        self.assertEqual(sched.status, "Active")
        self.assertEqual(str(sched.next_invoice_date), str(new_date))
        self.assertIn("Resumed on", sched.notes)

    def test_resume_non_paused_raises(self):
        sched = self._make_active_schedule()  # Active, not Paused
        with self.assertRaises(InvalidStatusTransitionError) as cm:
            self.svc.resume_schedule(sched)
        self.assertIn("Cannot resume", str(cm.exception))

    # ==================================================================
    # cancel_schedule
    # ==================================================================
    def test_cancel_active_schedule(self):
        sched = self._make_active_schedule()
        self.svc.cancel_schedule(sched, reason="member left")
        self.assertEqual(sched.status, "Cancelled")
        self.assertIn("member left", sched.notes)

    def test_cancel_already_cancelled_is_noop(self):
        sched = self._make_active_schedule()
        self.svc.cancel_schedule(sched, reason="first")
        notes_before = sched.notes
        # Second cancel returns early without appending another note.
        self.svc.cancel_schedule(sched, reason="second")
        self.assertEqual(sched.status, "Cancelled")
        self.assertEqual(sched.notes, notes_before)

    # ==================================================================
    # validate_status_transition
    # ==================================================================
    def test_transition_new_doc_short_circuits(self):
        # A brand-new unsaved doc: is_new() True -> returns without error.
        doc = frappe.new_doc("Membership Dues Schedule")
        doc.status = "Active"
        self.assertIsNone(self.svc.validate_status_transition(doc))

    def test_transition_invalid_active_to_test_raises(self):
        sched = self._make_active_schedule()
        # Simulate a transition Active -> Test (not allowed) using _doc_before_save.
        sched._doc_before_save = frappe.copy_doc(sched)
        sched._doc_before_save.status = "Active"
        sched.status = "Test"
        with self.assertRaises(InvalidStatusTransitionError) as cm:
            self.svc.validate_status_transition(sched)
        self.assertIn("Cannot transition", str(cm.exception))

    def test_transition_valid_active_to_paused_passes(self):
        sched = self._make_active_schedule()
        sched._doc_before_save = frappe.copy_doc(sched)
        sched._doc_before_save.status = "Active"
        sched.status = "Paused"
        self.assertIsNone(self.svc.validate_status_transition(sched))

    def test_transition_same_status_short_circuits(self):
        sched = self._make_active_schedule()
        sched._doc_before_save = frappe.copy_doc(sched)
        sched._doc_before_save.status = "Active"
        sched.status = "Active"
        self.assertIsNone(self.svc.validate_status_transition(sched))

    def test_transition_from_cancelled_to_active_raises(self):
        sched = self._make_active_schedule()
        sched._doc_before_save = frappe.copy_doc(sched)
        sched._doc_before_save.status = "Cancelled"
        sched.status = "Active"
        with self.assertRaises(InvalidStatusTransitionError) as cm:
            self.svc.validate_status_transition(sched)
        # Cancelled allows no transitions.
        self.assertIn("None", str(cm.exception))

    # ==================================================================
    # singleton accessor
    # ==================================================================
    def test_singleton_accessor(self):
        self.assertIsInstance(get_dues_schedule_lifecycle_service(), DuesScheduleLifecycleService)
