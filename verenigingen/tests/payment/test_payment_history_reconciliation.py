#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Task 9: reconcile the payment-history catch-all against
source-of-truth Sales Invoices instead of blindly re-enqueuing through the
circular `member_doc.add_invoice_to_payment_history(...)` path (which just
re-enqueues through the batch processor and always returns True, so the old
validator counted "repaired" without ever verifying a row actually landed).

The fixed `validate_and_repair_payment_history` must instead:
- find in-window submitted Sales Invoices missing from the member's
  `payment_history` child table with a single batched query (no per-invoice
  get_doc), and
- drive the real drain job (`background_jobs.drain_member_payment_history`)
  once per member (deduplicated by job_id), never call
  `add_invoice_to_payment_history` directly.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import (
    build_eur_membership_invoice,
    receive_against_invoice,
)
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company


class TestPaymentHistoryReconciliation(EnhancedTestCase):
    """TDD coverage for the source-of-truth reconciliation rewrite."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # receive_against_invoice READS the bank account; provision it here, not in a test body.
        get_eur_bank_account(get_eur_test_company())

    def setUp(self):
        super().setUp()

        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        # Company whose receivable currency matches the EUR invoices these tests
        # build. Ensure the shared test item exists up front (as Administrator);
        # creating it later inside a restricted context could hit permission limits.
        self.test_company = get_eur_test_company()
        self._ensure_test_item("TEST-MEMBERSHIP")

    def _make_member_with_customer(self, suffix):
        member = self.create_test_member(
            first_name=f"Reconcile{suffix}",
            last_name="TestMember",
            email=f"reconcile.test.{suffix}@example.com",
        )
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.save()
            member.customer = customer.name
            member.save()
            self.track_doc("Customer", customer.name)
        return member

    def test_missing_invoice_is_detected_and_enqueued_once(self):
        """An in-window submitted invoice with no payment_history row must
        trigger exactly one deduplicated drain-job enqueue for its member."""
        member = self._make_member_with_customer("missing")
        invoice = build_eur_membership_invoice(self, member.customer, 42.0)

        # Defensively clear any payment_history row for this invoice so it is a
        # genuine gap for the reconciliation to find. Payment-history population on
        # Sales Invoice submit now runs only via the async batch/drain path (the
        # synchronous on_submit rebuild was removed), which does not run inline in
        # tests -- but keep this delete so the test does not depend on that timing
        # (mirrors test_payment_history_validator.py's _clear_history_rows pattern).
        frappe.db.delete("Member Payment History", {"invoice": invoice.name})

        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()

        self.assertTrue(result["success"])

        job_ids = [k.get("job_id") for k in calls]
        expected_job_id = f"fin_history_payment_{member.name}"
        self.assertIn(expected_job_id, job_ids)
        # Enqueued exactly once for this member -- dedup by member, not per invoice.
        self.assertEqual(job_ids.count(expected_job_id), 1)

        # The call must target the real drain job, not the circular
        # add_invoice_to_payment_history re-enqueue path.
        enqueued_call = calls[job_ids.index(expected_job_id)]
        self.assertEqual(enqueued_call.get("member"), member.name)
        self.assertEqual(enqueued_call.get("customer"), member.customer)

    def test_already_reflected_invoice_is_not_reprocessed(self):
        """An invoice already reflected in payment_history must not be re-enqueued."""
        member = self._make_member_with_customer("reflected")
        invoice = build_eur_membership_invoice(self, member.customer, 42.0)

        from verenigingen.utils.background_jobs import drain_member_payment_history

        # Drive the real drain job synchronously so payment_history genuinely
        # reflects this invoice (independent of whatever the on_submit sync
        # handler already did).
        drain_member_payment_history(member.name, member.customer)

        self.assertTrue(
            frappe.db.exists("Member Payment History", {"parent": member.name, "invoice": invoice.name}),
            "Precondition failed: invoice should be reflected in payment_history before reconciling",
        )

        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()

        self.assertTrue(result["success"])

        job_ids = [k.get("job_id") for k in calls]
        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)

    def _enqueued_job_ids(self):
        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()
        self.assertTrue(result["success"], result)
        return [k.get("job_id") for k in calls], result

    def _drained_invoice(self, suffix, rate=42.0):
        from verenigingen.utils.background_jobs import drain_member_payment_history

        member = self._make_member_with_customer(suffix)
        invoice = build_eur_membership_invoice(self, member.customer, rate)
        drain_member_payment_history(member.name, member.customer)
        self.assertTrue(
            frappe.db.exists("Member Payment History", {"parent": member.name, "invoice": invoice.name}),
            "Precondition: row must exist before the invoice changes",
        )
        return member, invoice

    def test_stale_row_after_a_payment_is_repaired(self):
        """A Payment Entry whose drain was lost leaves an existing row Unpaid/full
        outstanding. The validator must enqueue the member's drain (#3190).

        Real flow: the Payment Entry is submitted for real and NO drain is run
        afterwards (that is the lost drain). The precondition proves the row is stale."""
        member, invoice = self._drained_invoice("stale")
        receive_against_invoice(self, invoice.name, 42.0)
        row = frappe.db.get_value(
            "Member Payment History",
            {"parent": member.name, "invoice": invoice.name},
            ["outstanding_amount", "payment_status"],
            as_dict=True,
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)
        self.assertGreater(
            row.outstanding_amount, 0, "Precondition: the row must still be stale (drain not run)"
        )

        job_ids, result = self._enqueued_job_ids()

        self.assertEqual(job_ids.count(f"fin_history_payment_{member.name}"), 1)
        self.assertGreaterEqual(result["stale_found"], 1)

    def test_stale_payment_status_alone_is_detected(self):
        """Status/outstanding agree with the invoice but payment_status does not."""
        member, invoice = self._drained_invoice("statusonly")
        # Probe shortcut: direct write of the row's payment_status to stand in for a drifted row.
        frappe.db.set_value(
            "Member Payment History",
            {"parent": member.name, "invoice": invoice.name},
            "payment_status",
            "Paid",
        )

        job_ids, _result = self._enqueued_job_ids()

        self.assertIn(f"fin_history_payment_{member.name}", job_ids)

    def test_up_to_date_row_is_not_redrained(self):
        """Control: a paid invoice whose row was drained AFTER the payment is current.
        Uses a real payment so the row carries non-default status/outstanding/paid values
        that a wrong comparison (e.g. always-stale) would flag."""
        member, invoice = self._drained_invoice("current")
        receive_against_invoice(self, invoice.name, 42.0)
        from verenigingen.utils.background_jobs import drain_member_payment_history

        drain_member_payment_history(member.name, member.customer)
        row = frappe.db.get_value(
            "Member Payment History",
            {"parent": member.name, "invoice": invoice.name},
            ["outstanding_amount", "payment_status"],
            as_dict=True,
        )
        self.assertEqual(row.outstanding_amount, 0, "Precondition: the drain refreshed the row")

        job_ids, _result = self._enqueued_job_ids()

        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)

    def test_invoice_older_than_seven_days_is_covered(self):
        """A missing row on a 30-day-old invoice (outside the former 7-day window) is found."""
        member = self._make_member_with_customer("old")
        invoice = build_eur_membership_invoice(self, member.customer, 42.0)
        frappe.db.delete("Member Payment History", {"invoice": invoice.name})
        old = frappe.utils.add_days(frappe.utils.now_datetime(), -30)
        frappe.db.set_value("Sales Invoice", invoice.name, "creation", old, update_modified=False)

        job_ids, _result = self._enqueued_job_ids()

        self.assertIn(f"fin_history_payment_{member.name}", job_ids)

    def test_invoice_older_than_the_window_is_not_scanned(self):
        """Control: the window is bounded, not unlimited."""
        from verenigingen.utils.payment_history_validator import RECONCILIATION_WINDOW_DAYS

        member = self._make_member_with_customer("ancient")
        invoice = build_eur_membership_invoice(self, member.customer, 42.0)
        frappe.db.delete("Member Payment History", {"invoice": invoice.name})
        ancient = frappe.utils.add_days(frappe.utils.now_datetime(), -(RECONCILIATION_WINDOW_DAYS + 5))
        frappe.db.set_value("Sales Invoice", invoice.name, "creation", ancient, update_modified=False)

        job_ids, _result = self._enqueued_job_ids()

        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)

    def test_drains_enqueued_per_run_are_capped(self):
        """The hourly job enqueues at most MAX_MEMBER_DRAINS_PER_RUN drains and reports the rest."""
        from verenigingen.utils import payment_history_validator as validator

        members = [self._make_member_with_customer(f"cap{i}") for i in range(3)]
        for m in members:
            inv = build_eur_membership_invoice(self, m.customer, 42.0)
            frappe.db.delete("Member Payment History", {"invoice": inv.name})

        with patch.object(validator, "MAX_MEMBER_DRAINS_PER_RUN", 1):
            job_ids, result = self._enqueued_job_ids()

        mine = {f"fin_history_payment_{m.name}" for m in members}
        self.assertEqual(len(mine & set(job_ids)), 1)
        self.assertGreaterEqual(result["deferred_members"], 2)

    def test_reconciliation_query_count_does_not_grow_with_gaps(self):
        """Two batched queries (scan + row-cap check), however many members have gaps (the
        decorator stack's own queries are excluded by calling the undecorated function)."""
        from verenigingen.utils import payment_history_validator as validator

        for i in range(3):
            m = self._make_member_with_customer(f"qc{i}")
            inv = build_eur_membership_invoice(self, m.customer, 42.0)
            frappe.db.delete("Member Payment History", {"invoice": inv.name})
        inner = validator.validate_and_repair_payment_history
        while hasattr(inner, "__wrapped__"):
            inner = inner.__wrapped__

        sql_calls = []
        real_sql = frappe.db.sql

        def counting_sql(*a, **k):
            sql_calls.append(a[0])
            return real_sql(*a, **k)

        # Mock justified: call-through spy that counts queries; it runs the real SQL unchanged.
        with patch.object(frappe.db, "sql", counting_sql), patch.object(
            validator.frappe, "enqueue", side_effect=lambda *a, **k: None
        ):
            result = inner()

        self.assertGreaterEqual(result["missing_found"], 3)
        self.assertEqual(len(sql_calls), 2, sql_calls)

    def _assert_clean_after_drain(self, member):
        from verenigingen.utils.background_jobs import drain_member_payment_history

        drain_member_payment_history(member.name, member.customer)
        job_ids, _result = self._enqueued_job_ids()
        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)

    def test_status_only_difference_is_stale(self):
        """Outstanding and payment_status agree; only the invoice status differs.

        Probe shortcut: the invoice status is written directly ("Unpaid and Discounted" is what
        ERPNext's invoice-discounting flow writes; payment_status stays Unpaid)."""
        member, invoice = self._drained_invoice("statusdiff")
        frappe.db.set_value("Sales Invoice", invoice.name, "status", "Unpaid and Discounted")
        row = frappe.db.get_value(
            "Member Payment History",
            {"parent": member.name, "invoice": invoice.name},
            ["outstanding_amount", "payment_status", "status"],
            as_dict=True,
        )
        self.assertGreater(row.outstanding_amount, 0)
        self.assertEqual(row.payment_status, "Unpaid")

        job_ids, _result = self._enqueued_job_ids()

        self.assertIn(f"fin_history_payment_{member.name}", job_ids)

    def test_overdue_job_leaves_a_stale_row_that_is_repaired(self):
        """Real writer: ERPNext's daily update_invoice_status marks the invoice Overdue."""
        from erpnext.controllers.accounts_controller import update_invoice_status

        member, invoice = self._drained_invoice("overdue")
        frappe.db.sql(
            "UPDATE `tabPayment Schedule` SET due_date = %s WHERE parent = %s",
            (frappe.utils.add_days(frappe.utils.today(), -5), invoice.name),
        )
        update_invoice_status()
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "status"), "Overdue")

        job_ids, _result = self._enqueued_job_ids()

        self.assertIn(f"fin_history_payment_{member.name}", job_ids)
        self._assert_clean_after_drain(member)

    def test_partly_paid_is_clean_after_drain(self):
        """Flap control: a drained Partly Paid row is not re-reported."""
        member, invoice = self._drained_invoice("partly")
        receive_against_invoice(self, invoice.name, 10.0)
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "status"), "Partly Paid")
        self._assert_clean_after_drain(member)

    def test_credit_note_is_clean_after_drain(self):
        """Flap control: invoice + credit note rows are not re-reported after a drain."""
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

        member, invoice = self._drained_invoice("creditnote")
        credit_note = make_sales_return(invoice.name)
        credit_note.insert()
        credit_note.submit()
        self.track_doc("Sales Invoice", credit_note.name)
        self._assert_clean_after_drain(member)

    def test_fallback_row_without_status_is_clean_after_drain(self):
        """Flap control: a row written by _minimal_entry (status NULL) is not stale forever.

        The builder stays patched through the validate, so the fallback row is not
        overwritten by a later real drain."""
        from verenigingen.utils.background_jobs import drain_member_payment_history

        member = self._make_member_with_customer("fallback")
        invoice = build_eur_membership_invoice(self, member.customer, 42.0)
        frappe.db.delete("Member Payment History", {"invoice": invoice.name})
        # Mock justified: failure injection -- forces the builder's last-resort fallback row.
        # The service imports the builder inside the method, so patch it at its source.
        with patch("verenigingen.utils.payment_history_builder.build_payment_history_entry", return_value=None):
            drain_member_payment_history(member.name, member.customer)
            row = frappe.db.get_value(
                "Member Payment History",
                {"parent": member.name, "invoice": invoice.name},
                ["status", "payment_status"],
                as_dict=True,
            )
            self.assertIsNotNone(row, "Precondition: a fallback row must exist")
            self.assertFalse(row.status, "Precondition: fallback row carries no status")
            job_ids, _result = self._enqueued_job_ids()
        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)

    def test_member_over_the_row_cap_is_clean_after_drain(self):
        """Flap control: 33 invoices, drain, validate. _trim_history keeps 30 rows, so the
        3 dropped invoices must not be re-reported as missing every hour."""
        from verenigingen.utils.payment_history_validator import PAYMENT_HISTORY_MAX_ROWS

        member = self._make_member_with_customer("cap33")
        for _ in range(PAYMENT_HISTORY_MAX_ROWS + 3):
            build_eur_membership_invoice(self, member.customer, 42.0)
        self._assert_clean_after_drain(member)
        self.assertEqual(
            frappe.db.count("Member Payment History", {"parent": member.name}), PAYMENT_HISTORY_MAX_ROWS
        )
