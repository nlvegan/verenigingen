"""#3186: a dedupe enqueue race on one member must not skip the members after it.

``enqueue_payment_history_drain_for_customers`` fans out one deduplicated drain job per
Member. A rq ``InvalidJobOperation`` raised from the dedupe ``Job.delete`` used to escape the
loop, so every later member's job was never queued (the hook handlers swallow the exception
with one generic log line, so the save survived but the fan-out did not). The race is injected
at the rq boundary (``get_job``); members, hooks and the enqueue call are real.
"""

from unittest.mock import patch

import frappe
from rq.exceptions import InvalidJobOperation

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import background_jobs

ERROR_TITLE = "Event dedupe enqueue race (InvalidJobOperation)"


class _FinishedJobVanishing3186:
    id = "raced"

    def get_status(self, refresh=False):
        return "finished"

    def delete(self, *args, **kwargs):
        raise InvalidJobOperation("Failed to retrieve status for job")


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

    def _error_titles(self):
        return [
            r.method
            for r in frappe.get_all(
                "Error Log", filters={"creation": [">=", self._cutoff]}, fields=["method"], limit=0
            )
        ]

    def _run_fan_out_with_race(self, raced_attempts):
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
                return _FinishedJobVanishing3186()
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
        accepted, raced_job = self._run_fan_out_with_race(raced_attempts=2)
        later_job = f"fin_history_payment_{self.later_member.name}"
        self.assertIn(later_job, accepted, "the member after the raced one was never queued")
        self.assertNotIn(raced_job, accepted, "both attempts raced, so that job cannot have been queued")
        titles = self._error_titles()
        self.assertEqual(titles.count(ERROR_TITLE), 2, "first attempt and failed retry are both logged")

    def test_a_single_race_is_retried_and_the_raced_member_is_still_queued(self):
        accepted, raced_job = self._run_fan_out_with_race(raced_attempts=1)
        self.assertIn(raced_job, accepted)
        self.assertIn(f"fin_history_payment_{self.later_member.name}", accepted)
        self.assertEqual(self._error_titles().count(ERROR_TITLE), 1)
