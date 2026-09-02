"""clear_stuck_jobs / get_queue_status must actually work against the installed RQ.

Both functions were written for RQ 1.x:

* `from rq import Connection` -- `Connection` was removed in RQ 2.0. The import is
  inside the function's own `try`, so it fails before anything else runs and both
  functions always report an error (#685).
* `queue.started_job_registry.get_job_class()` -- registries never had a
  `get_job_class()` method; `job_class` is a plain attribute. Calling it raises
  `AttributeError`, caught by the per-job handler and logged invisibly
  (`frappe.logger()`), so a fixed import alone still reports "no stuck jobs found"
  for a real one.
* Constructing `Job(job_id, connection=...)` directly (RQ's bare constructor) never
  loads data from Redis -- only `Job.fetch()` / `.refresh()` do. So even past the
  previous two defects, `job.started_at` is always `None` and the stuck check never
  fires.
* `datetime.now() - job.started_at` -- RQ's `started_at` is timezone-aware UTC
  (`rq.utils.now()`/`utcparse()`). Subtracting a naive `datetime.now()` from it
  raises `TypeError`. This is the deliberately-UTC RQ clock, not the site's
  Asia/Kolkata clock -- the fix is `datetime.now(timezone.utc)`, not
  `frappe.utils.now_datetime()` (see #637/#668/#686 for that different class).
* `queue.started_job_registry.remove(job_id)` -- RQ 2.x moved "started" bookkeeping
  to an Execution model; `StartedJobRegistry.add()`/`.remove()` are now stubs that
  unconditionally `raise NotImplementedError()`. The replacement is
  `remove_executions(job)`.

These tests exercise the real Redis queue used by this bench (no mocking of RQ or
Redis) end to end: they plant a job/Execution pair directly in Redis -- exactly the
state `Worker.perform_job` leaves behind (`rq/worker.py`: `prepare_job_execution` ->
`Execution.create`) -- with an old `started_at`, then call the whitelisted functions
exactly as the admin UI and the daily scheduler task do.

Planting goes through `Job.create()` + `.save()`, never `queue.enqueue_call()`: this
bench runs real RQ workers (via `bench start`), and pushing onto the live "long"
queue would race a real worker for the job, which could execute or reap it before
the test gets to it. `Job.create()` only builds Redis hash/registry state and never
touches the queue's wait-list, so nothing but this test ever sees these job ids.
"""

import uuid
from datetime import datetime, timedelta, timezone

import frappe
import redis
from frappe.tests.utils import FrappeTestCase
from rq import Queue
from rq.executions import Execution
from rq.job import Job

from verenigingen.utils.bulk_queue_config import clear_stuck_jobs, get_bulk_queue_config, get_queue_status


def _redis_conn():
    return redis.from_url(frappe.conf.redis_queue or "redis://localhost:11000")


def _plant_job(redis_conn, queue_name, started_minutes_ago):
    """Write a real RQ job + Execution directly into Redis, `started_minutes_ago`
    minutes in the past, without ever enqueuing it for a real worker to pick up."""
    job = Job.create(
        func="time.sleep",
        args=(0,),
        connection=redis_conn,
        origin=queue_name,
        id=f"test-685-{uuid.uuid4().hex}",
    )
    job.started_at = datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)
    job._status = "started"
    job.save()

    with redis_conn.pipeline() as pipeline:
        execution = Execution.create(job, ttl=3600, pipeline=pipeline)
        pipeline.execute()

    return job, execution


def _remove_job(redis_conn, queue_name, job, execution):
    """Undo `_plant_job` precisely. `remove_executions` reads `job.get_executions()`
    from Redis, so it must run before the job/execution hashes are deleted --
    otherwise the `rq:wip:<queue>` sorted-set entry is orphaned forever (it has no
    TTL shorter than the heartbeat ttl passed to `Execution.create`)."""
    queue = Queue(queue_name, connection=redis_conn)
    queue.started_job_registry.remove_executions(job)
    redis_conn.delete(job.key)
    redis_conn.delete(execution.key)
    redis_conn.delete(f"rq:executions:{job.id}")


class TestBulkQueueConfigRQCompat(FrappeTestCase):
    """RQ-version-compatibility tests for verenigingen.utils.bulk_queue_config.

    Run as Administrator: both functions gate on frappe.has_permission against
    System Settings, which Administrator always has.
    """

    def setUp(self):
        self._user = frappe.session.user
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user(self._user)

    def test_get_queue_status_does_not_hit_the_removed_rq_connection_import(self):
        """`from rq import Connection` used to blow up before any queue was
        inspected, so the whitelisted call always returned a top-level
        {"error": "cannot import name 'Connection' ..."}. After the fix it must
        actually report real per-queue data."""
        result = get_queue_status()

        self.assertNotIn("error", result, f"get_queue_status() failed outright: {result}")
        self.assertIn("long", result)
        self.assertNotIn("error", result["long"], f"'long' queue status failed: {result['long']}")
        self.assertIn("length", result["long"])

    def test_clear_stuck_jobs_clears_a_job_older_than_the_threshold(self):
        """End-to-end: a job started well past `stuck_job_timeout_minutes` ago
        must actually be detected and removed from the started registry -- not
        silently swallowed by an AttributeError/TypeError and reported as
        'no stuck jobs found'."""
        redis_conn = _redis_conn()
        threshold_minutes = get_bulk_queue_config()["stuck_job_timeout_minutes"]
        job, execution = _plant_job(redis_conn, "long", threshold_minutes + 30)

        try:
            queue = Queue("long", connection=redis_conn)
            self.assertIn(
                job.id,
                queue.started_job_registry.get_job_ids(),
                "planted job did not land in the started registry -- test setup is wrong",
            )

            result = clear_stuck_jobs()

            self.assertTrue(result.get("success"), f"clear_stuck_jobs() reported failure: {result}")
            cleared_ids = [j["job_id"] for j in result["cleared_jobs"]]
            self.assertIn(
                job.id,
                cleared_ids,
                f"stuck job {job.id} was not cleared; cleared_jobs={result['cleared_jobs']}",
            )

            cleared_entry = next(j for j in result["cleared_jobs"] if j["job_id"] == job.id)
            self.assertGreaterEqual(cleared_entry["duration_minutes"], threshold_minutes)

            queue = Queue("long", connection=redis_conn)
            self.assertNotIn(
                job.id,
                queue.started_job_registry.get_job_ids(),
                "stuck job is still in the started registry after clear_stuck_jobs()",
            )
        finally:
            _remove_job(redis_conn, "long", job, execution)

    def test_clear_stuck_jobs_leaves_a_fresh_job_alone(self):
        """A job started moments ago must NOT be cleared -- guards against a
        fix that clears every started job regardless of age."""
        redis_conn = _redis_conn()
        job, execution = _plant_job(redis_conn, "long", started_minutes_ago=0)

        try:
            result = clear_stuck_jobs()
            self.assertTrue(result.get("success"), f"clear_stuck_jobs() reported failure: {result}")
            cleared_ids = [j["job_id"] for j in result["cleared_jobs"]]
            self.assertNotIn(job.id, cleared_ids, "a freshly started job was incorrectly cleared")

            queue = Queue("long", connection=redis_conn)
            self.assertIn(
                job.id,
                queue.started_job_registry.get_job_ids(),
                "fresh job was removed from the started registry",
            )
        finally:
            _remove_job(redis_conn, "long", job, execution)
