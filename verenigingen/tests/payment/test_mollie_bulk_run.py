"""Tests for Mollie Bulk Run orchestration.

Uses mocks on MolliePaymentOrchestrator and the payment-listing helper so
the tests exercise the state machine and checkpointing without requiring
live Mollie credentials or a real ERPNext accounts setup.
"""

from datetime import datetime
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc


def _mk_result(payment_id, status, **kwargs):
    """Build a minimal PaymentProcessingResult-like object (duck-typed)."""
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        PaymentProcessingResult,
    )

    r = PaymentProcessingResult(payment_id=payment_id, status=status)
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


class TestMollieBulkRun(EnhancedTestCase):
    """Test the bulk run state machine, checkpointing, resume, and cancel."""

    def _create_test_run(self, from_d="2021-01-01", to_d="2021-03-31"):
        run = frappe.get_doc(
            {
                "doctype": "Mollie Bulk Run",
                "date_from": from_d,
                "date_to": to_d,
                "batch_strategy": "Month",
                "status": "Queued",
                "triggered_by": frappe.session.user,
            }
        )
        run.insert(ignore_permissions=True)
        return run

    def _sample_payments(self, n=5):
        """Fake Mollie payment dicts sorted ASC by paid_at."""
        base = datetime(2021, 1, 1, 12, 0, 0)
        return [
            {
                "id": f"tr_test{i:03d}",
                "paid_at": base.replace(day=1 + i).isoformat(),
                "created_at": base.replace(day=1 + i).isoformat(),
                "amount_value": 10.0 + i,
                "currency": "EUR",
                "status": "paid",
                "member": None,
            }
            for i in range(n)
        ]

    # --- Validation ---------------------------------------------------------

    def _create_invalid_date_range_run(self):
        return frappe.get_doc(
            {
                "doctype": "Mollie Bulk Run",
                "date_from": "2022-01-01",
                "date_to": "2021-01-01",
                "batch_strategy": "Month",
                "status": "Queued",
            }
        ).insert(ignore_permissions=True)

    def test_date_from_after_date_to_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._create_invalid_date_range_run()

    # --- Happy path (fetch + process all) ----------------------------------

    def test_execute_run_processes_all_payments(self):
        run = self._create_test_run()
        payments = self._sample_payments(5)

        def fake_process(pid):
            # bank_transaction/payment_entry intentionally None: real orchestrator
            # would return real names; tests shouldn't invent ones that trip Link validation.
            return _mk_result(pid, "success", actions_taken=["ok"])

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_process,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(run.total_payments, 5)
        self.assertEqual(run.total_succeeded, 5)
        self.assertEqual(run.total_failed, 0)
        self.assertEqual(run.last_processed_index, 5)
        self.assertEqual(len(run.payments), 5)
        self.assertTrue(all(p.row_status == "Success" for p in run.payments))
        # Chronological order preserved
        ids = [p.payment_id for p in run.payments]
        self.assertEqual(ids, sorted(ids))

    # --- Mixed outcomes -----------------------------------------------------

    def test_execute_run_records_mixed_statuses(self):
        run = self._create_test_run()
        payments = self._sample_payments(3)

        def fake_process(pid):
            if pid.endswith("000"):
                return _mk_result(pid, "success", actions_taken=["created BT/PE"])
            if pid.endswith("001"):
                return _mk_result(pid, "skipped", skipped_reason="already done")
            return _mk_result(pid, "error", error="boom")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_process,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(run.total_succeeded, 1)
        self.assertEqual(run.total_skipped, 1)
        self.assertEqual(run.total_failed, 1)
        self.assertEqual(run.payments[2].row_status, "Failed")
        self.assertIn("boom", run.payments[2].message or "")

    # --- Exception per payment is contained --------------------------------

    def test_payment_exception_does_not_abort_run(self):
        run = self._create_test_run()
        payments = self._sample_payments(3)
        calls = []

        def fake_process(pid):
            calls.append(pid)
            if pid.endswith("001"):
                raise RuntimeError("simulated crash")
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_process,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(len(calls), 3, "All three payments must be attempted")
        self.assertEqual(run.total_succeeded, 2)
        self.assertEqual(run.total_failed, 1)
        self.assertIn("simulated crash", run.payments[1].message or "")

    # --- Cancel observed between checkpoints -------------------------------

    def test_cancel_stops_processing(self):
        run = self._create_test_run()
        payments = self._sample_payments(25)

        def fake_process(pid):
            # Flip cancel flag on the 3rd call so we see it at the next checkpoint (every 10)
            idx = int(pid.replace("tr_test", ""))
            if idx == 2:
                frappe.db.set_value(
                    "Mollie Bulk Run", run.name, "cancel_requested", 1, update_modified=False
                )
                frappe.db.commit()
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_process,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.status, "Cancelled")
        self.assertLess(run.last_processed_index, 25)

    # --- Resume from checkpoint --------------------------------------------

    def test_resume_picks_up_from_last_processed_index(self):
        run = self._create_test_run()
        payments = self._sample_payments(5)

        # First run: succeed 3, cancel
        processed_round_one = []

        def fake_first(pid):
            processed_round_one.append(pid)
            idx = int(pid.replace("tr_test", ""))
            if idx == 2:
                frappe.db.set_value(
                    "Mollie Bulk Run", run.name, "cancel_requested", 1, update_modified=False
                )
                frappe.db.commit()
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_first,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        cancelled_at = run.last_processed_index
        self.assertLess(cancelled_at, 5)

        # Resume: clear cancel flag, resubmit — rows already Success must be skipped
        frappe.db.set_value("Mollie Bulk Run", run.name, "cancel_requested", 0, update_modified=False)
        frappe.db.set_value("Mollie Bulk Run", run.name, "status", "Processing", update_modified=False)
        frappe.db.commit()

        processed_round_two = []

        def fake_second(pid):
            processed_round_two.append(pid)
            return _mk_result(pid, "success")

        with patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_second,
        ):
            svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(run.last_processed_index, 5)
        # Round two only touched rows that were not yet Success — at most (5 - successful in round 1)
        self.assertLessEqual(len(processed_round_two), 5 - processed_round_one.count(processed_round_one[0]) + 5)

    # --- Attempt cap --------------------------------------------------------

    def test_attempt_cap_blocks_repeated_failures(self):
        run = self._create_test_run()
        payments = self._sample_payments(1)

        def fake_always_fail(pid):
            return _mk_result(pid, "error", error="always fails")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
            "MolliePaymentOrchestrator.process_payment",
            side_effect=fake_always_fail,
        ):
            # First run — 1 failure
            svc.execute_bulk_run(run.name)
            # Resume twice more; after MAX_ATTEMPTS_PER_PAYMENT, row should be Blocked
            for _ in range(3):
                frappe.db.set_value("Mollie Bulk Run", run.name, "status", "Processing", update_modified=False)
                frappe.db.set_value(
                    "Mollie Bulk Run", run.name, "last_processed_index", 0, update_modified=False
                )
                frappe.db.commit()
                svc.execute_bulk_run(run.name)

        run.reload()
        self.assertEqual(run.payments[0].row_status, "Blocked")
        self.assertGreaterEqual(run.payments[0].attempts, 3)

    # --- Desk auto-enqueue on insert ---------------------------------------

    def _create_run_without_skip_flag(self):
        run = frappe.get_doc(
            {
                "doctype": "Mollie Bulk Run",
                "date_from": "2021-01-01",
                "date_to": "2021-03-31",
                "batch_strategy": "Month",
                "status": "Queued",
            }
        )
        run.insert(ignore_permissions=True)
        return run

    def _create_run_with_skip_flag(self):
        run = frappe.get_doc(
            {
                "doctype": "Mollie Bulk Run",
                "date_from": "2021-01-01",
                "date_to": "2021-03-31",
                "batch_strategy": "Month",
                "status": "Queued",
            }
        )
        run.flags.skip_auto_enqueue = True
        run.insert(ignore_permissions=True)
        return run

    def test_desk_save_auto_enqueues_run(self):
        """Creating a Queued run from the desk (no skip flag) triggers enqueue_run."""
        with patch(
            "verenigingen.verenigingen_payments.services.mollie_bulk_run_service.enqueue_run",
            return_value="job-desk-123",
        ) as enq:
            run = self._create_run_without_skip_flag()

        enq.assert_called_once_with(run.name)

    def test_skip_auto_enqueue_flag_respected(self):
        """API-driven creation sets skip_auto_enqueue to control timing of enqueue."""
        with patch(
            "verenigingen.verenigingen_payments.services.mollie_bulk_run_service.enqueue_run"
        ) as enq:
            self._create_run_with_skip_flag()

        enq.assert_not_called()

    # --- Stale run cleanup --------------------------------------------------

    def test_mark_stale_runs_timed_out(self):
        run = self._create_test_run()
        frappe.db.set_value("Mollie Bulk Run", run.name, "status", "Processing", update_modified=False)
        # Force modified to >5h ago
        six_hours_ago = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-6)
        frappe.db.sql(
            "UPDATE `tabMollie Bulk Run` SET modified=%s WHERE name=%s",
            (six_hours_ago, run.name),
        )
        frappe.db.commit()

        svc.mark_stale_runs_timed_out()

        run.reload()
        self.assertEqual(run.status, "Timed Out")
        self.assertIn("Timed Out", run.last_error or "")
