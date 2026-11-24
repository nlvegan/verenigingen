"""#2505: a deduplicate=True enqueue race must not abort the save that emitted the event.

``frappe.enqueue(deduplicate=True)`` fetches the job and ``delete()``s it when it is not
queued/started; ``Job.delete`` re-reads the status and raises rq's ``InvalidJobOperation``
when a concurrent actor removed the hash in between. The race is injected deterministically
at the rq boundary (the job's ``delete``); the saves and hooks are real.
"""

from unittest.mock import patch

import frappe
from frappe.exceptions import QueryDeadlockError
from rq.exceptions import InvalidJobOperation

from verenigingen.events import delayed_expense_hooks
from verenigingen.tests.utils.base import VereningingenTestCase

ERROR_TITLE = "Event dedupe enqueue race (InvalidJobOperation)"
# member_events logs with the arguments swapped, so the message lands in the title column.
EMISSION_FAILURE_PREFIX = "Failed to emit member_status_changed event"
FIRST_SUBSCRIBER = "handle_status_change_notifications"
SECOND_SUBSCRIBER = "handle_chapter_assignment_updates"


class _FinishedJobWhoseHashVanishes:
    """What ``get_job`` returns mid-race: found, not queued, and ``delete`` finds it gone."""

    def __init__(self, exc):
        self.id = "raced"
        self._exc = exc

    def get_status(self, refresh=False):
        return "finished"

    def delete(self, *args, **kwargs):
        raise self._exc


class TestEventDedupeEnqueueRace2505(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._saved_flags = {
            k: getattr(frappe.flags, k, None)
            for k in ("in_import", "in_bulk_import", "bulk_member_operations", "in_test")
        }
        # The harness flags make events skip or run inline; production has none of them.
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.in_test = False
        self.member = self.create_test_member(
            first_name="Dedupe",
            last_name="Race",
            email=f"dedupe.race.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self._cutoff = frappe.utils.now_datetime()

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _error_titles(self):
        return [
            r.method
            for r in frappe.get_all(
                "Error Log", filters={"creation": [">=", self._cutoff]}, fields=["method"], limit=0
            )
        ]

    @staticmethod
    def _emission_failures(titles):
        return [t for t in titles if t.startswith(EMISSION_FAILURE_PREFIX)]

    def _racing_get_job(self, exc, racing_marker):
        real_get_job = frappe.utils.background_jobs.get_job

        def get_job(job_id):
            if racing_marker in job_id:
                return _FinishedJobWhoseHashVanishes(exc)
            return real_get_job(job_id)

        return get_job

    def _save_application_status_change(self, exc):
        """Real Member save; the FIRST subscriber's dedupe enqueue hits the race."""
        accepted = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            result = real_enqueue(*args, **kwargs)
            accepted.append(str(args[0] if args else kwargs.get("method", "")))
            return result

        member = frappe.get_doc("Member", self.member.name)
        member.application_status = "Approved" if member.application_status != "Approved" else "Rejected"
        # Mock justified: the race is a concurrent actor deleting the job hash; it cannot be
        # produced on demand, so the rq boundary (get_job/delete) is made to behave as it does mid-race.
        with patch(
            "frappe.utils.background_jobs.get_job", self._racing_get_job(exc, FIRST_SUBSCRIBER)
        ), patch("frappe.enqueue", recording_enqueue):
            member.save()
        return accepted

    def test_member_save_survives_the_race_and_still_dispatches_the_other_subscribers(self):
        accepted = self._save_application_status_change(InvalidJobOperation("Failed to retrieve status"))
        titles = self._error_titles()
        self.assertFalse(self._emission_failures(titles), "the race aborted the emission")
        self.assertIn(ERROR_TITLE, titles, "the race was swallowed without a log row")
        self.assertTrue(
            any(SECOND_SUBSCRIBER in m for m in accepted),
            f"the sibling subscriber was never dispatched: {accepted}",
        )

    def test_control_a_deadlock_is_not_swallowed_as_a_race(self):
        accepted = self._save_application_status_change(QueryDeadlockError())
        titles = self._error_titles()
        self.assertNotIn(ERROR_TITLE, titles, "a deadlock was treated as the benign dedupe race")
        self.assertTrue(self._emission_failures(titles), "the deadlock did not reach the caller's handler")
        self.assertFalse(any(SECOND_SUBSCRIBER in m for m in accepted), accepted)

    def test_expense_hook_survives_the_race(self):
        """delayed_expense_hooks runs bare in the doc hook: the race used to raise out of it."""
        doc = frappe._dict(doctype="Expense Claim", employee="EMP-2505", name="EXP-2505")
        volunteer = frappe._dict(name="VOL-2505", member=self.member.name)
        racing = self._racing_get_job(InvalidJobOperation("gone"), "fin_history_expense_")
        # Mock justified: lookup stand-in for the volunteer link; the enqueue under test is real.
        with patch("frappe.db.get_value", return_value=volunteer), patch(
            "frappe.utils.background_jobs.get_job", racing
        ):
            delayed_expense_hooks.schedule_member_expense_history_update(doc)
        self.assertIn(ERROR_TITLE, self._error_titles())

    def test_control_expense_hook_still_raises_a_deadlock(self):
        doc = frappe._dict(doctype="Expense Claim", employee="EMP-2505", name="EXP-2505")
        volunteer = frappe._dict(name="VOL-2505", member=self.member.name)
        racing = self._racing_get_job(QueryDeadlockError(), "fin_history_expense_")
        # Mock justified: as above.
        with patch("frappe.db.get_value", return_value=volunteer), patch(
            "frappe.utils.background_jobs.get_job", racing
        ):
            with self.assertRaises(QueryDeadlockError):
                delayed_expense_hooks.schedule_member_expense_history_update(doc)
