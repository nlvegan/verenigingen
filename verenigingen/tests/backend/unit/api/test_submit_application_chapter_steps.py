# -*- coding: utf-8 -*-
"""#1731: submit_application is a Guest endpoint, and both chapter steps need rights a Guest lacks.

Determining the suggested chapter and saving the Pending Chapter Member row therefore run as the
configured system user. That escalation is only safe if the chapter the anonymous caller named is one
the application form could have offered, so the refusal cases are tested here as hard as the happy path.
Every test drives the real submit_application as Guest; nothing is stubbed.
"""

import json

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application import submit_application
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSubmitApplicationChapterStepsAsGuest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _apply_as_guest(self, **overrides):
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
        frappe.set_user("Guest")
        self.addCleanup(frappe.set_user, "Administrator")
        before_messages = len(frappe.local.message_log)
        result = submit_application(**data)
        messages = [m for m in frappe.local.message_log[before_messages:]]
        user_after = frappe.session.user
        frappe.set_user("Administrator")
        self.assertEqual(user_after, "Guest", "the system-user context must not leak past the endpoint")
        self.assertTrue(result["success"], msg=json.dumps(result, default=str))
        member = result["data"]["member_record"]
        self.track_doc("Member", member)
        return member, messages

    def _pending_rows(self, member):
        return frappe.get_all(
            "Chapter Member",
            filters={"member": member},
            fields=["parent", "status", "enabled"],
        )

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

    def test_selected_chapter_gets_a_pending_row_without_an_error(self):
        chapter = self._published_chapter()
        start = frappe.utils.now()
        member, messages = self._apply_as_guest(selected_chapter=chapter.name)

        rows = self._pending_rows(member)
        self.assertEqual([(r.parent, r.status) for r in rows], [(chapter.name, "Pending")], msg=str(rows))
        self.assertFalse(self._setup_errors_since(start))
        self.assertFalse(
            [m for m in messages if "Failed to save chapter membership" in json.dumps(m)],
            msg="a successful application must not carry the red chapter error",
        )

    def test_postal_code_suggestion_works_for_a_guest(self):
        chapter = self._published_chapter(postal_codes="8301-8399")
        member, _messages = self._apply_as_guest(postal_code="8345AB")

        rows = self._pending_rows(member)
        self.assertEqual(
            [(r.parent, r.status) for r in rows],
            [(chapter.name, "Pending")],
            msg="the suggestion step was refused for Guest, so no chapter was suggested",
        )

    def test_unpublished_chapter_is_refused_and_untouched(self):
        chapter = self._published_chapter(published=0)
        before = frappe.db.get_value("Chapter", chapter.name, "modified")
        start = frappe.utils.now()
        member, _messages = self._apply_as_guest(selected_chapter=chapter.name)

        self.assertEqual(self._pending_rows(member), [])
        self.assertFalse(self._setup_errors_since(start), "the refused chapter still reached a chapter step")
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "modified"), before)

    def test_inactive_published_chapter_is_refused(self):
        chapter = self._published_chapter(status="Inactive")
        start = frappe.utils.now()
        member, _messages = self._apply_as_guest(selected_chapter=chapter.name)
        self.assertEqual(self._pending_rows(member), [])
        self.assertFalse(self._setup_errors_since(start), "the refused chapter still reached a chapter step")

    def test_unknown_chapter_name_is_refused(self):
        """Without the guard create_pending_chapter_membership logs 'Chapter Not Found' for this name."""
        start = frappe.utils.now()
        member, _messages = self._apply_as_guest(
            selected_chapter="No Such Chapter " + frappe.generate_hash(length=6)
        )
        self.assertEqual(self._pending_rows(member), [])
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

        member, _messages = self._apply_as_guest(selected_chapter=chapter.name)

        rows_after = frappe.get_all(
            "Chapter Member", filters={"parent": chapter.name}, fields=["member", "status", "enabled"]
        )
        added = [r for r in rows_after if r not in rows_before]
        self.assertEqual([(r.member, r.status) for r in added], [(member, "Pending")])
        self.assertEqual([r for r in rows_before if r not in rows_after], [])
        self.assertEqual(frappe.db.get_value("Chapter", other_chapter.name, "modified"), other_before)
