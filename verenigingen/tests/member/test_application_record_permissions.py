"""#1765: chapter boards review a Membership Application Submission by ITS chapter.

Fixture shortcut, stated: the Pending Review rows here are inserted as an inert Unconfirmed row and
then given `chapter` plus `set_status("Pending Review")` -- the same two writes
application_record._record_confirmation makes -- instead of driving the emailed-link flow. The
permission code under test reads only `chapter` and `status`; the flow itself is covered by
test_application_record.py.
"""

import json

import frappe

from verenigingen.services.chapter.chapter_security import (
    can_user_manage_application_record,
    validate_application_permission_or_throw,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SUBMISSION = "Membership Application Submission"


def _stable(log):
    """message_log entries minus the per-call random exception id."""
    out = []
    for entry in log:
        entry = json.loads(entry) if isinstance(entry, str) else dict(entry)
        entry.pop("__frappe_exc_id", None)
        out.append(entry)
    return out


class TestApplicationRecordPermissions(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self.ensure_test_chapter("TEST Record Perm A")
        self.chapter_b = self.ensure_test_chapter("TEST Record Perm B")
        self.board_a = self.create_test_board_member(self.chapter_a.name, permissions_level="Admin")
        self.app_a = self._application(self.chapter_a.name)
        self.app_b = self._application(self.chapter_b.name)
        self.app_none = self._application(None)
        self.unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

    def _application(self, chapter):
        email = f"rp.{frappe.generate_hash(length=8).lower()}@example.org"
        doc = frappe.get_doc({"doctype": SUBMISSION, "email": email, "source": "Full Form", "payload": "{}"})
        doc.insert()
        self.track_doc(SUBMISSION, doc.name)
        if chapter:
            doc.db_set("chapter", chapter)
        doc.set_status("Pending Review")
        return doc.name

    def test_board_member_sees_only_own_chapter_applications(self):
        with self.as_user(self.board_a.user):
            names = frappe.get_list(SUBMISSION, pluck="name")
            self.assertIn(self.app_a, names)
            self.assertNotIn(self.app_b, names)
            self.assertNotIn(self.app_none, names)
            self.assertTrue(frappe.has_permission(SUBMISSION, "read", doc=self.app_a))
            self.assertFalse(frappe.has_permission(SUBMISSION, "read", doc=self.app_b))
            self.assertFalse(frappe.has_permission(SUBMISSION, "write", doc=self.app_a))

    def test_unassigned_application_admin_only(self):
        self.assertFalse(can_user_manage_application_record(self.app_none, self.board_a.user))
        with self.as_admin_role():
            self.assertTrue(can_user_manage_application_record(self.app_none))
            validate_application_permission_or_throw(self.app_none, "approve")
        with self.as_user(self.board_a.user):
            with self.assertRaises(frappe.PermissionError):
                validate_application_permission_or_throw(self.app_none, "approve")

    def test_board_member_manages_own_chapter_only(self):
        self.assertTrue(can_user_manage_application_record(self.app_a, self.board_a.user))
        self.assertFalse(can_user_manage_application_record(self.app_b, self.board_a.user))

    def test_non_admin_without_a_seat_manages_nothing(self):
        with self.as_role("Verenigingen Member"):
            self.assertFalse(can_user_manage_application_record(self.app_a))

    def test_board_role_without_a_seat_sees_nothing(self):
        """The role grants the DocPerm; only a seat scopes the list (a role-only user must get none)."""
        with self.as_role("Verenigingen Chapter Board Member"):
            self.assertEqual(frappe.get_list(SUBMISSION, pluck="name"), [])
            self.assertFalse(frappe.has_permission(SUBMISSION, "read", doc=self.app_a))

    def _probe(self, fn):
        """(exception type, message, new message_log entries, Error Log delta) for fn() as the board user."""
        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        try:
            fn()
        except Exception as e:
            kind, message = type(e), str(e)
        log = _stable(list(frappe.local.message_log)[before:])
        return kind, message, log, frappe.db.count("Error Log") - errors

    def test_foreign_and_unknown_refused_identically(self):
        """Compared on type, message, message_log delta and Error Log delta, as a seat-holder of A."""

        def validate(name):
            return lambda: validate_application_permission_or_throw(name, "approve")

        # Not compared: frappe.has_permission(doc=<name>, throw=True) / REST GET. Frappe loads the doc
        # first, so an unknown name is DoesNotExistError for EVERY doctype and caller; that is framework
        # behaviour this change does not own (reported, not fixed).
        with self.as_user(self.board_a.user):
            foreign = self._probe(validate(self.app_b))
            unknown = self._probe(validate(self.unknown))
            self.assertEqual(foreign[0], frappe.PermissionError)
            self.assertEqual(foreign, unknown)
            self.assertFalse(frappe.has_permission(SUBMISSION, "read", doc=self.app_b))
            self.assertEqual(frappe.get_list(SUBMISSION, filters={"name": self.app_b}), [])
            self.assertEqual(frappe.get_list(SUBMISSION, filters={"name": self.unknown}), [])
