"""Issue 2989: the lifecycle service's cancellation paths used names that do not exist.

`_handle_cancellation` read `mandate_doc.cancellation_date` (the SEPA Mandate field is
`cancelled_date`), and `process_mandate_cancellation` called
`send_mandate_status_notification` (the notifier's method is
`send_mandate_cancelled_notification`). Both failures were swallowed into the result, so
the member-side link was never updated.

These tests drive REAL persisted mandates (the Mock-based sibling suite hides both
defects: a Mock grows any attribute). Only the email-send boundary is stubbed.
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    SEPAMandateLifecycleService,
)

SEND_BOUNDARY = "verenigingen.services.communication.compatibility.send_sepa_email"


class TestSEPAMandateCancellationFieldNames2989(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = SEPAMandateLifecycleService()
        self.member = self.create_test_member()
        self.mandate = self.create_test_sepa_mandate(member=self.member.name, status="Active")

    def _link_row_2989(self):
        return frappe.db.get_value(
            "Member SEPA Mandate Link",
            {"parent": self.member.name, "sepa_mandate": self.mandate.name},
            ["status", "is_current"],
            as_dict=True,
        )

    def test_status_transition_to_cancelled_completes_and_updates_member_link(self):
        before = self._link_row_2989()
        self.assertEqual(before.status, "Active", "control: the link starts Active")

        self.mandate.status = "Cancelled"
        result = self.service.handle_status_transition(self.mandate, "Active")

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(str(self.mandate.cancelled_date), today())
        after = self._link_row_2989()
        self.assertEqual(after.status, "Cancelled")
        self.assertEqual(after.is_current, 0)

    def test_status_transition_keeps_an_existing_cancelled_date(self):
        """Control: the 'only if not already set' guard must not overwrite a real date."""
        self.mandate.status = "Cancelled"
        self.mandate.cancelled_date = "2020-01-31"
        result = self.service.handle_status_transition(self.mandate, "Active")
        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(str(getdate(self.mandate.cancelled_date)), "2020-01-31")

    def test_process_cancellation_sends_the_real_cancelled_notification(self):
        with patch(SEND_BOUNDARY) as send:
            result = self.service.process_mandate_cancellation(self.mandate, "Member request")

        self.assertTrue(result["success"], result["errors"])
        self.assertFalse(
            [w for w in result["warnings"] if "Failed to send notification" in w], result["warnings"]
        )
        self.assertIn("status_change", result["notifications_sent"])
        self.assertEqual(send.call_count, 1)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["template"], "sepa_mandate_cancelled")
        self.assertEqual(kwargs["recipients"], [self.member.email])
        self.assertEqual(kwargs["context"]["cancellation_reason"], "Member request")
        self.assertEqual(str(self.mandate.cancelled_date), today())
        self.assertEqual(self._link_row_2989().status, "Cancelled")

    def test_real_save_to_cancelled_sends_once_and_updates_link_2989(self):
        """Regression pin for the production path: save() runs handle_mandate_update,
        which sends the cancelled email and updates the member link."""
        self.mandate.reload()
        self.mandate.status = "Cancelled"
        with patch(SEND_BOUNDARY) as send:
            self.mandate.save()
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs["template"], "sepa_mandate_cancelled")
            self.assertEqual(self._link_row_2989().status, "Cancelled")
            self.mandate.reload()
            self.mandate.save()
            self.assertEqual(send.call_count, 1, "a re-save must not send again")
