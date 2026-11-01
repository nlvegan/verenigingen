"""#1765 task 9: the application review endpoints keep the protections the member-keyed ones had.

The removed approve/reject endpoints sanitised the identifier, and logged a security event for an unknown
target. approve_application / reject_application / request_more_info did neither, and a refusal logged
nothing. Driven through the real endpoints; the audit trail is read from the API Audit Log rows they write.
The refusal event says nothing about whether the application exists: an unknown and a foreign name must
leave the same trace (the oracle tests compare the caller's side, this is the server side).
"""

import json

import frappe

from verenigingen.api.membership_application_review import (
    approve_application,
    reject_application,
    request_more_info,
)
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase

ENDPOINTS = {
    "approve": lambda name: approve_application(name, create_invoice=False),
    "reject": lambda name: reject_application(name, reason="No"),
    "request_more_info": lambda name: request_more_info(name, "Please tell us more"),
}


class TestApplicationReviewSecurityEvents(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.other_chapter = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    def _events(self, event_type, containing):
        rows = frappe.get_all(
            "API Audit Log",
            filters={"event_type": event_type, "details": ["like", f"%{containing}%"]},
            fields=["severity", "details"],
        )
        return [(row.severity, json.loads(row.details).get("message", "")) for row in rows]

    def _call_endpoint_as(self, user, label, name):
        with self.as_user(user):
            with self.assertRaises(Exception) as caught:
                ENDPOINTS[label](name)
        return caught.exception

    def test_a_refusal_is_audited_and_unknown_and_foreign_leave_the_same_trace(self):
        self.email = self._fresh_applicant_email()
        foreign = self._stage_and_confirm(selected_chapter=self.other_chapter.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"
        for label in ENDPOINTS:
            with self.subTest(endpoint=label):
                traces = {}
                for kind, name in (("foreign", foreign), ("unknown", unknown)):
                    error = self._call_endpoint_as(self.board.user, label, name)
                    self.assertIsInstance(error, frappe.PermissionError, (kind, error))
                    events = self._events("unauthorized_access_attempt", name)
                    self.assertTrue(events, f"{label}: a refused {kind} application left no security event")
                    traces[kind] = {(sev, msg.replace(name, "<name>")) for sev, msg in events}
                self.assertEqual(traces["foreign"], traces["unknown"], "the audit trail must not reveal existence")

    def test_an_unknown_target_reached_by_an_administrator_is_audited(self):
        for label in ENDPOINTS:
            with self.subTest(endpoint=label):
                unknown = f"nonexistent-{frappe.generate_hash(length=8)}"
                error = self._call_endpoint_as(self.admin_user.email, label, unknown)
                self.assertIsInstance(error, frappe.DoesNotExistError, error)
                events = self._events("unauthorized_access_attempt", unknown)
                self.assertTrue(events, f"{label}: an unknown application left no security event")
                self.assertTrue(any(sev == "error" and "non-existent" in msg for sev, msg in events), events)

    def test_the_identifier_is_sanitised_before_anything_uses_it(self):
        markup = f"<b>x{frappe.generate_hash(length=6)}</b>"
        for label in ENDPOINTS:
            with self.subTest(endpoint=label):
                error = self._call_endpoint_as(self.admin_user.email, label, markup)
                self.assertNotIn("<b>", str(error), "the name reached the error text unescaped")
                self.assertIn("&lt;b&gt;", str(error))

    def test_an_overlong_identifier_is_refused_as_invalid_input(self):
        for label in ENDPOINTS:
            with self.subTest(endpoint=label):
                error = self._call_endpoint_as(self.admin_user.email, label, "a" * 300)
                self.assertIsInstance(error, frappe.ValidationError)
                self.assertNotIsInstance(error, frappe.DoesNotExistError, "the length was never checked")
