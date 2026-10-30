"""A Cancelled Account Creation Request must stay cancelled (#1709, #1710).

Every writer of ``status`` on the request is driven through its real code path.
The Member source record is a real fixture; the only patched thing is
``frappe.enqueue``, the queue boundary (CI has no RQ workers).
"""

import threading
import time
from unittest.mock import patch

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.account_creation_request import account_creation_request as acr_module
from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
    BulkOperationTracker,
)


class TestAccountCreationRequestCancel(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.uid = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="AcrCancel",
            last_name=f"Member{self.uid}",
            email=f"acrcancel.member.{self.uid}@test.invalid",
            status="Active",
        )

    def _make_request_for_cancel(self):
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": self.member.name,
                "email": self.member.email,
                "full_name": self.member.full_name,
                "priority": "Normal",
                "role_profile": "Verenigingen Member",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Member"}],
            }
        )
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        return request

    def _request_status(self, name):
        return frappe.db.get_value("Account Creation Request", name, "status")

    def _keep_member_user(self):
        if frappe.db.exists("User", self.member.email):
            self.track_doc("User", self.member.email)

    def _cancelled(self, reason="not wanted"):
        request = self._make_request_for_cancel()
        request.cancel_request(reason=reason)
        self.assertEqual(self._request_status(request.name), "Cancelled")
        return frappe.get_doc("Account Creation Request", request.name)

    # --- #1709: the pipeline entry -------------------------------------------------

    def test_control_uncancelled_request_still_creates_the_user(self):
        request = self._make_request_for_cancel()
        api.process_account_creation_request(request.name)
        self._keep_member_user()
        self.assertEqual(self._request_status(request.name), "Completed")
        self.assertTrue(frappe.db.exists("User", self.member.email))

    def test_cancelled_request_creates_no_user_and_stays_cancelled(self):
        request = self._cancelled()
        result = api.process_account_creation_request(request.name)
        self._keep_member_user()
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(frappe.db.exists("User", self.member.email))
        self.assertEqual(self._request_status(request.name), "Cancelled")

    def test_cancelled_request_with_an_existing_user_links_nothing(self):
        """Resumed request (user exists, stages done): no mark_processing runs, so only the
        entry check keeps the link phase from writing Member.user."""
        request = self._make_request_for_cancel()
        user = frappe.get_doc(
            {"doctype": "User", "email": self.member.email, "first_name": "Pre", "send_welcome_email": 0}
        ).insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"created_user": user.name, "pipeline_stage": "Completed"},
        )
        frappe.get_doc("Account Creation Request", request.name).cancel_request(reason="stop")
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "user"))
        api.process_account_creation_request(request.name)
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "user"))
        self.assertEqual(self._request_status(request.name), "Cancelled")

    # --- #1709: every status writer -------------------------------------------------

    def test_mark_processing_refuses_a_cancelled_request(self):
        request = self._cancelled()
        with self.assertRaises(frappe.ValidationError):
            request.mark_processing("User Creation")
        self.assertEqual(self._request_status(request.name), "Cancelled")

    def test_mark_failed_does_not_overwrite_cancelled(self):
        request = self._cancelled(reason="operator said stop")
        request.mark_failed("late pipeline error", "Role Assignment")
        self.assertEqual(self._request_status(request.name), "Cancelled")
        self.assertNotIn(
            "late pipeline error", frappe.db.get_value("Account Creation Request", request.name, "failure_reason") or ""
        )

    def test_mark_completed_does_not_overwrite_cancelled_but_records_what_was_made(self):
        request = self._cancelled()
        request.mark_completed(user="Administrator")
        self.assertEqual(self._request_status(request.name), "Cancelled")
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "created_user"), "Administrator"
        )

    def test_schedule_retry_does_not_reset_cancelled_or_enqueue(self):
        request = self._cancelled()
        manager = AccountCreationManager(request.name)
        manager.load_request()
        # Mock justified: queue boundary, CI has no RQ workers
        with patch("frappe.enqueue") as enqueue:
            manager.schedule_retry()
        self.assertEqual(self._request_status(request.name), "Cancelled")
        enqueue.assert_not_called()

    def test_retry_and_queue_endpoints_refuse_cancelled(self):
        request = self._cancelled()
        with self.assertRaises(frappe.ValidationError):
            request.retry_processing()
        with self.assertRaises(frappe.ValidationError):
            request.queue_processing()
        self.assertEqual(self._request_status(request.name), "Cancelled")

    def test_cancel_between_stages_stops_the_pipeline(self):
        """A cancel landing after User Creation stops it at the next stage.

        The cancel is issued from inside the real ``create_user_account`` wrapper,
        i.e. after the user exists and before roles are assigned.
        """
        request = self._make_request_for_cancel()
        real_create = AccountCreationManager.create_user_account

        def create_then_cancel(manager):
            real_create(manager)
            frappe.get_doc("Account Creation Request", request.name).cancel_request(reason="mid-flight")

        # No expectErrorLog: a cancel is not an error and must not write an Error Log row.
        errors_before = frappe.db.count("Error Log")
        with patch.object(AccountCreationManager, "create_user_account", create_then_cancel):
            api.process_account_creation_request(request.name)
        self._keep_member_user()
        row = frappe.db.get_value(
            "Account Creation Request",
            request.name,
            ["status", "completed_at", "pipeline_stage", "created_user"],
            as_dict=True,
        )
        self.assertEqual(row.status, "Cancelled")
        self.assertIsNone(row.completed_at)
        self.assertNotEqual(row.pipeline_stage, "Completed")
        # the user that WAS created before the cancel is recorded on the request (F2)
        self.assertEqual(row.created_user, self.member.email)
        # stopped at the Role Assignment check: the role was never granted and nothing was linked
        self.assertNotIn("Verenigingen Member", frappe.get_roles(self.member.email))
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "user"))
        self.assertEqual(frappe.db.count("Error Log"), errors_before)

    # --- cancel_request itself -------------------------------------------------------

    def test_cancel_uses_the_db_status_not_a_stale_copy(self):
        request = self._make_request_for_cancel()
        stale = frappe.get_doc("Account Creation Request", request.name)
        request.mark_completed()
        with self.assertRaises(frappe.ValidationError):
            stale.cancel_request(reason="too late")
        self.assertEqual(self._request_status(request.name), "Completed")

    # --- #1710: the original failure reason survives a cancel ------------------------

    def test_cancelling_a_failed_request_keeps_the_original_error(self):
        request = self._make_request_for_cancel()
        request.mark_failed("SMTP exploded at stage 2", "Role Assignment")
        frappe.get_doc("Account Creation Request", request.name).cancel_request(reason="duplicate of ACR-x")
        row = frappe.db.get_value(
            "Account Creation Request", request.name, ["status", "failure_reason"], as_dict=True
        )
        self.assertEqual(row.status, "Cancelled")
        self.assertIn("SMTP exploded at stage 2", row.failure_reason)
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Account Creation Request", "reference_name": request.name},
            pluck="content",
        )
        self.assertTrue(any("duplicate of ACR-x" in (c or "") for c in comments), comments)

    def test_cancel_reason_is_kept_when_there_was_no_error(self):
        request = self._make_request_for_cancel()
        request.cancel_request(reason="changed my mind")
        self.assertIn(
            "changed my mind", frappe.db.get_value("Account Creation Request", request.name, "failure_reason")
        )

    # --- the dashboard's server paths (#1710 F1) -------------------------------------

    def test_dashboard_cancel_keeps_the_original_error(self):
        request = self._make_request_for_cancel()
        request.mark_failed("SMTP exploded at stage 2", "Role Assignment")
        acr_module.cancel_account_creation_request(request.name, "dashboard cancel")
        row = frappe.db.get_value(
            "Account Creation Request", request.name, ["status", "failure_reason"], as_dict=True
        )
        self.assertEqual(row.status, "Cancelled")
        self.assertIn("SMTP exploded at stage 2", row.failure_reason)

    def test_dashboard_queue_enqueues_and_refuses_a_cancelled_request(self):
        pending = self._make_request_for_cancel()
        # Mock justified: queue boundary, CI has no RQ workers
        with patch("frappe.enqueue") as enqueue:
            acr_module.queue_account_creation_request(pending.name)
        enqueue.assert_called_once()
        self.assertEqual(self._request_status(pending.name), "Queued")

        cancelled = self._cancelled()
        with patch("frappe.enqueue") as enqueue:
            with self.assertRaises(frappe.ValidationError):
                acr_module.queue_account_creation_request(cancelled.name)
        enqueue.assert_not_called()
        self.assertEqual(self._request_status(cancelled.name), "Cancelled")

    def test_a_save_cannot_revive_a_cancelled_request(self):
        """frappe.client.set_value (what the dashboard used to call) goes through save()."""
        request = self._cancelled()
        with self.assertRaises(frappe.ValidationError):
            frappe.client.set_value("Account Creation Request", request.name, "status", "Queued")
        self.assertEqual(self._request_status(request.name), "Cancelled")

    # --- F3: two real connections -----------------------------------------------------

    def _create_rows_visible_to_other_connections(self):
        """Commit the fixtures so another connection (a worker thread) can see them.

        Load-bearing: the rows are tracked, so EnhancedTestCase's drain deletes them again.
        """
        frappe.db.commit()

    def _create_worker_thread(self, fn):
        site = frappe.local.site
        box = {}

        def run():
            try:
                frappe.connect(site=site)
                frappe.flags.in_test = True
                box["result"] = fn()
                frappe.db.commit()
            except Exception as e:
                box["error"] = e
            finally:
                frappe.destroy()

        thread = threading.Thread(target=run)
        thread.start()
        return thread, box

    def test_cancel_blocked_on_the_row_lock_survives_a_concurrent_commit(self):
        """The job holds the row lock, the cancel blocks on it, the job commits (changing
        ``modified``) and releases: the cancel must still land, not TimestampMismatchError."""
        request = self._make_request_for_cancel()
        name = request.name
        self._create_rows_visible_to_other_connections()
        locked, release = threading.Event(), threading.Event()

        def job():
            frappe.db.get_value("Account Creation Request", name, "status", for_update=True)
            locked.set()
            release.wait(30)
            frappe.db.set_value(
                "Account Creation Request", name, "pipeline_stage", "User Creation", update_modified=True
            )

        snapshot_taken = threading.Event()

        def canceller():
            doc = frappe.get_doc("Account Creation Request", name)  # REPEATABLE READ snapshot
            snapshot_taken.set()
            doc.cancel_request(reason="while the job runs")
            return doc.status

        job_thread, job_box = self._create_worker_thread(job)
        self.assertTrue(locked.wait(15))
        cancel_thread, cancel_box = self._create_worker_thread(canceller)
        # The snapshot predates the job's commit whether or not the cancel has reached the
        # lock yet, so the assertion below does not depend on timing; the pause only makes the
        # blocked-on-FOR-UPDATE ordering the usual one.
        self.assertTrue(snapshot_taken.wait(15))
        time.sleep(1)
        release.set()
        job_thread.join(30)
        cancel_thread.join(30)

        self.assertNotIn("error", job_box)
        self.assertNotIn("error", cancel_box, cancel_box.get("error"))
        self.assertEqual(cancel_box["result"], "Cancelled")
        frappe.db.rollback()  # leave the main connection's snapshot
        self.assertEqual(self._request_status(name), "Cancelled")

    # --- F4: the bulk batch counts a cancel separately --------------------------------

    def _run_batch(self, request_name):
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=1, batch_size=25
        )
        self.track_doc("Bulk Operation Tracker", tracker.name)
        self._create_rows_visible_to_other_connections()
        result = api.process_bulk_account_creation_batch([request_name], "batch-cancel", 1, tracker.name)
        self._keep_member_user()
        tracker_row = frappe.db.get_value(
            "Bulk Operation Tracker",
            tracker.name,
            ["successful_records", "failed_records", "processed_records"],
            as_dict=True,
        )
        return result["data"], tracker_row

    def test_batch_counts_a_request_cancelled_before_it_ran_as_cancelled(self):
        request = self._cancelled()
        self._create_rows_visible_to_other_connections()
        data, tracker = self._run_batch(request.name)
        self.assertEqual((data["completed"], data["failed"], data["cancelled"]), (0, 0, 1))
        self.assertEqual((tracker.successful_records, tracker.failed_records), (0, 0))
        self.assertEqual(tracker.processed_records, 1)
        self.assertFalse(frappe.db.exists("User", self.member.email))

    def test_batch_counts_a_request_cancelled_mid_batch_as_cancelled(self):
        request = self._make_request_for_cancel()
        self._create_rows_visible_to_other_connections()
        real_create = AccountCreationManager.create_user_account

        def create_then_cancel(manager):
            real_create(manager)
            frappe.get_doc("Account Creation Request", request.name).cancel_request(reason="mid-batch")

        with patch.object(AccountCreationManager, "create_user_account", create_then_cancel):
            data, tracker = self._run_batch(request.name)
        self.assertEqual((data["completed"], data["failed"], data["cancelled"]), (0, 0, 1))
        self.assertEqual((tracker.successful_records, tracker.failed_records), (0, 0))
        self.assertEqual(self._request_status(request.name), "Cancelled")

    # --- F6: a failing lock read must not mask the original error ----------------------

    def test_a_lock_timeout_in_the_guards_does_not_raise_over_the_original_error(self):
        request = self._make_request_for_cancel()
        manager = AccountCreationManager(request.name)
        manager.load_request()
        lock_timeout = frappe.QueryTimeoutError("Lock wait timeout exceeded")
        # Mock justified: injecting a 1205 lock-wait timeout, which cannot be produced on demand
        with patch.object(type(request), "_locked_status", side_effect=lock_timeout):
            self.expectErrorLog("Account Creation Retry Skipped")
            with patch("frappe.enqueue") as enqueue:
                manager.request.mark_failed("original error", "User Creation")  # must not raise
                manager.schedule_retry()  # must not raise, and fails closed: no retry
        enqueue.assert_not_called()
