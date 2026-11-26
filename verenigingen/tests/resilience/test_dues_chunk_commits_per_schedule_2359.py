# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#2359: a dues invoice chunk must commit as it goes, so a job timeout loses at most one schedule.

Since #2235 an RQ ``JobTimeoutException`` propagates out of ``process_invoice_chunk`` and
``_process_sequential``; Frappe's ``execute_job`` then rolls back everything uncommitted.
Both committed only after the loop, so a run longer than the job timeout (1800 s for a
chunk) discarded every invoice it had built, on every run.

Instrument, stated: ``frappe.db.commit`` is replaced by a recorder that does NOT commit (the
test transaction must stay rollback-able) and snapshots the invoices that exist in the
session at that moment. "Survives the timeout" is therefore read as "a commit was issued
while the first schedule's invoice was already in the session", which is what execute_job's
rollback would otherwise take away. The timeout is injected at ``Sales Invoice.submit`` for
the SECOND schedule only; the first goes through the real generation flow.
The recorder proves a commit was issued; survival across a real rollback was verified
separately in review (both paths, 3 schedules, timeout on the 3rd).
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today
from rq.timeouts import JobTimeoutException

from verenigingen.services.billing.bulk_invoice_generation_service import (
    BulkGenerationResult,
    get_bulk_invoice_generation_service,
    process_invoice_chunk,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesChunkCommitsPerSchedule(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.schedules = [self._make_schedule(f"Chunk2359{i}") for i in range(2)]
        self.customers = [
            frappe.db.get_value("Member", frappe.db.get_value("Membership Dues Schedule", s, "member"), "customer")
            for s in self.schedules
        ]

    def _make_schedule(self, first_name):
        member = self.create_test_member(first_name=first_name, last_name="Probe", birth_date="1975-09-09")
        self.create_test_membership(member_name=member.name, membership_type_name="Regular Member")
        name = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, limit=1
        )[0].name
        frappe.db.set_value("Membership Dues Schedule", name, "next_invoice_date", add_days(today(), -1))
        return name

    def _first_customer_invoices(self):
        return set(frappe.get_all("Sales Invoice", filters={"customer": self.customers[0]}, pluck="name"))

    def _run_with_second_submit_timing_out(self, runner):
        """Run ``runner`` with the 2nd Sales Invoice.submit raising a job timeout.

        Returns (commit_snapshots, invoices_of_first_customer_at_the_end). Each snapshot is
        (first customer's invoice set, number of submit calls so far) at the moment a commit
        was requested.
        """
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

        real_submit = SalesInvoice.submit
        calls = []

        def submit(doc, *args, **kwargs):
            calls.append(doc.name)
            if len(calls) == 2:
                raise JobTimeoutException("t")
            return real_submit(doc, *args, **kwargs)

        snapshots = []
        with patch.object(SalesInvoice, "submit", submit), patch.object(
            frappe.db, "commit", side_effect=lambda *a, **k: snapshots.append((self._first_customer_invoices(), len(calls)))
        ):
            with self.assertRaises(JobTimeoutException):
                runner()
        self.assertEqual(len(calls), 2, "the first schedule must have reached submit before the timeout")
        return snapshots, self._first_customer_invoices()

    def test_chunk_commits_the_first_invoice_before_a_later_schedule_times_out(self):
        snapshots, first_invoices = self._run_with_second_submit_timing_out(
            lambda: process_invoice_chunk(
                self.schedules, chunk_id=1, total_chunks=1, cutoff_date=getdate(today())
            )
        )
        self.assertTrue(first_invoices, "fixture: the first schedule must have produced an invoice")
        self.assertTrue(
            any(first_invoices <= invoices for invoices, _ in snapshots),
            "no commit was issued after the first invoice was built; the timeout rollback takes it",
        )

    def test_sequential_run_commits_the_first_invoice_before_a_later_schedule_times_out(self):
        snapshots, first_invoices = self._run_with_second_submit_timing_out(
            lambda: get_bulk_invoice_generation_service()._process_sequential(
                self.schedules, getdate(today()), test_mode=False, result=BulkGenerationResult()
            )
        )
        self.assertTrue(first_invoices, "fixture: the first schedule must have produced an invoice")
        self.assertTrue(
            any(first_invoices <= invoices for invoices, _ in snapshots),
            "no commit was issued after the first invoice was built; the timeout rollback takes it",
        )

    def test_the_schedule_that_timed_out_is_not_committed(self):
        """Control for the wrong fix 'commit in a finally': the in-flight schedule's partial work must roll back."""
        snapshots, _ = self._run_with_second_submit_timing_out(
            lambda: process_invoice_chunk(
                self.schedules, chunk_id=1, total_chunks=1, cutoff_date=getdate(today())
            )
        )
        after_timeout_started = [snap for snap in snapshots if snap[1] >= 2]
        self.assertEqual(
            after_timeout_started, [], "a commit was issued once the timed-out schedule had started"
        )
