# -*- coding: utf-8 -*-
"""#1731: the chapter suggestion runs for an anonymous applicant, and needs rights a Guest lacks.

Since #1765 the suggestion is made when the applicant CONFIRMS the emailed link (the application is a
Membership Application Submission until approval) and is stored on the submission; no Chapter Member row
is written. The suggestion still runs as the configured system user, which is only safe if the chapter the
anonymous caller named is one the application form could have offered, so the refusal cases are tested
here as hard as the happy path. Every test drives the real endpoints as Guest; nothing is stubbed.
"""

import json
import random

import frappe
from frappe.utils import add_days, today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api import short_application as sa
from verenigingen.api.membership_application import submit_application
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

SUBMISSION = "Membership Application Submission"


class TestSubmitApplicationChapterStepsAsGuest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _apply_as_guest(self, **overrides):
        """Submit and confirm as Guest; return (submission name, chapter suggested on it, messages)."""
        data = {
            "first_name": "Guest",
            "last_name": f"Applicant{frappe.generate_hash(length=6)}",
            "email": f"guest-{frappe.generate_hash(length=8)}@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type,
        }
        data.update(overrides)
        self._previous_request = getattr(frappe.local, "request", None)
        self.addCleanup(setattr, frappe.local, "request", self._previous_request)
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user("Guest")
        result = submit_application(**data)
        self.assertTrue(result["success"], msg=json.dumps(result, default=str))
        name = frappe.get_all(SUBMISSION, {"email": data["email"].lower()}, pluck="name")[0]
        self.track_doc(SUBMISSION, name)
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())
        frappe.local.request_ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        before_messages = len(frappe.local.message_log)
        confirmed = sa.confirm_short_application(name, token)
        messages = list(frappe.local.message_log[before_messages:])
        user_after = frappe.session.user
        frappe.set_user("Administrator")
        self.assertEqual(user_after, "Guest", "the system-user context must not leak past the endpoint")
        self.assertTrue(confirmed["success"], msg=json.dumps(confirmed, default=str))
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        return name, frappe.db.get_value(SUBMISSION, name, "chapter"), messages

    def _setup_errors_since(self, start):
        return frappe.get_all(
            "Error Log",
            or_filters=[
                ["method", "like", "Chapter %"],
                ["error", "like", "Chapter Setup Error%"],
                ["error", "like", "Chapter Not Found%"],
            ],
            filters={"creation": [">=", start]},
            pluck="name",
        )

    def _published_chapter(self, **kwargs):
        kwargs.setdefault("published", 1)
        return self.create_test_chapter(**kwargs)

    def test_selected_chapter_is_suggested_without_an_error_or_a_roster_row(self):
        chapter = self._published_chapter()
        rows_before = frappe.db.count("Chapter Member", {"parent": chapter.name})
        start = frappe.utils.now()
        _name, suggested, messages = self._apply_as_guest(selected_chapter=chapter.name)

        self.assertEqual(suggested, chapter.name)
        self.assertEqual(frappe.db.count("Chapter Member", {"parent": chapter.name}), rows_before)
        self.assertFalse(self._setup_errors_since(start))
        self.assertEqual(messages, [], msg="a successful confirmation must not carry a chapter message")

    def test_postal_code_suggestion_works_for_a_guest(self):
        chapter = self._published_chapter(postal_codes="8301-8399")
        _name, suggested, _messages = self._apply_as_guest(postal_code="8345AB")

        self.assertEqual(
            suggested, chapter.name, "the suggestion step was refused for Guest, so no chapter was suggested"
        )

    def test_unpublished_chapter_is_refused_and_untouched(self):
        chapter = self._published_chapter(published=0)
        before = frappe.db.get_value("Chapter", chapter.name, "modified")
        start = frappe.utils.now()
        _name, suggested, _messages = self._apply_as_guest(selected_chapter=chapter.name)

        self.assertIsNone(suggested)
        self.assertFalse(self._setup_errors_since(start), "the refused chapter still reached a chapter step")
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "modified"), before)

    def test_inactive_published_chapter_is_refused(self):
        chapter = self._published_chapter(status="Inactive")
        start = frappe.utils.now()
        _name, suggested, _messages = self._apply_as_guest(selected_chapter=chapter.name)
        self.assertIsNone(suggested)
        self.assertFalse(self._setup_errors_since(start), "the refused chapter still reached a chapter step")

    def test_unknown_chapter_name_is_refused(self):
        start = frappe.utils.now()
        _name, suggested, _messages = self._apply_as_guest(
            selected_chapter="No Such Chapter " + frappe.generate_hash(length=6)
        )
        self.assertIsNone(suggested)
        self.assertFalse(self._setup_errors_since(start), "the unknown name still reached a chapter step")

    def test_other_members_and_chapters_are_left_alone(self):
        chapter = self._published_chapter()
        other_chapter = self._published_chapter()
        bystander = self.create_test_member(
            first_name="Bystander",
            last_name=f"Row{frappe.generate_hash(length=6)}",
            email=f"bystander-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
            chapter=chapter.name,
        )
        rows_before = frappe.get_all(
            "Chapter Member", filters={"parent": chapter.name}, fields=["member", "status", "enabled"]
        )
        self.assertTrue(any(r.member == bystander.name for r in rows_before), "control needs a real row")
        other_before = frappe.db.get_value("Chapter", other_chapter.name, "modified")
        chapter_before = frappe.db.get_value("Chapter", chapter.name, "modified")

        _name, suggested, _messages = self._apply_as_guest(selected_chapter=chapter.name)

        self.assertEqual(suggested, chapter.name)
        rows_after = frappe.get_all(
            "Chapter Member", filters={"parent": chapter.name}, fields=["member", "status", "enabled"]
        )
        self.assertEqual(rows_after, rows_before, "confirming writes no roster row")
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "modified"), chapter_before)
        self.assertEqual(frappe.db.get_value("Chapter", other_chapter.name, "modified"), other_before)
