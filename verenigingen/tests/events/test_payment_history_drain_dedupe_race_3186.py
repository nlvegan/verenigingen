"""#3186: a dedupe enqueue race on one member must not skip the members after it.

``enqueue_payment_history_drain_for_customers`` fans out one deduplicated drain job per
Member. A rq ``InvalidJobOperation`` raised from the dedupe ``Job.delete`` used to escape the
loop, so every later member's job was never queued (the hook handlers swallow the exception
with one generic log line, so the save survived but the fan-out did not). The race is injected
at the rq boundary (``get_job``); members, hooks and the enqueue call are real.
"""

from unittest.mock import patch

import frappe
from frappe.exceptions import QueryDeadlockError
from rq.exceptions import InvalidJobOperation

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.events import test_event_dedupe_enqueue_race_2505 as race_2505
from verenigingen.utils import background_jobs

ERROR_TITLE = "Event dedupe enqueue race (InvalidJobOperation)"
NOT_QUEUED_TITLE = "Payment history drain NOT queued"


class _FinishedJobVanishing3186:
    id = "raced"

    def __init__(self, exc=None):
        self._exc = exc or InvalidJobOperation("Failed to retrieve status for job")

    def get_status(self, refresh=False):
        return "finished"

    def delete(self, *args, **kwargs):
        raise self._exc


class TestPaymentHistoryDrainDedupeRace3186(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.raced_member = self.create_test_member(
            first_name="Raced", last_name="First", email="raced.first.3186@test.invalid"
        )
        self.later_member = self.create_test_member(
            first_name="Later", last_name="Second", email="later.second.3186@test.invalid"
        )
        self.assertNotEqual(self.raced_member.customer, self.later_member.customer)
        self._cutoff = frappe.utils.now_datetime()

    def _drain_race_error_titles_3186(self):
        # Shared with the #2505 test rather than copied (a third copy reddens the clone-family gate).
        return race_2505.TestEventDedupeEnqueueRace2505._error_titles(self)

    def _run_fan_out_with_race(self, raced_attempts, exc=None):
        """Fan-out over both customers, raced member first; the raced member's dedupe hits the race ``raced_attempts`` times."""
        accepted, fired = [], []
        real_enqueue = frappe.enqueue
        real_get_job = frappe.utils.background_jobs.get_job
        raced_job = f"fin_history_payment_{self.raced_member.name}"

        def recording_enqueue(*args, **kwargs):
            result = real_enqueue(*args, **kwargs)
            accepted.append(kwargs.get("job_id"))
            return result

        def get_job(job_id):
            if job_id == raced_job and len(fired) < raced_attempts:
                fired.append(job_id)
                return _FinishedJobVanishing3186(exc)
            return real_get_job(job_id)

        # Mock justified: the race is a concurrent actor deleting the job hash; it cannot be
        # produced on demand, so the rq boundary (get_job/delete) is made to behave as it does mid-race.
        with patch("frappe.utils.background_jobs.get_job", get_job), patch(
            "frappe.enqueue", recording_enqueue
        ):
            # A list, not the hook's set: the raced member must come FIRST for the loop abort to show.
            background_jobs.enqueue_payment_history_drain_for_customers(
                [self.raced_member.customer, self.later_member.customer]
            )
        return accepted, raced_job

    def test_a_race_on_one_member_does_not_skip_the_next_member(self):
        self.expectErrorLog(ERROR_TITLE)
        self.expectErrorLog(NOT_QUEUED_TITLE)
        accepted, raced_job = self._run_fan_out_with_race(raced_attempts=2)
        later_job = f"fin_history_payment_{self.later_member.name}"
        self.assertIn(later_job, accepted, "the member after the raced one was never queued")
        self.assertNotIn(raced_job, accepted, "both attempts raced, so that job cannot have been queued")
        titles = self._drain_race_error_titles_3186()
        self.assertEqual(titles.count(ERROR_TITLE), 2, "first attempt and failed retry are both logged")
        self.assertEqual(titles.count(NOT_QUEUED_TITLE), 1, "the lost drain must be logged distinctly")
        not_queued = frappe.get_all(
            "Error Log",
            filters={"method": NOT_QUEUED_TITLE, "creation": [">=", self._cutoff]},
            fields=["error"],
        )
        self.assertIn(self.raced_member.name, not_queued[0].error)
        self.assertIn(self.raced_member.customer, not_queued[0].error)
        self.assertNotIn(self.later_member.name, not_queued[0].error)

    def test_control_a_deadlock_is_not_swallowed_as_a_race(self):
        with self.assertRaises(QueryDeadlockError):
            self._run_fan_out_with_race(raced_attempts=2, exc=QueryDeadlockError())
        self.assertNotIn(NOT_QUEUED_TITLE, self._drain_race_error_titles_3186())

    def test_a_single_race_is_retried_and_the_raced_member_is_still_queued(self):
        self.expectErrorLog(ERROR_TITLE)
        accepted, raced_job = self._run_fan_out_with_race(raced_attempts=1)
        self.assertIn(raced_job, accepted)
        self.assertIn(f"fin_history_payment_{self.later_member.name}", accepted)
        titles = self._drain_race_error_titles_3186()
        self.assertEqual(titles.count(ERROR_TITLE), 1)
        self.assertNotIn(NOT_QUEUED_TITLE, titles)
