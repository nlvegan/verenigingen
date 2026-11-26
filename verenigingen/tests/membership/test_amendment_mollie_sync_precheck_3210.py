# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""#3210: the Mollie-sync pre-check in Contribution Amendment Request.on_update listed every RQ Job on
the site (``frappe.get_all("RQ Job", ...)``). frappe serialises each listed job with
``job.get_status()``, which raises rq ``InvalidJobOperation`` when a job hash has lost its status
(a worker finishing or expiring a job mid-listing, ANY job on the shared Redis). Nothing caught it, so
the Applied save aborted before the 'Queued' write and the enqueue.

State driven here (real Redis, real save, no worker needed): a job listed in a registry of the
default queue whose hash has no ``status`` field. The enqueue is stubbed at ``frappe.enqueue`` (the
boundary under test is the pre-check, and a real enqueue would reach any RQ worker on the shared
Redis); the stub records the call so "queued exactly once" is asserted, not inferred.

Control: a genuinely STARTED job for this amendment (the invariant the pre-check protects: no second
sync while one is running) must still suppress the enqueue, and must leave mollie_sync_status alone.
"""

import time
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today
from frappe.utils.background_jobs import create_job_id, get_queue, get_redis_conn
from rq.job import Job, JobStatus

from verenigingen.tests.utils.base import VereningingenTestCase

ENQUEUE_TARGET_3210 = "sync_mollie_subscription_on_amendment_applied"


class TestAmendmentMollieSyncPrecheck3210(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Precheck3210",
            last_name="Amendment",
            email=f"precheck3210.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"Precheck3210Type{frappe.generate_hash(length=6)}"
        )
        self.membership = self.create_test_membership(
            member=self.member.name, membership_type=self.membership_type.name
        )
        self.membership.submit()
        self.membership.reload()
        self._seeded_jobs_3210 = []
        self.addCleanup(self._drop_seeded_jobs_3210)

    def _drop_seeded_jobs_3210(self):
        conn = get_redis_conn()
        for job_id in self._seeded_jobs_3210:
            conn.zrem(get_queue("default").started_job_registry.key, job_id)
            conn.delete(Job.key_for(job_id))

    def _approved_amendment_3210(self):
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.membership.name,
                "member": self.member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 23.0,
                "reason": "precheck 3210",
                "effective_date": add_days(today(), 30),
                "status": "Draft",
            }
        )
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        amendment.db_set("status", "Approved")
        amendment.db_set("effective_date", today())
        amendment.reload()
        amendment._force_apply = True
        return amendment

    def _seed_started_job_3210(self, job_id, *, job_name):
        """A real RQ job hash listed in the default queue's StartedJobRegistry."""
        queue_args = {
            "site": frappe.local.site,
            "user": "Administrator",
            "method": "x",
            "event": None,
            "job_name": job_name,
            "is_async": True,
            "kwargs": {},
        }
        job = Job.create(
            "frappe.utils.background_jobs.execute_job",
            kwargs=queue_args,
            id=job_id,
            origin=get_queue("default").name,
            connection=get_redis_conn(),
        )
        job.save()
        job.set_status(JobStatus.STARTED)
        # StartedJobRegistry.add is not implemented in this rq; the registry is a plain zset of id -> expiry.
        registry = get_queue("default").started_job_registry
        get_redis_conn().zadd(registry.key, {job_id: int(time.time()) + 600})
        self._seeded_jobs_3210.append(job_id)
        return job

    def _seed_statusless_job_3210(self):
        """A job any other job producer on the shared Redis left mid-expiry: listed, hash lacks status."""
        job_id = create_job_id(f"other_job_3210_{frappe.generate_hash(length=6)}")
        self._seed_started_job_3210(job_id, job_name="someone_elses_job_3210")
        get_redis_conn().hdel(Job.key_for(job_id), "status")
        return job_id

    def _apply_with_enqueue_spy_3210(self, amendment):
        # Mock justified: Infrastructure - frappe.enqueue would push to the shared Redis queue (CI has
        # no worker, this bench does); the spy records the call so the test asserts what was queued.
        with patch.object(frappe, "enqueue") as spy:
            result = amendment.apply_amendment()
        calls = [c for c in spy.call_args_list if ENQUEUE_TARGET_3210 in str(c.args[:1])]
        return result, calls

    def _sync_status_3210(self, amendment):
        return frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status")

    def test_unreadable_unrelated_job_does_not_abort_the_applied_save(self):
        amendment = self._approved_amendment_3210()
        self._seed_statusless_job_3210()

        result, calls = self._apply_with_enqueue_spy_3210(amendment)

        self.assertEqual(result["status"], "success", result)
        amendment.reload()
        self.assertEqual(amendment.status, "Applied")
        self.assertEqual(self._sync_status_3210(amendment), "Queued")
        self.assertEqual(len(calls), 1, "the Mollie sync must be enqueued exactly once")
        self.assertEqual(calls[0].kwargs["job_id"], f"mollie_sync_{amendment.name}")

    def test_running_sync_job_for_this_amendment_still_suppresses_the_enqueue(self):
        amendment = self._approved_amendment_3210()
        self._seed_started_job_3210(
            create_job_id(f"mollie_sync_{amendment.name}"), job_name=f"mollie_sync_{amendment.name}"
        )
        before = self._sync_status_3210(amendment)

        result, calls = self._apply_with_enqueue_spy_3210(amendment)

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(calls, [], "a sync job already STARTED for this amendment must not be doubled")
        self.assertEqual(self._sync_status_3210(amendment), before)

    def test_running_sync_job_still_suppresses_even_beside_an_unreadable_job(self):
        amendment = self._approved_amendment_3210()
        self._seed_statusless_job_3210()
        self._seed_started_job_3210(
            create_job_id(f"mollie_sync_{amendment.name}"), job_name=f"mollie_sync_{amendment.name}"
        )

        result, calls = self._apply_with_enqueue_spy_3210(amendment)

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(calls, [])

    def test_other_amendments_job_does_not_suppress_this_enqueue(self):
        amendment = self._approved_amendment_3210()
        self._seed_started_job_3210(
            create_job_id("mollie_sync_CAR-OTHER-3210"), job_name="mollie_sync_CAR-OTHER-3210"
        )

        result, calls = self._apply_with_enqueue_spy_3210(amendment)

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(len(calls), 1)
