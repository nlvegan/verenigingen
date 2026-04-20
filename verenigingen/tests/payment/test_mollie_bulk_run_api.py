"""Tests for the Mollie Bulk Run whitelisted API endpoints.

Complements test_mollie_bulk_run.py which covers the execution engine.
These tests verify the input validation, access gating, and state
transitions exposed to the page frontend.
"""

from unittest.mock import patch

import frappe

from verenigingen.api import mollie_bulk_run_api as _api_module


# Bypass the @high_security_api decorator (which depends on audit hooks that
# aren't wired up in the test context) by calling the raw underlying function.
# __wrapped__ is set by functools.wraps in the decorator chain.
class _RawAPI:
    def __getattr__(self, name):
        fn = getattr(_api_module, name)
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn


api = _RawAPI()
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieBulkRunAPI(EnhancedTestCase):
    """Verify the whitelisted endpoints construct runs, gate access,
    and surface state consistently."""

    def _create_test_run(self, status="Queued", **overrides):
        run = frappe.get_doc(
            {
                "doctype": "Mollie Bulk Run",
                "date_from": "2021-01-01",
                "date_to": "2021-03-31",
                "batch_strategy": "Month",
                "status": status,
                "triggered_by": frappe.session.user,
                **overrides,
            }
        )
        run.insert(ignore_permissions=True)
        return run

    # --- start_bulk_run ----------------------------------------------------

    def test_start_bulk_run_creates_queued_run_and_enqueues(self):
        with patch.object(_api_module, "enqueue_run", return_value="job-123") as enq:
            result = api.start_bulk_run(
                date_from="2021-01-01",
                date_to="2021-12-31",
                batch_strategy="Month",
            )

        self.assertIn("run_name", result)
        self.assertEqual(result["job_id"], "job-123")
        enq.assert_called_once_with(result["run_name"])

        run = frappe.get_doc("Mollie Bulk Run", result["run_name"])
        self.assertEqual(run.status, "Queued")
        self.assertEqual(str(run.date_from), "2021-01-01")
        self.assertEqual(str(run.date_to), "2021-12-31")
        self.assertEqual(run.batch_strategy, "Month")
        self.assertEqual(run.triggered_by, frappe.session.user)

    def test_start_bulk_run_rejects_reversed_dates(self):
        with patch.object(_api_module, "enqueue_run"):
            with self.assertRaises(frappe.ValidationError):
                api.start_bulk_run(
                    date_from="2022-01-01",
                    date_to="2021-01-01",
                    batch_strategy="Month",
                )

    def test_start_bulk_run_rejects_invalid_strategy(self):
        with patch.object(_api_module, "enqueue_run"):
            with self.assertRaises(frappe.ValidationError):
                api.start_bulk_run(
                    date_from="2021-01-01",
                    date_to="2021-12-31",
                    batch_strategy="Quarter",
                )

    def test_start_bulk_run_denied_for_user_without_access(self):
        with patch.object(_api_module, "enqueue_run"), patch(
            "verenigingen.templates.pages.mollie_payment_processing.has_payment_processing_access",
            return_value=False,
        ):
            with self.assertRaises(frappe.PermissionError):
                api.start_bulk_run(
                    date_from="2021-01-01",
                    date_to="2021-12-31",
                    batch_strategy="Month",
                )

    # --- get_bulk_run_status ----------------------------------------------

    def test_get_status_returns_counters_and_percentage(self):
        run = self._create_test_run()
        frappe.db.set_value(
            "Mollie Bulk Run",
            run.name,
            {
                "total_payments": 100,
                "last_processed_index": 25,
                "total_succeeded": 20,
                "total_skipped": 3,
                "total_failed": 2,
            },
            update_modified=False,
        )

        status = api.get_bulk_run_status(run.name)

        self.assertEqual(status["name"], run.name)
        self.assertEqual(status["total_payments"], 100)
        self.assertEqual(status["last_processed_index"], 25)
        self.assertEqual(status["total_succeeded"], 20)
        self.assertEqual(status["percentage"], 25)

    def test_get_status_percentage_zero_when_no_payments(self):
        run = self._create_test_run()
        status = api.get_bulk_run_status(run.name)
        self.assertEqual(status["percentage"], 0)

    def test_get_status_raises_for_unknown_run(self):
        with self.assertRaises(frappe.DoesNotExistError):
            api.get_bulk_run_status("MBR-DOES-NOT-EXIST-999")

    # --- request_cancel ---------------------------------------------------

    def test_request_cancel_sets_flag_on_active_run(self):
        run = self._create_test_run(status="Processing")
        result = api.request_cancel(run.name)

        self.assertTrue(result["cancel_requested"])
        self.assertEqual(
            frappe.db.get_value("Mollie Bulk Run", run.name, "cancel_requested"), 1
        )

    def test_request_cancel_rejects_terminal_run(self):
        run = self._create_test_run(status="Completed")
        with self.assertRaises(frappe.ValidationError):
            api.request_cancel(run.name)

    # --- resume_bulk_run --------------------------------------------------

    def test_resume_requeues_failed_run(self):
        run = self._create_test_run(status="Failed")
        frappe.db.set_value(
            "Mollie Bulk Run",
            run.name,
            {"cancel_requested": 1, "last_error": "old error"},
            update_modified=False,
        )

        with patch.object(_api_module, "enqueue_run", return_value="job-456") as enq:
            result = api.resume_bulk_run(run.name)

        self.assertEqual(result["job_id"], "job-456")
        enq.assert_called_once_with(run.name)

        fresh = frappe.db.get_value(
            "Mollie Bulk Run",
            run.name,
            ["status", "cancel_requested", "last_error"],
            as_dict=True,
        )
        self.assertEqual(fresh.status, "Queued")
        self.assertEqual(fresh.cancel_requested, 0)
        self.assertIsNone(fresh.last_error)

    def test_resume_requeues_timed_out_and_cancelled_runs(self):
        for status in ("Timed Out", "Cancelled"):
            run = self._create_test_run(status=status)
            with patch.object(_api_module, "enqueue_run", return_value=f"job-{status}"):
                result = api.resume_bulk_run(run.name)
            self.assertEqual(result["run_name"], run.name)

    def test_resume_rejects_active_or_completed_run(self):
        for status in ("Queued", "Fetching", "Processing", "Completed"):
            run = self._create_test_run(status=status)
            with patch.object(_api_module, "enqueue_run"):
                with self.assertRaises(frappe.ValidationError):
                    api.resume_bulk_run(run.name)

    # --- list_recent_bulk_runs --------------------------------------------

    def test_list_recent_runs_returns_ordered_with_flags(self):
        # Create three runs in varying states
        self._create_test_run(status="Completed")
        run_active = self._create_test_run(status="Processing")
        run_resumable = self._create_test_run(status="Failed")

        runs = api.list_recent_bulk_runs(limit=10)
        names = [r["name"] for r in runs]

        # Ordered by creation desc — the last-created run appears first
        self.assertEqual(names[0], run_resumable.name)

        by_name = {r["name"]: r for r in runs}
        self.assertTrue(by_name[run_active.name]["active"])
        self.assertFalse(by_name[run_active.name]["resumable"])
        self.assertTrue(by_name[run_resumable.name]["resumable"])
        self.assertFalse(by_name[run_resumable.name]["active"])

    def test_list_recent_runs_limits_result_count(self):
        """limit caps how many rows come back (tested with real data, no DB mocking)."""
        # Create 3 test runs
        for _ in range(3):
            self._create_test_run()

        # limit=1 returns at most 1
        self.assertLessEqual(len(api.list_recent_bulk_runs(limit=1)), 1)
        # limit greater than available returns all 3+ we created
        self.assertGreaterEqual(len(api.list_recent_bulk_runs(limit=50)), 3)

    def test_list_recent_runs_rejects_negative_limit_via_clamp(self):
        """Negative limit gets clamped to 1 (not zero; not an error)."""
        self._create_test_run()
        self._create_test_run()
        # Negative → clamped to 1 → at most 1 row
        self.assertLessEqual(len(api.list_recent_bulk_runs(limit=-5)), 1)
