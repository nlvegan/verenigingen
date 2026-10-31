"""
#1744: process_bulk_account_creation_batch paces its batch chain by counting the
batch's still-open Account Creation Requests. It filtered on "In Progress", a status
the doctype does not have, so a request in Processing was not counted as open and the
next batch was queued at once (the wait loop never slept), defeating the pacing that
exists to stop the queue saturating.

Probe shortcut, stated: the request is put in Processing by the real mark_processing()
and left there (the state a worker that died mid-pipeline leaves behind). Nothing is
committed, so the batch's worker thread (own connection) skips the row as not_found and
cannot move it; only the wait loop, on this connection, sees and counts it. Everything else,
the ACR row, the batch function, the wait loop and the enqueue call, is real except
``frappe.enqueue`` (recorded, not run) and ``time.sleep`` (the 3s wait tick flips the
request to Completed, as the finishing worker would).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase


class TestBatchWaitsForProcessingRequest(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        uid = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="Acr1744",
            last_name=f"Member{uid}",
            email=f"acr1744.{uid}@test.invalid",
            status="Active",
        )

    def _make_requested_acr(self):
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

    def _tracker(self):
        from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
            BulkOperationTracker,
        )

        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=1, batch_size=50, priority="Normal"
        )
        self.track_doc("Bulk Operation Tracker", tracker.name)
        return tracker

    def test_next_batch_waits_while_a_request_is_processing(self):
        request = self._make_requested_acr()
        tracker = self._tracker()
        events = []

        request.mark_processing("test")  # real transition Requested -> Processing

        def fake_sleep(seconds):
            if seconds == 3:  # the wait loop's tick, not the worker's 0.5s throttle
                events.append("wait")
                frappe.db.set_value("Account Creation Request", request.name, "status", "Completed")

        def fake_enqueue(method, **kwargs):
            events.append(("enqueue", frappe.db.get_value("Account Creation Request", request.name, "status")))

        remaining = [
            {"batch_id": "b2", "batch_number": 2, "request_names": ["x"], "request_count": 1}
        ]
        with patch("time.sleep", fake_sleep), patch.object(frappe, "enqueue", fake_enqueue):
            api.process_bulk_account_creation_batch(
                request_names=[request.name],
                batch_id="b1",
                batch_number=1,
                tracker_name=tracker.name,
                remaining_batches=remaining,
            )
        # Precondition: the stand-in really left the request Processing (the wait loop ran
        # against it); the wait is the first event and the enqueue only follows completion.
        self.assertEqual(events, ["wait", ("enqueue", "Completed")])
