"""#2653: the volunteer form must not report "received" over a Volunteer row that is gone.

``submit_application``'s ordinary-failure path calls ``frappe.db.rollback()``, which also removes
the Volunteer inserted earlier in the same request. ``submit_volunteer_application`` used to commit
and answer ``success: True`` anyway. The decision is server-side: the response must be a failure.
The fault is injected below ``submit_application``'s own try (``parse_application_data``), so the
real rollback path runs; only the exception is synthetic.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerFormFailureSignal2653(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._uniq = frappe.generate_hash(length=8).lower()
        self.expectErrorLog(
            "Volunteer Application",
            "ordinary failure",
            "RuntimeError",
            "Application Submission Error",
            "submit_application",
        )

    def _vol2653_payload(self, email=None):
        return {
            "first_name": "Ria",
            "last_name": "Vermeer",
            "email": email or f"ria.2653.{self._uniq}@example.com",
            "birth_date": "1990-05-01",
            "motivation": "I care about animals.",
            "time_commitment": "6-10",
            "become_member": 1,
        }

    def _vol2653_submit_with_membership_fault(self, payload):
        from verenigingen.api import membership_application
        from verenigingen.api.volunteer_application import submit_volunteer_application

        with self.as_user("Guest"), patch.object(
            membership_application, "parse_application_data", side_effect=RuntimeError("ordinary failure")
        ):
            result = submit_volunteer_application(**payload)
        name = (result.get("data") or {}).get("volunteer_name")
        if name and frappe.db.exists("Volunteer", name):
            self.track_doc("Volunteer", name)
        return result

    def test_a_rolled_back_new_volunteer_is_reported_as_a_failure(self):
        payload = self._vol2653_payload()
        result = self._vol2653_submit_with_membership_fault(payload)

        self.assertFalse(frappe.db.exists("Volunteer", {"email": payload["email"]}))
        self.assertFalse(result["success"], f"reported success over a vanished Volunteer: {result}")
        self.assertEqual(result["error"]["code"], "VOLUNTEER_APPLICATION_NOT_SAVED")
        self.assertNotIn("application_id", (result.get("data") or {}))

    def test_a_rolled_back_reactivation_is_reported_as_a_failure(self):
        """The rollback reverts the in-place reactivation to its committed Inactive state."""
        existing = self.create_test_volunteer()
        email = f"ria.2653r.{self._uniq}@example.com"
        frappe.db.set_value("Volunteer", existing.name, {"email": email, "status": "Inactive"})
        frappe.db.commit()

        result = self._vol2653_submit_with_membership_fault(self._vol2653_payload(email))

        self.assertEqual(frappe.db.get_value("Volunteer", existing.name, "status"), "Inactive")
        self.assertFalse(result["success"], f"reported success over a reverted reactivation: {result}")
        self.assertEqual(result["error"]["code"], "VOLUNTEER_APPLICATION_NOT_SAVED")

    def test_a_membership_validation_failure_keeps_the_volunteer_and_says_so(self):
        """CONTROL: a failure that does NOT roll back (no address) still keeps the Volunteer."""
        from verenigingen.api.volunteer_application import submit_volunteer_application

        payload = self._vol2653_payload()
        with self.as_user("Guest"):
            result = submit_volunteer_application(**payload)
        name = result["data"]["volunteer_name"]
        self.track_doc("Volunteer", name)

        self.assertTrue(result["success"], result)
        self.assertTrue(frappe.db.exists("Volunteer", name))
        self.assertTrue(result["data"].get("membership_application_error"))
