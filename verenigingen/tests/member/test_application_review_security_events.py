"""#1765 task 9: the application review endpoints keep the protections the member-keyed ones had.

The removed approve/reject endpoints sanitised the identifier, and logged a security event for an unknown
target. approve_application / reject_application / request_more_info did neither, and a refusal logged
nothing. Driven through the real endpoints; the audit trail is read from the API Audit Log rows they write.
The refusal event says nothing about whether the application exists: an unknown and a foreign name must
leave the same trace (the oracle tests compare the caller's side, this is the server side).
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.api.membership_application_review import (
    approve_application,
    get_application_changes,
    reject_application,
    request_more_info,
)
from verenigingen.services.chapter.chapter_security import store_application_security_event
from verenigingen.services.member.validation.member_duplicate_detection_service import (
    check_duplicate_for_application,
)
from verenigingen.api.chapter_dashboard_api import quick_approve_application
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.utils.security.audit_logging import SEPAAuditLogger

ENDPOINTS = {
    "approve": lambda name: approve_application(name, create_invoice=False),
    "reject": lambda name: reject_application(name, reason="No"),
    "request_more_info": lambda name: request_more_info(name, "Please tell us more"),
}

# The read-only endpoints refuse through the same permission check, so they sanitise first as well (S1).
READ_ENDPOINTS = {
    "get_application_changes": lambda name: get_application_changes(name),
    "check_duplicate_for_application": lambda name: check_duplicate_for_application(name),
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

    def _call_read_endpoint_as(self, user, label, name):
        with self.as_user(user):
            with self.assertRaises(Exception) as caught:
                READ_ENDPOINTS[label](name)
        return caught.exception

    def test_read_endpoints_sanitise_the_identifier_before_the_refusal_event(self):
        """S1: the refusal event message carries the name, so an unsanitised name reached the stored event."""
        markup = f"<b>x{frappe.generate_hash(length=6)}</b>"
        for label in READ_ENDPOINTS:
            with self.subTest(endpoint=label):
                error = self._call_read_endpoint_as(self.board.user, label, markup)
                self.assertIsInstance(error, frappe.PermissionError, error)
                self.assertTrue(self._events("unauthorized_access_attempt", "&lt;b&gt;x"), "no sanitised event")
                self.assertFalse(self._events("unauthorized_access_attempt", "<b>x"), "raw markup reached the event")

    def test_the_dashboard_approval_sanitises_the_identifier_too(self):
        """quick_approve_application (handle_api_error: a refusal comes back as a failed result, not a raise)
        reached the refusal event with the raw name just like the read endpoints."""
        markup = f"<b>x{frappe.generate_hash(length=6)}</b>"
        with self.as_user(self.board.user):
            result = quick_approve_application(markup)
        self.assertFalse(result.get("success"), result)
        self.assertTrue(self._events("unauthorized_access_attempt", "&lt;b&gt;x"), "no sanitised event")
        self.assertFalse(self._events("unauthorized_access_attempt", "<b>x"), "raw markup reached the event")

    def test_read_endpoints_refuse_an_overlong_identifier_as_invalid_input(self):
        for label in READ_ENDPOINTS:
            with self.subTest(endpoint=label):
                before = frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"})
                error = self._call_read_endpoint_as(self.board.user, label, "a" * 300)
                self.assertIsInstance(error, frappe.ValidationError, error)
                self.assertNotIsInstance(error, frappe.PermissionError)
                self.assertEqual(
                    frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"}),
                    before,
                    "an overlong name must not reach a security event",
                )

    def test_read_endpoints_leave_the_same_trace_for_an_unknown_and_a_foreign_application(self):
        self.email = self._fresh_applicant_email()
        foreign = self._stage_and_confirm(selected_chapter=self.other_chapter.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"
        for label in READ_ENDPOINTS:
            with self.subTest(endpoint=label):
                traces = {}
                for kind, name in (("foreign", foreign), ("unknown", unknown)):
                    error = self._call_read_endpoint_as(self.board.user, label, name)
                    self.assertIsInstance(error, frappe.PermissionError, (kind, error))
                    events = self._events("unauthorized_access_attempt", name)
                    self.assertTrue(events, f"{label}: a refused {kind} application left no event")
                    traces[kind] = {(sev, msg.replace(name, "<name>")) for sev, msg in events}
                self.assertEqual(traces["foreign"], traces["unknown"])

    # -- persistence: the events must outlive the request's rollback ---------------------------------

    def _refuse_with_the_queue_captured(self, names):
        """Refuse each name as the board user with frappe.enqueue captured (it stands in for the Redis
        push: a boundary the test cannot run without a worker); returns the captured calls."""
        captured = []

        def capture(method, **kwargs):
            captured.append((method, kwargs))

        # Mock justified: Infrastructure - the RQ queue (CI has no worker)
        with patch("frappe.enqueue", capture):
            for name in names:
                self._call_endpoint_as(self.board.user, "approve", name)
        return captured

    def test_refusals_survive_the_request_rollback(self):
        """Frappe rolls the request back on the PermissionError (frappe/app.py), so a row written inline is
        lost: the refusal must be one job per call, pushed outside the transaction, that a worker then stores."""
        self.email = self._fresh_applicant_email()
        foreign = self._stage_and_confirm(selected_chapter=self.other_chapter.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"
        before = frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"})

        captured = self._refuse_with_the_queue_captured([foreign, unknown])

        self.assertEqual(len(captured), 2, "one enqueue per refusal, identical for unknown and foreign")
        for method, kwargs in captured:
            self.assertEqual(method, "verenigingen.services.chapter.chapter_security.store_application_security_event")
            self.assertEqual(kwargs["queue"], "short")
            self.assertFalse(kwargs.get("enqueue_after_commit"), "an after-commit push is dropped by the rollback")
            self.assertEqual(set(kwargs), {"queue", "now", "event_type", "severity", "message"})
        self.assertEqual(
            captured[0][1]["message"].replace(foreign, "<name>"), captured[1][1]["message"].replace(unknown, "<name>")
        )

        frappe.db.rollback()  # what the request handler does on the PermissionError
        self.assertEqual(
            frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"}),
            before,
            "control: nothing was written inline, so nothing depends on the request's transaction",
        )
        for method, kwargs in captured:  # the worker
            store_application_security_event(kwargs["event_type"], kwargs["severity"], kwargs["message"])
        self.assertEqual(
            frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"}) - before,
            2,
            "one row per refusal",
        )

    def test_a_burst_of_refusals_raises_the_security_alert(self):
        """Through the real endpoint: four refusals inside the window (threshold: 3 unauthorized attempts
        in 5 minutes) reach the alert path, because the job checks the thresholds."""
        self.email = self._fresh_applicant_email()
        foreign = self._stage_and_confirm(selected_chapter=self.other_chapter.name)
        suspicious = {"event_type": "suspicious_activity"}
        before = frappe.db.count("API Audit Log", suspicious)
        # Mock justified: External Service - the alert mail to administrators
        with patch.object(SEPAAuditLogger, "_send_security_notification") as notify:
            for _ in range(4):
                self._call_endpoint_as(self.board.user, "approve", foreign)
        self.assertTrue(notify.called, "four refusals inside the window must reach the alert path")
        self.assertGreater(frappe.db.count("API Audit Log", suspicious), before)
