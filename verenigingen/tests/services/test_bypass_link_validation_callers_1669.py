# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#1669: four secure_document_operation call sites passed bypass_validations=["link_validation"]
unconditionally. secure_document_operation REFUSES that argument (PermissionError) to anyone
but System Manager / Verenigingen System Administrator, so every other actor reaching them
had the write refused:

* member_history_update_service.refresh_fee_change_history  -> whitelisted endpoint
  financial_api.refresh_fee_change_history (@high_security_api ADMIN: Verenigingen
  Administrator / Treasurer / National Board Member profiles pass, bare System Manager does not)
* member_fee_change_history_service.update_fee_change_in_history -> called from the refresh
* invoice_error_handler_service.handle_invoice_generation_failure (two sites) -> reached from
  BulkInvoiceGenerationService._process_sequential, which runs as the user that enqueued
  api.dues_invoice_workflow.generate_missing_invoices (critical_api FINANCIAL; same profiles).
  frappe.enqueue runs the job as the enqueuing user (background_jobs.execute_job set_user).

The actor is a Verenigingen Treasurer (role profile) WITHOUT System Manager (the Verenigingen
Administrator profile INCLUDES System Manager, so it is bypass-capable and unaffected): the
realistic non-System-Manager caller of both entry points.

Probe shortcuts (stated, not hidden): the invoice-failure tests make Membership Dues Schedule
.generate_invoice raise frappe.ValidationError (the same technique test_bulk_invoice_generation
_service uses) to stand in for a real generation failure; everything after that -- the
bulk service's except branch, the recovery handler, secure_document_operation, the persisted
write -- is real. The broken-link fixture inserts the child row with db_insert (a normal save
would refuse it) to stand in for legacy data.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.secure_operations import can_use_bypass_validations


class _ActorMixin:
    def _make_actor(self, label):
        email = f"{label}-{frappe.generate_hash(length=8)}@bypass1669.local".lower()
        user = self.create_test_user_with_roles(email=email, roles=["Verenigingen Treasurer"])
        grant_matching_role_profiles(user.name, "Verenigingen Treasurer")
        self.assertNotIn("System Manager", frappe.get_roles(user.name))
        self.assertFalse(can_use_bypass_validations(user.name), "the actor must NOT be bypass-capable")
        return user.name


