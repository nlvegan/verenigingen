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
Redis) end to end: they plant a job whose `started_at` is older than the configured
stuck-job threshold, directly in the "long" queue's started-job registry, then call
the whitelisted functions exactly as the admin UI and the daily scheduler task do.
"""

from datetime import datetime, timedelta, timezone

import frappe
import redis
from frappe.tests.utils import FrappeTestCase
from rq import Queue

from verenigingen.utils.bulk_queue_config import clear_stuck_jobs, get_bulk_queue_config, get_queue_status


def _redis_conn():
    return redis.from_url(frappe.conf.redis_queue or "redis://localhost:11000")


def _plant_stuck_job(redis_conn, queue_name, started_minutes_ago):
    """Create a real RQ job, mark it started `started_minutes_ago` minutes back,
    and register a started Execution for it -- mirroring what a worker does in
    `Worker.perform_job` (`rq/worker.py`), so the registry lookups used by
    `clear_stuck_jobs` behave exactly as they would for a real stuck job."""
    queue = Queue(queue_name, connection=redis_conn)
    job = queue.enqueue_call(func="time.sleep", args=(0,))
    job.started_at = datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)
    job._status = "started"
    job.save()

    with redis_conn.pipeline() as pipeline:
        from rq.executions import Execution

        execution = Execution.create(job, ttl=3600, pipeline=pipeline)
        pipeline.execute()

    return job, execution


def _delete_job_and_execution(redis_conn, job, execution):
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
        job, execution = _plant_stuck_job(redis_conn, "long", threshold_minutes + 30)

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
            _delete_job_and_execution(redis_conn, job, execution)

    def test_clear_stuck_jobs_leaves_a_fresh_job_alone(self):
        """A job started moments ago must NOT be cleared -- guards against a
        fix that clears every started job regardless of age."""
        redis_conn = _redis_conn()
        job, execution = _plant_stuck_job(redis_conn, "long", started_minutes_ago=0)

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
            _delete_job_and_execution(redis_conn, job, execution)
