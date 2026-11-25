"""#3186 sites 2 and 3: what a dedupe enqueue race means when BOTH attempts race (maintainer ruling 2026-11-25).

* Contribution Amendment Request: the row must not stay "Queued" when the sync job was not
  queued; it becomes "Failed", which the existing ``in ["Not Started", "Failed"]`` guard retries.
* Ponto webhook: a link whose executed-payment job was not queued is a FAILED link (rolled back to
  its savepoint, listed in ``failed_links``), never ``payment_entries_queued``.

Injection boundary: the same as the site-1 tests, ``frappe.utils.background_jobs.get_job`` (the
rq lookup frappe.enqueue does for ``deduplicate=True``); the doc, the hook, the savepoint and the
enqueue call are real. The control tests let ``get_job`` race ONCE (the retry then succeeds).
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.events.test_payment_history_drain_dedupe_race_3186 import _FinishedJobVanishing3186
from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.ponto.api import webhook_handlers

ERROR_TITLE = "Event dedupe enqueue race (InvalidJobOperation)"


class TestRemainingDedupeRaceSites3186(VereningingenTestCase):
    def _race_get_job(self, job_id, attempts):
        """Context manager: ``get_job`` races for ``job_id`` the first ``attempts`` times, then behaves."""
        real_get_job = frappe.utils.background_jobs.get_job
        fired = []

        def get_job(requested):
            if requested == job_id and len(fired) < attempts:
                fired.append(requested)
                return _FinishedJobVanishing3186()
            return real_get_job(requested)

        # Mock justified: the race is a concurrent actor deleting the job hash; it cannot be
        # produced on demand, so the rq boundary is made to behave as it does mid-race.
        self.fired = fired
        return patch("frappe.utils.background_jobs.get_job", get_job)

    def tearDown(self):
        # A successful enqueue_after_commit only REGISTERS a callback. Drop it BEFORE the harness
        # teardown, whose drains commit: a cleanup registered with addCleanup runs after them and
        # would let that commit push a real job onto the site's queue.
        frappe.db.after_commit.reset()
        super().tearDown()

    # ------------------------------------------------------------------ site 2: amendment

    def _applied_amendment(self):
        member = self.create_test_member(
            first_name="Amend",
            last_name="Race",
            email=f"amend.race.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        membership_type = self.create_test_membership_type(
            membership_type_name=f"AmendRace{frappe.generate_hash(length=6)}"
        )
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.submit()
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.0,
                "reason": "dedupe race 3186",
                "effective_date": add_days(today(), 30),
                "status": "Draft",
            }
        )
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        amendment.db_set("status", "Approved")
        amendment.reload()
        return amendment

    def _apply(self, amendment):
        amendment.status = "Applied"
        # Mock justified (#3210): the controller's "RQ Job" pre-check lists every job on the shared
        # Redis and itself raises InvalidJobOperation when an unrelated worker's job vanishes
        # mid-listing (seen ~2 in 25 runs). That is not what is under test; no job of this
        # amendment is queued, which is what the stub says.
        with patch("frappe.core.doctype.rq_job.rq_job.RQJob.get_list", return_value=[]):
            amendment.save()
        return frappe.db.get_value("Contribution Amendment Request", amendment.name, "mollie_sync_status")

    def test_amendment_not_queued_after_two_races_is_failed_not_queued(self):
        amendment = self._applied_amendment()
        self.expectErrorLog(ERROR_TITLE)
        with self._race_get_job(f"mollie_sync_{amendment.name}", attempts=2):
            status = self._apply(amendment)
        self.assertEqual(len(self.fired), 2, "both attempts must have raced")
        self.assertEqual(status, "Failed", "a lost sync job must not leave the row 'Queued'")

    def test_amendment_failed_by_a_lost_job_is_retried_by_the_next_applied_save(self):
        """The point of 'Failed': the existing guard lets a later save queue the sync again."""
        amendment = self._applied_amendment()
        self.expectErrorLog(ERROR_TITLE)
        with self._race_get_job(f"mollie_sync_{amendment.name}", attempts=2):
            self.assertEqual(self._apply(amendment), "Failed")
        amendment.reload()
        amendment.db_set("status", "Approved")
        amendment.reload()
        self.assertEqual(self._apply(amendment), "Queued")

    def test_control_amendment_single_race_is_retried_and_stays_queued(self):
        amendment = self._applied_amendment()
        self.expectErrorLog(ERROR_TITLE)
        with self._race_get_job(f"mollie_sync_{amendment.name}", attempts=1):
            status = self._apply(amendment)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(status, "Queued", "the retry succeeded, so the job IS queued")

    def test_control_amendment_without_a_race_is_queued(self):
        amendment = self._applied_amendment()
        self.assertEqual(self._apply(amendment), "Queued")

    # ------------------------------------------------------------------ site 3: ponto webhook

    def _executed_link(self):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = 25
        link.currency = "EUR"
        link.description = "dedupe race 3186"
        link.creditor_name = "Org"
        link.creditor_iban = TestIBAN.ABN_AMRO_1
        link.status = "Pending Authorization"
        link.ponto_request_id = f"race-3186-{frappe.generate_hash(length=8)}"
        link.redirect_link = "https://example.test/x"
        link.insert()
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def _webhook_executed(self, link):
        result = webhook_handlers._update_payment_link_status(
            request_id=link.ponto_request_id, new_status="executed"
        )
        return result, frappe.db.get_value("Ponto Payment Link", link.name, "status")

    def test_ponto_not_queued_after_two_races_is_a_failed_link_and_rolled_back(self):
        link = self._executed_link()
        self.expectErrorLog(ERROR_TITLE)
        self.expectErrorLog(f"Payment link webhook status update failed: {link.name}")
        with self._race_get_job(f"ponto_executed_{link.name}", attempts=2):
            result, status = self._webhook_executed(link)
        self.assertEqual(len(self.fired), 2, "both attempts must have raced")
        self.assertEqual(result["failed_links"], [link.name])
        self.assertIsNone(result["payment_entries_queued"], "a job that was not queued is not 'queued'")
        self.assertEqual(status, "Pending Authorization", "the failed link must be rolled back to its savepoint")

    def test_control_ponto_single_race_is_retried_and_reported_queued(self):
        link = self._executed_link()
        self.expectErrorLog(ERROR_TITLE)
        with self._race_get_job(f"ponto_executed_{link.name}", attempts=1):
            result, status = self._webhook_executed(link)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(result["payment_entries_queued"], [link.name])
        self.assertIsNone(result["failed_links"])
        self.assertEqual(status, "Executed")

    def test_control_ponto_without_a_race_is_reported_queued(self):
        link = self._executed_link()
        result, status = self._webhook_executed(link)
        self.assertEqual(result["payment_entries_queued"], [link.name])
        self.assertIsNone(result["failed_links"])
        self.assertEqual(status, "Executed")

    def test_ponto_failed_link_does_not_stop_the_next_link(self):
        """Two links under one request id: the raced one fails, the other is still queued."""
        first = self._executed_link()
        second = self._executed_link()
        second.db_set("ponto_request_id", first.ponto_request_id)
        self.expectErrorLog(ERROR_TITLE)
        self.expectErrorLog(f"Payment link webhook status update failed: {first.name}")
        with self._race_get_job(f"ponto_executed_{first.name}", attempts=2):
            result, _ = self._webhook_executed(first)
        self.assertEqual(result["failed_links"], [first.name])
        self.assertEqual(result["payment_entries_queued"], [second.name])
