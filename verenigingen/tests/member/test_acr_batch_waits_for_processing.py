"""
process_bulk_account_creation_batch paces its batch chain by counting the batch's
still-open Account Creation Requests (Requested / Queued / Processing) before it
enqueues the next batch.

#1744: the filter named "In Progress", a status the doctype does not have, so a request
in Processing was not counted and the next batch was queued at once.

#1788: the count ran on the main connection, inside one REPEATABLE READ snapshot that was
opened long before the wait started. Workers commit on their OWN connections, so the loop
never saw them finish and always waited the full 600 s. The first version of this test
flipped the status on the SAME connection, which a snapshot does see, so it could not show
that. Every scenario here commits the status change on a DIFFERENT connection.

Probe shortcut, stated: the Account Creation Request is a minimal row INSERTed and committed
on a second connection (not built through the real insert flow), because only a committed
row is visible to a worker or to the wait loop's fresh read. The worker pipeline
(``AccountCreationManager``) is a stand-in: it either completes the request on the worker's
own connection or leaves it Processing, as a worker that died mid-pipeline would. The batch
function, its worker threads and commit, the wait loop and the tracker are real, except
``frappe.enqueue`` (recorded, not run) and ``time.sleep`` (a tick counter; no real wait).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase

WAIT_TICK = 3  # the wait loop's sleep; the worker's own throttle sleeps 0.5
FULL_TIMEOUT_TICKS = 600 // WAIT_TICK


def _on_other_connection(sql, params=()):
    """Run and COMMIT one statement on a new connection, independent of the test transaction."""
    connection = frappe.db.create_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


class _WorkerThatLeavesRequestProcessing:
    """Stand-in pipeline: a worker that died mid-pipeline, request still Processing."""

    cancelled = False

    def __init__(self, request_name):
        self.request_name = request_name

    def process_complete_pipeline(self):
        return None


class _WorkerThatCompletesRequest(_WorkerThatLeavesRequestProcessing):
    """Stand-in pipeline: sets Completed and COMMITS it on a connection of its own.

    The real worker commits too, but skips it under ``frappe.flags.in_test``, so the commit is
    made here explicitly rather than inherited.
    """

    def process_complete_pipeline(self):
        _on_other_connection(
            "UPDATE `tabAccount Creation Request` SET status = 'Completed' WHERE name = %s",
            (self.request_name,),
        )


class TestBatchWaitSeesCommitsFromOtherConnections(VereningingenTestCase):
    def setUp(self):
        # Production order: the requests are committed BEFORE the batch job starts, and the
        # job's snapshot opens after. End any snapshot left by the previous test, commit the
        # row on the other connection, and only then let this connection read anything --
        # otherwise the row would simply be invisible to the main connection from the start.
        frappe.db.rollback()
        self.request_name = f"ACR-T1788-{frappe.generate_hash(length=8)}"
        self._create_committed_processing_request(self.request_name)
        self.addCleanup(self._cleanup_committed_request, self.request_name)
        super().setUp()
        from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
            BulkOperationTracker,
        )

        self.tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=1, batch_size=50, priority="Normal"
        )
        self.track_doc("Bulk Operation Tracker", self.tracker.name)

    # -- a second, independent connection: it commits for real and sees only committed data
    def _create_committed_processing_request(self, name):
        _on_other_connection(
            "INSERT INTO `tabAccount Creation Request` (name, creation, modified, modified_by, owner, "
            "docstatus, idx, request_type, source_record, email, full_name, status) "
            "VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', 0, 0, 'Member', %s, %s, %s, "
            "'Processing')",
            (name, "T1788-no-such-member", f"{name.lower()}@test.invalid", "Acr1788 Probe"),
        )

    def _cleanup_committed_request(self, name):
        _on_other_connection("DELETE FROM `tabAccount Creation Request` WHERE name = %s", (name,))

    @staticmethod
    def _committed_status(name):
        connection = frappe.db.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT status FROM `tabAccount Creation Request` WHERE name = %s", (name,))
            return cursor.fetchone()[0]
        finally:
            connection.close()

    def _run_batch(self, worker_cls, on_tick=None):
        ticks = []
        enqueued = []

        def fake_sleep(seconds):
            if seconds == WAIT_TICK:
                ticks.append(seconds)
                if on_tick:
                    on_tick(len(ticks))

        def fake_enqueue(method, **kwargs):
            enqueued.append((kwargs.get("batch_id"), len(ticks), self._committed_status(self.request_name)))

        remaining = [{"batch_id": "b2", "batch_number": 2, "request_names": ["x"], "request_count": 1}]
        with (
            patch("time.sleep", fake_sleep),
            patch.object(frappe, "enqueue", fake_enqueue),
            patch.object(api, "AccountCreationManager", worker_cls),
        ):
            api.process_bulk_account_creation_batch(
                request_names=[self.request_name],
                batch_id="b1",
                batch_number=1,
                tracker_name=self.tracker.name,
                remaining_batches=remaining,
            )
        return ticks, enqueued

    def test_completion_committed_by_the_worker_is_seen_without_waiting(self):
        """The worker finishes and commits on its own connection before the wait starts."""
        ticks, enqueued = self._run_batch(_WorkerThatCompletesRequest)

        self.assertEqual(self._committed_status(self.request_name), "Completed", "precondition")
        self.assertEqual(len(ticks), 0, "the loop kept reading a stale snapshot and waited")
        self.assertEqual(enqueued, [("b2", 0, "Completed")])

    def test_completion_committed_mid_wait_ends_the_wait(self):
        """The request is genuinely Processing, so the loop must wait, then see the commit."""
        flip_on_tick = 2

        def other_connection_completes(tick_number):
            if tick_number == flip_on_tick:
                _on_other_connection(
                    "UPDATE `tabAccount Creation Request` SET status = 'Completed' WHERE name = %s",
                    (self.request_name,),
                )

        ticks, enqueued = self._run_batch(_WorkerThatLeavesRequestProcessing, other_connection_completes)

        # Exactly flip_on_tick sleeps: it waited while Processing (#1744) and stopped once the
        # other connection committed (#1788). 0 would mean Processing was not counted; the full
        # timeout would mean the commit was never seen.
        self.assertEqual(len(ticks), flip_on_tick)
        self.assertEqual(enqueued, [("b2", flip_on_tick, "Completed")])

    def test_a_batch_that_never_finishes_still_times_out_and_queues_next(self):
        ticks, enqueued = self._run_batch(_WorkerThatLeavesRequestProcessing)

        self.assertEqual(len(ticks), FULL_TIMEOUT_TICKS)
        self.assertEqual(enqueued, [("b2", FULL_TIMEOUT_TICKS, "Processing")])