class TestFeeHistoryWritersAsNonSystemManager(_ActorMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        membership_type = self.create_test_membership_type(amount=15.0)
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="Bypass1669",
            last_name="Fee",
            membership_type_name=membership_type.name,
            start_date=today(),
        )
        self.actor = self._make_actor("fee")

    def _refresh_as(self, user):
        from verenigingen.api.member.financial_api import refresh_fee_change_history

        previous = frappe.session.user
        frappe.set_user(user)
        try:
            return refresh_fee_change_history(member_name=self.member.name)
        finally:
            frappe.set_user(previous)

    def _fee_row_1669(self):
        self.member.reload()
        rows = [r for r in self.member.fee_change_history or [] if r.dues_schedule == self.schedule.name]
        return rows[0] if rows else None

    def test_refresh_endpoint_writes_history_for_non_system_manager(self):
        existing = self._fee_row_1669()
        if existing:
            frappe.db.delete("Member Fee Change History", {"name": existing.name})
        response = self._refresh_as(self.actor)
        self.assertTrue(response["success"], response)
        row = self._fee_row_1669()
        self.assertIsNotNone(row, "the refresh reported success but wrote no history row")
        self.assertEqual(float(row.new_dues_rate), float(self.schedule.dues_rate))

    def _update_rate_as(self, user, new_rate):
        previous = frappe.session.user
        frappe.set_user(user)
        try:
            frappe.get_doc("Member", self.member.name).update_fee_change_in_history(
                {
                    "name": self.schedule.name,
                    "schedule_name": self.schedule.schedule_name,
                    "dues_rate": new_rate,
                    "billing_frequency": self.schedule.billing_frequency,
                    "change_type": "Fee Adjustment",
                    "reason": "1669 probe",
                }
            )
        finally:
            frappe.set_user(previous)

    def test_update_fee_change_in_history_persists_for_non_system_manager(self):
        """Site member_fee_change_history_service ~264, called directly: its failure is
        swallowed (logged), so the only observable is whether the row changed."""
        self.assertTrue(self._fee_row_1669(), "fixture must start with a history row to update")
        new_rate = float(self.schedule.dues_rate) + 7
        self._update_rate_as(self.actor, new_rate)
        self.assertEqual(float(self._fee_row_1669().new_dues_rate), new_rate)

    def _insert_broken_link_row(self):
        """Legacy data: a Member Payment History row carrying a reference_name but no
        reference_doctype -- the dynamic-link shape secure_document_operation's
        link_validation bypass exists to tolerate ("Reference DocType must be set first").
        db_insert stands in for how such a row came to exist (a normal save refuses it)."""
        row = frappe.get_doc(
            {
                "doctype": "Member Payment History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "payment_history",
                "idx": 99,
                "reference_name": f"GHOST-{frappe.generate_hash(length=6)}",
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "Member Payment History", {"name": row.name})

    def test_system_manager_still_tolerates_a_broken_link_row(self):
        """OPPOSITE HARM control: the bypass exists so a legacy dead dynamic link on the Member
        does not block history maintenance. Whoever may bypass must still get it -- this test
        fails if the fix is 'never ask for the bypass'."""
        self._insert_broken_link_row()
        admin = self.ensure_test_admin_user().name
        self.assertTrue(can_use_bypass_validations(admin))
        new_rate = float(self.schedule.dues_rate) + 3
        self._update_rate_as(admin, new_rate)
        self.assertEqual(float(self._fee_row_1669().new_dues_rate), new_rate)

    def test_non_system_manager_does_not_write_through_a_broken_link_row(self):
        """The same state for the actor who may NOT bypass: the genuine link error stops the
        write (and is logged), it is not written through, and not a bogus permission refusal."""
        self._insert_broken_link_row()
        before = float(self._fee_row_1669().new_dues_rate)
        self.expectErrorLog()
        self._update_rate_as(self.actor, before + 5)
        self.assertEqual(float(self._fee_row_1669().new_dues_rate), before)
        logged = frappe.get_all(
            "Error Log",
            filters={"method": ["like", "Secure Operation Failed%"]},
            fields=["error"],
            order_by="creation desc",
            limit=1,
        )
        self.assertIn("must be set first", logged[0].error)
        self.assertNotIn("bypass validations", logged[0].error)


class TestInvoiceFailureTrackingAsNonSystemManager(_ActorMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            get_bulk_invoice_generation_service,
        )

        self.svc = get_bulk_invoice_generation_service()
        self.member = self.create_test_member(first_name="Bypass1669", last_name="Inv", birth_date="1975-09-09")
        self.create_test_membership(member_name=self.member.name, membership_type_name="Regular Member")
        name = frappe.get_all(
            "Membership Dues Schedule", filters={"member": self.member.name, "status": "Active"}, limit=1
        )[0].name
        self.schedule_name = name
        frappe.db.set_value("Membership Dues Schedule", name, "next_invoice_date", add_days(today(), -1))
        self.actor = self._make_actor("inv")

    def _fail_generation_as(self, user, message):
        from verenigingen.services.billing.bulk_invoice_generation_service import BulkGenerationResult
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        original = MembershipDuesSchedule.generate_invoice
        target = self.schedule_name

        def raises(self_doc, *a, **k):
            if self_doc.name == target:
                raise frappe.ValidationError(message)
            return original(self_doc, *a, **k)

        previous = frappe.session.user
        MembershipDuesSchedule.generate_invoice = raises
        frappe.set_user(user)
        self.expectErrorLog()
        try:
            return self.svc._process_sequential(
                [target], getdate(today()), test_mode=False, result=BulkGenerationResult()
            )
        finally:
            MembershipDuesSchedule.generate_invoice = original
            frappe.set_user(previous)

    def _persisted(self, field):
        return frappe.db.get_value("Membership Dues Schedule", self.schedule_name, field)

    def test_retry_tracking_is_persisted_for_non_system_manager(self):
        """Site invoice_error_handler_service ~240."""
        self.assertEqual(int(self._persisted("custom_invoice_retry_count") or 0), 0)
        self._fail_generation_as(self.actor, "invalid coverage window")
        self.assertEqual(int(self._persisted("custom_invoice_retry_count") or 0), 1)

    def test_manual_review_flag_is_persisted_for_non_system_manager(self):
        """Site invoice_error_handler_service ~271: the escalation write itself. 'permission
        denied' is a critical pattern, so after the third failure it flags instead of advancing."""
        frappe.db.set_value("Membership Dues Schedule", self.schedule_name, "custom_invoice_retry_count", 2)
        self._fail_generation_as(self.actor, "permission denied: cannot create Sales Invoice")
        self.assertEqual(int(self._persisted("custom_requires_manual_review") or 0), 1)
