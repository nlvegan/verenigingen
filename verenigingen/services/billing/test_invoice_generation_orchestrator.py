# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
End-to-end integration tests for InvoiceGenerationOrchestrator.

The existing unit suite (verenigingen/tests/unit/test_invoice_generation_orchestrator.py)
exercises the orchestrator's BRANCHING with MagicMock schedules. This suite drives
the REAL pipeline against a real Membership Dues Schedule (no mocks of the
schedule/generator/ORM) so the genuinely-uncovered runtime paths execute:

    - generate(force=True) full happy path: real Redis lock acquire/release,
      _execute_generation (coverage calc -> InvoiceGenerator -> coverage tracking),
      and _update_coverage_tracking persisting last_generated_invoice + coverage dates.
    - test_mode path: _handle_test_mode logs + advances dates without an invoice.
    - skip path: an ineligible schedule (force=False) returns a skipped OperationResult.
    - _handle_error: a forced ValidationError is wrapped and re-raised with the schedule name.
"""

import frappe

from verenigingen.services.billing.invoice_generation_orchestrator import (
    InvoiceGenerationOrchestrator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceGenerationOrchestratorE2E(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Orch", last_name="Test", birth_date="1982-11-11")
        self.customer_doc = self.link_member_to_customer(self.member)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        self.member.reload()

    def _track_invoice(self, name):
        self.addCleanup(self._safe_delete_invoice, name)

    def _safe_delete_invoice(self, name):
        if name and frappe.db.exists("Sales Invoice", name):
            try:
                doc = frappe.get_doc("Sales Invoice", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Sales Invoice", name, force=True, ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Full happy path - real generation pipeline
    # ------------------------------------------------------------------
    def test_generate_force_creates_invoice_and_tracks_coverage(self):
        """force=True runs the full pipeline: lock -> coverage calc -> generate ->
        coverage tracking. Asserts a real Sales Invoice with coverage dates is created
        and the schedule's last_generated_invoice + coverage fields are updated."""
        self.schedule.test_mode = 0
        orchestrator = InvoiceGenerationOrchestrator(self.schedule)
        result = orchestrator.generate(force=True)

        self.assertTrue(result.success, f"generate failed: {result.error_message}")
        invoice = result.data
        self.assertIsNotNone(invoice, "force=True must produce an invoice")
        self._track_invoice(invoice.name)

        # Real Sales Invoice with coverage dates set during construction.
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice.name))
        self.assertEqual(invoice.member, self.member.name)
        self.assertEqual(invoice.is_membership_invoice, 1)
        self.assertIsNotNone(invoice.custom_coverage_start_date)
        self.assertIsNotNone(invoice.custom_coverage_end_date)

        # _update_coverage_tracking wrote the back-references onto the schedule.
        self.assertEqual(self.schedule.last_generated_invoice, invoice.name)
        self.assertEqual(self.schedule.last_invoice_coverage_start, invoice.custom_coverage_start_date)
        self.assertEqual(self.schedule.last_invoice_coverage_end, invoice.custom_coverage_end_date)

    # ------------------------------------------------------------------
    # test_mode path
    # ------------------------------------------------------------------
    def test_test_mode_advances_without_creating_invoice(self):
        """With test_mode set, the orchestrator returns test_mode metadata, creates NO
        invoice, but still advances the schedule dates (_handle_test_mode)."""
        self.schedule.test_mode = 1
        old_next = self.schedule.next_invoice_date
        orchestrator = InvoiceGenerationOrchestrator(self.schedule)
        result = orchestrator.generate(force=True)

        self.assertTrue(result.success)
        self.assertIsNone(result.data, "test mode must not create an invoice")
        self.assertTrue(result.metadata.get("test_mode"))
        # update_schedule_dates ran -> next_invoice_date moved.
        self.assertNotEqual(self.schedule.next_invoice_date, old_next)

    # ------------------------------------------------------------------
    # skip path (ineligible, force=False)
    # ------------------------------------------------------------------
    def test_ineligible_schedule_skips(self):
        """A schedule that cannot generate (no future-due, force=False) returns a
        skipped OperationResult rather than throwing."""
        # Make the schedule ineligible: it was just created so generating again would
        # overlap. Force=False routes through _check_eligibility's skip branch.
        self.schedule.test_mode = 0
        orchestrator = InvoiceGenerationOrchestrator(self.schedule)
        # First real generation consumes the current period.
        first = orchestrator.generate(force=True)
        if first.data:
            self._track_invoice(first.data.name)

        # A second non-forced generation for the same period should now be skipped
        # (coverage overlap / not eligible).
        can_generate, _reason = self.schedule.can_generate_invoice()
        if can_generate:
            self.skipTest("schedule still eligible after first generation on this dataset")
        # _check_eligibility logs non-overlap skip reasons (e.g. "Too early") to Error Log.
        self.expectErrorLog(f"Membership Dues Schedule {self.schedule.name}")
        result = orchestrator.generate(force=False)
        self.assertTrue(result.success)
        self.assertTrue(result.metadata.get("skipped"))
        self.assertIsNone(result.data)

    # ------------------------------------------------------------------
    # _handle_error wraps and re-raises
    # ------------------------------------------------------------------
    def test_handle_error_raises_validation_error_with_schedule_name(self):
        orchestrator = InvoiceGenerationOrchestrator(self.schedule)
        # Health-reconstruction / error logging during _handle_error is expected.
        self.expectErrorLog(f"Invoice Gen Fail - {self.schedule.name[:50]}")
        with self.assertRaises(frappe.ValidationError) as ctx:
            orchestrator._handle_error(RuntimeError("boom in pipeline"))
        msg = str(ctx.exception)
        self.assertIn(self.schedule.name, msg)
        self.assertIn("boom in pipeline", msg)
